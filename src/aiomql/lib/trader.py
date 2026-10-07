"""Tạo lệnh và thực thi giao dịch theo tín hiệu chiến lược."""

from abc import ABC, abstractmethod
from typing import TypeVar
from logging import getLogger

from ..core.models import OrderType, OrderSendResult, OrderCheckResult
from ..core.constants import TradeRetcode
from ..core.config import Config
from ..core.task_queue import QueueItem
from ..core.volume import numeric_volume, round_volume, validate_volume
from ..core.exceptions import InvalidVolume
from .result import Result
from .order import Order
from .symbol import Symbol as _Symbol
from .ram import RAM
from ..utils import error_handler

logger = getLogger(__name__)
Symbol = TypeVar("Symbol", bound=_Symbol)


class Trader(ABC):
    """Lớp nền để tạo và quản lý lệnh giao dịch."""

    config: Config
    ram: RAM
    parameters: dict

    def __init__(self, *, symbol: Symbol, ram: RAM = None):
        """Khởi tạo `Trader`; phối hợp với `Config` và `Order`."""
        self.config = Config()
        self.symbol = symbol
        self.ram = ram or RAM()
        self.order = Order(symbol=symbol.name)
        self.parameters = {}

    def _set_order_volume(self, volume):
        """Apply the symbol's upper bound and require a valid broker volume step."""
        volume = numeric_volume(volume)
        if volume < self.symbol.volume_min:
            raise InvalidVolume(f"volume {volume} is below volume_min {self.symbol.volume_min}")
        _, bounded = self.symbol.check_volume(volume=volume)
        if volume > self.symbol.volume_max:
            bounded = round_volume(volume=bounded, minimum=self.symbol.volume_min,
                                   step=self.symbol.volume_step, round_down=True)
        self.order.volume = validate_volume(volume=bounded, minimum=self.symbol.volume_min,
                                            maximum=self.symbol.volume_max, step=self.symbol.volume_step)

    def set_trade_stop_levels_pips(self, *, pips: float, risk_to_reward: float = None):
        """Thiết lập dừng lỗ và chốt lời theo số pip; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        pips = pips * self.symbol.pip
        sl, tp = pips, pips * (risk_to_reward or self.ram.risk_to_reward)
        price = self.order.price
        if self.order.type.is_long:
            self.order.sl, self.order.tp = round(price - sl, self.symbol.digits), round(price + tp, self.symbol.digits)
        elif self.order.type.is_short:
            self.order.sl, self.order.tp = round(price + sl, self.symbol.digits), round(price - tp, self.symbol.digits)

    def set_trade_stop_levels_points(self, *, points: float, risk_to_reward: float = None):
        """Thiết lập dừng lỗ và chốt lời theo số điểm giá; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        points = points * self.symbol.point
        sl, tp = points, points * (risk_to_reward or self.ram.risk_to_reward)
        price, digits = self.order.price, self.symbol.digits

        if self.order.type.is_long:
            self.order.sl, self.order.tp = round(price - sl, self.symbol.digits), round(price + tp, digits)

        elif self.order.type.is_short == OrderType.SELL:
            self.order.sl, self.order.tp = round(price + sl, self.symbol.digits), round(price - tp, digits)

    async def create_order_with_stops(
        self, *, order_type: OrderType, sl: float, tp: float, amount_to_risk: float = None
    ):
        """Tạo lệnh với dừng lỗ và chốt lời chỉ định; phối hợp với `Symbol.amount_in_quote_currency` và `Symbol.info_tick`."""
        amount = amount_to_risk or await self.ram.get_amount()
        amount = await self.symbol.amount_in_quote_currency(amount=amount)
        tick = await self.symbol.info_tick()
        price = tick.ask if order_type.is_long else tick.bid
        volume = await self.symbol.compute_volume_sl(amount=amount, price=price, sl=sl)
        self._set_order_volume(volume)
        self.order.set_attributes(sl=sl, tp=tp, price=price, type=order_type)

    async def create_order_with_sl(
        self, *, order_type: OrderType, sl: float, amount_to_risk: float = None, risk_to_reward: float = None
    ):
        """Tạo lệnh từ mức dừng lỗ và tỷ lệ lợi nhuận/rủi ro; phối hợp với `Symbol.amount_in_quote_currency` và `Symbol.info_tick`."""
        amount = amount_to_risk or await self.ram.get_amount()
        amount = await self.symbol.amount_in_quote_currency(amount=amount)
        tick = await self.symbol.info_tick()
        price = tick.ask if order_type == OrderType.BUY else tick.bid
        dsl = abs(price - sl)
        dtp = dsl * (risk_to_reward or self.ram.risk_to_reward)
        tp = price + dtp if order_type == OrderType.BUY else price - dtp
        volume = await self.symbol.compute_volume_sl(amount=amount, price=price, sl=sl)
        self._set_order_volume(volume)
        self.order.set_attributes(sl=sl, tp=tp, price=price, type=order_type)

    async def create_order_with_points(
        self, *, order_type: OrderType, points: float, amount_to_risk: float = None, risk_to_reward: float = None
    ):
        """Tạo lệnh với khoảng dừng tính bằng điểm giá; phối hợp với `Symbol.amount_in_quote_currency` và `Symbol.info_tick`."""
        self.order.type = order_type
        amount = amount_to_risk or await self.ram.get_amount()
        amount = await self.symbol.amount_in_quote_currency(amount=amount)
        tick = await self.symbol.info_tick()
        self.order.price = tick.ask if order_type == OrderType.BUY else tick.bid
        volume = await self.symbol.compute_volume_points(amount=amount, points=points)
        self._set_order_volume(volume)
        self.set_trade_stop_levels_points(points=points, risk_to_reward=risk_to_reward)

    async def create_order_no_stops(self, *, order_type: OrderType, volume: float = None):
        """Tạo lệnh không có dừng lỗ hoặc chốt lời; phối hợp với `Symbol.info_tick`."""
        tick = await self.symbol.info_tick()
        self._set_order_volume(self.symbol.volume_min if volume is None else volume)
        self.order.price = tick.ask if order_type == OrderType.BUY else tick.bid
        self.order.type = order_type

    async def check_order(self) -> OrderCheckResult | None:
        """Kiểm tra lệnh; phối hợp với `Order.check`."""
        self._order_check_passed = False
        check = await self.order.check()

        if check is None:
            logger.warning(f"{self.order.mt5.error}: Order check failed")
            return check

        if check.retcode != 0:
            logger.warning("Invalid order %s, for due to %s", self.symbol, check.comment)
            return None
        self._order_check_passed = True
        return check

    async def send_order(self) -> OrderSendResult | None:
        """Gửi lệnh; phối hợp với `Order.send`."""
        if getattr(self, "_order_check_passed", None) is False:
            logger.warning("Order check failed; refusing to send order for %s", self.symbol)
            return None
        self._set_order_volume(getattr(self.order, "volume", None))
        result = await self.order.send()
        if result is None:
            logger.warning("%s: Failed to place order.", self.order.mt5.error)
            return result

        if result.retcode == TradeRetcode.DONE_PARTIAL:
            logger.warning("Order partially filled for %s: filled %s of %s", self.symbol,
                           result.volume, result.request.volume)
            return result
        if result.retcode != TradeRetcode.DONE:
            logger.warning("Unable to place order for %s due to %s", self.symbol, result.comment)
            return result
        return result

    @error_handler
    async def record_trade(self, *, result: OrderSendResult, parameters: dict = None, name: str = "",
                           expected_profit: float = None, use_task_queue=True):
        """Ghi lại giao dịch; phối hợp với `Order.calc_profit` và `Order.get_history_order_by_ticket`."""
        if self.config.record_trades is False or result.retcode not in (TradeRetcode.DONE, TradeRetcode.DONE_PARTIAL):
            return
        params = {**parameters} if isinstance(parameters, dict) else {}
        expected_profit = expected_profit or await self.order.calc_profit() or 0
        if result.retcode == TradeRetcode.DONE_PARTIAL:
            if result.request.volume:
                expected_profit *= result.volume / result.request.volume
            params["_execution"] = {"retcode": int(result.retcode), "requested_volume": result.request.volume,
                                    "filled_volume": result.volume}
        order = await self.order.get_history_order_by_ticket(ticket=result.order)
        if order is not None:
            result.request.sl = order.sl
            result.request.tp = order.tp
        res = Result(result=result, parameters=params, name=name,
                     time=order.time_setup_msc if order is not None else None, expected_profit=expected_profit)
        if use_task_queue:
            self.config.task_queue.add(item=QueueItem(res.save), must_complete=True)
        else:
            await res.save()

    def reset_order(self):
        """Đặt lại lệnh đang được bộ giao dịch chuẩn bị; phối hợp với `Order`."""
        self.order = Order(symbol=self.symbol)
        self._order_check_passed = None

    @abstractmethod
    async def place_trade(self, *args, **kwargs):
        """Tạo, kiểm tra và gửi lệnh giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
