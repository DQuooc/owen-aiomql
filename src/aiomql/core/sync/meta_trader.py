from datetime import datetime
from logging import getLogger
from typing import Literal, Self
from pathlib import Path

import numpy as np
from MetaTrader5 import (
    BookInfo,
    SymbolInfo,
    AccountInfo,
    Tick,
    TerminalInfo,
    TradeOrder,
    TradeDeal,
    TradePosition,
    OrderSendResult,
    OrderCheckResult,
)

from ..constants import OrderType, CopyTicks, TradeAction, TradeRetcode

from .._core import MetaCore
from ..errors import Error
from ..exceptions import OrderError, OrderSendAmbiguous
from ..exceptions import InvalidVolume
from ..volume import numeric_volume, validate_volume
from ..config import Config

logger = getLogger()


class MetaTrader(MetaCore):
    def __new__(cls, *args, **kwargs):
        """Tạo hoặc lấy thể hiện dùng chung của `MetaTrader`; kết nối trực tiếp với giao diện MetaTrader5."""
        if not hasattr(cls, "config"):
            cls.config = Config()
        return super().__new__(cls)

    def __init__(self):
        """Khởi tạo `MetaTrader`; kết nối trực tiếp với giao diện MetaTrader5."""
        self.error: Error = Error(code=1)

    def __enter__(self) -> Self:
        """Mở ngữ cảnh đồng bộ của `MetaTrader`; kết nối trực tiếp với giao diện MetaTrader5."""
        self.initialize()
        self.login()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Đóng ngữ cảnh đồng bộ của `MetaTrader`; kết nối trực tiếp với giao diện MetaTrader5."""
        self.shutdown()

    def _handler(self, api: dict, retries=3, *, retry_safe=True):
        """Retry connection failures only for calls declared safe to repeat.

        Non-idempotent callers such as order_send must pass retry_safe=False.
        """
        func = api["func"]
        args = api.get("args", ())
        kwargs = api.get("kwargs", {})
        error_msg = api.get("error_msg", f"An error occurred in {func.__name__} of {self.__class__.__name__}")
        res = func(*args, **kwargs)

        if res is not None or not retry_safe:
            return res

        err = self.last_error()
        self.error = Error(*err)

        if self.error.is_connection_error() and retries > 0:
            self.initialize()
            self.login()
            return self._handler(api, retries=retries - 1, retry_safe=retry_safe)
        else:
            logger.warning(f"{error_msg}:{self.error.description}")
        return res

    def login(self, *, login: int = 0, password: str = "", server: str = "", timeout: int = 60000) -> bool:
        """Đăng nhập tài khoản giao dịch; gọi trực tiếp giao diện `MetaTrader5.login`."""
        acc_details = self.config.account_info
        login = login or acc_details.get("login", 0)
        password = password or acc_details.get("password", "")
        server = server or acc_details.get("server", "")
        return self._login(login, password=password, server=server, timeout=timeout)

    def initialize(self, path: str = None, login: int = 0, password: str = "", server: str = "",
                        timeout: int | None = None, portable=False) -> bool:
        """Khởi tạo dữ liệu và tài nguyên của `MetaTrader`; gọi trực tiếp giao diện `MetaTrader5.initialize`, `MetaTrader5.last_error`."""
        path = self.config.path if path is None else path
        path = "" if Path(path).exists() is False else path
        args = (str(path),) if path else ()
        acc = self.config.account_info
        kwargs = {key: value for key, value in (("login", login or acc.get("login")),
                                                ("password", password or acc.get("password")),
                                                ("server", server or acc.get("server")), ("timeout", timeout or 45000),
                                                ("portable", portable)) if key is not None}
        res = self._initialize(*args, **kwargs)
        if not res:
            err = self._last_error()
            self.error = Error(*err)
        return res

    def shutdown(self) -> None:
        """Ngắt kết nối với phần mềm đầu cuối MetaTrader; gọi trực tiếp giao diện `MetaTrader5.shutdown`."""
        self._shutdown()

    def last_error(self) -> tuple[int, str]:
        """Lấy lỗi gần nhất từ MetaTrader; gọi trực tiếp giao diện `MetaTrader5.last_error`."""
        try:
            return self._last_error()
        except Exception as err:
            logger.warning("%s: Error in obtaining last error.", err)
            return -1, str(err)

    def version(self) -> tuple[int, int, str] | None:
        """Lấy phiên bản MetaTrader đang kết nối; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._version, "error_msg": "Error in obtaining version."}
        return self._handler(api)

    def account_info(self) -> AccountInfo | None:
        """Lấy thông tin tài khoản giao dịch; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._account_info, "error_msg": "Error in obtaining account information"}
        return self._handler(api)

    def terminal_info(self) -> TerminalInfo | None:
        """Lấy thông tin phần mềm đầu cuối MetaTrader; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._terminal_info, "error_msg": "Error in obtaining terminal information"}
        return self._handler(api)

    def symbols_total(self) -> int:
        """Lấy tổng số mã giao dịch từ MetaTrader; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._symbols_total, "error_msg": "Error in obtaining total symbols."}
        return self._handler(api)

    def symbols_get(self, group: str = "") -> tuple[SymbolInfo] | None:
        """Lấy danh sách mã giao dịch từ MetaTrader; kết nối trực tiếp với giao diện MetaTrader5."""
        kwargs = {"group": group} if group else {}
        api = {"func": self._symbols_get, "kwargs": kwargs, "error_msg": "Error in obtaining symbols."}
        return self._handler(api)

    def symbol_info(self, symbol: str) -> SymbolInfo | None:
        """Lấy thông tin một mã giao dịch; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._symbol_info,
            "args": (symbol,),
            "error_msg": f"Error in obtaining information for {symbol}",
        }
        return self._handler(api)

    def symbol_info_tick(self, symbol: str) -> Tick | None:
        """Lấy giá tick mới nhất của mã giao dịch; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._symbol_info_tick, "args": (symbol,), "error_msg": f"Error in obtaining tick for {symbol}"}
        return self._handler(api)

    def symbol_select(self, symbol: str, enable: bool) -> bool:
        """Bật hoặc tắt mã giao dịch trong bảng Theo dõi thị trường; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._symbol_select, "args": (symbol, enable), "error_msg": f"Error in selecting {symbol}"}
        return self._handler(api)

    def market_book_add(self, symbol: str) -> bool:
        """Đăng ký nhận dữ liệu sổ lệnh thị trường; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._market_book_add,
            "args": (symbol,),
            "error_msg": f"Error in adding {symbol} to market book",
        }
        return self._handler(api)

    def market_book_get(self, symbol: str) -> tuple[BookInfo] | None:
        """Lấy dữ liệu sổ lệnh thị trường; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._market_book_get,
            "args": (symbol,),
            "error_msg": f"Error in obtaining market depth for {symbol}",
        }
        return self._handler(api)

    def market_book_release(self, symbol: str) -> bool:
        """Hủy đăng ký dữ liệu sổ lệnh thị trường; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._market_book_release,
            "args": (symbol,),
            "error_msg": f"Error in releasing market depth for {symbol}",
        }
        return self._handler(api)

    def copy_rates_from(
        self, symbol: str, timeframe: int, date_from: datetime | float, count: int
    ) -> np.ndarray | None:
        """Lấy dữ liệu nến từ một thời điểm; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._copy_rates_from,
            "args": (symbol, timeframe, date_from, count),
            "error_msg": f"Error in obtaining rates for {symbol}",
        }
        return self._handler(api)

    def copy_rates_from_pos(self, symbol: str, timeframe: int, start_pos: int, count: int) -> np.ndarray | None:
        """Lấy dữ liệu nến từ vị trí chỉ định; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._copy_rates_from_pos,
            "args": (symbol, timeframe, start_pos, count),
            "error_msg": f"Error in obtaining rates for {symbol}",
        }
        return self._handler(api)

    def copy_rates_range(
        self, symbol: str, timeframe: int, date_from: datetime | float, date_to: datetime | float
    ) -> np.ndarray | None:
        """Lấy dữ liệu nến trong một khoảng thời gian; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._copy_rates_range,
            "args": (symbol, timeframe, date_from, date_to),
            "error_msg": f"Error in obtaining rates for {symbol}",
        }
        return self._handler(api)

    def copy_ticks_from(
        self, symbol: str, date_from: datetime | float, count: int, flags: CopyTicks
    ) -> np.ndarray | None:
        """Lấy dữ liệu tick từ một thời điểm; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._copy_ticks_from,
            "args": (symbol, date_from, count, flags),
            "error_msg": f"Error in obtaining ticks for {symbol}",
        }
        return self._handler(api)

    def copy_ticks_range(
        self, symbol: str, date_from: datetime | float, date_to: datetime | float, flags: CopyTicks
    ) -> np.ndarray | None:
        """Lấy dữ liệu tick trong một khoảng thời gian; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._copy_ticks_range,
            "args": (symbol, date_from, date_to, flags),
            "error_msg": f"Error in obtaining ticks for {symbol}",
        }
        return self._handler(api)

    def orders_total(self) -> int:
        """Lấy tổng số lệnh chờ đang hoạt động; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._orders_total, "error_msg": "Error in obtaining total orders."}
        return self._handler(api)

    def orders_get(self, group: str = "", ticket: int = 0, symbol: str = "") -> tuple[TradeOrder] | None:
        """Lấy các lệnh chờ đang hoạt động; kết nối trực tiếp với giao diện MetaTrader5."""
        kwargs = {key: value for key, value in (("group", group), ("ticket", ticket), ("symbol", symbol)) if value}
        api = {"func": self._orders_get, "kwargs": kwargs, "error_msg": "Error in obtaining orders."}
        return self._handler(api)

    def order_calc_margin(
        self, action: Literal[OrderType.BUY, OrderType.SELL], symbol: str, volume: float, price: float
    ) -> float | None:
        """Tính mức ký quỹ; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._order_calc_margin,
            "args": (action, symbol, volume, price),
            "error_msg": "Error in calculating margin.",
        }
        return self._handler(api)

    def order_calc_profit(
        self,
        action: Literal[OrderType.BUY, OrderType.SELL],
        symbol: str,
        volume: float,
        price_open: float,
        price_close: float,
    ) -> float | None:
        """Tính mức lợi nhuận; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._order_calc_profit,
            "args": (action, symbol, volume, price_open, price_close),
            "error_msg": "Error in calculating profit.",
        }
        return self._handler(api)

    def order_check(self, request: dict) -> OrderCheckResult:
        """Kiểm tra yêu cầu lệnh trước khi gửi; kết nối trực tiếp với giao diện MetaTrader5."""
        comment = request.get("comment")
        if comment is not None and len(comment) > 25:
            request["comment"] = comment[:25]
            logger.warning("order comment length exceeds 25 characters.")
        api = {"func": self._order_check, "args": (request,), "error_msg": "Error in checking order."}
        return self._handler(api)

    def order_send(self, request: dict) -> OrderSendResult:
        """Check the final normalized snapshot, then send once.

        Earlier caller checks do not authorize this send. Check failures occur
        before submission; only unconfirmed sends raise OrderSendAmbiguous.
        """
        request = dict(request)
        if request.get("action") in (TradeAction.DEAL, TradeAction.PENDING) or "volume" in request:
            volume = numeric_volume(request.get("volume"))
            symbol = request.get("symbol")
            if not isinstance(symbol, str) or not symbol:
                raise InvalidVolume("order symbol is required for volume validation")
            info = self.symbol_info(symbol)
            if info is None:
                raise InvalidVolume(f"broker volume limits unavailable for {symbol}")
            request["volume"] = validate_volume(volume=volume, minimum=info.volume_min,
                                                 maximum=info.volume_max, step=info.volume_step)
        comment = request.get("comment")
        if comment is not None and len(comment) > 25:
            request["comment"] = comment[:25]
            logger.warning("order comment length exceeds 25 characters.")
        checked_request = dict(request)
        check = self._handler(
            {"func": self._order_check, "args": (checked_request,), "error_msg": "Error in checking order."},
            retry_safe=False,
        )
        retcode = getattr(check, "retcode", None)
        if isinstance(retcode, bool) or not isinstance(retcode, int) or retcode != 0:
            raise OrderError(f"Order check failed or rejected for {request.get('symbol', '')}")
        if checked_request != request:
            raise OrderError("Order request changed during check; refusing to send")
        api = {"func": self._order_send, "args": (request,), "error_msg": "Error in sending order."}
        try:
            res = self._handler(api, retry_safe=False)
            if res is None:
                self.error = Error(*self.last_error())
        except Exception as exc:
            raise OrderSendAmbiguous(request=request) from exc
        if res is None or getattr(res, "retcode", None) in (None, TradeRetcode.TIMEOUT, TradeRetcode.CONNECTION):
            raise OrderSendAmbiguous(request=request, result=res, error=self.error if res is None else None)
        return res

    def positions_total(self) -> int:
        """Lấy tổng số vị thế đang mở; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {"func": self._positions_total, "error_msg": "Error in obtaining total positions."}
        return self._handler(api)

    def positions_get(self, group: str = "", ticket: int = None, symbol: str = "") -> tuple[TradePosition] | None:
        """Lấy các vị thế đang mở; kết nối trực tiếp với giao diện MetaTrader5."""
        kwargs = {key: value for key, value in (("group", group), ("ticket", ticket), ("symbol", symbol)) if value}
        api = {"func": self._positions_get, "kwargs": kwargs, "error_msg": "Error in obtaining open positions."}
        return self._handler(api)

    def history_orders_total(self, date_from: datetime | float, date_to: datetime | float) -> int:
        """Lấy tổng số lệnh trong lịch sử giao dịch; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._history_orders_total,
            "args": (date_from, date_to),
            "error_msg": "Error in obtaining total history orders.",
        }
        return self._handler(api)

    def history_orders_get(
        self,
        date_from: datetime | float = None,
        date_to: datetime | float = None,
        group: str = "",
        ticket: int = None,
        position: int = None,
    ) -> tuple[TradeOrder] | None:
        """Lấy các lệnh trong lịch sử giao dịch; kết nối trực tiếp với giao diện MetaTrader5."""
        kwargs = {key: value for key, value in (("group", group), ("ticket", ticket), ("position", position)) if value}
        args = tuple(arg for arg in (date_from, date_to) if arg)
        api = {
            "func": self._history_orders_get,
            "args": args,
            "kwargs": kwargs,
            "error_msg": "Error in obtaining history orders",
        }
        return self._handler(api)

    def history_deals_total(self, date_from: datetime | float, date_to: datetime | float) -> int:
        """Lấy tổng số giao dịch đã khớp trong lịch sử; kết nối trực tiếp với giao diện MetaTrader5."""
        api = {
            "func": self._history_deals_total,
            "args": (date_from, date_to),
            "error_msg": "Error in obtaining total history deals",
        }
        return self._handler(api)

    def history_deals_get(
        self,
        date_from: datetime | float = None,
        date_to: datetime | float = None,
        group: str = "",
        ticket: int = None,
        position: int = None,
    ) -> tuple[TradeDeal] | None:
        """Lấy các giao dịch đã khớp trong lịch sử; kết nối trực tiếp với giao diện MetaTrader5."""
        kwargs = {key: value for key, value in (("group", group), ("ticket", ticket), ("position", position)) if value}
        args = tuple(arg for arg in (date_from, date_to) if arg)
        api = {
            "func": self._history_deals_get,
            "args": args,
            "kwargs": kwargs,
            "error_msg": "Error in obtaining history deals",
        }
        return self._handler(api)
