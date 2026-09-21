"""Static safety-contract tests for the account-scoped close-all route.

These tests never instantiate an exchange client and therefore can never emit
an order.  They pin the orchestration invariants around the pure arithmetic
tests in test_portfolio_growth.py.
"""
from pathlib import Path


SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
_START = SOURCE.index('def _portfolio_growth_client')
# The close-all block owns this terminal fail-closed audit marker.  Use the next
# FastAPI route after that marker as the boundary instead of depending on the
# name/order of an unrelated endpoint that may move during Strategy-2 work.
_TAIL = SOURCE.index('"PARTIAL_FAIL_CLOSED"', _START)
_NEXT_ROUTE = SOURCE.find("\n@app.", _TAIL)
ROUTE = SOURCE[_START:_NEXT_ROUTE if _NEXT_ROUTE != -1 else len(SOURCE)]


def test_state_is_strictly_nested_below_authenticated_uid():
    assert 'portfolio_growth_reference(uid)' in ROUTE
    assert 'collection("users").document(uid).collection("portfolioGrowth")' in SOURCE
    assert 'f"{uid}:{request.idempotency_key}"' in ROUTE


def test_initial_baseline_is_one_time_and_owner_audited():
    assert "De startwaarde bestaat al" in ROUTE
    assert '"actorUid":uid' in ROUTE
    assert '"event":"BASELINE_INITIALIZED"' in ROUTE


def test_reset_requires_confirmation_reason_and_audit():
    assert "Bevestig de handmatige reset expliciet" in ROUTE
    assert '"event":"BASELINE_RESET"' in ROUTE
    assert '"reason":request.reason' in ROUTE


def test_close_all_lock_and_all_pauses_are_uid_scoped():
    assert '"closeLock":{"active":True' in ROUTE
    assert 'aster_strategy2_reference(uid)' in ROUTE
    assert 'aster_sniper_reference(uid)' in ROUTE
    assert '"phase":"EMERGENCY_STOP"' in ROUTE
    assert 'aster_automation_reference(uid)' not in ROUTE
    assert 'aster_strategy3_reference(uid)' not in ROUTE


def test_idempotency_is_bound_to_account_and_key():
    assert 'f"{uid}:{request.idempotency_key}"' in ROUTE
    assert 'if existing.exists:return' in ROUTE


def test_emergency_cancels_every_open_order_before_closing_positions():
    cancel_all = ROUTE.index('for order in client.open_orders():')
    submit = ROUTE.index('execute_aster_leg(')
    assert cancel_all < submit
    assert 'is_exposure_order(row)' not in ROUTE[ROUTE.index('@app.post("/v1/me/aster/automation/close-all")'):]


def test_emergency_close_is_independent_from_portfolio_profit_and_quote_state():
    route = ROUTE[ROUTE.index('@app.post("/v1/me/aster/automation/close-all")'):]
    assert '_portfolio_growth_estimate(user,persist_quote=False)' not in route
    assert 'quote_data' not in route
    assert 'safe_float(preview.get("difference"))<=0' not in route
    assert '"emergency":True' in route


def test_partial_failure_never_writes_a_new_baseline():
    failure = ROUTE[ROUTE.rindex('except Exception as exc:'):]
    assert '"PARTIAL_FAIL_CLOSED"' in failure
    assert '"baseline"' not in failure


def test_existing_baseline_is_only_updated_after_confirmed_flat_positions_and_orders():
    flat_positions = ROUTE.index('if remaining:')
    flat_orders = ROUTE.index('if remaining_orders:')
    baseline = ROUTE.index('"baseline":final_equity')
    assert flat_positions < flat_orders < baseline
    assert 'if old>0 and final_equity>0:' in ROUTE
    assert 'emergency Close All never creates one' in ROUTE


def test_success_keeps_both_bots_off_and_audits_confirmed_flat_close():
    assert '"botPaused":True' in ROUTE
    assert '"asterEnabled":False' in ROUTE
    assert '"sniperEnabled":False' in ROUTE
    assert '"openPositions":0' in ROUTE
    assert '"confirmedReportedFees":actual_fees' in ROUTE
    assert '"event":"CLOSE_ALL_CONFIRMED_FLAT"' in ROUTE


def test_live_flag_is_centrally_required():
    assert 'ASTER_LIVE_EXECUTION_ENABLED' in ROUTE
    assert 'raise HTTPException(423' in ROUTE


def test_close_all_waits_for_shared_account_execution_gate():
    route = ROUTE[ROUTE.index('@app.post("/v1/me/aster/automation/close-all")'):]
    assert '_acquire_aster_account_coordination(uid,"EMERGENCY","CLOSE_ALL")' in route
    assert '_release_aster_account_coordination(uid,str(account_token))' in route
    assert '"phase":"EMERGENCY_STOP"' in route
