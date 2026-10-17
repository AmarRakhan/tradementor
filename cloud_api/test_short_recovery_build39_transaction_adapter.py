"""Injected Firestore transaction contract tests. Local mock only; no cloud connection."""
import threading
import unittest
from decimal import Decimal as D
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_firestore_mock import MockFirestore,encode,decode,Conflict
from short_recovery_transaction_adapter import record_confirmed_fill
from short_recovery_gate import partition_reconciliation

class Ref:
    def __init__(self,db,key):self.db=db;self.key=key
    def get(self,transaction):return transaction.read(self)
class Snap:
    def __init__(self,doc):self.doc=doc;self.exists=doc is not None
    def to_dict(self):return self.doc
class Transaction:
    def __init__(self,db):self.db=db;self.reads={};self.writes={}
    def read(self,ref):
        version,doc=self.db.snapshot(ref.key);self.reads[ref.key]=version
        return Snap(doc)
    def set(self,ref,value):self.writes[ref.key]=value
    def commit(self):
        for key,doc in self.writes.items():self.db.commit(key,self.reads[key],doc)
class DB(MockFirestore):
    def transaction(self):return Transaction(self)
def transactional(func):
    def wrapped(txn):
        for _ in range(32):
            tx=txn.db.transaction()
            result=func(tx)
            try:tx.commit();return result
            except Conflict:continue
        raise Conflict('too many retries')
    return wrapped
class Contract(unittest.TestCase):
    def setUp(self):
        self.db=DB();self.key=('u','XRPUSDT');self.ref=Ref(self.db,self.key)
        self.db.commit(self.key,0,encode(Ledger('u','XRPUSDT',(Allocation('zone1','cycle1',D(100)),))))
    def apply(self,execution='fill1',quantity=25,verified=True,zone='zone1',account='u'):
        f=Fill(account,'XRPUSDT',execution,'order1',D(quantity),D(1),D('0.1'))
        return record_confirmed_fill(db=self.db,transactional=transactional,ref=self.ref,fill=f,
            splits=((zone,'cycle1',D(quantity)),),verified_owner=verified,account='u',symbol='XRPUSDT')
    def test_duplicate_and_restart(self):
        self.assertEqual(self.apply(),'APPLIED')
        self.assertEqual(self.apply(),'ALREADY_APPLIED')
        self.db._docs=self.db.restart()._docs
        self.assertEqual(self.apply(),'ALREADY_APPLIED')
        self.assertEqual(decode(self.db.snapshot(self.key)[1]).allocations[0].remaining,D(75))
    def test_unverified_owner_never_writes(self):
        v=self.db.snapshot(self.key)[0]
        self.assertEqual(self.apply(verified=False),'BLOCKED_OWNERSHIP')
        self.assertEqual(self.db.snapshot(self.key)[0],v)
    def test_cross_account_and_zone_rejected(self):
        self.assertEqual(self.apply(account='other'),'BLOCKED_OWNERSHIP')
        with self.assertRaises(ValueError):self.apply(zone='not-owned')
    def test_concurrent_workers_exactly_once(self):
        start=threading.Barrier(4);results=[];guard=threading.Lock()
        def worker():
            start.wait();v=self.apply()
            with guard:results.append(v)
        threads=[threading.Thread(target=worker) for _ in range(4)]
        for t in threads:t.start()
        for t in threads:t.join(5);self.assertFalse(t.is_alive())
        self.assertCountEqual(results,['APPLIED']+['ALREADY_APPLIED']*3)
    def test_partial_shadow_not_live_skip(self):
        self.apply()
        route=partition_reconciliation(settings={'enabled':True,'steps':4,'stepPct':'3'},
            protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),
            recovery_cycles={'XRPUSDT':{'ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}})
        self.assertIn('XRPUSDT',route['shadow_skip'])
        self.assertNotIn('XRPUSDT',route['legacy_skip'])
        self.assertEqual(route['orders'],0)
if __name__=='__main__':unittest.main()
