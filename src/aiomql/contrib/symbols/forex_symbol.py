"""Mở rộng công cụ tài chính cho giao dịch ngoại hối."""

from ...lib.symbol import Symbol


class ForexSymbol(Symbol):
    """Mở rộng Symbol với cách tính pip và khối lượng ngoại hối."""

    @property
    def pip(self) -> float:
        """Tính kích thước một pip của mã giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return self.point * 10

    def compute_points(self, *, amount: float, volume: float) -> float:
        """Tính số điểm giá; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        points = amount / (volume * self.point * self.trade_contract_size)
        return points

    async def compute_volume_points(self, *, amount: float, points: float, round_down: bool = False) -> float:
        """Tính khối lượng giao dịch số điểm giá; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        volume = amount / (self.point * points * self.trade_contract_size)
        return self.round_off_volume(volume=volume, round_down=round_down)

    async def compute_volume_sl(self, *, amount: float, price: float, sl: float, round_down: bool = False) -> float:
        """Tính khối lượng giao dịch mức dừng lỗ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        volume = amount / (abs(price - sl) * self.trade_contract_size)
        return self.round_off_volume(volume=volume, round_down=round_down)
