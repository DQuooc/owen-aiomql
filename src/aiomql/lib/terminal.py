"""Truy xuất thông tin phần mềm đầu cuối MetaTrader5."""

from typing import NamedTuple
from logging import getLogger

from ..core.models import TerminalInfo
from ..core.base import _Base

logger = getLogger(__name__)

Version = NamedTuple("Version", (("version", str), ("build", int), ("release_date", str)))


class Terminal(_Base, TerminalInfo):
    """Truy xuất thông tin phần mềm đầu cuối MetaTrader5."""

    version: Version | None = None

    async def initialize(self) -> bool:
        """Khởi tạo dữ liệu và tài nguyên của `Terminal`; gọi `MetaTrader.initialize`, `MetaTrader.last_error`."""
        self.connected = await self.mt5.initialize()
        if not self.connected:
            err = await self.mt5.last_error()
            logger.warning(f"Failed to initialize Terminal. Error Code: {err}")
        info = await self.info()
        await self.get_version()
        return bool(self.connected and info and self.version)

    async def get_version(self) -> Version | None:
        """Lấy phiên bản phần mềm đầu cuối MetaTrader; gọi `MetaTrader.version`."""
        res = await self.mt5.version()
        if res is None:
            logger.error("Failed to get terminal version")
            return None
        self.version = Version(*res)
        return self.version

    async def info(self) -> TerminalInfo | None:
        """Lấy thông tin hiện tại của đối tượng; gọi `MetaTrader.terminal_info`."""
        info = await self.mt5.terminal_info()
        if info:
            self.set_attributes(**info._asdict())
        return info

    async def symbols_total(self) -> int:
        """Lấy tổng số mã giao dịch từ MetaTrader; gọi `MetaTrader.symbols_total`."""
        return await self.mt5.symbols_total()

    def initialize_sync(self) -> bool:
        """Khởi tạo `Terminal` theo luồng đồng bộ; gọi `MetaTrader.initialize_sync`, `MetaTrader._last_error`."""
        self.connected = self.mt5.initialize_sync()
        if not self.connected:
            err = self.mt5._last_error()
            logger.warning(f"Failed to initialize Terminal. Error Code: {err}")
        info = self.info_sync()
        self.get_version_sync()
        return bool(self.connected and info and self.version)

    def get_version_sync(self) -> Version | None:
        """Lấy phiên bản phần mềm đầu cuối theo luồng đồng bộ; gọi `MetaTrader._version`."""
        res = self.mt5._version()
        if res is None:
            logger.error("Failed to get terminal version")
            return None
        self.version = Version(*res)
        return self.version

    def info_sync(self) -> TerminalInfo | None:
        """Lấy thông tin hiện tại theo luồng đồng bộ; gọi `MetaTrader._terminal_info`."""
        info = self.mt5._terminal_info()
        if info:
            self.set_attributes(**info._asdict())
        return info

    def symbols_total_sync(self) -> int:
        """Lấy tổng số mã giao dịch theo luồng đồng bộ; gọi `MetaTrader._symbols_total`."""
        return self.mt5._symbols_total()
