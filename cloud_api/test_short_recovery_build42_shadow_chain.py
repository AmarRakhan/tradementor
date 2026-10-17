"""Build42 offline persisted fill -> owner -> actual Auto Hedge SHADOW integration."""
import unittest
import threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_firestore_mock import encode,decode
from short_recovery_ledger import Ledger,Allocation,Fill
from short_recovery_transaction_adapter import record_confirmed_fill_owned
from short_recovery_gate import partition_reconciliation
from aster_position_loss_auto_hedge import reconcile_auto_hedge

class NoExchange:
 def submit_order(self,*a,**k):raise AssertionError('LIVE ORDER FORBIDDEN')
 def position_risk(self):raise AssertionError('EXCHANGE READ FORBIDDEN')
 def open_orders(self):raise AssertionError('EXCHANGE READ FORBIDDEN')

class Chain(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.lk=('u','XRPUSDT','ledger');self.ok=('u','XRPUSDT','owner')
  self.attach()
  self.db.commit(self.lk,0,encode(Ledger('u','XRPUSDT',(Allocation('z','c',D(100)),))))
  self.owner={'account':'u','symbol':'XRPUSDT','cycleId':'c','ownerSide':'SHORT','cycleConfirmed':True,'ownershipVerified':True,'state':'PARTIAL'}
  self.db.commit(self.ok,0,self.owner)
 def attach(self):self.lr=Ref(self.db,self.lk);self.oref=Ref(self.db,self.ok)
 def fill(self,id='e',qty=25):
  return record_confirmed_fill_owned(db=self.db,transactional=transactional,ledger_ref=self.lr,ownership_ref=self.oref,fill=Fill('u','XRPUSDT',id,'order-'+id,D(qty),D(0),D(0)),splits=(('z','c',D(qty)),),account='u',symbol='XRPUSDT',cycle_id='c')
 def preview(self):
  owner=self.db.snapshot(self.ok)[1];ledger_doc=self.db.snapshot(self.lk)[1]
  verified=bool(owner and ledger_doc and owner.get('account')=='u' and owner.get('symbol')=='XRPUSDT' and owner.get('cycleId')=='c' and owner.get('ownershipVerified') is True and owner.get('cycleConfirmed') is True and owner.get('ownerSide')=='SHORT' and owner.get('state') in {'PARTIAL','FINAL_PENDING'})
  ledger=decode(ledger_doc)
  remaining=ledger.allocations[0].remaining
  states={'XRPUSDT':owner} if verified and remaining<D(100) else {}
  routing=partition_reconciliation(settings={'enabled':True,'steps':4,'stepPct':'3'},protected_sides={'XRPUSDT':'LONG'},existing_skip_symbols=set(),recovery_cycles=states)
  rows=[{'symbol':'XRPUSDT','positionSide':'LONG','positionAmt':'100','unRealizedProfit':'-10','markPrice':'1.8'}, {'symbol':'XRPUSDT','positionSide':'SHORT','positionAmt':str(-remaining),'unRealizedProfit':'10','markPrice':'1.8'}]
  result=reconcile_auto_hedge(client=NoExchange(),uid='u',threshold_usd=1,execute=False,protected_sides={'XRPUSDT':'LONG'},positions=rows,open_orders=[],recovery_shadow_skip_symbols=routing['shadow_skip'])
  return result,routing
 def test_confirmed_partial_suppresses_topup(self):
  self.assertEqual(self.fill(),'APPLIED')
  result,routing=self.preview()
  self.assertIn('XRPUSDT',routing['shadow_skip'])
  self.assertNotIn('XRPUSDT',[x['symbol'] for x in result['actions']]);self.assertEqual(result['ordersSent'],0)
 def test_restart_duplicate_reentry(self):
  self.assertEqual(self.fill(),'APPLIED');self.db=self.db.restart();self.attach()
  self.assertEqual(self.fill(),'ALREADY_APPLIED')
  self.assertNotIn('XRPUSDT',[a['symbol'] for a in self.preview()[0]['actions']])
 def test_concurrent_workers_single_booking(self):
  gate=threading.Barrier(4);out=[];lock=threading.Lock()
  def run():
   gate.wait();result=self.fill()
   with lock:out.append(result)
  ts=[threading.Thread(target=run) for _ in range(4)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['APPLIED']+['ALREADY_APPLIED']*3)
  self.assertNotIn('XRPUSDT',[a['symbol'] for a in self.preview()[0]['actions']])
 def test_revoked_owner_never_produces_trusted_skip(self):
  self.fill();version,owner=self.db.snapshot(self.ok);owner['ownershipVerified']=False;self.db.commit(self.ok,version,owner)
  result,routing=self.preview()
  self.assertNotIn('XRPUSDT',routing['shadow_skip'])
  self.assertIn('XRPUSDT',[a['symbol'] for a in result['actions']])
  self.assertEqual(result['ordersSent'],0)
 def test_missing_owner_blocks_new_booking(self):
  version,owner=self.db.snapshot(self.ok);self.db.commit(self.ok,version,{})
  self.assertEqual(self.fill(),'BLOCKED_OWNERSHIP')
if __name__=='__main__':unittest.main()
