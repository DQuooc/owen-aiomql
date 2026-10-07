"""Cung cấp bộ giao dịch đơn giản có mức dừng lỗ."""

from logging import getLogger

from ...core.models import OrderType
from ...core.exceptions import OrderSendAmbiguous
from ...lib.trader import Trader

logger = getLogger(__name__)


class SimpleTrader(Trader):
    """Đặt lệnh giao dịch từ một mức dừng lỗ cho trước."""
    async def place_trade(self, *, order_type: OrderType, sl: float, parameters: dict = None):
        """Tạo, kiểm tra và gửi lệnh giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        try:
            self.parameters |= parameters or {}
            await self.create_order_with_sl(order_type=order_type, sl=sl)
            if not await self.check_order():
                return
            self.order.comment = self.parameters.get("name", self.__class__.__name__)
            await self.send_order()
            self.reset_order()
        except OrderSendAmbiguous:
            raise
        except Exception as err:
            logger.error(f"{err} in {self.__class__.__name__}.place_trade for {self.symbol.name}")
