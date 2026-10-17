import unittest
from decimal import Decimal
from short_recovery_build60_evidence_shadow import ownership_audit, timestamp_boundary_audit

class Tests(unittest.TestCase):
    def row(self, ident, **overrides):
        item={'tranId':ident,'time':120,'incomeType':'FUNDING_FEE','symbol':'XRPUSDT','positionSide':'SHORT','income':'-0.02'}
        item.update(overrides)
        return item
    def audit(self, rows, proof=None):
        return ownership_audit(rows=rows,symbol='XRPUSDT',side='SHORT',cycle_id='cycle-A',start_ms=100,end_ms=200,exclusive_event_owners=proof or {})
    def test_existing_exchange_fields_do_not_prove_cycle(self):
        self.assertEqual(self.audit([self.row('1')])['status'],'BLOCKED_OWNERSHIP_PROOF')
    def test_proven_cycle_stays_preview_not_ledger_authority(self):
        r=self.audit([self.row('1')],{'1':('XRPUSDT','SHORT','cycle-A')})
        self.assertEqual(r['funding'],Decimal('-0.02'))
        self.assertFalse(r['ledgerSafe'])
        self.assertEqual(r['ordersSent'],0)
    def test_wrong_cycle_block(self):
        self.assertEqual(self.audit([self.row('1')],{'1':('XRPUSDT','SHORT','cycle-B')})['status'],'BLOCKED_OWNERSHIP_PROOF')
    def test_two_cycles_same_symbol_side_not_interchangeable(self):
        r=self.audit([self.row('1'),self.row('2')],{'1':('XRPUSDT','SHORT','cycle-A'),'2':('XRPUSDT','SHORT','cycle-B')})
        self.assertEqual(r['status'],'BLOCKED_OWNERSHIP_PROOF')
    def test_no_side_is_not_side_proof(self):
        self.assertEqual(self.audit([self.row('1',positionSide=None)],{'1':('XRPUSDT','SHORT','cycle-A')})['status'],'BLOCKED_EVENT')
    def test_duplicate_income_rejected(self):
        self.assertEqual(self.audit([self.row('1'),self.row('1')],{'1':('XRPUSDT','SHORT','cycle-A')})['status'],'BLOCKED_EVENT')
    def test_missing_income_amount_rejected(self):
        self.assertEqual(self.audit([self.row('1',income='NaN')],{'1':('XRPUSDT','SHORT','cycle-A')})['status'],'BLOCKED_EVENT')
    def test_full_page_same_timestamp_fails_closed(self):
        self.assertEqual(timestamp_boundary_audit([self.row('1'),self.row('2')],page_size=2),'BLOCKED_TIMESTAMP_CURSOR_AMBIGUOUS')
    def test_full_page_distinct_timestamps_also_ambiguous(self):
        self.assertEqual(timestamp_boundary_audit([self.row('1'),self.row('2',time=121)],page_size=2),'BLOCKED_TIMESTAMP_CURSOR_AMBIGUOUS')
    def test_short_page_not_complete_cycle_proof(self):
        self.assertEqual(timestamp_boundary_audit([self.row('1')],page_size=2),'SHADOW_SHORT_PAGE_ONLY')
    def test_no_funding_does_not_prove_zero_funding(self):
        result=self.audit([])
        self.assertFalse(result['proven'])
        self.assertIsNone(result['funding'])

if __name__=='__main__':unittest.main()
