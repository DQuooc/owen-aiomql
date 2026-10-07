import asyncio
from logging import getLogger
from datetime import datetime

from aiomql import OpenPosition, OrderSendAmbiguous

logger = getLogger(__name__)


async def close_after(open_pos: OpenPosition, /, *, duration: int, start: float = 0):
    """Đóng vị thế sau thời lượng được cấu hình; phối hợp với `OpenPosition.update_position` và `OpenPosition.close_position`."""
    if not await open_pos.update_position():
        return
    pos = open_pos.position
    start = start or pos.time
    diff = datetime.now().timestamp() - start
    if diff > duration:
        _, res = await open_pos.close_position()
        if res.retcode == 10009:
            logger.info("%s, %d closed", pos.symbol, pos.ticket)


async def hedge_position(pos: OpenPosition, /, *, hedge_amount: float = -2, close_hedge_amount: float = 0,
                         order_params: dict = None):
    """Mở vị thế ngược chiều để phòng hộ vị thế hiện tại; phối hợp với `OpenPosition.update_position` và `OpenPosition.hedge_position`."""
    is_open = await pos.update_position()
    position = pos.position
    if not (is_open and pos.is_hedged is False and position.profit < 0):
        return

    if position.profit <= hedge_amount:
        ok, order = await pos.hedge_position(order_params=order_params)
        if not ok:
            logger.error("Could not hedge %s:%d", pos.symbol, pos.ticket)


async def track_hedges(pos: OpenPosition, close_hedge_amount: float = -10):
    """Theo dõi và đóng các vị thế phòng hộ chạm ngưỡng lỗ; phối hợp với `OpenPosition.update_position`."""
    res = await pos.update_position()
    if not res:
        return
    hedges = list(pos.hedges.values())
    await asyncio.gather(*[hedge.update_position() for hedge in hedges], return_exceptions=True)
    hedges = [hedge for hedge in hedges if hedge.is_open]
    results = await asyncio.gather(
        *[hedge.close_position() for hedge in hedges if hedge.position.profit <= close_hedge_amount],
        return_exceptions=True)
    for result in results:
        if isinstance(result, OrderSendAmbiguous):
            raise result
