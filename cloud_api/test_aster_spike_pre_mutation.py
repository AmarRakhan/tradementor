import unittest
from unittest.mock import patch
from aster_unified_engine import ActionType
from aster_unified_execution import execute_approved_leg_once
from aster_extreme_spike_filter import claim_spike_entry_once, SpikeFilterRejected

class Decision:
    allowed=True
    action_type=ActionType.INITIAL_ENTRY
    reason_code="ALL_ACTIVE_RULES_PASSED"
    def public_dict(self): return {"allowed":True}

class PreMutationTests(unittest.TestCase):
    def test_failed_spike_claim_causes_no_exchange_mutations(self):
        called=[]
        def exchange(*args,**kwargs):
            called.append("exchange")
            return {}
        def failing_claim():
            raise PermissionError("SPIKE_EVENT_CLAIM_FAILED_OR_REPLAY")
        with patch("aster_unified_execution.execute_leg_once",side_effect=exchange):
            with self.assertRaises(PermissionError):
                execute_approved_leg_once(None,None,side="LONG",action="OPEN",
                  id_prefix="mbb-open-test",confirm=True,
                  expected_action=ActionType.INITIAL_ENTRY,
                  decision_provider=lambda:Decision(),
                  pre_mutation_admission=failing_claim)
        self.assertEqual(called,[])
    def test_final_admission_still_runs_after_pre_mutation(self):
        sequence=[]
        def exchange(*args,**kwargs):
            sequence.append("executor")
            kwargs["before_submit"]("intent")
            sequence.append("submit")
            return {"result":{}}
        def pre():
            sequence.append("pre")
            return Decision()
        def final():
            sequence.append("final")
            return Decision()
        with patch("aster_unified_execution.execute_leg_once",side_effect=exchange):
            execute_approved_leg_once(None,None,side="LONG",action="OPEN",
              id_prefix="mbb-open-test",confirm=True,
              expected_action=ActionType.INITIAL_ENTRY,
              decision_provider=final,pre_mutation_admission=pre)
        self.assertEqual(sequence,["pre","executor","final","submit"])
    def test_exchange_failure_keeps_spike_claim_reserved(self):
        class Doc:
            def __init__(self,seen):self.seen=seen
            def create(self,payload):
                if payload["eventId"] in self.seen:raise RuntimeError("ALREADY_EXISTS")
                self.seen.add(payload["eventId"])
        class Account:
            def __init__(self):self.seen=set()
            def collection(self,name):
                account=self
                class Collection:
                    def document(self,key):return Doc(account.seen)
                return Collection()
        account=Account()
        events=[]
        def claim():
            claim_spike_entry_once(account,event_key="f"*32,symbol="BTCUSDT",side="LONG",timeframe="1m",now_ms=1000)
            return Decision()
        def order_failure(*args,**kwargs):
            events.append("attempt")
            raise TimeoutError("uncertain exchange order")
        with patch("aster_unified_execution.execute_leg_once",side_effect=order_failure):
            with self.assertRaises(TimeoutError):
                execute_approved_leg_once(None,None,side="LONG",action="OPEN",id_prefix="mbb-open-test",
                    confirm=True,expected_action=ActionType.INITIAL_ENTRY,
                    decision_provider=lambda:Decision(),pre_mutation_admission=claim)
            with self.assertRaises(SpikeFilterRejected):
                execute_approved_leg_once(None,None,side="LONG",action="OPEN",id_prefix="mbb-open-test",
                    confirm=True,expected_action=ActionType.INITIAL_ENTRY,
                    decision_provider=lambda:Decision(),pre_mutation_admission=claim)
        self.assertEqual(events,["attempt"])
        self.assertEqual(len(account.seen),1)

if __name__=="__main__":unittest.main()
