import unittest,threading
from short_recovery_aster_readback_mock_adapter import inspect
from test_short_recovery_real_reconciler_shadow import TestShadowReconciler
class Client:
 def __init__(self,order=None,fills=None,error=False):
  self.order=order if order is not None else {'symbol':'XRPUSDT','clientOrderId':'intent','orderId':11,'status':'PARTIALLY_FILLED'}
  self.fills=fills if fills is not None else [{'symbol':'XRPUSDT','orderId':11,'id':77,'qty':'25'}]
  self.error=error
 def query_order(self,symbol,client_order_id):
  if self.error:raise TimeoutError('mock timeout')
  return self.order
 def user_trades(self,symbol,limit=500):
  if self.error:raise TimeoutError('mock timeout')
  return self.fills
 def submit_order(self,*a,**k):raise AssertionError('orders forbidden')
class Tests(unittest.TestCase):
 def scan(self,client):return inspect(client,symbol='XRPUSDT',client_order_id='intent')
 def test_readback_partial_fill(self):
  r=self.scan(Client());self.assertEqual(r['status'],'READBACK_PREVIEW');self.assertEqual(len(r['fills']),1)
  self.assertFalse(r['terminalVerified']);self.assertEqual(r['ordersSent'],0)
 def test_timeout_fail_closed(self):self.assertEqual(self.scan(Client(error=True))['status'],'BLOCKED_READBACK_UNAVAILABLE')
 def test_missing_order_not_proof(self):self.assertEqual(self.scan(Client(order={}))['status'],'BLOCKED_ORDER_UNPROVEN')
 def test_wrong_order_identity(self):self.assertEqual(self.scan(Client(order={'symbol':'XRPUSDT','clientOrderId':'wrong','orderId':11}))['status'],'BLOCKED_ORDER_MISMATCH')
 def test_missing_executions_not_finality(self):
  r=self.scan(Client(fills=[]));self.assertEqual(r['fills'],[]);self.assertFalse(r['terminalVerified'])
 def test_bad_fill_fails_closed(self):self.assertEqual(self.scan(Client(fills=[{'symbol':'XRPUSDT','orderId':11,'id':77,'qty':'NaN'}]))['status'],'BLOCKED_BAD_FILL')
 def test_duplicate_execution_ids(self):
  c=Client();c.fills=c.fills*2;self.assertEqual(len(self.scan(c)['fills']),1)
 def test_concurrent_readback_preview(self):
  gate=threading.Barrier(6);results=[];lock=threading.Lock()
  def worker():
   gate.wait();r=self.scan(Client())
   with lock:results.append(r['status'])
  threads=[threading.Thread(target=worker) for _ in range(6)]
  for t in threads:t.start()
  for t in threads:
   t.join(5);self.assertFalse(t.is_alive())
  self.assertEqual(results,['READBACK_PREVIEW']*6)
 def test_legacy_auto_hedge_shadow_only(self):
  case=TestShadowReconciler();case.setUp();r=case.run_shadow({'XRPUSDT'})
  self.assertEqual(r['ordersSent'],0);self.assertEqual([x['symbol'] for x in r['actions']],['BTCUSDT'])
