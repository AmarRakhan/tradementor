import unittest
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_order_claim_shadow import canonical_intent_id
from short_recovery_standalone_offline import RECOVERY,CLASSIC
from short_recovery_standalone_claim_gate_offline import check_standalone_canonical_claim_offline as check

class ClaimBridge(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB()
  self.refs={k:Ref(self.db,k) for k in ('selector','position','claim','control','coord')}
  self.cid=canonical_intent_id(account='u',symbol='XRPUSDT',cycle='c',side='SHORT',action='CLOSE',step=1)
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c','offlineOnly':True})
  self.put('claim',{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.cid,'side':'SHORT','action':'CLOSE','step':1,'state':'RESERVED'})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('coord',{'recoveryFenceReservation':{'account':'u','symbol':'XRPUSDT','cycle':'c','intentId':self.cid,'state':'RECOVERY_CLAIM_RESERVED'}})
 def put(self,key,value):
  v,_=self.db.snapshot(key);self.db.commit(key,v,value)
 def inspect(self,**other):
  kw=dict(db=self.db,transactional=transactional,selector_ref=self.refs['selector'],position_ref=self.refs['position'],claim_ref=self.refs['claim'],control_ref=self.refs['control'],coordination_ref=self.refs['coord'],account='u',symbol='XRPUSDT',cycle='c',action='CLOSE',step=1,quantity='25')
  kw.update(other);return check(**kw)
 def test_existing_canonical_claim_not_transport_authority(self):
  self.assertEqual(self.inspect(),'CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED')
  self.assertEqual(self.inspect(),'CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED')
  self.assertEqual(self.db.snapshot('claim')[1]['state'],'RESERVED')
 def test_classic_wrong_account_wrong_cycle(self):
  self.put('selector',{'account':'u','activeStrategy':CLASSIC,'offlineOnly':True})
  self.assertEqual(self.inspect(),'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.assertEqual(self.inspect(account='other'),'BLOCKED_STRATEGY_NOT_ACTIVE')
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.assertEqual(self.inspect(cycle='c2'),'BLOCKED_CANONICAL_CLAIM')
 def test_unknown_partial_and_stale_fence(self):
  for state in ('SUBMITTING','UNKNOWN','PARTIAL'):
   self.put('claim',{**self.db.snapshot('claim')[1],'state':state})
   self.assertEqual(self.inspect(),'BLOCKED_CANONICAL_CLAIM')
  self.put('claim',{**self.db.snapshot('claim')[1],'state':'RESERVED'})
  self.put('coord',{'recoveryFenceReservation':{'intentId':'stale'}})
  self.assertEqual(self.inspect(),'BLOCKED_SHARED_FENCE')
 def test_emergency_closeall_and_lease(self):
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.inspect(),'BLOCKED_CONTROL')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':True})
  self.assertEqual(self.inspect(),'BLOCKED_CONTROL')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('coord',{**self.db.snapshot('coord')[1],'lease':{'token':'unknown'}})
  self.assertEqual(self.inspect(),'BLOCKED_UNRESOLVED_LEASE')
 def test_restart_and_duplicate_reads_never_create_right(self):
  self.db=self.db.restart()
  self.refs={k:Ref(self.db,k) for k in self.refs}
  self.assertEqual(self.inspect(),'CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED')
  self.assertEqual(self.inspect(),'CLAIM_SCOPE_MATCHED_NOT_AUTHORIZED')
  self.assertEqual(self.db.snapshot('claim')[1]['state'],'RESERVED')
if __name__=='__main__':unittest.main()
