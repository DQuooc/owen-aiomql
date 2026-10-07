"""Volume construction and native send guard, using only fake MetaTrader data."""

import asyncio
import math
import sys
import types
import unittest
from unittest.mock import AsyncMock, Mock, patch

from test_order_check_contract import (
    PREFIX, ConcreteTrader, FakeMetaTrader, FakeMT5Response, FakeSymbol, Order,
    exceptions, load_source, module,
)
from test_order_send_safety import MetaTrader, SyncMetaTrader, SyncOrder, reset_sdk, sdk


InvalidVolume = exceptions.InvalidVolume
OrderError = exceptions.OrderError
constants = sys.modules[f"{PREFIX}.core.constants"]
constants.TimeFrame = object
constants.CopyTicks = types.SimpleNamespace(ALL=0)
models = sys.modules[f"{PREFIX}.core.models"]
models.SymbolInfo = object
models.BookInfo = object
module(f"{PREFIX}.lib.ticks", Tick=object, Ticks=object)
module(f"{PREFIX}.lib.account", Account=object)
module(f"{PREFIX}.lib.candle", Candles=object)
load_source(f"{PREFIX}.lib.symbol", "src/aiomql/lib/symbol.py")
load_source(f"{PREFIX}.lib.sync.symbol", "src/aiomql/lib/sync/symbol.py")
module(f"{PREFIX}.contrib.symbols").__path__ = []
ForexSymbol = load_source(f"{PREFIX}.contrib.symbols.forex_symbol", "src/aiomql/contrib/symbols/forex_symbol.py").ForexSymbol
SyncTrader = load_source(f"{PREFIX}.lib.sync.trader", "src/aiomql/lib/sync/trader.py").Trader
sys.modules[f"{PREFIX}.lib.trader"].OrderType = constants.OrderType
sys.modules[f"{PREFIX}.lib.sync.trader"].OrderType = constants.OrderType


def forex_symbol(*, minimum=0.01, maximum=1.0, step=0.01):
    symbol = object.__new__(ForexSymbol)
    symbol.name = "EURUSD"
    symbol.volume_min = minimum
    symbol.volume_max = maximum
    symbol.volume_step = step
    symbol.point = 0.0001
    symbol.digits = 5
    symbol.trade_contract_size = 100000
    symbol.amount_in_quote_currency = AsyncMock(side_effect=lambda *, amount: amount)
    symbol.info_tick = AsyncMock(return_value=types.SimpleNamespace(ask=1.10, bid=1.09))
    return symbol


def trader_with_symbol(symbol, mt5):
    trader = object.__new__(ConcreteTrader)
    trader.symbol = symbol
    trader.ram = types.SimpleNamespace(get_amount=AsyncMock(return_value=100), risk_to_reward=2)
    trader.order = Order(symbol=symbol.name)
    trader.order.mt5 = mt5
    Order.mt5 = mt5
    return trader


class AsyncVolumeTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_sdk()
        self.mt5 = FakeMetaTrader(FakeMT5Response(retcode=0))
        self.trader = trader_with_symbol(forex_symbol(), self.mt5)

    async def test_async_compute_volume_sl_is_awaited_and_is_numeric(self):
        await self.trader.create_order_with_stops(order_type=types.SimpleNamespace(is_long=True),
                                                   sl=1.09, tp=1.12, amount_to_risk=100)
        self.assertIsInstance(self.trader.order.volume, (int, float))
        self.assertFalse(asyncio.iscoroutine(self.trader.order.volume))
        self.assertEqual(self.trader.order.volume, 0.1)

    async def test_below_minimum_is_rejected_before_send(self):
        with self.assertRaises(InvalidVolume):
            await self.trader.create_order_no_stops(order_type=0, volume=0.001)
        self.mt5.order_send.assert_not_awaited()

    async def test_above_maximum_uses_check_volume_cap(self):
        await self.trader.create_order_no_stops(order_type=0, volume=1.2)
        self.assertEqual(self.trader.order.volume, 1.0)
        await self.trader.send_order()
        self.assertEqual(self.mt5.order_send.await_args.args[0]["volume"], 1.0)
        self.mt5.order_send.assert_awaited_once()

    async def test_above_maximum_caps_to_last_valid_step(self):
        trader = trader_with_symbol(forex_symbol(minimum=0.1, maximum=1.25, step=0.2), self.mt5)
        await trader.create_order_no_stops(order_type=0, volume=2.0)
        self.assertEqual(trader.order.volume, 1.1)

    async def test_invalid_step_is_rejected_before_send(self):
        with self.assertRaises(InvalidVolume):
            await self.trader.create_order_no_stops(order_type=0, volume=0.015)
        self.mt5.order_send.assert_not_awaited()

    async def test_computed_volume_rounds_to_actual_broker_step(self):
        symbol = forex_symbol(minimum=0.25, maximum=2.0, step=0.25)
        self.assertEqual(symbol.round_off_volume(volume=0.3), 0.5)
        self.assertEqual(symbol.round_off_volume(volume=0.3, round_down=True), 0.25)
        self.assertEqual(forex_symbol(minimum=0.1, step=0.1).round_off_volume(volume=0.30000000000000004), 0.3)
        trader = trader_with_symbol(symbol, self.mt5)
        await trader.create_order_with_stops(order_type=types.SimpleNamespace(is_long=True),
                                              sl=1.09, tp=1.12, amount_to_risk=300)
        self.assertEqual(trader.order.volume, 0.5)

    async def test_other_calculated_order_paths_keep_numeric_volume(self):
        await self.trader.create_order_with_sl(order_type=0, sl=1.09, amount_to_risk=100)
        self.assertEqual(self.trader.order.volume, 0.1)
        await self.trader.create_order_with_points(order_type=types.SimpleNamespace(is_long=True, is_short=False),
                                                    points=100, amount_to_risk=100)
        self.assertEqual(self.trader.order.volume, 0.1)

    async def test_valid_volume_reaches_native_send(self):
        mt5 = MetaTrader()
        mt5.initialize = AsyncMock(return_value=True)
        mt5.login = AsyncMock(return_value=True)
        sdk.order_send.return_value = FakeMT5Response(retcode=10009, comment="done")
        trader = trader_with_symbol(forex_symbol(), mt5)
        await trader.create_order_no_stops(order_type=0, volume=0.5)
        result = await trader.send_order()
        self.assertEqual(result.retcode, 10009)
        self.assertEqual(sdk.order_send.call_args.args[0]["volume"], 0.5)
        sdk.order_send.assert_called_once()

    async def test_non_numeric_non_finite_and_zero_volume_never_send(self):
        for invalid in (None, True, "0.1", 0, -0.1, math.nan, math.inf, -math.inf):
            with self.subTest(volume=invalid):
                self.trader.order.volume = invalid
                with self.assertRaises(InvalidVolume):
                    await self.trader.send_order()
        coroutine = asyncio.sleep(0)
        try:
            self.trader.order.volume = coroutine
            with self.assertRaises(InvalidVolume):
                await self.trader.send_order()
        finally:
            coroutine.close()
        self.mt5.order_send.assert_not_awaited()

    async def test_direct_order_send_rejects_invalid_broker_volume(self):
        mt5 = MetaTrader()
        mt5.initialize = AsyncMock(return_value=True)
        mt5.login = AsyncMock(return_value=True)
        with patch.object(Order, "mt5", mt5, create=True):
            for invalid in (0.001, 1.2, 0.015, math.nan):
                with self.subTest(volume=invalid):
                    with self.assertRaises(InvalidVolume):
                        await Order.send_order(request={"action": constants.TradeAction.DEAL,
                                                        "symbol": "EURUSD", "volume": invalid})
        sdk.order_send.assert_not_called()

    async def test_missing_broker_limits_fail_closed(self):
        mt5 = MetaTrader()
        mt5.initialize = AsyncMock(return_value=True)
        mt5.login = AsyncMock(return_value=True)
        sdk.symbol_info.return_value = None
        with self.assertRaises(InvalidVolume):
            await mt5.order_send({"action": constants.TradeAction.DEAL, "symbol": "EURUSD", "volume": 0.1})
        sdk.symbol_info.return_value = types.SimpleNamespace(volume_min=0.01, volume_max=1.0, volume_step=0)
        with self.assertRaises(InvalidVolume):
            await mt5.order_send({"action": constants.TradeAction.DEAL, "symbol": "EURUSD", "volume": 0.1})
        sdk.order_send.assert_not_called()


class SyncVolumeTests(unittest.TestCase):
    def setUp(self):
        reset_sdk()

    def test_direct_order_send_rejects_invalid_broker_volume(self):
        mt5 = SyncMetaTrader()
        mt5.initialize = Mock(return_value=True)
        mt5.login = Mock(return_value=True)
        with patch.object(SyncOrder, "mt5", mt5, create=True):
            for invalid in (0.001, 1.2, 0.015, math.inf):
                with self.subTest(volume=invalid):
                    with self.assertRaises(InvalidVolume):
                        SyncOrder.send_order(request={"action": constants.TradeAction.DEAL,
                                                      "symbol": "EURUSD", "volume": invalid})
        sdk.order_send.assert_not_called()

    def test_sync_trader_caps_high_volume_and_rejects_low_volume(self):
        class ConcreteSyncTrader(SyncTrader):
            def place_trade(self, *args, **kwargs):
                raise NotImplementedError

        symbol = FakeSymbol()
        symbol.info_tick = Mock(return_value=types.SimpleNamespace(ask=1.10, bid=1.09))
        mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume", "type", "price")),
                                    order_check=Mock(return_value=FakeMT5Response(retcode=0, comment="done")),
                                    order_send=Mock(return_value=FakeMT5Response(retcode=10009, comment="done")))
        trader = object.__new__(ConcreteSyncTrader)
        trader.symbol = symbol
        trader.order = SyncOrder(symbol="EURUSD")
        trader.order.mt5 = mt5
        with patch.object(SyncOrder, "mt5", mt5, create=True):
            with self.assertRaises(InvalidVolume):
                trader.create_order_no_stops(order_type=0, volume=0.001)
            trader.create_order_no_stops(order_type=0, volume=1.2)
            self.assertEqual(trader.order.volume, 1.0)
            trader.send_order()
        self.assertEqual(mt5.order_send.call_args.args[0]["volume"], 1.0)
        mt5.order_send.assert_called_once()

    def test_sync_direct_order_send_requires_successful_check(self):
        for response in (FakeMT5Response(retcode=10016, comment="invalid stops"), None):
            with self.subTest(response=response):
                mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume")),
                                            order_check=Mock(return_value=response), order_send=Mock())
                order = SyncOrder(symbol="EURUSD", volume=0.1)
                order.mt5 = mt5
                if response is None:
                    with self.assertRaises(OrderError):
                        order.check()
                else:
                    self.assertEqual(order.check().retcode, 10016)
                with self.assertRaises(OrderError):
                    order.send()
                mt5.order_send.assert_not_called()

    def test_sync_check_exception_blocks_direct_and_trader_send(self):
        class ConcreteSyncTrader(SyncTrader):
            def place_trade(self, *args, **kwargs):
                raise NotImplementedError

        failure = ConnectionError("check unavailable")
        mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume")),
                                    order_check=Mock(side_effect=failure), order_send=Mock())
        trader = object.__new__(ConcreteSyncTrader)
        trader.symbol = FakeSymbol()
        trader.order = SyncOrder(symbol="EURUSD", volume=0.1)
        trader.order.mt5 = mt5
        with self.assertRaises(ConnectionError) as caught:
            trader.order.send()
        self.assertIs(caught.exception, failure)
        with self.assertRaises(ConnectionError):
            trader.check_order()
        self.assertIsNone(trader.send_order())
        mt5.order_send.assert_not_called()

    def test_sync_trader_rejection_is_falsy_and_blocks_send(self):
        class ConcreteSyncTrader(SyncTrader):
            def place_trade(self, *args, **kwargs):
                raise NotImplementedError

        for response in (FakeMT5Response(retcode=10016, comment="invalid stops"), None):
            with self.subTest(response=response):
                mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume")),
                                            error="offline error", order_check=Mock(return_value=response),
                                            order_send=Mock())
                trader = object.__new__(ConcreteSyncTrader)
                trader.symbol = FakeSymbol()
                trader.order = SyncOrder(symbol="EURUSD", volume=0.1)
                trader.order.mt5 = mt5
                if response is None:
                    with self.assertRaises(OrderError):
                        trader.check_order()
                else:
                    self.assertIsNone(trader.check_order())
                self.assertIsNone(trader.send_order())
                mt5.order_send.assert_not_called()

    def test_sync_stale_trader_check_cannot_send_after_rejection(self):
        class ConcreteSyncTrader(SyncTrader):
            def place_trade(self, *args, **kwargs):
                raise NotImplementedError

        mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume")),
                                    order_check=Mock(side_effect=[FakeMT5Response(retcode=0, comment="done"),
                                                                  FakeMT5Response(retcode=10016, comment="invalid stops")]),
                                    order_send=Mock())
        trader = object.__new__(ConcreteSyncTrader)
        trader.symbol = FakeSymbol()
        trader.order = SyncOrder(symbol="EURUSD", volume=0.1)
        trader.order.mt5 = mt5
        self.assertIsNotNone(trader.check_order())
        with self.assertRaises(OrderError):
            trader.send_order()
        mt5.order_send.assert_not_called()

    def test_sync_trader_send_without_prior_check_still_rejects(self):
        class ConcreteSyncTrader(SyncTrader):
            def place_trade(self, *args, **kwargs):
                raise NotImplementedError

        mt5 = types.SimpleNamespace(TradeRequest=types.SimpleNamespace(__match_args__=("symbol", "volume")),
                                    order_check=Mock(return_value=FakeMT5Response(retcode=10016,
                                                                                   comment="invalid stops")),
                                    order_send=Mock())
        trader = object.__new__(ConcreteSyncTrader)
        trader.symbol = FakeSymbol()
        trader.order = SyncOrder(symbol="EURUSD", volume=0.1)
        trader.order.mt5 = mt5
        with self.assertRaises(OrderError):
            trader.send_order()
        mt5.order_send.assert_not_called()


if __name__ == "__main__":
    unittest.main()
