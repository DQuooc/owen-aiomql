"""Quản lý các phiên giao dịch theo thời gian."""

import asyncio
from datetime import time, timedelta, datetime, UTC
from typing import Literal, Callable, Iterable, NamedTuple
from logging import getLogger

from ..core.models import OrderSendResult, TradePosition
from ..core.exceptions import OrderSendAmbiguous
from ..core.config import Config
from .positions import Positions

logger = getLogger(__name__)


class Duration(NamedTuple):
    """Biểu diễn một khoảng thời gian theo ngày, giây và micro giây."""
    hours: int
    minutes: int
    seconds: int


def delta(obj: time) -> timedelta:
    """Đổi thời điểm trong ngày thành khoảng thời gian; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
    return timedelta(hours=obj.hour, minutes=obj.minute, seconds=obj.second, microseconds=obj.microsecond)


class Session:
    """Biểu diễn một phiên giao dịch giữa hai thời điểm UTC."""

    def __init__(
        self,
        *,
        start: int | time,
        end: int | time,
        on_start: Literal["close_all", "close_win", "close_loss", "custom_start"] = None,
        on_end: Literal["close_all", "close_win", "close_loss", "custom_end"] = None,
        custom_start: Callable = None,
        custom_end: Callable = None,
        name: str = "",
    ):
        """Khởi tạo `Session`; phối hợp với `Positions` và `Config`."""
        self.start = start.replace(tzinfo=UTC) if isinstance(start, time) else time(hour=start, tzinfo=UTC)
        self.end = end if isinstance(end, time) else time(hour=end, tzinfo=UTC)
        self.on_start = on_start
        self.on_end = on_end
        self.custom_start = custom_start
        self.custom_end = custom_end
        self.name = name or f"{self.start}<-->{self.end}"
        self.positions_manager = Positions()
        self.config = Config()

    def __contains__(self, item: time) -> bool:
        """Kiểm tra một phần tử có thuộc `Session` hay không; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        span = (delta(self.end) - delta(self.start)).seconds
        item_span = (delta(self.end) - delta(item)).seconds
        return item_span <= span

    def __str__(self) -> str:
        """Tạo chuỗi hiển thị dễ đọc cho `Session`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return f"{self.start}<-->{self.end}"

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Session`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return f"{self.start}<-->{self.end}"

    def __len__(self) -> int:
        """Trả về số phần tử của `Session`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return int((delta(self.end) - delta(self.start)).seconds)

    def in_session(self) -> bool:
        """Kiểm tra thời điểm hiện tại có nằm trong phiên giao dịch hay không; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        now = datetime.now(tz=UTC).time()
        return now in self

    async def begin(self):
        """Đánh dấu bắt đầu phiên giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.action(action=self.on_start)

    async def close(self):
        """Đóng `Session` hoặc tài nguyên mà đối tượng đang quản lý; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.action(action=self.on_end)

    def duration(self) -> Duration:
        """Tính thời lượng của phiên giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        hours, seconds = divmod(len(self), 3600)
        minutes, seconds = divmod(seconds, 60)
        return Duration(hours=hours, minutes=minutes, seconds=seconds)

    async def close_positions(self, *, positions: tuple[TradePosition, ...]):
        """Đóng các vị thế; phối hợp các tác vụ qua `asyncio`."""
        results = await asyncio.gather(
            *(self.positions_manager.close_position(position=position) for position in positions),
            return_exceptions=True,
        )
        closed = pending = 0
        for result in results:
            if isinstance(result, OrderSendAmbiguous):
                raise result
            if isinstance(result, OrderSendResult) and result.retcode == 10009:
                closed += 1
                continue
            pending += 1
        logger.info(f"Closed {closed} positions")
        logger.warning(f"{pending} positions still pending") if pending else ...

    async def close_all(self):
        """Đóng toàn bộ vị thế của phiên giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        open_positions = await self.positions_manager.get_positions()
        await self.close_positions(positions=open_positions)

    async def close_win(self):
        """Đóng các vị thế đang có lãi; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        open_positions = await self.positions_manager.get_positions()
        positions = tuple(position for position in open_positions if position.profit >= 0)
        await self.close_positions(positions=positions)

    async def close_loss(self):
        """Đóng các vị thế đang thua lỗ; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        open_positions = await self.positions_manager.get_positions()
        positions = tuple(position for position in open_positions if position.profit < 0)
        await self.close_positions(positions=positions)

    async def action(self, *, action):
        """Thực thi hành động được cấu hình cho phiên giao dịch; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        try:
            match action:
                case "close_all":
                    await self.close_all()

                case "close_win":
                    await self.close_win()

                case "close_loss":
                    await self.close_loss()

                case "custom_end":
                    await self.custom_end()

                case "custom_start":
                    await self.custom_start()

                case _:
                    pass
        except OrderSendAmbiguous:
            raise
        except Exception as exe:
            logger.warning(f"Failed to call action {action} due to {exe}")

    def until(self) -> int:
        """Tính số giây còn lại tới phiên giao dịch kế tiếp; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        secs = (delta(self.start) - delta(datetime.now(tz=UTC).time())).seconds
        return secs

class Sessions:
    """Quản lý một tập phiên giao dịch và tự động chọn phiên phù hợp."""

    sessions: list[Session]
    current_session: Session | None

    def __init__(self, *, sessions: Iterable[Session]):
        """Khởi tạo `Sessions`; phối hợp với `Sessions.sort` và `Config`."""
        self.sessions = list(sessions)
        self.sessions.sort(key=lambda x: (x.start.hour, x.end.hour))
        self.current_session = None
        self.config = Config()

    def find(self, *, moment: time = None) -> Session | None:
        """Tìm phiên giao dịch chứa thời điểm chỉ định; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        moment = moment or datetime.now(tz=UTC).time()
        for session in self.sessions:
            if moment in session:
                return session
        return None

    def find_next(self, *, moment: time = None) -> Session:
        """Tìm phiên giao dịch kế tiếp; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        moment = moment or datetime.now(tz=UTC).time()
        for session in self.sessions:
            if delta(moment) < delta(session.start):
                return session
        return self.sessions[0]

    def __contains__(self, moment: time) -> bool:
        """Kiểm tra một phần tử có thuộc `Sessions` hay không; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        return True if self.find(moment=moment) is not None else False

    async def __aenter__(self):
        """Mở ngữ cảnh bất đồng bộ của `Sessions`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.check()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh bất đồng bộ của `Sessions`; dùng dữ liệu nội bộ của lớp và các đối tượng miền giao dịch."""
        await self.current_session.close() if self.current_session is not None else ...

    async def check(self):
        """Kiểm tra tính hợp lệ hoặc trạng thái của `Sessions`; phối hợp các tác vụ qua `asyncio`."""
        if self.current_session is not None and self.current_session.in_session():
            return
        now = datetime.now(tz=UTC).time()
        next_session = self.find(moment=now)
        if next_session and self.current_session is None:
            self.current_session = next_session
            await self.current_session.begin()
            return

        if next_session and self.current_session is not None:
            await self.current_session.close()
            self.current_session = next_session
            await self.current_session.begin()
            return

        if next_session is None and self.current_session is not None:
            await self.current_session.close()

        next_session = self.find_next(moment=now)
        secs = next_session.until() + 10
        logger.info(f"sleeping for {secs} seconds until next {next_session} session")
        await asyncio.sleep(secs)
        self.current_session = next_session
        await self.current_session.begin()
