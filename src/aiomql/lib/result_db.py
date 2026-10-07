"""Lưu kết quả giao dịch trong cơ sở dữ liệu SQLite."""

import json
from dataclasses import dataclass, field
from typing import ClassVar

from ..core.db import DB


@dataclass(kw_only=True)
class ResultDB(DB):
    """Biểu diễn một bản ghi kết quả giao dịch trong SQLite."""
    _table: ClassVar[str] = "result"
    deal: int = field(metadata={"NOT NULL": True})
    order: int = field(metadata={"PRIMARY KEY": True, "UNIQUE": True, "NOT NULL": True})
    name: str = field(metadata={"NOT NULL": True})
    symbol: str = field(metadata={"NOT NULL": True})
    time: float = field(metadata={"NOT NULL": True})
    volume: float
    price: float
    type: int
    bid: float = 0
    ask: float = 0
    tp: float = 0
    sl: float = 0
    price_close: float = 0
    time_close: float = 0
    expected_profit: float = 0
    win: bool = False
    closed: bool = False
    profit: float = 0
    comment: str = ""
    parameters: dict|bytes|str = ""

    def __post_init__(self):
        """Hoàn tất khởi tạo `ResultDB` sau khi lớp dữ liệu tạo đối tượng; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        if isinstance(self.parameters, (bytes, str)):
            if not self.parameters:
                self.parameters = {}
            else:
                try:
                    params = json.loads(self.parameters)
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                    raise ValueError("Result parameters are not valid JSON") from exc
                if not isinstance(params, dict):
                    raise ValueError("Result parameters must be a JSON object")
                self.parameters = params
        elif self.parameters is None:
            self.parameters = {}
        elif not isinstance(self.parameters, dict):
            raise TypeError("Result parameters must be a dictionary or JSON")
        self.comment = str() if self.comment is None else self.comment
        self.win = bool(self.win)
        self.closed = bool(self.closed)

    def get_data(self) -> dict:
        """Lấy dữ liệu; đọc hoặc ghi dữ liệu trên hệ thống tệp."""
        data = self.asdict()
        data["parameters"] = json.dumps(data["parameters"], allow_nan=False).encode("utf-8")
        return data

    @classmethod
    def dump_to_csv(cls, file_path: str = None, name: str = ""):
        """Ghi các kết quả giao dịch ra tệp CSV; đọc hoặc ghi bản ghi qua CSV, JSON hoặc SQLite."""
        import csv
        query = {"name": name} if name else {}
        records = cls.filter(**query)
        if not records:
            return

        data_to_write = [record.asdict() for record in records]
        # Trường 'parameters' là từ điển nên không phù hợp để lưu trong một ô CSV.
        # Trải phẳng dữ liệu và thêm tiền tố 'param_' vào từng khóa tham số.
        # Cách này cũng xử lý được các bản ghi có bộ tham số khác nhau.
        
        processed_data = []
        all_keys = set()

        for item in data_to_write:
            params = item.pop('parameters', {})
            if isinstance(params, dict):
                for p_key, p_value in params.items():
                    item[f'param_{p_key}'] = p_value
            processed_data.append(item)
            all_keys.update(item.keys())
            
        # Bảo đảm mọi từ điển có cùng tập khóa
        final_data = []
        sorted_keys = sorted(list(all_keys))
        for item in processed_data:
            row = {key: item.get(key) for key in sorted_keys}
            final_data.append(row)
        file_path = file_path or (f"{name}.csv" if name else "") or cls.config.db_dir_name / 'result_db.csv'
        with open(file_path, 'w', newline='') as output_file:
            writer = csv.DictWriter(output_file, fieldnames=sorted_keys)
            writer.writeheader()
            writer.writerows(final_data)


