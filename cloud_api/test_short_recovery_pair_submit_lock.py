import threading, unittest
from decimal import Decimal
from aster_gateway import AsterOrderIntent,PositionSide
from short_recovery_order_claim_shadow import canonical_intent_id,lock_pair_submit_offline
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
class PairLock(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.refs={x:Ref(self.db,x) for x in ('LONG','SHORT','control')}
  self.ids={x:canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side=x,action='CLOSE',step=1) for x in ('LONG','SHORT')}
  for side in ('LONG','SHORT'):
   self.db.commit(side,0,dict(account='u',symbol='XRPUSDT',cycle='c',intentId=self.ids[side],side=side,action='CLOSE',step=1,state='RESERVED'))
  self.db.commit('control',0,dict(account='u',enabled=True,emergencyStop=False,closeAllActive=False))
  self.intents={s:AsterOrderIntent(self.ids[s],'XRPUSDT',getattr(PositionSide,s),Decimal('10'),'CLOSE') for s in ('LONG','SHORT')}
 def call(self):
  return lock_pair_submit_offline(db=self.db,transactional=transactional,long_claim_ref=self.refs['LONG'],short_claim_ref=self.refs['SHORT'],control_ref=self.refs['control'],account='u',symbol='XRPUSDT',cycle='c',long_intent=self.intents['LONG'],short_intent=self.intents['SHORT'],account_close_guard=lambda:None)
 def test_atomic_two_side_lock_and_no_replay(self):
  self.assertEqual(self.call(),'PAIR_SUBMITTING_LOCKED')
  self.assertEqual(self.db.snapshot('LONG')[1]['state'],'SUBMITTING')
  self.assertEqual(self.db.snapshot('SHORT')[1]['state'],'SUBMITTING')
  self.assertEqual(self.call(),'BLOCKED_PAIR_SIDE_CLAIMS')
  self.db=self.db.restart();self.refs={x:Ref(self.db,x) for x in self.refs}
  self.assertEqual(self.call(),'BLOCKED_PAIR_SIDE_CLAIMS')
 def test_invalid_side_does_not_mutate_either(self):
  self.intents['LONG']=AsterOrderIntent('incorrect','XRPUSDT',PositionSide.LONG,Decimal('10'),'CLOSE')
  self.assertEqual(self.call(),'BLOCKED_PAIR_SIDE_CLAIMS')
  self.assertEqual(self.db.snapshot('SHORT')[1]['state'],'RESERVED')
 def test_emergency_stop_never_locks(self):
  self.db.commit('control',1,dict(account='u',enabled=True,emergencyStop=True,closeAllActive=False))
  self.assertEqual(self.call(),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
 def test_concurrent_one_winner(self):
  results=[];threads=[threading.Thread(target=lambda:results.append(self.call())) for _ in range(8)]
  for t in threads:t.start()
  for t in threads:t.join()
  self.assertEqual(results.count('PAIR_SUBMITTING_LOCKED'),1)

class PairTransportMock(PairLock):
 def send(self,submit):
  from short_recovery_order_claim_shadow import submit_locked_pair_mock_offline
  return submit_locked_pair_mock_offline(db=self.db,transactional=transactional,
     long_claim_ref=self.refs['LONG'],short_claim_ref=self.refs['SHORT'],
     control_ref=self.refs['control'],account='u',symbol='XRPUSDT',cycle='c',
     long_intent=self.intents['LONG'],short_intent=self.intents['SHORT'],
     account_close_guard=lambda:None,submit_mock=submit)
 def test_two_mock_posts_only_once_even_after_restart(self):
  calls=[]
  self.assertEqual(self.send(lambda i:(calls.append(i.intent_id) or {'clientOrderId':i.intent_id,'orderId':i.position_side.value+'-order'})),('SUBMITTED_RECONCILE_ONLY','SUBMITTED_RECONCILE_ONLY'))
  self.db=self.db.restart();self.refs={x:Ref(self.db,x) for x in self.refs}
  self.assertEqual(self.send(lambda i:(calls.append(i.intent_id) or {'clientOrderId':i.intent_id,'orderId':i.position_side.value+'-order'})),('BLOCKED_PAIR_SIDE_CLAIMS',))
  self.assertEqual(calls,[self.ids['LONG'],self.ids['SHORT']])
 def test_first_side_timeout_never_posts_second_or_retries(self):
  calls=[]
  def timeout(i):calls.append(i.intent_id);raise TimeoutError('mock')
  self.assertEqual(self.send(timeout),('UNKNOWN_RECONCILE_ONLY',))
  self.assertEqual(self.send(timeout),('BLOCKED_PAIR_SIDE_CLAIMS',))
  self.assertEqual(calls,[self.ids['LONG']])
  self.assertEqual(self.db.snapshot('SHORT')[1]['state'],'SUBMITTING')
 def test_second_side_timeout_never_posts_again(self):
  calls=[]
  def timeout_second(i):
   calls.append(i.intent_id)
   if i.position_side is PositionSide.SHORT:raise TimeoutError('mock')
   return {'clientOrderId':i.intent_id,'orderId':'LONG-order'}
  self.assertEqual(self.send(timeout_second),('SUBMITTED_RECONCILE_ONLY','UNKNOWN_RECONCILE_ONLY'))
  self.assertEqual(self.send(timeout_second),('BLOCKED_PAIR_SIDE_CLAIMS',))
  self.assertEqual(len(calls),2)

class BadAckIsNotSettlement(PairTransportMock):
 def test_wrong_client_order_id_does_not_ack_or_retry(self):
  calls=[]
  def wrong_ack(intent):
   calls.append(intent.intent_id)
   return {'clientOrderId':'someone-else','orderId':'order-x'}
  self.assertEqual(self.send(wrong_ack),('BLOCKED_ACK_MISMATCH',))
  self.assertEqual(self.db.snapshot('LONG')[1]['state'],'SUBMITTING')
  self.assertEqual(self.db.snapshot('SHORT')[1]['state'],'SUBMITTING')
  self.assertEqual(self.send(wrong_ack),('BLOCKED_PAIR_SIDE_CLAIMS',))
  self.assertEqual(len(calls),1)
