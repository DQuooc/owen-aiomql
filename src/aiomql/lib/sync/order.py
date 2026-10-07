"""Tạo, kiểm tra và gửi lệnh theo luồng đồng bộ."""

from logging import getLogger

from ...core.models import TradeRequest, TradeOrder, OrderCheckResult, OrderSendResult
from ...core.constants import TradeAction, OrderTime, OrderFilling, OrderType, TradeRetcode
from ...core.exceptions import OrderError, OrderSendAmbiguous
from ...core.base import _Base
from ...utils import error_handler_sync, decrease_value_by_pct, increase_value_by_pct

logger = getLogger(__name__)



class Order(_Base, TradeRequest):
    mode: str = "sync"
    """Trade order related functions and properties. Subclass of TradeRequest."""
    def __init__(self, **kwargs):
        """Khởi tạo `Order`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        kwargs = {"action": TradeAction.DEAL, "type_time": OrderTime.DAY, "type_filling": OrderFilling.FOK, **kwargs}
        super().__init__(**kwargs)

    def modify(self, **kwargs):
        """Cập nhật thuộc tính của `Order`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        self.set_attributes(**kwargs)

    @classmethod
    def orders_total(cls):
        """Lấy tổng số lệnh chờ đang hoạt động; gọi `MetaTrader.orders_total`."""
        return cls.mt5.orders_total()

    @classmethod
    def get_pending_order(cls, *, ticket: int) -> TradeOrder | None:
        """Lấy một lệnh chờ theo mã định danh; gọi `MetaTrader.orders_get`."""
        orders = cls.mt5.orders_get(ticket=ticket)
        for order_ in orders:
            if order_.ticket == ticket:
                return TradeOrder(**order_._asdict())
        return None

    @classmethod
    def get_pending_orders(cls, *, ticket: int = 0, symbol: str = "", group: str = "") -> tuple[TradeOrder, ...]:
        """Lấy các lệnh chờ theo điều kiện; gọi `MetaTrader.orders_get`."""
        orders = cls.mt5.orders_get(symbol=symbol, ticket=ticket, group=group)
        if orders is not None:
            return tuple(TradeOrder(**order._asdict()) for order in orders)
        return tuple()

    @classmethod
    def cancel_order(cls, *, order: int, symbol: str = "") -> OrderSendResult:
        """Hủy lệnh; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        res = cls.send_order(request={"order": order, "action": TradeAction.REMOVE, "symbol": symbol})
        if res is None:
            raise OrderError("Unable to cancel order %d:%s" % (order, symbol))
        return res

    def check(self, **kwargs) -> OrderCheckResult:
        """Kiểm tra tính hợp lệ hoặc trạng thái của `Order`; gọi `MetaTrader.order_check`."""
        req = self.request | kwargs
        res = self.mt5.order_check(req)
        if res is None:
            raise OrderError(f"Order check failed for {self.symbol}")
        return OrderCheckResult(**res._asdict())

    def send(self) -> OrderSendResult:
        """Gửi yêu cầu lệnh hiện tại tới MetaTrader; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        request = self.request
        check = self.check(**request)
        if check is None or check.retcode != 0:
            raise OrderError(f"Order check rejected for {self.symbol}: {getattr(check, 'comment', '')}")
        return self.send_order(request=request)

    @classmethod
    def send_order(cls, *, request: dict, connection_retries=0) -> OrderSendResult:
        """Send once; propagate OrderSendAmbiguous for an unconfirmed outcome.

        ``connection_retries`` is retained for compatibility and no longer enables retries.
        """
        res = cls.mt5.order_send(request)
        if res is None or getattr(res, "retcode", None) in (None, TradeRetcode.TIMEOUT, TradeRetcode.CONNECTION):
            raise OrderSendAmbiguous(request=request, result=res, error=getattr(cls.mt5, "error", None))
        return OrderSendResult(**res._asdict())

    @error_handler_sync(log_error_msg=False)
    def calc_margin(self) -> float | None:
        """Tính mức ký quỹ; gọi `MetaTrader.order_calc_margin`."""
        res = self.mt5.order_calc_margin(self.type, self.symbol, self.volume, self.price)
        return res

    @error_handler_sync(log_error_msg=False)
    def calc_profit(self) -> float:
        """Tính mức lợi nhuận; gọi `MetaTrader.order_calc_profit`."""
        action, symbol, volume, price_open, price_close = (self.type, self.symbol, self.volume, self.price, self.tp)
        res = self.mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
        return res

    @error_handler_sync(log_error_msg=False)
    def calc_loss(self) -> float:
        """Tính mức thua lỗ; gọi `MetaTrader.order_calc_profit`."""
        action, symbol, volume, price_open, price_close = (self.type, self.symbol, self.volume, self.price, self.sl)
        res = self.mt5.order_calc_profit(action, symbol, volume, price_open, price_close)
        return res

    @property
    def request(self) -> dict:
        """Tạo dữ liệu yêu cầu lệnh từ các thuộc tính hiện tại; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return {key: value for key, value in self.dict.items() if key in self.mt5.TradeRequest.__match_args__}

    @classmethod
    def profit_to_price(cls, *, profit: float, order_type: OrderType, volume: float, symbol: str, price_open: float):
        """Tính mức giá tương ứng với lợi nhuận mục tiêu; gọi `MetaTrader.order_calc_profit`."""
        price_close = increase_value_by_pct(price_open, 50) if order_type == 0 else decrease_value_by_pct(price_open, 50)
        half_profit = cls.mt5.order_calc_profit(symbol=symbol, action=order_type, volume=volume,
                                             price_open=price_open, price_close=price_close)
        rate = profit / half_profit * 50
        rate = increase_value_by_pct(price_open, rate) if order_type == 0 else decrease_value_by_pct(price_open, rate)
        return rate

    @classmethod
    def get_history_order_by_ticket(cls, *, ticket: int) -> TradeOrder | None:
        """Lấy lệnh lịch sử theo mã định danh; gọi `MetaTrader.history_orders_get`."""
        res = cls.mt5.history_orders_get(ticket=ticket)
        if res is not None and len(res) > 0 and res[0].ticket == ticket:
            return TradeOrder(**res[0]._asdict())
        return None
