import unittest
from datetime import datetime, timezone
from manual_profit_close_snapshot import make_profit_close_snapshot

class SnapshotTests(unittest.TestCase):
    def test_export_contains_both_legs_and_timestamp(self):
        rows=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"5","markPrice":"10","unRealizedProfit":"-1"},{"symbol":"BTCUSDT","positionSide":"SHORT","positionAmt":"5","markPrice":"10","unRealizedProfit":"2"}]
        out=make_profit_close_snapshot(rows,25,{"BTCUSDT":True},datetime(2026,10,20,15,0,tzinfo=timezone.utc))
        self.assertEqual(len(out["rows"]),2)
        self.assertIn("BTCUSDT,SHORT,5,10,2,verified,25",out["csv"])
        self.assertIn("2026-10-20T15:00:00+00:00",out["json"])
    def test_invalid_percentage_rejected(self):
        with self.assertRaises(ValueError): make_profit_close_snapshot([],33)
    def test_snapshot_never_mutates_source(self):
        rows=[{"symbol":"XRPUSDT","positionSide":"SHORT","positionAmt":"2"}]
        make_profit_close_snapshot(rows,50)
        self.assertNotIn("capturedAtUtc",rows[0])
if __name__=="__main__": unittest.main()
