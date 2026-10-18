import unittest
from decimal import Decimal
from short_recovery_open_price_provenance_offline import weighted_open_price
class OpenPriceProof(unittest.TestCase):
 def test_weighted_price_and_all_unreliable_open_readbacks_fail_closed(self):
  class Mock:
   offline_mock_only=True
   status='FILLED'
   rows=None
   def query_order(self,s,c):return {'symbol':s,'clientOrderId':c,'orderId':'o','status':self.status,'executedQty':'100'}
   def user_trades(self,s,**kw):return self.rows
  c=Mock();base=[{'symbol':'XRPUSDT','orderId':'o','id':1,'qty':'40','price':'1.60'}, {'symbol':'XRPUSDT','orderId':'o','id':2,'qty':'60','price':'1.70'}];c.rows=base
  def check():return weighted_open_price(c,symbol='XRPUSDT',intent_id='i',order_id='o',executed_qty='100')
  self.assertEqual(check(),Decimal('1.66'))
  c.status='PARTIALLY_FILLED';self.assertIsNone(check());c.status='FILLED'
  for rows in ([{k:v for k,v in x.items() if k!='price'} for x in base], [base[0]], [base[0],{**base[1],'id':1}], [base[0],{**base[1],'qty':'59'}], [base[0],{**base[1],'price':'NaN'}]):
   c.rows=rows;self.assertIsNone(check())
  c.rows=base
  self.assertIsNone(weighted_open_price(c,symbol='XRPUSDT',intent_id='i',order_id='o',executed_qty='100',page_size=1))
  c.offline_mock_only=False;self.assertIsNone(check())
