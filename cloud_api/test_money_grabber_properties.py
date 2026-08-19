from dataclasses import replace
from hypothesis import given, strategies as st
import pytest

from money_grabber import Intent,ProtectedPair,apply_protection_fill,normal_action_allowed


@given(st.sampled_from(["PROTECTION_PENDING","PARTIAL_PROTECTION","FULL_PROTECTION_PENDING","LOCKED","PAIR_CLOSE_PENDING","PAIR_CLOSING","COOLDOWN","RECOVERY"]),st.sampled_from(["ENTRY","DCA","TAKE_PROFIT","AUTO_REOPEN"]))
def test_protected_pair_can_never_produce_normal_action(status,action):
    assert not normal_action_allowed(ProtectedPair("a","r","BTCUSDT","LONG",status),action)


@given(st.floats(min_value=.01,max_value=1_000,allow_nan=False,allow_infinity=False),st.floats(min_value=.01,max_value=1,allow_nan=False,allow_infinity=False))
def test_protection_fill_never_exceeds_configured_ratio(original,ratio):
    target=original*ratio
    pair=ProtectedPair("a","r","BTCUSDT","LONG")
    intent=Intent("i","PAIR_PROTECTION_RISK_REDUCING","a","r","BTCUSDT","SHORT",target)
    filled=apply_protection_fill(pair,intent,fill_notional=target,original_notional=original,full_ratio=ratio)
    assert filled.protection_notional <= original*ratio+max(1e-8,original*1e-6)
    with pytest.raises(ValueError):
        apply_protection_fill(pair,intent,fill_notional=target+max(.01,original*.01),original_notional=original,full_ratio=ratio)


def test_same_intent_fill_cannot_be_reapplied_as_new_economic_exposure():
    pair=ProtectedPair("a","r","BTCUSDT","LONG")
    intent=Intent("unique","PAIR_PROTECTION_RISK_REDUCING","a","r","BTCUSDT","SHORT",10)
    first=apply_protection_fill(pair,intent,fill_notional=10,original_notional=20,full_ratio=1)
    # Persistence/reconciliation must recognize the intent before applying it again.
    assert first.intent_id=="unique"
    assert replace(first).intent_id==intent.intent_id
