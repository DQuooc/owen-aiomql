"""Offline contract tests for the asynchronous Order/Trader check-to-send path."""

import importlib.util
import sys
import types
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch


ROOT = Path(__file__).resolve().parents[2]
PREFIX = "_aiomql_order_check_offline"


def module(name, **attributes):
    result = types.ModuleType(name)
    result.__dict__.update(attributes)
    sys.modules[name] = result
    return result


for package in (PREFIX, f"{PREFIX}.lib", f"{PREFIX}.core"):
    module(package).__path__ = []


class FakeBase:
    def __init__(self, **kwargs):
        self.set_attributes(**kwargs)

    def set_attributes(self, **kwargs):
        self.__dict__.update(kwargs)

    @property
    def dict(self):
        return self.__dict__


class FakeTradeRequest:
    __match_args__ = ("symbol", "volume", "price", "type", "comment")


class FakeResult:
    def __init__(self, **kwargs):
        self.__dict__.update(kwargs)


class FakeMT5Response:
    def __init__(self, **kwargs):
        self.values = kwargs
        self.__dict__.update(kwargs)

    def _asdict(self):
        return self.values


module(f"{PREFIX}.core.models", TradeRequest=FakeTradeRequest, TradeOrder=object,
       OrderCheckResult=FakeResult, OrderSendResult=FakeResult, TradePosition=object, OrderType=object)
module(f"{PREFIX}.core.constants", TradeAction=types.SimpleNamespace(DEAL=1, PENDING=5),
       OrderTime=types.SimpleNamespace(DAY=0), OrderFilling=types.SimpleNamespace(FOK=0), OrderType=object,
       TradeRetcode=types.SimpleNamespace(DONE=10009, DONE_PARTIAL=10010, TIMEOUT=10012, CONNECTION=10031))
module(f"{PREFIX}.core.base", _Base=FakeBase, BaseMeta=type)
module(f"{PREFIX}.core.meta_trader", MetaTrader=object)
module(f"{PREFIX}.core.config", Config=object)
module(f"{PREFIX}.core.task_queue", QueueItem=object)
module(f"{PREFIX}.lib.result", Result=object)
module(f"{PREFIX}.lib.symbol", Symbol=type("Symbol", (), {}))
module(f"{PREFIX}.lib.ram", RAM=type("RAM", (), {}))
module(f"{PREFIX}.utils", error_handler=lambda func=None, **kwargs: func if func else (lambda wrapped: wrapped),
       decrease_value_by_pct=lambda *args: None, increase_value_by_pct=lambda *args: None)


def load_source(name, path):
    spec = importlib.util.spec_from_file_location(name, ROOT / path)
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)
    return loaded


exceptions = load_source(f"{PREFIX}.core.exceptions", "src/aiomql/core/exceptions.py")
OrderError = exceptions.OrderError
load_source(f"{PREFIX}.core.volume", "src/aiomql/core/volume.py")
Order = load_source(f"{PREFIX}.lib.order", "src/aiomql/lib/order.py").Order
trader_module = load_source(f"{PREFIX}.lib.trader", "src/aiomql/lib/trader.py")
Trader = trader_module.Trader
Positions = load_source(f"{PREFIX}.lib.positions", "src/aiomql/lib/positions.py").Positions


class FakeMetaTrader:
    TradeRequest = FakeTradeRequest
    error = "offline check error"

    def __init__(self, check_response, send_response=None):
        self.order_check = AsyncMock(return_value=check_response)
        self.order_send = AsyncMock(return_value=send_response or FakeMT5Response(retcode=10009, comment="done"))


class ConcreteTrader(Trader):
    async def place_trade(self, *args, **kwargs):
        raise NotImplementedError


class FakeSymbol:
    name = "EURUSD"
    volume_min = 0.01
    volume_max = 1.0
    volume_step = 0.01

    def check_volume(self, *, volume):
        return self.volume_min <= volume <= self.volume_max, max(self.volume_min, min(self.volume_max, volume))

    def __str__(self):
        return self.name


class CheckToSendContractTests(unittest.IsolatedAsyncioTestCase):
    def make_trader(self, check_response, send_response=None):
        mt5 = FakeMetaTrader(check_response, send_response)
        # Avoid Config/RAM/terminal setup; the real Order and Trader methods remain under test.
        order = Order(symbol="EURUSD", volume=0.1, price=1.0, type=0)
        order.mt5 = mt5
        Order.mt5 = mt5
        trader = object.__new__(ConcreteTrader)
        trader.symbol = FakeSymbol()
        trader.order = order
        return trader, mt5

    async def test_valid_check_allows_send(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0, comment="done"))

        self.assertIsNotNone(await trader.check_order())
        self.assertEqual((await trader.send_order()).retcode, 10009)
        self.assertEqual(mt5.order_check.await_count, 2)
        mt5.order_send.assert_awaited_once()

    async def test_direct_order_send_requires_successful_check(self):
        for response in (FakeMT5Response(retcode=10016, comment="invalid stops"), None):
            with self.subTest(response=response):
                trader, mt5 = self.make_trader(response)
                if response is None:
                    with self.assertRaises(OrderError):
                        await trader.order.check()
                else:
                    self.assertEqual((await trader.order.check()).retcode, 10016)
                with self.assertRaises(OrderError):
                    await trader.order.send()
                mt5.order_send.assert_not_awaited()

    async def test_direct_send_check_exception_never_sends(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0))
        failure = ConnectionError("check unavailable")
        mt5.order_check.side_effect = failure
        with self.assertRaises(ConnectionError) as caught:
            await trader.order.send()
        self.assertIs(caught.exception, failure)
        mt5.order_send.assert_not_awaited()

    async def test_send_uses_checked_snapshot_if_order_changes_during_check(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0))
        request = trader.order.request

        async def check_then_modify(checked_request):
            self.assertEqual(checked_request, request)
            trader.order.price = 2.0
            return FakeMT5Response(retcode=0)

        mt5.order_check.side_effect = check_then_modify
        await trader.order.send()
        mt5.order_send.assert_awaited_once_with(request)
        self.assertEqual(trader.order.price, 2.0)

    async def test_trader_send_without_prior_check_still_rejects(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=10016, comment="invalid stops"))
        with self.assertRaises(OrderError):
            await trader.send_order()
        mt5.order_send.assert_not_awaited()

    async def test_stale_trader_check_cannot_send_after_rejection(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0, comment="done"))
        self.assertIsNotNone(await trader.check_order())
        mt5.order_check.return_value = FakeMT5Response(retcode=10016, comment="invalid stops")

        with self.assertRaises(OrderError):
            await trader.send_order()
        mt5.order_send.assert_not_awaited()

    async def test_invalid_retcode_never_sends_even_if_caller_ignores_check(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=10016, comment="invalid stops"))

        self.assertIsNone(await trader.check_order())
        self.assertIsNone(await trader.send_order())
        mt5.order_send.assert_not_awaited()

    async def test_none_check_never_sends_even_if_caller_catches_error(self):
        trader, mt5 = self.make_trader(None)

        with self.assertRaises(OrderError):
            await trader.check_order()
        self.assertIsNone(await trader.send_order())
        mt5.order_send.assert_not_awaited()

    async def test_check_exception_propagates_and_blocks_send(self):
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0))
        failure = ConnectionError("check response unavailable")
        mt5.order_check.side_effect = failure

        with self.assertRaises(ConnectionError) as caught:
            await trader.check_order()
        self.assertIs(caught.exception, failure)
        self.assertIsNone(await trader.send_order())
        mt5.order_send.assert_not_awaited()

    async def test_done_is_full_success(self):
        response = FakeMT5Response(retcode=10009, volume=1.0, comment="done",
                                   request=types.SimpleNamespace(volume=1.0))
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0), response)

        await trader.check_order()
        result = await trader.send_order()

        self.assertEqual(result.retcode, 10009)
        self.assertEqual(result.volume, result.request.volume)
        mt5.order_send.assert_awaited_once()

    async def test_done_partial_is_reported_with_actual_filled_volume(self):
        response = FakeMT5Response(retcode=10010, volume=0.4, comment="partial fill",
                                   request=types.SimpleNamespace(volume=1.0))
        trader, _ = self.make_trader(FakeMT5Response(retcode=0), response)

        await trader.check_order()
        with self.assertLogs(f"{PREFIX}.lib.trader", level="WARNING") as logs:
            result = await trader.send_order()

        self.assertEqual(result.retcode, 10010)
        self.assertEqual(result.volume, 0.4)
        self.assertEqual(result.request.volume, 1.0)
        self.assertIn("partially filled", logs.output[0])
        self.assertNotIn("Unable to place order", logs.output[0])

    async def test_done_partial_sends_only_once(self):
        response = FakeMT5Response(retcode=10010, volume=0.4, comment="partial fill",
                                   request=types.SimpleNamespace(volume=1.0))
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0), response)

        await trader.check_order()
        await trader.send_order()

        mt5.order_send.assert_awaited_once()

    async def test_rejected_remains_failure(self):
        response = FakeMT5Response(retcode=10006, volume=0.0, comment="rejected",
                                   request=types.SimpleNamespace(volume=1.0))
        trader, mt5 = self.make_trader(FakeMT5Response(retcode=0), response)

        await trader.check_order()
        with self.assertLogs(f"{PREFIX}.lib.trader", level="WARNING") as logs:
            result = await trader.send_order()

        self.assertEqual(result.retcode, 10006)
        self.assertIn("Unable to place order", logs.output[0])
        mt5.order_send.assert_awaited_once()

    async def test_partial_record_uses_filled_volume_for_expected_profit(self):
        trader, _ = self.make_trader(FakeMT5Response(retcode=0))
        trader.config = types.SimpleNamespace(record_trades=True)
        trader.order.calc_profit = AsyncMock(return_value=100.0)
        trader.order.get_history_order_by_ticket = AsyncMock(return_value=None)
        result = FakeResult(retcode=10010, volume=0.4, order=123,
                            request=types.SimpleNamespace(volume=1.0, sl=1.0, tp=1.2))
        saved = AsyncMock()
        captures = []

        def capture_result(**kwargs):
            captures.append(kwargs)
            return types.SimpleNamespace(save=saved)

        with patch.object(trader_module, "Result", capture_result):
            await trader.record_trade(result=result, use_task_queue=False)

        self.assertIs(captures[0]["result"], result)
        self.assertEqual(captures[0]["expected_profit"], 40.0)
        self.assertEqual(captures[0]["parameters"]["_execution"],
                         {"retcode": 10010, "requested_volume": 1.0, "filled_volume": 0.4})
        saved.assert_awaited_once()

    async def test_partial_close_does_not_claim_position_fully_closed(self):
        response = FakeResult(retcode=10010, volume=0.4, comment="partial fill")
        position = types.SimpleNamespace(ticket=123, symbol="EURUSD", volume=1.0,
                                         type=types.SimpleNamespace(opposite=1), price_current=1.0)
        with patch.object(Order, "send_order", new_callable=AsyncMock, return_value=response) as send:
            fully_closed, result = await Positions.close_position(position=position)

        self.assertFalse(fully_closed)
        self.assertIs(result, response)
        send.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
