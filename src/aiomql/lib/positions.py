"""Truy xuất và quản lý các vị thế giao dịch đang mở."""

import asyncio
from logging import getLogger

from ..core.meta_trader import MetaTrader
from ..core.base import BaseMeta
from ..core.models import TradePosition, OrderSendResult
from ..core.constants import OrderType, TradeAction, TradeRetcode
from ..core.config import Config
from ..core.exceptions import InvalidRequest, OrderSendAmbiguous
from .order import Order


logger = getLogger(__name__)

class Positions(metaclass=BaseMeta):
    """Truy xuất và đóng các vị thế đang mở."""
    mt5: MetaTrader
    config: Config

    @classmethod
    async def get_positions(cls, *, symbol: str = None, ticket: int = None, group: str = None) -> tuple[TradePosition, ...]:
        """Lấy các vị thế; gọi `MetaTrader.positions_get`."""
        kwargs = {}
        if symbol is not None:
            kwargs["symbol"] = symbol
            ticket = None
        if ticket is not None:
            kwargs["ticket"] = ticket
        if group is not None:
            kwargs["group"] = group
        positions = await cls.mt5.positions_get(**kwargs)
        if positions is not None:
            return tuple(TradePosition(**pos._asdict()) for pos in positions)
        logger.warning("Failed to get open positions")
        return ()

    @classmethod
    async def get_position_by_ticket(cls, *, ticket: int) -> TradePosition | None:
        """Lấy vị thế theo mã định danh; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        positions = await cls.get_positions(ticket=ticket)
        return pos if len(positions) and (pos := positions[0]).ticket == ticket else None

    @classmethod
    async def get_positions_by_symbol(cls, *, symbol: str) -> tuple[TradePosition, ...]:
        """Lấy các vị thế theo mã giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return await cls.get_positions(symbol=symbol)

    @staticmethod
    async def close(*, ticket: int, symbol: str, price: float, volume: float, order_type: OrderType) -> tuple[bool, OrderSendResult]:
        """Đóng `Positions` hoặc tài nguyên mà đối tượng đang quản lý; phối hợp với `Order.send_order` và `Order.get_history_order_by_ticket`."""
        req = dict(action=TradeAction.DEAL, price=price, position=ticket, symbol=symbol, volume=volume,
                   type=OrderType(order_type).opposite)
        res = await Order.send_order(request=req)
        if res.retcode == TradeRetcode.DONE_PARTIAL:
            logger.warning("Position %s only partially closed: %s of %s", ticket, res.volume, req["volume"])
            return False, res
        if res.retcode != 10009:
            cop = await Order.get_history_order_by_ticket(ticket=ticket)
            res.comment = f"{res.comment}: Position is already closed"
            if cop is None:
                return False, res
        return True, res

    @classmethod
    async def close_position_by_ticket(cls, *, ticket: int) -> tuple[bool, OrderSendResult]:
        """Đóng vị thế theo mã định danh; phối hợp với `Order.get_history_order_by_ticket`."""
        position = await cls.get_position_by_ticket(ticket=ticket)
        if position is None:
            cop = await Order.get_history_order_by_ticket(ticket=ticket)
            if cop is None:
                raise InvalidRequest("Failed to get open position with %d" % ticket)
            return True, OrderSendResult(order=ticket, comment="Position is already closed")
        return await cls.close_position(position=position)

    @staticmethod
    async def close_position(*, position: TradePosition) -> tuple[bool, OrderSendResult]:
        """Đóng vị thế; phối hợp với `Order.send_order` và `Order.get_history_order_by_ticket`."""
        req = dict(position=position.ticket, symbol=position.symbol, volume=position.volume,
                   type=position.type.opposite, price=position.price_current, action=TradeAction.DEAL)
        res = await Order.send_order(request=req)
        if res.retcode == TradeRetcode.DONE_PARTIAL:
            logger.warning("Position %s only partially closed: %s of %s", position.ticket, res.volume, req["volume"])
            return False, res
        if res.retcode != 10009:
            cop = await Order.get_history_order_by_ticket(ticket=position.ticket)
            res.comment = f"{res.comment}: Position is already closed"
            if cop is None:
                return False, res
        return True, res
    
    @classmethod
    async def close_positions(cls, *, positions: tuple[TradePosition, ...]) -> tuple[tuple[bool, OrderSendResult], ...]:
        """Đóng các vị thế; phối hợp các tác vụ qua `asyncio`."""
        results = await asyncio.gather(
            *(cls.close_position(position=position) for position in positions), return_exceptions=True
        )
        for result in results:
            if isinstance(result, OrderSendAmbiguous):
                raise result
        return tuple(res for res in results if isinstance(res, tuple) and res[0])

    @classmethod
    async def close_all_positions(cls) -> tuple[OrderSendResult, ...]:
        """Đóng toàn bộ vị thế đang mở; phối hợp các tác vụ qua `asyncio`."""
        positions = await cls.get_positions()
        if positions is None:
            return ()
        results = await asyncio.gather(
            *(cls.close_position(position=position) for position in positions), return_exceptions=True
        )
        for result in results:
            if isinstance(result, OrderSendAmbiguous):
                raise result
        return tuple(res[1] for res in results if isinstance(res, tuple) and res[0])

    @classmethod
    async def get_total_positions(cls) -> int:
        """Lấy tổng số các vị thế; gọi `MetaTrader.positions_total`."""
        return await cls.mt5.positions_total()
