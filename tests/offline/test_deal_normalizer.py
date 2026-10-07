"""Pure, offline contracts for Phase 2.2A; no MT5 package or terminal is loaded."""

from datetime import datetime, timedelta, timezone
from decimal import Decimal
import importlib.util
from pathlib import Path
import sys
import unittest
from uuid import UUID


LEDGER_DIR = Path(__file__).resolve().parents[2] / "src" / "aiomql" / "ledger"
PACKAGE = "_aiomql_ledger_offline"
spec = importlib.util.spec_from_file_location(
    PACKAGE, LEDGER_DIR / "__init__.py", submodule_search_locations=[str(LEDGER_DIR)])
ledger = importlib.util.module_from_spec(spec)
sys.modules[PACKAGE] = ledger
spec.loader.exec_module(ledger)


class SDKDeal:
    def __init__(self, values):
        self.values = values

    def _asdict(self):
        return self.values


def raw_deal(**changes):
    raw = {
        "ticket": 9001, "order": 8001, "position_id": 7001,
        "time": 1700000000, "time_msc": 1700000000123,
        "type": 0, "entry": 0, "magic": 42, "volume": 0.15,
        "price": 1.12345, "commission": -0.2, "swap": 0.0,
        "profit": 12.34, "fee": -0.05, "symbol": "EURUSD",
        "reason": 3, "sl": 1.1, "tp": 1.2, "comment": "", "external_id": "",
    }
    raw.update(changes)
    return raw


class DealNormalizerTests(unittest.TestCase):
    def setUp(self):
        self.account = ledger.AccountRef(
            mt5_account_id=UUID("cc17f0e2-0784-4d99-81cc-ce44e990767c"),
            broker_namespace="broker-a", server="server-live", login=123456,
            company_observed="Broker A", trade_mode=2)
        self.observed_at = datetime(2026, 10, 7, 12, 30, tzinfo=timezone(timedelta(hours=7)))

    def normalize(self, raw=None, account=None):
        return ledger.normalize_deal(account or self.account, raw_deal() if raw is None else raw,
                                     self.observed_at, "batch-1")

    def test_normal_sdk_deal_and_explicit_account_identity(self):
        deal = self.normalize(SDKDeal(raw_deal()))
        self.assertIsInstance(deal, ledger.NormalizedDeal)
        self.assertEqual(deal.mt5_account_id, self.account.mt5_account_id)
        self.assertEqual((deal.deal_ticket, deal.order_ticket, deal.position_id), (9001, 8001, 7001))
        self.assertEqual((deal.broker_time_seconds, deal.executed_at_msc), (1700000000, 1700000000123))
        self.assertEqual(deal.first_seen_at, datetime(2026, 10, 7, 5, 30, tzinfo=timezone.utc))
        self.assertEqual((deal.reason, deal.sl, deal.tp), (3, Decimal("1.1"), Decimal("1.2")))

    def test_account_ref_must_be_supplied_and_is_stable_after_recreation(self):
        with self.assertRaises(TypeError):
            ledger.AccountRef(broker_namespace="broker-a", server="server-live", login=123456,
                              company_observed="Broker A", trade_mode=2)
        recreated = ledger.AccountRef(
            mt5_account_id=str(self.account.mt5_account_id), broker_namespace="broker-a",
            server="server-live", login=123456, company_observed="Broker A", trade_mode=2)
        self.assertEqual(recreated, self.account)
        self.assertEqual(self.normalize().id, self.normalize(account=recreated).id)
        other = ledger.AccountRef(
            mt5_account_id=UUID("ac647462-f801-44f7-a60f-6b6c86c2b9e1"),
            broker_namespace="broker-b", server="server-live", login=123456,
            company_observed="Broker B", trade_mode=2)
        self.assertNotEqual(self.normalize().id, self.normalize(account=other).id)

    def test_account_ref_rejects_placeholder_identity(self):
        with self.assertRaisesRegex(ValueError, "nil UUID"):
            ledger.AccountRef(mt5_account_id=UUID(int=0), broker_namespace="broker-a",
                              server="server-live", login=123456,
                              company_observed="Broker A", trade_mode=2)

    def test_volume_uses_decimal_from_sdk_float(self):
        deal = self.normalize(raw_deal(volume=0.1))
        self.assertEqual(deal.volume, Decimal("0.1"))
        self.assertNotEqual(deal.volume, Decimal(0.1))

    def test_money_and_price_use_decimal(self):
        deal = self.normalize(raw_deal(price=1.234567, commission=-0.1, swap=-0.02,
                                       profit=3.33, fee=-0.04, sl=1.01, tp=1.5))
        self.assertEqual((deal.price, deal.commission, deal.swap, deal.profit, deal.broker_fee,
                          deal.sl, deal.tp),
                         tuple(Decimal(value) for value in
                               ("1.234567", "-0.1", "-0.02", "3.33", "-0.04", "1.01", "1.5")))

    def test_large_ticket_is_exact(self):
        ticket = 9_007_199_254_740_993
        deal = self.normalize(raw_deal(ticket=ticket, order=ticket + 1, position_id=ticket + 2))
        self.assertEqual((deal.deal_ticket, deal.order_ticket, deal.position_id),
                         (ticket, ticket + 1, ticket + 2))
        self.assertEqual(deal.raw_payload["ticket"], ticket)

    def test_zero_empty_and_absent_remain_distinct(self):
        raw = raw_deal(order=0, position_id=0, magic=0, volume=0.0, price=0.0,
                       commission=0.0, swap=0.0, profit=0.0, fee=0.0,
                       symbol="", comment="", external_id="")
        raw.pop("reason")
        raw.pop("sl")
        raw.pop("tp")
        deal = self.normalize(raw)
        self.assertEqual((deal.order_ticket, deal.position_id, deal.magic), (0, 0, 0))
        self.assertEqual(deal.volume, Decimal("0.0"))
        self.assertEqual(deal.broker_fee, Decimal("0.0"))
        self.assertEqual((deal.symbol, deal.comment, deal.external_id), ("", "", ""))
        self.assertIsNone(deal.reason)
        self.assertNotIn("reason", deal.raw_payload)
        self.assertIn("fee", deal.raw_payload)

    def test_unknown_fields_and_snapshot_are_preserved(self):
        raw = raw_deal(extra={"empty": "", "zero": 0, "items": [1, 2]})
        deal = self.normalize(SDKDeal(raw))
        raw["extra"]["zero"] = 999
        raw["ticket"] = 1
        self.assertEqual(deal.raw_payload["extra"], {"empty": "", "zero": 0, "items": [1, 2]})
        self.assertEqual(deal.raw_payload["ticket"], 9001)
        snapshot = deal.raw_payload
        snapshot["extra"]["zero"] = 888
        self.assertEqual(deal.raw_payload["extra"]["zero"], 0)

    def test_unknown_enum_codes_are_kept(self):
        deal = self.normalize(raw_deal(type=999, entry=998, reason=997))
        self.assertEqual((deal.deal_type, deal.deal_entry, deal.reason), (999, 998, 997))

    def test_missing_required_field_is_explicit_error(self):
        for name in ("ticket", "order", "position_id", "time", "time_msc", "type", "entry",
                     "magic", "volume", "price", "commission", "swap", "profit", "fee", "symbol"):
            with self.subTest(field=name):
                raw = raw_deal()
                del raw[name]
                with self.assertRaisesRegex(ledger.DealNormalizationError, name):
                    self.normalize(raw)

    def test_invalid_types_and_timestamps_fail(self):
        for field, value in (("ticket", 1.5), ("ticket", True), ("volume", "0.1"),
                             ("price", "1.0"), ("entry", "new"), ("symbol", 123)):
            with self.subTest(field=field, value=value):
                with self.assertRaises(ledger.DealNormalizationError):
                    self.normalize(raw_deal(**{field: value}))
        with self.assertRaises(ledger.DealNormalizationError):
            ledger.normalize_deal(self.account, raw_deal(), datetime(2026, 10, 7), "batch-1")

    def test_nonfinite_values_are_rejected_including_unknown_fields(self):
        for field in ("volume", "price", "commission", "swap", "profit", "fee", "sl", "tp", "extra"):
            for invalid in (float("nan"), float("inf"), -float("inf")):
                with self.subTest(field=field, invalid=invalid):
                    with self.assertRaises(ledger.DealNormalizationError):
                        self.normalize(raw_deal(**{field: invalid}))

    def test_payload_hash_ignores_mapping_insertion_order(self):
        first = raw_deal(extra={"b": 2, "a": 1})
        second = dict(reversed(list(first.items())))
        second["extra"] = {"a": 1, "b": 2}
        self.assertEqual(self.normalize(first).payload_hash, self.normalize(second).payload_hash)
        self.assertEqual(self.normalize(first).raw_payload_json, self.normalize(second).raw_payload_json)

    def test_changed_raw_changes_payload_hash_but_not_deal_identity(self):
        first = self.normalize(raw_deal())
        changed = self.normalize(raw_deal(comment="broker correction"))
        self.assertEqual(first.id, changed.id)
        self.assertNotEqual(first.payload_hash, changed.payload_hash)

    def test_broker_fee_is_distinct_from_saas_fee(self):
        deal = self.normalize(raw_deal(fee=-0.75))
        self.assertEqual(deal.broker_fee, Decimal("-0.75"))
        self.assertNotIn("saas_fee", deal.__dataclass_fields__)
        self.assertEqual(deal.raw_payload["fee"], -0.75)

    def test_historical_volume_is_not_rounded_to_symbol_step(self):
        deal = self.normalize(raw_deal(volume=0.015))
        self.assertEqual(deal.volume, Decimal("0.015"))
        self.assertEqual(deal.raw_payload["volume"], 0.015)

    def test_unsupported_or_cyclic_raw_is_explicit_error(self):
        with self.assertRaisesRegex(ledger.DealNormalizationError, "unsupported type"):
            self.normalize(raw_deal(extra=object()))
        cyclic = raw_deal()
        cyclic["extra"] = cyclic
        with self.assertRaisesRegex(ledger.DealNormalizationError, "cycle"):
            self.normalize(cyclic)


if __name__ == "__main__":
    unittest.main()
