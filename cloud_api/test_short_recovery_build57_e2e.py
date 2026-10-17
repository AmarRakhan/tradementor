"""Offline Aster mock readback -> atomic owned Recovery ledger; no exchange writes."""
import unittest,threading
from decimal import Decimal as D
from short_recovery_aster_readback_mock_adapter import inspect
from short_recovery_ledger import Fill,Ledger,Allocation
from short_recovery_firestore_mock import encode,decode
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_transaction_adapter import record_confirmed_fill_owned
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Client:
 def __init__(self,account='u'):
  self.account=account
  self.rows=[{'symbol':'XRPUSDT','orderId':7,'id':'ex1','qty':'25','realizedPnl':'1.2','commission':'0.1','funding':'-0.05'}, {'symbol':'XRPUSDT','orderId':7,'id':'ex2','qty':'25','realizedPnl':'2.0','commission':'0.2','funding':'0.03'}]
 def query_order(self,symbol,client_order_id):return {'symbol':symbol,'clientOrderId':client_order_id,'orderId':7,'status':'PARTIALLY_FILLED'}
 def user_trades(self,symbol,limit=500):return self.rows
 def submit_order(self,*a,**kw):raise AssertionError('forbidden')
class Tests(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.key=('u','XRPUSDT');self.lk=Ref(self.db,(*self.key,'ledger'));self.ok=Ref(self.db,(*self.key,'owner'))
  self.db.commit(self.lk.key,0,encode(Ledger('u','XRPUSDT',(Allocation('zone','cycle',D(100)),))))
  self.db.commit(self.ok.key,0,{'account':'u','symbol':'XRPUSDT','cycleId':'cycle','ownerSide':'SHORT','ownershipVerified':True,'cycleConfirmed':True,'state':'PARTIAL'})
 def apply(self,ex):
  f=Fill('u','XRPUSDT',ex['executionId'],ex['orderId'],ex['quantity'],ex['realizedPnl'],ex['fee'],ex['funding'])
  return record_confirmed_fill_owned(db=self.db,transactional=transactional,ledger_ref=self.lk,ownership_ref=self.ok,fill=f,splits=(('zone','cycle',ex['quantity']),),account='u',symbol='XRPUSDT',cycle_id='cycle')
 def test_net_accounting_partial_and_duplicate(self):
  result=inspect(Client(),symbol='XRPUSDT',client_order_id='intent');self.assertEqual(result['status'],'READBACK_PREVIEW')
  self.assertEqual([self.apply(x) for x in result['fills']],['APPLIED','APPLIED'])
  ledger=decode(self.db.snapshot(self.lk.key)[1]);self.assertEqual(ledger.allocations[0].remaining,D(50))
  self.assertEqual(ledger.cycle_realized('cycle'),D('2.88'))
  self.assertEqual(self.apply(result['fills'][0]),'ALREADY_APPLIED')
 def test_restart_and_workers(self):
  ex=inspect(Client(),symbol='XRPUSDT',client_order_id='intent')['fills'][0]
  self.db=self.db.restart();self.lk=Ref(self.db,self.lk.key);self.ok=Ref(self.db,self.ok.key)
  gate=threading.Barrier(4);out=[];lock=threading.Lock()
  def run():
   gate.wait();r=self.apply(ex)
   with lock:out.append(r)
  threads=[threading.Thread(target=run) for _ in range(4)]
  for t in threads:t.start()
  for t in threads:t.join(5);self.assertFalse(t.is_alive())
  self.assertCountEqual(out,['APPLIED']+['ALREADY_APPLIED']*3)
 def test_wrong_order_and_missing_executions(self):
  client=Client();client.rows[0]['orderId']=999
  r=inspect(client,symbol='XRPUSDT',client_order_id='intent')
  self.assertEqual(len(r['fills']),1);self.assertFalse(r['terminalVerified'])
  client.rows=[];self.assertEqual(inspect(client,symbol='XRPUSDT',client_order_id='intent')['fills'],[])
 def test_invalid_money_blocks_all(self):
  client=Client();client.rows[0]['commission']='NaN'
  self.assertEqual(inspect(client,symbol='XRPUSDT',client_order_id='intent')['status'],'BLOCKED_BAD_FILL')
 def test_account_scope_rejects_cross_account_fill(self):
  from short_recovery_transaction_adapter import record_confirmed_fill_owned
  ex=inspect(Client(),symbol='XRPUSDT',client_order_id='intent')['fills'][0]
  f=Fill('other','XRPUSDT',ex['executionId'],ex['orderId'],ex['quantity'],ex['realizedPnl'],ex['fee'],ex['funding'])
  self.assertEqual(record_confirmed_fill_owned(db=self.db,transactional=transactional,ledger_ref=self.lk,ownership_ref=self.ok,fill=f,splits=(('zone','cycle',ex['quantity']),),account='u',symbol='XRPUSDT',cycle_id='cycle'),'BLOCKED_SCOPE')
 def test_legacy_shadow_and_execution_gate(self):
  c=TestShadowReconciler();c.setUp();r=c.run_shadow({'XRPUSDT'})
  self.assertEqual(r['ordersSent'],0);self.assertEqual([a['symbol'] for a in r['actions']],['BTCUSDT'])
