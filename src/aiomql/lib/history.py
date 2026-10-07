"""Truy xuất lệnh và giao dịch đã khớp trong lịch sử tài khoản."""

import asyncio
from typing import ClassVar
from datetime import datetime, UTC
from logging import getLogger

from ..core.config import Config
from ..core.meta_trader import MetaTrader
from ..core.models import TradeDeal, TradeOrder
from ..core.base import BaseMeta
from ..core.exceptions import InvalidRequest

logger = getLogger(__name__)


class History(metaclass=BaseMeta):
    """Truy xuất và lọc lệnh cùng giao dịch đã khớp trong lịch sử."""
    mt5: ClassVar[MetaTrader]
    config: ClassVar[Config]
    deals: tuple[TradeDeal, ...]
    orders: tuple[TradeOrder, ...]
    total_deals: int
    total_orders: int
    group: str

    def __init__(self, *, date_from: datetime | float, date_to: datetime | float, group: str = "", use_utc: bool = False):
        """Khởi tạo `History`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        date_from = date_from if isinstance(date_from, datetime) else datetime.fromtimestamp(date_from)
        date_to = date_to if isinstance(date_to, datetime) else datetime.fromtimestamp(date_to)
        self.date_from = date_from.astimezone(UTC) if use_utc else date_from
        self.date_to = date_to.astimezone(UTC) if use_utc else date_to
        self.group = group
        self.deals: tuple[TradeDeal, ...] = ()
        self.orders: tuple[TradeOrder, ...] = ()
        self.total_deals: int = 0
        self.total_orders: int = 0

    async def initialize(self) -> None:
        """Khởi tạo dữ liệu và tài nguyên của `History`; phối hợp các tác vụ qua `asyncio`."""
        deals, orders = await asyncio.gather(self.get_deals(), self.get_orders(), return_exceptions=True)
        self.deals = deals if isinstance(deals, tuple) else ()
        self.orders = orders if isinstance(orders, tuple) else ()
        self.total_deals = len(self.deals)
        self.total_orders = len(self.orders)

    async def get_deals(self) -> tuple[TradeDeal, ...]:
        """Lấy các giao dịch đã khớp; gọi `MetaTrader.history_deals_get`."""
        deals = await self.mt5.history_deals_get(date_from=self.date_from, date_to=self.date_to, group=self.group)
        return tuple(TradeDeal(**deal._asdict()) for deal in deals)

    async def get_orders(self) -> tuple[TradeOrder, ...]:
        """Lấy các lệnh; gọi `MetaTrader.history_orders_get`."""
        orders = await self.mt5.history_orders_get(date_from=self.date_from, date_to=self.date_to, group=self.group)
        return tuple(TradeOrder(**order._asdict()) for order in orders)

    def filter_deals_by_ticket(self, *, ticket: int) -> tuple[TradeDeal, ...]:
        """Lọc các giao dịch đã khớp theo mã định danh; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return tuple(deal for deal in self.deals if deal.ticket == ticket)

    def filter_deals_by_position(self, *, position: int) -> tuple[TradeDeal, ...]:
        """Lọc các giao dịch đã khớp theo vị thế; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return tuple(deal for deal in self.deals if deal.position_id == position)

    def filter_orders_by_ticket(self, *, ticket: int) -> tuple[TradeOrder, ...]:
        """Lọc các lệnh theo mã định danh; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return tuple(order for order in self.orders if order.ticket == ticket)

    def filter_orders_by_position(self, *, position: int) -> tuple[TradeOrder, ...]:
        """Lọc các lệnh theo vị thế; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return tuple(order for order in self.orders if order.position_id == position)

    @classmethod
    async def get_deal_by_ticket(cls, *, ticket: int) -> TradeDeal:
        """Lấy giao dịch đã khớp theo mã định danh; gọi `MetaTrader.history_deals_get`."""
        deals = await cls.mt5.history_deals_get(ticket=ticket)
        if (deal := deals[0]).ticket == ticket:
            return TradeDeal(**deal._asdict())
        raise InvalidRequest("Ticket not found")

    @classmethod
    async def get_deals_by_position(cls, *, position: int = None) -> tuple[TradeDeal, ...]:
        """Lấy các giao dịch đã khớp theo vị thế; gọi `MetaTrader.history_deals_get`."""
        deals = await cls.mt5.history_deals_get(position=position)
        return tuple(TradeDeal(**deal._asdict()) for deal in deals if deal.position_id == position)

    @classmethod
    async def get_order_by_ticket(cls, *, ticket: int) -> TradeOrder:
        """Lấy lệnh theo mã định danh; gọi `MetaTrader.history_orders_get`."""
        orders = await cls.mt5.history_orders_get(ticket=ticket)
        if (order := orders[0]).ticket == ticket:
            return TradeOrder(**order._asdict())
        raise InvalidRequest("Ticket not found")

    @classmethod
    async def get_orders_by_position(cls, *, position: int) -> tuple[TradeOrder, ...]:
        """Lấy các lệnh theo vị thế; gọi `MetaTrader.history_orders_get`."""
        orders = await cls.mt5.history_orders_get(position=position)
        return tuple(TradeOrder(**order._asdict()) for order in orders)
