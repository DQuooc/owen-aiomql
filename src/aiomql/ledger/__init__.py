"""Deal Ledger models, normalization, and explicit storage contracts."""

from .models import AccountRef, NormalizedDeal
from .normalize import DealNormalizationError, NORMALIZER_VERSION, normalize_deal
from .repository import AccountIdentityError, DealObservation, DealRepository, IngestOutcome, IngestResult
from .sqlite import SQLiteDealRepository
from .source import DealHistoryBatch, DealHistorySource, HistoryFetchError, MetaTraderDealHistorySource, SessionAccount
from .ingestion import DealIngestor, IngestionError, IngestionReport, IngestionStage, IngestionStatus

__all__ = ["AccountRef", "NormalizedDeal", "DealNormalizationError", "NORMALIZER_VERSION", "normalize_deal",
           "AccountIdentityError", "DealObservation", "DealRepository", "IngestOutcome", "IngestResult",
           "SQLiteDealRepository", "DealHistoryBatch", "DealHistorySource", "HistoryFetchError",
           "MetaTraderDealHistorySource", "SessionAccount", "DealIngestor", "IngestionError",
           "IngestionReport", "IngestionStage", "IngestionStatus"]
