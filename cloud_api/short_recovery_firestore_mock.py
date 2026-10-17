"""Strictly offline Firestore-like document transaction test seam. No Google imports."""
import copy
import threading
from decimal import Decimal
from short_recovery_ledger import Ledger, Allocation, Fill

class Conflict(Exception):pass

class MockFirestore:
    def __init__(self):
        self._lock=threading.Lock();self._docs={}
    def snapshot(self,key):
        with self._lock:
            version,doc=self._docs.get(key,(0,None))
            return version,copy.deepcopy(doc)
    def commit(self,key,version,doc):
        with self._lock:
            current=self._docs.get(key,(0,None))[0]
            if current!=version:raise Conflict('stale document version')
            self._docs[key]=(version+1,copy.deepcopy(doc))
    def restart(self):
        clone=MockFirestore()
        with self._lock:clone._docs=copy.deepcopy(self._docs)
        return clone

def encode(ledger):
    return {'account':ledger.account,'symbol':ledger.symbol,
            'allocations':[(a.zone_id,a.cycle_id,str(a.remaining)) for a in ledger.allocations],
            'seen':sorted(ledger.seen),
            'booked':[(z,c,str(q),str(p)) for z,c,q,p in ledger.booked]}

def decode(doc):
    if doc is None:raise ValueError('ledger not initialized')
    return Ledger(doc['account'],doc['symbol'],tuple(Allocation(z,c,Decimal(q)) for z,c,q in doc['allocations']),
                  frozenset(doc['seen']),tuple((z,c,Decimal(q),Decimal(p)) for z,c,q,p in doc['booked']))

def record_fill(db,ledger_key,fill,splits,retries=16):
    if ledger_key!=(fill.account,fill.symbol):raise ValueError('wrong document ownership')
    for _ in range(retries):
        version,doc=db.snapshot(ledger_key)
        ledger=decode(doc)
        if fill.execution_id in ledger.seen:return 'ALREADY_APPLIED'
        next_ledger=ledger.apply(fill,splits)
        try:db.commit(ledger_key,version,encode(next_ledger));return 'APPLIED'
        except Conflict:continue
    raise Conflict('transaction retries exhausted')
