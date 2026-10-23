"""SHORT Recovery 2.0 — the SAME worker scenarios against a REAL Firestore (emulator): real lease transactions,
real documents. Still mocked: Aster (ledger)."""
from __future__ import annotations

import unittest

import test_hedge_grid_634 as grid
import test_short_recovery_2_0_worker as scenarios
from test_rehedge_all_1_0_emulator import EMULATOR, HAVE_CLIENT, EmulatorMixin


def _make(cls):
    return unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")(
        type("Emulator" + cls.__name__, (EmulatorMixin, cls), {}))


EmulatorLiveLadder = _make(scenarios.LiveLadder)
EmulatorJointExit = _make(scenarios.JointExit)
EmulatorShadow = _make(scenarios.Shadow)
EmulatorUncertainFills = _make(scenarios.UncertainFills)
EmulatorGridWorker = _make(grid.GridWorker)          # build 634: grid on the REAL Firestore emulator

if __name__ == "__main__":
    unittest.main()
