from pathlib import Path

SIMPLE = Path('cloud_api/test_focus_simple_deterministic_flow.py')
TRAIL = Path('cloud_api/test_aster_strategy2_focus_trailing.py')


def replace_between(text: str, start: str, end: str, replacement: str, label: str) -> str:
    a = text.find(start)
    b = text.find(end, a + len(start)) if a >= 0 else -1
    if a < 0 or b < 0:
        raise SystemExit(f'{label}: markers not found')
    return text[:a] + replacement + text[b:]


simple = SIMPLE.read_text(encoding='utf-8')
old = '''def test_simple_flow_contract_has_no_fixed_release_gate():
    source = Path(focus.__file__).read_text(encoding='utf-8')
    assert 'release_allowed = (price_release_ready and net_green_ready and reserve_release_ready) if simple_flow' in source
    assert 'cycleStatus": "DCA_HEDGE_SYNC_PENDING"' in source
    assert 'target_qty_after = fresh_primary_qty * configured_hedge_ratio' in source
    assert 'fresh_hedge_qty' in source
    assert 'FOCUS_DCA_BLOCKED' in source
    assert 'FOCUS_HEDGE_RELEASED_NET_GREEN' in source
'''
new = '''def test_simple_flow_contract_is_mechanical_release_plus_full_rehedge():
    source = Path(focus.__file__).read_text(encoding='utf-8')
    release = source.split('# v7 mechanical SHORT release.', 1)[1].split('# Legacy non-simple Focus TP only.', 1)[0]
    assert 'net_green_ready' not in release
    assert 'protectionReserveReady' not in release
    assert 'price_release_ready = last_dca > 0 and hedge_release_crossed' in release
    assert 'FOCUS_HEDGE_RELEASED_MECHANICAL' in release
    assert 'reHedgeArmed' in release and 'reHedgePrice' in release
    assert 'cycleStatus": "DCA_HEDGE_SYNC_PENDING"' in source
    assert 'target_qty_after = fresh_primary_qty * configured_hedge_ratio' in source
    assert 'fresh_hedge_qty' in source
    assert 'FOCUS_DCA_BLOCKED' in source
'''
if old not in simple:
    raise SystemExit('simple contract test not found')
simple = simple.replace(old, new, 1)
SIMPLE.write_text(simple, encoding='utf-8')

trail = TRAIL.read_text(encoding='utf-8')
trail = trail.replace('    take_profit_reached,\n', '    take_profit_reached,\n    portfolio_target_reached,\n', 1)

trail = replace_between(
    trail,
    'def test_runtime_source_contains_v6_start_hedge_full_tp_and_no_frozen_release_trigger():',
    'def test_v6_configurable_start_hedge_margin_amounts_and_full_tp():',
    '''def test_runtime_source_contains_v7_portfolio_cycle_and_mechanical_release():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'DCA_TRAILING = "TRAILING"' in src
    assert '"lastDcaFillPrice"' in src
    assert '"hedgeReleasePrice"' in src
    assert "hedge_release_crossed(mark, release_price, primary_side)" in src
    assert "fresh_primary_qty * configured_hedge_ratio" in src
    assert "FOCUS_HEDGE_RELEASED_MECHANICAL" in src
    assert "FOCUS_REHEDGE_ACTIVE" in src
    assert "FOCUS_V2_START_HEDGED" in src
    assert "def portfolio_target_reached" in src
    assert "FOCUS_PORTFOLIO_TARGET_CLOSED" in src
    assert "target_now = bool(simple_flow" in src
    assert "distance >= release_ratio" not in src
    assert "recovery_confirmed" not in src


''',
    'runtime contract test',
)

trail = replace_between(
    trail,
    'def test_v6_source_guards_full_tp_until_hedge_is_flat_and_persists_restart_boundary():',
    'def test_precision_retry_is_bounded_and_rebuilds_plan():',
    '''def test_v7_source_prioritizes_portfolio_exit_and_persists_restart_boundary():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    assert 'target_now = bool(simple_flow' in src
    assert '"cycleStatus": "PORTFOLIO_EXIT_EXECUTING"' in src
    assert src.index('target_now = bool(simple_flow') < src.index('# Hard invariant: a confirmed LONG DCA')
    assert 'confirmed = client.position_risk(symbol)' in src
    assert 'focusV2LastCycle=last_cycle' in src
    assert '"pausedAfterTp": True' in src


''',
    'portfolio source guard test',
)

# This test is about trailing while hedge remains active; keep release deliberately far away.
trail = trail.replace(
    'settings = _v6_settings(focusV2AmountsAreMargin=False, focusDcaDistance=.003)\n',
    'settings = _v6_settings(focusV2AmountsAreMargin=False, focusDcaDistance=.003, focusV2HedgeReleaseRecoveryPct=.24)\n',
    1,
)

trail = replace_between(
    trail,
    'def test_v6_full_tp_is_blocked_by_hedge_and_closes_when_flat(monkeypatch):',
    'def test_v6_auto_restart_boundary_is_persisted_and_next_tick_reopens_same_margin(monkeypatch):',
    '''def test_v7_portfolio_target_closes_hedge_and_primary_even_when_hedged(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    positions = [_pos("LONG", 1, 100, 101, 1), _pos("SHORT", 1, 100, 101, -1)]
    client = _RuntimeClient(positions, 101)
    calls = []
    def close(**kw):
        calls.append((kw["side"], kw["action"]))
        if kw["side"] == "SHORT":
            client.positions = [row for row in client.positions if row["positionSide"] != "SHORT"]
        else:
            client.positions = [row for row in client.positions if row["positionSide"] != "LONG"]
        return (1.0, 101.0, f"cid-{len(calls)}", f"oid-{len(calls)}")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", close)
    raw = {"focusV2State": {"cycleId": "c", "symbol": "BTCUSDT", "primarySide": "LONG",
        "dcaCount": 1, "lastDcaFillPrice": 100, "trailingHigh": 101, "hedgeState": "ACTIVE",
        "cycleStartEquity": 500, "stateMachineVersion": 7}}
    ref = _Ref()
    result = engine.run_focus_v2_live_step(
        client=client, ref=ref, raw_state=raw, settings=_v6_settings(focusV2TakeProfitValue=10), uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"},
        positions=positions, timestamp_ms=3, order_budget=2)
    assert result["action"] == "FOCUS_PORTFOLIO_TARGET_CLOSED"
    assert calls == [("SHORT", "CLOSE"), ("LONG", "CLOSE")]
    assert result["autoRestart"] is True


''',
    'portfolio closes both test',
)

trail = replace_between(
    trail,
    'def test_v6_auto_restart_boundary_is_persisted_and_next_tick_reopens_same_margin(monkeypatch):',
    'def test_v6_dca_adds_long_then_tops_short_only_to_total_target(monkeypatch):',
    '''def test_v7_portfolio_target_restart_boundary_and_next_tick_reopens_same_margin(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    monkeypatch.setattr(engine, "_resolved_leverage", lambda *_a, **_k: 100)
    settings = _v6_settings(focusV2TakeProfitValue=10)
    flat = [_pos("LONG", 1, 100, 101, 1)]
    client = _RuntimeClient(flat, 101)
    def close(**kw):
        client.positions = []
        return (1.0, 101.0, "tp-cid", "tp-oid")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", close)
    ref = _Ref(); raw = {"focusV2State": {"cycleId": "old", "symbol": "BTCUSDT", "primarySide": "LONG",
        "dcaCount": 0, "lastDcaFillPrice": 0, "trailingHigh": 101, "nextDcaPrice": 100.697,
        "hedgeState": "OFF", "cycleStartEquity": 500, "stateMachineVersion": 7}}
    result = engine.run_focus_v2_live_step(client=client, ref=ref, raw_state=raw, settings=settings, uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"}, positions=flat, timestamp_ms=10)
    assert result["action"] == "FOCUS_PORTFOLIO_TARGET_CLOSED"
    boundary = ref.values[-1]["focusV2State"]
    assert boundary["cycleStatus"] == "RESTARTING" and boundary["restartPending"] is True and boundary["cycleId"] == ""

    opens = []
    client2 = _RuntimeClient([], 101)
    def open_order(**kw):
        opens.append((kw["side"], kw["action"], kw["notional"]))
        qty = kw["notional"] / kw["mark"]
        if kw["side"] == "LONG":
            client2.positions = [_pos("LONG", qty, kw["mark"], kw["mark"])]
        else:
            long_row = next(row for row in client2.positions if row["positionSide"] == "LONG")
            client2.positions = [long_row, _pos("SHORT", qty, kw["mark"], kw["mark"])]
        return (qty, kw["mark"], f"cid-{len(opens)}", f"oid-{len(opens)}")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", open_order)
    ref2 = _Ref()
    again = engine.run_focus_v2_live_step(client=client2, ref=ref2, raw_state={"focusV2State": boundary}, settings=settings, uid="u",
        account={"totalMarginBalance": "510", "availableBalance": "400", "totalMaintMargin": "0"}, positions=[], timestamp_ms=11)
    assert again["action"] == "FOCUS_V2_START_HEDGED"
    assert opens == [("LONG", "OPEN", 7000.0), ("SHORT", "OPEN", 7000.0)]
    assert ref2.values[-1]["focusV2State"]["restartPending"] is False
    assert ref2.values[-1]["focusV2State"]["cycleStartEquity"] == pytest.approx(510.0)


''',
    'portfolio restart test',
)

# Replace old source requirement for green+reserve with the new exact mechanical rule.
trail = replace_between(
    trail,
    'def test_v6_short_release_requires_last_dca_plus_point15_and_net_green():',
    'def test_v6_release_is_blocked_when_price_ready_but_short_net_red(monkeypatch):',
    '''def test_v7_short_release_requires_only_last_buy_plus_point15():
    from pathlib import Path
    src = (Path(__file__).resolve().parent / "aster_strategy2_focus_trailing.py").read_text()
    gate = src.index('price_release_ready = last_dca > 0 and hedge_release_crossed')
    mechanical = src.index('if price_release_ready:', gate)
    end = src.index('# Legacy non-simple Focus TP only.', mechanical)
    section = src[gate:end]
    assert mechanical > gate
    assert 'net_green_ready' not in section
    assert 'protectionReserveReady' not in section
    assert 'FOCUS_HEDGE_RELEASED_MECHANICAL' in section


''',
    'mechanical source release test',
)

# The next old runtime test explicitly asserted a red short blocked release. In v7 that is invalid;
# replace it through the next test marker with a direct mechanical-red release expectation.
trail = replace_between(
    trail,
    'def test_v6_release_is_blocked_when_price_ready_but_short_net_red(monkeypatch):',
    'def test_v6_release_happens_when_price_ready_and_short_net_green(monkeypatch):',
    '''def test_v7_release_happens_at_price_even_if_short_net_red(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    calls = []
    positions = [_pos("LONG", 70, 100, 100.15), _pos("SHORT", 70, 99, 100.15)]
    client = _RuntimeClient(positions, 100.15)
    def execute(**kw):
        calls.append(kw)
        client.positions = [row for row in client.positions if row["positionSide"] != "SHORT"]
        return (70, 100.15, "cid", "oid")
    monkeypatch.setattr(engine, "_execute_with_precision_retry", execute)
    raw = {"focusV2State": {"cycleId": "c", "symbol": "BTCUSDT", "primarySide": "LONG", "dcaCount": 1,
        "lastDcaFillPrice": 100, "trailingHigh": 100.15, "nextDcaPrice": 99.7, "hedgeReleasePrice": 100.15,
        "hedgeState": "ACTIVE", "cycleStatus": "HEDGED", "cycleStartEquity": 500, "stateMachineVersion": 7}}
    ref = _Ref()
    result = engine.run_focus_v2_live_step(client=client, ref=ref, raw_state=raw, settings=_v6_settings(), uid="u",
        account={"totalMarginBalance": "500", "availableBalance": "400", "totalMaintMargin": "0"}, positions=positions, timestamp_ms=400, order_budget=2)
    assert len(calls) == 1 and calls[0]["action"] == "CLOSE" and calls[0]["side"] == "SHORT"
    assert result["action"] == "FOCUS_HEDGE_RELEASED_MECHANICAL"
    saved = ref.values[-1]["focusV2State"]
    assert saved["reHedgeArmed"] is True and saved["reHedgePrice"] == pytest.approx(100)


''',
    'red short release runtime test',
)

# Rename green release test; its behavior remains a valid subset of mechanical release.
trail = trail.replace('def test_v6_release_happens_when_price_ready_and_short_net_green(monkeypatch):', 'def test_v7_release_also_happens_when_short_is_green(monkeypatch):', 1)
trail = trail.replace('assert result["action"]=="FOCUS_HEDGE_RELEASED_NET_GREEN"', 'assert result["action"]=="FOCUS_HEDGE_RELEASED_MECHANICAL"')

# Reserve is deliberately NOT a release gate in v7.
start = 'def test_v6_release_is_blocked_when_protection_reserve_is_not_ready(monkeypatch):'
idx = trail.find(start)
if idx < 0:
    raise SystemExit('reserve test marker not found')
next_idx = trail.find('\ndef ', idx + len(start))
if next_idx < 0:
    next_idx = len(trail)
replacement = '''def test_v7_release_ignores_old_protection_reserve_gate(monkeypatch):
    import aster_strategy2_focus_trailing as engine
    monkeypatch.setattr(engine, "_selected_symbol", lambda *_a, **_k: "BTCUSDT")
    calls = []
    positions = [_pos("LONG",70,100,100.15), _pos("SHORT",70,101,100.15)]
    client = _RuntimeClient(positions,100.15)
    def execute(**kw):
        calls.append(kw)
        client.positions = [row for row in client.positions if row["positionSide"] != "SHORT"]
        return (70,100.15,"cid","oid")
    monkeypatch.setattr(engine,"_execute_with_precision_retry",execute)
    raw={"focusV2State":{"cycleId":"c","symbol":"BTCUSDT","primarySide":"LONG","dcaCount":1,
         "lastDcaFillPrice":100,"trailingHigh":100.15,"nextDcaPrice":99.7,"hedgeReleasePrice":100.15,
         "hedgeState":"ACTIVE","cycleStatus":"HEDGED","cycleStartEquity":500,"stateMachineVersion":7}}
    ref=_Ref()
    result=engine.run_focus_v2_live_step(client=client,ref=ref,raw_state=raw,
        settings=_v6_settings(focusProtectionReserveBufferPct=.05),uid="u",
        account={"totalMarginBalance":"500","availableBalance":"50","totalMaintMargin":"0"},
        positions=positions,timestamp_ms=401,order_budget=2)
    assert len(calls)==1 and calls[0]["action"]=="CLOSE"
    assert result["action"]=="FOCUS_HEDGE_RELEASED_MECHANICAL"
'''
trail = trail[:idx] + replacement + trail[next_idx:]

TRAIL.write_text(trail, encoding='utf-8')
print('Focus portfolio-cycle v7 legacy contract tests updated')
