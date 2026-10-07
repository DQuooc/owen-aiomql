"""Cung cấp các lớp nền để quản lý cấu trúc dữ liệu trong aiomql."""

import enum
from typing import Literal
from logging import getLogger
from functools import cache

from .config import Config
from .meta_trader import MetaTrader
from .sync.meta_trader import MetaTrader as MetaTraderSync

logger = getLogger(__name__)

class BaseMeta(type):
    def __getattr__(cls, item):
        """Chuyển tiếp việc đọc thuộc tính chưa có của `BaseMeta`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        if item in ("config", "mt5"):
            cls._setup()
        return super().__getattribute__(item)

    def __call__(cls, *args, **kwargs):
        """Cho phép gọi `BaseMeta` như một hàm; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        inst = super().__call__(*args, **kwargs)
        inst.__class__._setup()
        return inst

    def _setup(cls):
        """Thiết lập các phụ thuộc dùng chung cho lớp; phối hợp với `Config`."""
        if 'config' not in cls.__dict__:
            cls.config = Config()
        if 'mt5' not in cls.__dict__:
            cls.mt5 = MetaTrader() if cls.__dict__.get("mode", "") != "sync" else MetaTraderSync()


class Base:
    """Lớp nền cung cấp thao tác chung cho các cấu trúc dữ liệu của aiomql."""
    exclude: set[str] = {"mt5", "config", "exclude", "include", "annotations", "class_vars", "dict", "_instance", "mode"}
    include: set[str] = {}

    def __init__(self, **kwargs):
        """Khởi tạo `Base`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        self.set_attributes(**kwargs)

    def __repr__(self):
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Base`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        kv = [
            (k, v)
            for k, v in self.__dict__.items()
            if not k.startswith("_") and (type(v) in (int, float, str) or isinstance(v, enum.Enum))
        ]
        args = ", ".join("%s=%s" % (i, j) for i, j in kv[:3])
        args = args if len(kv) <= 3 else args + " ... " + ", ".join("%s=%s" % (i, j) for i, j in kv[-1:])
        return "%(class)s(%(args)s)" % {"class": self.__class__.__name__, "args": args}

    def set_attributes(self, **kwargs):
        """Thiết lập thuộc tính; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        for i, j in kwargs.items():
            try:
                setattr(self, i, self.annotations[i](j))
            except KeyError:
                logger.debug(f"Attribute {i} does not belong to class {self.__class__.__name__}")
                continue

            except (ValueError, TypeError):
                logger.debug(f"Cannot covert object of type {type(j)} to type {self.annotations[i]}")
                setattr(self, i, j)

            except Exception as exe:
                logger.debug(f"Did not set attribute {i} on class {self.__class__.__name__} due to {exe}")
                continue

    @property
    @cache
    def annotations(self) -> dict:
        """Thu thập khai báo kiểu của lớp; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        annots = {}
        for base in self.__class__.__mro__[::-1]:
            annots |= getattr(base, "__annotations__", {})
        return annots

    def get_dict(self, exclude: set[str] = None, include: set[str] = None) -> dict:
        """Lấy từ điển; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        exclude, include = exclude or set(), include or set()
        filter_ = include or set(self.dict.keys()).difference(exclude)
        return {key: value for key, value in self.dict.items() if key in filter_ and value is not None}

    @property
    @cache
    def class_vars(self):
        """Lấy các biến cấp lớp; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        clss = self.__class__.__mro__[::-1]
        cls_dict = {}
        for cls in clss:
            cls_dict |= cls.__dict__
        return {key: value for key, value in cls_dict.items() if key in self.annotations}

    @property
    def dict(self) -> dict:
        """Chuyển dữ liệu của đối tượng thành từ điển; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        _filter = self.exclude.difference(self.include)
        return {
            key: value
            for key, value in (self.class_vars | self.__dict__).items()
            if key not in _filter and value is not None
        }


class _Base(Base, metaclass=BaseMeta):
    """Lớp nền mở rộng, liên kết dữ liệu với MetaTrader và cấu hình dùng chung."""
    mt5: MetaTrader | MetaTraderSync
    config: Config
    mode: Literal["async", "sync"] = "async"

    def __getstate__(self):
        """Chuẩn bị trạng thái của `_Base` để tuần tự hóa; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        state = self.__dict__.copy()
        state.pop("mt5", None)
        return state
