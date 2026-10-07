"""Validate order volume against broker limits without accessing MetaTrader5."""

from decimal import Decimal, InvalidOperation, ROUND_CEILING, ROUND_FLOOR, ROUND_HALF_UP
from math import isfinite
from numbers import Real

from .exceptions import InvalidVolume


def _number(value, name: str) -> Decimal:
    if isinstance(value, bool) or not isinstance(value, (Real, Decimal)):
        raise InvalidVolume(f"{name} must be numeric")
    try:
        number = Decimal(str(value))
    except InvalidOperation as exc:
        raise InvalidVolume(f"{name} must be numeric") from exc
    if not number.is_finite():
        raise InvalidVolume(f"{name} must be finite")
    return number


def numeric_volume(volume) -> float:
    """Accept a finite positive number, before examining broker limits."""
    value = _number(volume, "volume")
    if value <= 0:
        raise InvalidVolume("volume must be positive")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise InvalidVolume("volume must be a finite positive number")
    return result


def validate_volume(*, volume, minimum, maximum, step) -> float:
    """Require a broker-valid volume on the grid starting at volume_min."""
    value = _number(volume, "volume")
    low = _number(minimum, "volume_min")
    high = _number(maximum, "volume_max")
    increment = _number(step, "volume_step")
    if low <= 0 or high < low or increment <= 0:
        raise InvalidVolume("invalid broker volume limits")
    if value <= 0 or not low <= value <= high:
        raise InvalidVolume(f"volume {value} is outside [{low}, {high}]")
    units = (value - low) / increment
    nearest = units.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(units - nearest) > Decimal("1e-8"):
        raise InvalidVolume(f"volume {value} is not aligned to step {increment} from {low}")
    result = float(value)
    if not isfinite(result) or result <= 0:
        raise InvalidVolume("volume must be a finite positive number")
    return result


def round_volume(*, volume, minimum, step, round_down=False) -> float:
    """Round a calculated volume to an actual broker step, preserving a low result."""
    value = _number(volume, "volume")
    low = _number(minimum, "volume_min")
    increment = _number(step, "volume_step")
    if value <= 0 or low <= 0 or increment <= 0:
        raise InvalidVolume("volume and broker step must be positive")
    if value < low:
        return float(value)  # The send validator must reject this; do not increase risk to minimum.
    units = (value - low) / increment
    nearest = units.to_integral_value(rounding=ROUND_HALF_UP)
    if abs(units - nearest) <= Decimal("1e-8"):
        units = nearest
    rounding = ROUND_FLOOR if round_down else ROUND_CEILING
    return float(low + units.to_integral_value(rounding=rounding) * increment)
