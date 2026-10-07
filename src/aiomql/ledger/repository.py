"""Storage-independent contracts for an account-scoped Deal Ledger."""

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
import json
from typing import Any, Protocol
from uuid import UUID

from .models import AccountRef, NormalizedDeal


class AccountIdentityError(ValueError):
    """A supplied account identity conflicts with the persisted account mapping."""


class IngestOutcome(StrEnum):
    INSERTED = "INSERTED"
    DUPLICATE = "DUPLICATE"
    CONFLICT = "CONFLICT"


@dataclass(frozen=True, slots=True)
class IngestResult:
    outcome: IngestOutcome
    deal_id: UUID
    observation_added: bool = False


@dataclass(frozen=True, slots=True)
class DealObservation:
    id: UUID
    deal_id: UUID
    payload_hash: str
    raw_payload_json: str
    observed_at: datetime
    ingestion_id: str
    normalizer_version: int

    @property
    def raw_payload(self) -> dict[str, Any]:
        return json.loads(self.raw_payload_json)


class DealRepository(Protocol):
    """A storage boundary; every Deal read and write is scoped to an account."""

    def register_account(self, account: AccountRef) -> AccountRef: ...

    def resolve_account(self, *, broker_namespace: str, server: str, login: int) -> AccountRef | None: ...

    def ingest(self, account: AccountRef, deal: NormalizedDeal) -> IngestResult: ...

    def get(self, mt5_account_id: UUID, deal_ticket: int) -> NormalizedDeal | None: ...

    def list_by_order(self, mt5_account_id: UUID, order_ticket: int) -> tuple[NormalizedDeal, ...]: ...

    def list_by_position(self, mt5_account_id: UUID, position_id: int) -> tuple[NormalizedDeal, ...]: ...

    def list_observations(self, mt5_account_id: UUID, deal_ticket: int) -> tuple[DealObservation, ...]: ...

    def close(self) -> None: ...
