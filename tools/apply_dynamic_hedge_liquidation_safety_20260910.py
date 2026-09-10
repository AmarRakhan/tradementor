from pathlib import Path

MAIN = Path("cloud_api/main.py")


def replace_once(text: str, old: str, new: str) -> str:
    if new in text:
        return text
    if old not in text:
        raise SystemExit(f"Expected main.py marker not found: {old[:180]!r}")
    return text.replace(old, new, 1)


def patch_between(text: str, start: str, end: str, old: str, new: str) -> str:
    begin = text.find(start)
    finish = text.find(end, begin + len(start))
    if begin < 0 or finish < 0:
        raise SystemExit(f"Function boundary missing: {start!r} -> {end!r}")
    segment = text[begin:finish]
    if new in segment:
        return text
    if old not in segment:
        raise SystemExit(f"Expected scoped marker not found in {start!r}: {old[:180]!r}")
    segment = segment.replace(old, new, 1)
    return text[:begin] + segment + text[finish:]


text = MAIN.read_text(encoding="utf-8")
text = replace_once(
    text,
    "from aster_hedge_recovery_api import install_aster_hedge_recovery_routes, load_hedge_settings, profit_preview_with_settings\n",
    "from aster_hedge_recovery_api import install_aster_hedge_recovery_routes, load_hedge_settings, profit_preview_with_settings\n"
    "from aster_dynamic_hedge_api import install_aster_dynamic_hedge_routes\n"
    "from aster_dynamic_hedge_manual import begin_manual_action, complete_manual_action, fail_manual_action\n",
)
text = replace_once(
    text,
    "from aster_dynamic_hedge_api import install_aster_dynamic_hedge_routes\n",
    "from aster_dynamic_hedge_api import install_aster_dynamic_hedge_routes\n"
    "from aster_dynamic_hedge_manual import begin_manual_action, complete_manual_action, fail_manual_action\n",
)
text = replace_once(
    text,
    "from aster_dynamic_hedge_manual import begin_manual_action, complete_manual_action, fail_manual_action\n",
    "from aster_dynamic_hedge_manual import begin_manual_action, complete_manual_action, fail_manual_action\n"
    "from aster_dynamic_hedge_execution import run_dynamic_hedge_overlay, dynamic_strategy_order_guard\n",
)

# Profit bulk close: lock Dynamic Hedge before any live close and reconcile exact
# LONG/SHORT quantities from Aster before automation can resume.
profit_start = "def close_profitable_aster_positions("
profit_end = '@app.post("/v1/me/aster/positions/{symbol}/close")'
text = patch_between(
    text, profit_start, profit_end,
    "    closed: list[dict[str, Any]] = []\n",
    "    dynamic_hedge_ref = user_reference(user).collection(\"asterDynamicHedge\").document(\"control\")\n"
    "    manual_guard = None\n"
    "    try:\n"
    "        before_manual_rows = _portfolio_growth_client(user, live=False).position_risk()\n"
    "        manual_guard = begin_manual_action(dynamic_hedge_ref, scope, before_manual_rows)\n"
    "    except Exception as exc:\n"
    "        _release_strategy2_queue_lease(strategy_ref, queue_token)\n"
    "        raise HTTPException(502, \"Dynamic Hedge kon vóór de sluiting niet veilig worden vergrendeld\") from exc\n\n"
    "    closed: list[dict[str, Any]] = []\n",
)
text = patch_between(
    text, profit_start, profit_end,
    "        return {**result, \"duplicate\": False}\n",
    "        after_manual_rows = client.position_risk()\n"
    "        complete_manual_action(dynamic_hedge_ref, manual_guard, after_manual_rows)\n"
    "        return {**result, \"duplicate\": False}\n",
)
text = patch_between(
    text, profit_start, profit_end,
    "    except HTTPException:\n        raise\n",
    "    except HTTPException as exc:\n"
    "        fail_manual_action(dynamic_hedge_ref, manual_guard, str(exc.detail))\n"
    "        raise\n",
)
text = patch_between(
    text, profit_start, profit_end,
    "    except Exception as exc:\n        action_ref.set({\n",
    "    except Exception as exc:\n"
    "        fail_manual_action(dynamic_hedge_ref, manual_guard, str(exc))\n"
    "        action_ref.set({\n",
)

# Single-leg manual close: acquire the lock from the exact pre-close exchange
# snapshot. On success, validate that the opposite side did not move at all.
one_start = "def close_one_aster_position("
one_end = '@app.post("/v1/me/aster/simulate")'
text = patch_between(
    text, one_start, one_end,
    "    try:\n        live_rows = client.position_risk()\n",
    "    dynamic_hedge_ref = user_reference(user).collection(\"asterDynamicHedge\").document(\"control\")\n"
    "    manual_guard = None\n"
    "    try:\n"
    "        live_rows = client.position_risk()\n"
    "        manual_guard = begin_manual_action(dynamic_hedge_ref, request.side, live_rows)\n",
)
text = patch_between(
    text, one_start, one_end,
    "        intent_ref.set({\"status\": \"confirmed_closed\", \"result\": result, \"completedAt\": datetime.now(timezone.utc)}, merge=True)\n",
    "        after_manual_rows = client.position_risk()\n"
    "        complete_manual_action(dynamic_hedge_ref, manual_guard, after_manual_rows)\n"
    "        intent_ref.set({\"status\": \"confirmed_closed\", \"result\": result, \"completedAt\": datetime.now(timezone.utc)}, merge=True)\n",
)
text = patch_between(
    text, one_start, one_end,
    "    except HTTPException as exc:\n        intent_ref.set({\"status\": \"failed_closed\"",
    "    except HTTPException as exc:\n"
    "        fail_manual_action(dynamic_hedge_ref, manual_guard, str(exc.detail))\n"
    "        intent_ref.set({\"status\": \"failed_closed\"",
)
text = patch_between(
    text, one_start, one_end,
    "    except Exception as exc:\n        intent_ref.set({\"status\": \"unknown_fail_closed\"",
    "    except Exception as exc:\n"
    "        fail_manual_action(dynamic_hedge_ref, manual_guard, str(exc))\n"
    "        intent_ref.set({\"status\": \"unknown_fail_closed\"",
)

# Emergency Alles Sluiten: Dynamic Hedge cannot issue a compensating order while
# the account is being flattened. A successful all-flat exchange read returns
# the controller to ADOPTING; any ambiguity intentionally leaves the lock set.
all_start = "def close_all_aster_strategy("
all_end = '@app.get("/v1/me/aster/positions/profitable-close-preview")'
text = patch_between(
    text, all_start, all_end,
    "    client=_portfolio_growth_client(user,live=True);submitted=[]\n",
    "    client=_portfolio_growth_client(user,live=True);submitted=[]\n"
    "    dynamic_hedge_ref = user_reference(user).collection(\"asterDynamicHedge\").document(\"control\")\n"
    "    manual_guard = None\n"
    "    try:\n"
    "        manual_guard = begin_manual_action(dynamic_hedge_ref, \"ALL\", client.position_risk())\n"
    "    except Exception as exc:\n"
    "        raise HTTPException(502, \"Dynamic Hedge kon vóór Alles sluiten niet veilig worden vergrendeld\") from exc\n",
)
text = patch_between(
    text, all_start, all_end,
    "        complete(finish)\n        return {\"actionId\":action_hash,\"status\":\"COMPLETED\"",
    "        complete(finish)\n"
    "        complete_manual_action(dynamic_hedge_ref, manual_guard, remaining)\n"
    "        return {\"actionId\":action_hash,\"status\":\"COMPLETED\"",
)
text = patch_between(
    text, all_start, all_end,
    "    except Exception as exc:\n        action_ref.set({\"status\":\"PARTIAL_FAIL_CLOSED\"",
    "    except Exception as exc:\n"
    "        fail_manual_action(dynamic_hedge_ref, manual_guard, str(exc))\n"
    "        action_ref.set({\"status\":\"PARTIAL_FAIL_CLOSED\"",
)

# Strategy-2 scheduler integration. Dynamic Hedge gets first right of action and
# at most one hedge order per leased tick. Only when the hedge is already inside
# its safe dynamic band may Multi BB continue on the dominant trading side.
strategy_start = "def _run_aster_strategy2_tick("
strategy_end = "def _run_aster_strategy2_queue_scan("
old_run = '''    # The legacy Focus/Strategy-2 planners are retired. The new engine owns all active decisions.\n    return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings,uid=uid,account=account,positions=positions,\n        open_orders=orders,timestamp_ms=int(now.timestamp()*1000),dry_run=dry_run,order_budget=order_budget,before_order=before_order)\n'''
new_run = '''    # The legacy Focus/Strategy-2 planners are retired. Multi BB remains the\n    # dominant-side strategy; Dynamic Hedge exclusively owns the smaller hedge\n    # side while its optional toggle is enabled.\n    dynamic_ref=user_reference({"uid":uid}).collection("asterDynamicHedge").document("control")\n    dynamic_stored=dynamic_ref.get().to_dict() or {}\n    if bool(dynamic_stored.get("enabled",False)):\n        dynamic=run_dynamic_hedge_overlay(client=client,control_ref=dynamic_ref,settings=settings,uid=uid,account=account,\n            positions=positions,open_orders=orders,timestamp_ms=int(now.timestamp()*1000),dry_run=dry_run,order_budget=order_budget,before_order=before_order)\n        ref.set({"dynamicHedgeReport":dynamic,"dynamicHedgeUpdatedAt":now},merge=True)\n        if int(safe_float(dynamic.get("ordersSent")))>0 or str(dynamic.get("reason",""))!="HEDGE_STABLE" or str(dynamic.get("safetyStatus","VEILIG"))!="VEILIG":\n            return {"status":str(dynamic.get("status","waiting")),"action":"DYNAMIC_HEDGE","ordersSent":int(safe_float(dynamic.get("ordersSent"))),"dynamicHedge":dynamic}\n        long_exposure=sum(abs(safe_float(row.get("positionAmt")))*safe_float(row.get("markPrice",row.get("entryPrice"))) for row in positions if str(row.get("positionSide","")).upper()=="LONG")\n        short_exposure=sum(abs(safe_float(row.get("positionAmt")))*safe_float(row.get("markPrice",row.get("entryPrice"))) for row in positions if str(row.get("positionSide","")).upper()=="SHORT")\n        blocked_side="SHORT" if long_exposure>short_exposure else "LONG" if short_exposure>long_exposure else ""\n        runtime_settings=settings\n        if bool(getattr(runtime_settings,"asymmetric_hedge_enabled",False)):\n            runtime_settings=replace(runtime_settings,asymmetric_hedge_enabled=False)\n        if str(getattr(runtime_settings,"take_profit_mode",""))=="PORTFOLIO":\n            runtime_settings=replace(runtime_settings,take_profit_mode="OFF")\n        def dynamic_before_order(intent):\n            dynamic_strategy_order_guard(dynamic_ref,intent,account,positions)\n            if before_order is not None:\n                try:return before_order(intent)\n                except TypeError:return before_order(intent,None)\n            return None\n        report=run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=runtime_settings,uid=uid,account=account,positions=positions,\n            open_orders=orders,timestamp_ms=int(now.timestamp()*1000),dry_run=dry_run,order_budget=order_budget,before_order=dynamic_before_order,\n            dynamic_hedge_blocked_side=blocked_side)\n        report["dynamicHedge"]={**dynamic,"blockedStrategySide":blocked_side or None,"portfolioTpSuppressed":str(getattr(settings,"take_profit_mode",""))=="PORTFOLIO"}\n        return report\n    return run_multi_bb_step(client=client,ref=ref,raw_state=raw,settings=settings,uid=uid,account=account,positions=positions,\n        open_orders=orders,timestamp_ms=int(now.timestamp()*1000),dry_run=dry_run,order_budget=order_budget,before_order=before_order)\n'''
text = patch_between(text, strategy_start, strategy_end, old_run, new_run)

marker = "# DYNAMIC_HEDGE_LIQUIDATION_SAFETY_ROUTES_20260910"
if marker not in text:
    text += f'''\n\n{marker}\ndef _dynamic_hedge_aster_client(user: dict[str, Any], live: bool = False) -> AsterV3Client:\n    secret = load_aster_secret(user)\n    return AsterV3Client(\n        signer_address=secret.signer_address,\n        sign_message=local_eip712_signer(secret),\n        live_authorized=bool(live),\n    )\n\n\ninstall_aster_dynamic_hedge_routes(\n    app,\n    authenticated_user=authenticated_user,\n    user_reference=user_reference,\n    client_factory=_dynamic_hedge_aster_client,\n)\n'''

MAIN.write_text(text, encoding="utf-8")
print("Dynamic Hedge routes, manual-close locks and Strategy-2 overlay installed in cloud_api/main.py")
