"""Ghi nhận và lưu kết quả giao dịch."""

import csv
import json
from datetime import datetime
from logging import getLogger
from typing import Iterable, Literal
from threading import Lock

from ..core.config import Config
from ..core.models import OrderSendResult
from .result_db import ResultDB

logger = getLogger(__name__)


class Result:
    """Tổng hợp và lưu kết quả cùng tham số của giao dịch."""

    config: Config
    lock = Lock()

    def __init__(self, *, result: OrderSendResult, parameters: dict = None, name: str = "", **kwargs):
        """Khởi tạo `Result`; phối hợp với `Config`."""
        self.config = Config()
        self.parameters = parameters or {}
        self.result = result
        self.name = name or self.parameters.get("name", "Trades")
        self.extra_params = kwargs
        if not self.extra_params.get("time"):
            self.extra_params["time"] = datetime.now().timestamp() * 1000

    def to_sql(self):
        """Ghi bản ghi vào SQLite; phối hợp với `ResultDB.filter_dict` và `ResultDB`."""
        try:
            data = self.get_data() | {"name": self.name}
            data = ResultDB.filter_dict(data)
            db = ResultDB(**data)
            db.save(commit=True)
        except Exception as err:
            logger.error("%s: Error occurred while saving", err)

    def get_data(self) -> dict:
        """Lấy dữ liệu; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        res = self.result.get_dict(exclude={"retcode", "comment", "retcode_external", "request_id", "request"})
        req = self.result.request.get_dict(include={"symbol", "type", "sl", "tp"})
        return res | {"profit": 0, "closed": False, "win": False, "parameters": self.parameters} | req |self.extra_params

    async def save(self, *, trade_record_mode: Literal["csv", "json", "sql"] = None):
        """Lưu dữ liệu hiện tại; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        with self.lock:
            trade_record_mode = trade_record_mode or self.config.trade_record_mode
            if trade_record_mode == "csv":
                self.to_csv()
            elif trade_record_mode == "json":
                self.to_json()
            elif trade_record_mode == "sql":
                self.to_sql()
            else:
                logger.error(f"Invalid trade record mode: {trade_record_mode}")

    def save_sync(self, *, trade_record_mode: Literal["csv", "json", "sql"] = None):
        """Lưu dữ liệu hiện tại theo luồng đồng bộ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        with self.lock:
            trade_record_mode = trade_record_mode or self.config.trade_record_mode
            if trade_record_mode == "csv":
                self.to_csv()
            elif trade_record_mode == "json":
                self.to_json()
            elif trade_record_mode == "sql":
                self.to_sql()
            else:
                logger.error(f"Invalid trade record mode: {trade_record_mode}")

    def to_csv(self):
        """Xuất bản ghi sang tệp CSV; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        try:
            data = self.get_data()
            data["time"] = data["time"] / 1000
            parameters = data.pop("parameters", {})
            data |= parameters
            file = self.config.records_dir / f"{self.name}.csv"
            file.touch(exist_ok=True) if not file.exists() else ...
            read_file = file.open("r", newline="")
            reader: Iterable[dict] = csv.DictReader(read_file)
            rows: list[dict] = []
            headers = set()
            [(rows.append(row), headers.update(row.keys())) for row in reader]
            rows.append(data)
            headers.update(data.keys())
            read_file.close()
            with file.open("w", newline="") as write_file:
                writer = csv.DictWriter(write_file, fieldnames=headers, restval=None, extrasaction="ignore")
                writer.writeheader()
                writer.writerows(rows)
        except Exception as err:
            logger.error(f"Unable to save to csv: {err}")

    @staticmethod
    def serialize(value) -> str:
        """Tuần tự hóa dữ liệu để lưu trữ; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        try:
            return str(value)
        except Exception as err:
            logger.error("%s: Unable to serialize value", err)
            return ""

    def to_json(self):
        """Xuất bản ghi sang tệp JSON; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        try:
            file = self.config.records_dir / f"{self.name}.json"
            data = self.get_data()
            if not file.exists():
                file.touch()
                with file.open("w") as fh:
                    json.dump([], fh, indent=2)

            try:
                with file.open("r") as fh:
                    rows = json.load(fh)
                    rows.append(data)
            except json.decoder.JSONDecodeError as _:
                rows = [data]

            with file.open("w") as fh:
                json.dump(rows, fh, indent=2, skipkeys=True, default=self.serialize)
        except Exception as err:
            logger.error(f"Unable to save as json file: {err}")
