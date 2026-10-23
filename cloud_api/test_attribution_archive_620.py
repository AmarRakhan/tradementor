"""Build 620: ordergeschiedenis compact houden zonder eigendomsbewijs of recente historie te verliezen."""
from datetime import datetime, timedelta, timezone
import unittest

import aster_attribution_archive as arch

NOW = datetime(2026, 10, 23, 8, 15, tzinfo=timezone.utc)


def row(symbol, side, action, days_ago, order_id):
    return {"orderId": str(order_id), "clientOrderId": f"s2-{order_id}", "symbol": symbol, "side": side,
            "action": action, "recordedAt": NOW - timedelta(days=days_ago), "strategyId": "aster-strategy-2"}


class FakeDoc:
    def __init__(self, store, doc_id):
        self.store, self.doc_id = store, doc_id

    def set(self, payload):
        self.store[self.doc_id] = payload


class FakeCollection:
    def __init__(self, store):
        self.store = store

    def document(self, doc_id):
        return FakeDoc(self.store, doc_id)


class FakeSnapshot:
    def __init__(self, data):
        self._data = data
        self.update_time = "t1"

    def to_dict(self):
        return dict(self._data)


class FakeClient:
    def write_option(self, **kwargs):
        return ("precondition", kwargs)


class FakeRef:
    def __init__(self, data=None, fail_archive=False, fail_update=False):
        self.data = data or {}
        self.archive = {}
        self.updates = []
        self.fail_archive = fail_archive
        self.fail_update = fail_update
        self._client = FakeClient()

    def collection(self, name):
        assert name == arch.ARCHIVE_COLLECTION
        if self.fail_archive:
            raise RuntimeError("archive down")
        return FakeCollection(self.archive)

    def get(self):
        return FakeSnapshot(self.data)

    def update(self, data, option=None):
        if self.fail_update:
            raise RuntimeError("precondition failed")
        self.updates.append((data, option))


def history():
    rows = []
    # BTC LONG: oude gesloten cycli + lopende cyclus (open sinds 20 dagen, geen close sindsdien)
    rows += [row("BTCUSDT", "LONG", "OPEN_LEG", 60, 1), row("BTCUSDT", "LONG", "FULL_TP", 55, 2),
             row("BTCUSDT", "LONG", "OPEN_LEG", 40, 3), row("BTCUSDT", "LONG", "TAKE_PROFIT_CLOSE", 30, 4),
             row("BTCUSDT", "LONG", "OPEN_LEG", 20, 5), row("BTCUSDT", "LONG", "ADD_DCA", 15, 6)]
    # ETH SHORT: alles oud, laatste actie een sluiting
    rows += [row("ETHUSDT", "SHORT", "OPEN_LEG", 50, 7), row("ETHUSDT", "SHORT", "FULL_TP", 45, 8)]
    # SOL LONG: recent
    rows += [row("SOLUSDT", "LONG", "OPEN_LEG", 2, 9)]
    return rows


class SplitTests(unittest.TestCase):
    def test_keeps_current_cycle_latest_and_recent(self):
        keep, archive = arch.split_rows(history(), now=NOW)
        kept_ids = [r["orderId"] for r in keep]
        # BTC: lopende cyclus vanaf de laatste sluiting (4) + 5, 6; ETH: alleen de laatste rij; SOL: recent
        self.assertEqual(kept_ids, ["4", "5", "6", "8", "9"])
        self.assertEqual(sorted(r["orderId"] for r in archive), ["1", "2", "3", "7"])

    def test_latest_row_per_key_always_kept_for_ownership(self):
        keep, _ = arch.split_rows(history(), now=NOW)
        latest = {}
        for r in history():
            latest[(r["symbol"], r["side"])] = r["orderId"]
        kept = {r["orderId"] for r in keep}
        self.assertTrue(set(latest.values()) <= kept)

    def test_row_without_time_is_never_archived(self):
        rows = [{"orderId": "x", "symbol": "A", "side": "LONG", "action": "OPEN_LEG", "recordedAt": "garbage"},
                row("A", "LONG", "FULL_TP", 30, "y"), row("A", "LONG", "OPEN_LEG", 1, "z")]
        keep, archive = arch.split_rows(rows, now=NOW)
        self.assertIn("x", [r["orderId"] for r in keep])

    def test_iso_string_times_are_understood(self):
        rows = [dict(r, recordedAt=r["recordedAt"].isoformat()) for r in history()]
        keep, archive = arch.split_rows(rows, now=NOW)
        self.assertEqual(sorted(r["orderId"] for r in archive), ["1", "2", "3", "7"])


class WriteTests(unittest.TestCase):
    def test_compact_for_write_archives_then_trims(self):
        ref = FakeRef()
        out = arch.compact_for_write(ref, history(), now=NOW)
        self.assertEqual([r["orderId"] for r in out], ["4", "5", "6", "8", "9"])
        self.assertEqual(len(ref.archive), 4)
        self.assertTrue(all("archivedAt" in v for v in ref.archive.values()))

    def test_archive_failure_keeps_everything(self):
        ref = FakeRef(fail_archive=True)
        rows = history()
        self.assertEqual(arch.compact_for_write(ref, rows, now=NOW), rows)

    def test_write_only_ref_keeps_old_behaviour(self):
        class WriteOnly:
            pass
        rows = history()
        self.assertEqual(arch.compact_for_write(WriteOnly(), rows, now=NOW), rows)

    def test_archive_ids_are_stable(self):
        r = history()[0]
        self.assertEqual(arch.archive_id(r), arch.archive_id(dict(r)))


class TickCompactTests(unittest.TestCase):
    def big_history(self):
        rows = []
        for i in range(120):
            rows.append(row(f"C{i}USDT", "LONG", "OPEN_LEG", 40, f"o{i}"))
            rows.append(row(f"C{i}USDT", "LONG", "FULL_TP", 35, f"c{i}"))
        return rows

    def test_small_backlog_does_nothing(self):
        ref = FakeRef({"orderAttributions": history()})
        self.assertEqual(arch.compact_document(ref, ref.data, now=NOW), 0)
        self.assertEqual(ref.updates, [])

    def test_large_backlog_compacts_with_precondition(self):
        data = {"orderAttributions": self.big_history()}
        ref = FakeRef(data)
        self.assertEqual(arch.compact_document(ref, data, now=NOW), 120)
        (payload, option), = ref.updates
        self.assertEqual(len(payload["orderAttributions"]), 120)
        self.assertEqual(option, ("precondition", {"last_update_time": "t1"}))
        self.assertEqual(len(ref.archive), 120)

    def test_failed_precondition_is_harmless(self):
        data = {"orderAttributions": self.big_history()}
        ref = FakeRef(data, fail_update=True)
        self.assertEqual(arch.compact_document(ref, data, now=NOW), 0)

    def test_archive_failure_means_no_update(self):
        data = {"orderAttributions": self.big_history()}
        ref = FakeRef(data, fail_archive=True)
        self.assertEqual(arch.compact_document(ref, data, now=NOW), 0)
        self.assertEqual(ref.updates, [])


class WiringTests(unittest.TestCase):
    def test_writers_and_tick_use_archive(self):
        import os
        here = os.path.dirname(__file__)
        main_src = open(os.path.join(here, "main.py"), encoding="utf-8").read()
        core_src = open(os.path.join(here, "aster_multi_bb_core.py"), encoding="utf-8").read()
        self.assertNotIn('ref.set({"orderAttributions":rows[-2000:]}', main_src)
        self.assertNotIn('ref.set({"orderAttributions": rows[-2000:]}', core_src)
        self.assertIn("compact_attributions_for_write(ref,rows)", main_src)
        self.assertIn("compact_for_write(ref, rows)", core_src)
        start = main_src.index("def _run_aster_strategy2_tick(")
        body = main_src[start:start + 12000]
        self.assertLess(body.index("compact_attribution_document("), body.index("_sync_price_zone_seat_runtime("))


if __name__ == "__main__":
    unittest.main()
