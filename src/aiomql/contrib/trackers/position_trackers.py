"""Theo dõi và điều phối việc quản lý các vị thế đang mở."""
import asyncio

from collections.abc import Callable
from typing import Any, TypeVar, ClassVar
from logging import getLogger

from ...core import Config, State, sleep
from ...core.exceptions import OrderSendAmbiguous
from ...lib import Positions

logger = getLogger(__name__)

OpenPosition = TypeVar('OpenPosition')


class PositionTracker:
    """Bọc một hàm theo dõi để thực thi trên vị thế mở."""
    params: dict[str, Any]
    function: Callable
    name: str
    rank: int | None
    open_position: OpenPosition

    def __init__(self, open_position: OpenPosition, function: Callable, /, rank: int = None, 
                 name: str = None, function_params: dict[str, Any] = None) -> None:
        """Khởi tạo `PositionTracker`; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        self.function = function
        self.params = function_params or {}
        self.rank = rank
        self.open_position = open_position
        self.name = name or function.__name__
        self.set_tracker()

    async def __call__(self, **kwargs):
        """Cho phép gọi `PositionTracker` như một hàm; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        try:
            kwargs = self.params | kwargs
            await self.function(self.open_position, **kwargs)
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.error("%s: Error occurred in %s for %s:%d", exe, self.function.__name__,
                         self.open_position.symbol.name, self.open_position.ticket)

    def set_tracker(self, name: str = None, rank: int = None):
        """Đăng ký hàm theo dõi cho vị thế; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        self.open_position.add_tracker(tracker=self, name=name or self.name, rank=rank or self.rank)


class OpenPositionsTracker:
    """Quản lý và theo dõi toàn bộ vị thế đang mở."""
    config: ClassVar[Config]
    positions: ClassVar[Positions]
    state: ClassVar[State]

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `OpenPositionsTracker`; phối hợp với `Config` và `Positions`."""
        if not hasattr(cls, "config"):
            cls.config = Config()

        if not hasattr(cls, "positions"):
            cls.positions = Positions()

        if not hasattr(cls, "state"):
            cls.state = State()

        return super().__new__(cls)

    def __init__(self, interval: int = 10, state_key: str = "tracked_positions", 
                 autocommit: bool = False, auto_remove_closed: bool = False):
        """Khởi tạo `OpenPositionsTracker`; phối hợp với `Position`, `Order` và trạng thái chiến lược."""
        self.interval = interval
        self.state_key = state_key
        self.autocommit = autocommit
        self.auto_remove_closed = auto_remove_closed

    async def track(self):
        """Theo dõi thay đổi của vị thế giao dịch; phối hợp với `State` và `OpenPosition.track`."""
        conn = self.config.state.conn
        while not self.config.shutdown:
            try:
                await sleep(self.interval)
                tracked_positions = self.state.get("tracked_positions", {})
                results = await asyncio.gather(*(pos.track() for pos in tracked_positions.values()), return_exceptions=True)
                for result in results:
                    if isinstance(result, OrderSendAmbiguous):
                        raise result
                if self.auto_remove_closed:
                    await self.remove_closed_positions(tracked_positions)
                if self.autocommit:
                    await self.state.acommit(conn=conn, close=False)
            except OrderSendAmbiguous:
                raise
            except Exception as exe:
                logger.error("%s: Error occurred in %s.track", exe, self.__class__.__name__)
        conn.close()

    async def remove_closed_positions(self, tracked_positions: dict):
        """Loại các vị thế đã đóng khỏi bộ theo dõi; phối hợp với `Positions.get_positions`."""
        all_pos = await self.positions.get_positions()
        all_pos = {pos.ticket for pos in all_pos}
        self.state[self.state_key] = {pos.ticket: pos for pos in tracked_positions.values() if pos.ticket in all_pos}
