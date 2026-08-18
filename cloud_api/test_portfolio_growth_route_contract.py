"""Static safety-contract tests for the account-scoped close-all route.

These tests never instantiate an exchange client and therefore can never emit
an order.  They pin the orchestration invariants around the pure arithmetic
tests in test_portfolio_growth.py.
"""
from pathlib import Path


SOURCE = Path(__file__).with_name("main.py").read_text(encoding="utf-8")
ROUTE = SOURCE[SOURCE.index('def _portfolio_growth_client'):SOURCE.index('@app.post("/v1/me/aster/positions/{symbol}/close")')]


def test_state_is_strictly_nested_below_authenticated_uid():
    assert 'portfolio_growth_reference(uid)' in ROUTE
    assert 'collection("users").document(uid).collection("portfolioGrowth")' in SOURCE
    assert 'quote_data.get("uid")!=uid' in ROUTE


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
    assert 'aster_automation_reference(uid)' in ROUTE
    assert 'aster_strategy2_reference(uid)' in ROUTE
    assert 'aster_strategy3_reference(uid)' in ROUTE


def test_idempotency_is_bound_to_account_and_key():
    assert 'f"{uid}:{request.idempotency_key}"' in ROUTE
    assert 'if existing.exists:return' in ROUTE


def test_entry_orders_are_cancelled_but_unknown_orders_fail_closed():
    assert 'if unknown:raise RuntimeError' in ROUTE
    assert 'if is_exposure_order(row) is True' in ROUTE


def test_exchange_truth_is_refetched_after_lock_before_any_close():
    recalc = ROUTE.index('_portfolio_growth_estimate(user,persist_quote=False)')
    submit = ROUTE.index('execute_aster_leg(')
    assert recalc < submit
    assert 'safe_float(preview.get("difference"))<=0' in ROUTE


def test_partial_failure_never_writes_a_new_baseline():
    failure = ROUTE[ROUTE.rindex('except Exception as exc:'):]
    assert '"PARTIAL_FAIL_CLOSED"' in failure
    assert '"baseline"' not in failure


def test_new_baseline_requires_confirmed_flat_positions_and_orders():
    flat_positions = ROUTE.index('if remaining:')
    flat_orders = ROUTE.index('if remaining_orders:')
    baseline = ROUTE.index('"baseline":final_equity')
    assert flat_positions < flat_orders < baseline


def test_success_keeps_bot_paused_and_audits_costs():
    assert '"botPaused":True' in ROUTE
    assert '"confirmedReportedFees":actual_fees' in ROUTE
    assert '"slippageBuffer":safe_float(preview.get("slippageBuffer"))' in ROUTE


def test_live_flag_is_centrally_required():
    assert 'ASTER_LIVE_EXECUTION_ENABLED' in ROUTE
    assert 'raise HTTPException(423' in ROUTE
