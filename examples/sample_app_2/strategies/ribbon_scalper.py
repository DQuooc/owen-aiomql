from aiomql import Strategy, ForexSymbol, TimeFrame, OrderType, Tracker, Trader
from ..traders.rs_trader import RSTrader

class RibbonScalper(Strategy):
    """Chiến lược lướt sóng dựa trên giao cắt của dải EMA."""
    fast_ema: int # Đường trung bình động nhanh
    medium_ema: int  # Đường trung bình động trung hạn
    slow_ema: int   # Đường trung bình động chậm
    time_frame: TimeFrame # Khung thời gian
    candles_count: int # Số kỳ dữ liệu nhìn lại
    tracker: Tracker # Bộ theo dõi trạng thái
    pips_target: int  # Số pip lợi nhuận mục tiêu
    interval: int # Khoảng nghỉ giữa hai lần chạy, tính bằng giây

    parameters = {"fast_ema": 5, "medium_ema": 8, "slow_ema": 13, "time_frame": TimeFrame.M1,
                  "candles_count": 120, "pips_target": 10, "interval": 30}

    def __init__(self, *, symbol: ForexSymbol, params: dict = None, trader: Trader = None, name="RibbonScalper"):
        """Khởi tạo `RibbonScalper`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        super().__init__(symbol=symbol, params=params, name=name)
        self.tracker = Tracker()
        self.trader = trader or RSTrader(symbol=symbol)
        self.interval = self.time_frame.seconds

    async def find_entry(self):
        """Tìm tín hiệu và mức giá vào lệnh; phối hợp với `Symbol.copy_rates_from_pos` và bộ theo dõi vị thế."""
        rates = await self.symbol.copy_rates_from_pos(count=self.candles_count, timeframe=self.time_frame)
        rates.ta.ema(length=self.fast_ema, append=True)
        rates.ta.ema(length=self.medium_ema, append=True)
        rates.ta.ema(length=self.slow_ema, append=True)
        rates.rename(**{f"EMA_{self.fast_ema}": "fast", f"EMA_{self.medium_ema}": "medium", f"EMA_{self.slow_ema}": "slow"})
        find_long_fast = rates.ta_lib.cross(rates.fast, rates.slow)
        find_long_medium = rates.ta_lib.cross(rates.medium, rates.slow)

        if find_long_fast.iloc[-1]  and find_long_medium.iloc[-1]:
            self.tracker.update(order_type=OrderType.BUY, trend="bullish", sl=rates[-2].low, snooze=300)
            return

        find_short_fast = rates.ta_lib.cross(rates.fast, rates.slow, above=False)
        find_short_medium = rates.ta_lib.cross(rates.medium, rates.slow, above=False)

        if find_short_fast.iloc[-1] and find_short_medium.iloc[-1]:
            self.tracker.update(order_type=OrderType.SELL, trend="bearish", sl=rates[-2].high, snooze=300)
            return

        self.tracker.update(order_type=None, trend="ranging", snooze=self.interval)

    async def trade(self):
        """Thực thi một chu kỳ của chiến lược giao dịch; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        await self.find_entry()
        if self.tracker.order_type is not None:
            await self.trader.place_trade(parameters=self.parameters, order_type=self.tracker.order_type,
                                          sl=self.tracker.sl, pips_target=self.pips_target)
            await self.sleep(secs=self.tracker.snooze)
            return
        else:
            await self.sleep(secs=self.tracker.snooze)