"""Close Profits 2.0 — the SAME scenarios as test_close_profits_2_0_integration, executed against a REAL Firestore
(emulator). Real here: Firestore transactions/documents/AlreadyExists; the route/helper/lease source from main.py.
Still mocked: the Aster exchange (ledger). NOT RUN in the authoring sandbox (no google-cloud-firestore / emulator).

    npx firebase emulators:exec --config <cfg> --only firestore --project close-profits-test-only \
      'PYTHONPATH=cloud_api python -m unittest -v cloud_api.test_close_profits_2_0_firestore_emulator'
(see tools/run_close_profits_2_1_integration.sh / tools/run_close_profits_2_0_integration.sh)"""
from __future__ import annotations

import os
import unittest
import uuid

import test_close_profits_2_0_integration as scenarios

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
        self.uid = "u-" + uuid.uuid4().hex[:12]                 # unique account per test: no cross-test state
        db = firestore.Client(project=os.environ.get("GCLOUD_PROJECT", "close-profits-test-only"))
        return db, (firestore, google_exceptions)


def _make(cls):
    return unittest.skipUnless(EMULATOR and HAVE_CLIENT, "needs FIRESTORE_EMULATOR_HOST and google-cloud-firestore")(
        type("Emulator" + cls.__name__, (EmulatorMixin, cls), {}))


EmulatorSequentialBulkTests = _make(scenarios.SequentialBulkTests)
EmulatorUnknownOutcomeTests = _make(scenarios.UnknownOutcomeTests)
EmulatorAutoHedgeConcurrencyTests = _make(scenarios.AutoHedgeConcurrencyTests)
EmulatorPlainShortBecomesAutoHedgeTests = _make(scenarios.PlainShortBecomesAutoHedgeTests)

if __name__ == "__main__":
    unittest.main()
