"""Cung cấp các tiện ích thời gian cho thư viện giao dịch aiomql."""

import asyncio
import time
from logging import getLogger

from .config import Config

logger = getLogger(__name__)


async def auto_commit():
    """Định kỳ ghi trạng thái dùng chung xuống nơi lưu trữ; phối hợp với `Config`."""
    config = Config()
    try:
        with config.state.conn as conn:
            while config.shutdown is False:
                await config.state.acommit(conn=conn, close=False)
                await sleep(config.db_commit_interval)
    except Exception as err:
        logger.error("%s: Error occurred in auto_commit", err)


async def sleep(secs):
    """Tạm dừng theo chế độ chạy thật hoặc kiểm thử dữ liệu quá khứ; phối hợp các tác vụ qua `asyncio`."""
    await asyncio.sleep(secs)


def sleep_sync(secs):
    """Tạm dừng đồng bộ theo chế độ chạy thật hoặc kiểm thử dữ liệu quá khứ; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    time.sleep(secs)
