"""Cung cấp các tiện ích dùng chung trong aiomql."""

import decimal
from typing import Callable
from functools import wraps, partial
from threading import RLock
from logging import getLogger
from ..core.exceptions import OrderSendAmbiguous

logger = getLogger(__name__)


def dict_to_string(data: dict, multi=False) -> str:
    """Chuyển từ điển thành chuỗi tham số; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    sep = "\n" if multi else ", "
    return f"{sep}".join(f"{key}: {value}" for key, value in data.items())


def backoff_decorator(func=None, *, max_retries: int = 3, retries: int = 0) -> Callable:
    """Tạo hàm trang trí tự thử lại hàm khi phát sinh lỗi; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    if func is None:
        return partial(backoff_decorator, max_retries=max_retries, retries=retries)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        """Bọc hàm gốc để áp dụng chính sách của hàm trang trí; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        nonlocal retries
        try:
            res = await func(*args, **kwargs)
            retries = 0
            return res
        except OrderSendAmbiguous:
            retries = 0
            raise
        except Exception as err:
            if max_retries == retries:
                retries = 0
                logger.error("An Error %s: occurred in %s", err, func.__name__)
                raise err
            retries += 1
            return await wrapper(*args, **kwargs)
    return wrapper


def error_handler(func=None, *, msg="", exe=Exception, response=None, log_error_msg=True):
    """Tạo hàm trang trí xử lý lỗi cho hàm bất đồng bộ; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    if func is None:
        return partial(error_handler, msg=msg, exe=exe, response=response, log_error_msg=log_error_msg)

    @wraps(func)
    async def wrapper(*args, **kwargs):
        """Bọc hàm gốc để áp dụng chính sách của hàm trang trí; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        try:
            res = await func(*args, **kwargs)
            return res
        except OrderSendAmbiguous:
            raise
        except exe as err:
            if log_error_msg:
                err_msg = msg or f"Error in {func.__name__}: {err}"
                logger.error(err_msg)
            return response

    return wrapper


def error_handler_sync(func=None, *, msg="", exe=Exception, response=None, log_error_msg=True):
    """Tạo hàm trang trí xử lý lỗi cho hàm đồng bộ; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    if func is None:
        return partial(error_handler_sync, msg=msg, exe=exe, response=response, log_error_msg=log_error_msg)

    @wraps(func)
    def wrapper(*args, **kwargs):
        """Bọc hàm gốc để áp dụng chính sách của hàm trang trí; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        try:
            res = func(*args, **kwargs)
            return res
        except OrderSendAmbiguous:
            raise
        except exe as err:
            if log_error_msg:
                logger.error(f"Error in {func.__name__}: {msg or err}")
            return response

    return wrapper


def round_down(value: int | float, base: int) -> int | float:
    """Làm tròn xuống theo bội số chỉ định; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return int(value) if value % base == 0 else int(value - (value % base))


def round_up(value: int | float, base: int) -> int:
    """Làm tròn lên theo bội số chỉ định; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return int(value) if value % base == 0 else int(value + base - (value % base))


# noinspection PyShadowingNames
def round_off(value: float, step: float, round_down: bool = False) -> float:
    """Làm tròn giá trị theo bước chỉ định; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    with decimal.localcontext() as ctx:
        ctx.rounding = decimal.ROUND_DOWN if round_down else decimal.ROUND_UP
        return float(decimal.Decimal(str(value)).quantize(decimal.Decimal(str(step))))


def async_cache(fun):
    """Tạo bộ nhớ đệm cho kết quả của hàm bất đồng bộ; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    @wraps(fun)
    async def wrapper(*args, **kwargs):
        """Bọc hàm gốc để áp dụng chính sách của hàm trang trí; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        key = (args, frozenset(kwargs.items()))
        with wrapper.lock:
            if key not in wrapper.cache:
                wrapper.cache[key] = await fun(*args, **kwargs)
            return wrapper.cache[key]

    wrapper.lock = RLock()
    wrapper.cache = {}
    return wrapper
