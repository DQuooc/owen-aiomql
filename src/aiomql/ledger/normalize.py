"""Deterministic, offline normalization of SDK historical deal snapshots."""

from collections.abc import Mapping
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from enum import IntEnum
import hashlib
import json
import math
from typing import Any
from uuid import UUID, uuid5

from .models import AccountRef, NormalizedDeal


NORMALIZER_VERSION = 1
_DEAL_ID_NAMESPACE = UUID("b1d90f1e-f01b-4f8b-b52c-b8ee3a90d991")


class DealNormalizationError(ValueError):
    """The SDK snapshot cannot be safely represented as a ledger deal."""


def _snapshot(value: Any, *, path: str = "raw_payload", active: frozenset[int] = frozenset()) -> Any:
    """Copy SDK values into a deterministic JSON-compatible snapshot."""
    if value is None or isinstance(value, (str, bool)):
        return value
    if isinstance(value, IntEnum):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise DealNormalizationError(f"{path} must be finite")
        return value
    if isinstance(value, (Mapping, list, tuple)):
        if id(value) in active:
            raise DealNormalizationError(f"{path} contains a cycle")
        active = active | {id(value)}
        if isinstance(value, Mapping):
            if any(not isinstance(key, str) for key in value):
                raise DealNormalizationError(f"{path} has a non-string key")
            return {key: _snapshot(item, path=f"{path}.{key}", active=active)
                    for key, item in value.items()}
        return [_snapshot(item, path=f"{path}[{index}]", active=active)
                for index, item in enumerate(value)]
    raise DealNormalizationError(f"{path} has unsupported type {type(value).__name__}")


def _required(raw: dict[str, Any], name: str) -> Any:
    if name not in raw:
        raise DealNormalizationError(f"missing required deal field: {name}")
    return raw[name]


def _integer(raw: dict[str, Any], name: str, *, optional: bool = False,
             minimum: int | None = None) -> int | None:
    value = raw.get(name) if optional else _required(raw, name)
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, int):
        raise DealNormalizationError(f"{name} must be an integer")
    if minimum is not None and value < minimum:
        raise DealNormalizationError(f"{name} must be >= {minimum}")
    return int(value)


def _decimal(raw: dict[str, Any], name: str, *, optional: bool = False) -> Decimal | None:
    value = raw.get(name) if optional else _required(raw, name)
    if optional and value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DealNormalizationError(f"{name} must be a number")
    try:
        result = Decimal(str(value))
    except InvalidOperation as exc:
        raise DealNormalizationError(f"{name} must be a finite number") from exc
    if not result.is_finite():
        raise DealNormalizationError(f"{name} must be finite")
    return result


def _string(raw: dict[str, Any], name: str, *, optional: bool = False) -> str | None:
    value = raw.get(name) if optional else _required(raw, name)
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise DealNormalizationError(f"{name} must be a string")
    return value


def normalize_deal(account_ref: AccountRef, raw_payload: Mapping[str, Any] | Any,
                   observed_at: datetime, ingestion_id: str) -> NormalizedDeal:
    """Normalize one SDK Deal without MT5 calls, persistence, or broker volume rules."""
    if not isinstance(account_ref, AccountRef):
        raise TypeError("account_ref must be an AccountRef with a stable mt5_account_id")
    if not isinstance(observed_at, datetime) or observed_at.tzinfo is None or observed_at.utcoffset() is None:
        raise DealNormalizationError("observed_at must be timezone-aware")
    if not isinstance(ingestion_id, str) or not ingestion_id.strip():
        raise DealNormalizationError("ingestion_id must be a non-empty string")

    source = raw_payload._asdict() if callable(getattr(raw_payload, "_asdict", None)) else raw_payload
    if not isinstance(source, Mapping):
        raise DealNormalizationError("raw_payload must be a mapping or SDK namedtuple")
    raw = _snapshot(source)
    ticket = _integer(raw, "ticket", minimum=1)
    volume = _decimal(raw, "volume")
    if volume < 0:
        raise DealNormalizationError("volume must be non-negative")
    canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)
    return NormalizedDeal(
        id=uuid5(_DEAL_ID_NAMESPACE, f"{account_ref.mt5_account_id}:{ticket}"),
        mt5_account_id=account_ref.mt5_account_id,
        deal_ticket=ticket,
        order_ticket=_integer(raw, "order", minimum=0),
        position_id=_integer(raw, "position_id", minimum=0),
        symbol=_string(raw, "symbol"),
        deal_type=_integer(raw, "type"),
        deal_entry=_integer(raw, "entry"),
        magic=_integer(raw, "magic"),
        volume=volume,
        price=_decimal(raw, "price"),
        commission=_decimal(raw, "commission"),
        swap=_decimal(raw, "swap"),
        profit=_decimal(raw, "profit"),
        broker_fee=_decimal(raw, "fee"),
        broker_time_seconds=_integer(raw, "time", minimum=0),
        executed_at_msc=_integer(raw, "time_msc", minimum=0),
        reason=_integer(raw, "reason", optional=True),
        sl=_decimal(raw, "sl", optional=True),
        tp=_decimal(raw, "tp", optional=True),
        comment=_string(raw, "comment", optional=True),
        external_id=_string(raw, "external_id", optional=True),
        raw_payload_json=canonical,
        payload_hash=hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        normalizer_version=NORMALIZER_VERSION,
        first_seen_at=observed_at.astimezone(timezone.utc),
        ingestion_id=ingestion_id,
    )
