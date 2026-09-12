from pathlib import Path

SOURCE = Path(__file__).with_name('main.py').read_text()


def _dynamic_dispatch_block() -> str:
    start = SOURCE.index('if bool(dynamic_stored.get("enabled",False)):')
    end = SOURCE.index('    return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings', start)
    return SOURCE[start:end]


def test_dynamic_hedge_does_not_claim_every_position_on_smaller_side():
    block = _dynamic_dispatch_block()
    assert 'blocked_side="SHORT" if long_exposure>short_exposure' not in block
    assert 'blocked_side=""' in block


def test_dynamic_hedge_still_fail_closes_each_strategy_order_through_guard():
    block = _dynamic_dispatch_block()
    assert 'dynamic_strategy_order_guard(dynamic_ref,intent,account,positions)' in block
    assert 'before_order=dynamic_before_order' in block
