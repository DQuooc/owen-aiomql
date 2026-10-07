from datetime import datetime
from dataclasses import dataclass
from typing import Literal

from ...core.constants import OrderType


@dataclass
class StrategyTracker:
    """Lưu và cập nhật dữ liệu trạng thái của chiến lược."""
    trend: Literal["ranging", "bullish", "bearish"] = "ranging"
    bullish: bool = False
    bearish: bool = False
    ranging: bool = True
    snooze: float = 0
    trend_time: float = 0
    entry_time: float = 0
    last_trend_price: float = 0
    last_entry_price: float = 0
    new: bool = True
    order_type: OrderType = None
    sl: float = 0
    tp: float = 0

    @property
    def time(self):
        """Lấy thời gian hiện tại của bộ theo dõi; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return datetime.now()

    @property
    def timestamp(self):
        """Lấy dấu thời gian hiện tại của bộ theo dõi; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return self.time.timestamp()

    def update(self, **kwargs):
        """Cập nhật dữ liệu của `StrategyTracker`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        fields = self.__dict__
        for key in kwargs:
            if key in fields:
                setattr(self, key, kwargs[key])
        if "trend" in kwargs:
            match self.trend:
                case "ranging":
                    self.ranging = True
                    self.bullish = self.bearish = False
                case "bullish":
                    self.ranging = self.bearish = False
                    self.bullish = True
                case "bearish":
                    self.ranging = self.bullish = False
                    self.bearish = True
