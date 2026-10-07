"""File-backed Deal Ledger tests; no terminal, network, or credentials."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from uuid import UUID

from test_deal_normalizer import ledger, raw_deal


class DealRepositoryTests(unittest.TestCase):
    def setUp(self):
        # A named file avoids restrictive ACLs on TemporaryDirectory in this
        # Windows test environment while still exercising real file storage.
        temp = tempfile.NamedTemporaryFile(dir=Path.cwd(), suffix=".sqlite3", delete=False)
        self.path = Path(temp.name)
        temp.close()
        self.addCleanup(self.path.unlink, missing_ok=True)
        self.repo = ledger.SQLiteDealRepository(self.path)
        self.addCleanup(self.repo.close)
        self.account = ledger.AccountRef(
            mt5_account_id=UUID("cc17f0e2-0784-4d99-81cc-ce44e990767c"),
            broker_namespace="broker-a", server="server-live", login=123456,
            company_observed="Broker A", trade_mode=2)
        self.other = ledger.AccountRef(
            mt5_account_id=UUID("ac647462-f801-44f7-a60f-6b6c86c2b9e1"),
            broker_namespace="broker-b", server="server-live", login=123456,
            company_observed="Broker B", trade_mode=2)
        self.when = datetime(2026, 10, 7, 12, 30, tzinfo=timezone(timedelta(hours=7)))

    def deal(self, account=None, **changes):
        account = account or self.account
        return ledger.normalize_deal(account, raw_deal(**changes), self.when, "batch-1")

    def register(self):
        self.repo.register_account(self.account)

    def count(self, table):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    def test_register_resolve_and_reopen_preserve_uuid_and_deal(self):
        self.register()
        deal = self.deal()
        self.assertEqual(self.repo.ingest(self.account, deal).outcome, ledger.IngestOutcome.INSERTED)
        self.repo.close()
        reopened = ledger.SQLiteDealRepository(self.path)
        self.addCleanup(reopened.close)
        resolved = reopened.resolve_account(broker_namespace="broker-a", server="server-live", login=123456)
        self.assertEqual(resolved, self.account)
        self.assertEqual(reopened.get(resolved.mt5_account_id, deal.deal_ticket), deal)
        self.assertEqual(reopened.ingest(resolved, deal).outcome, ledger.IngestOutcome.DUPLICATE)
        self.assertEqual(self.count("deals"), 1)

    def test_account_identity_mismatches_fail_and_metadata_can_change(self):
        self.register()
        with self.assertRaises(ledger.AccountIdentityError):
            self.repo.register_account(replace(self.account, server="other-server"))
        with self.assertRaises(ledger.AccountIdentityError):
            self.repo.register_account(replace(self.account, mt5_account_id=self.other.mt5_account_id))
        updated = replace(self.account, company_observed="Renamed Broker", trade_mode=1)
        self.repo.register_account(updated)
        self.assertEqual(self.repo.resolve_account(broker_namespace="broker-a", server="server-live",
                                                   login=123456), updated)
        self.assertEqual(self.count("ledger_accounts"), 1)

    def test_unregistered_or_wrong_account_context_cannot_ingest(self):
        deal = self.deal()
        with self.assertRaises(ledger.AccountIdentityError):
            self.repo.ingest(self.account, deal)
        self.register()
        with self.assertRaises(ledger.AccountIdentityError):
            self.repo.ingest(self.other, deal)
        with self.assertRaises(ledger.AccountIdentityError):
            self.repo.ingest(replace(self.account, login=654321), deal)
        self.assertEqual(self.count("deals"), 0)

    def test_first_insert_and_identical_replay_do_not_change_original(self):
        self.register()
        deal = self.deal()
        first = self.repo.ingest(self.account, deal)
        self.assertEqual((first.outcome, first.deal_id, first.observation_added),
                         (ledger.IngestOutcome.INSERTED, deal.id, False))
        replay = replace(deal, first_seen_at=deal.first_seen_at + timedelta(days=1), ingestion_id="batch-2")
        self.assertEqual(self.repo.ingest(self.account, replay).outcome, ledger.IngestOutcome.DUPLICATE)
        self.assertEqual(self.repo.get(self.account.mt5_account_id, deal.deal_ticket), deal)
        self.assertEqual(self.repo.list_observations(self.account.mt5_account_id, deal.deal_ticket), ())
        self.assertEqual(self.count("deals"), 1)

    def test_changed_payload_is_observation_and_replay_is_idempotent(self):
        self.register()
        original = self.deal()
        changed = self.deal(comment="broker sửa", profit=99.25, fee=-0.75)
        self.repo.ingest(self.account, original)
        first = self.repo.ingest(self.account, changed)
        second = self.repo.ingest(self.account, changed)
        self.assertEqual((first.outcome, first.observation_added), (ledger.IngestOutcome.CONFLICT, True))
        self.assertEqual((second.outcome, second.observation_added), (ledger.IngestOutcome.CONFLICT, False))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, original.deal_ticket), original)
        observations = self.repo.list_observations(self.account.mt5_account_id, original.deal_ticket)
        self.assertEqual(len(observations), 1)
        self.assertEqual((observations[0].deal_id, observations[0].payload_hash,
                          observations[0].raw_payload["comment"]),
                         (original.id, changed.payload_hash, "broker sửa"))
        self.assertEqual((self.count("deals"), self.count("deal_observations")), (1, 1))

    def test_same_ticket_in_two_accounts_is_distinct_and_reads_are_scoped(self):
        self.register()
        self.repo.register_account(self.other)
        first, second = self.deal(), self.deal(self.other)
        self.assertEqual(self.repo.ingest(self.account, first).outcome, ledger.IngestOutcome.INSERTED)
        self.assertEqual(self.repo.ingest(self.other, second).outcome, ledger.IngestOutcome.INSERTED)
        self.assertNotEqual(first.id, second.id)
        for account, deal in ((self.account, first), (self.other, second)):
            self.assertEqual(self.repo.get(account.mt5_account_id, 9001), deal)
            self.assertEqual(self.repo.list_by_order(account.mt5_account_id, 8001), (deal,))
            self.assertEqual(self.repo.list_by_position(account.mt5_account_id, 7001), (deal,))
        self.assertEqual(self.count("deals"), 2)

    def test_one_order_and_position_can_have_multiple_deals(self):
        self.register()
        deals = tuple(self.deal(ticket=ticket, time_msc=1700000000123 + i)
                      for i, ticket in enumerate((9001, 9002, 9003)))
        for deal in deals:
            self.repo.ingest(self.account, deal)
        self.assertEqual(self.repo.list_by_order(self.account.mt5_account_id, 8001), deals)
        self.assertEqual(self.repo.list_by_position(self.account.mt5_account_id, 7001), deals)
        self.assertEqual(self.repo.list_by_order(self.account.mt5_account_id, 9999), ())

    def test_decimal_large_ticket_and_raw_json_round_trip_without_loss(self):
        self.register()
        large = 2**63 + 55
        deal = self.deal(ticket=large, order=large + 1, position_id=large + 2, magic=large + 3,
                         volume=0.015, price=1.2345678901234567, commission=-0.1,
                         swap=-0.02, profit=3.33, fee=-0.75, sl=1.01, tp=1.5,
                         extra={"unicode": "cà phê", "items": [0, "", None]})
        self.repo.ingest(self.account, deal)
        loaded = self.repo.get(self.account.mt5_account_id, large)
        self.assertEqual(loaded, deal)
        self.assertEqual((loaded.deal_ticket, loaded.order_ticket, loaded.position_id, loaded.magic),
                         (large, large + 1, large + 2, large + 3))
        self.assertEqual((loaded.volume, loaded.price, loaded.broker_fee),
                         (Decimal("0.015"), Decimal("1.2345678901234567"), Decimal("-0.75")))
        self.assertEqual(loaded.raw_payload["extra"], {"unicode": "cà phê", "items": [0, "", None]})
        self.assertNotIn("saas_fee", loaded.__dataclass_fields__)

    def test_zero_empty_and_absent_fields_survive_file_storage(self):
        self.register()
        raw = raw_deal(order=0, position_id=0, magic=0, volume=0.0, price=0.0,
                       commission=0.0, swap=0.0, profit=0.0, fee=0.0,
                       symbol="", comment="", external_id="")
        for key in ("reason", "sl", "tp"):
            raw.pop(key)
        deal = ledger.normalize_deal(self.account, raw, self.when, "batch-1")
        self.repo.ingest(self.account, deal)
        loaded = self.repo.get(self.account.mt5_account_id, 9001)
        self.assertEqual(loaded, deal)
        self.assertEqual((loaded.volume, loaded.broker_fee), (Decimal("0.0"), Decimal("0.0")))
        self.assertEqual((loaded.comment, loaded.external_id, loaded.symbol), ("", "", ""))
        self.assertIsNone(loaded.reason)
        self.assertNotIn("reason", loaded.raw_payload)
        self.assertIn("fee", loaded.raw_payload)

    def test_database_enforces_both_unique_constraints(self):
        self.register()
        deal = self.deal()
        self.repo.ingest(self.account, deal)
        changed = self.deal(comment="correction")
        self.repo.ingest(self.account, changed)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                # Explicit second ID with the same composite identity.
                conn.execute("INSERT INTO deals SELECT ?, mt5_account_id, deal_ticket, order_ticket, "
                             "position_id, symbol, deal_type, deal_entry, magic, volume, price, commission, "
                             "swap, profit, broker_fee, broker_time_seconds, executed_at_msc, reason, sl, tp, "
                             "comment, external_id, raw_payload, payload_hash, normalizer_version, "
                             "first_seen_at, ingestion_id FROM deals WHERE id = ?",
                             (str(self.other.mt5_account_id), str(deal.id)))
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO deal_observations SELECT ?, deal_id, payload_hash, raw_payload, "
                             "observed_at, ingestion_id, normalizer_version FROM deal_observations",
                             (str(self.other.mt5_account_id),))
        self.assertEqual((self.count("deals"), self.count("deal_observations")), (1, 1))

    def test_account_mapping_unique_constraint_is_in_database(self):
        self.register()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            with self.assertRaises(sqlite3.IntegrityError):
                conn.execute("INSERT INTO ledger_accounts VALUES (?, ?, ?, ?, ?, ?)",
                             (str(self.other.mt5_account_id), "broker-a", "server-live",
                              "123456", "Another label", 1))
        self.assertEqual(self.count("ledger_accounts"), 1)

    def test_concurrent_duplicate_writers_leave_one_row(self):
        self.register()
        deal = self.deal()
        barrier = Barrier(2)

        def worker():
            repo = ledger.SQLiteDealRepository(self.path)
            try:
                barrier.wait(timeout=5)
                return repo.ingest(self.account, deal).outcome
            finally:
                repo.close()

        with ThreadPoolExecutor(max_workers=2) as pool:
            outcomes = list(pool.map(lambda _: worker(), range(2)))
        self.assertCountEqual(outcomes, [ledger.IngestOutcome.INSERTED, ledger.IngestOutcome.DUPLICATE])
        self.assertEqual(self.count("deals"), 1)

    def test_transaction_failure_never_reports_success_or_partial_observation(self):
        self.register()
        deal = self.deal()
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TRIGGER deny_deal BEFORE INSERT ON deals BEGIN SELECT RAISE(ABORT, 'deny'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.ingest(self.account, deal)
        self.assertIsNone(self.repo.get(self.account.mt5_account_id, deal.deal_ticket))
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("DROP TRIGGER deny_deal")
        self.repo.ingest(self.account, deal)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TRIGGER deny_observation BEFORE INSERT ON deal_observations "
                         "BEGIN SELECT RAISE(ABORT, 'deny'); END")
        with self.assertRaises(sqlite3.IntegrityError):
            self.repo.ingest(self.account, self.deal(comment="changed"))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, deal.deal_ticket), deal)
        self.assertEqual(self.count("deal_observations"), 0)

    def test_credentials_are_absent_from_account_schema(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            columns = {row[1] for row in conn.execute("PRAGMA table_info(ledger_accounts)")}
            deal_columns = {row[1] for row in conn.execute("PRAGMA table_info(deals)")}
        self.assertEqual(columns, {"mt5_account_id", "broker_namespace", "server", "login",
                                   "company_observed", "trade_mode"})
        self.assertIn("broker_fee", deal_columns)
        self.assertNotIn("saas_fee", deal_columns)


if __name__ == "__main__":
    unittest.main()
