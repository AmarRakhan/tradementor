"""Build 648: trade journal (Trade Historie export). Pure logic + resumable sync on fakes; no Aster, no Firestore."""
from __future__ import annotations

import json
import unittest
from pathlib import Path

import trade_journal as tj

H = 3_600_000
T0 = 1_760_000_000_000


def fill(fid, order, side, order_side, qty, price, t, pnl=0.0, fee=0.01, symbol="BTCUSDT"):
    return {"id": fid, "orderId": order, "symbol": symbol, "positionSide": side, "side": order_side,
            "qty": str(qty), "price": str(price), "quoteQty": str(qty * price), "realizedPnl": str(pnl),
            "commission": str(fee), "commissionAsset": "USDT", "time": t, "maker": False}


def norm(rows):
    return [tj.normalize_fill(r) for r in rows]


class ClassifyTest(unittest.TestCase):
    def test_bot_prefixes(self):
        self.assertEqual(tj.classify_order("mbb-tp-abc", closing=True)["code"], "TAKE_PROFIT")
        self.assertEqual(tj.classify_order("mbb-ptp-abc", closing=True)["code"], "PORTFOLIO_TP")
        self.assertEqual(tj.classify_order("mbb-open-1-long", closing=False)["code"], "BOT_ENTRY")
        self.assertEqual(tj.classify_order("plah2-abc", closing=True)["code"], "AUTO_HEDGE")
        self.assertIn("afbouwen", tj.classify_order("plah2-abc", closing=True)["label"])
        self.assertEqual(tj.classify_order("tm-manual-abc-close-short", closing=True)["code"], "APP_CLOSE")
        self.assertEqual(tj.classify_order("tm-eh-3-abc", closing=True)["code"], "EMERGENCY_HEDGE")
        self.assertEqual(tj.classify_order("mbb-pll-exit-x", closing=True)["code"], "PROFIT_LOCK_EXIT")
        self.assertEqual(tj.classify_order("web_abc", closing=True)["code"], "EXCHANGE_MANUAL")

    def test_unknown_stays_unknown(self):
        self.assertFalse(tj.classify_order("", closing=True)["proven"])
        self.assertEqual(tj.classify_order(None, closing=True)["code"], "ORDER_NOT_AVAILABLE")
        self.assertEqual(tj.classify_order("xyz-123", closing=True)["code"], "OTHER")


class ProcessFillsTest(unittest.TestCase):
    def test_full_long_cycle_with_dca_and_split_tp_order(self):
        rows = norm([
            fill(1, "o1", "LONG", "BUY", 1, 100, T0, fee=0.05),
            fill(2, "o1", "LONG", "BUY", 1, 102, T0 + 1, fee=0.05),
            fill(3, "o2", "LONG", "BUY", 2, 90, T0 + H, fee=0.1),
            fill(4, "o3", "LONG", "SELL", 3, 110, T0 + 5 * H, pnl=40, fee=0.2),
            fill(5, "o3", "LONG", "SELL", 1, 111, T0 + 5 * H + 2, pnl=16, fee=0.1),
        ])
        cids = {"o1": "mbb-open-aa-open-long", "o2": "mbb-dca-bb-open-long", "o3": "mbb-tp-cc-close-long"}
        records, cycles = tj.process_fills("BTCUSDT", rows, {}, cids, contexts={"LONG": {"leverage": 10, "soldierRole": "ZONE_BASE"}})
        self.assertEqual(cycles, {})
        self.assertEqual(len(records), 1)
        r = records[0]
        self.assertEqual(r["closeType"], "FULL")
        self.assertEqual(r["closeReason"]["code"], "TAKE_PROFIT")
        self.assertEqual(r["cycle"]["entryReason"]["code"], "BOT_ENTRY")
        self.assertEqual(r["cycle"]["dcaCount"], 1)
        self.assertAlmostEqual(r["cycle"]["entryPriceAvg"], (100 + 102 + 180) / 4)
        self.assertAlmostEqual(r["quantity"], 4)
        self.assertAlmostEqual(r["exitPriceAvg"], (330 + 111) / 4)
        self.assertAlmostEqual(r["realizedPnlUsd"], 56)
        self.assertAlmostEqual(r["closeCommissionUsd"], 0.3)
        self.assertAlmostEqual(r["entryCommissionShareUsd"], 0.2)
        self.assertAlmostEqual(r["netPnlAfterFeesUsd"], 55.5)
        self.assertAlmostEqual(r["marginUsd"], 382 / 10)
        self.assertEqual(r["durationMs"], 5 * H + 2)
        self.assertEqual(r["fillIds"], [4, 5])
        self.assertEqual(r["context"]["soldierRole"], "ZONE_BASE")

    def test_hedge_afbouw_steps_are_partial_then_full(self):
        rows = norm([
            fill(10, "h1", "SHORT", "SELL", 3, 50, T0),
            fill(11, "s1", "SHORT", "BUY", 1, 49, T0 + H, pnl=1),
            fill(12, "s2", "SHORT", "BUY", 1, 48, T0 + 2 * H, pnl=2),
            fill(13, "s3", "SHORT", "BUY", 1, 47, T0 + 3 * H, pnl=3),
        ])
        cids = {"h1": "plah2-x", "s1": "plah2-y", "s2": "plah2-z", "s3": "plah2-w"}
        records, cycles = tj.process_fills("ETHUSDT", [dict(r, symbol="ETHUSDT") for r in rows], {}, cids)
        self.assertEqual([r["closeType"] for r in records], ["PARTIAL", "PARTIAL", "FULL"])
        self.assertEqual([r["cycle"]["closesBefore"] for r in records], [0, 1, 2])
        self.assertAlmostEqual(records[0]["closedFraction"], 1 / 3)
        self.assertAlmostEqual(records[1]["closedFraction"], 0.5)
        self.assertAlmostEqual(records[2]["closedFraction"], 1.0)
        self.assertTrue(all(r["closeReason"]["code"] == "AUTO_HEDGE" for r in records))
        self.assertEqual(cycles, {})

    def test_close_without_known_opening_is_not_invented(self):
        records, cycles = tj.process_fills("BTCUSDT", norm([fill(7, "x", "LONG", "SELL", 1, 100, T0, pnl=5)]), {}, {})
        self.assertEqual(records[0]["closeType"], "UNKNOWN_CYCLE")
        self.assertIsNone(records[0]["cycle"])
        self.assertIsNone(records[0]["netPnlAfterFeesUsd"])
        self.assertIsNone(records[0]["closeClientOrderId"])
        self.assertEqual(records[0]["closeReason"]["code"], "ORDER_NOT_AVAILABLE")

    def test_open_cycle_carries_over_between_calls(self):
        first, cycles = tj.process_fills("BTCUSDT", norm([fill(1, "o1", "LONG", "BUY", 2, 100, T0)]), {}, {"o1": "mbb-open-a"})
        self.assertEqual(first, [])
        stored = json.loads(json.dumps(cycles))                        # survives a JSON round trip (Firestore)
        second, cycles = tj.process_fills("BTCUSDT", norm([fill(2, "o2", "LONG", "SELL", 2, 105, T0 + H, pnl=10)]),
                                          stored, {"o2": "mbb-tp-b"})
        self.assertEqual(second[0]["closeType"], "FULL")
        self.assertEqual(second[0]["cycle"]["openedAtMs"], T0)
        self.assertEqual(second[0]["cycle"]["entryReason"]["code"], "BOT_ENTRY")

    def test_record_id_is_stable_per_order(self):
        a, _ = tj.process_fills("BTCUSDT", norm([fill(1, "o1", "LONG", "BUY", 1, 1, T0), fill(2, "o2", "LONG", "SELL", 1, 1, T0 + 1)]), {}, {})
        b, _ = tj.process_fills("BTCUSDT", norm([fill(1, "o1", "LONG", "BUY", 1, 1, T0), fill(2, "o2", "LONG", "SELL", 1, 1, T0 + 1)]), {}, {})
        self.assertEqual(a[0]["id"], b[0]["id"])


class TrimTest(unittest.TestCase):
    def test_full_page_drops_last_orders_fills(self):
        rows = norm([fill(i, f"o{i // 2}", "LONG", "BUY", 1, 1, T0 + i) for i in range(1, 11)])
        kept, complete = tj.trim_partial_tail(rows, page_limit=10)
        self.assertFalse(complete)
        self.assertNotIn("o5", {r["orderId"] for r in kept})

    def test_short_page_is_complete(self):
        rows = norm([fill(1, "o1", "LONG", "BUY", 1, 1, T0)])
        self.assertEqual(tj.trim_partial_tail(rows, page_limit=10), (rows, True))


class FakeStore:
    def __init__(self, strategy=None, auto=None):
        self.ctrl, self.symbols, self.records, self.versions, self.funding = {}, {}, {}, [], {}
        self.strategy = strategy or {"settings": {"takeProfit": 20, "longTakeProfitValue": 20}, "configVersion": 7}
        self.auto = auto or {"enabled": True, "thresholdUsd": 0.25}
        self.pairs = {}
        self.seed = {"BTCUSDT"}

    def control(self): return json.loads(json.dumps(self.ctrl))
    def save_control(self, patch): self.ctrl.update(json.loads(json.dumps(patch, default=str)))
    def symbol_state(self, symbol): return json.loads(json.dumps(self.symbols.get(symbol, {})))
    def save_symbol_state(self, symbol, state): self.symbols[symbol] = json.loads(json.dumps(state))
    def save_records(self, records):
        for r in records: self.records[r["id"]] = json.loads(json.dumps(r))
    def strategy_doc(self): return self.strategy
    def auto_hedge_doc(self): return self.auto
    def dynamic_hedge_doc(self): return {"enabled": False}
    def controls_doc(self): return {"profitSweep": {"enabled": True, "sweepPercent": 5}}
    def pair_doc(self, symbol): return self.pairs.get(symbol, {})
    def latest_settings_hash(self): return self.versions[-1]["hash"] if self.versions else None
    def save_settings_version(self, version): self.versions.append(json.loads(json.dumps(version)))
    def stored_symbols(self): return set(self.seed)
    def merge_funding(self, events):
        for s, rows in events.items(): self.funding.setdefault(s, {}).update(rows)


class FakeClient:
    def __init__(self, fills, orders, income=None, funding=None, broken=()):
        self.fills, self.orders, self.income, self.fund = fills, orders, income or [], funding or []
        self.broken = set(broken)
        self.calls = []

    def income_history(self, *, income_type=None, start_time=None, limit=500, **_):
        self.calls.append(("income", income_type))
        source = self.income if income_type == "REALIZED_PNL" else self.fund
        return [r for r in source if r["time"] >= (start_time or 0)][:limit]

    def all_orders(self, symbol, *, limit=500, **_):
        self.calls.append(("orders", symbol))
        if symbol in self.broken:
            raise RuntimeError("Aster-symbool niet leesbaar")
        return self.orders.get(symbol, [])

    def user_trades(self, symbol, *, from_id=None, limit=500, **_):
        self.calls.append(("trades", symbol, from_id))
        rows = sorted((r for r in self.fills if r["symbol"] == symbol and r["id"] >= (from_id or 0)), key=lambda r: r["id"])
        return rows[:limit]


class SyncTest(unittest.TestCase):
    def setUp(self):
        self.now = T0 + 10 * H
        self.fills = [
            fill(1, "o1", "LONG", "BUY", 1, 100, T0),
            fill(2, "o2", "LONG", "SELL", 1, 110, T0 + H, pnl=10),
            fill(1, "e1", "SHORT", "SELL", 2, 10, T0, symbol="ETHUSDT"),
            fill(2, "e2", "SHORT", "BUY", 1, 9, T0 + 2 * H, pnl=1, symbol="ETHUSDT"),
        ]
        self.orders = {"BTCUSDT": [{"orderId": "o1", "clientOrderId": "mbb-open-a"}, {"orderId": "o2", "clientOrderId": "mbb-tp-b"}],
                       "ETHUSDT": [{"orderId": "e1", "clientOrderId": "plah2-a"}, {"orderId": "e2", "clientOrderId": "plah2-b"}]}
        self.income = [{"symbol": "ETHUSDT", "incomeType": "REALIZED_PNL", "time": T0 + 2 * H, "income": "1"}]
        self.funding = [{"symbol": "ETHUSDT", "incomeType": "FUNDING_FEE", "time": self.now - H, "income": "-0.02"}]

    def test_backfill_then_incremental_and_resumable(self):
        store = FakeStore()
        client = FakeClient(self.fills, self.orders, self.income, self.funding)
        result = tj.sync_step(store, client, now_ms=self.now, max_calls=20)
        self.assertTrue(result["complete"], result)
        self.assertEqual(len(store.records), 2)
        reasons = sorted(r["closeReason"]["code"] for r in store.records.values())
        self.assertEqual(reasons, ["AUTO_HEDGE", "TAKE_PROFIT"])
        eth = store.symbols["ETHUSDT"]
        self.assertEqual(eth["lastTradeId"], 2)
        self.assertIn("SHORT", eth["cycles"])                         # 1 of 2 still open
        self.assertEqual(len(store.versions), 1)                      # settings captured once
        # nothing new: no new records, no new settings version, cursors respected
        client.calls.clear()
        again = tj.sync_step(store, client, now_ms=self.now + 60_000, max_calls=20)
        self.assertEqual(again["recordsWritten"], 0)
        self.assertEqual(len(store.versions), 1)
        self.assertNotIn(("trades", "BTCUSDT", 0), client.calls)
        # the open ETH SHORT closes later: picked up via income, cycle kept from the earlier step
        self.fills.append(fill(3, "e3", "SHORT", "BUY", 1, 8, self.now + 2 * H, pnl=2, symbol="ETHUSDT"))
        self.orders["ETHUSDT"].append({"orderId": "e3", "clientOrderId": "tm-manual-z"})
        self.income.append({"symbol": "ETHUSDT", "incomeType": "REALIZED_PNL", "time": self.now + 2 * H, "income": "2"})
        later = tj.sync_step(store, client, now_ms=self.now + 3 * H, max_calls=20)
        self.assertEqual(later["recordsWritten"], 1)
        last = max(store.records.values(), key=lambda r: r["closedAtMs"])
        self.assertEqual(last["closeType"], "FULL")
        self.assertEqual(last["closeReason"]["code"], "APP_CLOSE")
        self.assertEqual(last["cycle"]["closesBefore"], 1)
        self.assertEqual(last["cycle"]["entryReason"]["code"], "AUTO_HEDGE")

    def test_small_budget_spreads_backfill_over_steps(self):
        store = FakeStore()
        store.seed = {"BTCUSDT", "ETHUSDT"}
        client = FakeClient(self.fills, self.orders, self.income, self.funding)
        steps = []
        for i in range(6):
            steps.append(tj.sync_step(store, client, now_ms=self.now + i * 10_000, max_calls=4))
            if steps[-1]["complete"]:
                break
        self.assertFalse(steps[0]["complete"])
        self.assertTrue(steps[-1]["complete"])
        self.assertEqual(len(store.records), 2)
        self.assertLessEqual(max(s["asterCalls"] for s in steps), 4)

    def test_unreadable_symbol_does_not_block_and_is_reported(self):
        store = FakeStore()
        store.seed = {"BTCUSDT", "DEADUSDT"}
        client = FakeClient(self.fills, self.orders, [], [], broken={"DEADUSDT"})
        result = tj.sync_step(store, client, now_ms=self.now, max_calls=20)
        self.assertTrue(result["backfillComplete"])
        self.assertEqual(result["unreadableSymbols"], ["DEADUSDT"])
        # not retried within the hour
        client.calls.clear()
        tj.sync_step(store, client, now_ms=self.now + 60_000, max_calls=20)
        self.assertNotIn(("orders", "DEADUSDT"), client.calls)

    def test_rate_limit_stops_the_step_without_losing_state(self):
        store = FakeStore()

        class Limited(FakeClient):
            def income_history(self, **kwargs):
                raise RuntimeError("Aster REST tijdelijk geblokkeerd tot 2026-10-24T08:00:00Z: rate-limit")

        result = tj.sync_step(store, Limited(self.fills, self.orders), now_ms=self.now, max_calls=20)
        self.assertTrue(result["rateLimited"])
        self.assertFalse(result["complete"])
        self.assertEqual(store.records, {})
        self.assertIn("BTCUSDT", store.ctrl["dirtySymbols"])

    def test_context_and_pair_snapshot_are_attached(self):
        store = FakeStore(strategy={"settings": {}, "multiBbPositions": {
            "BTCUSDT|LONG": {"cycleId": "c1", "leverage": 5, "soldierRole": "ZONE_BASE", "cycleStartedAtMs": T0,
                             "lastBotFillPrice": 1, "updatedAtMs": 9}}})
        open_only = [f for f in self.fills if f["id"] == 1 and f["symbol"] == "BTCUSDT"]
        client = FakeClient(open_only, self.orders, [], [])
        tj.sync_step(store, client, now_ms=T0 + 60_000, max_calls=20)          # position open: context seen
        store.strategy = {"settings": {}, "multiBbPositions": {}}             # closed: row gone
        store.pairs["BTCUSDT"] = {"status": "CLOSED", "protectedSide": "LONG", "shortRecovery": {"stepsReached": 3}, "uid": "x"}
        close_time = T0 + H
        client.fills = self.fills
        tj.sync_step(store, FakeClient(self.fills, self.orders, [{"symbol": "BTCUSDT", "incomeType": "REALIZED_PNL", "time": close_time, "income": "10"}], []),
                     now_ms=close_time + 5 * 60_000, max_calls=20)
        record = next(iter(store.records.values()))
        self.assertEqual(record["context"]["soldierRole"], "ZONE_BASE")
        self.assertNotIn("lastBotFillPrice", record["context"])
        self.assertAlmostEqual(record["marginUsd"], 100 / 5)
        self.assertEqual(record["autoHedgePair"]["status"], "CLOSED")
        self.assertNotIn("uid", record["autoHedgePair"])


    def test_context_attached_on_first_read_of_a_symbol(self):
        store = FakeStore(strategy={"settings": {}, "multiBbPositions": {
            "ETHUSDT|SHORT": {"cycleId": "c", "leverage": 4, "soldierRole": "AUTO_HEDGE", "cycleStartedAtMs": T0}}})
        store.seed = {"ETHUSDT"}
        tj.sync_step(store, FakeClient(self.fills, self.orders, self.income, []), now_ms=self.now, max_calls=20)
        record = next(iter(store.records.values()))
        self.assertEqual(record["context"]["soldierRole"], "AUTO_HEDGE")
        self.assertAlmostEqual(record["marginUsd"], 10 / 4)


class SettingsAndExportTest(unittest.TestCase):
    def test_capture_only_on_change(self):
        store = FakeStore()
        self.assertTrue(tj.capture_settings(store, T0, reason="test"))
        self.assertFalse(tj.capture_settings(store, T0 + 1, reason="test"))
        store.auto = {"enabled": True, "thresholdUsd": 0.5}
        self.assertTrue(tj.capture_settings(store, T0 + 2, reason="test"))
        self.assertEqual(len(store.versions), 2)

    def test_timeline_prefers_newest_strategy_and_marks_completeness(self):
        history = [{"timestampMs": T0 - 10 * H, "version": 3, "newValue": {"longTakeProfitValue": 10}},
                   {"timestampMs": T0 + 5 * H, "version": 4, "newValue": {"longTakeProfitValue": 30}}]
        versions = [{"id": "v1", "effectiveFromMs": T0, "settings": {"strategy": {"longTakeProfitValue": 20},
                                                                    "autoHedge": {"thresholdUsd": 0.25, "enabled": True}}}]
        timeline = tj.build_settings_timeline(versions, history)
        before = tj.settings_at(timeline, T0 - H)
        self.assertFalse(before["complete"])
        self.assertIsNone(before["fullSnapshotId"])
        at = tj.settings_at(timeline, T0 + H)
        self.assertTrue(at["complete"])
        self.assertEqual(tj.key_settings(timeline, at, "LONG")["takeProfit"], 20)
        self.assertEqual(tj.key_settings(timeline, at, "LONG")["autoHedgeTriggerUsd"], 0.25)
        later = tj.settings_at(timeline, T0 + 6 * H)
        self.assertEqual(tj.key_settings(timeline, later, "LONG")["takeProfit"], 30)
        self.assertIsNone(tj.settings_at(timeline, T0 - 20 * H))

    def test_export_shape_funding_coverage_and_summary(self):
        rows = norm([fill(1, "o1", "LONG", "BUY", 1, 100, T0), fill(2, "o2", "LONG", "SELL", 1, 110, T0 + H, pnl=10),
                     fill(3, "o3", "LONG", "BUY", 1, 100, T0 + 3 * H), fill(4, "o4", "LONG", "SELL", 1, 95, T0 + 4 * H, pnl=-5)])
        records, _ = tj.process_fills("BTCUSDT", rows, {}, {"o2": "mbb-tp-a", "o4": "tm-manual-b"})
        funding = {"BTCUSDT": {str(T0 + 30 * 60_000): -0.1, str(T0 + 3 * H + 60_000): 0.2}}
        data = tj.build_export(records, [], funding, uid_hint="abcdef123456", generated_ms=T0 + 5 * H,
                               sync_state={"backfillComplete": True, "knownSymbols": ["BTCUSDT"], "fundingCoverageFromMs": T0 + 2 * H},
                               app_build="648")
        self.assertEqual(data["schema"], tj.JOURNAL_SCHEMA)
        self.assertEqual(data["summary"]["trades"], 2)
        self.assertEqual(data["summary"]["winningCloses"], 1)
        self.assertEqual(data["summary"]["byCloseReason"]["TAKE_PROFIT"]["count"], 1)
        newest, oldest = data["trades"]
        self.assertEqual(newest["closeReason"]["code"], "APP_CLOSE")
        self.assertAlmostEqual(newest["fundingSymbolUsd"], 0.2)
        self.assertIsNone(oldest["fundingSymbolUsd"])                  # opened before funding was recorded
        self.assertTrue(newest["closedAtLocal"].endswith("+02:00") or newest["closedAtLocal"].endswith("+01:00"))
        self.assertEqual(data["account"]["uidSuffix"], "123456")
        json.dumps(data)                                               # file-ready

    def test_list_row_matches_card_fields(self):
        records, _ = tj.process_fills("BTCUSDT", norm([fill(1, "o1", "LONG", "BUY", 1, 100, T0), fill(2, "o2", "LONG", "SELL", 1, 110, T0 + H, pnl=10)]), {}, {"o2": "mbb-tp-a"})
        row = tj.list_row(records[0])
        for field in ("symbol", "side", "closedAt", "openedAt", "realizedPnlUsd", "marginUsd", "closeReason"):
            self.assertIn(field, row)


class ContextTest(unittest.TestCase):
    def test_contexts_kept_while_unseen_then_expire(self):
        seen = tj.contexts_from_strategy({"multiBbPositions": {"BTCUSDT|LONG": {"cycleId": "a", "leverage": 3}}})
        merged = tj.merge_contexts({}, seen, T0)
        merged = tj.merge_contexts(merged, {}, T0 + H)
        self.assertIn("BTCUSDT|LONG", merged)
        merged = tj.merge_contexts(merged, {}, T0 + tj.CONTEXT_RETENTION_MS + H)
        self.assertNotIn("BTCUSDT|LONG", merged)

    def test_context_not_used_for_a_later_cycle(self):
        entry = {"context": {"cycleId": "a"}, "firstSeenMs": T0, "lastSeenMs": T0 + H}
        self.assertIsNone(tj.context_for_cycle(entry, {"openedAtMs": T0 + 5 * H}))
        self.assertEqual(tj.context_for_cycle(entry, {"openedAtMs": T0})["cycleId"], "a")


class ExtensionContractTest(unittest.TestCase):
    def test_extension_is_read_only_and_registered(self):
        root = Path(__file__).resolve().parent
        source = (root / "trade_journal_extension.py").read_text(encoding="utf-8")
        core = (root / "trade_journal.py").read_text(encoding="utf-8")
        for forbidden in ("submit_order", "cancel_order", "change_leverage", '"POST", "/fapi', "live_authorized=True"):
            self.assertNotIn(forbidden, source)
            self.assertNotIn(forbidden, core)
        self.assertIn("live_authorized=False", source)
        for route in ('@main.app.get("/v1/me/aster/trade-journal/recent")', '@main.app.post("/v1/me/aster/trade-journal/sync")',
                      '@main.app.get("/v1/me/aster/trade-journal/export")'):
            self.assertIn(route, source)
        self.assertIn("import trade_journal_extension", (root / "withdraw_app.py").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
