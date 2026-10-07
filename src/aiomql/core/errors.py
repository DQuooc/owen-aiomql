"""Biểu diễn và phân loại lỗi trả về từ MetaTrader5."""


class Error:
    """Biểu diễn một lỗi được trả về từ MetaTrader5."""

    descriptions = {
        # Các lỗi thường gặp
        1: "successful",
        -1: "generic fail",
        -2: "invalid arguments/parameters",
        -3: "no memory condition",
        -4: "no history",
        -5: "invalid version",
        -6: "authorization failed",
        -7: "unsupported method",
        -8: "auto-trading disabled",
        # Các lỗi nội bộ
        -10000: "internal IPC general error",
        -10001: "internal IPC send failed",
        -10002: "internal IPC recv failed",
        -10003: "internal IPC initialization fail",
        -10004: "internal IPC no ipc",
        -10005: "internal timeout",
    }

    conn_errors = (-10000, -10001, -10002, -10003, -10004, -10005, -6)

    def __init__(self, code: int = 1, description: str = ""):
        """Khởi tạo `Error`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        self.code = code
        self.description = self.descriptions.get(code, description or "unknown error")

    def is_connection_error(self):
        """Kiểm tra lỗi có phải lỗi kết nối MetaTrader hay không; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return self.code in self.conn_errors

    def __repr__(self):
        """Tạo chuỗi biểu diễn phục vụ gỡ lỗi cho `Error`; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
        return f"{self.code}: {self.description}"

