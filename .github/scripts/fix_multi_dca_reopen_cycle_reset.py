from pathlib import Path

p = Path('cloud_api/aster_multi_bb.py')
text = p.read_text(encoding='utf-8')

marker = '''def _position_map(positions: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:\n'''
helper = '''def _manual_reopen_boundary(client: Any, symbol: str, side: str, state: dict[str, Any]) -> bool:\n    """Return True only when Aster fills prove the old cycle went flat and reopened."""\n    start = _i(state.get("cycleStartedAtMs"))\n    if start <= 0:\n        return False\n    try:\n        fills = sorted(client.user_trades(symbol, start_time=max(0, start - 1000), limit=1000), key=lambda x: _i(x.get("time", x.get("timestamp", x.get("timestampMs")))))\n    except Exception:\n        return False\n    running = 0.0\n    was_open = False\n    went_flat = False\n    for fill in fills:\n        position_side = str(fill.get("positionSide", side)).upper()\n        if position_side not in {side, "BOTH"}:\n            continue\n        trade_side = str(fill.get("side", "")).upper()\n        qty = abs(_f(fill.get("qty", fill.get("quantity", fill.get("executedQty")))))\n        if qty <= 0 or trade_side not in {"BUY", "SELL"}:\n            continue\n        delta = qty if (side == "LONG" and trade_side == "BUY") or (side == "SHORT" and trade_side == "SELL") else -qty\n        running = max(0.0, running + delta)\n        if running > 1e-12:\n            if went_flat:\n                return True\n            was_open = True\n        elif was_open:\n            went_flat = True\n    return False\n\n\n'''
if helper not in text:
    if marker not in text: raise SystemExit('position map marker missing')
    text = text.replace(marker, helper + marker, 1)

old = '''        st = dict(state[key]); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); leverage = max(1, _i(row.get("leverage"), st.get("leverage", 1)))\n        if abs(qty - _f(st.get("lastKnownQty"))) > 1e-12 or abs(entry - _f(st.get("lastKnownEntry"))) > 1e-12:\n            st["manualOrExchangeReconciledAtMs"] = timestamp_ms\n        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})\n'''
new = '''        st = dict(state[key]); qty = abs(_f(row.get("positionAmt"))); entry = _f(row.get("entryPrice")); leverage = max(1, _i(row.get("leverage"), st.get("leverage", 1)))\n        changed = abs(qty - _f(st.get("lastKnownQty"))) > 1e-12 or abs(entry - _f(st.get("lastKnownEntry"))) > 1e-12\n        boundary_check = settings.manual_symbol_selection_enabled and _i(st.get("dcaCount")) > 0 and (bool(raw_state.get("multiBbAdoptionPending")) or not st.get("cycleBoundaryCheckedAtMs") or changed)\n        if boundary_check and _manual_reopen_boundary(client, str(row.get("symbol", "")).upper(), str(row.get("positionSide", "")).upper(), st):\n            old_cycle = str(st.get("cycleId", ""))\n            st = {"cycleId": hashlib.sha256((uid+key+str(timestamp_ms)).encode()).hexdigest()[:16], "dcaCount": 0,\n                "lastBotFillPrice": entry, "lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage,\n                "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "cycleBoundaryCheckedAtMs": timestamp_ms, "botManaged": True}\n            actions.append({"kind": "REENTRY_CYCLE_RESET", "key": key, "oldCycleId": old_cycle, "reason": "Aster fills prove prior cycle went flat before this reopen"})\n        else:\n            if changed:\n                st["manualOrExchangeReconciledAtMs"] = timestamp_ms\n            if boundary_check:\n                st["cycleBoundaryCheckedAtMs"] = timestamp_ms\n            st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})\n'''
if old not in text: raise SystemExit('reconciliation marker missing')
text = text.replace(old, new, 1)
p.write_text(text, encoding='utf-8')

pt = Path('cloud_api/test_aster_multi_bb.py')
t = pt.read_text(encoding='utf-8')
block = r'''


def test_manual_close_and_reopen_same_coin_resets_old_dca_cycle(monkeypatch):
    class ReopenClient(Client):
        def user_trades(self, symbol, start_time=None, limit=1000):
            return [
                {"symbol":"ARBUSDT","positionSide":"LONG","side":"BUY","qty":"1.0","time":1000},
                {"symbol":"ARBUSDT","positionSide":"LONG","side":"BUY","qty":"0.5","time":1100},
                {"symbol":"ARBUSDT","positionSide":"LONG","side":"SELL","qty":"1.5","time":2000},
                {"symbol":"ARBUSDT","positionSide":"LONG","side":"BUY","qty":"0.2","time":3000},
            ]
    pos={"symbol":"ARBUSDT","positionSide":"LONG","positionAmt":"0.2","entryPrice":"110","markPrice":"110","leverage":"20"}
    stale={"multiBbAdoptionPending":True,"multiBbPositions":{"ARBUSDT|LONG":{"cycleId":"old-cycle","dcaCount":5,"lastBotFillPrice":90,"lastKnownQty":1.5,"lastKnownEntry":95,"cycleStartedAtMs":1000,"updatedAtMs":1500,"botManaged":True}}}
    c=ReopenClient(positions=[pos],tickers=[{"symbol":"ARBUSDT","quoteVolume":"100"}],prices={"ARBUSDT":110},leverage=20)
    settings=manual_cfg([{"symbol":"ARBUSDT","side":"LONG"}],minimumLeverage=20,entryMarginUsd=1,maximumPositions=1,longSlots=1,shortSlots=0)
    ref=Ref()
    r=run_multi_bb_step(client=c,ref=ref,raw_state=stale,settings=settings,uid="u",account={"availableBalance":"100","totalMarginBalance":"161"},positions=[pos],open_orders=[],timestamp_ms=4000,dry_run=False)
    fresh=ref.updates[-1]["multiBbPositions"]["ARBUSDT|LONG"]
    assert fresh["cycleId"] != "old-cycle"
    assert fresh["dcaCount"] == 0
    assert fresh["lastBotFillPrice"] == pytest.approx(110)
    assert fresh["nextDcaNumber"] == 1
    assert any(x["kind"]=="REENTRY_CYCLE_RESET" for x in r["actions"])
'''
if 'test_manual_close_and_reopen_same_coin_resets_old_dca_cycle' not in t:
    pt.write_text(t + block, encoding='utf-8')
