"""Offline Firestore-style serializable multi-document transaction emulator.
No Google imports, network, storage, or exchange execution.
"""
import copy
import threading
from short_recovery_firestore_mock import Conflict

class MultiDocDB:
    def __init__(self):
        self.lock=threading.RLock()
        self.docs={}
    def snapshot(self,key):
        with self.lock:
            v,data=self.docs.get(key,(0,None))
            return v,copy.deepcopy(data)
    def commit(self,key,expected,data):
        with self.lock:
            if self.docs.get(key,(0,None))[0]!=expected:raise Conflict('stale document')
            self.docs[key]=(expected+1,copy.deepcopy(data))
    def transaction(self):return Transaction(self)
    def restart(self):
        other=MultiDocDB()
        with self.lock:other.docs=copy.deepcopy(self.docs)
        return other

class Ref:
    def __init__(self,db,key):self.db=db;self.key=key
    def get(self,transaction):return transaction.read(self)

class Snapshot:
    def __init__(self,data):self.exists=data is not None;self.data=data
    def to_dict(self):return copy.deepcopy(self.data)

class Transaction:
    def __init__(self,db):self.db=db;self.reads={};self.writes={}
    def read(self,ref):
        if self.writes:raise ValueError('Firestore transaction requires all reads before writes')
        version,data=self.db.snapshot(ref.key)
        if ref.key in self.reads:raise ValueError('duplicate read not supported')
        self.reads[ref.key]=version
        return Snapshot(data)
    def set(self,ref,value):
        if ref.key not in self.reads:raise ValueError('must read before write')
        self.writes[ref.key]=copy.deepcopy(value)
    def commit(self):
        with self.db.lock:
            for key,version in self.reads.items():
                if self.db.docs.get(key,(0,None))[0]!=version:raise Conflict('read-set changed')
            for key,value in self.writes.items():
                version=self.db.docs.get(key,(0,None))[0]
                self.db.docs[key]=(version+1,copy.deepcopy(value))

def transactional(fn):
    def wrapper(tx):
        for _ in range(64):
            attempt=tx.db.transaction()
            outcome=fn(attempt)
            try:attempt.commit();return outcome
            except Conflict:continue
        raise Conflict('retry exhausted')
    return wrapper
