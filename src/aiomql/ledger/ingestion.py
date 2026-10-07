"""Explicit one-shot history ingestion. No scheduling or order execution."""

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from enum import StrEnum
from uuid import UUID, uuid4

from .models import AccountRef
from .normalize import normalize_deal
from .repository import AccountIdentityError, DealRepository, IngestOutcome
from .source import DealHistoryBatch, DealHistorySource, HistoryFetchError, SessionAccount, utc_range


class IngestionStatus(StrEnum):
    SUCCESS = "SUCCESS"
    SUCCESS_EMPTY = "SUCCESS_EMPTY"
    PARTIAL = "PARTIAL"
    FAILED = "FAILED"


class IngestionStage(StrEnum):
    ACCOUNT_BEFORE_FETCH = "ACCOUNT_BEFORE_FETCH"
    FETCH = "FETCH"
    ACCOUNT_AFTER_FETCH = "ACCOUNT_AFTER_FETCH"
    NORMALIZE = "NORMALIZE"
    STORAGE = "STORAGE"


@dataclass(frozen=True, slots=True)
class IngestionError:
    stage: IngestionStage
    exception_type: str
    message: str
    record_index: int | None = None
    deal_ticket: int | None = None


@dataclass(frozen=True, slots=True)
class IngestionReport:
    """Counters for one invocation, with requested bounds canonicalized to UTC.

    retrieved counts the fetched batch, normalized counts successful conversions,
    and inserted/duplicates/conflicts count completed repository calls. invalid
    counts normalization failures only. On storage failure later records remain
    unprocessed; the successful counters still describe earlier completed calls.
    """

    ingestion_id: str
    mt5_account_id: UUID
    requested_from: datetime
    requested_to: datetime
    status: IngestionStatus
    retrieved: int = 0
    normalized: int = 0
    inserted: int = 0
    duplicates: int = 0
    conflicts: int = 0
    invalid: int = 0
    errors: tuple[IngestionError, ...] = ()

    @property
    def has_errors(self) -> bool:
        return bool(self.errors)


class DealIngestor:
    """Guard a single fetch, normalize SDK records, persist and report outcomes.

    Invalid arguments raise before I/O. Fetch/account failures return FAILED
    without writes. Normalization failures continue: PARTIAL if at least one
    record was persisted/classified, FAILED if all were invalid. A storage error
    stops the batch and returns FAILED even if earlier rows committed; counters
    retain those completed outcomes. There is no whole-batch transaction/retry.
    Conflicts are preserved repository outcomes, not normalization/storage errors.
    Cancellation propagates; earlier per-record commits may already exist.

    Persistence runs synchronously through the existing repository contract,
    before returning, without TaskQueue or a background worker.
    """

    def __init__(self, source: DealHistorySource, repository: DealRepository):
        self.source = source
        self.repository = repository

    async def _guard(self, expected: AccountRef) -> None:
        if self.source.broker_namespace != expected.broker_namespace:
            raise AccountIdentityError("source broker_namespace differs from expected account")
        current = await self.source.current_account()
        if not isinstance(current, SessionAccount):
            raise AccountIdentityError("source did not return a verified session account")
        if (current.login, current.server) != (expected.login, expected.server):
            raise AccountIdentityError("session login/server differs from expected account")

    async def ingest_range(self, account_ref: AccountRef, from_time: datetime,
                           to_time: datetime, *, ingestion_id: str | None = None) -> IngestionReport:
        if not isinstance(account_ref, AccountRef):
            raise TypeError("account_ref must be an AccountRef")
        start, end = utc_range(from_time, to_time)
        if ingestion_id is None:
            ingestion_id = str(uuid4())
        if not isinstance(ingestion_id, str) or not ingestion_id.strip():
            raise ValueError("ingestion_id must be a non-empty string")
        counts = dict(retrieved=0, normalized=0, inserted=0, duplicates=0, conflicts=0, invalid=0)
        errors: list[IngestionError] = []

        def report(status: IngestionStatus) -> IngestionReport:
            return IngestionReport(ingestion_id=ingestion_id, mt5_account_id=account_ref.mt5_account_id,
                                   requested_from=start, requested_to=end, status=status,
                                   **counts, errors=tuple(errors))

        def error(stage: IngestionStage, exc: Exception, index: int | None = None,
                  ticket: int | None = None) -> None:
            errors.append(IngestionError(stage, type(exc).__name__, str(exc), index, ticket))

        stage = IngestionStage.ACCOUNT_BEFORE_FETCH
        try:
            await self._guard(account_ref)
            stage = IngestionStage.FETCH
            batch = await self.source.fetch(account_ref, start, end)
            if not isinstance(batch, DealHistoryBatch):
                raise HistoryFetchError("source did not return DealHistoryBatch")
            counts["retrieved"] = len(batch.deals)
            stage = IngestionStage.ACCOUNT_AFTER_FETCH
            await self._guard(account_ref)
        except Exception as exc:
            error(stage, exc)
            return report(IngestionStatus.FAILED)

        if not batch.deals:
            return report(IngestionStatus.SUCCESS_EMPTY)

        observed_at = datetime.now(timezone.utc)
        for index, item in enumerate(batch.deals):
            ticket = None
            try:
                # Extract all SDK fields once; normalize_deal owns the deep raw
                # snapshot and canonicalization before converting any fields.
                raw = item._asdict() if callable(getattr(item, "_asdict", None)) else item
                candidate = raw.get("ticket") if isinstance(raw, Mapping) else None
                if isinstance(candidate, int) and not isinstance(candidate, bool):
                    ticket = candidate
                deal = normalize_deal(account_ref, raw, observed_at, ingestion_id)
                counts["normalized"] += 1
            except Exception as exc:
                counts["invalid"] += 1
                error(IngestionStage.NORMALIZE, exc, index, ticket)
                continue
            try:
                result = self.repository.ingest(account_ref, deal)
                counter = {IngestOutcome.INSERTED: "inserted", IngestOutcome.DUPLICATE: "duplicates",
                           IngestOutcome.CONFLICT: "conflicts"}[result.outcome]
                counts[counter] += 1
            except Exception as exc:
                error(IngestionStage.STORAGE, exc, index, ticket)
                return report(IngestionStatus.FAILED)

        if errors:
            return report(IngestionStatus.PARTIAL if counts["normalized"] else IngestionStatus.FAILED)
        return report(IngestionStatus.SUCCESS)
