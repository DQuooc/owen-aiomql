"""Cung cấp kho khóa–giá trị được lưu bền vững bằng SQLite."""

import os
import sqlite3
from threading import Lock
from typing import MutableMapping, Iterable, Any
from logging import getLogger
from pathlib import Path


SENTINEL = object()
logger = getLogger(__name__)


class Store(MutableMapping):
    """Quản lý kho khóa–giá trị được lưu bằng SQLite."""

    autocommit: bool
    db_name: str
    table_name: str
    cursor: sqlite3.Cursor
    _conn: sqlite3.Connection = None
    conn: sqlite3.Connection
    lock: Lock = Lock()
    def __init__(self, db_name: str | Path = "", table_name="store", data: dict = None, flush: bool = False, autocommit: bool = True):
        """Khởi tạo `Store`; đọc hoặc ghi dữ liệu qua SQLite."""
        self.autocommit = autocommit
        self.db_name = db_name or os.environ.get("DB_NAME", "db.sqlite3")
        self.table_name = table_name
        if not self.autocommit:
            self.conn = self.connection(db_name)
        else:
            self.conn = sqlite3.connect(self.db_name, check_same_thread=False)
        self.cursor = self.conn.cursor()
        make_table_query = f"CREATE TABLE IF NOT EXISTS {self.table_name} (key unique, value)"
        self.conn.execute(make_table_query)
        if flush:
            flush_query = f"DELETE FROM {self.table_name}"
            self.conn.execute(flush_query)
            self.conn.commit()
        if data:
            load_query = f"REPLACE INTO {self.table_name} VALUES(?, ?)"
            self.conn.executemany(load_query, data.items())
            self.conn.commit()

    @classmethod
    def connection(cls, db_name: str | Path = ""):
        """Mở kết nối tới cơ sở dữ liệu; đọc hoặc ghi dữ liệu qua SQLite."""
        if cls._conn is not None:
            return cls._conn
        cls._conn = sqlite3.connect(db_name, check_same_thread=False)
        return cls._conn

    def __len__(self):
        """Trả về số phần tử của `Store`; làm việc với kho dữ liệu SQLite nội bộ."""
        count_query = f"SELECT COUNT(*) FROM {self.table_name}"
        rows = self.cursor.execute(count_query).fetchone()[0]
        return rows if rows is not None else 0

    def __contains__(self, key):
        """Kiểm tra một phần tử có thuộc `Store` hay không; làm việc với kho dữ liệu SQLite nội bộ."""
        contains_query = f"SELECT 1 FROM {self.table_name} WHERE key = ?"
        return self.cursor.execute(contains_query, (key,)).fetchone() is not None

    def __getitem__(self, key):
        """Lấy phần tử của `Store` theo khóa hoặc chỉ số; làm việc với kho dữ liệu SQLite nội bộ."""
        get_query = f"SELECT value FROM {self.table_name} WHERE key = ?"
        item = self.cursor.execute(get_query, (key,)).fetchone()
        if item is None:
            raise KeyError(key)
        return item[0]

    def __setitem__(self, key, value):
        """Gán phần tử của `Store` theo khóa hoặc chỉ số; đọc hoặc ghi dữ liệu qua SQLite."""
        set_query = f"REPLACE INTO {self.table_name} VALUES (?, ?)"
        self.cursor.execute(set_query, (key, value))
        if self.autocommit:
            self.conn.commit()

    def __delitem__(self, key):
        """Xóa phần tử của `Store` theo khóa; đọc hoặc ghi dữ liệu qua SQLite."""
        if key not in self:
            raise KeyError(key)
        delete_query = f"DELETE FROM {self.table_name} WHERE key = ?"
        self.cursor.execute(delete_query, (key,))
        if self.autocommit:
            self.conn.commit()

    def __iter__(self):
        """Duyệt các phần tử của `Store`; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.iterkeys()

    def __repr__(self):
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Store`; làm việc với kho dữ liệu SQLite nội bộ."""
        return f"{self.__class__.__name__}()"

    def iterkeys(self):
        """Duyệt lần lượt các khóa đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        key_query = f"SELECT key FROM {self.table_name}"
        for row in self.cursor.execute(key_query):
            yield row[0]

    def itervalues(self):
        """Duyệt lần lượt các giá trị đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        value_query = f"SELECT value FROM {self.table_name}"
        for row in self.cursor.execute(value_query):
            yield row[0]

    def iteritems(self):
        """Duyệt lần lượt các cặp khóa và giá trị; làm việc với kho dữ liệu SQLite nội bộ."""
        item_query = f"SELECT key, value FROM {self.table_name}"
        for row in self.cursor.execute(item_query):
            yield row[0], row[1]

    def keys(self):
        """Lấy các khóa đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return list(self.iterkeys())

    def values(self):
        """Lấy các giá trị đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return list(self.itervalues())

    def items(self):
        """Lấy các cặp khóa và giá trị đang được lưu; làm việc với kho dữ liệu SQLite nội bộ."""
        return list(self.iteritems())

    def update(self, data: MutableMapping | Iterable[Iterable[Any]] = None, /, **kwargs):
        """Cập nhật dữ liệu của `Store`; đọc hoặc ghi dữ liệu qua SQLite."""
        data = (dict(data if data is not None else {}) or {}) | kwargs
        update_query = f"REPLACE INTO {self.table_name} VALUES(?, ?)"
        self.conn.executemany(update_query, data.items())
        if self.autocommit:
            self.conn.commit()

    def setdefault(self, key, default = None, /):
        """Lấy giá trị theo khóa hoặc tạo giá trị mặc định; làm việc với kho dữ liệu SQLite nội bộ."""
        if key in self:
            return self[key]
        self[key] = default
        return self[key]

    def get(self, key, /, default=None):
        """Lấy một giá trị hoặc bản ghi phù hợp; làm việc với kho dữ liệu SQLite nội bộ."""
        try:
            value = self[key]
            return value
        except KeyError:
            return default

    def clear(self):
        """Xóa toàn bộ dữ liệu mà `Store` đang quản lý; đọc hoặc ghi dữ liệu qua SQLite."""
        clear_query = f"DELETE FROM {self.table_name}"
        self.cursor.execute(clear_query)
        if self.autocommit:
            self.conn.commit()

    def pop(self, key, /, default=SENTINEL):
        """Lấy rồi xóa một giá trị theo khóa; làm việc với kho dữ liệu SQLite nội bộ."""
        try:
            value = self[key]
            del self[key]
            return value
        except KeyError as err:
            if default is SENTINEL:
                raise err
            return default

    @classmethod
    def commit(cls, conn: sqlite3.Connection = None, close: bool = False):
        """Ghi các thay đổi đang chờ xuống nơi lưu trữ; đọc hoặc ghi dữ liệu qua SQLite."""
        with cls.lock:
            conn = conn or cls.connection()
            conn.commit()
            if close:
                conn.close()

    async def acommit(self, conn: sqlite3.Connection = None, close: bool = False):
        """Ghi bất đồng bộ các thay đổi đang chờ xuống nơi lưu trữ; làm việc với kho dữ liệu SQLite nội bộ."""
        self.commit(conn=conn, close=close)

    @property
    def data(self):
        """Đọc hoặc cập nhật dữ liệu mà `Store` đang quản lý; làm việc với kho dữ liệu SQLite nội bộ."""
        select_query = f"SELECT * FROM {self.table_name}"
        res = self.cursor.execute(select_query).fetchall()
        return {key: value for key, value in res}
