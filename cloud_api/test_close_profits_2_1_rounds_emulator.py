"""Close Profits 2.1 — the SAME round scenarios against a REAL Firestore (emulator).

Real here: Firestore transactions (optimistic, retried), documents, AlreadyExists, plus the round engine and the
individual close route source from main.py. Still mocked: Aster (ledger). Run via the Close Profits 2.1 CI workflow:

    npx firebase emulators:exec --only firestore --project close-profits-test-only \
      'cd cloud_api && python -m unittest -v test_close_profits_2_1_rounds_emulator'
"""
from __future__ import annotations

import os
import unittest
import uuid

import test_close_profits_2_1_rounds as scenarios

EMULATOR = bool(os.environ.get("FIRESTORE_EMULATOR_HOST"))
try:
    from google.api_core import exceptions as google_exceptions
    from google.cloud import firestore
    HAVE_CLIENT = True
except Exception:  # pragma: no cover
    HAVE_CLIENT = False


class EmulatorMixin:
    EMULATOR = True

    def make_store(self):
        host = os.environ.get("FIRESTORE_EMULATOR_HOST", "")
        if not host.startswith(("127.0.0.1:", "localhost:")) or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS"):
            raise RuntimeError("refusing to run: emulator on localhost only, and no service-account credentials in the env")
        self.uid = "u-" + uuid.uuid4().hex[:12]
        db = firestore.Client(project=os.environ.get("GCLOUD_PROJECT", "close-profits-test-only"))
        return db, (firestore, google_exceptions)


def _make(cls):
    return unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")(
        type("Emulator" + cls.__name__, (EmulatorMixin, cls), {}))


EmulatorCreateTests = _make(scenarios.CreateTests)
EmulatorResumeTests = _make(scenarios.ResumeTests)
EmulatorNetworkLossTests = _make(scenarios.NetworkLossTests)
EmulatorReconciliationTests = _make(scenarios.ReconciliationTests)
EmulatorRefusalTests = _make(scenarios.RefusalTests)
EmulatorRejectBeforeAcceptTests = _make(scenarios.RejectBeforeAcceptTests)

if __name__ == "__main__":
    unittest.main()
