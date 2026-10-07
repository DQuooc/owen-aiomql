"""One-shot history ingestion against fake sources and real temporary SQLite files."""

import asyncio
from collections import namedtuple
from contextlib import closing
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import sqlite3
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock
from uuid import UUID

from test_deal_normalizer import ledger, raw_deal


class FakeSource:
    def __init__(self, account, records=()):
        self.broker_namespace = account.broker_namespace
        self.account = ledger.SessionAccount(account.login, account.server)
        self.before = self.after = self.account
        self.response = ledger.DealHistoryBatch(tuple(records))
        self.failure = None
        self.account_calls = 0
        self.fetch_calls = []

    async def current_account(self):
        self.account_calls += 1
        return self.before if self.account_calls % 2 else self.after

    async def fetch(self, account_ref, from_time, to_time):
        self.fetch_calls.append((account_ref, from_time, to_time))
        if self.failure is not None:
            raise self.failure
        return self.response


class DealIngestionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
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
        self.repo.register_account(self.account)
        self.start = datetime(2023, 11, 14, 22, 13, 20, tzinfo=timezone.utc)
        self.end = self.start + timedelta(days=1)

    def count(self, table="deals"):
        with closing(sqlite3.connect(self.path)) as conn:
            return conn.execute(f"SELECT count(*) FROM {table}").fetchone()[0]

    async def run_source(self, source, *, account=None, ingestion_id=None):
        return await ledger.DealIngestor(source, self.repo).ingest_range(
            account or self.account, self.start, self.end, ingestion_id=ingestion_id)

    def adapter(self, response, accounts=None):
        info = SimpleNamespace(login=self.account.login, server=self.account.server,
                               company="Changed label", trade_mode=0)
        mt5 = SimpleNamespace(
            account_info=AsyncMock(side_effect=accounts or [info, info]),
            history_deals_get=AsyncMock(return_value=response))
        return ledger.MetaTraderDealHistorySource(mt5, broker_namespace="broker-a"), mt5

    async def test_successful_single_deal_and_broker_fee(self):
        source = FakeSource(self.account, [raw_deal(fee=-0.75)])
        report = await self.run_source(source, ingestion_id="explicit-run")
        self.assertEqual(report.status, ledger.IngestionStatus.SUCCESS)
        self.assertEqual((report.retrieved, report.normalized, report.inserted,
                          report.duplicates, report.conflicts, report.invalid), (1, 1, 1, 0, 0, 0))
        self.assertFalse(report.has_errors)
        deal = self.repo.get(self.account.mt5_account_id, 9001)
        self.assertEqual(deal.broker_fee, Decimal("-0.75"))
        self.assertEqual(deal.ingestion_id, "explicit-run")
        self.assertNotIn("saas_fee", deal.__dataclass_fields__)
        self.assertEqual(source.account_calls, 2)

    async def test_empty_tuple_is_success_and_still_double_guarded(self):
        source, mt5 = self.adapter(())
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.SUCCESS_EMPTY)
        self.assertEqual((report.retrieved, report.inserted), (0, 0))
        self.assertFalse(report.has_errors)
        self.assertEqual(mt5.account_info.await_count, 2)

    async def test_source_none_is_failed_not_success_empty(self):
        source = FakeSource(self.account)
        source.response = None
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual(report.errors[0].stage, ledger.IngestionStage.FETCH)
        self.assertTrue(report.has_errors)
        self.assertEqual((report.retrieved, self.count()), (0, 0))

    async def test_invalid_sdk_collection_or_element_rejects_whole_fetch(self):
        for response in (None, "invalid", {"ticket": 9001}, (raw_deal(), 42)):
            with self.subTest(response=response):
                source, _ = self.adapter(response)
                report = await self.run_source(source)
                self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
                self.assertEqual(report.errors[0].stage, ledger.IngestionStage.FETCH)
                self.assertEqual(self.count(), 0)

    async def test_source_exception_is_explicit_failure(self):
        source = FakeSource(self.account)
        source.failure = ConnectionError("offline connection failure")
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual((report.errors[0].stage, report.errors[0].exception_type),
                         (ledger.IngestionStage.FETCH, "ConnectionError"))
        self.assertIn("offline connection failure", report.errors[0].message)
        self.assertEqual(self.count(), 0)

    async def test_account_mismatch_before_fetch_blocks_fetch_and_writes(self):
        for current in (ledger.SessionAccount(999, self.account.server),
                        ledger.SessionAccount(self.account.login, "other-server"), None):
            with self.subTest(current=current):
                source = FakeSource(self.account, [raw_deal()])
                source.before = current
                report = await self.run_source(source)
                self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
                self.assertEqual(report.errors[0].stage, ledger.IngestionStage.ACCOUNT_BEFORE_FETCH)
                self.assertEqual(source.fetch_calls, [])
                self.assertEqual(self.count(), 0)

    async def test_account_change_after_fetch_rejects_entire_batch(self):
        source = FakeSource(self.account, [raw_deal(), raw_deal(ticket=9002)])
        source.after = ledger.SessionAccount(999, "other-server")
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual(report.errors[0].stage, ledger.IngestionStage.ACCOUNT_AFTER_FETCH)
        self.assertEqual((report.retrieved, report.normalized, self.count()), (2, 0, 0))

    async def test_configured_broker_namespace_mismatch_is_rejected(self):
        source = FakeSource(self.account, [raw_deal()])
        source.broker_namespace = "another-broker"
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual(source.fetch_calls, [])
        self.assertEqual(self.count(), 0)

    async def test_adapter_account_unavailable_exception_or_changed_fails_closed(self):
        info = SimpleNamespace(login=self.account.login, server=self.account.server)
        cases = [([None], ledger.IngestionStage.ACCOUNT_BEFORE_FETCH),
                 ([ConnectionError("account unavailable")], ledger.IngestionStage.ACCOUNT_BEFORE_FETCH),
                 ([info, None], ledger.IngestionStage.ACCOUNT_AFTER_FETCH),
                 ([info, SimpleNamespace(login=999, server=info.server)],
                  ledger.IngestionStage.ACCOUNT_AFTER_FETCH)]
        for accounts, expected_stage in cases:
            with self.subTest(stage=expected_stage, accounts=accounts):
                source, mt5 = self.adapter((raw_deal(),), accounts)
                report = await self.run_source(source)
                self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
                self.assertEqual(report.errors[0].stage, expected_stage)
                if expected_stage == ledger.IngestionStage.ACCOUNT_BEFORE_FETCH:
                    mt5.history_deals_get.assert_not_awaited()
                self.assertEqual(self.count(), 0)

    async def test_raw_sdk_namedtuple_unknown_fields_preserved_and_metadata_ignored(self):
        raw = raw_deal(extra={"unicode": "cà phê", "zero": 0, "empty": ""})
        SDKDeal = namedtuple("SDKDeal", raw.keys())
        source, _ = self.adapter((SDKDeal(**raw),))
        report = await self.run_source(source)
        self.assertEqual(report.inserted, 1)
        raw["extra"]["zero"] = 999
        deal = self.repo.get(self.account.mt5_account_id, 9001)
        self.assertEqual(deal.raw_payload["extra"], {"unicode": "cà phê", "zero": 0, "empty": ""})

    async def test_partial_fills_same_order_and_position_are_independent(self):
        source = FakeSource(self.account, [raw_deal(ticket=9001, volume=0.015),
                                          raw_deal(ticket=9002, volume=0.025)])
        report = await self.run_source(source)
        self.assertEqual((report.retrieved, report.inserted), (2, 2))
        deals = self.repo.list_by_order(self.account.mt5_account_id, 8001)
        self.assertEqual({d.deal_ticket for d in deals}, {9001, 9002})
        self.assertEqual({d.volume for d in deals}, {Decimal("0.015"), Decimal("0.025")})
        self.assertEqual(len(self.repo.list_by_position(self.account.mt5_account_id, 7001)), 2)
        self.assertEqual({d.ingestion_id for d in deals}, {report.ingestion_id})

    async def test_replay_generates_new_ingestion_id_without_new_deals(self):
        source = FakeSource(self.account, [raw_deal(), raw_deal(ticket=9002)])
        first = await self.run_source(source)
        second = await self.run_source(source)
        self.assertNotEqual(first.ingestion_id, second.ingestion_id)
        self.assertEqual((first.inserted, second.inserted, second.duplicates, self.count()), (2, 0, 2, 2))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, 9001).ingestion_id, first.ingestion_id)

    async def test_changed_payload_replay_preserves_original_and_one_observation(self):
        await self.run_source(FakeSource(self.account, [raw_deal()]))
        original = self.repo.get(self.account.mt5_account_id, 9001)
        changed = FakeSource(self.account, [raw_deal(profit=99.25)])
        first = await self.run_source(changed, ingestion_id="correction-1")
        second = await self.run_source(changed, ingestion_id="correction-2")
        self.assertEqual((first.conflicts, second.conflicts, self.count()), (1, 1, 1))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, 9001), original)
        observations = self.repo.list_observations(self.account.mt5_account_id, 9001)
        self.assertEqual(len(observations), 1)
        self.assertEqual(observations[0].ingestion_id, "correction-1")

    async def test_same_ticket_in_other_account_is_isolated(self):
        other = replace(self.account, mt5_account_id=UUID("ac647462-f801-44f7-a60f-6b6c86c2b9e1"), login=555)
        self.repo.register_account(other)
        first = await self.run_source(FakeSource(self.account, [raw_deal()]))
        second = await self.run_source(FakeSource(other, [raw_deal()]), account=other)
        self.assertEqual((first.inserted, second.inserted, self.count()), (1, 1, 2))
        self.assertNotEqual(self.repo.get(self.account.mt5_account_id, 9001).id,
                            self.repo.get(other.mt5_account_id, 9001).id)

    async def test_mixed_batch_is_partial_and_reports_invalid_ticket_and_reason(self):
        source = FakeSource(self.account, [raw_deal(), raw_deal(ticket=9002, volume="bad"),
                                          raw_deal(ticket=9003)])
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.PARTIAL)
        self.assertEqual((report.retrieved, report.normalized, report.inserted, report.invalid), (3, 2, 2, 1))
        error = report.errors[0]
        self.assertEqual((error.stage, error.record_index, error.deal_ticket),
                         (ledger.IngestionStage.NORMALIZE, 1, 9002))
        self.assertIn("volume", error.message)
        self.assertEqual(self.count(), 2)

    async def test_all_invalid_is_failed_and_missing_identity_is_visible(self):
        raw = raw_deal()
        del raw["ticket"]
        report = await self.run_source(FakeSource(self.account, [raw]))
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual((report.invalid, report.inserted, self.count()), (1, 0, 0))
        self.assertIsNone(report.errors[0].deal_ticket)
        self.assertIn("ticket", report.errors[0].message)

    async def test_storage_failure_stops_batch_and_reports_prior_commits(self):
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute("CREATE TRIGGER deny_second BEFORE INSERT ON deals "
                         "WHEN NEW.deal_ticket = '9002' BEGIN SELECT RAISE(ABORT, 'storage unavailable'); END")
        source = FakeSource(self.account, [raw_deal(ticket=t) for t in (9001, 9002, 9003)])
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.FAILED)
        self.assertEqual((report.retrieved, report.normalized, report.inserted, report.invalid), (3, 2, 1, 0))
        self.assertEqual((report.errors[0].stage, report.errors[0].deal_ticket),
                         (ledger.IngestionStage.STORAGE, 9002))
        self.assertEqual(self.count(), 1)
        self.assertIsNone(self.repo.get(self.account.mt5_account_id, 9003))

    async def test_five_record_mixed_outcome_counters(self):
        await self.run_source(FakeSource(self.account, [raw_deal(ticket=9001), raw_deal(ticket=9002)]))
        source = FakeSource(self.account, [raw_deal(ticket=t) for t in (9003, 9004, 9005, 9001)] +
                            [raw_deal(ticket=9002, comment="changed")])
        report = await self.run_source(source)
        self.assertEqual(report.status, ledger.IngestionStatus.SUCCESS)
        self.assertEqual((report.retrieved, report.normalized, report.inserted, report.duplicates,
                          report.conflicts, report.invalid), (5, 5, 3, 1, 1, 0))
        self.assertEqual((self.count(), self.count("deal_observations")), (5, 1))

    async def test_timezone_conversion_and_boundary_deals_are_preserved(self):
        zone = timezone(timedelta(hours=7))
        start, end = self.start.astimezone(zone), self.end.astimezone(zone)
        first, last = int(self.start.timestamp()), int(self.end.timestamp())
        source, mt5 = self.adapter((raw_deal(time=first, time_msc=first * 1000),
                                   raw_deal(ticket=9002, time=last, time_msc=last * 1000)))
        report = await ledger.DealIngestor(source, self.repo).ingest_range(self.account, start, end)
        mt5.history_deals_get.assert_awaited_once_with(date_from=self.start, date_to=self.end)
        self.assertIs(report.requested_from.tzinfo, timezone.utc)
        self.assertEqual((report.requested_from, report.requested_to, report.inserted),
                         (self.start, self.end, 2))
        self.assertEqual(self.repo.get(self.account.mt5_account_id, 9002).executed_at_msc, last * 1000)

    async def test_equal_range_is_allowed_and_bad_arguments_fail_before_io(self):
        source = FakeSource(self.account, [raw_deal()])
        ingestor = ledger.DealIngestor(source, self.repo)
        report = await ingestor.ingest_range(self.account, self.start, self.start)
        self.assertEqual(report.inserted, 1)
        for start, end in ((self.start.replace(tzinfo=None), self.end), (self.end, self.start),
                           (self.start.timestamp(), self.end)):
            with self.subTest(start=start, end=end):
                with self.assertRaises(ValueError):
                    await ingestor.ingest_range(self.account, start, end)
        with self.assertRaises(ValueError):
            await ingestor.ingest_range(self.account, self.start, self.end, ingestion_id=" ")
        self.assertEqual(len(source.fetch_calls), 1)

    async def test_cancellation_propagates_without_being_success_or_empty(self):
        source = FakeSource(self.account)
        source.failure = asyncio.CancelledError()
        with self.assertRaises(asyncio.CancelledError):
            await self.run_source(source)
        self.assertEqual(self.count(), 0)


if __name__ == "__main__":
    unittest.main()
