"""Cung cấp bộ giao dịch lướt sóng không đặt mức dừng."""

from logging import getLogger

from ...core.models import OrderType
from ...core.exceptions import OrderSendAmbiguous
from ...lib.trader import Trader

logger = getLogger(__name__)


class ScalpTrader(Trader):
    """Đặt lệnh lướt sóng mà không cấu hình mức dừng."""
    async def place_trade(self, *, order_type: OrderType, volume: float = None, parameters: dict = None):
        """Tạo, kiểm tra và gửi lệnh giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        try:
            self.parameters |= parameters or {}
            volume = self.symbol.volume_min if volume is None else volume
            await self.create_order_no_stops(order_type=order_type, volume=volume)
            if not await self.check_order():
                return
            self.order.comment = self.parameters.get("name", self.__class__.__name__)
            res = await self.send_order()
            if res is not None:
                await self.record_trade(result=res, parameters=self.parameters)
            self.reset_order()
        except OrderSendAmbiguous:
            raise
        except Exception as err:
            logger.error(f"{err} in {self.__class__.__name__}.place_trade for {self.symbol.name}")
