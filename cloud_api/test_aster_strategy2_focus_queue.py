import pytest

from aster_strategy2_focus_queue import (
    FocusQueueIntent, MAX_ACCOUNT_SCAN_ACTIONS, order_focus_intents,
    validate_focus_queue,
)


def intent(kind, symbol="AAAUSDT", side="LONG", *, reduce=False, sequence=0):
    return FocusQueueIntent(kind, symbol, side, 100, reduce, kind, sequence)


def test_focus_queue_hard_cap_is_existing_15_actions():
    rows=[intent("LEGACY_MANAGEMENT",f"P{i}USDT") for i in range(30)]
    assert MAX_ACCOUNT_SCAN_ACTIONS==15
    assert len(order_focus_intents(rows))==15


def test_existing_orders_used_reduce_focus_budget():
    rows=[intent("LEGACY_MANAGEMENT",f"P{i}USDT") for i in range(20)]
    assert len(order_focus_intents(rows,orders_used=12))==3


def test_emergency_and_risk_close_preempt_focus_dca_and_entry():
    rows=[
        intent("FOCUS_ENTRY"),intent("FOCUS_DCA"),
        intent("RISK_CLOSE",reduce=True),intent("EMERGENCY_CLOSE",reduce=True),
    ]
    ordered=order_focus_intents(rows)
    assert [x.kind for x in ordered]==["EMERGENCY_CLOSE","RISK_CLOSE","FOCUS_DCA","FOCUS_ENTRY"]


def test_focus_full_close_preempts_partial_dca_and_entry():
    rows=[intent("FOCUS_ENTRY"),intent("FOCUS_DCA"),intent("FOCUS_PARTIAL_TP",reduce=True),intent("FOCUS_CLOSE",reduce=True)]
    assert [x.kind for x in order_focus_intents(rows)]==["FOCUS_CLOSE","FOCUS_PARTIAL_TP","FOCUS_DCA","FOCUS_ENTRY"]


def test_legacy_management_is_after_focus_new_entry_per_requested_priority():
    rows=[intent("LEGACY_MANAGEMENT"),intent("FOCUS_ENTRY")]
    assert [x.kind for x in order_focus_intents(rows)]==["FOCUS_ENTRY","LEGACY_MANAGEMENT"]


def test_reduce_only_is_required_for_focus_and_risk_closes():
    with pytest.raises(ValueError):validate_focus_queue([intent("FOCUS_CLOSE")])
    with pytest.raises(ValueError):validate_focus_queue([intent("FOCUS_PARTIAL_TP")])
    with pytest.raises(ValueError):validate_focus_queue([intent("RISK_CLOSE")])


def test_focus_opening_actions_are_long_only():
    with pytest.raises(ValueError):validate_focus_queue([intent("FOCUS_ENTRY",side="SHORT")])
    with pytest.raises(ValueError):validate_focus_queue([intent("FOCUS_DCA",side="SHORT")])
    validate_focus_queue([intent("FOCUS_ENTRY",side="LONG")])


def test_focus_cannot_plan_two_new_pairs():
    with pytest.raises(ValueError):validate_focus_queue([intent("FOCUS_ENTRY","AAAUSDT"),intent("FOCUS_ENTRY","BBBUSDT")])
