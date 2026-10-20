"""H3: public submission boundaries with real wrappers and a fake native SDK."""

import asyncio
from decimal import Decimal
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_order_check_contract import PREFIX, FakeMT5Response, Order, Positions, exceptions, load_source
from test_order_send_safety import MetaTrader, SyncMetaTrader, SyncOrder, reset_sdk, sdk


with patch.dict(sys.modules, {f"{PREFIX}.core.sync.meta_trader": SimpleNamespace(MetaTrader=SyncMetaTrader)}):
    sync_positions_module = load_source(
        f"{PREFIX}.lib.sync.h3_positions", "src/aiomql/lib/sync/positions.py")
SyncPositions = sync_positions_module.Positions


class SubmissionCheckCases:
    """Run the same safety contract against both actual implementations."""

    async_mode = True
    paths = ("core", "class", "instance", "close", "close_position", "close_by_ticket")

    def setUp(self):
        reset_sdk()
        self.mt5 = MetaTrader() if self.async_mode else SyncMetaTrader()
        self.order = Order if self.async_mode else SyncOrder
        self.positions = Positions if self.async_mode else SyncPositions
        mock = AsyncMock if self.async_mode else Mock
        self.mt5.initialize = mock(return_value=True)
        self.mt5.login = mock(return_value=True)
        self.enterContext(patch.object(self.order, "mt5", self.mt5, create=True))
        self.position = SimpleNamespace(ticket=123, symbol="EURUSD", volume=0.1,
                                        type=SimpleNamespace(opposite=1), price_current=1.25)
        self.enterContext(patch.object(self.positions, "get_position_by_ticket",
                                      mock(return_value=self.position)))
        positions_module = sys.modules[Positions.__module__] if self.async_mode else sync_positions_module
        self.enterContext(patch.object(positions_module, "OrderType",
                                      lambda value: SimpleNamespace(opposite=1)))
        self.request = {"action": 1, "symbol": "EURUSD", "volume": 0.1,
                        "type": 1, "price": 1.25}
        self.response = FakeMT5Response(retcode=10009, volume=0.1, comment="done", order=123)
        sdk.order_send.return_value = self.response

    async def invoke(self, path, request=None):
        request = self.request if request is None else request
        if path == "core":
            result = self.mt5.order_send(request)
        elif path == "class":
            result = self.order.send_order(request=request, connection_retries=10)
        elif path == "instance":
            result = self.order(**request).send()
        elif path == "close":
            result = self.positions.close(ticket=123, symbol="EURUSD", price=1.25,
                                          volume=0.1, order_type=0)
        elif path == "close_position":
            result = self.positions.close_position(position=self.position)
        elif path == "close_by_ticket":
            result = self.positions.close_position_by_ticket(ticket=123)
        else:
            raise AssertionError(path)
        return await result if self.async_mode else result

    def assert_no_submission(self):
        sdk.order_send.assert_not_called()
        self.mt5.initialize.assert_not_called()
        self.mt5.login.assert_not_called()

    async def test_rejected_check_blocks_every_submission_path(self):
        for path in self.paths:
            with self.subTest(path=path):
                sdk.order_check.reset_mock()
                sdk.order_check.return_value = FakeMT5Response(retcode=10016, comment="invalid stops")
                with self.assertRaises(exceptions.OrderError) as caught:
                    await self.invoke(path)
                self.assertNotIsInstance(caught.exception, exceptions.OrderSendAmbiguous)
                sdk.order_check.assert_called_once()
                self.assert_no_submission()

    async def test_missing_malformed_and_ambiguous_checks_fail_closed(self):
        responses = [None, {}, {"retcode": 0}, object(), FakeMT5Response(),
                     *[FakeMT5Response(retcode=code) for code in
                       (None, False, True, 0.0, "0", 10009, 10010, 10012, 10031, -1)]]
        for path in ("core", "class", "close_position"):
            for response in responses:
                with self.subTest(path=path, response=response):
                    sdk.order_check.reset_mock()
                    sdk.order_check.return_value = response
                    with self.assertRaises(exceptions.OrderError) as caught:
                        await self.invoke(path)
                    self.assertNotIsInstance(caught.exception, exceptions.OrderSendAmbiguous)
                    sdk.order_check.assert_called_once()
                    self.assert_no_submission()

    async def test_check_transport_error_propagates_without_send_or_retry(self):
        for path in self.paths:
            for error_type in (TimeoutError, ConnectionError):
                with self.subTest(path=path, error=error_type):
                    sdk.order_check.reset_mock()
                    failure = error_type("check unavailable")
                    sdk.order_check.side_effect = failure
                    with self.assertRaises(error_type):
                        await self.invoke(path)
                    sdk.order_check.assert_called_once()
                    self.assert_no_submission()

    async def test_final_check_rejects_after_successful_instance_precheck(self):
        sdk.order_check.side_effect = [FakeMT5Response(retcode=0), FakeMT5Response(retcode=10016)]
        with self.assertRaises(exceptions.OrderError):
            await self.invoke("instance")
        self.assertEqual(sdk.order_check.call_count, 2)
        self.assert_no_submission()

    async def test_success_and_partial_preserve_result_and_send_once(self):
        for path in self.paths:
            for retcode in (10009, 10010):
                with self.subTest(path=path, retcode=retcode):
                    sdk.order_check.reset_mock()
                    sdk.order_send.reset_mock()
                    response = FakeMT5Response(retcode=retcode, volume=0.04, comment="executed", order=123)
                    sdk.order_send.return_value = response
                    result = await self.invoke(path)
                    if path.startswith("close"):
                        closed, result = result
                        self.assertEqual(closed, retcode == 10009)
                        self.assertEqual(sdk.order_send.call_args.args[0]["position"], 123)
                    if path == "core":
                        self.assertIs(result, response)
                    self.assertEqual((result.retcode, result.volume), (retcode, 0.04))
                    sdk.order_send.assert_called_once()
                    self.assertEqual(sdk.order_check.call_count, 2 if path == "instance" else 1)
                    self.assertEqual(sdk.order_check.call_args.args[0], sdk.order_send.call_args.args[0])

    async def test_checked_snapshot_matches_effective_send_despite_caller_mutation(self):
        for path in ("core", "class"):
            with self.subTest(path=path):
                sdk.order_send.reset_mock()
                original = dict(self.request, volume=Decimal("0.10"), comment="x" * 40)
                checked = []

                def check(request):
                    checked.append(dict(request))
                    original.update(volume=0.9, price=99, comment="changed by caller")
                    return FakeMT5Response(retcode=0)

                sdk.order_check.side_effect = check
                await self.invoke(path, original)
                expected = dict(self.request, volume=0.1, comment="x" * 25)
                self.assertEqual(checked, [expected])
                self.assertIsInstance(checked[0]["volume"], float)
                sdk.order_send.assert_called_once_with(expected)
                self.assertIsNot(sdk.order_send.call_args.args[0], original)

    async def test_check_cannot_mutate_the_snapshot_then_authorize_send(self):
        def mutate(request):
            request["volume"] = 0.9
            return FakeMT5Response(retcode=0)

        sdk.order_check.side_effect = mutate
        with self.assertRaisesRegex(exceptions.OrderError, "changed during check"):
            await self.invoke("class")
        self.assert_no_submission()

    async def test_ambiguous_send_is_never_resent(self):
        for path in self.paths:
            for outcome in (None, FakeMT5Response(retcode=10012), FakeMT5Response(retcode=10031),
                            TimeoutError("send unavailable")):
                with self.subTest(path=path, outcome=outcome):
                    sdk.order_send.reset_mock(return_value=True, side_effect=True)
                    if isinstance(outcome, Exception):
                        sdk.order_send.side_effect = outcome
                    else:
                        sdk.order_send.return_value = outcome
                    with self.assertRaises(exceptions.OrderSendAmbiguous):
                        await self.invoke(path)
                    sdk.order_send.assert_called_once()
                    self.mt5.initialize.assert_not_called()
                    self.mt5.login.assert_not_called()

    async def test_invalid_volume_still_blocks_before_final_check(self):
        for path in ("core", "class"):
            for volume in (0, -1, 0.015, float("nan"), "0.1"):
                with self.subTest(path=path, volume=volume):
                    with self.assertRaises(exceptions.InvalidVolume):
                        await self.invoke(path, dict(self.request, volume=volume))
                    sdk.order_check.assert_not_called()
                    self.assert_no_submission()

    async def test_actions_without_volume_cannot_bypass_check(self):
        for action in (6, 7, 8):  # SLTP, MODIFY, REMOVE: the gate is not volume-dependent.
            with self.subTest(action=action):
                sdk.order_check.reset_mock()
                sdk.order_check.return_value = FakeMT5Response(retcode=10016)
                with self.assertRaises(exceptions.OrderError):
                    await self.invoke("class", {"action": action, "order": 123, "symbol": "EURUSD"})
                sdk.order_check.assert_called_once()
                sdk.symbol_info.assert_not_called()
                self.assert_no_submission()


class AsyncSubmissionCheckTests(SubmissionCheckCases, unittest.IsolatedAsyncioTestCase):
    async def test_cancellation_during_check_never_submits(self):
        sdk.order_check.side_effect = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.invoke("class")
        self.assert_no_submission()


class SyncSubmissionCheckTests(SubmissionCheckCases, unittest.IsolatedAsyncioTestCase):
    async_mode = False


if __name__ == "__main__":
    unittest.main()
