"""Đọc và cập nhật bản ghi kết quả giao dịch từ nhiều định dạng."""
from datetime import datetime
import asyncio
import json
from pathlib import Path
import csv
import logging
from typing import Iterable

from .result_db import ResultDB
from ..core.config import Config
from ..core.meta_trader import MetaTrader
from ..core.models import TradePosition

logger = logging.getLogger(__name__)


class TradeRecords:
    """Đọc và cập nhật bản ghi giao dịch từ CSV, JSON hoặc SQLite."""
    config: Config
    mt5: MetaTrader
    result_db: type[ResultDB]
    positions: list[TradePosition] | None = None

    def __init__(self, *, records_dir: Path | str = ""):
        """Khởi tạo `TradeRecords`; phối hợp với `Config`."""
        self.config = Config()
        self.mt5 = MetaTrader()
        self.records_dir = records_dir or self.config.records_dir
        self.result_db = ResultDB

    def get_sql_records_unclosed(self):
        """Lấy các bản ghi SQLite chưa đóng; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        rows = self.result_db.execute_raw("select * from result where closed = 0")
        return rows

    async def update_sql_records(self):
        """Cập nhật các bản ghi giao dịch trong SQLite; gọi `MetaTrader.history_deals_get`."""
        conn = self.result_db.get_connection()
        rows = self.get_sql_records_unclosed()
        rows.sort(key=lambda r: r.time)
        start = datetime.fromtimestamp(rows[0].time/1000).replace(hour=0, minute=0)
        end = datetime.now().replace(hour=23, minute=59)
        deals = await self.mt5.history_deals_get(date_from=start, date_to=end)
        closing_deals = {deal.position_id: deal for deal in deals if deal.order != deal.position_id and deal.entry == self.mt5.DEAL_ENTRY_OUT}
        for row in rows:
            if row.order in closing_deals and not row.closed:
                deal = closing_deals[row.order]
                data = dict(profit=deal.profit, win=deal.profit > 0, closed=True, time_close=deal.time_msc, price_close=deal.price)
                row.save(conn=conn, update=True, data=data, commit=False)
        conn.commit()
        conn.close()

    def get_csv_records(self):
        """Lấy các bản ghi giao dịch từ tệp CSV; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        for file in self.records_dir.iterdir():
            if file.is_file() and file.name.endswith(".csv"):
                yield file

    def get_json_records(self):
        """Lấy các bản ghi giao dịch từ tệp JSON; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        for file in self.records_dir.iterdir():
            if file.is_file() and file.name.endswith(".json"):
                yield file

    async def read_update_csv(self, *, file: Path):
        """Đọc và cập nhật một tệp bản ghi CSV; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        try:
            with open(file, mode="r", newline="") as fr:
                reader: Iterable[dict] | csv.DictReader = csv.DictReader(fr)
                rows = [row for row in reader]
                rows = await self.update_rows(rows=rows)

            with open(file, mode="w", newline="") as fw:
                writer = csv.DictWriter(fw, fieldnames=reader.fieldnames, extrasaction="ignore", restval=None)
                writer.writeheader()
                writer.writerows(rows)
        except Exception as err:
            logger.error(f"Error: {err}. Unable to read and update csv trade records")

    async def read_update_json(self, *, file: Path):
        """Đọc và cập nhật một tệp bản ghi JSON; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        try:
            with open(file, mode="r") as fh:
                data = json.load(fh)
                rows = [row for row in data]
                rows = await self.update_rows(rows=rows)

            with open(file, mode="w") as fh:
                json.dump(rows, fh, indent=2)
        except Exception as err:
            logger.error(f"Error: {err}. Unable to read and update json trade records")

    async def update_rows(self, rows: list[dict]) -> list[dict]:
        """Cập nhật các dòng dữ liệu; gọi `MetaTrader.history_deals_get`."""
        rows.sort(key=lambda _row: _row["time"])
        start = datetime.fromtimestamp(float(rows[0]["time"]) / 1000).replace(hour=0, minute=0)
        end = datetime.now().replace(hour=23, minute=59)
        deals = await self.mt5.history_deals_get(date_from=start, date_to=end)
        closing_deals = {deal.position_id: deal for deal in deals if deal.order != deal.position_id and deal.entry == self.mt5.DEAL_ENTRY_OUT}
        for row in rows:
            if (self.str_to_bool(row["closed"])) is False  and (deal := closing_deals.get(int(row["order"]), 0)) and deal.order != deal.position_id and deal.entry == self.mt5.DEAL_ENTRY_OUT:
                row.update(profit=deal.profit, win=deal.profit > 0, closed=True, time_close=deal.time_msc/1000, price_close=deal.price)
        return rows

    @staticmethod
    def str_to_bool(val: bool | str):
        """Chuyển chuỗi biểu diễn xử lý thành kiểu đúng/sai; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        if isinstance(val, bool):
            return val
        elif val.lower() == "true":
            return True
        elif val.lower() == "false":
            return False
        else:
            raise TypeError(f"{val} is not a valid boolean value")

    async def update_csv_records(self):
        """Cập nhật toàn bộ tệp bản ghi CSV; phối hợp các tác vụ qua `asyncio`."""
        records = [self.read_update_csv(file=record) for record in self.get_csv_records()]
        await asyncio.gather(*records)

    async def update_json_records(self):
        """Cập nhật toàn bộ tệp bản ghi JSON; phối hợp các tác vụ qua `asyncio`."""
        records = [self.read_update_json(file=record) for record in self.get_json_records()]
        await asyncio.gather(*records)

    async def update_csv_record(self, *, file: Path | str):
        """Cập nhật một tệp bản ghi CSV; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        await self.read_update_csv(file=file)

    async def update_json_record(self, *, file: Path | str):
        """Cập nhật một tệp bản ghi JSON; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        await self.read_update_json(file=file)

    def read_update_csv_sync(self, *, file: Path):
        """Đọc và cập nhật tệp CSV theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        try:
            with open(file, mode="r", newline="") as fr:
                reader: Iterable[dict] | csv.DictReader = csv.DictReader(fr)
                rows = [row for row in reader]
                rows = self.update_rows_sync(rows=rows)

            with open(file, mode="w", newline="") as fw:
                writer = csv.DictWriter(fw, fieldnames=reader.fieldnames, extrasaction="ignore", restval=None)
                writer.writeheader()
                writer.writerows(rows)
        except Exception as err:
            logger.error(f"Error: {err}. Unable to read and update csv trade records")

    def read_update_json_sync(self, *, file: Path):
        """Đọc và cập nhật tệp JSON theo luồng đồng bộ; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        try:
            with open(file, mode="r") as fh:
                data = json.load(fh)
                rows = [row for row in data]
                rows = self.update_rows_sync(rows=rows)

            with open(file, mode="w") as fh:
                json.dump(rows, fh, indent=2)
        except Exception as err:
            logger.error(f"Error: {err}. Unable to read and update json trade records")

    def update_rows_sync(self, *, rows: list[dict]) -> list[dict]:
        """Cập nhật các dòng dữ liệu; gọi `MetaTrader._history_deals_get`."""
        rows.sort(key=lambda _row: _row["time"])
        start = datetime.fromtimestamp(float(rows[0]["time"]) / 1000).replace(hour=0, minute=0)
        end = datetime.now().replace(hour=23, minute=59)
        deals = self.mt5._history_deals_get(date_from=start, date_to=end)
        closing_deals = {deal.position_id: deal for deal in deals if
                         deal.order != deal.position_id and deal.entry == self.mt5.DEAL_ENTRY_OUT}
        for row in rows:
            if (self.str_to_bool(row["closed"])) is False and (deal := closing_deals.get(int(row["order"]),
                                                                                         0)) and deal.order != deal.position_id and deal.entry == self.mt5.DEAL_ENTRY_OUT:
                row.update(profit=deal.profit, win=deal.profit > 0, closed=True, time_close=deal.time_msc / 1000,
                           price_close=deal.price)
        return rows

    def update_csv_records_sync(self):
        """Cập nhật các tệp CSV theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        for record in self.get_csv_records():
            self.read_update_csv_sync(file=record)

    def update_json_records_sync(self):
        """Cập nhật các tệp JSON theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        for record in self.get_json_records():
            self.read_update_json_sync(file=record)

    def update_csv_record_sync(self, *, file: Path | str):
        """Cập nhật một tệp CSV theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        self.read_update_csv_sync(file=file)

    def update_json_record_sync(self, *, file: Path | str):
        """Cập nhật một tệp JSON theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        self.read_update_json_sync(file=file)
