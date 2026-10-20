"""File-backed Deal Ledger tests; no terminal, network, or credentials."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3
import tempfile
from threading import Barrier
import unittest
from unittest.mock import patch
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

    def assert_invalid_deal(self, deal):
        """Invalid models must not reach a transaction or change any ledger table."""
        def snapshot():
            with closing(sqlite3.connect(self.path)) as conn:
                return tuple(conn.execute(f"SELECT * FROM {table} ORDER BY rowid").fetchall()
                             for table in ("ledger_accounts", "deals", "deal_observations"))

        before = snapshot()
        with patch.object(self.repo, "_write", side_effect=AssertionError("invalid input reached write")) as write:
            with self.assertRaises(ValueError):
                self.repo.ingest(self.account, deal)
            write.assert_not_called()
        self.assertEqual(snapshot(), before)

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

    def test_nonfinite_decimals_cannot_enter_any_decimal_column(self):
        self.register()
        deal = self.deal()
        for name in ("volume", "price", "commission", "swap", "profit", "broker_fee", "sl", "tp"):
            for value in ("NaN", "sNaN", "Infinity", "-Infinity"):
                with self.subTest(field=name, value=value):
                    self.assert_invalid_deal(replace(deal, **{name: Decimal(value)}))

    def test_negative_and_payload_inconsistent_volume_and_price_are_rejected(self):
        self.register()
        deal = self.deal()
        for changes in ({"volume": Decimal("-1")}, {"volume": Decimal("99")},
                        {"price": Decimal("99")}, {"volume": Decimal(0.15)}):
            with self.subTest(changes=changes):
                self.assert_invalid_deal(replace(deal, **changes))
        # Rejected input has not poisoned a later, valid first insert.
        self.assertEqual(self.repo.ingest(self.account, deal).outcome, ledger.IngestOutcome.INSERTED)
        self.assertEqual(self.repo.get(self.account.mt5_account_id, deal.deal_ticket), deal)

    def test_all_payload_derived_fields_must_match_the_raw_snapshot(self):
        self.register()
        deal = self.deal()
        changes = dict(order_ticket=8888, position_id=7777, symbol="GBPUSD", deal_type=999,
                       deal_entry=999, magic=43, commission=Decimal("-99"), swap=Decimal("-1"),
                       profit=Decimal("99"), broker_fee=Decimal("-1"), broker_time_seconds=1,
                       executed_at_msc=1, reason=None, sl=None, tp=Decimal("9"),
                       comment="not the broker comment", external_id="not the broker ID")
        for name, value in changes.items():
            with self.subTest(field=name):
                self.assert_invalid_deal(replace(deal, **{name: value}))

    def test_equal_values_of_incorrect_types_do_not_pass_validation(self):
        self.register()
        deal = self.deal(volume=1.0, price=1.0, commission=0, swap=0, profit=0, fee=0,
                         sl=1.0, tp=1.0, type=0, entry=0, reason=0)
        for name in ("volume", "price", "commission", "swap", "profit", "broker_fee", "sl", "tp"):
            for value in (int(getattr(deal, name)), float(getattr(deal, name)),
                          str(getattr(deal, name)), None, False):
                with self.subTest(field=name, value=value):
                    self.assert_invalid_deal(replace(deal, **{name: value}))
        for name in ("deal_ticket", "order_ticket", "position_id", "deal_type", "deal_entry",
                     "magic", "broker_time_seconds", "executed_at_msc", "reason"):
            with self.subTest(field=name):
                self.assert_invalid_deal(replace(deal, **{name: float(getattr(deal, name))}))
        for name in ("deal_type", "deal_entry", "reason"):
            with self.subTest(field=name, value=False):
                self.assert_invalid_deal(replace(deal, **{name: False}))

    def test_ticket_and_deterministic_uuid_cannot_be_forged(self):
        self.register()
        deal = self.deal()
        wrong_id = self.deal(ticket=9002).id
        for changes in ({"deal_ticket": 9002}, {"id": wrong_id},
                        {"id": wrong_id, "deal_ticket": 9002}, {"id": UUID(int=0)},
                        {"id": str(deal.id)}, {"deal_ticket": 0}, {"deal_ticket": -1}):
            with self.subTest(changes=changes):
                self.assert_invalid_deal(replace(deal, **changes))

    def test_incorrect_account_uuid_and_cross_account_derived_id_are_rejected(self):
        self.register()
        self.repo.register_account(self.other)
        deal = self.deal()
        for value in (self.other.mt5_account_id, UUID(int=0), str(self.account.mt5_account_id), None):
            with self.subTest(account=value):
                self.assert_invalid_deal(replace(deal, mt5_account_id=value))
        # Relabeling the other account's normalized Deal still leaves its UUID inconsistent.
        self.assert_invalid_deal(replace(self.deal(self.other), mt5_account_id=self.account.mt5_account_id))

    def test_invalid_hash_and_unsupported_normalizer_version_are_rejected(self):
        self.register()
        deal = self.deal()
        for value in ("0" * 64, "", None, deal.payload_hash.encode()):
            with self.subTest(hash=value):
                self.assert_invalid_deal(replace(deal, payload_hash=value))
        for version in (0, -1, ledger.NORMALIZER_VERSION + 1, True, 1.0, "1", None):
            with self.subTest(version=version):
                self.assert_invalid_deal(replace(deal, normalizer_version=version))

    def test_malformed_or_noncanonical_raw_cannot_be_rescued_by_a_matching_hash(self):
        self.register()
        deal = self.deal()
        raw_cases = [None, b"{}", {}, "{", "[]", "null", "42", '"text"', "{}",
                     json.dumps(deal.raw_payload), deal.raw_payload_json + " ",
                     deal.raw_payload_json[:-1] + ',"ticket":9001}']
        for changes in ({"volume": -1}, {"volume": "0.15"}, {"ticket": True},
                        {"time_msc": -1}, {"extra": float("nan")}, {"price": float("inf")},
                        {"extra": -float("inf")}):
            raw_cases.append(json.dumps(raw_deal(**changes), sort_keys=True, separators=(",", ":")))
        for raw in raw_cases:
            with self.subTest(raw=raw):
                hash_ = hashlib.sha256(raw.encode()).hexdigest() if isinstance(raw, str) else deal.payload_hash
                self.assert_invalid_deal(replace(deal, raw_payload_json=raw, payload_hash=hash_))

    def test_invalid_metadata_is_rejected_before_any_write(self):
        self.register()
        deal = self.deal()
        for changes in ({"first_seen_at": self.when.replace(tzinfo=None)}, {"first_seen_at": None},
                        {"first_seen_at": self.when.isoformat()}, {"ingestion_id": ""},
                        {"ingestion_id": " "}, {"ingestion_id": None}, {"ingestion_id": 123}):
            with self.subTest(changes=changes):
                self.assert_invalid_deal(replace(deal, **changes))

    def test_invalid_input_cannot_be_classified_as_duplicate_or_create_false_conflict(self):
        self.register()
        original = self.deal()
        self.repo.ingest(self.account, original)
        changed = self.deal(comment="actual broker correction", profit=99.25)
        self.assert_invalid_deal(replace(original, volume=Decimal("99")))
        self.assert_invalid_deal(replace(original, raw_payload_json=changed.raw_payload_json,
                                         payload_hash=changed.payload_hash))
        self.assert_invalid_deal(replace(changed, profit=original.profit))
        self.assertEqual(self.repo.ingest(self.account, changed).outcome, ledger.IngestOutcome.CONFLICT)
        self.assert_invalid_deal(replace(changed, price=Decimal("99")))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, original.deal_ticket), original)
        self.assertEqual(self.count("deal_observations"), 1)

    def test_valid_zero_nullable_unknown_and_negative_historical_values_remain_supported(self):
        self.register()
        variants = (
            raw_deal(ticket=9001, order=0, position_id=0, magic=0, volume=0, price=0,
                     commission=0, swap=0, profit=0, fee=0, symbol="", comment="", external_id="",
                     reason=None, sl=None, tp=None),
            raw_deal(ticket=9002, volume=0.015, price=-1.25, commission=-0.2, swap=-1,
                     profit=-12, fee=-0.03, type=999, entry=998, reason=997,
                     extra={"unicode": "cà phê", "items": [0, "", None, {"future": True}]}),
        )
        for raw in variants:
            with self.subTest(ticket=raw["ticket"]):
                deal = ledger.normalize_deal(self.account, raw, self.when, "valid-history")
                self.assertEqual(self.repo.ingest(self.account, deal).outcome, ledger.IngestOutcome.INSERTED)
                loaded = self.repo.get(self.account.mt5_account_id, deal.deal_ticket)
                self.assertEqual(loaded, deal)
                self.assertEqual(loaded.raw_payload, raw)

    def test_metadata_changes_decimal_scale_conflicts_and_reopen_remain_compatible(self):
        self.register()
        original = replace(self.deal(), first_seen_at=self.when, volume=Decimal("0.1500"))
        self.assertEqual(self.repo.ingest(self.account, original).outcome, ledger.IngestOutcome.INSERTED)
        replay = replace(original, first_seen_at=self.when + timedelta(days=1), ingestion_id="new-run")
        self.assertEqual(self.repo.ingest(self.account, replay).outcome, ledger.IngestOutcome.DUPLICATE)
        changed = replace(self.deal(profit=99.25, extra={"future": [1, None]}),
                          first_seen_at=self.when + timedelta(days=2), ingestion_id="correction")
        first = self.repo.ingest(self.account, changed)
        second = self.repo.ingest(self.account, replace(changed, ingestion_id="correction-replay"))
        self.assertEqual((first.outcome, first.observation_added), (ledger.IngestOutcome.CONFLICT, True))
        self.assertEqual((second.outcome, second.observation_added), (ledger.IngestOutcome.CONFLICT, False))
        self.repo.close()
        reopened = ledger.SQLiteDealRepository(self.path)
        self.addCleanup(reopened.close)
        loaded = reopened.get(self.account.mt5_account_id, original.deal_ticket)
        self.assertEqual(loaded, original)
        self.assertEqual(str(loaded.volume), "0.1500")
        self.assertEqual(reopened.ingest(self.account, loaded).outcome, ledger.IngestOutcome.DUPLICATE)
        self.assertFalse(reopened.ingest(self.account, changed).observation_added)
        observations = reopened.list_observations(self.account.mt5_account_id, original.deal_ticket)
        self.assertEqual(len(observations), 1)
        self.assertEqual((observations[0].raw_payload_json, observations[0].ingestion_id),
                         (changed.raw_payload_json, "correction"))


if __name__ == "__main__":
    unittest.main()
