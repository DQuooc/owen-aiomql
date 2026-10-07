"""Theo dõi và quản lý vị thế mở, phòng hộ và bổ sung vị thế."""
from dataclasses import dataclass, field
from typing import ClassVar, Self
from logging import getLogger
import asyncio

from ...lib import Symbol, Positions, Order
from ...core.models import TradePosition, TradeAction, OrderSendResult
from ...core.constants import OrderType, TradeRetcode
from ...core.exceptions import OrderSendAmbiguous
from ...core.config import Config
from ...utils.price_utils import increase_value_by_pct, decrease_value_by_pct
from .position_trackers import PositionTracker

logger = getLogger()


@dataclass
class PendingOrder:
    """Biểu diễn lệnh chờ gắn với một vị thế đang mở."""
    order: OrderSendResult
    is_hedge: bool = False
    is_stack: bool = False
    open_pos_params: dict = field(default_factory=dict)


@dataclass
class OpenPosition:
    """Quản lý vị thế mở cùng hoạt động phòng hộ và bổ sung vị thế."""
    symbol: Symbol
    ticket: int
    position: TradePosition
    is_open: bool = True
    is_hedged: bool = False
    is_stacked: bool = False
    is_a_stack: bool = False
    is_a_hedge: bool = False
    hedge: Self | None = None
    stack: Self | None = None
    pending_orders: dict[int, PendingOrder] = field(default_factory=dict)
    hedges: dict[int, "OpenPosition"] = field(default_factory=dict)
    stacks: dict[int, "OpenPosition"] = field(default_factory=dict)
    close_pending_orders_on_close: bool = True
    remove_from_state_on_close: bool = True
    auto_track_closed: bool = True
    close_hedges_on_close: bool = False
    close_stacks_on_close: bool = False
    _trackers: dict[str, PositionTracker] = field(default_factory=dict)
    positions: ClassVar[Positions]
    state_key: ClassVar[str] = "tracked_positions"
    archive_key: ClassVar[str] = "archived_positions"
    config: ClassVar[Config]

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `OpenPosition`; phối hợp với `Config` và `Positions`."""
        if not hasattr(cls, "config"):
            cls.config = Config()
        if not hasattr(cls, "positions"):
            cls.positions = Positions()
        return super().__new__(cls)

    def __post_init__(self):
        """Hoàn tất khởi tạo `OpenPosition` sau khi lớp dữ liệu tạo đối tượng; phối hợp với `Config` và `PositionTracker`."""
        self.config.state.setdefault(self.state_key, {}).setdefault(self.ticket, self)
        if self.auto_track_closed:
            PositionTracker(self, self.remove_closed, name="remove_closed_tracker", rank=1)
        PositionTracker(self, self.check_pending_orders, name="pending_orders_tracker", rank=2)

    def add_tracker(self, *, tracker: PositionTracker, name: str = None, rank: int = None):
        """Thêm bộ theo dõi; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        tracker.rank = rank if rank is not None else (tracker.rank if tracker.rank is not None else len(self._trackers) + 1)
        self._trackers[name] = tracker

    @property
    def trackers(self):
        """Duyệt các bộ theo dõi theo thứ tự ưu tiên; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        for tracker in sorted(self._trackers, key=lambda key: self._trackers[key].rank):
            yield self._trackers[tracker]

    @staticmethod
    async def remove_closed(self, /):
        """Dọn vị thế đã đóng cùng các lệnh và vị thế liên quan; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        try:
            await self.update_position()
            if self.is_open:
                return
            if self.close_pending_orders_on_close:
                await self.close_pending_orders()
            if self.close_hedges_on_close:
                await self.close_hedges()
            if self.close_stacks_on_close:
                await self.close_stacks()
            if self.remove_from_state_on_close:
                self.remove_from_state()
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred while removing closed position from state", exe)
    
    async def close_pending_orders(self) -> tuple[tuple[bool, PendingOrder], ...]:
        """Hủy toàn bộ lệnh chờ liên quan tới vị thế; phối hợp các tác vụ qua `asyncio`."""
        try:
            pending_orders: list[PendingOrder] = list(self.pending_orders.values())
            ord_res = await asyncio.gather(*[self.close_pending_order(pending_order=pending_order)
             for pending_order in pending_orders], return_exceptions=True)
            for result in ord_res:
                if isinstance(result, OrderSendAmbiguous):
                    raise result
            return tuple(res for res in ord_res if isinstance(res, tuple) and res[0] is True)
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred while closing pending orders for %s:%d in %s.close_pending_orders",
             exe, self.symbol.name, self.ticket, self.__class__.__name__)
            return ()

    async def close_pending_order(self, *, pending_order: PendingOrder) -> tuple[bool, PendingOrder]:
        """Hủy một lệnh chờ liên quan tới vị thế; phối hợp với `Order.cancel_order` và `Order.get_history_order_by_ticket`."""
        pending_order_ticket = pending_order.order.order
        res = await Order.cancel_order(order=pending_order_ticket, symbol=pending_order.order.request.symbol)
        if res.retcode == TradeRetcode.DONE_PARTIAL:
            logger.warning("Pending order %s only partially canceled", pending_order_ticket)
            return False, pending_order
        if res.retcode != 10009:
            cpo = await Order.get_history_order_by_ticket(ticket=pending_order_ticket) # Kiểm tra lệnh đã bị xóa trước đó hay chưa
            res.comment = f"{res.comment}: Order already canceled)"
            if cpo is None:
                logger.critical("%s: Unable to cancel pending order %d for %s:%d in %s.close_pending_order",
                    res.comment, pending_order_ticket, self.symbol.name, self.ticket, self.__class__.__name__)
                return False, pending_order
        pending_order.order = res
        self.pending_orders.pop(pending_order_ticket, None)
        return True, pending_order

    async def update_position(self) -> bool:
        """Cập nhật vị thế; phối hợp với `Positions.get_position_by_ticket`."""
        try:
            pos = await self.positions.get_position_by_ticket(ticket=self.ticket)
            if pos is not None:
                self.position = pos
                self.is_open = True
            else:
                self.is_open = False
            return self.is_open
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.critical("%s: Error occurred while updating position for %s:%d in %s.update_position",
             exe, self.symbol.name, self.ticket, self.__class__.__name__)
            return self.is_open

    async def modify_stops(self, *, sl: float = None, tp: float = None,
                           use_stop_levels: bool = False) -> tuple[bool, OrderSendResult | None]:
        """Cập nhật mức dừng lỗ hoặc chốt lời của vị thế; phối hợp với `Symbol.info_tick` và `Order`."""
        try:
            tick = await self.symbol.info_tick()

            if sl is not None and use_stop_levels is True:
                min_stops_value = (self.symbol.trade_stops_level + self.symbol.spread) * self.symbol.point
                if OrderType(self.position.type).is_long:
                    sl = min(sl, tick.ask - min_stops_value)
                elif OrderType(self.position.type).is_short:
                    sl = max(sl, tick.bid + min_stops_value)
                else:
                    logger.critical("Invalid OrderType cannot modify stops for %d:%s In %s.modify_stops",
                     self.ticket, self.symbol.name,self.__class__.__name__)
                    return False, None

            elif sl is not None and use_stop_levels is False:
                sl = sl or self.position.sl

            # Cập nhật mức chốt lời
            if tp is not None and use_stop_levels is True:
                min_stops_value = (self.symbol.trade_stops_level + self.symbol.spread) * self.symbol.point
                if OrderType(self.position.type).is_long:
                    tp = max(tp, tick.ask + min_stops_value)
                elif OrderType(self.position.type).is_short():
                    tp = min(tp, tick.bid - min_stops_value)
                else:
                    logger.critical("Invalid OrderType cannot modify stops for %d:%s In %s.modify_stops",
                     self.ticket, self.symbol.name,self.__class__.__name__)
                    return False, None
            elif tp is not None and use_stop_levels is False:
                tp = tp or self.position.tp

            # Gửi lệnh
            order = Order(position=self.ticket, sl=sl, tp=tp, action=TradeAction.SLTP)
            res = await order.send()
            if res.retcode == TradeRetcode.DONE_PARTIAL:
                logger.warning("Stops only partially modified for position %s", self.ticket)
                return False, res
            if res.retcode == 10009:
                await self.update_position()
                return True, res
            else:
                comment = res.comment if res else ""
                logger.critical("Unable to modify stops for %d:%s In %s.modify_stops: %s", self.ticket,
                 self.symbol.name,self.__class__.__name__, comment)
                return False, res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.modify_stops for %s:%d",
                         exe, self.__class__.__name__, self.symbol.name, self.ticket)
            return False, None

    def remove_from_state(self):
        """Chuyển vị thế đã đóng khỏi trạng thái hoạt động sang kho lưu trữ; phối hợp với `Config`."""
        try:
            pos = self.config.state.get(self.state_key, {}).pop(self.ticket, None)
            self.config.state.setdefault(self.archive_key, {}).setdefault(self.ticket, pos) if pos else ...
        except KeyError as err:
            logger.error("%s: Unable to remove closed position from state in %s", err, self.__class__.__name__)

    async def close_position(self) -> tuple[bool, OrderSendResult | None]:
        """Đóng vị thế; phối hợp với `Positions.close_position`."""
        try:
            res = await self.positions.close_position(position=self.position)
            if not res[0]:
                logger.critical("Unable to close position for %d:%s In %s.close_position: %s", self.ticket,
                                self.symbol.name, self.__class__.__name__, res[1].comment)
                return res
            self.is_open = False
            closures = []
            if self.close_pending_orders_on_close:
                closures.append(self.close_pending_orders())
            if self.close_hedges_on_close:
                closures.append(self.close_hedges())
            if self.close_stacks_on_close:
                closures.append(self.close_stacks())
            results = await asyncio.gather(*closures, return_exceptions=True)
            for result in results:
                if isinstance(result, OrderSendAmbiguous):
                    raise result
            if self.remove_from_state_on_close:
                self.remove_from_state()
            return res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.close_position for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)
            return False, None

    async def close_hedges(self):
        """Đóng các vị thế phòng hộ; phối hợp các tác vụ qua `asyncio`."""
        try:
            hedges = tuple(self.hedges.values())
            results = await asyncio.gather(*[hedge.close_position() for hedge in hedges], return_exceptions=True)
            for result in results:
                if isinstance(result, OrderSendAmbiguous):
                    raise result
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.close_hedges for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)

    async def close_stacks(self):
        """Đóng các vị thế xếp chồng; phối hợp các tác vụ qua `asyncio`."""
        try:
            stacks = tuple(self.stacks.values())
            results = await asyncio.gather(*[stack.close_position() for stack in stacks], return_exceptions=True)
            for result in results:
                if isinstance(result, OrderSendAmbiguous):
                    raise result
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.close_stacks for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)

    async def check_pending_order(self, *, pending_order: PendingOrder):
        """Kiểm tra một lệnh chờ đã khớp thành vị thế hay chưa; phối hợp với `Positions.get_position_by_ticket` và `OpenPosition`."""
        try:
            pos = await self.positions.get_position_by_ticket(ticket=pending_order.order.order)
            if pos is None:
                return
            if pending_order.is_hedge:
                self.hedges[pos.ticket] = OpenPosition(symbol=self.symbol, position=pos, ticket=pos.ticket,
                                          is_a_hedge=True, hedge=self, **pending_order.open_pos_params)
                self.pending_orders.pop(pending_order.order.order)
            elif pending_order.is_stack:
                self.stacks[pos.ticket] = OpenPosition(symbol=self.symbol, position=pos, ticket=pos.ticket, 
                    is_a_stack=True, stack=self, **pending_order.open_pos_params)
                self.pending_orders.pop(pending_order.order.order)
            else:
                logger.warning("Unexpected pending order (neither hedge nor stack) for %s:%d", 
                   self.symbol.name, pending_order.order.order)
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.check_pending_hedge_order for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)
    
    @staticmethod
    async def check_pending_orders(self, /):
        """Kiểm tra các lệnh chờ đã khớp thành vị thế hay chưa; phối hợp các tác vụ qua `asyncio`."""
        try:
            orders = list(self.pending_orders.values())
            await asyncio.gather(*[self.check_pending_order(pending_order=pending_order) for pending_order in orders], return_exceptions=True)
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.check_pending_orders for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)

    async def track(self):
        """Theo dõi thay đổi của vị thế giao dịch; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        try:
            for tracker in self.trackers:
                await tracker()
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.track for %s:%d", exe, self.__class__.__name__, self.symbol.name, self.ticket)

    async def profit_to_price(self, *, profit: float) -> float:
        """Tính mức giá tương ứng với lợi nhuận mục tiêu; gọi `MetaTrader.order_calc_profit`."""
        action = self.position.type
        volume = self.position.volume
        price_open = self.position.price_open
        price_close = increase_value_by_pct(price_open, 50) if self.position.type.is_long else decrease_value_by_pct(price_open, 50)
        half_profit = await Order.mt5.order_calc_profit(symbol=self.symbol.name, action=action, volume=volume,
                                             price_open=price_open, price_close=price_close)
        rate = profit / half_profit * 50
        rate = increase_value_by_pct(price_open, rate) if self.position.type.is_long else decrease_value_by_pct(price_open, rate)
        return rate

    async def hedge_order(self, *, price: float, order_params: dict = None,
                          open_pos_params: dict = None) -> tuple[bool, OrderSendResult | None]:
        """Tạo lệnh chờ phòng hộ cho vị thế; phối hợp với `Order`."""
        try:
            order_params = order_params or {}
            open_pos_params = open_pos_params or {}
            order_type = order_params.pop("type", OrderType.SELL_STOP if self.position.type.is_long else OrderType.BUY_STOP)
            volume = order_params.pop("volume", self.position.volume)
            action = order_params.pop("action", TradeAction.PENDING)
            symbol = order_params.pop("symbol", self.symbol.name)
            comment = order_params.pop("comment", f"Hedge_{self.symbol.name}:{self.ticket}")
            order = Order(action=action, symbol=symbol, type=order_type, price=price, volume=volume, comment=comment, **order_params)
            res = await order.send()
            if res.retcode == TradeRetcode.DONE_PARTIAL:
                logger.warning("Hedge order for position %s partially placed: %s of %s", self.ticket, res.volume, volume)
                return False, res
            if res.retcode != 10009:
                logger.critical("Unable to send pending order for %d:%s In %s.hedge_order: %s, %f", self.ticket,
                 self.symbol.name, self.__class__.__name__, res.comment, price)
                return False, res
            pending_order = PendingOrder(order=res, is_hedge=True, open_pos_params=open_pos_params)
            self.pending_orders[res.order] = pending_order
            self.is_hedged = True
            return True, res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.hedge_order for %s:%d", exe, self.__class__.__name__, self.symbol.name, self.ticket)
            return False, None
        
    async def stack_order(self, *, price: float, order_params: dict = None,
                          open_pos_params: dict = None) -> tuple[bool, OrderSendResult | None]:
        """Tạo lệnh chờ bổ sung vị thế cùng chiều; phối hợp với `Order`."""
        try:
            order_params = order_params or {}
            open_pos_params = open_pos_params or {}
            order_type = order_params.pop("type", OrderType.BUY_STOP if self.position.type.is_long else OrderType.SELL_STOP)
            volume = order_params.pop("volume", self.position.volume)
            action = order_params.pop("action", TradeAction.PENDING)
            symbol = order_params.pop("symbol", self.symbol.name)
            comment = order_params.pop("comment", f"Stack_{self.symbol.name}:{self.ticket}")
            order = Order(action=action, symbol=symbol, type=order_type, price=price, volume=volume, comment=comment, **order_params)
            res = await order.send()
            if res.retcode == TradeRetcode.DONE_PARTIAL:
                logger.warning("Stack order for position %s partially placed: %s of %s", self.ticket, res.volume, volume)
                return False, res
            if res.retcode != 10009:
                logger.critical("Unable to send pending order for %d:%s In %s.stack_order: %s", self.ticket,
                 self.symbol.name, self.__class__.__name__, res.comment)
                return False, res
            pending_order = PendingOrder(order=res, is_stack=True, open_pos_params=open_pos_params)
            self.pending_orders[res.order] = pending_order
            self.is_stacked = True
            return True, res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.hedge_order for %s:%d", exe, self.__class__.__name__, self.symbol.name, self.ticket)
            return False, None
    
    def update(self, **kwargs):
        """Cập nhật dữ liệu của `OpenPosition`; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        [setattr(self, attr, value) for attr, value in kwargs.items()]

    async def hedge_position(self, *, order_params: dict = None, 
                             open_pos_params: dict = None) -> tuple[bool, OrderSendResult | None]:
        """Mở vị thế ngược chiều để phòng hộ vị thế hiện tại; phối hợp với `Symbol.info_tick` và `Order`."""
        try:
            order_params = order_params or {}
            open_pos_params = open_pos_params or {}
            volume = order_params.pop("volume", self.position.volume)
            order_type = order_params.pop("type", OrderType(self.position.type).opposite)
            symbol = order_params.pop("symbol", self.symbol.name)
            if (price := order_params.pop("price", None)) is None:
                tick = await self.symbol.info_tick(name=symbol)
                price = (tick.ask if order_type.is_long else tick.bid)
            comment = order_params.pop("comment", f"Hedge:{self.symbol.name}:{self.ticket}")
            hedge_order = Order(type=order_type, symbol=symbol, volume=volume, price=price, comment=comment, **order_params)
            res = await hedge_order.send()
            if res.retcode == TradeRetcode.DONE_PARTIAL:
                logger.warning("Hedge for position %s partially filled: %s of %s", self.ticket, res.volume, volume)
                return False, res
            if res.retcode != 10009:
                logger.critical("Unable to send hedge order for %d:%s In %s.hedge_position: %s", self.ticket,
                 self.symbol.name, self.__class__.__name__, res.comment)
                return False, res
            hedge_pos = await self.positions.get_position_by_ticket(ticket=res.order)
            if hedge_pos is None:
                logger.critical("Position not found for %d:%s In %s.hedge_position",
                                self.ticket, self.symbol.name, self.__class__.__name__)
                return False, res
            hedge = OpenPosition(symbol=symbol, ticket=res.order, position=hedge_pos, hedge=self, is_a_hedge=True, **open_pos_params)
            self.hedges[res.order] = hedge
            self.is_hedged = True
            return True, res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.hedge_position for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)
            return False, None

    async def stack_position(self, *, order_params: dict = None,
                             open_pos_params: dict = None) -> tuple[bool, OrderSendResult | None]:
        """Mở thêm vị thế cùng chiều với vị thế hiện tại; phối hợp với `Symbol.info_tick` và `Order`."""
        try:
            order_params = order_params or {}
            open_pos_params = open_pos_params or {}
            volume = order_params.pop("volume", self.position.volume)
            order_type = order_params.pop("type", self.position.type)
            symbol = order_params.pop("symbol", self.symbol.name)
            if (price := order_params.pop("price", None)) is None:
                tick = await self.symbol.info_tick(name=symbol)
                price = (tick.ask if order_type == OrderType.BUY else tick.bid)
            comment = order_params.pop("comment", f"Stack:{self.symbol.name}:{self.ticket}")
            stack_order = Order(type=order_type, symbol=symbol, volume=volume, price=price, comment=comment, **order_params)
            res = await stack_order.send()
            if res.retcode == TradeRetcode.DONE_PARTIAL:
                logger.warning("Stack for position %s partially filled: %s of %s", self.ticket, res.volume, volume)
                return False, res
            if res.retcode != 10009:
                logger.critical("Unable to send stack order for %d:%s In %s.stack_position: %s", self.ticket,
                 self.symbol.name, self.__class__.__name__, res.comment)
                return False, res
            stack_pos = await self.positions.get_position_by_ticket(ticket=res.order)
            if stack_pos is None:
                logger.critical("Position not found for %d:%s In %s.stack_position",
                                self.ticket, self.symbol.name, self.__class__.__name__)
                return False, res
            stack = OpenPosition(symbol=symbol, ticket=res.order, position=stack_pos, stack=self, is_a_stack=True, **open_pos_params)
            self.is_stacked = True
            self.stacks[res.order] = stack
            return True, res
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s.stack_position for %s:%d", exe, self.__class__.__name__,
                         self.symbol.name, self.ticket)
            return False, None
