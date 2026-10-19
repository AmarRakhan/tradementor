import unittest
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal as D
from short_recovery_multidoc_mock import MultiDocDB,Ref,transactional
from short_recovery_minimum_carry_claim_offline import reserve_minimum_carry_offline
from short_recovery_standalone_offline import RECOVERY
from short_recovery_order_claim_shadow import submit_once_offline
from aster_gateway import AsterOrderIntent,PositionSide

class CarryClaim(unittest.TestCase):
 def setUp(self):
  self.db=MultiDocDB();self.refs={x:Ref(self.db,x) for x in ('selector','position','control','coord','claim')}
  self.put('selector',{'account':'u','activeStrategy':RECOVERY,'offlineOnly':True})
  self.put('position',{'account':'u','symbol':'XRPUSDT','cycle':'c','offlineOnly':True,
     'state':'ADOPTED_OFFLINE','pending':False,'anchor':'100','originalShortQty':'1',
     'confirmedClosed':'0','stepPct':'5','steps':4})
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.put('coord',{})
 def put(self,key,value):
  n,_=self.db.snapshot(key);self.db.commit(key,n,value)
 def reserve(self,**kw):
  opts=dict(db=self.db,transactional=transactional,selector_ref=self.refs['selector'],
    position_ref=self.refs['position'],control_ref=self.refs['control'],
    coordination_ref=self.refs['coord'],claim_ref=self.refs['claim'],
    account='u',symbol='XRPUSDT',cycle='c',mark='90',exchange_short_qty='1',
    minimum_qty='.01',quantity_step='.01',minimum_notional='30',executable_price='100')
  opts.update(kw);return reserve_minimum_carry_offline(**opts)
 def submit(self,quantity,transport):
  c=self.db.snapshot('claim')[1]
  return submit_once_offline(db=self.db,transactional=transactional,
    claim_ref=self.refs['claim'],control_ref=self.refs['control'],
    coordination_ref=self.refs['coord'],require_shared_fence=True,
    standalone_selector_ref=self.refs['selector'],account='u',symbol='XRPUSDT',
    cycle='c',intent=AsterOrderIntent(c['intentId'],'XRPUSDT',PositionSide.SHORT,D(quantity),'CLOSE'),
    account_close_guard=lambda:None,submit_mock=transport)
 def test_skip_first_reserve_second_and_one_mock_post(self):
  self.assertEqual(self.reserve(mark='95'),'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertIsNone(self.db.snapshot('claim')[1])
  self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
  self.assertEqual(self.db.snapshot('claim')[1]['minimumCarryQuantity'],'0.5')
  sent=[]
  self.assertEqual(self.submit('.25',lambda intent:sent.append(intent)),
    'BLOCKED_MINIMUM_CARRY_QUANTITY')
  self.assertEqual(self.submit('.5',lambda intent:sent.append(intent)),
    'SUBMITTED_RECONCILE_ONLY')
  self.assertEqual(self.submit('.5',lambda intent:sent.append(intent)),
    'BLOCKED_CLAIM_NOT_RESERVED')
  self.assertEqual(len(sent),1)
 def test_concurrent_reserve_one_claim(self):
  with ThreadPoolExecutor(max_workers=2) as pool:
   outcomes=list(pool.map(lambda _:self.reserve(),range(2)))
  self.assertEqual(outcomes.count('MINIMUM_CARRY_RESERVED_OFFLINE'),1)
  self.assertEqual(outcomes.count('BLOCKED_CLAIM_EXISTS'),1)
 def test_stop_unknown_and_restart_fail_closed(self):
  self.assertEqual(self.reserve(),'MINIMUM_CARRY_RESERVED_OFFLINE')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':True,'closeAllActive':False})
  self.assertEqual(self.submit('.5',lambda _:None),'BLOCKED_RECOVERY_DISABLED_OR_STOPPED')
  self.put('control',{'account':'u','enabled':True,'emergencyStop':False,'closeAllActive':False})
  self.assertEqual(self.submit('.5',lambda _:(_ for _ in ()).throw(TimeoutError())),
    'UNKNOWN_RECONCILE_ONLY')
  self.db=self.db.restart();self.refs={k:Ref(self.db,k) for k in self.refs}
  self.assertEqual(self.submit('.5',lambda _:None),'BLOCKED_CLAIM_NOT_RESERVED')
 def test_inventory_and_final_dust_no_claim(self):
  self.assertEqual(self.reserve(exchange_short_qty='.7'),'BLOCKED_INVENTORY')
  self.put('position',{**self.db.snapshot('position')[1],'confirmedClosed':'.9'})
  self.assertEqual(self.reserve(mark='80',exchange_short_qty='.1'),
    'BLOCKED_FINAL_REMAINDER_UNDER_MINIMUM')
  self.assertIsNone(self.db.snapshot('claim')[1])
 def test_ten_step_carry(self):
  self.put('position',{**self.db.snapshot('position')[1],'steps':10})
  self.assertEqual(self.reserve(mark='95'),'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.reserve(mark='90'),'WAIT_MINIMUM_CARRY_FORWARD')
  self.assertEqual(self.reserve(mark='85'),'MINIMUM_CARRY_RESERVED_OFFLINE')
  self.assertEqual(self.db.snapshot('claim')[1]['minimumCarryQuantity'],'0.3')
if __name__=='__main__':unittest.main()
