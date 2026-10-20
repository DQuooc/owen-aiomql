"""H1: repeated exposure helpers and tracker ticks, without a real MT5 SDK."""

import asyncio
from enum import IntEnum
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch

from test_execution_callers import example_trackers
from test_order_check_contract import FakeMT5Response, FakeTradeRequest, Order, exceptions
from test_order_send_safety import MetaTrader, OpenPosition, reset_sdk, sdk, trackers


class OrderType(IntEnum):
    BUY = 0
    SELL = 1
    BUY_STOP = 4
    SELL_STOP = 5

    @property
    def opposite(self):
        return self.SELL if self == self.BUY else self.BUY

    @property
    def is_long(self):
        return self in (self.BUY, self.BUY_STOP)


class PartialExposureSafetyTests(unittest.IsolatedAsyncioTestCase):
    methods = ("hedge_position", "stack_position", "hedge_order", "stack_order")

    def setUp(self):
        reset_sdk()
        self.mt5 = MetaTrader()
        self.mt5.initialize = AsyncMock(return_value=True)
        self.mt5.login = AsyncMock(return_value=True)
        self.enterContext(patch.object(Order, "mt5", self.mt5, create=True))
        self.enterContext(patch.object(FakeTradeRequest, "__match_args__",
                                      (*FakeTradeRequest.__match_args__, "action")))
        module = sys.modules[OpenPosition.__module__]
        self.enterContext(patch.object(module, "OrderType", OrderType))
        self.enterContext(patch.object(module.TradeRetcode, "REJECT", 10006, create=True))
        self.config = SimpleNamespace(state={})
        self.positions = SimpleNamespace(get_position_by_ticket=AsyncMock())
        self.enterContext(patch.object(OpenPosition, "config", self.config, create=True))
        self.enterContext(patch.object(OpenPosition, "positions", self.positions, create=True))
        self.symbol = SimpleNamespace(name="EURUSD", info_tick=AsyncMock(
            return_value=SimpleNamespace(ask=1.25, bid=1.24)))
        self.broker_position = SimpleNamespace(ticket=123, symbol="EURUSD", volume=0.1,
                                               type=OrderType.BUY, profit=-3)
        self.child_position = SimpleNamespace(ticket=456, symbol="EURUSD", volume=0.1,
                                              type=OrderType.SELL, profit=0)
        self.positions.get_position_by_ticket.side_effect = (
            lambda *, ticket: self.broker_position if ticket == 123 else self.child_position)

    def position(self):
        self.config.state.clear()  # Each subtest represents an independent tracked position.
        return OpenPosition(symbol=self.symbol, ticket=123, position=self.broker_position,
                            auto_track_closed=False)

    def response(self, retcode=10010, volume=0.04):
        return FakeMT5Response(retcode=retcode, volume=volume, order=456, deal=789,
                               comment="offline", request=SimpleNamespace(volume=0.1))

    async def invoke(self, pos, method, params=None):
        params = {"volume": 0.1} if params is None else params
        if method.endswith("_order"):
            return await getattr(pos, method)(price=1.25, order_params=params)
        return await getattr(pos, method)(order_params=params)

    def attempt(self, pos, method):
        return getattr(pos, "unresolved_hedge" if method.startswith("hedge") else "unresolved_stack")

    def add_hedge_tracker(self, pos):
        trackers.PositionTracker(pos, example_trackers.hedge_position,
                                 function_params={"order_params": {"volume": 0.1}})

    async def test_done_preserves_existing_and_new_bookkeeping_for_all_helpers(self):
        for method in self.methods:
            with self.subTest(method=method):
                sdk.order_send.reset_mock()
                sdk.order_send.return_value = self.response(retcode=10009, volume=0.1)
                pos = self.position()
                sentinel = object()
                pos.hedges[11] = pos.stacks[22] = sentinel
                params = {"volume": 0.1, "comment": "explicit intent"}
                ok, result = await self.invoke(pos, method, params)
                self.assertTrue(ok)
                self.assertEqual(result.volume, 0.1)
                self.assertIsNone(self.attempt(pos, method))
                self.assertIs(pos.hedges[11], sentinel)
                self.assertIs(pos.stacks[22], sentinel)
                self.assertEqual(params, {"volume": 0.1, "comment": "explicit intent"})
                is_hedge = method.startswith("hedge")
                self.assertTrue(pos.is_hedged if is_hedge else pos.is_stacked)
                if method.endswith("_order"):
                    pending = pos.pending_orders[456]
                    self.assertIs(pending.order, result)
                    self.assertEqual((pending.is_hedge, pending.is_stack), (is_hedge, not is_hedge))
                else:
                    child = (pos.hedges if is_hedge else pos.stacks)[456]
                    self.assertIs(child.position, self.child_position)
                    self.assertIs(child.hedge if is_hedge else child.stack, pos)
                    self.assertIs(self.config.state["tracked_positions"][456], child)
                sdk.order_send.assert_called_once()

    async def test_complete_hedge_is_not_repeated_by_tracker(self):
        sdk.order_send.return_value = self.response(retcode=10009, volume=0.1)
        pos = self.position()
        self.add_hedge_tracker(pos)
        for _ in range(3):
            await pos.track()
        self.assertTrue(pos.is_hedged)
        self.assertIn(456, pos.hedges)
        sdk.order_send.assert_called_once()

    async def test_three_tracker_ticks_keep_first_partial_and_never_send_residual(self):
        sdk.order_send.side_effect = [self.response(), self.response()]
        pos = self.position()
        self.add_hedge_tracker(pos)
        for _ in range(3):
            await pos.track()
        sdk.order_send.assert_called_once()
        self.assertEqual(sdk.order_send.call_args.args[0]["volume"], 0.1)
        self.assertFalse(pos.is_hedged)
        self.assertEqual(pos.hedges, {})
        self.assertEqual(pos.position.volume, 0.1)
        self.assertEqual(pos.unresolved_hedge.request["volume"], 0.1)
        self.assertEqual((pos.unresolved_hedge.result.retcode, pos.unresolved_hedge.result.volume),
                         (10010, 0.04))

    async def test_all_partial_helpers_block_repeated_calls_and_market_pending_fallback(self):
        for method in self.methods:
            for reported_volume in (0.04, 0.0):
                with self.subTest(method=method, volume=reported_volume):
                    sdk.order_send.reset_mock()
                    sdk.order_send.return_value = self.response(volume=reported_volume)
                    pos = self.position()
                    ok, result = await self.invoke(pos, method)
                    self.assertFalse(ok)
                    attempt = self.attempt(pos, method)
                    self.assertIs(attempt.result, result)
                    other = method.replace("position", "order") if method.endswith("position") else method.replace("order", "position")
                    for next_method in (method, other, method):
                        self.assertEqual(await self.invoke(pos, next_method), (False, None))
                    sdk.order_send.assert_called_once()
                    self.assertIs(self.attempt(pos, method), attempt)
                    self.assertEqual(attempt.result.volume, reported_volume)
                    self.assertEqual((pos.hedges, pos.stacks, pos.pending_orders), ({}, {}, {}))

    async def test_ambiguous_outcomes_remain_latched_for_every_helper(self):
        for method in self.methods:
            for response in (None, self.response(retcode=10012), self.response(retcode=10031)):
                with self.subTest(method=method, response=response):
                    sdk.order_send.reset_mock()
                    sdk.order_send.return_value = response
                    pos = self.position()
                    with self.assertRaises(exceptions.OrderSendAmbiguous) as caught:
                        await self.invoke(pos, method)
                    attempt = self.attempt(pos, method)
                    self.assertIs(attempt.error, caught.exception)
                    self.assertIs(attempt.result, response)
                    for _ in range(2):
                        with self.assertRaises(exceptions.OrderSendAmbiguous) as repeated:
                            await self.invoke(pos, method)
                        self.assertIs(repeated.exception, caught.exception)
                    sdk.order_send.assert_called_once()

    async def test_restarted_tracker_ticks_do_not_resend_unknown_hedge(self):
        sdk.order_send.return_value = None
        pos = self.position()
        self.add_hedge_tracker(pos)
        for _ in range(3):
            with self.assertRaises(exceptions.OrderSendAmbiguous):
                await pos.track()
        sdk.order_send.assert_called_once()
        self.assertIsNone(pos.unresolved_hedge.result)

    async def test_unconfirmed_transport_exception_is_not_retried(self):
        sdk.order_send.side_effect = TimeoutError("lost response")
        pos = self.position()
        for _ in range(3):
            with self.assertRaises(exceptions.OrderSendAmbiguous):
                await self.invoke(pos, "hedge_position")
        sdk.order_send.assert_called_once()
        self.assertIsInstance(pos.unresolved_hedge.error.__cause__, TimeoutError)
        self.assertIsNone(pos.unresolved_hedge.result)

    async def test_result_conversion_failure_retains_guard_without_claiming_zero_execution(self):
        # Native success followed by a broken adapter conversion cannot justify another send.
        sdk.order_send.return_value = SimpleNamespace(retcode=10009)
        pos = self.position()
        for _ in range(3):
            self.assertEqual(await self.invoke(pos, "hedge_position"), (False, None))
        sdk.order_send.assert_called_once()
        self.assertIsInstance(pos.unresolved_hedge.error, AttributeError)
        self.assertIsNone(pos.unresolved_hedge.result)
        self.assertFalse(pos.is_hedged)

    async def test_missing_adapter_response_is_unknown_and_latched(self):
        pos = self.position()
        with patch.object(Order, "send", AsyncMock(return_value=None)) as send:
            for _ in range(3):
                with self.assertRaises(exceptions.OrderSendAmbiguous):
                    await self.invoke(pos, "hedge_position")
            send.assert_awaited_once()
        sdk.order_send.assert_not_called()

    async def test_malformed_adapter_success_is_unknown_and_latched(self):
        for response in (SimpleNamespace(), self.response(retcode=10009.0)):
            with self.subTest(response=response):
                pos = self.position()
                with patch.object(Order, "send", AsyncMock(return_value=response)) as send:
                    for _ in range(2):
                        with self.assertRaises(exceptions.OrderSendAmbiguous):
                            await self.invoke(pos, "hedge_position")
                    send.assert_awaited_once()
                self.assertIs(pos.unresolved_hedge.result, response)

    async def test_placed_or_unclassified_result_is_not_treated_as_zero_execution(self):
        for method in self.methods:
            for retcode in (10008, 10011, 99999):
                with self.subTest(method=method, retcode=retcode):
                    sdk.order_send.reset_mock()
                    sdk.order_send.return_value = self.response(retcode=retcode, volume=0)
                    pos = self.position()
                    for _ in range(3):
                        await self.invoke(pos, method)
                    sdk.order_send.assert_called_once()
                    self.assertEqual(self.attempt(pos, method).result.retcode, retcode)

    async def test_confirmed_zero_execution_rejection_can_release_for_a_new_attempt(self):
        for method in self.methods:
            with self.subTest(method=method):
                sdk.order_send.reset_mock()
                sdk.order_send.side_effect = [self.response(retcode=10006, volume=0), self.response()]
                pos = self.position()
                ok, result = await self.invoke(pos, method)
                self.assertFalse(ok)
                self.assertEqual(result.retcode, 10006)
                self.assertIsNone(self.attempt(pos, method))
                ok, result = await self.invoke(pos, method)
                self.assertFalse(ok)
                self.assertEqual(result.retcode, 10010)
                await self.invoke(pos, method)
                self.assertEqual(sdk.order_send.call_count, 2)
                self.assertEqual(self.attempt(pos, method).result.volume, 0.04)

    async def test_rejection_with_missing_or_positive_volume_does_not_clear_guard(self):
        for volume in (None, 0.04):
            with self.subTest(volume=volume):
                sdk.order_send.reset_mock()
                sdk.order_send.return_value = self.response(retcode=10006, volume=volume)
                pos = self.position()
                for _ in range(3):
                    await self.invoke(pos, "hedge_position")
                sdk.order_send.assert_called_once()
                self.assertEqual(pos.unresolved_hedge.result.volume, volume)

    async def test_done_with_missing_or_failed_position_lookup_stays_latched(self):
        for method in ("hedge_position", "stack_position"):
            for lookup in (None, RuntimeError("position lookup unavailable")):
                with self.subTest(method=method, lookup=lookup):
                    sdk.order_send.reset_mock()
                    sdk.order_send.return_value = self.response(retcode=10009, volume=0.1)
                    pos = self.position()
                    self.positions.get_position_by_ticket.side_effect = lookup if isinstance(lookup, Exception) else None
                    self.positions.get_position_by_ticket.return_value = lookup
                    await self.invoke(pos, method)
                    # Becoming visible later does not silently authorize a new submission.
                    self.positions.get_position_by_ticket.side_effect = None
                    self.positions.get_position_by_ticket.return_value = self.child_position
                    await self.invoke(pos, method)
                    sdk.order_send.assert_called_once()
                    self.assertEqual(self.attempt(pos, method).result.retcode, 10009)
                    self.assertFalse(pos.is_hedged if method.startswith("hedge") else pos.is_stacked)

    async def test_preflight_failure_is_conservatively_latched_without_native_send(self):
        sdk.order_check.return_value = FakeMT5Response(retcode=10016, comment="invalid stops")
        pos = self.position()
        for _ in range(3):
            self.assertEqual(await self.invoke(pos, "hedge_position"), (False, None))
        sdk.order_check.assert_called_once()
        sdk.order_send.assert_not_called()
        self.assertIsInstance(pos.unresolved_hedge.error, exceptions.OrderError)

    async def test_in_flight_guard_blocks_concurrent_same_loop_submission(self):
        entered, release = asyncio.Event(), asyncio.Event()

        async def send():
            entered.set()
            await release.wait()
            return self.response()

        pos = self.position()
        with patch.object(Order, "send", AsyncMock(side_effect=send)) as mock:
            first = asyncio.create_task(self.invoke(pos, "hedge_position"))
            try:
                await asyncio.wait_for(entered.wait(), timeout=1)
                self.assertEqual(await self.invoke(pos, "hedge_order"), (False, None))
            finally:
                release.set()
                await first
            mock.assert_awaited_once()
        self.assertEqual(pos.unresolved_hedge.result.volume, 0.04)

    async def test_cancelled_attempt_remains_blocked(self):
        pos = self.position()
        with patch.object(Order, "send", AsyncMock(side_effect=asyncio.CancelledError())) as send:
            with self.assertRaises(asyncio.CancelledError):
                await self.invoke(pos, "stack_position")
            self.assertEqual(await self.invoke(pos, "stack_order"), (False, None))
            send.assert_awaited_once()
        self.assertIsInstance(pos.unresolved_stack.error, asyncio.CancelledError)

    async def test_changing_boolean_flags_does_not_release_unresolved_execution(self):
        sdk.order_send.return_value = self.response()
        pos = self.position()
        await self.invoke(pos, "hedge_position")
        attempt = pos.unresolved_hedge
        pos.update(is_hedged=False, is_stacked=False)
        await self.invoke(pos, "hedge_order")
        sdk.order_send.assert_called_once()
        self.assertIs(pos.unresolved_hedge, attempt)

    async def test_other_exposure_kind_does_not_clear_existing_guard(self):
        sdk.order_send.return_value = self.response()
        pos = self.position()
        await self.invoke(pos, "hedge_position")
        hedge = pos.unresolved_hedge
        sdk.order_send.return_value = self.response(retcode=10009, volume=0.1)
        await self.invoke(pos, "stack_order")
        self.assertIsNone(pos.unresolved_stack)
        self.assertIs(pos.unresolved_hedge, hedge)
        await self.invoke(pos, "hedge_position")
        self.assertEqual(sdk.order_send.call_count, 2)


if __name__ == "__main__":
    unittest.main()
