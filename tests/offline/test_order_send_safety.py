"""Real retry/send code with a fake SDK; no installed MT5, terminal or credentials.

Run: python -m unittest discover -s tests/offline -p 'test_*.py' -v
"""

import asyncio
import sys
import threading
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_order_check_contract import (
    PREFIX, ConcreteTrader, FakeMT5Response, FakeTradeRequest, FakeSymbol, Order, Positions,
    exceptions, load_source, module,
)


OrderSendAmbiguous = exceptions.OrderSendAmbiguous
sdk = types.ModuleType("MetaTrader5")
for name in ("Tick", "SymbolInfo", "AccountInfo", "TerminalInfo", "TradeOrder", "TradePosition",
             "TradeDeal", "OrderCheckResult", "OrderSendResult", "BookInfo"):
    setattr(sdk, name, type(name, (), {}))
sdk.TradeRequest = FakeTradeRequest
sdk.order_send = Mock(__name__="order_send")
sdk.order_check = Mock(__name__="order_check")
sdk.symbol_info = Mock(__name__="symbol_info")
sdk.last_error = Mock(__name__="last_error", return_value=(-10005, "IPC timeout"))

constants = sys.modules[f"{PREFIX}.core.constants"]
constants.CopyTicks = object
constants.OrderType = types.SimpleNamespace(BUY=0, SELL=1)
module(f"{PREFIX}.core.sync").__path__ = []
module(f"{PREFIX}.lib.sync").__path__ = []
load_source(f"{PREFIX}.core.errors", "src/aiomql/core/errors.py")
with patch.dict(sys.modules, {"MetaTrader5": sdk, "numpy": types.SimpleNamespace(ndarray=object)}):
    # Load the real MetaBase binding as well as both real MetaTrader implementations.
    load_source(f"{PREFIX}.core._core", "src/aiomql/core/_core.py")
    MetaTrader = load_source(f"{PREFIX}.core.meta_trader", "src/aiomql/core/meta_trader.py").MetaTrader
    SyncMetaTrader = load_source(f"{PREFIX}.core.sync.meta_trader", "src/aiomql/core/sync/meta_trader.py").MetaTrader

utils = load_source(f"{PREFIX}.utils.send_safety", "src/aiomql/utils/utils.py")
sys.modules[f"{PREFIX}.utils"].error_handler_sync = utils.error_handler_sync
SyncOrder = load_source(f"{PREFIX}.lib.sync.order", "src/aiomql/lib/sync/order.py").Order
module(f"{PREFIX}.contrib").__path__ = []
module(f"{PREFIX}.contrib.traders").__path__ = []
ScalpTrader = load_source(f"{PREFIX}.contrib.traders.scalp_trader", "src/aiomql/contrib/traders/scalp_trader.py").ScalpTrader
SimpleTrader = load_source(f"{PREFIX}.contrib.traders.simple_trader", "src/aiomql/contrib/traders/simple_trader.py").SimpleTrader
Session = load_source(f"{PREFIX}.lib.sessions", "src/aiomql/lib/sessions.py").Session
sys.modules[f"{PREFIX}.core"].Config = object
Strategy = load_source(f"{PREFIX}.lib.strategy", "src/aiomql/lib/strategy.py").Strategy
sys.modules[f"{PREFIX}.core"].State = object
sys.modules[f"{PREFIX}.core"].sleep = AsyncMock()
sys.modules[f"{PREFIX}.lib"].Positions = Positions
sys.modules[f"{PREFIX}.lib"].Symbol = type("Symbol", (), {})
sys.modules[f"{PREFIX}.lib"].Order = Order
sys.modules[f"{PREFIX}.core.models"].TradeAction = constants.TradeAction
module(f"{PREFIX}.utils.price_utils", increase_value_by_pct=lambda *args: None,
       decrease_value_by_pct=lambda *args: None)
module(f"{PREFIX}.contrib.trackers").__path__ = []
trackers = load_source(f"{PREFIX}.contrib.trackers.position_trackers", "src/aiomql/contrib/trackers/position_trackers.py")
OpenPosition = load_source(f"{PREFIX}.contrib.trackers.open_position", "src/aiomql/contrib/trackers/open_position.py").OpenPosition
module(f"{PREFIX}.lib.sync.positions", Positions=object)
SyncSession = load_source(f"{PREFIX}.lib.sync.sessions", "src/aiomql/lib/sync/sessions.py").Session


def reset_sdk():
    sdk.order_send.reset_mock(return_value=True, side_effect=True)
    sdk.order_check.reset_mock(return_value=True, side_effect=True)
    sdk.order_check.return_value = FakeMT5Response(retcode=0, comment="done")
    sdk.symbol_info.reset_mock(return_value=True, side_effect=True)
    sdk.symbol_info.return_value = types.SimpleNamespace(volume_min=0.01, volume_max=1.0, volume_step=0.01)
    sdk.last_error.reset_mock()
    sdk.last_error.return_value = (-10005, "IPC timeout")


class AsyncSendSafetyTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_sdk()
        self.mt5 = MetaTrader()
        self.mt5.initialize = AsyncMock(return_value=True)
        self.mt5.login = AsyncMock(return_value=True)
        self.request = {"symbol": "EURUSD", "volume": 0.1}

    def assert_sent_once_without_reconnect(self):
        sdk.order_send.assert_called_once_with(self.request)
        self.mt5.initialize.assert_not_awaited()
        self.mt5.login.assert_not_awaited()

    async def test_read_connection_failure_reconnects_and_retries(self):
        expected = object()
        sdk.symbol_info.side_effect = [None, expected]
        self.assertIs(await self.mt5.symbol_info("EURUSD"), expected)
        self.assertEqual(sdk.symbol_info.call_count, 2)
        self.mt5.initialize.assert_awaited_once()
        self.mt5.login.assert_awaited_once()
        sdk.order_send.assert_not_called()

    async def test_definitive_rejection_is_returned_without_retry(self):
        response = FakeMT5Response(retcode=10006, comment="rejected")
        sdk.order_send.return_value = response
        self.assertIs(await self.mt5.order_send(self.request), response)
        self.assert_sent_once_without_reconnect()

    async def test_none_response_is_explicit_unknown_and_never_resent(self):
        sdk.order_send.return_value = None
        with self.assertRaises(OrderSendAmbiguous) as caught:
            await self.mt5.order_send(self.request)
        error = caught.exception
        self.assertEqual(error.outcome, "UNKNOWN_OUTCOME")
        self.assertEqual(error.error.code, -10005)
        self.assertEqual(error.request, self.request)
        self.assertIsNot(error.request, self.request)
        self.assert_sent_once_without_reconnect()

    async def test_transport_exception_preserves_cause_and_never_resends(self):
        for failure in (TimeoutError("lost response"), ConnectionError("disconnected")):
            with self.subTest(failure=type(failure).__name__):
                sdk.order_send.reset_mock()
                sdk.order_send.side_effect = failure
                with self.assertRaises(OrderSendAmbiguous) as caught:
                    await self.mt5.order_send(self.request)
                self.assertIs(caught.exception.__cause__, failure)
                self.assert_sent_once_without_reconnect()

    async def test_timeout_and_connection_retcodes_preserve_raw_response(self):
        for retcode in (10012, 10031):
            with self.subTest(retcode=retcode):
                sdk.order_send.reset_mock()
                response = FakeMT5Response(retcode=retcode)
                sdk.order_send.return_value = response
                with self.assertRaises(OrderSendAmbiguous) as caught:
                    await self.mt5.order_send(self.request)
                self.assertIs(caught.exception.result, response)
                self.assert_sent_once_without_reconnect()

    async def test_ambiguity_propagates_through_order_and_trader(self):
        sdk.order_send.return_value = None
        with patch.object(Order, "mt5", self.mt5, create=True):
            trader = object.__new__(ConcreteTrader)
            trader.symbol = FakeSymbol()
            trader.order = Order(**self.request)
            with self.assertRaises(OrderSendAmbiguous) as caught:
                await trader.send_order()
        self.assertEqual(caught.exception.outcome, "UNKNOWN_OUTCOME")
        self.assert_sent_once_without_reconnect()

    async def test_order_layer_no_longer_retries_adapter_connection_response(self):
        for response in (None, FakeMT5Response(retcode=10031), FakeMT5Response(retcode=10012)):
            with self.subTest(response=response):
                adapter = types.SimpleNamespace(order_send=AsyncMock(return_value=response))
                with patch.object(Order, "mt5", adapter, create=True):
                    with self.assertRaises(OrderSendAmbiguous):
                        await Order.send_order(request=self.request, connection_retries=5)
                adapter.order_send.assert_awaited_once_with(self.request)

    async def test_builtin_traders_propagate_ambiguity_from_place_trade(self):
        for trader_type, params in ((ScalpTrader, {"volume": 0.1}), (SimpleTrader, {"sl": 1.0})):
            with self.subTest(trader=trader_type.__name__):
                sdk.order_send.reset_mock()
                sdk.order_send.return_value = None
                with patch.object(Order, "mt5", self.mt5, create=True):
                    trader = object.__new__(trader_type)
                    trader.symbol = FakeSymbol()
                    trader.parameters = {}
                    trader.order = Order(**self.request)
                    trader.create_order_no_stops = AsyncMock()
                    trader.create_order_with_sl = AsyncMock()
                    trader.check_order = AsyncMock(return_value=True)
                    with self.assertRaises(OrderSendAmbiguous):
                        await trader.place_trade(order_type=0, **params)
                sdk.order_send.assert_called_once()

    async def test_strategy_stops_and_exposes_ambiguity_instead_of_repeating_trade(self):
        class ProbeStrategy(Strategy):
            async def __aenter__(self):
                return self

            async def __aexit__(self, *args):
                return None

        strategy = object.__new__(ProbeStrategy)
        strategy.running = True
        strategy.name = "offline"
        strategy.symbol = types.SimpleNamespace(name="EURUSD")
        strategy.sessions = types.SimpleNamespace(check=AsyncMock())
        error = OrderSendAmbiguous(request=self.request)
        strategy.trade = AsyncMock(side_effect=error)
        with self.assertRaises(OrderSendAmbiguous) as caught:
            await strategy.live_strategy()
        self.assertIs(caught.exception, error)
        self.assertFalse(strategy.running)
        strategy.trade.assert_awaited_once()

    async def test_bulk_close_does_not_filter_out_ambiguous_errors(self):
        error = OrderSendAmbiguous(request=self.request)
        with patch.object(Positions, "close_position", new_callable=AsyncMock, side_effect=error):
            with self.assertRaises(OrderSendAmbiguous):
                await Positions.close_positions(positions=(object(),))
            with patch.object(Positions, "get_positions", new_callable=AsyncMock, return_value=(object(),)):
                with self.assertRaises(OrderSendAmbiguous):
                    await Positions.close_all_positions()

    async def test_session_preserves_unknown_from_close_and_custom_action(self):
        error = OrderSendAmbiguous(request=self.request)
        session = object.__new__(Session)
        session.positions_manager = types.SimpleNamespace(close_position=AsyncMock(side_effect=error))
        with self.assertRaises(OrderSendAmbiguous):
            await session.close_positions(positions=(object(),))
        session.custom_end = AsyncMock(side_effect=error)
        with self.assertRaises(OrderSendAmbiguous):
            await session.action(action="custom_end")

    async def test_open_position_does_not_convert_unknown_send_to_false(self):
        sdk.order_send.return_value = None
        position = object.__new__(OpenPosition)
        position.symbol = types.SimpleNamespace(name="EURUSD")
        position.ticket = 123
        position.position = types.SimpleNamespace(volume=0.1, type=0)
        with patch.object(Order, "mt5", self.mt5, create=True):
            with self.assertRaises(OrderSendAmbiguous):
                await position.stack_position(order_params={"price": 1.0})
        sdk.order_send.assert_called_once()

    async def test_open_position_rejected_check_never_reaches_native_send(self):
        sdk.order_check.return_value = FakeMT5Response(retcode=10016, comment="invalid stops")
        position = object.__new__(OpenPosition)
        position.symbol = types.SimpleNamespace(name="EURUSD")
        position.ticket = 123
        position.position = types.SimpleNamespace(volume=0.1, type=0)
        with patch.object(Order, "mt5", self.mt5, create=True):
            self.assertEqual(await position.stack_position(order_params={"price": 1.0}), (False, None))
        sdk.order_check.assert_called_once()
        sdk.order_send.assert_not_called()

    async def test_open_position_bulk_close_preserves_unknown(self):
        error = OrderSendAmbiguous(request=self.request)
        position = object.__new__(OpenPosition)
        position.hedges = {123: types.SimpleNamespace(close_position=AsyncMock(side_effect=error))}
        with self.assertRaises(OrderSendAmbiguous):
            await position.close_hedges()

    async def test_tracker_loop_stops_on_ambiguity(self):
        error = OrderSendAmbiguous(request=self.request)
        tracker = object.__new__(trackers.PositionTracker)
        tracker.params = {}
        tracker.open_position = object()
        tracker.function = AsyncMock(side_effect=error)
        with self.assertRaises(OrderSendAmbiguous):
            await tracker()
        tracker.function.assert_awaited_once()

        loop = object.__new__(trackers.OpenPositionsTracker)
        loop.config = types.SimpleNamespace(shutdown=False, state=types.SimpleNamespace(conn=Mock()))
        tracked = types.SimpleNamespace(track=AsyncMock(side_effect=error))
        loop.state = {"tracked_positions": {123: tracked}}
        loop.interval = 0
        loop.auto_remove_closed = loop.autocommit = False
        with self.assertRaises(OrderSendAmbiguous):
            await asyncio.wait_for(loop.track(), timeout=1)
        tracked.track.assert_awaited_once()

    async def test_cancellation_during_native_send_is_ambiguous(self):
        started, release = threading.Event(), threading.Event()

        def native_send(request):
            started.set()
            release.wait(timeout=2)
            return FakeMT5Response(retcode=10009)

        sdk.order_send.side_effect = native_send
        task = asyncio.create_task(self.mt5.order_send(self.request))
        try:
            self.assertTrue(await asyncio.to_thread(started.wait, 2))
            task.cancel()
            with self.assertRaises(OrderSendAmbiguous) as caught:
                await task
            self.assertIsInstance(caught.exception.__cause__, asyncio.CancelledError)
            self.assert_sent_once_without_reconnect()
        finally:
            release.set()

    async def test_backoff_does_not_retry_ambiguous_send(self):
        sdk.order_send.return_value = None
        wrapped = utils.backoff_decorator(self.mt5.order_send)
        with self.assertRaises(OrderSendAmbiguous):
            await wrapped(self.request)
        self.assert_sent_once_without_reconnect()

    async def test_error_handler_does_not_convert_ambiguity_to_none(self):
        sdk.order_send.return_value = None
        wrapped = utils.error_handler(self.mt5.order_send)
        with self.assertRaises(OrderSendAmbiguous):
            await wrapped(self.request)
        self.assert_sent_once_without_reconnect()

    async def test_done_and_partial_are_not_retried_or_reclassified(self):
        for retcode in (10009, 10010):
            with self.subTest(retcode=retcode):
                sdk.order_send.reset_mock()
                response = FakeMT5Response(retcode=retcode)
                sdk.order_send.return_value = response
                self.assertIs(await self.mt5.order_send(self.request), response)
                self.assert_sent_once_without_reconnect()


class SyncSendSafetyTests(unittest.TestCase):
    def setUp(self):
        reset_sdk()
        self.mt5 = SyncMetaTrader()
        self.mt5.initialize = Mock(return_value=True)
        self.mt5.login = Mock(return_value=True)
        self.request = {"symbol": "EURUSD", "volume": 0.1}

    def test_read_connection_failure_reconnects_and_retries(self):
        expected = object()
        sdk.symbol_info.side_effect = [None, expected]
        self.assertIs(self.mt5.symbol_info("EURUSD"), expected)
        self.assertEqual(sdk.symbol_info.call_count, 2)
        self.mt5.initialize.assert_called_once()
        self.mt5.login.assert_called_once()

    def test_rejection_is_returned_after_one_send(self):
        response = FakeMT5Response(retcode=10006)
        sdk.order_send.return_value = response
        self.assertIs(self.mt5.order_send(self.request), response)
        sdk.order_send.assert_called_once_with(self.request)

    def test_ambiguous_responses_and_transport_errors_never_resend(self):
        for response in (None, FakeMT5Response(retcode=10031), FakeMT5Response(retcode=10012), TimeoutError()):
            with self.subTest(response=response):
                sdk.order_send.reset_mock(side_effect=True)
                if isinstance(response, Exception):
                    sdk.order_send.side_effect = response
                else:
                    sdk.order_send.return_value = response
                with self.assertRaises(OrderSendAmbiguous) as caught:
                    self.mt5.order_send(self.request)
                self.assertEqual(caught.exception.outcome, "UNKNOWN_OUTCOME")
                sdk.order_send.assert_called_once_with(self.request)
                self.mt5.initialize.assert_not_called()
                self.mt5.login.assert_not_called()

    def test_order_layer_no_longer_retries_connection_response(self):
        adapter = types.SimpleNamespace(order_send=Mock(return_value=FakeMT5Response(retcode=10031)))
        with patch.object(SyncOrder, "mt5", adapter, create=True):
            with self.assertRaises(OrderSendAmbiguous):
                SyncOrder.send_order(request=self.request, connection_retries=0)
        adapter.order_send.assert_called_once_with(self.request)

    def test_error_handler_preserves_ambiguous_error(self):
        sdk.order_send.return_value = None
        with self.assertRaises(OrderSendAmbiguous):
            utils.error_handler_sync(self.mt5.order_send)(self.request)
        sdk.order_send.assert_called_once_with(self.request)

    def test_session_preserves_unknown_from_close_and_custom_action(self):
        error = OrderSendAmbiguous(request=self.request)
        session = object.__new__(SyncSession)
        session.positions_manager = types.SimpleNamespace(close_position=Mock(side_effect=error))
        with self.assertRaises(OrderSendAmbiguous):
            session.close_positions(positions=(object(),))
        session.custom_end = Mock(side_effect=error)
        with self.assertRaises(OrderSendAmbiguous):
            session.action(action="custom_end")


if __name__ == "__main__":
    unittest.main()
