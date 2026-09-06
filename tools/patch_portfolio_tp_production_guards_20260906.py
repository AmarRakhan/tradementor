from __future__ import annotations

from pathlib import Path
import re

MAIN = Path("cloud_api/main.py")
PORTFOLIO = Path("cloud_api/aster_multi_bb_portfolio.py")

main = MAIN.read_text()

save_pattern = re.compile(
    r'@app\.put\("/v1/me/aster/strategy2/settings"\)\n'
    r'def save_aster_strategy2_settings\(.*?(?=\n\n@app\.)',
    re.S,
)
new_save = '''@app.put("/v1/me/aster/strategy2/settings")
def save_aster_strategy2_settings(request: AsterStrategySettingsRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); existing=ref.get().to_dict() or {}; old=existing.get("settings") if isinstance(existing.get("settings"),dict) else {}
    try: candidate=MultiBbConfig.from_mapping(request.settings)
    except ValueError as exc: raise HTTPException(422,str(exc)) from exc
    version=max(int(safe_float(existing.get("configVersion"))),candidate.version)+1
    saved=MultiBbConfig.from_mapping({**candidate.public_dict(),"version":version}); now=datetime.now(timezone.utc)
    switching=str(old.get("engine",old.get("strategyKind","")))!=MULTI_BB_ENGINE
    if switching:
        # Engine migration is the only settings save that is allowed to build a
        # clean state. Existing Multi BB accounts never pass through this path.
        update={"settings":saved.public_dict(),"configVersion":version,"updatedAt":now,"phase":"CONFIGURED",
            "lastReason":"Nieuwe Multi DCA-strategie opgeslagen; start de bot handmatig wanneer je klaar bent",
            "multiBbReport":{},"pendingReopens":[],"focusLiveState":{},"focusLiveSlots":[],"focusV2State":{},"focusV2History":{},
            "moneyGrabberActivated":False,"moneyGrabberRound":None,"moneyGrabberPairs":[],
            "enabled":False,"monitor":False,"multiBbPositions":{}}
    else:
        # Live config edits are deliberately state-preserving. In particular:
        # no phase reset, no DCA reset, no position reset, no baseline reset and
        # no clearing of recovery/asymmetric state.
        update={"settings":saved.public_dict(),"configVersion":version,"updatedAt":now,"settingsChangedAt":now,
            "lastReason":"Multi DCA-instellingen live bijgewerkt; actieve positie-, DCA- en cycle-state behouden"}
    ref.set(update,merge=True)
    ref.collection("configHistory").add({"version":version,"oldValue":old,"newValue":saved.public_dict(),"source":"user-multi-bb-v1","timestamp":now})

    # Switching to Portfolio while the bot is live gets an immediate protected
    # evaluation instead of waiting for the next scheduler minute. The same
    # account-scoped lease used by the scheduler serializes this with DCA/TP.
    immediate=None
    if not switching and bool(existing.get("enabled",False)) and saved.take_profit_mode=="PORTFOLIO":
        latest=ref.get().to_dict() or {};queue_enabled=_strategy2_order_queue_enabled(latest)
        if queue_enabled:
            token=_acquire_strategy2_queue_lease(ref)
            if token:
                try: immediate=_run_aster_strategy2_queue_scan(uid,maximum_orders=MAX_ORDERS_PER_ACCOUNT_SCAN)
                finally: _release_strategy2_queue_lease(ref,str(token))
            else:
                immediate={"status":"lease-busy","reason":"Bestaande Strategy-2-worker verwerkt de zojuist opgeslagen Portfolio-modus"}
        elif _acquire_mexc_automation_lease(ref):
            try: immediate=_run_aster_strategy2_tick(uid)
            finally: ref.set({"leaseUntil":datetime.now(timezone.utc)},merge=True)
        else:
            immediate={"status":"lease-busy","reason":"Bestaande Strategy-2-worker verwerkt de zojuist opgeslagen Portfolio-modus"}
    return {"saved":True,"activeStatePreserved":not switching,"immediateEvaluation":immediate,**aster_strategy2_public(uid)}
'''
main, count = save_pattern.subn(new_save.rstrip(), main, count=1)
if count != 1:
    raise SystemExit(f"settings function patch count={count}")

stop_pattern = re.compile(
    r'@app\.post\("/v1/me/aster/strategy2/stop"\)\n'
    r'def stop_aster_strategy2\(.*?(?=\n\n@app\.)',
    re.S,
)
new_stop = '''@app.post("/v1/me/aster/strategy2/stop")
def stop_aster_strategy2(request: AsterStrategyStopRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm: raise HTTPException(422,"Bevestig veilig stoppen")
    uid=str(user["uid"]); ref=aster_strategy2_reference(uid); raw=ref.get().to_dict() or {}
    cycle=raw.get("multiBbCycle") if isinstance(raw.get("multiBbCycle"),dict) else {}
    cycle_status=str(cycle.get("cycleStatus","")).upper()
    exit_in_progress=cycle_status in {"PORTFOLIO_TP_EXECUTING","FLAT_CONFIRMING"}
    # User intent to stop wins for *new* exposure immediately. If a transactional
    # Portfolio exit is already active, monitoring stays alive only to finish the
    # close/reconciliation; the flat-confirmed branch then turns monitor off.
    ref.set({"enabled":False,"monitor":exit_in_progress,
        "phase":cycle_status if exit_in_progress else "STOPPED","pendingReopens":[],
        "lastReason":("Bot UIT; lopende Portfolio-exit wordt alleen nog veilig tot FLAT_CONFIRMED afgerond"
            if exit_in_progress else "Multi BB handmatig gestopt; er worden geen automatische orders geplaatst"),
        "updatedAt":datetime.now(timezone.utc)},merge=True)
    return {"stopped":True,"finishingPortfolioExit":exit_in_progress,**aster_strategy2_public(uid)}
'''
main, count = stop_pattern.subn(new_stop.rstrip(), main, count=1)
if count != 1:
    raise SystemExit(f"stop function patch count={count}")

old_queue_guard = '''    if not bool(raw.get("enabled",False)) and not (raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []) and not current_intent:
        return {"status":"stopped-flat","scanId":scan_id,"ordersSent":0,"ordersUsed":0,"maximumOrders":scan_limit,"actions":[]}'''
new_queue_guard = '''    cycle=raw.get("multiBbCycle") if isinstance(raw.get("multiBbCycle"),dict) else {}
    portfolio_exit_active=str(cycle.get("cycleStatus","")).upper() in {"PORTFOLIO_TP_EXECUTING","FLAT_CONFIRMING"}
    if not bool(raw.get("enabled",False)) and not portfolio_exit_active and not (raw.get("ownedLegs") if isinstance(raw.get("ownedLegs"),list) else []) and not current_intent:
        return {"status":"stopped-flat","scanId":scan_id,"ordersSent":0,"ordersUsed":0,"maximumOrders":scan_limit,"actions":[]}'''
if old_queue_guard not in main:
    raise SystemExit("queue stopped-flat guard not found")
main = main.replace(old_queue_guard, new_queue_guard, 1)
MAIN.write_text(main)

portfolio = PORTFOLIO.read_text()
old_flat = '''        _write_cycle(ref, cycle, phase=FLAT_CONFIRMED,
                     reason="Portfolio TP afgerond en exchange flat; bot staat UIT dus geen herstart", extra=base_extra)'''
new_flat = '''        _write_cycle(ref, cycle, phase=FLAT_CONFIRMED,
                     reason="Portfolio TP afgerond en exchange flat; bot staat UIT dus geen herstart",
                     extra={**base_extra, "monitor": False})'''
if old_flat not in portfolio:
    raise SystemExit("portfolio bot-off flat branch not found")
portfolio = portfolio.replace(old_flat, new_flat, 1)

# Linearize Portfolio->Per trade/OFF races. If the config save wins before the
# durable exit transition, the stale worker must not start the portfolio exit.
old_trigger = '''    status = str(cycle.get("cycleStatus") or RUNNING).upper()
    target = _f(cycle.get("targetEquity"))
    triggered = mode == "PORTFOLIO" and target > 0 and equity >= target
    if status == RUNNING and triggered:
        cycle.update({"cycleStatus": PORTFOLIO_TP_EXECUTING,'''
new_trigger = '''    status = str(cycle.get("cycleStatus") or RUNNING).upper()
    target = _f(cycle.get("targetEquity"))
    if status == RUNNING and mode == "PORTFOLIO":
        latest = ref.get().to_dict() or {}
        latest_settings = latest.get("settings") if isinstance(latest.get("settings"), dict) else {}
        latest_mode = str(latest_settings.get("takeProfitMode", "PER_TRADE")).upper()
        if latest_mode != "PORTFOLIO":
            mode = latest_mode
        else:
            portfolio_tp_percent = _f(latest_settings.get("portfolioTpPercent"), portfolio_tp_percent)
            target = target_equity(_f(cycle.get("cycleStartEquity")), portfolio_tp_percent)
            cycle["targetEquity"] = target
    triggered = mode == "PORTFOLIO" and target > 0 and equity >= target
    if status == RUNNING and triggered:
        cycle.update({"cycleStatus": PORTFOLIO_TP_EXECUTING,'''
if old_trigger not in portfolio:
    raise SystemExit("portfolio trigger block not found")
portfolio = portfolio.replace(old_trigger, new_trigger, 1)
PORTFOLIO.write_text(portfolio)

print("Portfolio TP production guards patched")
