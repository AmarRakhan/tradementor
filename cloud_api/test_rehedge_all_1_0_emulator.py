"""Re-Hedge All 1.0 — the SAME scenarios against a REAL Firestore (emulator): real transactions for the account
lease, real documents. Still mocked: Aster (ledger). Run via the Re-Hedge All 1.0 CI workflow:

    npx firebase emulators:exec --only firestore --project rehedge-all-test-only \
      'cd cloud_api && python -m unittest -v test_rehedge_all_1_0_emulator'
"""
from __future__ import annotations

import os
import unittest
import uuid

import test_rehedge_all_1_0 as scenarios

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
        db = firestore.Client(project=os.environ.get("GCLOUD_PROJECT", "rehedge-all-test-only"))
        return db, (firestore, google_exceptions)


def _make(cls):
    return unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")(
        type("Emulator" + cls.__name__, (EmulatorMixin, cls), {}))


EmulatorSizingTests = _make(scenarios.SizingTests)
EmulatorSelectionTests = _make(scenarios.SelectionTests)
EmulatorExecutionSafetyTests = _make(scenarios.ExecutionSafetyTests)

if __name__ == "__main__":
    unittest.main()
