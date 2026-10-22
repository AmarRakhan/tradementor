"""Firestore emulator integration gate for Extreme Spike reservation.

Run ONLY against local Firestore emulator. No production credentials are used.
FIRESTORE_EMULATOR_HOST=127.0.0.1:8080 python -m unittest test_aster_spike_firestore_emulator
"""
import os
import unittest
import uuid
from concurrent.futures import ThreadPoolExecutor

from aster_extreme_spike_filter import claim_spike_entry_once, SpikeFilterRejected


@unittest.skipUnless(os.getenv("FIRESTORE_EMULATOR_HOST"), "Requires isolated Firestore emulator")
class FirestoreSpikeIntegration(unittest.TestCase):
    def test_atomic_duplicate_and_account_isolation(self):
        from google.cloud import firestore
        # Emulator only: refuse execution without explicit local endpoint.
        host = os.environ["FIRESTORE_EMULATOR_HOST"]
        if not (host.startswith("127.0.0.1:") or host.startswith("localhost:")):
            self.fail("Refusing to run outside loopback Firestore emulator")
        client = firestore.Client(project="spike-release-test-only")
        run_id = "test-" + uuid.uuid4().hex
        root = client.collection("spikeSafetyIntegration").document(run_id)
        accounts = root.collection("accounts")
        first = accounts.document("a")
        second = accounts.document("b")
        key = "c" * 32
        def reserve(ref):
            try:
                claim_spike_entry_once(ref,event_key=key,symbol="BTCUSDT",side="LONG",
                                       timeframe="1m",now_ms=1000)
                return "OK"
            except SpikeFilterRejected:
                return "BLOCKED"
        try:
            with ThreadPoolExecutor(max_workers=2) as pool:
                results=list(pool.map(reserve,[first,first]))
            self.assertEqual(sorted(results),["BLOCKED","OK"])
            self.assertEqual(reserve(second),"OK")
            self.assertEqual(reserve(first),"BLOCKED")
            self.assertTrue(first.collection("spikeEntryClaims").document(key).get().exists)
            self.assertTrue(second.collection("spikeEntryClaims").document(key).get().exists)
        finally:
            # Deletes only test-path documents in the disposable emulator.
            for ref in [first,second]:
                ref.collection("spikeEntryClaims").document(key).delete()


if __name__ == "__main__":
    unittest.main()
