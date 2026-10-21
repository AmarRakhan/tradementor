"""Close Profits 2.1 — real Firestore-emulator checks (lease transactions + ownership reads).

NOT RUN in the authoring sandbox (no google-cloud-firestore / emulator reachable). Runs only when
FIRESTORE_EMULATOR_HOST is set and google-cloud-firestore is installed; otherwise every test SKIPs.
It extracts the REAL lease and ownership-read functions from main.py (AST) and binds them to a real
Firestore client pointed at the emulator. Aster is never contacted; no orders exist here.

    npx firebase emulators:exec --config <cfg> --only firestore --project close-profits-test-only \
      'PYTHONPATH=cloud_api python -m unittest -v cloud_api.test_close_profits_2_1_firestore_emulator'
"""
from __future__ import annotations

import ast
import os
import secrets
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
try:
    from google.cloud import firestore
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False

MAIN_SRC = (Path(__file__).with_name("main.py")).read_text()
WANTED = {"_acquire_aster_account_coordination", "_release_aster_account_coordination",
          "_renew_aster_account_coordination", "_aster_account_coordination_held",
          "aster_account_coordination_reference", "_read_bulk_ownership_globals", "_bulk_reason_from_globals",
          "_position_loss_auto_hedge_pair_ref", "_position_loss_auto_hedge_pair", "user_reference",
          "aster_strategy2_reference", "aster_sniper_reference"}


def load_real_functions(db):
    tree = ast.parse(MAIN_SRC)
    nodes = [n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name in WANTED]
    nodes += [n for n in tree.body if isinstance(n, ast.Assign)
              and any(getattr(t, "id", "") == "ACCOUNT_COORDINATION_LEASE_SECONDS" for t in n.targets)]
    assert len(nodes) == len(WANTED) + 1, sorted(getattr(n, "name", "assign") for n in nodes)
    for node in nodes:
        if isinstance(node, ast.FunctionDef):
            node.decorator_list = []
    module = ast.Module(body=nodes, type_ignores=[])
    ast.fix_missing_locations(module)
    from manual_profit_close_guard import BulkProtectionUnreliable, OwnershipContext, bulk_profit_close_block_reason
    ns = {
        "db": db, "firestore": firestore, "datetime": datetime, "timezone": timezone, "timedelta": timedelta,
        "python_secrets": secrets, "Any": object, "BulkProtectionUnreliable": BulkProtectionUnreliable,
        "OwnershipContext": OwnershipContext, "bulk_profit_close_block_reason": bulk_profit_close_block_reason,
        "auto_hedge_symbol_managed_strict": lambda **kw: False,   # Auto Hedge status is covered by its own tests
        "safe_float": lambda v, d=0.0: float(v) if v not in (None, "") else d,
    }
    exec(compile(module, "main.py::emulator", "exec"), ns)
    return SimpleNamespace(**ns)


@unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")
class EmulatorLeaseTests(unittest.TestCase):
    def setUp(self):
        self.db = firestore.Client(project=os.environ.get("GCLOUD_PROJECT", "close-profits-test-only"))
        self.fn = load_real_functions(self.db)
        self.uid = "u-" + uuid.uuid4().hex[:10]

    def test_sixteen_concurrent_acquirers_exactly_one_winner(self):
        results, barrier = [], threading.Barrier(16)

        def worker(i):
            barrier.wait()
            results.append(self.fn._acquire_aster_account_coordination(self.uid, f"W{i}", "TEST"))
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(16)]
        [t.start() for t in threads]
        [t.join() for t in threads]
        self.assertEqual(len([r for r in results if r]), 1)

    def test_renew_release_and_expiry_fencing(self):
        token = self.fn._acquire_aster_account_coordination(self.uid, "MANUAL_BULK_PROFIT_CLOSE", "TEST")
        self.assertTrue(token)
        self.assertIsNone(self.fn._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "TEST"))
        self.assertTrue(self.fn._renew_aster_account_coordination(self.uid, token))
        self.assertTrue(self.fn._aster_account_coordination_held(self.uid, token))
        # force expiry directly in Firestore
        self.fn.aster_account_coordination_reference(self.uid).set(
            {"lease": {"until": datetime.now(timezone.utc) - timedelta(seconds=1)}}, merge=True)
        self.assertFalse(self.fn._renew_aster_account_coordination(self.uid, token))     # never resurrects
        self.assertFalse(self.fn._aster_account_coordination_held(self.uid, token))
        other = self.fn._acquire_aster_account_coordination(self.uid, "AUTO_HEDGE", "TEST")
        self.assertTrue(other)
        self.fn._release_aster_account_coordination(self.uid, token)                     # stale release is a no-op
        self.assertTrue(self.fn._aster_account_coordination_held(self.uid, other))
        self.fn._release_aster_account_coordination(self.uid, other)
        self.assertFalse(self.fn._aster_account_coordination_held(self.uid, other))


@unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")
class EmulatorOwnershipReadTests(unittest.TestCase):
    def setUp(self):
        self.db = firestore.Client(project=os.environ.get("GCLOUD_PROJECT", "close-profits-test-only"))
        self.fn = load_real_functions(self.db)
        self.uid = "u-" + uuid.uuid4().hex[:10]
        self.user = {"uid": self.uid}
        self.rows = [{"symbol": "BTCUSDT", "positionSide": "SHORT", "positionAmt": "-8"}]

    def reason(self, symbol="BTCUSDT", rows=None):
        snaps = self.fn._read_bulk_ownership_globals(self.user, self.uid)
        return self.fn._bulk_reason_from_globals(self.uid, symbol, "SHORT", snaps, rows or self.rows)

    def test_nothing_configured_allows_plain_short(self):
        self.assertIsNone(self.reason())

    def test_each_owner_document_blocks(self):
        d = self.db
        d.collection("users").document(self.uid).collection("asterDynamicHedge").document("control").set({"enabled": True})
        self.assertIn("Dynamic Hedge", self.reason())
        d.collection("users").document(self.uid).collection("asterDynamicHedge").document("control").set({"enabled": False})
        d.collection("aster_portfolio_emergency_hedges").document(self.uid).set({"status": "LOCKED"})
        self.assertIn("Noodhedge", self.reason())
        d.collection("aster_portfolio_emergency_hedges").document(self.uid).set({"status": "OFF"})
        d.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document("BTCUSDT").set({"state": "PARTIAL"})
        self.assertIn("Short Recovery 2.0", self.reason())
        d.collection("asterPositionLossAutoHedge").document(self.uid).collection("pairs").document("BTCUSDT").delete()
        d.collection("asterSniper").document(self.uid).set({"activeTrades": [{"symbol": "BTCUSDT"}]})
        self.assertIn("Sniper", self.reason())
        d.collection("asterSniper").document(self.uid).delete()
        d.collection("asterStrategy2").document(self.uid).set({"ownedLegs": [], "pendingReopens": [{"symbol": "BTCUSDT"}]})
        self.assertIn("order in uitvoering", self.reason())

    def test_recovery_plan_blocks_hedged_short_only(self):
        self.db.collection("asterPositionLossAutoHedge").document(self.uid).set({"shortRecoveryPlan": {"enabled": True}})
        self.assertIsNone(self.reason())
        hedged = self.rows + [{"symbol": "BTCUSDT", "positionSide": "LONG", "positionAmt": "8"}]
        self.assertIn("Short Recovery 2.0", self.reason(rows=hedged))

    def test_guard_reads_do_not_write(self):
        before = {c.id for c in self.db.collections()}
        self.reason()
        self.assertFalse(self.db.collection("asterPositionLossAutoHedge").document(self.uid).get().exists)
        self.assertFalse(self.db.collection("aster_portfolio_emergency_hedges").document(self.uid).get().exists)
        self.assertTrue({c.id for c in self.db.collections()} >= before)


if __name__ == "__main__":
    unittest.main()
