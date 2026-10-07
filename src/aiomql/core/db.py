"""Cung cấp lớp ánh xạ đối tượng sang SQLite dựa trên lớp dữ liệu."""

import os
import sqlite3
import re
from logging import getLogger
from dataclasses import Field, fields, asdict, MISSING, is_dataclass
from typing import ClassVar
from functools import cached_property

from .config import Config

logger = getLogger(__name__)

class DB:
    """Lớp nền ánh xạ mô hình dữ liệu sang bảng SQLite."""

    _table: ClassVar[str] = ""
    _initialized: ClassVar[bool] = False
    TYPES: ClassVar[dict] = {str: "TEXT", float: "REAL", int: "INTEGER", bool: "BOOLEAN", None: "NULL", bytes: "BLOB"}
    config: ClassVar[Config]
    db_name: ClassVar[str]

    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `DB`; phối hợp với `Config`."""
        cls.config = Config()
        if not cls._initialized:
            cls.init_db()
        return super().__new__(cls)

    # def __post_init__(self):
    #     """Được gọi sau __init__ để khởi tạo cơ sở dữ liệu."""
    #     self.init_db()

    @cached_property
    def pk(self):
        """Lấy tên khóa chính của mô hình dữ liệu; làm việc với kho dữ liệu SQLite nội bộ."""
        name = next((f.name for f in fields(self) if f.metadata.get("PRIMARY KEY")))
        return name, getattr(self, name)

    @classmethod
    def init_db(cls):
        """Khởi tạo tệp và bảng cơ sở dữ liệu; phối hợp với `Config`."""
        cls.config = Config()
        cls.db_name = getattr(cls.config, "db_name", os.getenv("DB_NAME", "db.sqlite3"))
        conn = sqlite3.connect(cls.db_name)
        cls.create_table(conn)
        conn.close()
    
    @classmethod
    def get_connection(cls):
        """Lấy kết nối; đọc hoặc ghi dữ liệu qua SQLite."""
        if not cls._initialized:
            cls.init_db()
            cls._initialized = True
        conn = sqlite3.connect(cls.db_name)
        conn.row_factory = cls.dict_factory()
        return conn

    @classmethod
    def create_table(cls, conn: sqlite3.Connection):
        """Tạo bảng dữ liệu; đọc hoặc ghi dữ liệu qua SQLite."""
        try:
            if not is_dataclass(cls):
                return
            cls._table = cls._table or cls.__name__.lower()
            columns = cls.get_columns()
            conn.execute(f"""CREATE TABLE IF NOT EXISTS'{cls._table}' ({columns})""")
            conn.commit()
            cls._initialized = True
        except Exception as e:
            logger.error("%s: Failed to create table", e)

    @classmethod
    def dict_factory(cls):
        """Chuyển một hàng dữ liệu SQLite thành từ điển; làm việc với kho dữ liệu SQLite nội bộ."""
        def dict_factory(cursor, row):
            """Chuyển một hàng dữ liệu SQLite thành từ điển; làm việc với kho dữ liệu SQLite nội bộ."""
            cols = [column[0] for column in cursor.description]
            kw = {key: value for key, value in zip(cols, row)}
            return cls(**kw)
        return dict_factory

    @staticmethod
    def sanitize(identifier):
        """Kiểm tra và làm sạch định danh SQL; làm việc với kho dữ liệu SQLite nội bộ."""
        if re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", identifier):
            return f'"{identifier}"'
        raise ValueError("Invalid table name")

    @classmethod
    def types(cls, key):
        """Ánh xạ kiểu Python sang kiểu cột SQLite; làm việc với kho dữ liệu SQLite nội bộ."""
        return cls.TYPES.get(key, "TEXT")

    @staticmethod
    def get_default(col: Field):
        """Lấy giá trị mặc định; làm việc với kho dữ liệu SQLite nội bộ."""
        if isinstance(col.default, type(MISSING)) and isinstance(col.default_factory, type(MISSING)):
            return ""

        if not isinstance(col.default, type(MISSING)):
            return f"DEFAULT {col.default!r}"

        if not isinstance(col.default_factory, type(MISSING)):
            return f"DEFAULT {col.default_factory()!r}"

        return ""

    @staticmethod
    def get_metadata(col: Field):
        """Lấy siêu dữ liệu; làm việc với kho dữ liệu SQLite nội bộ."""
        return f"{' '.join(meta for meta, value in col.metadata.items() if value)}"

    @classmethod
    def get_columns(cls):
        """Lấy các cột; làm việc với kho dữ liệu SQLite nội bộ."""
        cols = fields(cls)
        cols = [f"'{col.name}' {cls.types(col.type)} {cls.get_metadata(col)} {cls.get_default(col)}" for col in
                cols]
        return ",".join(cols)

    def asdict(self):
        """Chuyển mô hình thành từ điển; làm việc với kho dữ liệu SQLite nội bộ."""
        return asdict(self)

    def get_data(self):
        """Lấy dữ liệu; làm việc với kho dữ liệu SQLite nội bộ."""
        return self.asdict()

    @classmethod
    def clear(cls):
        """Xóa toàn bộ dữ liệu mà `DB` đang quản lý; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        conn.execute(f"DELETE FROM {cls._table}")
        conn.commit()
        conn.close()

    def save(self, commit: bool = True, update: bool = False, data: dict = None, conn: sqlite3.Connection = None):
        """Lưu dữ liệu hiện tại; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = conn or self.get_connection()
        data = data or self.get_data()
        columns = ", ".join(self.sanitize(key) for key in data.keys())
        placeholders = ", ".join(["?"] * len(data))
        values = tuple(data.values())
        table = self.sanitize(self._table)
        if update:
            pk, pk_value = self.pk
            update_columns = ", ".join(f"{self.sanitize(key)} = ?" for key in data.keys())
            query = f"UPDATE {table} SET {update_columns} WHERE {self.sanitize(pk)} = {pk_value}"
        else:
            query = f"INSERT INTO {table} ({columns}) VALUES ({placeholders})"
        conn.execute(query, values)
        if commit:
            conn.commit()
            conn.close()

    @classmethod
    def get(cls, **kwargs):
        """Lấy một giá trị hoặc bản ghi phù hợp; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        _query = " AND ".join([f'"{key}" = "{value}"' for key, value in kwargs.items()])
        query = f"""SELECT * FROM {cls.sanitize(cls._table)} WHERE {_query}"""
        res = conn.execute(query).fetchone()
        conn.close()
        return res

    @classmethod
    def filter(cls, **kwargs):
        """Lọc các bản ghi theo điều kiện; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        _query = " AND ".join([f'"{key}" = "{value}"' for key, value in kwargs.items()])
        _query = f"WHERE {_query}" if _query else ""
        query = f"SELECT * FROM {cls.sanitize(cls._table)} {_query}"
        res = conn.execute(query).fetchall()
        conn.close()
        return res

    @classmethod
    def update(cls, data=None, /, **kwargs):
        """Cập nhật dữ liệu của `DB`; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        update = data or {}
        _query = " AND ".join([f'"{key}" = "{value}"' for key, value in kwargs.items()])
        update = ", ".join([f'"{key}" = "{value}"' for key, value in update.items()])
        table = cls.sanitize(cls._table)
        _query = f"WHERE {_query}" if _query else ""
        query = f"""UPDATE {table} SET {update} {_query}"""
        conn.execute(query)
        conn.commit()
        conn.close()
        return True

    @classmethod
    def fields(cls) -> list[str]:
        """Lấy danh sách trường của mô hình; làm việc với kho dữ liệu SQLite nội bộ."""
        fs = fields(cls)
        return [f.name for f in fs]

    @classmethod
    def drop_table(cls):
        """Xóa bảng dữ liệu của mô hình; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        conn.execute(f"DROP TABLE IF EXISTS {cls._table}")
        conn.commit()
        conn.close()


    @classmethod
    def all(cls, limit: int | None = None):
        """Lấy toàn bộ bản ghi phù hợp; đọc hoặc ghi dữ liệu qua SQLite."""
        conn = cls.get_connection()
        if limit is None:
            query = f"SELECT * FROM {cls._table}"
        else:
            query = f"SELECT * FROM {cls._table} LIMIT {limit}"
        res = conn.execute(query).fetchall()
        conn.close()
        return res

    @classmethod
    def execute_raw(cls, sql: str, params: tuple | list | dict = None, *, allow_write: bool = False):
        """Thực thi câu lệnh SQL thô đã được kiểm soát; đọc hoặc ghi dữ liệu qua SQLite."""
        if not sql or not isinstance(sql, str):
            raise ValueError("SQL query must be a non-empty string")

        # Chuẩn hóa khoảng trắng và chuyển sang chữ hoa để kiểm tra
        sql_normalized = " ".join(sql.split()).upper()

        # Các mẫu nguy hiểm tuyệt đối không được phép xuất hiện
        dangerous_patterns = [
            r";\s*DROP\s+",
            r";\s*DELETE\s+",
            r";\s*TRUNCATE\s+",
            r";\s*ALTER\s+",  
            r";\s*CREATE\s+",
            r"--",  # Chú thích SQL
            r"/\*",  # Chú thích dạng khối
            r"EXEC\s*\(",
            r"EXECUTE\s*\(",
            r"XP_",  # Thủ tục lưu trữ mở rộng
            r"SP_",  # Thủ tục lưu trữ hệ thống
            r"0x[0-9A-F]+",  # Giá trị thập lục phân thường xuất hiện trong tấn công
        ]

        for pattern in dangerous_patterns:
            if re.search(pattern, sql_normalized, re.IGNORECASE):
                raise ValueError(f"SQL query contains dangerous pattern: {pattern}")

        # Kiểm tra trường hợp chứa nhiều câu lệnh qua nhiều dấu chấm phẩy
        # Cho phép dấu chấm phẩy cuối câu nhưng không cho phép nhiều câu lệnh
        sql_stripped = sql.strip().rstrip(";")
        if ";" in sql_stripped:
            raise ValueError("Multiple SQL statements are not allowed")

        # Xác định loại câu lệnh
        sql_type = sql_normalized.split()[0] if sql_normalized.split() else ""

        # Khai báo các loại câu lệnh được phép
        read_statements = {"SELECT"}
        write_statements = {"INSERT", "UPDATE", "DELETE"}

        if sql_type in write_statements:
            if not allow_write:
                raise PermissionError(
                    f"{sql_type} operations require allow_write=True. "
                    "This is a safety measure to prevent accidental data modification."
                )
        elif sql_type not in read_statements:
            raise ValueError(
                f"Unsupported SQL statement type: {sql_type}. "
                f"Allowed: SELECT, or INSERT/UPDATE/DELETE with allow_write=True"
            )

        # Kiểm tra kiểu của tham số
        if params is not None and not isinstance(params, (tuple, list, dict)):
            raise ValueError("params must be tuple, list, or dict")

        # Thực thi truy vấn bằng các giá trị tham số hóa
        conn = cls.get_connection()
        try:
            if params:
                cursor = conn.execute(sql, params)
            else:
                cursor = conn.execute(sql)

            if sql_type == "SELECT":
                results = cursor.fetchall()
                conn.close()
                return results
            else:
                # Với thao tác ghi, xác nhận thay đổi và trả về số dòng bị tác động
                affected_rows = cursor.rowcount
                conn.commit()
                conn.close()
                return affected_rows

        except sqlite3.Error as e:
            conn.close()
            logger.error("SQL execution error: %s", e)
            raise ValueError(f"SQL execution failed: {e}") from e

    @classmethod
    def filter_dict(cls, data: dict, exclude: set[str] = None, include: set[str] = None) -> dict:
        """Lọc từ điển; làm việc với kho dữ liệu SQLite nội bộ."""
        exclude, include = exclude or set(), include or set(cls.fields())
        filter_ = include.difference(exclude)
        return {key: value for key, value in data.items() if key in filter_ and value is not None}