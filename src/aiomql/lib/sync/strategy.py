"""Cung cấp lớp nền để xây dựng chiến lược đồng bộ."""

import time
from datetime import time as dtime
from logging import getLogger

from .sessions import Sessions, Session
from .symbol import Symbol
from ...core import Config
from ...core.exceptions import StopTrading, OrderSendAmbiguous
from ...core.meta_trader import MetaTrader
from ..strategy import Strategy as BaseStrategy


logger = getLogger(__name__)


class Strategy(BaseStrategy):
    """Lớp nền để xây dựng và vận hành chiến lược giao dịch."""
    name: str
    symbol: Symbol
    sessions: Sessions
    mt5: MetaTrader
    config: Config
    running: bool
    parameters = {}
    current_session = Session

    def __init__(self, *, symbol: Symbol, params: dict = None, sessions: Sessions = None, name=""):
        """Khởi tạo `Strategy`; phối hợp với `Config`."""
        self.parameters = {**self.parameters} | (params or {})
        self.symbol = symbol
        self.name = name or self.__class__.__name__
        self.parameters["symbol"] = symbol.name
        self.parameters["name"] = self.name
        self.running = True
        self.sessions = sessions or Sessions(sessions=[Session(start=0, end=dtime(hour=23, minute=59, second=59))])
        self.config = Config()
        self.mt5 = MetaTrader()

    def __repr__(self):
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Strategy`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return f"{self.name}({self.symbol!r})"

    def __getattr__(self, item):
        """Chuyển tiếp việc đọc thuộc tính chưa có của `Strategy`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        if item in self.parameters:
            return self.parameters[item]
        raise AttributeError(f"{item} not an attribute of {self.name}")

    def __setattr__(self, key, value):
        """Kiểm soát việc gán thuộc tính của `Strategy`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        if key in self.parameters:
            self.parameters[key] = value
        super().__setattr__(key, value)

    def __enter__(self):
        """Mở ngữ cảnh đồng bộ của `Strategy`; phối hợp với `Sessions.check`."""
        self.sessions.check()
        self.running = True
        self.current_session = self.sessions.current_session

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh đồng bộ của `Strategy`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        try:
            self.current_session.close() if self.current_session else ...
            self.running = False
        except OrderSendAmbiguous:
            self.running = False
            raise
        except Exception as err:
            logger.error(f"Error: {err}")

    def initialize(self):
        """Khởi tạo dữ liệu và tài nguyên của `Strategy`; phối hợp với `Symbol.initialize_sync`."""
        return self.symbol.initialize_sync()

    @staticmethod
    def live_sleep(*, secs: float):
        """Tạm dừng theo thời gian thực; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        mod = time.time() % secs
        secs = secs - mod if mod != 0 else mod
        time.sleep(secs + 0.1)

    def sleep(self, *, secs: float):
        """Tạm dừng theo chế độ chạy thật hoặc kiểm thử dữ liệu quá khứ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        self.live_sleep(secs=secs)

    def delay(self, *, secs: float):
        """Dịch thời gian mô phỏng khi đang kiểm thử dữ liệu quá khứ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        time.sleep(secs)

    def run_strategy(self):
        """Chạy vòng lặp giao dịch của một chiến lược; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        self.live_strategy()

    def live_strategy(self):
        """Chạy vòng lặp chiến lược trên tài khoản thật; phối hợp với `Sessions.check`."""
        with self as _:
            logger.info("Running %s strategy on %s", self.name, self.symbol.name)
            while self.running:
                try:
                    self.sessions.check()
                    self.trade()

                except OrderSendAmbiguous:
                    self.running = False
                    raise

                except StopTrading:
                    self.running = False
                    break

                except Exception as err:
                    logger.error("Error: %s in live_strategy", err)
                    self.running = False
                    break

    def trade(self):
        """Thực thi một chu kỳ của chiến lược giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        raise NotImplementedError("Implement this method in your subclass")

    def test(self):
        """Thực thi chiến lược ở chế độ kiểm thử; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        self.trade()
