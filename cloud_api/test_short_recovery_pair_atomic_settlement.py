import unittest,threading
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_ledger import Ledger,Allocation
from short_recovery_firestore_mock import encode,decode
from short_recovery_order_resolution_shadow import reconcile_pair_close
class PairAtomic(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.bind();self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False});self.put('pair',{'account':'u','symbol':'XRPUSDT','cycle':'c','state':'OPEN','fundingCycleVerified':True})
  for s in ('LONG','SHORT'):
   self.put(s+'claim',{'account':'u','symbol':'XRPUSDT','cycle':'c','positionSide':s,'intentId':s+'-intent','orderId':s+'-order','state':'ACKED'})
   self.put(s+'ledger',encode(Ledger('u','XRPUSDT',(Allocation(s,'c',D(100 if s=='LONG' else 75)),))))
 def bind(self):self.refs={k:Ref(self.db,('u','XRPUSDT',k)) for k in ('control','pair','LONGclaim','SHORTclaim','LONGledger','SHORTledger')}
 def put(self,k,data):self.db.commit(self.refs[k].key,self.db.snapshot(self.refs[k].key)[0],data)
 def snapshot(self,k):return self.db.snapshot(self.refs[k].key)[1]
 def row(self,side,qty=None,status='FILLED'):
  qty=D(qty if qty is not None else (100 if side=='LONG' else 75))
  return {'symbol':'XRPUSDT','positionSide':side,'orderId':side+'-order','readbackVerified':True,'fillsComplete':True,'incomeHistoryComplete':True,'terminalVerified':status=='FILLED','status':status,'executedQty':str(qty),'fills':[{'orderId':side+'-order','executionId':side+'-exec','quantity':str(qty),'realizedPnl':'1','commission':'.1','funding':'-.05','financialVerified':True,'fundingOwnershipVerified':True}]}
 def run_pair(self,rows=None):
  rows=rows or {s:self.row(s) for s in ('LONG','SHORT')}
  return reconcile_pair_close(db=self.db,transactional=transactional,claim_refs={s:self.refs[s+'claim'] for s in ('LONG','SHORT')},ledger_refs={s:self.refs[s+'ledger'] for s in ('LONG','SHORT')},control_ref=self.refs['control'],pair_ref=self.refs['pair'],account='u',symbol='XRPUSDT',cycle='c',readbacks=rows)
 def test_complete_two_sided_atomic_settlement(self):
  self.assertEqual(self.run_pair(),'PAIR_CLOSED_VERIFIED')
  self.assertEqual(self.snapshot('pair')['state'],'CLOSED')
  for s in ('LONG','SHORT'):
   self.assertEqual(self.snapshot(s+'claim')['state'],'CLOSED')
   self.assertEqual(decode(self.snapshot(s+'ledger')).allocations[0].remaining,0)
  self.assertEqual(self.run_pair(),'ALREADY_PAIR_CLOSED')
 def test_partial_side_books_only_confirmed_and_retains_claim(self):
  rows={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(rows),'PAIR_RECONCILE_REQUIRED')
  self.assertEqual(self.snapshot('pair')['state'],'RECONCILE_REQUIRED')
  self.assertEqual(decode(self.snapshot('SHORTledger')).allocations[0].remaining,D(50))
  self.assertEqual(self.snapshot('SHORTclaim')['state'],'UNKNOWN')
  self.assertEqual(self.run_pair(rows),'PAIR_RECONCILE_REQUIRED')
  self.assertEqual(decode(self.snapshot('SHORTledger')).allocations[0].remaining,D(50))
 def test_missing_funding_never_books(self):
  rows={'LONG':self.row('LONG'),'SHORT':self.row('SHORT')};del rows['SHORT']['fills'][0]['funding']
  self.assertEqual(self.run_pair(rows),'BLOCKED_FINANCIAL_EVIDENCE')
  self.assertEqual(decode(self.snapshot('LONGledger')).allocations[0].remaining,D(100))
 def test_stop_records_fills_but_never_marks_pair_closed(self):
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.run_pair(),'PAIR_RECONCILE_REQUIRED')
  self.assertEqual(self.snapshot('pair')['state'],'RECONCILE_REQUIRED')
 def test_unknown_restart_and_concurrency_deduplicate(self):
  rows={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='UNKNOWN')}
  self.db=self.db.restart();self.bind();barrier=threading.Barrier(5);result=[];lock=threading.Lock()
  def worker():
   barrier.wait();v=self.run_pair(rows)
   with lock:result.append(v)
  ts=[threading.Thread(target=worker) for _ in range(5)]
  for t in ts:t.start()
  for t in ts:t.join(5);self.assertFalse(t.is_alive())
  self.assertEqual(result,['PAIR_RECONCILE_REQUIRED']*5)
  self.assertEqual(decode(self.snapshot('SHORTledger')).allocations[0].remaining,D(50))
 def test_funding_cycle_gate_blocks_pair_close(self):
  p=self.snapshot('pair');p['fundingCycleVerified']=False;self.put('pair',p)
  self.assertEqual(self.run_pair(),'PAIR_RECONCILE_REQUIRED')
  self.assertEqual(self.snapshot('pair')['state'],'RECONCILE_REQUIRED')

class ReplayedFillQuantityConflict(PairAtomic):
 def test_modified_same_execution_id_cannot_inflate_confirmed_qty(self):
  rows={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(rows),'PAIR_RECONCILE_REQUIRED')
  before=self.snapshot('SHORTledger')
  replay={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',50,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(replay),'BLOCKED_EXECUTION_INCOMPLETE')
  self.assertEqual(self.snapshot('SHORTledger'),before)
  self.assertNotEqual(self.snapshot('pair')['state'],'CLOSED')

class StaleExecutedQtyCannotRegress(PairAtomic):
 def test_stale_short_partial_after_restart_is_rejected_without_mutation(self):
  first={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(first),'PAIR_RECONCILE_REQUIRED')
  before=self.snapshot('SHORTledger');claim=self.snapshot('SHORTclaim')
  self.db=self.db.restart();self.bind()
  stale={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',20,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(stale),'BLOCKED_EXECUTED_QTY_REGRESSION')
  self.assertEqual(self.snapshot('SHORTledger'),before)
  self.assertEqual(self.snapshot('SHORTclaim'),claim)

class ReplayedFillFinancialConflict(PairAtomic):
 def test_same_execution_id_changed_fee_is_rejected_after_restart(self):
  rows={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='PARTIALLY_FILLED')}
  self.assertEqual(self.run_pair(rows),'PAIR_RECONCILE_REQUIRED')
  before=self.snapshot('SHORTledger')
  self.db=self.db.restart();self.bind()
  replay={'LONG':self.row('LONG'),'SHORT':self.row('SHORT',25,status='PARTIALLY_FILLED')}
  replay['SHORT']['fills'][0]['commission']='0.4'
  self.assertEqual(self.run_pair(replay),'BLOCKED_FINANCIAL_REPLAY_MISMATCH')
  self.assertEqual(self.snapshot('SHORTledger'),before)
  self.assertNotEqual(self.snapshot('pair')['state'],'CLOSED')
