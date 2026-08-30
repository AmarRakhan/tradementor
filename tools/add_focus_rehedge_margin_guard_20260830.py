from pathlib import Path

engine_path = Path('cloud_api/aster_strategy2_focus_trailing.py')
text = engine_path.read_text(encoding='utf-8')

old = '''        net_green_ready = expected_net_close_pnl > 0.0\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n'''
new = '''        net_green_ready = expected_net_close_pnl > 0.0\n        # Re-hedge funding guard: before releasing protection, conservatively prove\n        # that the margin freed by closing the current hedge plus current available\n        # balance can fund the full hedge again at the persisted last-DCA anchor.\n        release_leverage = max(1, int(_finite((hedge_row or {}).get("leverage"), settings.leverage)))\n        rehedge_target_notional = primary_qty * (last_dca if last_dca > 0 else mark)\n        rehedge_required_margin = rehedge_target_notional / release_leverage\n        released_hedge_margin_estimate = hedge_notional / release_leverage\n        rehedge_available_after_release = max(0.0, _finite(account.get("availableBalance"))) + released_hedge_margin_estimate\n        rehedge_funding_ready = bool(\n            rehedge_target_notional > 0 and\n            rehedge_available_after_release + 1e-9 >= rehedge_required_margin\n        )\n        state["releaseRehedgeMarginReady"] = rehedge_funding_ready\n        state["releaseRehedgeRequiredMargin"] = rehedge_required_margin\n        state["releaseRehedgeAvailableAfterCloseEstimate"] = rehedge_available_after_release\n        state["shortReleasePriceReady"] = bool(price_release_ready)\n'''
if old not in text:
    raise SystemExit('release insertion point not found')
text = text.replace(old, new, 1)

old = '''        if price_release_ready and net_green_ready:\n'''
new = '''        if price_release_ready and net_green_ready and rehedge_funding_ready:\n'''
if old not in text:
    raise SystemExit('release gate not found')
text = text.replace(old, new, 1)

old = '''                "lastReason": ("releaseprijs nog niet geraakt" if not price_release_ready else\n                    ("SHORT nog niet netto groen na kostenbuffer" if not net_green_ready else\n                     "equity onder cycleStartEquity; hedge mag niet worden verlaagd")),\n'''
new = '''                "lastReason": ("releaseprijs nog niet geraakt" if not price_release_ready else\n                    ("SHORT nog niet netto groen na kostenbuffer" if not net_green_ready else\n                     ("re-hedge na release niet financierbaar met beschikbare + vrijvallende SHORT-margin" if not rehedge_funding_ready else\n                      "release wacht op uitvoerbare voorwaarden"))),\n'''
if old not in text:
    raise SystemExit('release hold reason not found')
text = text.replace(old, new, 1)

old = '''        hq, hp, hcid, hoid = _execute_with_precision_retry(\n            client=client, symbol=symbol, mark=mark, notional=target_qty * mark, leverage=leverage,\n            side=hedge_side, action="OPEN", prefix=_prefix(str(state.get("cycleId")), int(_finite(state.get("dcaCount"))), "REHEDGE"),\n            new_position_leverage=leverage,\n        )\n'''
new = '''        rehedge_required_margin_live = (target_qty * mark) / max(1, leverage)\n        rehedge_available_live = max(0.0, _finite(account.get("availableBalance")))\n        if rehedge_required_margin_live > rehedge_available_live + 1e-9:\n            state.update({\n                "cycleStatus": "REHEDGE_WAIT_MARGIN",\n                "lastAction": "REHEDGE_WAIT_MARGIN",\n                "lastReason": "re-hedge trigger geraakt maar actuele Aster available margin is nog onvoldoende; trigger blijft armed",\n                "reHedgeArmed": True,\n                "reHedgePrice": rehedge_price,\n                "rehedgeRequiredMargin": rehedge_required_margin_live,\n                "rehedgeAvailableMargin": rehedge_available_live,\n            })\n            _persist(ref, state, owned)\n            _audit(ref, "FOCUS_REHEDGE_WAIT_MARGIN", cycleId=state.get("cycleId"), symbol=symbol,\n                reHedgePrice=rehedge_price, requiredMargin=rehedge_required_margin_live, availableMargin=rehedge_available_live)\n            return {\n                "status": "waiting", "action": "REHEDGE_WAIT_MARGIN", "ordersSent": 0,\n                "reHedgePrice": rehedge_price, "requiredMargin": rehedge_required_margin_live,\n                "availableMargin": rehedge_available_live,\n            }\n        hq, hp, hcid, hoid = _execute_with_precision_retry(\n            client=client, symbol=symbol, mark=mark, notional=target_qty * mark, leverage=leverage,\n            side=hedge_side, action="OPEN", prefix=_prefix(str(state.get("cycleId")), int(_finite(state.get("dcaCount"))), "REHEDGE"),\n            new_position_leverage=leverage,\n        )\n'''
if old not in text:
    raise SystemExit('rehedge open block not found')
text = text.replace(old, new, 1)

text = text.replace(
    'if price_release_ready and net_green_ready:',
    'if price_release_ready and net_green_ready and rehedge_funding_ready:'
)
engine_path.write_text(text, encoding='utf-8')

# Migrate regression tests to the approved technical safety guard only.
for rel in [
    'cloud_api/test_aster_strategy2_focus_trailing.py',
    'cloud_api/test_focus_portfolio_cycle_v7.py',
    'cloud_api/test_focus_v7_net_green_release.py',
]:
    p = Path(rel)
    if not p.exists():
        continue
    s = p.read_text(encoding='utf-8')
    s = s.replace(
        'price_release_ready and net_green_ready:',
        'price_release_ready and net_green_ready and rehedge_funding_ready:'
    )
    s = s.replace(
        'price_release_ready and net_green_ready"',
        'price_release_ready and net_green_ready and rehedge_funding_ready"'
    )
    p.write_text(s, encoding='utf-8')

# Deployment verification must validate the new guard rather than the older 2-condition literal.
deploy_path = Path('.github/workflows/deploy-focus-portfolio-v7-production-20260830.yml')
deploy = deploy_path.read_text(encoding='utf-8')
deploy = deploy.replace(
    "grep -q 'if price_release_ready and net_green_ready:' cloud_api/aster_strategy2_focus_trailing.py",
    "grep -q 'if price_release_ready and net_green_ready and rehedge_funding_ready:' cloud_api/aster_strategy2_focus_trailing.py\n          grep -q 'REHEDGE_WAIT_MARGIN' cloud_api/aster_strategy2_focus_trailing.py"
)
deploy_path.write_text(deploy, encoding='utf-8')

# Trigger the verified production deploy after this safety-only patch passes tests.
marker_path = Path('.deploy/focus-portfolio-v7-20260830')
marker = marker_path.read_text(encoding='utf-8')
marker += '\nRe-hedge margin safety guard: release only when full re-hedge is financeable from current available + conservatively estimated freed hedge margin; runtime re-hedge keeps trigger armed if live available margin is insufficient. No DCA/release distance/portfolio target changes.\n'
marker_path.write_text(marker, encoding='utf-8')

print('Applied re-hedge margin safety guard without changing Strategy-2 distances or portfolio target logic.')
