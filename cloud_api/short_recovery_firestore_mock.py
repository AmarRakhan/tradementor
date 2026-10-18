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
    """Firestore-valid documents: arrays of maps, never nested arrays."""
    return {'account':ledger.account,'symbol':ledger.symbol,
            'allocations':[{'zoneId':a.zone_id,'cycleId':a.cycle_id,'remaining':str(a.remaining)} for a in ledger.allocations],
            'seen':sorted(ledger.seen),
            'booked':[{'zoneId':z,'cycleId':c,'quantity':str(q),'netPnl':str(p)} for z,c,q,p in ledger.booked]}

def decode(doc):
    if doc is None:raise ValueError('ledger not initialized')
    # Existing mock fixtures with legacy array records remain readable.
    alloc=tuple(Allocation(row['zoneId'],row['cycleId'],Decimal(row['remaining'])) if isinstance(row,dict)
                else Allocation(row[0],row[1],Decimal(row[2])) for row in doc['allocations'])
    booked=tuple((row['zoneId'],row['cycleId'],Decimal(row['quantity']),Decimal(row['netPnl'])) if isinstance(row,dict)
                 else (row[0],row[1],Decimal(row[2]),Decimal(row[3])) for row in doc['booked'])
    return Ledger(doc['account'],doc['symbol'],alloc,frozenset(doc['seen']),booked)

def record_fill(db,ledger_key,fill,splits,retries=16,*,authorization_mode="LEGACY_MOCK_TEST"):
    if authorization_mode != 'LEGACY_MOCK_TEST':return 'BLOCKED_INDEPENDENT_EXECUTION_AUTHORIZATION'
    if ledger_key!=(fill.account,fill.symbol):raise ValueError('wrong document ownership')
    for _ in range(retries):
        version,doc=db.snapshot(ledger_key)
        ledger=decode(doc)
        if fill.execution_id in ledger.seen:return 'ALREADY_APPLIED'
        next_ledger=ledger.apply(fill,splits)
        try:db.commit(ledger_key,version,encode(next_ledger));return 'APPLIED'
        except Conflict:continue
    raise Conflict('transaction retries exhausted')
