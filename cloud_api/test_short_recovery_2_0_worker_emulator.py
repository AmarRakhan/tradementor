"""SHORT Recovery 2.0 — the SAME worker scenarios against a REAL Firestore (emulator): real lease transactions,
real documents. Still mocked: Aster (ledger)."""
from __future__ import annotations

import unittest

import test_short_recovery_2_0_worker as scenarios
from test_rehedge_all_1_0_emulator import EMULATOR, HAVE_CLIENT, EmulatorMixin


def _make(cls):
    return unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")(
        type("Emulator" + cls.__name__, (EmulatorMixin, cls), {}))


EmulatorLiveLadder = _make(scenarios.LiveLadder)
EmulatorLiveReopenNinety = _make(scenarios.LiveReopenNinety)
EmulatorJointExit = _make(scenarios.JointExit)
EmulatorShadow = _make(scenarios.Shadow)

if __name__ == "__main__":
    unittest.main()
