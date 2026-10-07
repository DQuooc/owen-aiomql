"""Cung cấp các phép tính giá dựa trên tỷ lệ phần trăm."""


def get_price_diff_pct(first: float, second: float) -> float:
    """Tính độ lệch phần trăm giữa hai mức giá; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    diff = abs(first - second)
    div = (first + second) / 2
    return (diff / div) * 100


def get_price_in_range_pct(start: float, end: float, value: float) -> float:
    """Tính vị trí phần trăm của giá trong một khoảng; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return ((value - start) / (end - start)) * 100


def get_price_at_pct(start: float, end: float, rate: float) -> float:
    """Tính mức giá tại một tỷ lệ trong khoảng; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    span = end - start
    position = start + ((rate / 100) * span)
    return position


def extend_range_by_pct(start: float, end: float, rate: float) -> float:
    """Mở rộng khoảng giá theo tỷ lệ phần trăm; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    span = end - start
    span *= (rate / 100)
    return end + span


def get_price_change_pct(start_value: float, end_value: float) -> float:
    """Tính phần trăm thay đổi giữa hai mức giá; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return ((end_value - start_value) / start_value) * 100


def increase_value_by_pct(value: float, rate: float) -> float:
    """Tăng giá trị theo tỷ lệ phần trăm; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return value * ((100 + rate) / 100)


def decrease_value_by_pct(value: float, rate: float) -> float:
    """Giảm giá trị theo tỷ lệ phần trăm; chỉ xử lý dữ liệu nội bộ, không gọi dịch vụ bên ngoài."""
    return value * ((100 - rate) / 100)
