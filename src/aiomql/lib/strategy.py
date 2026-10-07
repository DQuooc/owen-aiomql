"""Cung cấp lớp nền để xây dựng chiến lược giao dịch."""

import asyncio
import time
from abc import ABC
from datetime import time as dtime
from logging import getLogger

from .sessions import Sessions, Session
from .symbol import Symbol
from ..core import Config
from ..core.exceptions import StopTrading, OrderSendAmbiguous
from ..core.meta_trader import MetaTrader

logger = getLogger(__name__)


class Strategy(ABC):
    """Lớp nền để xây dựng và vận hành chiến lược giao dịch."""

    """
Lớp cơ sở để tạo các chiến lược giao dịch.

Thuộc tính:



    name → tên chiến lược

symbol → mã giao dịch (EURUSD, XAUUSD…)

parameters → tham số tùy chỉnh

sessions → phiên giao dịch áp dụng

running → trạng thái chạy/dừng

current_session → phiên hiện tại

mt5 → kết nối MetaTrader 5

config → cấu hình tổng thể

Ghi chú:
    Đặt tên cho chiến lược dưới dạng thuộc tính lớp. 
    Nếu không được cung cấp, tên lớp sẽ được dùng làm tên chiến lược.
"""



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

    async def __aenter__(self):
        """Mở ngữ cảnh bất đồng bộ của `Strategy`; phối hợp với `Sessions.check`."""
        await self.sessions.check()
        self.running = True
        self.current_session = self.sessions.current_session

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh bất đồng bộ của `Strategy`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        try:
            await self.current_session.close() if self.current_session else ...
            self.running = False
        except OrderSendAmbiguous:
            self.running = False
            raise
        except Exception as err:
            logger.error(f"Error: {err}")

    async def initialize(self):
        """Khởi tạo dữ liệu và tài nguyên của `Strategy`; phối hợp với `Symbol.initialize`."""
        return await self.symbol.initialize()

    def initialize_sync(self):
        """Khởi tạo `Strategy` theo luồng đồng bộ; phối hợp với `Symbol.initialize_sync`."""
        return self.symbol.initialize_sync()

    @staticmethod
    async def live_sleep(*, secs: float):
        """Tạm dừng theo thời gian thực; phối hợp các tác vụ qua `asyncio`."""
        mod = time.time() % secs
        secs = secs - mod if mod != 0 else mod
        await asyncio.sleep(secs + 0.1)

    async def sleep(self, *, secs: float):
        """Tạm dừng theo chế độ chạy thật hoặc kiểm thử dữ liệu quá khứ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.live_sleep(secs=secs)

    async def delay(self, *, secs: float):
        """Dịch thời gian mô phỏng khi đang kiểm thử dữ liệu quá khứ; phối hợp các tác vụ qua `asyncio`."""
        await asyncio.sleep(secs)

    async def run_strategy(self):
        """Chạy vòng lặp giao dịch của một chiến lược; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.live_strategy()

    async def live_strategy(self):
        """Chạy vòng lặp chiến lược trên tài khoản thật; phối hợp với `Sessions.check`."""
        async with self as _:
            logger.info("Running %s strategy on %s", self.name, self.symbol.name)
            while self.running:
                try:
                    await self.sessions.check()
                    await self.trade()

                except OrderSendAmbiguous:
                    self.running = False
                    raise

                except StopTrading:
                    self.running = False
                    break

                except asyncio.CancelledError:
                    self.running = False
                    break

                except Exception as err:
                    logger.error("Error: %s in live_strategy", err)
                    self.running = False
                    break

    async def trade(self):
        """Thực thi một chu kỳ của chiến lược giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        raise NotImplementedError("Implement this method in your subclass")

    async def test(self):
        """Thực thi chiến lược ở chế độ kiểm thử; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.trade()
