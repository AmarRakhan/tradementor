"""Build 619: verlopen instap-cooldowns worden opgeruimd vóór de eerste schrijfactie van een scan.

23-10-2026: asterStrategy2/{uid} liep over de Firestore-limiet van 1 MiB (1022 verlopen
cooldowns, ~285 kB) en de bot ging in DATA_HOLD. Deze test laadt alleen de helper uit
main.py (via de broncode), zonder main te importeren: geen netwerk, geen Firestore.
"""
import ast
import os
import unittest

SOURCE = os.path.join(os.path.dirname(__file__), "main.py")


def _load_helper():
    tree = ast.parse(open(SOURCE, encoding="utf-8").read())
    wanted = {"_prune_expired_entry_cooldowns", "ENTRY_COOLDOWN_KEEP_EXPIRED_MS"}
    nodes = [n for n in tree.body
             if (isinstance(n, ast.FunctionDef) and n.name in wanted)
             or (isinstance(n, ast.Assign) and any(getattr(t, "id", "") in wanted for t in n.targets))]
    assert len(nodes) == 2, "helper of constante ontbreekt in main.py"
    module = ast.Module(body=nodes, type_ignores=[])

    def safe_float(value):
        try:
            return float(value)
        except (TypeError, ValueError):
            return 0.0
    scope = {"Any": object, "safe_float": safe_float}
    exec(compile(module, SOURCE, "exec"), scope)
    return scope["_prune_expired_entry_cooldowns"], scope["ENTRY_COOLDOWN_KEEP_EXPIRED_MS"]


class FakeRef:
    def __init__(self, fail=False):
        self.updates = []
        self.fail = fail

    def update(self, data):
        if self.fail:
            raise RuntimeError("firestore down")
        self.updates.append(data)


NOW = 1_792_739_650_000


class EntryCooldownPruneTests(unittest.TestCase):
    def setUp(self):
        self.prune, self.keep_ms = _load_helper()

    def test_old_expired_removed_recent_and_active_kept(self):
        raw = {"entryCandidateCooldowns": {
            "OLD|LONG|OPEN": {"until": NOW - self.keep_ms - 1, "attempts": 8},
            "RECENT|LONG|OPEN": {"until": NOW - 60_000, "attempts": 3},
            "ACTIVE|SHORT|OPEN": {"until": NOW + 60_000, "attempts": 1},
            "BROKEN": "not-a-dict",
        }, "other": 1}
        ref = FakeRef()
        out = self.prune(ref, raw, NOW)
        self.assertEqual(set(out["entryCandidateCooldowns"]), {"RECENT|LONG|OPEN", "ACTIVE|SHORT|OPEN"})
        # update() (niet set merge) zodat de verlopen sleutels echt verdwijnen
        self.assertEqual(ref.updates, [{"entryCandidateCooldowns": out["entryCandidateCooldowns"]}])
        self.assertEqual(out["other"], 1)

    def test_nothing_to_prune_means_no_write(self):
        raw = {"entryCandidateCooldowns": {"A|LONG|OPEN": {"until": NOW + 1}}}
        ref = FakeRef()
        self.assertIs(self.prune(ref, raw, NOW), raw)
        self.assertEqual(ref.updates, [])

    def test_missing_field_means_no_write(self):
        ref = FakeRef()
        self.assertEqual(self.prune(ref, {}, NOW), {})
        self.assertEqual(ref.updates, [])

    def test_all_expired_leaves_empty_map(self):
        raw = {"entryCandidateCooldowns": {f"S{i}|LONG|OPEN": {"until": 1_787_740_993_472} for i in range(1022)}}
        ref = FakeRef()
        out = self.prune(ref, raw, NOW)
        self.assertEqual(out["entryCandidateCooldowns"], {})
        self.assertEqual(ref.updates, [{"entryCandidateCooldowns": {}}])

    def test_write_failure_is_harmless(self):
        raw = {"entryCandidateCooldowns": {"OLD|LONG|OPEN": {"until": 1}}}
        self.assertIs(self.prune(FakeRef(fail=True), raw, NOW), raw)

    def test_prune_runs_before_first_queue_write(self):
        src = open(SOURCE, encoding="utf-8").read()
        start = src.index("def _run_aster_strategy2_queue_scan(")
        body = src[start:start + 4000]
        self.assertLess(body.index("_prune_expired_entry_cooldowns("), body.index("ref.set("))

    def test_prune_runs_at_start_of_every_tick(self):
        src = open(SOURCE, encoding="utf-8").read()
        start = src.index("def _run_aster_strategy2_tick(")
        body = src[start:start + 6000]
        self.assertLess(body.index("_prune_expired_entry_cooldowns("), body.index("ref.set("))
        self.assertLess(body.index("_prune_expired_entry_cooldowns("), body.index("_sync_price_zone_seat_runtime("))


if __name__ == "__main__":
    unittest.main()
