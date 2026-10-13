import unittest
from unittest.mock import patch
from aster_unified_engine import ActionType
from aster_unified_execution import execute_approved_leg_once

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
if __name__=="__main__":unittest.main()
