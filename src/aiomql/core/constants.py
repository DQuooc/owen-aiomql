"""Khai báo các hằng số MetaTrader5 dưới dạng kiểu liệt kê số nguyên."""

from enum import IntEnum, IntFlag

import MetaTrader5 as mt5


class Repr:
    """Bổ sung cách hiển thị chuỗi cho các giá trị liệt kê."""

    __enum_name__: str = ""
    name: str

    def __str__(self):
        """Tạo chuỗi hiển thị dễ đọc cho `Repr`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return f"{self.__enum_name__}_{self.name}"


class TradeAction(Repr, IntEnum):
    """Liệt kê các hành động có thể thực hiện trong yêu cầu giao dịch."""
    __enum_name__ = "TRADE_ACTION"
    DEAL = mt5.TRADE_ACTION_DEAL
    PENDING = mt5.TRADE_ACTION_PENDING
    SLTP = mt5.TRADE_ACTION_SLTP
    MODIFY = mt5.TRADE_ACTION_MODIFY
    REMOVE = mt5.TRADE_ACTION_REMOVE
    CLOSE_BY = mt5.TRADE_ACTION_CLOSE_BY


class OrderFilling(Repr, IntEnum):
    """Liệt kê các chính sách khớp lệnh."""

    __enum_name__ = "ORDER_FILLING"
    FOK = mt5.ORDER_FILLING_FOK
    IOC = mt5.ORDER_FILLING_IOC
    RETURN = mt5.ORDER_FILLING_RETURN


class OrderTime(Repr, IntEnum):
    """Liệt kê các chính sách thời hạn của lệnh."""

    __enum_name__ = "ORDER_TIME"
    GTC = mt5.ORDER_TIME_GTC
    DAY = mt5.ORDER_TIME_DAY
    SPECIFIED = mt5.ORDER_TIME_SPECIFIED
    SPECIFIED_DAY = mt5.ORDER_TIME_SPECIFIED_DAY


class OrderType(Repr, IntEnum):
    """Liệt kê các loại lệnh giao dịch."""
    __enum_name__ = "ORDER_TYPE"
    BUY = mt5.ORDER_TYPE_BUY
    SELL = mt5.ORDER_TYPE_SELL
    BUY_LIMIT = mt5.ORDER_TYPE_BUY_LIMIT
    SELL_LIMIT = mt5.ORDER_TYPE_SELL_LIMIT
    BUY_STOP = mt5.ORDER_TYPE_BUY_STOP
    SELL_STOP = mt5.ORDER_TYPE_SELL_STOP
    BUY_STOP_LIMIT = mt5.ORDER_TYPE_BUY_STOP_LIMIT
    SELL_STOP_LIMIT = mt5.ORDER_TYPE_SELL_STOP_LIMIT
    CLOSE_BY = mt5.ORDER_TYPE_CLOSE_BY

    @property
    def opposite(self):
        """Trả về loại lệnh đối nghịch với loại hiện tại; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        _type = {0: 1, 1: 0, 2: 3, 3: 2, 4: 5, 5: 4, 6: 7, 7: 6, 8: 8}[self]
        return OrderType(_type)

    @property
    def is_long(self):
        """Kiểm tra loại lệnh có phải lệnh mua hay không; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return self in [0, 2, 4, 6]

    @property
    def is_short(self):
        """Kiểm tra loại lệnh có phải lệnh bán hay không; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return self in [1, 3, 5, 7]

class BookType(Repr, IntEnum):
    """Liệt kê các loại bản ghi trong sổ lệnh thị trường."""

    __enum_name__ = "BOOK_TYPE"
    SELL = mt5.BOOK_TYPE_SELL
    BUY = mt5.BOOK_TYPE_BUY
    SELL_MARKET = mt5.BOOK_TYPE_SELL_MARKET
    BUY_MARKET = mt5.BOOK_TYPE_BUY_MARKET


class TimeFrame(Repr, IntEnum):
    """Liệt kê các khung thời gian của dữ liệu giá."""

    __enum_name__ = "TIMEFRAME"
    M1 = mt5.TIMEFRAME_M1
    M2 = mt5.TIMEFRAME_M2
    M3 = mt5.TIMEFRAME_M3
    M4 = mt5.TIMEFRAME_M4
    M5 = mt5.TIMEFRAME_M5
    M6 = mt5.TIMEFRAME_M6
    M10 = mt5.TIMEFRAME_M10
    M15 = mt5.TIMEFRAME_M15
    M20 = mt5.TIMEFRAME_M20
    M30 = mt5.TIMEFRAME_M30
    H1 = mt5.TIMEFRAME_H1
    H2 = mt5.TIMEFRAME_H2
    H3 = mt5.TIMEFRAME_H3
    H4 = mt5.TIMEFRAME_H4
    H6 = mt5.TIMEFRAME_H6
    H8 = mt5.TIMEFRAME_H8
    H12 = mt5.TIMEFRAME_H12
    D1 = mt5.TIMEFRAME_D1
    W1 = mt5.TIMEFRAME_W1
    MN1 = mt5.TIMEFRAME_MN1

    @property
    def seconds(self):
        """Đổi khung thời gian sang số giây; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        seconds = {
            1: 60,
            2: 120,
            3: 180,
            4: 240,
            5: 300,
            6: 360,
            10: 600,
            15: 900,
            20: 1200,
            30: 1800,
            16385: 3600,
            16386: 7200,
            16387: 10800,
            16388: 14400,
            16390: 21600,
            16392: 28800,
            16396: 43200,
            16408: 86400,
            32769: 604800,
            49153: 2592000,
        }
        return seconds[self]

    @classmethod
    def get_timeframe(cls, time: int) -> "TimeFrame":
        """Lấy khung thời gian; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        time_frames = {
            60: 1,
            120: 2,
            180: 3,
            240: 4,
            300: 5,
            360: 6,
            600: 10,
            900: 15,
            1200: 20,
            1800: 30,
            3600: 16385,
            7200: 16386,
            10800: 16387,
            14400: 16388,
            21600: 16390,
            28800: 16392,
            43200: 16396,
            86400: 16408,
            604800: 32769,
            2592000: 49153,
        }
        return TimeFrame(time_frames[time])

    @classmethod
    @property
    def all(cls) -> tuple["TimeFrame", ...]:
        """Lấy toàn bộ bản ghi phù hợp; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return (
            TimeFrame.M1,
            TimeFrame.M2,
            TimeFrame.M3,
            TimeFrame.M4,
            TimeFrame.M5,
            TimeFrame.M6,
            TimeFrame.M10,
            TimeFrame.M15,
            TimeFrame.M20,
            TimeFrame.M30,
            TimeFrame.H1,
            TimeFrame.H2,
            TimeFrame.H3,
            TimeFrame.H4,
            TimeFrame.H6,
            TimeFrame.H8,
            TimeFrame.H12,
            TimeFrame.D1,
            TimeFrame.W1,
            TimeFrame.MN1,
        )


class CopyTicks(Repr, IntEnum):
    """Liệt kê các loại tick được phép truy xuất từ MetaTrader5."""

    __enum_name__ = "COPY_TICKS"
    ALL = mt5.COPY_TICKS_ALL
    INFO = mt5.COPY_TICKS_INFO
    TRADE = mt5.COPY_TICKS_TRADE


class PositionType(Repr, IntEnum):
    """Liệt kê hướng mua hoặc bán của vị thế đang mở."""

    __enum_name__ = "POSITION_TYPE"
    BUY = mt5.POSITION_TYPE_BUY
    SELL = mt5.POSITION_TYPE_SELL


class PositionReason(Repr, IntEnum):
    """Liệt kê nguyên nhân hình thành vị thế."""

    __enum_name__ = "POSITION_REASON"
    CLIENT = mt5.POSITION_REASON_CLIENT
    MOBILE = mt5.POSITION_REASON_MOBILE
    WEB = mt5.POSITION_REASON_WEB
    EXPERT = mt5.POSITION_REASON_EXPERT


class DealType(Repr, IntEnum):
    """Liệt kê các loại giao dịch đã khớp."""

    __enum_name__ = "DEAL_TYPE"
    BUY = mt5.DEAL_TYPE_BUY
    SELL = mt5.DEAL_TYPE_SELL
    BALANCE = mt5.DEAL_TYPE_BALANCE
    CREDIT = mt5.DEAL_TYPE_CREDIT
    CHARGE = mt5.DEAL_TYPE_CHARGE
    CORRECTION = mt5.DEAL_TYPE_CORRECTION
    BONUS = mt5.DEAL_TYPE_BONUS
    COMMISSION = mt5.DEAL_TYPE_COMMISSION
    COMMISSION_DAILY = mt5.DEAL_TYPE_COMMISSION_DAILY
    COMMISSION_MONTHLY = mt5.DEAL_TYPE_COMMISSION_MONTHLY
    COMMISSION_AGENT_DAILY = mt5.DEAL_TYPE_COMMISSION_AGENT_DAILY
    COMMISSION_AGENT_MONTHLY = mt5.DEAL_TYPE_COMMISSION_AGENT_MONTHLY
    INTEREST = mt5.DEAL_TYPE_INTEREST
    BUY_CANCELED = mt5.DEAL_TYPE_BUY_CANCELED
    SELL_CANCELED = mt5.DEAL_TYPE_SELL_CANCELED
    DEAL_DIVIDEND = mt5.DEAL_DIVIDEND
    DEAL_DIVIDEND_FRANKED = mt5.DEAL_DIVIDEND_FRANKED
    DEAL_TAX = mt5.DEAL_TAX

    def __str__(self):
        """Tạo chuỗi hiển thị dễ đọc cho `DealType`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        if self.name in ("DEAL_DIVIDEND", "DEAL_DIVIDEND_FRANKED", "DEAL_TAX"):
            return self.name
        return super().__str__()


class DealEntry(Repr, IntEnum):
    """Liệt kê cách giao dịch đã khớp làm thay đổi vị thế."""

    __enum_name__ = "DEAL_ENTRY"
    IN = mt5.DEAL_ENTRY_IN
    OUT = mt5.DEAL_ENTRY_OUT
    INOUT = mt5.DEAL_ENTRY_INOUT
    OUT_BY = mt5.DEAL_ENTRY_OUT_BY


class DealReason(Repr, IntEnum):
    """Liệt kê nguyên nhân thực thi giao dịch."""

    __enum_name__ = "DEAL_REASON"
    CLIENT = mt5.DEAL_REASON_CLIENT
    MOBILE = mt5.DEAL_REASON_MOBILE
    WEB = mt5.DEAL_REASON_WEB
    EXPERT = mt5.DEAL_REASON_EXPERT
    SL = mt5.DEAL_REASON_SL
    TP = mt5.DEAL_REASON_TP
    SO = mt5.DEAL_REASON_SO
    ROLLOVER = mt5.DEAL_REASON_ROLLOVER
    VMARGIN = mt5.DEAL_REASON_VMARGIN
    SPLIT = mt5.DEAL_REASON_SPLIT


class OrderReason(Repr, IntEnum):
    """Liệt kê nguyên nhân tạo lệnh."""

    __enum_name__ = "ORDER_REASON"
    CLIENT = mt5.ORDER_REASON_CLIENT
    MOBILE = mt5.ORDER_REASON_MOBILE
    WEB = mt5.ORDER_REASON_WEB
    EXPERT = mt5.ORDER_REASON_EXPERT
    SL = mt5.ORDER_REASON_SL
    TP = mt5.ORDER_REASON_TP
    SO = mt5.ORDER_REASON_SO


class SymbolChartMode(Repr, IntEnum):
    """Liệt kê loại giá được dùng để dựng biểu đồ của mã giao dịch."""

    __enum_name__ = "SYMBOL_CHART_MODE"
    BID = mt5.SYMBOL_CHART_MODE_BID
    LAST = mt5.SYMBOL_CHART_MODE_LAST


class SymbolCalcMode(Repr, IntEnum):
    """Liệt kê phương thức tính ký quỹ và lợi nhuận của mã giao dịch."""

    __enum_name__ = "SYMBOL_CALC_MODE"
    FOREX = mt5.SYMBOL_CALC_MODE_FOREX
    FOREX_NO_LEVERAGE = mt5.SYMBOL_CALC_MODE_FOREX_NO_LEVERAGE
    FUTURES = mt5.SYMBOL_CALC_MODE_FUTURES
    CFD = mt5.SYMBOL_CALC_MODE_CFD
    CFDINDEX = mt5.SYMBOL_CALC_MODE_CFDINDEX
    CFDLEVERAGE = mt5.SYMBOL_CALC_MODE_CFDLEVERAGE
    EXCH_STOCKS = mt5.SYMBOL_CALC_MODE_EXCH_STOCKS
    EXCH_FUTURES = mt5.SYMBOL_CALC_MODE_EXCH_FUTURES
    EXCH_OPTIONS = mt5.SYMBOL_CALC_MODE_EXCH_OPTIONS
    EXCH_OPTIONS_MARGIN = mt5.SYMBOL_CALC_MODE_EXCH_OPTIONS_MARGIN
    EXCH_BONDS = mt5.SYMBOL_CALC_MODE_EXCH_BONDS
    EXCH_STOCKS_MOEX = mt5.SYMBOL_CALC_MODE_EXCH_STOCKS_MOEX
    EXCH_BONDS_MOEX = mt5.SYMBOL_CALC_MODE_EXCH_BONDS_MOEX
    SERV_COLLATERAL = mt5.SYMBOL_CALC_MODE_SERV_COLLATERAL


class SymbolTradeMode(Repr, IntEnum):
    """Liệt kê các chế độ giao dịch được phép của mã giao dịch."""

    __enum_name__ = "SYMBOL_TRADE_MODE"
    DISABLED = mt5.SYMBOL_TRADE_MODE_DISABLED
    LONGONLY = mt5.SYMBOL_TRADE_MODE_LONGONLY
    SHORTONLY = mt5.SYMBOL_TRADE_MODE_SHORTONLY
    CLOSEONLY = mt5.SYMBOL_TRADE_MODE_CLOSEONLY
    FULL = mt5.SYMBOL_TRADE_MODE_FULL


class SymbolTradeExecution(Repr, IntEnum):
    """Liệt kê các chính sách thực thi lệnh của mã giao dịch."""

    __enum_name__ = "SYMBOL_TRADE_EXECUTION"
    REQUEST = mt5.SYMBOL_TRADE_EXECUTION_REQUEST
    INSTANT = mt5.SYMBOL_TRADE_EXECUTION_INSTANT
    MARKET = mt5.SYMBOL_TRADE_EXECUTION_MARKET
    EXCHANGE = mt5.SYMBOL_TRADE_EXECUTION_EXCHANGE


class SymbolSwapMode(Repr, IntEnum):
    """Liệt kê các phương thức tính phí qua đêm."""

    __enum_name__ = "SYMBOL_SWAP_MODE"
    DISABLED = mt5.SYMBOL_SWAP_MODE_DISABLED
    POINTS = mt5.SYMBOL_SWAP_MODE_POINTS
    CURRENCY_SYMBOL = mt5.SYMBOL_SWAP_MODE_CURRENCY_SYMBOL
    CURRENCY_MARGIN = mt5.SYMBOL_SWAP_MODE_CURRENCY_MARGIN
    CURRENCY_DEPOSIT = mt5.SYMBOL_SWAP_MODE_CURRENCY_DEPOSIT
    INTEREST_CURRENT = mt5.SYMBOL_SWAP_MODE_INTEREST_CURRENT
    INTEREST_OPEN = mt5.SYMBOL_SWAP_MODE_INTEREST_OPEN
    REOPEN_CURRENT = mt5.SYMBOL_SWAP_MODE_REOPEN_CURRENT
    REOPEN_BID = mt5.SYMBOL_SWAP_MODE_REOPEN_BID


class DayOfWeek(Repr, IntEnum):
    """Liệt kê các ngày trong tuần."""

    __enum__name__ = "DAY_OF_WEEK"
    SUNDAY = mt5.DAY_OF_WEEK_SUNDAY
    MONDAY = mt5.DAY_OF_WEEK_MONDAY
    TUESDAY = mt5.DAY_OF_WEEK_TUESDAY
    WEDNESDAY = mt5.DAY_OF_WEEK_WEDNESDAY
    THURSDAY = mt5.DAY_OF_WEEK_THURSDAY
    FRIDAY = mt5.DAY_OF_WEEK_FRIDAY
    SATURDAY = mt5.DAY_OF_WEEK_SATURDAY


class SymbolOrderGTCMode(Repr, IntEnum):
    """Liệt kê cách duy trì lệnh và mức dừng đến khi bị hủy."""

    __enum_name__ = "SYMBOL_ORDERS"
    GTC = mt5.SYMBOL_ORDERS_GTC
    DAILY = mt5.SYMBOL_ORDERS_DAILY
    DAILY_NO_STOPS = mt5.SYMBOL_ORDERS_DAILY_NO_STOPS


class SymbolOptionRight(Repr, IntEnum):
    """Liệt kê quyền mua hoặc quyền bán của hợp đồng quyền chọn."""

    __enum_name__ = "SYMBOL_OPTION_RIGHT"
    CALL = mt5.SYMBOL_OPTION_RIGHT_CALL
    PUT = mt5.SYMBOL_OPTION_RIGHT_PUT


class SymbolOptionMode(Repr, IntEnum):
    """Liệt kê kiểu thực hiện của hợp đồng quyền chọn."""

    __enum_name__ = "SYMBOL_OPTION_MODE"
    EUROPEAN = mt5.SYMBOL_OPTION_MODE_EUROPEAN
    AMERICAN = mt5.SYMBOL_OPTION_MODE_AMERICAN


class AccountTradeMode(Repr, IntEnum):
    """Liệt kê các loại tài khoản giao dịch."""

    __enum_name__ = "ACCOUNT_TRADE_MODE"
    DEMO = mt5.ACCOUNT_TRADE_MODE_DEMO
    CONTEST = mt5.ACCOUNT_TRADE_MODE_CONTEST
    REAL = mt5.ACCOUNT_TRADE_MODE_REAL


class TickFlag(Repr, IntFlag):
    """Liệt kê các cờ mô tả thay đổi trong dữ liệu tick."""

    __enum_name__ = "TICK_FLAG"
    BID = mt5.TICK_FLAG_BID
    ASK = mt5.TICK_FLAG_ASK
    LAST = mt5.TICK_FLAG_LAST
    VOLUME = mt5.TICK_FLAG_VOLUME
    BUY = mt5.TICK_FLAG_BUY
    SELL = mt5.TICK_FLAG_SELL


class TradeRetcode(Repr, IntEnum):
    """Liệt kê mã kết quả khi kiểm tra hoặc gửi lệnh."""

    __enum_name__ = "TRADE_RETCODE"
    REQUOTE = mt5.TRADE_RETCODE_REQUOTE
    REJECT = mt5.TRADE_RETCODE_REJECT
    CANCEL = mt5.TRADE_RETCODE_CANCEL
    PLACED = mt5.TRADE_RETCODE_PLACED
    DONE = mt5.TRADE_RETCODE_DONE
    DONE_PARTIAL = mt5.TRADE_RETCODE_DONE_PARTIAL
    ERROR = mt5.TRADE_RETCODE_ERROR
    TIMEOUT = mt5.TRADE_RETCODE_TIMEOUT
    INVALID = mt5.TRADE_RETCODE_INVALID
    INVALID_VOLUME = mt5.TRADE_RETCODE_INVALID_VOLUME
    INVALID_PRICE = mt5.TRADE_RETCODE_INVALID_PRICE
    INVALID_STOPS = mt5.TRADE_RETCODE_INVALID_STOPS
    TRADE_DISABLED = mt5.TRADE_RETCODE_TRADE_DISABLED
    MARKET_CLOSED = mt5.TRADE_RETCODE_MARKET_CLOSED
    NO_MONEY = mt5.TRADE_RETCODE_NO_MONEY
    PRICE_CHANGED = mt5.TRADE_RETCODE_PRICE_CHANGED
    PRICE_OFF = mt5.TRADE_RETCODE_PRICE_OFF
    INVALID_EXPIRATION = mt5.TRADE_RETCODE_INVALID_EXPIRATION
    ORDER_CHANGED = mt5.TRADE_RETCODE_ORDER_CHANGED
    TOO_MANY_REQUESTS = mt5.TRADE_RETCODE_TOO_MANY_REQUESTS
    NO_CHANGES = mt5.TRADE_RETCODE_NO_CHANGES
    SERVER_DISABLES_AT = mt5.TRADE_RETCODE_SERVER_DISABLES_AT
    CLIENT_DISABLES_AT = mt5.TRADE_RETCODE_CLIENT_DISABLES_AT
    LOCKED = mt5.TRADE_RETCODE_LOCKED
    FROZEN = mt5.TRADE_RETCODE_FROZEN
    INVALID_FILL = mt5.TRADE_RETCODE_INVALID_FILL
    CONNECTION = mt5.TRADE_RETCODE_CONNECTION
    ONLY_REAL = mt5.TRADE_RETCODE_ONLY_REAL
    LIMIT_ORDERS = mt5.TRADE_RETCODE_LIMIT_ORDERS
    LIMIT_VOLUME = mt5.TRADE_RETCODE_LIMIT_VOLUME
    INVALID_ORDER = mt5.TRADE_RETCODE_INVALID_ORDER
    POSITION_CLOSED = mt5.TRADE_RETCODE_POSITION_CLOSED
    INVALID_CLOSE_VOLUME = mt5.TRADE_RETCODE_INVALID_CLOSE_VOLUME
    CLOSE_ORDER_EXIST = mt5.TRADE_RETCODE_CLOSE_ORDER_EXIST
    LIMIT_POSITIONS = mt5.TRADE_RETCODE_LIMIT_POSITIONS
    REJECT_CANCEL = mt5.TRADE_RETCODE_REJECT_CANCEL
    LONG_ONLY = mt5.TRADE_RETCODE_LONG_ONLY
    SHORT_ONLY = mt5.TRADE_RETCODE_SHORT_ONLY
    CLOSE_ONLY = mt5.TRADE_RETCODE_CLOSE_ONLY
    FIFO_CLOSE = mt5.TRADE_RETCODE_FIFO_CLOSE


class AccountStopOutMode(Repr, IntEnum):
    """Liệt kê cách biểu diễn ngưỡng đóng vị thế bắt buộc."""

    __enum_name__ = "ACCOUNT_STOPOUT_MODE"
    PERCENT = mt5.ACCOUNT_STOPOUT_MODE_PERCENT
    MONEY = mt5.ACCOUNT_STOPOUT_MODE_MONEY


class AccountMarginMode(Repr, IntEnum):
    """Liệt kê chế độ tính ký quỹ của tài khoản."""

    __enum_name__ = "ACCOUNT_MARGIN_MODE"
    RETAIL_NETTING = mt5.ACCOUNT_MARGIN_MODE_RETAIL_NETTING
    EXCHANGE = mt5.ACCOUNT_MARGIN_MODE_EXCHANGE
    RETAIL_HEDGING = mt5.ACCOUNT_MARGIN_MODE_RETAIL_HEDGING
