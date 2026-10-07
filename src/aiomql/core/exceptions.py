"""Khai báo các ngoại lệ chuyên biệt của aiomql."""

__all__ = ["LoginError", "VolumeError", "InvalidVolume", "SymbolError", "OrderError", "OrderSendAmbiguous", "StopTrading", "InvalidRequest"]

class LoginError(Exception):
    """Báo lỗi khi đăng nhập tài khoản giao dịch thất bại."""

    ...


class VolumeError(Exception):
    """Báo lỗi khi khối lượng không hợp lệ với mã giao dịch."""

    ...


class InvalidVolume(VolumeError):
    """The volume or broker volume limits are invalid; no order was sent."""

    ...


class SymbolError(Exception):
    """Báo lỗi khi mã giao dịch bị thiếu hoặc không khả dụng."""

    ...


class OrderError(Exception):
    """Báo lỗi trong quá trình xử lý lệnh giao dịch."""

    ...


class OrderSendAmbiguous(OrderError):
    """The request may have executed. Resolve its outcome before attempting another send.

    ``request`` is a snapshot of the submitted request; ``result`` preserves any
    broker response and ``error`` preserves available IPC error details.
    """

    outcome = "UNKNOWN_OUTCOME"

    def __init__(self, *, request: dict, result=None, error=None):
        self.request = dict(request)
        self.result = result
        self.error = error
        super().__init__(f"UNKNOWN_OUTCOME: order_send for {request.get('symbol', '')}; "
                         "execution is unconfirmed; do not blindly resend")


class StopTrading(Exception):
    """Báo hiệu yêu cầu dừng hoạt động giao dịch."""

    ...

class InvalidRequest(Exception):
    """Báo lỗi khi yêu cầu truy vấn thị trường không hợp lệ."""
    ...
