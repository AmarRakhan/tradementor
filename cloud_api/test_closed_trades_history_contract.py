import unittest
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
    def test_today_reuses_authoritative_full_close_summary_without_exchange(self):
        self.assertIn('summary.get("fullClosedTrades")', handler)
        self.assertIn('summary.get("reliable") is not True', handler)
        self.assertIn('_aster_closed_trades_cache.get(uid)', handler)
        self.assertIn('time.monotonic() - cached[0] < 120.0', handler)
        self.assertIn('summary.get("dayStartAt") != day_start.isoformat()', handler)
    def test_no_account_cross_reference(self):
        self.assertIn('collection.document(cursor).get()', handler)
        self.assertNotIn('user_reference(other_user)', handler)

if __name__ == "__main__":
    unittest.main()
