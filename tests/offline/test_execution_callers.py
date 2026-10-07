"""Exercise example callers with real execution methods and a fake MT5 SDK."""

import sys
import types
import unittest
from unittest.mock import AsyncMock, patch

from test_order_check_contract import FakeMT5Response, FakeSymbol, Order, Trader, load_source, module
from test_order_send_safety import MetaTrader, OrderSendAmbiguous, reset_sdk, sdk


EXAMPLES = "_aiomql_examples_offline"
for package in (EXAMPLES, f"{EXAMPLES}.traders", f"{EXAMPLES}.trackers"):
    module(package).__path__ = []

api = types.ModuleType("aiomql")
api.Trader = Trader
api.OrderType = object
api.OrderSendAmbiguous = OrderSendAmbiguous
for name in ("OpenPosition", "Positions", "PositionTracker", "Store", "exit_at_profit", "round_off"):
    setattr(api, name, object)

with patch.dict(sys.modules, {"aiomql": api}):
    example_trackers = load_source(f"{EXAMPLES}.trackers.track", "examples/sample_app/trackers/track.py")
    for name in ("close_after", "hedge_position", "track_hedges"):
        setattr(sys.modules[f"{EXAMPLES}.trackers"], name, getattr(example_trackers, name))
    ExampleTrader = load_source(f"{EXAMPLES}.traders.test_trader",
                               "examples/sample_app/traders/test_trader.py").TestTrader
    RSTrader = load_source(f"{EXAMPLES}.traders.rs_trader",
                          "examples/sample_app_2/traders/rs_trader.py").RSTrader


class ExampleExecutionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        reset_sdk()
        sdk.order_send.return_value = FakeMT5Response(retcode=10009, comment="done")
        self.mt5 = MetaTrader()
        self.mt5.initialize = AsyncMock(return_value=True)
        self.mt5.login = AsyncMock(return_value=True)
        self.enterContext(patch.object(Order, "mt5", self.mt5, create=True))
        self.enterContext(patch.object(sys.modules[Trader.__module__], "OrderType",
                                       types.SimpleNamespace(BUY=0, SELL=1)))

    def make_trader(self, cls):
        trader = object.__new__(cls)
        trader.symbol = FakeSymbol()
        trader.parameters = {}
        trader.order = Order(symbol="EURUSD", volume=0.1, price=1.0, type=0)
        trader.ram = types.SimpleNamespace(get_amount=AsyncMock(return_value=100))
        trader.record_trade = AsyncMock()
        if cls is ExampleTrader:
            trader.create_order_no_stops = AsyncMock()
        else:
            trader.create_order = AsyncMock()
        return trader

    async def test_example_traders_preserve_unknown_outcome(self):
        for cls, params in ((ExampleTrader, {"volume": 0.1}), (RSTrader, {"sl": 0.9})):
            with self.subTest(caller=cls.__name__):
                reset_sdk()
                sdk.order_send.return_value = None
                trader = self.make_trader(cls)
                with self.assertRaises(OrderSendAmbiguous):
                    await trader.place_trade(order_type=0, **params)
                sdk.order_send.assert_called_once()
                trader.record_trade.assert_not_awaited()

    async def test_example_traders_rejected_check_never_reaches_native_send(self):
        for cls, params in ((ExampleTrader, {"volume": 0.1}), (RSTrader, {"sl": 0.9})):
            with self.subTest(caller=cls.__name__):
                reset_sdk()
                sdk.order_check.return_value = FakeMT5Response(retcode=10016, comment="invalid stops")
                trader = self.make_trader(cls)
                await trader.place_trade(order_type=0, **params)
                sdk.order_check.assert_called_once()
                sdk.order_send.assert_not_called()
                trader.record_trade.assert_not_awaited()

    async def test_failed_rs_order_creation_cannot_send_previous_order(self):
        trader = self.make_trader(RSTrader)
        del trader.create_order  # Use the actual example implementation.
        trader.ram.get_amount.side_effect = ValueError("risk amount unavailable")
        await trader.place_trade(order_type=0, sl=0.9)
        sdk.order_send.assert_not_called()
        trader.record_trade.assert_not_awaited()

    async def test_example_zero_volume_is_rejected_instead_of_replaced(self):
        trader = self.make_trader(ExampleTrader)
        del trader.create_order_no_stops
        trader.symbol.info_tick = AsyncMock(return_value=types.SimpleNamespace(ask=1.1, bid=1.0))
        await trader.place_trade(order_type=0, volume=0)
        sdk.order_send.assert_not_called()

    async def test_example_hedge_tracker_preserves_unknown_close(self):
        error = OrderSendAmbiguous(request={"symbol": "EURUSD", "position": 123})
        hedge = types.SimpleNamespace(is_open=True, position=types.SimpleNamespace(profit=-20),
                                      update_position=AsyncMock(return_value=True),
                                      close_position=AsyncMock(side_effect=error))
        position = types.SimpleNamespace(update_position=AsyncMock(return_value=True), hedges={123: hedge})
        with self.assertRaises(OrderSendAmbiguous) as caught:
            await example_trackers.track_hedges(position)
        self.assertIs(caught.exception, error)
        hedge.close_position.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
