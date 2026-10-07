"""Raw history read contracts, without importing or initializing an MT5 session."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from .models import AccountRef
from .repository import AccountIdentityError


class HistoryFetchError(RuntimeError):
    """History was unavailable or the SDK response was not a deal collection."""


def utc_range(from_time: datetime, to_time: datetime) -> tuple[datetime, datetime]:
    """Require aware datetimes; preserve supplied boundaries, including equality."""
    for value in (from_time, to_time):
        if not isinstance(value, datetime) or value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("history range requires timezone-aware datetimes")
    start, end = from_time.astimezone(timezone.utc), to_time.astimezone(timezone.utc)
    if start > end:
        raise ValueError("from_time must not be after to_time")
    return start, end


@dataclass(frozen=True, slots=True)
class SessionAccount:
    """Fields observed from account_info; broker namespace is configured separately."""

    login: int
    server: str

    def __post_init__(self) -> None:
        if isinstance(self.login, bool) or not isinstance(self.login, int) or self.login <= 0:
            raise AccountIdentityError("session login is unavailable or invalid")
        if not isinstance(self.server, str) or not self.server.strip():
            raise AccountIdentityError("session server is unavailable or invalid")


@dataclass(frozen=True, slots=True)
class DealHistoryBatch:
    """Raw SDK namedtuples/mappings, never aiomql TradeDeal wrappers.

    Empty tuples are successful reads. Record field validation and raw snapshot
    creation belong to normalize_deal, so a malformed field can be reported per
    record. A malformed collection or non-record element is a fetch failure.
    """

    deals: tuple[Any, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.deals, tuple):
            raise HistoryFetchError("history batch deals must be a tuple")
        if any(not isinstance(item, Mapping) and not callable(getattr(item, "_asdict", None))
               for item in self.deals):
            raise HistoryFetchError("history response contains a non-record element")


class DealHistorySource(Protocol):
    broker_namespace: str

    async def current_account(self) -> SessionAccount: ...

    async def fetch(self, account_ref: AccountRef, from_time: datetime,
                    to_time: datetime) -> DealHistoryBatch: ...


class MetaTraderHistoryClient(Protocol):
    async def account_info(self) -> Any: ...

    async def history_deals_get(self, *, date_from: datetime, date_to: datetime) -> Any: ...


class MetaTraderDealHistorySource:
    """Wrap an injected async MetaTrader client, preserving raw SDK records.

    MT5 does not verify broker_namespace. The application must bind this supplied
    namespace to the correct terminal/broker configuration. Login/server checks
    are performed by DealIngestor before and after fetch. They cannot detect an
    A -> B -> A switch during fetch and do not replace session isolation.
    """

    def __init__(self, mt5: MetaTraderHistoryClient, *, broker_namespace: str):
        if not isinstance(broker_namespace, str) or not broker_namespace.strip():
            raise ValueError("broker_namespace must be a non-empty string")
        self.mt5 = mt5
        self.broker_namespace = broker_namespace

    async def current_account(self) -> SessionAccount:
        info = await self.mt5.account_info()
        if info is None:
            raise AccountIdentityError("MT5 account_info returned None")
        login = info.get("login") if isinstance(info, Mapping) else getattr(info, "login", None)
        server = info.get("server") if isinstance(info, Mapping) else getattr(info, "server", None)
        return SessionAccount(login=login, server=server)

    async def fetch(self, account_ref: AccountRef, from_time: datetime,
                    to_time: datetime) -> DealHistoryBatch:
        if self.broker_namespace != account_ref.broker_namespace:
            raise AccountIdentityError("source broker_namespace differs from expected account")
        start, end = utc_range(from_time, to_time)
        result = await self.mt5.history_deals_get(date_from=start, date_to=end)
        if not isinstance(result, (tuple, list)):
            raise HistoryFetchError("history_deals_get returned None or an invalid collection")
        return DealHistoryBatch(tuple(result))
