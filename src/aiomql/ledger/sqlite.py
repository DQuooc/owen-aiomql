"""Local SQLite implementation of the account-scoped Deal Ledger."""

from contextlib import contextmanager, closing
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
from typing import Iterator
from uuid import UUID, uuid5

from .models import AccountRef, NormalizedDeal
from .repository import AccountIdentityError, DealObservation, IngestOutcome, IngestResult


_OBSERVATION_NAMESPACE = UUID("a3aa2b42-8d9d-41a5-8763-a593f60851d5")

_DEAL_COLUMNS = (
    "id", "mt5_account_id", "deal_ticket", "order_ticket", "position_id", "symbol",
    "deal_type", "deal_entry", "magic", "volume", "price", "commission", "swap",
    "profit", "broker_fee", "broker_time_seconds", "executed_at_msc", "reason",
    "sl", "tp", "comment", "external_id", "raw_payload", "payload_hash",
    "normalizer_version", "first_seen_at", "ingestion_id",
)


class SQLiteDealRepository:
    """One connection per operation; SQLite constraints arbitrate concurrent writers."""

    def __init__(self, db_path: str | Path):
        if str(db_path) == ":memory:":
            raise ValueError("Deal Ledger requires a durable SQLite file")
        self.path = Path(db_path).expanduser().resolve()
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._closed = False
        self._initialize_schema()

    def close(self) -> None:
        """Prevent further operations; connections are closed after each call."""
        self._closed = True

    def _connect(self) -> sqlite3.Connection:
        if self._closed:
            raise RuntimeError("Deal repository is closed")
        conn = sqlite3.connect(self.path, timeout=5.0, isolation_level=None)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        return conn

    @contextmanager
    def _write(self) -> Iterator[sqlite3.Connection]:
        conn = self._connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            yield conn
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
        finally:
            conn.close()

    def _initialize_schema(self) -> None:
        # executescript() commits any open transaction before running; keep
        # schema creation in the same explicit transaction as other writes.
        statements = (
            """
                CREATE TABLE IF NOT EXISTS ledger_accounts (
                    mt5_account_id TEXT PRIMARY KEY,
                    broker_namespace TEXT NOT NULL,
                    server TEXT NOT NULL,
                    login TEXT NOT NULL,
                    company_observed TEXT NOT NULL,
                    trade_mode INTEGER NOT NULL,
                    UNIQUE (broker_namespace, server, login)
                )
            """,
            """
                CREATE TABLE IF NOT EXISTS deals (
                    id TEXT PRIMARY KEY,
                    mt5_account_id TEXT NOT NULL REFERENCES ledger_accounts(mt5_account_id),
                    deal_ticket TEXT NOT NULL,
                    order_ticket TEXT NOT NULL,
                    position_id TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    deal_type INTEGER NOT NULL,
                    deal_entry INTEGER NOT NULL,
                    magic TEXT NOT NULL,
                    volume TEXT NOT NULL,
                    price TEXT NOT NULL,
                    commission TEXT NOT NULL,
                    swap TEXT NOT NULL,
                    profit TEXT NOT NULL,
                    broker_fee TEXT NOT NULL,
                    broker_time_seconds INTEGER NOT NULL,
                    executed_at_msc INTEGER NOT NULL,
                    reason INTEGER,
                    sl TEXT,
                    tp TEXT,
                    comment TEXT,
                    external_id TEXT,
                    raw_payload TEXT NOT NULL,
                    payload_hash TEXT NOT NULL,
                    normalizer_version INTEGER NOT NULL,
                    first_seen_at TEXT NOT NULL,
                    ingestion_id TEXT NOT NULL,
                    UNIQUE (mt5_account_id, deal_ticket)
                )
            """,
            "CREATE INDEX IF NOT EXISTS idx_deals_order ON deals (mt5_account_id, order_ticket)",
            "CREATE INDEX IF NOT EXISTS idx_deals_position ON deals (mt5_account_id, position_id)",
            """
                CREATE TABLE IF NOT EXISTS deal_observations (
                    id TEXT PRIMARY KEY,
                    deal_id TEXT NOT NULL REFERENCES deals(id),
                    payload_hash TEXT NOT NULL,
                    raw_payload TEXT NOT NULL,
                    observed_at TEXT NOT NULL,
                    ingestion_id TEXT NOT NULL,
                    normalizer_version INTEGER NOT NULL,
                    UNIQUE (deal_id, payload_hash)
                )
            """,
        )
        with self._write() as conn:
            for statement in statements:
                conn.execute(statement)

    @staticmethod
    def _account_from_row(row: sqlite3.Row) -> AccountRef:
        return AccountRef(mt5_account_id=UUID(row["mt5_account_id"]),
                          broker_namespace=row["broker_namespace"], server=row["server"],
                          login=int(row["login"]), company_observed=row["company_observed"],
                          trade_mode=row["trade_mode"])

    @staticmethod
    def _identity(account: AccountRef) -> tuple[str, str, str]:
        return account.broker_namespace, account.server, str(account.login)

    def register_account(self, account: AccountRef) -> AccountRef:
        if not isinstance(account, AccountRef):
            raise TypeError("account must be an AccountRef")
        account_id = str(account.mt5_account_id)
        identity = self._identity(account)
        with self._write() as conn:
            by_id = conn.execute("SELECT * FROM ledger_accounts WHERE mt5_account_id = ?", (account_id,)).fetchone()
            by_identity = conn.execute(
                "SELECT * FROM ledger_accounts WHERE broker_namespace = ? AND server = ? AND login = ?",
                identity).fetchone()
            if by_id is not None and self._identity(self._account_from_row(by_id)) != identity:
                raise AccountIdentityError("account UUID is already mapped to a different broker/server/login")
            if by_identity is not None and by_identity["mt5_account_id"] != account_id:
                raise AccountIdentityError("broker/server/login is already mapped to a different account UUID")
            if by_id is None:
                conn.execute(
                    "INSERT INTO ledger_accounts VALUES (?, ?, ?, ?, ?, ?)",
                    (account_id, *identity, account.company_observed, account.trade_mode))
            else:
                # These are observed metadata, not immutable identity fields.
                conn.execute("UPDATE ledger_accounts SET company_observed = ?, trade_mode = ? "
                             "WHERE mt5_account_id = ?",
                             (account.company_observed, account.trade_mode, account_id))
        return account

    def resolve_account(self, *, broker_namespace: str, server: str, login: int) -> AccountRef | None:
        if not isinstance(broker_namespace, str) or not isinstance(server, str):
            raise TypeError("broker_namespace and server must be strings")
        if isinstance(login, bool) or not isinstance(login, int) or login <= 0:
            raise ValueError("login must be a positive integer")
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM ledger_accounts WHERE broker_namespace = ? AND server = ? AND login = ?",
                (broker_namespace, server, str(login))).fetchone()
        return self._account_from_row(row) if row is not None else None

    @staticmethod
    def _deal_values(deal: NormalizedDeal) -> tuple:
        return (
            str(deal.id), str(deal.mt5_account_id), str(deal.deal_ticket),
            str(deal.order_ticket), str(deal.position_id), deal.symbol, deal.deal_type,
            deal.deal_entry, str(deal.magic), str(deal.volume), str(deal.price),
            str(deal.commission), str(deal.swap), str(deal.profit), str(deal.broker_fee),
            deal.broker_time_seconds, deal.executed_at_msc, deal.reason,
            str(deal.sl) if deal.sl is not None else None,
            str(deal.tp) if deal.tp is not None else None, deal.comment, deal.external_id,
            deal.raw_payload_json, deal.payload_hash, deal.normalizer_version,
            deal.first_seen_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
            deal.ingestion_id,
        )

    @staticmethod
    def _validate_payload(deal: NormalizedDeal) -> None:
        try:
            raw = json.loads(deal.raw_payload_json)
            canonical = json.dumps(raw, sort_keys=True, separators=(",", ":"),
                                   ensure_ascii=False, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise ValueError("deal raw_payload_json must be valid canonical JSON") from exc
        if not isinstance(raw, dict) or canonical != deal.raw_payload_json:
            raise ValueError("deal raw_payload_json must be a canonical JSON object")
        if hashlib.sha256(canonical.encode("utf-8")).hexdigest() != deal.payload_hash:
            raise ValueError("deal payload_hash does not match raw_payload_json")

    def ingest(self, account: AccountRef, deal: NormalizedDeal) -> IngestResult:
        if not isinstance(account, AccountRef) or not isinstance(deal, NormalizedDeal):
            raise TypeError("ingest requires AccountRef and NormalizedDeal")
        if deal.mt5_account_id != account.mt5_account_id:
            raise AccountIdentityError("deal account ID differs from supplied account context")
        self._validate_payload(deal)
        account_id = str(account.mt5_account_id)
        with self._write() as conn:
            registered = conn.execute(
                "SELECT * FROM ledger_accounts WHERE mt5_account_id = ?", (account_id,)).fetchone()
            if registered is None:
                raise AccountIdentityError("account is not registered in this ledger")
            if self._identity(self._account_from_row(registered)) != self._identity(account):
                raise AccountIdentityError("supplied account context differs from persisted identity")

            placeholders = ", ".join("?" for _ in _DEAL_COLUMNS)
            columns = ", ".join(_DEAL_COLUMNS)
            inserted = conn.execute(
                f"INSERT INTO deals ({columns}) VALUES ({placeholders}) "
                "ON CONFLICT(mt5_account_id, deal_ticket) DO NOTHING",
                self._deal_values(deal)).rowcount
            if inserted:
                return IngestResult(IngestOutcome.INSERTED, deal.id)

            original = conn.execute(
                "SELECT id, payload_hash FROM deals WHERE mt5_account_id = ? AND deal_ticket = ?",
                (account_id, str(deal.deal_ticket))).fetchone()
            if original is None:
                raise RuntimeError("deal conflict did not resolve to an existing row")
            original_id = UUID(original["id"])
            if original["payload_hash"] == deal.payload_hash:
                return IngestResult(IngestOutcome.DUPLICATE, original_id)

            observation_id = uuid5(_OBSERVATION_NAMESPACE, f"{original_id}:{deal.payload_hash}")
            added = conn.execute(
                "INSERT INTO deal_observations "
                "(id, deal_id, payload_hash, raw_payload, observed_at, ingestion_id, normalizer_version) "
                "VALUES (?, ?, ?, ?, ?, ?, ?) "
                "ON CONFLICT(deal_id, payload_hash) DO NOTHING",
                (str(observation_id), str(original_id), deal.payload_hash, deal.raw_payload_json,
                 deal.first_seen_at.astimezone(timezone.utc).isoformat(timespec="microseconds"),
                 deal.ingestion_id, deal.normalizer_version)).rowcount
            return IngestResult(IngestOutcome.CONFLICT, original_id, observation_added=bool(added))

    @staticmethod
    def _deal_from_row(row: sqlite3.Row) -> NormalizedDeal:
        return NormalizedDeal(
            id=UUID(row["id"]), mt5_account_id=UUID(row["mt5_account_id"]),
            deal_ticket=int(row["deal_ticket"]), order_ticket=int(row["order_ticket"]),
            position_id=int(row["position_id"]), symbol=row["symbol"],
            deal_type=row["deal_type"], deal_entry=row["deal_entry"], magic=int(row["magic"]),
            volume=Decimal(row["volume"]), price=Decimal(row["price"]),
            commission=Decimal(row["commission"]), swap=Decimal(row["swap"]),
            profit=Decimal(row["profit"]), broker_fee=Decimal(row["broker_fee"]),
            broker_time_seconds=row["broker_time_seconds"], executed_at_msc=row["executed_at_msc"],
            reason=row["reason"], sl=Decimal(row["sl"]) if row["sl"] is not None else None,
            tp=Decimal(row["tp"]) if row["tp"] is not None else None,
            comment=row["comment"], external_id=row["external_id"],
            raw_payload_json=row["raw_payload"], payload_hash=row["payload_hash"],
            normalizer_version=row["normalizer_version"],
            first_seen_at=datetime.fromisoformat(row["first_seen_at"]),
            ingestion_id=row["ingestion_id"],
        )

    @staticmethod
    def _account_id(mt5_account_id: UUID) -> str:
        if not isinstance(mt5_account_id, UUID):
            raise TypeError("mt5_account_id must be a UUID")
        return str(mt5_account_id)

    @staticmethod
    def _ticket(ticket: int, *, positive: bool = False) -> str:
        if isinstance(ticket, bool) or not isinstance(ticket, int) or ticket < (1 if positive else 0):
            raise ValueError("ticket must be a non-negative integer" if not positive else
                             "deal_ticket must be a positive integer")
        return str(ticket)

    def get(self, mt5_account_id: UUID, deal_ticket: int) -> NormalizedDeal | None:
        with closing(self._connect()) as conn:
            row = conn.execute(
                "SELECT * FROM deals WHERE mt5_account_id = ? AND deal_ticket = ?",
                (self._account_id(mt5_account_id), self._ticket(deal_ticket, positive=True))).fetchone()
        return self._deal_from_row(row) if row is not None else None

    def _list(self, account_id: UUID, ticket: int, column: str) -> tuple[NormalizedDeal, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                f"SELECT * FROM deals WHERE mt5_account_id = ? AND {column} = ? "
                "ORDER BY executed_at_msc, deal_ticket",
                (self._account_id(account_id), self._ticket(ticket))).fetchall()
        return tuple(self._deal_from_row(row) for row in rows)

    def list_by_order(self, mt5_account_id: UUID, order_ticket: int) -> tuple[NormalizedDeal, ...]:
        return self._list(mt5_account_id, order_ticket, "order_ticket")

    def list_by_position(self, mt5_account_id: UUID, position_id: int) -> tuple[NormalizedDeal, ...]:
        return self._list(mt5_account_id, position_id, "position_id")

    def list_observations(self, mt5_account_id: UUID, deal_ticket: int) -> tuple[DealObservation, ...]:
        with closing(self._connect()) as conn:
            rows = conn.execute(
                "SELECT o.* FROM deal_observations AS o JOIN deals AS d ON d.id = o.deal_id "
                "WHERE d.mt5_account_id = ? AND d.deal_ticket = ? "
                "ORDER BY o.observed_at, o.id",
                (self._account_id(mt5_account_id), self._ticket(deal_ticket, positive=True))).fetchall()
        return tuple(DealObservation(
            id=UUID(row["id"]), deal_id=UUID(row["deal_id"]), payload_hash=row["payload_hash"],
            raw_payload_json=row["raw_payload"], observed_at=datetime.fromisoformat(row["observed_at"]),
            ingestion_id=row["ingestion_id"], normalizer_version=row["normalizer_version"])
            for row in rows)
