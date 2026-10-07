"""Cung cấp các hàm theo dõi và quản lý vị thế mở."""
from logging import getLogger

from .open_position import OpenPosition
from ...utils.price_utils import get_price_in_range_pct, extend_range_by_pct

logger = getLogger(__name__)


async def exit_at_profit(pos: OpenPosition, /, tp: float = None, sl: float = None):
    """Đóng vị thế khi đạt lợi nhuận mục tiêu; phối hợp với `OpenPosition.update_position` và `OpenPosition.close_position`."""
    if not await pos.update_position():
        return

    if (tp is not None and pos.position.profit >= tp) or (sl is not None and pos.position.profit <= sl):
        ok, res = await pos.close_position()
        if not ok:
            comment = res.comment if res is not None else ""
            logger.warning("Unable to close %s:%d due to %s in exit_at_price", pos.symbol.name, pos.ticket, comment)
        else:
            logger.info("Closed %s:%d in exit_at_price with profit %s", pos.symbol.name, pos.ticket, pos.position.profit)


async def extend_take_profit(pos: OpenPosition, /, increase: float = 20, start: float = 80,
                             use_stop_levels: bool = True):
    """Nới mức chốt lời theo tỷ lệ đã cấu hình; phối hợp với `OpenPosition.update_position` và `OpenPosition.modify_stops`."""
    is_open = await pos.update_position()
    if is_open is False or pos.position.profit < 0:
        return
    position = pos.position
    if get_price_in_range_pct(position.price_open, position.tp, position.price_current) >= start:
        new_tp = extend_range_by_pct(position.price_open, position.tp, increase)
        ok, res = await pos.modify_stops(tp=new_tp, use_stop_levels=use_stop_levels)
        if ok:
            logger.info("%s:%d take_profit extended by extend_take_profit", position.symbol, position.ticket)
        else:
            logger.warning("Unable to extend take profit of %s:%d due to %s in extend_take_profit",
                           position.symbol, position.ticket, res.comment)

