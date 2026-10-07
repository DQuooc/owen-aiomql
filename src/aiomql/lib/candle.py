"""Biểu diễn và xử lý dữ liệu nến giá mở, cao, thấp và đóng."""

from datetime import datetime
from typing import Type, Self, Iterable, Protocol, runtime_checkable, Optional
from logging import getLogger

import pandas as pd
import mplfinance as mpf
from pandas import DataFrame, Series, DatetimeIndex, Timestamp

from ..ta_libs import pandas_ta_classic as ta
from ..core.constants import TimeFrame
from ..core.config import Config

logger = getLogger(__name__)


@runtime_checkable
class CandleProtocol(Protocol):
    """Quy định giao diện tối thiểu mà một lớp nến cần cung cấp."""

    open: float
    high: float
    low: float
    close: float

    def __init__(self, **kwargs) -> None:
        """Khởi tạo `CandleProtocol`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        ...


class CandleBase:
    """Cung cấp các phép phân tích chung cho dữ liệu nến."""
    open: float
    high: float
    low: float
    close: float
    time: Optional[float] = None
    index: Optional[Timestamp] = None
    Index: Optional[int] = None

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return (
            "%(class)s(open=%(open)s, high=%(high)s, low=%(low)s, close=%(close)s)"
            % {
                "class": self.__class__.__name__,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
            }
        )

    @staticmethod
    def _comparison_key(candle) -> tuple[float, float]:
        """Tạo khóa chuẩn hóa để so sánh hai nến; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        # Hỗ trợ truy cập bằng thuộc tính và bằng khóa như từ điển
        try:
            open_ = candle.open
            high = candle.high
            low = candle.low
            close = candle.close
        except AttributeError:
            open_ = candle['open']
            high = candle['high']
            low = candle['low']
            close = candle['close']
        return (abs(close - open_), high - low)

    def __eq__(self, other: "CandleProtocol") -> bool:
        """So sánh `CandleBase` bằng một đối tượng khác; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) == self._comparison_key(other)

    def __ne__(self, other: "CandleProtocol") -> bool:
        """So sánh `CandleBase` khác một đối tượng khác; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) != self._comparison_key(other)

    def __lt__(self, other: "CandleProtocol") -> bool:
        """So sánh thứ tự nhỏ hơn của `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) < self._comparison_key(other)

    def __le__(self, other: "CandleProtocol") -> bool:
        """So sánh thứ tự nhỏ hơn hoặc bằng của `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) <= self._comparison_key(other)

    def __gt__(self, other: "CandleProtocol") -> bool:
        """So sánh thứ tự lớn hơn của `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) > self._comparison_key(other)

    def __ge__(self, other: "CandleProtocol") -> bool:
        """So sánh thứ tự lớn hơn hoặc bằng của `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._comparison_key(self) >= self._comparison_key(other)

    def __hash__(self) -> int:
        """Tạo giá trị băm cho `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return hash((self.open, self.high, self.low, self.close))

    def __getitem__(self, item: str):
        """Lấy phần tử của `CandleBase` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__[item]

    def __setitem__(self, key: str, value) -> None:
        """Gán phần tử của `CandleBase` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        self.__dict__[key] = value

    def __iter__(self):
        """Duyệt các phần tử của `CandleBase`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return iter(self.__dict__.items())

    def keys(self):
        """Lấy các khóa đang được lưu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__.keys()

    def values(self):
        """Lấy các giá trị đang được lưu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.__dict__.values()

    def set_attributes(self, **kwargs) -> None:
        """Thiết lập thuộc tính; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        [setattr(self, i, j) for i, j in kwargs.items()]

    def dict(self, *, exclude: set = None, include: set = None) -> dict:
        """Chuyển dữ liệu của đối tượng thành từ điển; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        exclude = exclude or set()
        include = include or set()
        keys = include or set(self.__dict__.keys()).difference(exclude)
        return {k: v for k, v in self if k in keys}

    def to_series(self) -> Series:
        """Chuyển dữ liệu thành pandas Series; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return Series(self.dict(exclude={"Index", "index"}))

    def is_bullish(self) -> bool:
        """Kiểm tra nến có phải nến tăng hay không; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.close >= self.open

    def is_bearish(self) -> bool:
        """Kiểm tra nến có phải nến giảm hay không; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.close < self.open

    @property
    def upper_wick(self) -> float:
        """Tính độ dài râu nến trên; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.high - max(self.open, self.close)

    @property
    def lower_wick(self) -> float:
        """Tính độ dài râu nến dưới; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return min(self.open, self.close) - self.low

    @property
    def candle_range(self) -> float:
        """Tính toàn bộ biên độ của nến; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.high - self.low

    @property
    def candle_body(self) -> float:
        """Tính độ dài thân nến; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return abs(self.close - self.open)

    @property
    def upper_wick_percentage(self) -> float:
        """Tính tỷ lệ phần trăm râu nến trên; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.upper_wick / self.candle_range * 100

    @property
    def lower_wick_percentage(self) -> float:
        """Tính tỷ lệ phần trăm râu nến dưới; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.lower_wick / self.candle_range * 100

    @property
    def candle_body_percentage(self) -> float:
        """Tính tỷ lệ phần trăm thân nến; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self.candle_body / self.candle_range * 100


class Candle(CandleBase):
    """Biểu diễn một nến giá của MetaTrader5."""
    time: float
    open: float
    high: float
    low: float
    close: float
    volume: float
    real_volume: float
    spread: float
    tick_volume: float
    index: Timestamp
    Index: int

    def __init__(self, **kwargs):
        """Khởi tạo `Candle`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        kwargs = {k.lower() if k != "Index" else k: v for k, v in kwargs.items() }
        if not all(i in kwargs for i in ["open", "high", "low", "close"]):
            raise ValueError("Candle must be instantiated with open, high, low and close prices")
        self.time = kwargs.pop("time", Timestamp.now().timestamp())
        self.Index = kwargs.pop("Index", 0)
        self.index = kwargs.pop("index", Timestamp(self.time, unit="s", tz=datetime.now().astimezone().tzinfo))
        self.real_volume = kwargs.pop("real_volume", 0)
        self.spread = kwargs.pop("spread", 0)
        self.tick_volume = kwargs.pop("tick_volume", 0)
        self.volume = kwargs.pop("volume", self.real_volume or self.tick_volume)
        self.set_attributes(**kwargs)

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Candle`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return (
            "%(class)s(Index=%(Index)s, time=%(time)s, open=%(open)s, high=%(high)s, low=%(low)s, close=%(close)s, index=%(index)s)"
            % {
                "class": self.__class__.__name__,
                "open": self.open,
                "high": self.high,
                "low": self.low,
                "close": self.close,
                "time": self.time,
                "index": self.index.isoformat(),
                "Index": self.Index,
            }
        )

    def __hash__(self):
        """Tạo giá trị băm cho `Candle`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return hash((self.time, self.open, self.high, self.low, self.close))


class Candles:
    """Chứa và duyệt tập nến theo thứ tự thời gian."""
    index: DatetimeIndex
    Index: Series
    time: Series
    open: Series
    high: Series
    low: Series
    close: Series
    volume: Series
    tick_volume: Series
    real_volume: Series
    spread: Series
    Candle: Type[CandleProtocol]
    timeframe: TimeFrame
    _data: DataFrame

    def __init__(self, *, data: DataFrame | Self | Iterable, flip=False, candle_class: Type[Candle] = None):
        """Khởi tạo `Candles`; phối hợp với `Config`."""
        if isinstance(data, DataFrame):
            data = data
        elif isinstance(data, type(self)):
            data = DataFrame(data.data)
        elif isinstance(data, Iterable):
            data = DataFrame(data)
        else:
            raise ValueError(f"Cannot create DataFrame from object of {type(data)}")

        self._data = data.loc[::-1] if flip else data
        if 'time' in self._data.columns:
            dtype = pd.DatetimeTZDtype(unit='s', tz=datetime.now().astimezone().tzinfo)
            self._data.index = pd.DatetimeIndex(self._data.time, dtype=dtype)

        self.Candle = candle_class or Candle
        self.config = Config()

    def __repr__(self) -> str:
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Candles`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return repr(self._data)

    def __len__(self) -> int:
        """Trả về số phần tử của `Candles`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return len(self._data.index)

    def __contains__(self, item: Candle) -> bool:
        """Kiểm tra một phần tử có thuộc `Candles` hay không; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return item.time == self[item.Index].time

    def __getitem__(self, index: slice | int | str) -> Self | Series | Candle:
        """Lấy phần tử của `Candles` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
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
            candle = self._data.iloc[index]
            Index = index if index >= 0 else len(self) + index
            _index = self._data.index[index]
            return self.Candle(**candle, Index=Index, index=_index)
        raise TypeError(f"Expected int, slice or str got {type(index)}")

    def __setitem__(self, index: str, value: Series) -> None:
        """Gán phần tử của `Candles` theo khóa hoặc chỉ số; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if isinstance(value, Series):
            self._data[index] = value
            return
        raise TypeError(f"Expected Series got {type(value)}")

    def __getattr__(self, item: str):
        """Chuyển tiếp việc đọc thuộc tính chưa có của `Candles`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        if item in self._data.columns:
            return self._data[item]

        if item == "index":
            return self._data.index

        if item == "Index":
            return Series(range(len(self._data)))
        raise AttributeError(f"Attribute {item} not defined on class {self.__class__.__name__}")

    def __reversed__(self):
        """Duyệt `Candles` theo thứ tự đảo ngược; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        for index, row in enumerate(iter(self._data[::-1].iloc)):
            row = row.to_dict()
            index = len(self._data) - index - 1
            row["Index"] = index
            row["index"] = self._data.index[index]
            yield self.Candle(**row)

    def __iter__(self):
        """Duyệt các phần tử của `Candles`; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        for index, row in enumerate(iter(self._data.iloc)):
            row = row.to_dict()
            row["Index"] = index
            row["index"] = self._data.index[index]
            yield self.Candle(**row)

    @property
    def timeframe(self) -> TimeFrame:
        """Suy ra khung thời gian của dữ liệu nến; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        tf = self.time.iloc[1] - self.time.iloc[0]
        return TimeFrame.get_timeframe(abs(tf))

    @property
    def columns(self):
        """Lấy danh sách cột dữ liệu; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._data.columns

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
        """Đọc hoặc cập nhật dữ liệu mà `Candles` đang quản lý; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        return self._data

    def rename(self, inplace: bool = True, **kwargs) -> Self:
        """Đổi tên các cột dữ liệu; trao đổi dữ liệu với pandas."""
        res = self._data.rename(columns=kwargs, inplace=inplace)
        return self if inplace else self.__class__(data=res)

    def __iadd__(self, other: Self) -> Self:
        """Ghép dữ liệu trực tiếp vào `Candles`; trao đổi dữ liệu với pandas."""
        data_copy = self._data.copy()
        other = other._data
        for index, row in zip(other.index, iter(other.iloc)):
            data_copy.loc[index] = row
        self._data = data_copy.sort_index()
        return self

    def __add__(self, other: Self) -> Self:
        """Ghép `Candles` với dữ liệu khác và trả về đối tượng mới; trao đổi dữ liệu với pandas."""
        data = self._data.copy()
        for index, row in zip(other._data.index, iter(other._data.iloc)):
            data.loc[index] = row
        return self.__class__(data=data.sort_index())

    def add(self, obj: DataFrame | Series | Candle) -> Self:
        """Thêm dữ liệu vào `Candles`; trao đổi dữ liệu với pandas."""
        if isinstance(obj, Series):
            index = Timestamp(obj.time, unit="s", tz=datetime.now().astimezone().tzinfo)
            self._data.loc[index] = obj
            self._data = self._data.sort_index()
            return self
        elif isinstance(obj, DataFrame):
            data = self._data.copy()
            for index, row in zip(obj.index, iter(obj.iloc)):
                index = index if isinstance(index, Timestamp) else Timestamp(row.time, unit="s", tz=datetime.now().astimezone().tzinfo)
                data.loc[index] = row
            self._data = data.sort_index()
            return self
        elif isinstance(obj, Candle):
            self._data.loc[obj.index] = obj.to_series()
            self._data = self._data.sort_index()
            return self
        else:
            raise TypeError("Expected Series, DataFrame or Candle, got {}".format(type(obj)))

    def plot(self, subplots: dict = None, span: int = None, filename="", **kwargs):
        """Vẽ biểu đồ nến và các chỉ báo; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        type_ = kwargs.pop("type", "candle")
        subplots = subplots or []
        span = 0 if span is None else span
        data = self._data[-span:]
        if filename and not kwargs.get("savefig"):
            kwargs["savefig"] = self.config.plots_dir / filename

        mpf.plot(data, type=type_, addplot=subplots, **kwargs)

    def make_subplot(self, *, column: str | list[str], span: int = None, **kwargs) -> dict:
        """Tạo cấu hình biểu đồ con cho một hoặc nhiều cột; chỉ xử lý dữ liệu pandas trong bộ nhớ."""
        column = column if isinstance(column, list) else [column]
        span = 0 if span is None else span
        data = self._data[-span:]
        data = data[column]
        return mpf.make_addplot(data, **kwargs)
