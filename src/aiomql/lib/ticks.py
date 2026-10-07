"""Biểu diễn và xử lý dữ liệu giá tick."""

from typing import Iterable, Self
from datetime import datetime

import pandas as pd
from pandas import DataFrame, Series

from ..ta_libs import pandas_ta_classic as ta
from ..core.constants import TickFlag


class Tick:
    """Biểu diễn một lần cập nhật giá của công cụ tài chính."""

    time: float
    bid: float
    ask: float
    last: float
    volume: float
    time_msc: float
    flags: TickFlag
    volume_real: float
    index: int | float
    Index: int

    def __init__(self, **kwargs):
        """Khởi tạo `Tick`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if not all(key in kwargs for key in ["bid", "ask", "last", "volume"]):
            raise ValueError("bid, ask, last and volume, time must be present in the keyword arguments")
        self.time = kwargs.pop("time", datetime.now().timestamp())
        self.time_msc = kwargs.pop("time_msc", self.time * 1000)
        self.Index = kwargs.pop("Index", 0)
        self.index = kwargs.pop("index", self.time_msc)
        self.set_attributes(**kwargs)

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Tick`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return (
            "%(class)s(Index=%(Index)s, time=%(time)s, bid=%(bid)s, ask=%(ask)s, last=%(last)s, volume=%(volume)s, index=%(index)s)"
            % {
                "class": self.__class__.__name__,
                "time": self.time,
                "bid": self.bid,
                "ask": self.ask,
                "last": self.last,
                "volume": self.volume,
                "index": self.index,
                "Index": self.Index,
            }
        )

    def __eq__(self, other: Self) -> bool:
        """So sánh `Tick` bằng một đối tượng khác; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.time_msc == other.time_msc

    def __lt__(self, other: Self) -> bool:
        """So sánh thứ tự nhỏ hơn của `Tick`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.time_msc < other.time_msc

    def __hash__(self) -> int:
        """Tạo giá trị băm cho `Tick`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return hash(self.time_msc)

    def __getitem__(self, item: str):
        """Lấy phần tử của `Tick` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__[item]

    def __setitem__(self, key: str, value):
        """Gán phần tử của `Tick` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        self.__dict__[key] = value

    def __iter__(self):
        """Duyệt các phần tử của `Tick`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return iter(self.__dict__.items())

    def keys(self):
        """Lấy các khóa đang được lưu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__.keys()

    def values(self):
        """Lấy các giá trị đang được lưu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__.values()

    def dict(self, exclude: set = None, include: set = None) -> dict:
        """Chuyển dữ liệu của đối tượng thành từ điển; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        exclude = exclude or set()
        include = include or set()
        keys = include or set(self.__dict__.keys()).difference(exclude)
        return {k: v for k, v in self.__dict__.items() if k in keys}

    def set_attributes(self, **kwargs):
        """Thiết lập thuộc tính; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        for key, value in kwargs.items():
            setattr(self, key, value)

    def to_series(self) -> pd.Series:
        """Chuyển dữ liệu thành pandas Series; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return Series(self.dict(exclude={"Index", "index"}))

class Ticks:
    """Chứa và thao tác tập dữ liệu tick theo kiểu bảng."""

    time: Series
    bid: Series
    ask: Series
    last: Series
    volume: Series
    time_msc: Series
    flags: Series
    volume_real: Series
    Index: Series
    index: Series

    def __init__(self, *, data: DataFrame | Iterable | Self, flip: bool = False):
        """Khởi tạo `Ticks`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if isinstance(data, DataFrame):
            data = data
        elif isinstance(data, type(self)):
            data = DataFrame(data.data)
        elif isinstance(data, Iterable):
            data = DataFrame(data)
        else:
            raise ValueError(f"Cannot create DataFrame from object of {type(data)}")
        self._data = data.iloc[::-1] if flip else data

        if 'time_msc' in self._data.columns:
            self._data.index = self._data.time_msc

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Ticks`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return repr(self._data)

    def __len__(self) -> int:
        """Trả về số phần tử của `Ticks`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._data.shape[0]

    def __contains__(self, item: Tick) -> bool:
        """Kiểm tra một phần tử có thuộc `Ticks` hay không; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return item.time_msc == self[item.Index].time_msc

    def __getattr__(self, item: str):
        """Chuyển tiếp việc đọc thuộc tính chưa có của `Ticks`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if item in list(self._data.columns.values):
            return self._data[item]

        if item == "index":
            return self._data.index

        if item == "Index":
            return Series(range(len(self._data)))
        raise AttributeError(f"Attribute {item} not defined on class {self.__class__.__name__}")

    def __getitem__(self, index) -> Tick | Self:
        """Lấy phần tử của `Ticks` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if isinstance(index, slice):
            cls = self.__class__
            data = self._data.iloc[index]
            return cls(data=data)

        if isinstance(index, str):
            if index == "index":
                return self._data.index
            if index == "Index":
                return Series(range(len(self._data)))
            return self._data[index]

        if isinstance(index, int):
            tick = self._data.iloc[index]
            Index = index if index >= 0 else len(self) + index
            _index = self._data.index[index]
            return Tick(**tick, Index=Index, index=_index)

        raise TypeError(f"Expected int, slice or str got {type(index)}")

    def __setitem__(self, index: str, value: Series):
        """Gán phần tử của `Ticks` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if isinstance(value, Series):
            self._data[index] = value
            return
        raise TypeError(f"Expected Series got {type(value)}")

    def __reversed__(self):
        """Duyệt `Ticks` theo thứ tự đảo ngược; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        for index, row in enumerate(iter(self._data[::-1].iloc)):
            row = row.to_dict()
            index = len(self._data) - index - 1
            row["Index"] = index
            row["index"] = self._data.index[index]
            yield Tick(**row)

    def __iter__(self):
        """Duyệt các phần tử của `Ticks`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        for index, row in enumerate(iter(self._data.iloc)):
            row = row.to_dict()
            row["Index"] = index
            row["index"] = self._data.index[index]
            yield Tick(**row)

    @property
    def ta(self):
        """Cung cấp bộ chỉ báo phân tích kỹ thuật cho dữ liệu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._data.ta

    @property
    def ta_lib(self):
        """Cung cấp giao diện TA-Lib cho dữ liệu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return ta

    @property
    def data(self) -> DataFrame:
        """Đọc hoặc cập nhật dữ liệu mà `Ticks` đang quản lý; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._data

    def rename(self, inplace=True, **kwargs) -> Self | None:
        """Đổi tên các cột dữ liệu; trao đổi dữ liệu với pandas."""
        res = self._data.rename(columns=kwargs, inplace=inplace)
        return res if inplace else self.__class__(data=res)

    def __iadd__(self, other: Self) -> Self:
        """Ghép dữ liệu trực tiếp vào `Ticks`; trao đổi dữ liệu với pandas."""
        data_copy = self._data.copy()
        other = other._data
        for index, row in zip(other.index, iter(other.iloc)):
            data_copy.loc[index] = row
        self._data = data_copy.sort_index()
        return self

    def __add__(self, other: Self) -> Self:
        """Ghép `Ticks` với dữ liệu khác và trả về đối tượng mới; trao đổi dữ liệu với pandas."""
        data = self._data.copy()
        for index, row in zip(other._data.index, iter(other._data.iloc)):
            data.loc[index] = row
        return self.__class__(data=data.sort_index())

    def add(self, obj: DataFrame | Series | Tick) -> Self:
        """Thêm dữ liệu vào `Ticks`; trao đổi dữ liệu với pandas."""
        if isinstance(obj, Series):
            self._data.loc[obj.time_msc] = obj
            self._data = self._data.sort_index()
            return self
        elif isinstance(obj, DataFrame):
            data = self._data.copy()
            for index, row in zip(obj.index, iter(obj.iloc)):
                index = index
                data.loc[index] = row
            self._data = data.sort_index()
            return self
        elif isinstance(obj, Tick):
            self._data.loc[obj.index] = obj.to_series()
            self._data = self._data.sort_index()
            return self
        else:
            raise TypeError("Expected Series, DataFrame or Tick, got {}".format(type(obj)))
