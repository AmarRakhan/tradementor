import unittest
import threading
from concurrent.futures import ThreadPoolExecutor
import hashlib
from aster_execution import client_order_id
from aster_extreme_spike_filter import evaluate_spike, SpikeFilterRejected, normalize_mode,validate_settings,require_extreme_spike_entry,spike_event_key,claim_spike_entry_once
class SpikeTests(unittest.TestCase):
    def setUp(self):
        self.closes=[100.0 + (i%2)*2 for i in range(20)]
        self.base=dict(side="LONG",level="5-6",timeframe="15m",previous_closes=self.closes,candle_high=102,candle_low=95.5,candle_close_ms=10000,now_ms=11000,max_staleness_ms=2000)
    def test_sigma_band(self):
        out=evaluate_spike(**self.base)
        self.assertAlmostEqual(out.score,5.5)
        self.assertGreater(out.overshoot_pct,0)
    def test_long_short_symmetry(self):
        obj=dict(self.base,side="SHORT",candle_low=100,candle_high=106.5)
        self.assertAlmostEqual(evaluate_spike(**obj).score,5.5)
    def test_level_edges(self):
        for level,price in (("2-3",98.5),("3-4",97.5),("4-5",96.5),("6-7",94.5),("7+",93.5)):
            self.assertEqual(evaluate_spike(**dict(self.base,level=level,candle_low=price)).level,level)
    def test_fail_closed(self):
        cases=[dict(candle_close_ms=12000),dict(candle_close_ms=1),dict(previous_closes=[100]),dict(candle_low=0),dict(level="unknown"),dict(candle_low=99)]
        for change in cases:
            with self.subTest(change=change),self.assertRaises(SpikeFilterRejected):
                evaluate_spike(**dict(self.base,**change))
    def test_legacy_mode(self):
        self.assertEqual(normalize_mode(None,True),"BOLLINGER")
        self.assertEqual(normalize_mode(None,False),"OFF")
    def test_mutual_exclusion(self):
        with self.assertRaises(ValueError):
            validate_settings(mode="EXTREME_SPIKE",level="5-6",long_tf="1m",short_tf="15m",legacy_bb_enabled=True)
        with self.assertRaises(ValueError):
            validate_settings(mode="BOLLINGER",level="5-6",long_tf="1m",short_tf="15m",legacy_bb_enabled=False)
        validate_settings(mode="EXTREME_SPIKE",level="5-6",long_tf="1m",short_tf="4h",legacy_bb_enabled=False)

    def test_completed_candle_adapter_and_rejection(self):
        class Client:
            def klines(self, **kwargs):
                rows=[]
                for i in range(21):
                    price=100+(i%2)*2
                    lo=95.5 if i==20 else 100
                    rows.append([i*60000,price,102,lo,price,0,(i+1)*60000-1])
                rows.append([21*60000,101,102,90,101,0,22*60000-1])
                return rows
        c=Client()
        found=require_extreme_spike_entry(c,symbol="BTCUSDT",side="LONG",level="5-6",timeframe="1m",now_ms=21*60000+10)
        self.assertAlmostEqual(found.score,5.5)
        with self.assertRaises(SpikeFilterRejected):
            require_extreme_spike_entry(c,symbol="BTCUSDT",side="LONG",level="7+",timeframe="1m",now_ms=21*60000+10)
    def test_stable_spike_identity_across_scanner_ticks(self):
        first=spike_event_key(symbol="btcusdt",side="LONG",timeframe="1m",candle_close_ms=1000)
        self.assertEqual(first,spike_event_key(symbol="BTCUSDT",side="LONG",timeframe="1m",candle_close_ms=1000))
        self.assertNotEqual(first,spike_event_key(symbol="BTCUSDT",side="LONG",timeframe="1m",candle_close_ms=2000))
        self.assertNotEqual(first,spike_event_key(symbol="BTCUSDT",side="SHORT",timeframe="1m",candle_close_ms=1000))
        self.assertNotEqual(first,spike_event_key(symbol="BTCUSDT",side="LONG",timeframe="5m",candle_close_ms=1000))

    def test_order_id_stable_after_restart_and_tp(self):
        uid="test-account"
        event=spike_event_key(symbol="DOGEUSDT",side="LONG",timeframe="1m",candle_close_ms=150000)
        prefix=lambda tick: "mbb-open-"+hashlib.sha256((uid+event).encode()).hexdigest()[:12]
        order1=client_order_id(prefix(150100),"open","long")
        order2=client_order_id(prefix(170000),"open","long")
        self.assertEqual(order1,order2)
        self.assertLessEqual(len(order1),36)
        newer=spike_event_key(symbol="DOGEUSDT",side="LONG",timeframe="1m",candle_close_ms=210000)
        self.assertNotEqual(order1,client_order_id("mbb-open-"+hashlib.sha256((uid+newer).encode()).hexdigest()[:12],"open","long"))

    def test_atomic_spike_reservation_two_workers_and_restart(self):
        class AtomicCollection:
            def __init__(self):
                self.lock=threading.Lock()
                self.created=set()
                self.write_count=0
            def document(self,key):
                store=self
                class Doc:
                    def create(self,payload):
                        with store.lock:
                            if key in store.created:
                                raise RuntimeError("ALREADY_EXISTS")
                            store.created.add(key)
                            store.write_count+=1
                return Doc()
        class Account:
            def __init__(self):self.store=AtomicCollection()
            def collection(self,name):
                assert name=="spikeEntryClaims"
                return self.store
        acct=Account()
        args=dict(event_key="a"*32,symbol="DOGEUSDT",side="LONG",timeframe="1m",now_ms=10000)
        def attempt():
            try:
                claim_spike_entry_once(acct,**args)
                return "OK"
            except SpikeFilterRejected:
                return "BLOCKED"
        with ThreadPoolExecutor(max_workers=2) as pool:
            results=list(pool.map(lambda _:attempt(),range(2)))
        self.assertEqual(sorted(results),["BLOCKED","OK"])
        self.assertEqual(acct.store.write_count,1)
        self.assertEqual(attempt(),"BLOCKED")  # after process restart / TP
        self.assertEqual(acct.store.write_count,1)

    def test_claim_transport_uncertainty_is_fail_closed(self):
        class BrokenAccount:
            def collection(self,name):
                class Col:
                    def document(self,key):
                        class Doc:
                            def create(self,payload):
                                raise TimeoutError("uncertain write")
                        return Doc()
                return Col()
        with self.assertRaises(SpikeFilterRejected) as ctx:
            claim_spike_entry_once(BrokenAccount(),event_key="f"*32,symbol="BTCUSDT",side="LONG",timeframe="1m",now_ms=1000)
        self.assertEqual(ctx.exception.reason,"SPIKE_EVENT_CLAIM_FAILED_OR_REPLAY")

if __name__=="__main__": unittest.main()
