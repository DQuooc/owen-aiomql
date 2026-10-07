"""Quản lý thông tin và trạng thái tài khoản giao dịch."""

from threading import Lock
from logging import getLogger
from typing import Self, ClassVar

from ..core.base import _Base
from ..core.models import AccountInfo
from ..core.exceptions import LoginError

logger = getLogger(__name__)


class Account(_Base, AccountInfo):
    """Quản lý một thể hiện tài khoản giao dịch dùng chung."""

    _instance: Self
    _lock: ClassVar[Lock]
    connected: bool

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `Account`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        with (lock := Lock()) as _:
            if not hasattr(cls, "_instance"):
                cls._lock = lock
                cls._instance = super().__new__(cls)
                cls._instance.connected = False
                cls._instance.exclude.add("_lock")
        return cls._instance

    async def __aenter__(self) -> Self:
        """Mở ngữ cảnh bất đồng bộ của `Account`; gọi `MetaTrader.initialize`, `MetaTrader.login`."""
        await self.mt5.initialize()
        self.connected = await self.mt5.login()
        if not self.connected:
            raise LoginError(f"Login failed: {self.mt5.error}")
        await self.refresh()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh bất đồng bộ của `Account`; gọi `MetaTrader.shutdown`."""
        await self.mt5.shutdown()
        self.connected = False

    def __enter__(self) -> Self:
        """Mở ngữ cảnh đồng bộ của `Account`; gọi `MetaTrader.initialize_sync`, `MetaTrader.login_sync`."""
        self.mt5.initialize_sync()
        self.connected = self.mt5.login_sync()
        if not self.connected:
            raise LoginError(f"Login failed: {self.mt5.error}")
        self.refresh_sync()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh đồng bộ của `Account`; gọi `MetaTrader._shutdown`."""
        self.mt5._shutdown()
        self.connected = False

    async def refresh(self):
        """Làm mới dữ liệu của `Account`; gọi `MetaTrader.account_info`."""
        account_info = await self.mt5.account_info()
        acc = account_info._asdict()
        self.connected = True
        self.set_attributes(**acc)

    def refresh_sync(self):
        """Làm mới dữ liệu của `Account` theo luồng đồng bộ; gọi `MetaTrader._account_info`."""
        account_info = self.mt5._account_info()
        acc = account_info._asdict()
        self.connected = True
        self.set_attributes(**acc)

