import unittest
import json
from pathlib import Path

# Architectural safety tests: the historical API must stay account-scoped,
# read-only, bounded and independent of live exchange requests.
source = (Path(__file__).resolve().parent / "main.py").read_text(encoding="utf-8")
start = source.index('@app.get("/v1/me/aster/closed-trades/history")')
end = source.index('@app.get("/v1/me/aster/closed-trades")', start)
handler = source[start:end]

class ClosedTradesHistoryContractTests(unittest.TestCase):
    def test_authenticated_scoped_source(self):
        self.assertIn('Depends(authenticated_user)', handler)
        self.assertIn('user_reference(user).collection("asterClosedTrades")', handler)
        self.assertNotIn('db.collection("asterClosedTrades")', handler)
    def test_bounded_cursor(self):
        self.assertIn('le=100', handler)
        self.assertIn('limit(limit + 1)', handler)
        self.assertIn('start_after(last_document)', handler)
        self.assertIn('nextCursor', handler)
    def test_read_only_no_exchange_scan(self):
        for unsafe in ('AsterV3Client(', 'user_trades(', 'income_history(', 'batch.commit(', '.set('):
            self.assertNotIn(unsafe, handler)
    def test_today_uses_verified_durable_account_ledger(self):
        self.assertIn('where("verifiedFullClose", "==", True)', handler)
        self.assertIn('day_start.astimezone(timezone.utc)', handler)
        self.assertIn('day_end.astimezone(timezone.utc)', handler)
        self.assertNotIn('_aster_closed_trades_cache.get(uid)', handler)
    def test_composite_index_declared_for_verified_close_history(self):
        indexes_file = Path(__file__).resolve().parent.parent / "cloud" / "firestore.indexes.json"
        definition = json.loads(indexes_file.read_text(encoding="utf-8"))
        required = [
            {"fieldPath": "verifiedFullClose", "order": "ASCENDING"},
            {"fieldPath": "closedAt", "order": "DESCENDING"},
        ]
        self.assertTrue(any(entry.get("collectionGroup") == "asterClosedTrades"
                            and entry.get("queryScope") == "COLLECTION"
                            and entry.get("fields") == required
                            for entry in definition.get("indexes", [])))
    def test_verified_close_writer_batches_duplicate_checks(self):
        writer = source[source.index("def _persist_verified_full_closes("):source.index('@app.get("/v1/me/aster/closed-trades/history")')]
        self.assertIn("db.get_all(", writer)
        self.assertIn("if snap.exists", writer)
        self.assertIn("inserted += len(missing)", writer)
        self.assertIn('row.get("fullyClosed") is not True', writer)
    def test_cursor_rejects_unverified_and_cross_day_records(self):
        self.assertIn('last_document.get("verifiedFullClose") is not True', handler)
        self.assertIn('Cursor buiten de geselecteerde dag', handler)
        self.assertIn('query.start_after(last_document)', handler)
    def test_no_account_cross_reference(self):
        self.assertIn('collection.document(cursor).get()', handler)
        self.assertNotIn('user_reference(other_user)', handler)

if __name__ == "__main__":
    unittest.main()
