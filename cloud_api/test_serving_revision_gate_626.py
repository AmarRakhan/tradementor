"""Build 626: alleen de serverende Cloud Run-revisie doet achtergrond-botwerk."""
import os
import unittest

from serving_revision_gate import CACHE_SECONDS, STANDBY_HOLD_ON_ERROR_SECONDS, ServingGate

HERE = os.path.dirname(__file__)


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def gate(payloads, revision="api-rel-new", commit="new", clock=None):
    calls = []

    def fetch(url):
        calls.append(url)
        value = payloads.pop(0) if len(payloads) > 1 else payloads[0]
        if isinstance(value, Exception):
            raise value
        return value
    g = ServingGate(revision=revision, commit=commit, url="https://x/health", enabled=True,
                    fetch=fetch, clock=clock or Clock())
    return g, calls


class ServingGateTests(unittest.TestCase):
    def test_serving_revision_is_active(self):
        g, _ = gate([{"revision": "api-rel-new", "sourceCommit": "new"}])
        self.assertTrue(g.is_serving())

    def test_old_revision_goes_standby(self):
        g, _ = gate([{"revision": "api-rel-newer", "sourceCommit": "newer"}])
        self.assertFalse(g.is_serving())

    def test_candidate_before_promotion_goes_standby_even_if_serving_is_old_code(self):
        # Serverende revisie is nog code zonder "revision": vergelijk op commit.
        g, _ = gate([{"sourceCommit": "old"}])
        self.assertFalse(g.is_serving())

    def test_same_commit_without_revision_field_stays_active(self):
        g, _ = gate([{"sourceCommit": "new"}])
        self.assertTrue(g.is_serving())

    def test_check_failure_fails_open(self):
        g, _ = gate([OSError("netwerk")])
        self.assertTrue(g.is_serving())

    def test_unidentifiable_health_fails_open(self):
        g, _ = gate([{"status": "ready"}])
        self.assertTrue(g.is_serving())

    def test_recent_standby_is_held_during_short_outage(self):
        clock = Clock()
        g, _ = gate([{"revision": "api-rel-newer"}, OSError("netwerk"), OSError("netwerk")], clock=clock)
        self.assertFalse(g.is_serving())
        clock.t += CACHE_SECONDS + 1
        self.assertFalse(g.is_serving())  # kort daarna: stand-by aanhouden
        clock.t += STANDBY_HOLD_ON_ERROR_SECONDS + 1
        self.assertTrue(g.is_serving())   # lang onbereikbaar: weer doorwerken (fail-open)

    def test_result_is_cached(self):
        clock = Clock()
        g, calls = gate([{"revision": "api-rel-new"}], clock=clock)
        g.is_serving(); g.is_serving()
        self.assertEqual(len(calls), 1)
        clock.t += CACHE_SECONDS + 1
        g.is_serving()
        self.assertEqual(len(calls), 2)

    def test_rollback_reactivates_previous_revision(self):
        clock = Clock()
        g, _ = gate([{"revision": "api-rel-other"}, {"revision": "api-rel-new"}], clock=clock)
        self.assertFalse(g.is_serving())
        clock.t += CACHE_SECONDS + 1
        self.assertTrue(g.is_serving())

    def test_disabled_outside_cloud_run(self):
        g = ServingGate(revision="", commit="x", enabled=True, fetch=lambda url: {"revision": "other"})
        self.assertTrue(g.is_serving())
        g = ServingGate(revision="r1", commit="x", enabled=False, fetch=lambda url: {"revision": "other"})
        self.assertTrue(g.is_serving())


class WiringTests(unittest.TestCase):
    def read(self, name):
        return open(os.path.join(HERE, name), encoding="utf-8").read()

    def test_health_reports_revision(self):
        main = self.read("main.py")
        start = main.index('@app.get("/health")')
        self.assertIn('"revision": os.getenv("K_REVISION")', main[start:start + 800])

    def test_all_background_workers_are_gated(self):
        main = self.read("main.py")
        for marker in ("def _aster_periodic_scheduler_worker_loop", "def _run_aster_realtime_evaluation",
                       "def _run_spike_account_tick"):
            start = main.index(marker)
            self.assertIn("serving_gate_is_serving()", main[start:start + 700], marker)
        self.assertIn("stats=SpikeStats(persist=_serving_only(", main)
        self.assertIn("is_serving", self.read("aster_position_loss_auto_hedge_extension.py"))
        self.assertIn("is_serving", self.read("aster_portfolio_emergency_hedge.py"))
        self.assertIn("_recover_when_serving", self.read("aster_legacy_hedge_scale_extension.py"))


if __name__ == "__main__":
    unittest.main()
