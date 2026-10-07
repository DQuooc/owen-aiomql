"""Quản lý trạng thái khóa–giá trị dùng chung và lưu bền vững bằng SQLite."""

import os
import json
import sqlite3
from pathlib import Path
from threading import Lock
from typing import Self
from typing import MutableMapping, Iterable, Any, ClassVar
from logging import getLogger

SENTINEL = object()
logger = getLogger(__name__)


class State(MutableMapping):
    """Quản lý trạng thái khóa–giá trị dùng chung được lưu bằng SQLite."""

    _data: ClassVar
    _instance: Self
    _lock: Lock
    db_name: str
    autocommit: bool
    _initialized = False

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        with (lock := Lock()) as _:
            if not hasattr(cls, '_instance'):
                cls._data = {}
                cls._lock = lock
                cls._instance = super().__new__(cls)
        return cls._instance

    def __init__(self, db_name: str | Path = "", data: dict = None, flush: bool = False, autocommit: bool = True):
        """Khởi tạo `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        with self._lock:
            self.autocommit = autocommit
            self.init(data=data, flush=flush, db_name=db_name)

    @property
    def data(self):
        """Đọc hoặc cập nhật dữ liệu mà `State` đang quản lý; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.__class__._data

    @data.setter
    def data(self, value):
        """Đọc hoặc cập nhật dữ liệu mà `State` đang quản lý; làm việc với kho dữ liệu SQLite nội bộ."""
        assert isinstance(value, dict)
        self.__class__._data = value

    def __repr__(self):
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        return repr(self.data)

    def __iter__(self):
        """Duyệt các phần tử của `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        return iter(self.data)

    def __len__(self):
        """Trả về số phần tử của `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        return len(self.data)

    def __contains__(self, key):
        """Kiểm tra một phần tử có thuộc `State` hay không; làm việc với kho dữ liệu SQLite nội bộ."""
        return key in self.data

    def __setitem__(self, key, value):
        """Gán phần tử của `State` theo khóa hoặc chỉ số; làm việc với kho dữ liệu SQLite nội bộ."""
        self.data[key] = value
        if self.autocommit:
            self.commit()

    def __getitem__(self, key):
        """Lấy phần tử của `State` theo khóa hoặc chỉ số; làm việc với kho dữ liệu SQLite nội bộ."""
        value = self.data[key]
        return value

    def __delitem__(self, key):
        """Xóa phần tử của `State` theo khóa; làm việc với kho dữ liệu SQLite nội bộ."""
        del self.data[key]
        if self.autocommit:
            self.commit()

    def pop(self, key, default=SENTINEL):
        """Lấy rồi xóa một giá trị theo khóa; làm việc với kho dữ liệu SQLite nội bộ."""
        if default is SENTINEL:
            value = self.data.pop(key)
        else:
            value = self.data.pop(key, default)
        if self.autocommit:
            self.commit()
        return value

    def get(self, key, default=None):
        """Lấy một giá trị hoặc bản ghi phù hợp; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.data.get(key, default)

    def update(self, data: MutableMapping | Iterable[Iterable[Any]] = None, /, **kwargs):
        """Cập nhật dữ liệu của `State`; làm việc với kho dữ liệu SQLite nội bộ."""
        self.data.update(data, **kwargs)
        if self.autocommit:
            self.commit()

    def setdefault(self, key, default = None, /):
        """Lấy giá trị theo khóa hoặc tạo giá trị mặc định; làm việc với kho dữ liệu SQLite nội bộ."""
        value = self.data.setdefault(key, default)
        if self.autocommit:
            self.commit()
        return value

    def keys(self):
        """Lấy các khóa đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.data.keys()

    def values(self):
        """Lấy các giá trị đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.data.values()

    def items(self):
        """Lấy các cặp khóa và giá trị đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.data.items()

    def load(self, *, conn = None, data: dict = None):
        """Nạp dữ liệu đã lưu vào bộ nhớ; đọc hoặc ghi dữ liệu qua SQLite."""
        owns_connection = conn is None
        try:
            conn = conn or self.conn
            res = conn.execute("SELECT value FROM state where key = 'data'").fetchone()
            raw = res[0] if res else None
            if raw is None:
                db_data = {}
            else:
                try:
                    db_data = json.loads(raw)
                except (json.JSONDecodeError, UnicodeDecodeError, TypeError) as exc:
                    raise ValueError("State trong database không phải JSON hợp lệ") from exc

                if not isinstance(db_data, dict):
                    raise ValueError("State trong database phải là một dictionary")
            db_data |= (data or {})
            self.update(db_data)
            self.commit(conn=conn)
        except Exception as err:
            logger.error("%s: Failed to load state data from database", err)
            raise
        finally:
            if owns_connection and conn is not None:
                conn.close()

    def init(self, data: dict = None, flush: bool = False, db_name: str = ""):
        """Khởi tạo lại dữ liệu của `State`; đọc hoặc ghi dữ liệu qua SQLite."""
        if self._initialized:
            return
        self.db_name = db_name or os.environ.get("DB_NAME", "db.sqlite3")
        conn = self.conn
        try:
            conn.execute("CREATE TABLE IF NOT EXISTS state (key text unique, value blob)")
            if flush:
                self.data = data or {}
                self.commit(conn=conn)
            else:
                self.load(conn=conn, data=data)
            self._initialized = True
        finally:
            conn.close()
    
    def flush(self, data: dict = None):
        """Xóa dữ liệu hiện có rồi nạp lại trạng thái ban đầu; làm việc với kho dữ liệu SQLite nội bộ."""
        self.data = data or {}
        self.commit()

    def commit(self, *, conn: sqlite3.Connection = None, close: bool = True):
        """Ghi các thay đổi đang chờ xuống nơi lưu trữ; đọc hoặc ghi dữ liệu qua SQLite."""
        value = json.dumps(self.data, allow_nan=False).encode("utf-8")
        value = sqlite3.Binary(value)
        conn = conn or self.conn
        conn.execute("REPLACE INTO state (key, value) VALUES ('data', ?)", (value,))
        conn.commit()
        if close:
            conn.close()

    @property
    def conn(self):
        """Lấy kết nối cơ sở dữ liệu hiện tại; đọc hoặc ghi dữ liệu qua SQLite."""
        return sqlite3.connect(self.db_name)

    async def acommit(self, conn=None, close=True):
        """Ghi bất đồng bộ các thay đổi đang chờ xuống nơi lưu trữ; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = conn or self.conn
        value = json.dumps(self.data, allow_nan=False).encode("utf-8")
        value = sqlite3.Binary(value)
        conn.execute("REPLACE INTO state (key, value) VALUES ('data', ?)", (value,))
        conn.commit()
        if close:
            conn.close()
