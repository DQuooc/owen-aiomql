"""Tính toán và kiểm soát mức rủi ro cho mỗi giao dịch."""

from .account import Account
from .positions import Positions


class RAM:
    account: Account
    risk_to_reward: float
    risk: float
    fixed_amount: float | None
    min_amount: float
    max_amount: float
    loss_limit: int
    open_limit: int
    positions: Positions

    def __init__(self, **kwargs):
        """Khởi tạo `RAM`; phối hợp với `Account` và `Positions`."""
        self.account = Account()
        self.positions = Positions()
        self.risk_to_reward = kwargs.get("risk_to_reward", 2)
        self.risk = kwargs.get("risk", 1)
        self.min_amount = kwargs.get("min_amount", 0)
        self.max_amount = kwargs.get("max_amount", 0)
        self.loss_limit = kwargs.get("loss_limit", 3)
        self.open_limit = kwargs.get("open_limit", 3)
        self.fixed_amount = kwargs.get("fixed_amount", None)

    def modify_ram(self, **kwargs):
        """Cập nhật các giới hạn quản trị rủi ro; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        [setattr(self, key, value) for key, value in kwargs.items()]

    def get_amount_sync(self) -> float:
        """Tính số tiền rủi ro theo luồng đồng bộ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        if self.fixed_amount:
            return self.fixed_amount
        self.account.refresh_sync()
        amount = self.account.margin_free * (self.risk / 100)
        if self.min_amount and self.max_amount:
            return max(self.min_amount, min(self.max_amount, amount))
        return amount

    async def get_amount(self) -> float:
        """Tính số tiền được phép rủi ro cho một giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        if self.fixed_amount:
            return self.fixed_amount
        await self.account.refresh()
        amount = self.account.margin_free * (self.risk / 100)
        if self.min_amount and self.max_amount:
            return max(self.min_amount, min(self.max_amount, amount))
        return amount

    async def check_losing_positions(self) -> bool:
        """Kiểm tra số vị thế đang lỗ còn trong giới hạn; gọi `MetaTrader.positions_get`."""
        positions = await self.account.mt5.positions_get()
        loosing = [position for position in positions if position.profit <= 0]
        return len(loosing) <= self.loss_limit

    async def check_open_positions(self) -> bool:
        """Kiểm tra số vị thế đang mở còn trong giới hạn; gọi `MetaTrader.positions_get`."""
        positions = await self.account.mt5.positions_get()
        return len(positions) <= self.open_limit

    def check_losing_positions_sync(self) -> bool:
        """Kiểm tra đồng bộ số vị thế đang lỗ; gọi `MetaTrader._positions_get`."""
        positions = self.account.mt5._positions_get()
        loosing = [position for position in positions if position.profit <= 0]
        return len(loosing) <= self.loss_limit

    def check_open_positions_sync(self) -> bool:
        """Kiểm tra đồng bộ số vị thế đang mở; gọi `MetaTrader._positions_get`."""
        positions = self.account.mt5._positions_get()
        return len(positions) <= self.open_limit
