from aiomql import Strategy, ForexSymbol, TimeFrame, Tracker, OrderType, Sessions, Trader

from .traders import TestTrader

class EMAXOver(Strategy):
    ttf: TimeFrame  # Khung thời gian của chiến lược
    tcc: int  # Số nến dùng để phân tích
    fast_ema: int  # Chu kỳ đường trung bình động nhanh
    slow_ema: int  # Chu kỳ đường trung bình động chậm
    tracker: Tracker  # Bộ theo dõi trạng thái chiến lược
    interval: TimeFrame  # Khoảng thời gian giữa các lần kiểm tra tín hiệu vào và thoát lệnh
    timeout: int  # Thời gian chờ sau khi đặt lệnh, tính bằng giây

    # Tham số mặc định của chiến lược
    # Các tham số được gán thành thuộc tính và có thể ghi đè qua đối số params khi khởi tạo.
    parameters = {'ttf': TimeFrame.M10, 'tcc': 3000, 'fast_ema': 34, 'slow_ema': 55, 'interval': TimeFrame.M5,
                  'timeout': 120}

    def __init__(self, *, symbol: ForexSymbol, params: dict | None = None, trader: Trader = None,
                 sessions: Sessions = None, name: str = "EMAXOver"):
        """Khởi tạo `EMAXOver`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        super().__init__(symbol=symbol, params=params, sessions=sessions, name=name)
        self.tracker = Tracker(snooze=self.interval.seconds)
        self.trader = trader or TestTrader(symbol=self.symbol)

    async def find_entry(self):
        # Lấy dữ liệu nến
        """Tìm tín hiệu và mức giá vào lệnh; phối hợp với `Symbol.copy_rates_from_pos` và bộ theo dõi vị thế."""
        candles = await self.symbol.copy_rates_from_pos(timeframe=self.ttf, count=self.tcc)

        # Tính đường trung bình động nhanh
        candles.ta.ema(length=self.fast_ema, append=True)
        # Tính đường trung bình động chậm
        candles.ta.ema(length=self.slow_ema, append=True)
        # Đổi tên các cột
        candles.rename(**{f"EMA_{self.fast_ema}": "fast_ema", f"EMA_{self.slow_ema}": "slow_ema"}, inplace=True)

        # Kiểm tra giao cắt
        # Đường nhanh cắt lên đường chậm
        fas = candles.ta_lib.above(candles.fast_ema, candles.slow_ema)
        # Đường nhanh cắt xuống đường chậm
        fbs = candles.ta_lib.below(candles.fast_ema, candles.slow_ema)

        # Kiểm tra tín hiệu vào lệnh trên nến hiện tại
        if fas.iloc[-1]:
            self.tracker.update(order_type=OrderType.BUY, snooze=self.timeout)
        elif fbs.iloc[-1]:
            self.tracker.update(order_type=OrderType.SELL, snooze=self.timeout)
        else:
            self.tracker.update(order_type=None, snooze=self.interval.seconds)

    async def trade(self):
        """Thực thi một chu kỳ của chiến lược giao dịch; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        await self.find_entry()
        if self.tracker.order_type is None:
            await self.sleep(secs=self.tracker.snooze)
        else:
            await self.trader.place_trade(order_type=self.tracker.order_type, parameters=self.parameters)
            await self.delay(secs=self.tracker.snooze)
