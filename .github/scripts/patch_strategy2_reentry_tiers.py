from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"marker not found in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


def insert_after_block(path: str, marker: str, block: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    start = text.find(marker)
    if start < 0:
        raise SystemExit(f"route marker not found in {path}")
    nxt = text.find("\n\n@app.", start + len(marker))
    if nxt < 0:
        raise SystemExit(f"next route not found in {path}")
    if block.strip() in text:
        return
    text = text[:nxt] + "\n\n" + block.rstrip() + text[nxt:]
    p.write_text(text, encoding="utf-8")


Path("cloud_api/aster_leverage_tiers.py").write_text(r'''"""Single server-authoritative Aster leverage tier resolver for Strategy 2.

The same resolver powers entry planning, DCA tier transitions, diagnostics and
wizard previews.  It never invents exchange limits: callers must supply the
signed ``/fapi/v3/leverageBracket`` response for the account/symbol.
"""
from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal
from typing import Any

from aster_gateway import AsterValidationError, LeverageBracket, maximum_allowed_leverage


def _d(value: Any, default: str = "0") -> Decimal:
    try:
        out = Decimal(str(value))
        return out if out.is_finite() else Decimal(default)
    except Exception:
        return Decimal(default)


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def bracket_rows(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    wanted = str(symbol).upper().strip()
    for row in payload or []:
        if str(row.get("symbol", "")).upper() == wanted:
            rows = row.get("brackets") or []
            return [x for x in rows if isinstance(x, dict)]
    if payload and all(isinstance(row, dict) and "initialLeverage" in row for row in payload):
        return list(payload)
    return []


def normalized_tiers(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:
    rows = bracket_rows(payload, symbol)
    tiers = []
    for row in rows:
        floor = _d(row.get("notionalFloor"))
        cap = _d(row.get("notionalCap"))
        leverage = _i(row.get("initialLeverage"))
        if floor < 0 or cap < 0 or leverage < 1:
            continue
        tiers.append({
            "floor": float(floor), "cap": float(cap), "maxLeverage": leverage,
            "maintenanceMarginRatio": float(_d(row.get("maintMarginRatio"))),
        })
    tiers.sort(key=lambda x: (x["floor"], x["cap"] if x["cap"] > 0 else float("inf")))
    if not tiers:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return tiers


def maximum_for_notional(payload: list[dict[str, Any]], symbol: str, notional: float | Decimal) -> int:
    rows = bracket_rows(payload, symbol)
    if not rows:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return maximum_allowed_leverage(_d(notional), [LeverageBracket.from_mapping(row) for row in rows])


def _levels(payload: list[dict[str, Any]], symbol: str) -> list[int]:
    rows = bracket_rows(payload, symbol)
    values = sorted({_i(row.get("initialLeverage")) for row in rows if _i(row.get("initialLeverage")) > 0}, reverse=True)
    if not values:
        raise AsterValidationError(f"{str(symbol).upper()}: Aster leverage tiers ontbreken")
    return values


def resolve_entry(payload: list[dict[str, Any]], symbol: str, *, configured_minimum: int,
                  entry_margin_usd: float, entry_notional_usd: float,
                  entry_sizing_mode: str) -> dict[str, Any]:
    """Choose the highest self-consistent Aster leverage for a brand-new leg.

    In margin sizing, notional depends on leverage, so every Aster tier maximum
    is tested against the notional it would create.  If Aster's safe maximum is
    below the configured minimum, the exchange maximum wins instead of stopping
    Strategy 2; this is surfaced as ``forcedBelowConfiguredMinimum``.
    """
    mode = str(entry_sizing_mode).lower().strip()
    if mode not in {"margin", "notional"}:
        raise ValueError("entry sizing mode is ongeldig")
    levels = _levels(payload, symbol)
    if mode == "notional":
        planned = _d(entry_notional_usd)
        allowed = maximum_for_notional(payload, symbol, planned)
        chosen = min(max(levels), allowed)
        return {"leverage": chosen, "orderNotional": float(planned), "projectedNotional": float(planned),
                "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                "forcedBelowConfiguredMinimum": chosen < int(configured_minimum)}
    margin = _d(entry_margin_usd)
    if margin <= 0:
        raise ValueError("entry margin moet positief zijn")
    for chosen in levels:
        planned = margin * chosen
        allowed = maximum_for_notional(payload, symbol, planned)
        if chosen <= allowed:
            return {"leverage": chosen, "orderNotional": float(planned), "projectedNotional": float(planned),
                    "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                    "forcedBelowConfiguredMinimum": chosen < int(configured_minimum)}
    raise AsterValidationError(f"{str(symbol).upper()}: geen zelf-consistente Aster leverage tier voor entry")


def resolve_dca(payload: list[dict[str, Any]], symbol: str, *, current_notional: float,
                current_leverage: int, dca_margin_usd: float, configured_minimum: int) -> dict[str, Any]:
    """Resolve a DCA against the *projected total* contract notional.

    Leverage can stay equal or step down, never silently step up.  The returned
    ``additionalMarginRequired`` covers both the new DCA and any extra margin
    needed because the entire existing contract moves to a lower leverage.
    """
    existing = max(Decimal("0"), _d(current_notional))
    old_lev = max(1, int(current_leverage))
    margin = _d(dca_margin_usd)
    if margin <= 0:
        raise ValueError("DCA margin moet positief zijn")
    levels = [level for level in _levels(payload, symbol) if level <= old_lev]
    if old_lev not in levels:
        levels.append(old_lev)
    levels = sorted(set(levels), reverse=True)
    for chosen in levels:
        order_notional = margin * chosen
        projected = existing + order_notional
        allowed = maximum_for_notional(payload, symbol, projected)
        if chosen > allowed:
            continue
        current_margin = existing / old_lev
        projected_margin = projected / chosen
        additional = max(Decimal("0"), projected_margin - current_margin)
        return {"leverage": chosen, "previousLeverage": old_lev,
                "orderNotional": float(order_notional), "projectedNotional": float(projected),
                "exchangeMaxLeverage": allowed, "configuredMinimum": int(configured_minimum),
                "forcedBelowConfiguredMinimum": chosen < int(configured_minimum),
                "tierReduction": chosen < old_lev, "additionalMarginRequired": float(additional)}
    raise AsterValidationError(f"{str(symbol).upper()}: geen geldige Aster leverage tier voor geprojecteerde DCA")


def tier_preview(payload: list[dict[str, Any]], symbol: str, *, configured_minimum: int,
                 entry_margin_usd: float, entry_notional_usd: float, entry_sizing_mode: str,
                 dca_margin_usd: float, current_notional: float = 0.0,
                 current_leverage: int = 0) -> dict[str, Any]:
    tiers = normalized_tiers(payload, symbol)
    if current_notional > 0 and current_leverage > 0:
        base_notional = float(current_notional); base_leverage = int(current_leverage)
        entry = None
    else:
        entry = resolve_entry(payload, symbol, configured_minimum=configured_minimum,
                              entry_margin_usd=entry_margin_usd, entry_notional_usd=entry_notional_usd,
                              entry_sizing_mode=entry_sizing_mode)
        base_notional = float(entry["projectedNotional"]); base_leverage = int(entry["leverage"])
    next_tier = next((row for row in tiers if row["floor"] > base_notional and row["maxLeverage"] < base_leverage), None)
    estimated = None
    if next_tier is not None:
        simulated_notional = base_notional; simulated_leverage = base_leverage
        for count in range(1, 501):
            step = resolve_dca(payload, symbol, current_notional=simulated_notional,
                               current_leverage=simulated_leverage, dca_margin_usd=dca_margin_usd,
                               configured_minimum=configured_minimum)
            simulated_notional = float(step["projectedNotional"])
            if int(step["leverage"]) < base_leverage:
                estimated = count; break
            simulated_leverage = int(step["leverage"])
    return {"symbol": str(symbol).upper(), "source": "/fapi/v3/leverageBracket", "tiers": tiers,
            "currentNotional": float(current_notional), "currentLeverage": int(current_leverage),
            "entryPlan": entry, "nextTier": next_tier, "estimatedDcasToNextTier": estimated,
            "configuredMinimum": int(configured_minimum)}
''', encoding="utf-8")

# aster_execution: allow an explicit, audited contract-wide leverage reduction
# for a managed DCA, while preserving the old protection for unrelated/new legs.
replace_once("cloud_api/aster_execution.py",
'''def require_exact_new_position_leverage(client: Any, plan: PairExecutionPlan,
                                        configured_leverage: int) -> int:''',
'''def require_exact_new_position_leverage(client: Any, plan: PairExecutionPlan,
                                        configured_leverage: int, *,
                                        allow_existing_contract_change: bool = False) -> int:''')
replace_once("cloud_api/aster_execution.py",
'''    if active_rows:
        if active_leverages != {requested}:
            raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_VERIFICATION_FAILED", plan.symbol)
        # Aster leverage is contract-wide. Never rewrite it underneath an
        # existing leg; reliable exchange truth already proves the exact value.
        return requested
    try:
        response = client.change_leverage(plan.symbol, requested)''',
'''    if active_rows and active_leverages == {requested}:
        return requested
    if active_rows and not allow_existing_contract_change:
        # Aster leverage is contract-wide. A brand-new/opposite-side leg may not
        # rewrite an existing contract. Managed DCA callers opt in explicitly
        # only after projected-tier and available-margin checks.
        raise NewPositionLeverageBlocked("SYMBOL_LEVERAGE_VERIFICATION_FAILED", plan.symbol)
    try:
        response = client.change_leverage(plan.symbol, requested)''')
replace_once("cloud_api/aster_execution.py",
'''                     before_submit: Callable[[AsterOrderIntent], None] | None = None,
                     new_position_leverage: int | None = None) -> dict[str, Any]:''',
'''                     before_submit: Callable[[AsterOrderIntent], None] | None = None,
                     new_position_leverage: int | None = None,
                     allow_existing_contract_leverage_change: bool = False) -> dict[str, Any]:''')
replace_once("cloud_api/aster_execution.py",
'''        accepted_leverage = (require_exact_new_position_leverage(client, plan, new_position_leverage)
            if new_position_leverage is not None else configure_maximum_usable_leverage(client, plan))''',
'''        accepted_leverage = (require_exact_new_position_leverage(
                client, plan, new_position_leverage,
                allow_existing_contract_change=allow_existing_contract_leverage_change,
            ) if new_position_leverage is not None else configure_maximum_usable_leverage(client, plan))''')

# Multi BB uses the one central resolver and treats exchange maximum as the hard ceiling.
replace_once("cloud_api/aster_multi_bb.py",
'''from aster_gateway import PositionSide\n''',
'''from aster_gateway import PositionSide\nfrom aster_leverage_tiers import bracket_rows as tier_bracket_rows, resolve_entry, resolve_dca, tier_preview\n''')
replace_once("cloud_api/aster_multi_bb.py",
'''def _plan_new(client: Any, row: dict[str, Any], price: float, *, entry_margin_usd: float, entry_notional_usd: float, entry_sizing_mode: str, minimum_leverage: int) -> PairExecutionPlan:
    symbol = str(row.get("symbol", "")).upper(); bracket_rows = _brackets(client.leverage_brackets(symbol), symbol)
    candidates = sorted({_i(x.get("initialLeverage")) for x in bracket_rows if _i(x.get("initialLeverage")) >= minimum_leverage}, reverse=True)
    if not candidates: raise ValueError(f"{symbol}: max leverage lager dan minimum {minimum_leverage}x")
    last: Exception | None = None
    for leverage in candidates:
        configured_notional = entry_margin_usd * leverage if entry_sizing_mode == "margin" else entry_notional_usd
        try: return plan_pair(row, bracket_rows, price, configured_notional, accepted_leverage=leverage)
        except Exception as exc: last = exc
    raise ValueError(f"{symbol}: geen uitvoerbare order op minimaal {minimum_leverage}x") from last


def _plan_add(client: Any, row: dict[str, Any], price: float, margin: float, leverage: int, existing_notional: float) -> PairExecutionPlan:
    symbol = str(row.get("symbol", "")).upper(); bracket_rows = _brackets(client.leverage_brackets(symbol), symbol)
    return plan_pair(row, bracket_rows, price, margin * leverage, accepted_leverage=leverage, existing_contract_notional=existing_notional)
''',
'''def _plan_new(client: Any, row: dict[str, Any], price: float, *, entry_margin_usd: float, entry_notional_usd: float, entry_sizing_mode: str, minimum_leverage: int) -> tuple[PairExecutionPlan, dict[str, Any]]:
    symbol = str(row.get("symbol", "")).upper(); payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
    resolved = resolve_entry(payload, symbol, configured_minimum=minimum_leverage,
        entry_margin_usd=entry_margin_usd, entry_notional_usd=entry_notional_usd, entry_sizing_mode=entry_sizing_mode)
    plan = plan_pair(row, rows, price, resolved["orderNotional"], accepted_leverage=int(resolved["leverage"]))
    return plan, resolved


def _plan_add(client: Any, row: dict[str, Any], price: float, margin: float, leverage: int, existing_notional: float, minimum_leverage: int) -> tuple[PairExecutionPlan, dict[str, Any]]:
    symbol = str(row.get("symbol", "")).upper(); payload = client.leverage_brackets(symbol); rows = tier_bracket_rows(payload, symbol)
    resolved = resolve_dca(payload, symbol, current_notional=existing_notional, current_leverage=leverage,
        dca_margin_usd=margin, configured_minimum=minimum_leverage)
    plan = plan_pair(row, rows, price, resolved["orderNotional"], accepted_leverage=int(resolved["leverage"]), existing_contract_notional=existing_notional)
    return plan, resolved


def leverage_tier_preview(*, client: Any, symbol: str, settings: MultiBbConfig) -> dict[str, Any]:
    symbol = str(symbol).upper().strip(); payload = client.leverage_brackets(symbol)
    positions = _position_map(client.position_risk(symbol)); current = next((row for key, row in positions.items() if key.startswith(symbol + "|")), None)
    mark = _f((current or {}).get("markPrice"), _f((current or {}).get("entryPrice")))
    qty = abs(_f((current or {}).get("positionAmt"))); current_notional = qty * mark if qty > 0 and mark > 0 else 0.0
    current_leverage = max(0, _i((current or {}).get("leverage")))
    return tier_preview(payload, symbol, configured_minimum=settings.minimum_leverage,
        entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd,
        entry_sizing_mode=settings.entry_sizing_mode, dca_margin_usd=settings.dca_margin_usd,
        current_notional=current_notional, current_leverage=current_leverage)
''')

# Manual-mode adoption only adopts selected Strategy-2 rows. Unrelated/manual Aster
# positions no longer consume Strategy-2 seats, while already managed open rows do.
replace_once("cloud_api/aster_multi_bb.py",
'''    state = dict(raw_state.get("multiBbPositions") or {}); pmap = _position_map(positions)
    # Explicit user start may adopt already-open exchange positions once. Deployment/config save alone never does this.
    if bool(raw_state.get("multiBbAdoptionPending")):
''',
'''    state = dict(raw_state.get("multiBbPositions") or {}); pmap = _position_map(positions)
    selected_keys = {f"{symbol}|{side}" for symbol, side in settings.manual_symbols} if settings.manual_symbol_selection_enabled else set()
    reconciled_closed: list[str] = []
    # Explicit user start may adopt already-open exchange positions once. Deployment/config save alone never does this.
    if bool(raw_state.get("multiBbAdoptionPending")):
''')
replace_once("cloud_api/aster_multi_bb.py",
'''        for key, row in pmap.items():
            if key in state or key in conflict_keys: continue
''',
'''        for key, row in pmap.items():
            if settings.manual_symbol_selection_enabled and key not in selected_keys: continue
            if key in state or key in conflict_keys: continue
''')
replace_once("cloud_api/aster_multi_bb.py",
'''        row = pmap.get(key)
        if row is None:
            state.pop(key, None); continue
''',
'''        row = pmap.get(key)
        if row is None:
            reconciled_closed.append(key); state.pop(key, None); continue
''')
replace_once("cloud_api/aster_multi_bb.py",
'''    actions: list[dict[str, Any]] = []

    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.
''',
'''    actions: list[dict[str, Any]] = []
    for key in reconciled_closed:
        actions.append({"kind": "REENTRY_STATE_CLEARED", "key": key, "reason": "exchange position is flat"})

    # Exchange truth reconciles every already-managed leg; a manual add never resets/increments the automatic DCA counter.
''')

# Replace DCA planning/margin/execution with projected-total tier transition.
replace_once("cloud_api/aster_multi_bb.py",
'''        row_info = info_map.get(symbol); leverage = max(1, _i(row.get("leverage")))
        if row_info is None: continue
        try: plan = _plan_add(client, row_info, mark, settings.dca_margin_usd, leverage, qty * mark)
        except Exception as exc:
            actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)}); continue
        required = float(plan.notional_per_leg) / leverage
        if available < required * 1.05:
            actions.append({"kind": "DCA_MARGIN_WAIT", "symbol": symbol, "side": side}); continue
        actions.append({"kind": "DCA", "symbol": symbol, "side": side, "number": dca_count + 1, "trigger": trigger})
        if not dry_run:
            try:
                result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-dca-{hashlib.sha256((uid+key+str(dca_count+1)+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                          new_position_leverage=leverage, before_submit=before_order)
            except Exception as exc:
                if not is_definite_contract_rejection(exc): raise
                actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)})
                continue
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), mark)
            st = dict(st0); st.update({"dcaCount": dca_count + 1, "lastBotFillPrice": fill_price, "updatedAtMs": timestamp_ms}); state[key] = st
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; DCA {dca_count + 1} bevestigd op {symbol}"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_DCA", "symbol": symbol, "side": side, "dcaNumber": dca_count + 1, "timestamp": datetime.now(timezone.utc)})
        available -= required; sent += 1
''',
'''        row_info = info_map.get(symbol); leverage = max(1, _i(row.get("leverage")))
        if row_info is None: continue
        try: plan, tier = _plan_add(client, row_info, mark, settings.dca_margin_usd, leverage, qty * mark, settings.minimum_leverage)
        except Exception as exc:
            actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)}); continue
        required = float(tier["additionalMarginRequired"])
        if available < required * 1.05:
            actions.append({"kind": "DCA_MARGIN_WAIT", "symbol": symbol, "side": side,
                "reason": "INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION" if tier["tierReduction"] else "INSUFFICIENT_AVAILABLE_MARGIN",
                "requiredMargin": required, "targetLeverage": tier["leverage"]}); continue
        actions.append({"kind": "DCA", "symbol": symbol, "side": side, "number": dca_count + 1, "trigger": trigger,
            "leverage": tier["leverage"], "previousLeverage": tier["previousLeverage"], "tierReduction": tier["tierReduction"],
            "projectedNotional": tier["projectedNotional"]})
        if not dry_run:
            try:
                result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-dca-{hashlib.sha256((uid+key+str(dca_count+1)+str(timestamp_ms)).encode()).hexdigest()[:12]}", confirm=True,
                                          new_position_leverage=int(tier["leverage"]), allow_existing_contract_leverage_change=True, before_submit=before_order)
            except Exception as exc:
                if not is_definite_contract_rejection(exc): raise
                actions.append({"kind": "DCA_BLOCKED", "symbol": symbol, "side": side, "reason": str(exc)})
                continue
            fill = result.get("result") or {}; fill_price = _f(fill.get("avgPrice"), mark)
            st = dict(st0); st.update({"dcaCount": dca_count + 1, "lastBotFillPrice": fill_price, "updatedAtMs": timestamp_ms,
                "leverage": int(tier["leverage"]), "lastTierReductionAtMs": timestamp_ms if tier["tierReduction"] else st0.get("lastTierReductionAtMs")}); state[key] = st
            ref.set({"multiBbPositions": state, "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                     "lastReason": f"Multi DCA actief; DCA {dca_count + 1} bevestigd op {symbol} @ {int(tier['leverage'])}x"}, merge=True)
            ref.collection("audit").add({"event": "MULTI_BB_DCA", "symbol": symbol, "side": side, "dcaNumber": dca_count + 1,
                "previousLeverage": tier["previousLeverage"], "leverage": tier["leverage"], "tierReduction": tier["tierReduction"],
                "projectedNotional": tier["projectedNotional"], "timestamp": datetime.now(timezone.utc)})
        available -= required; sent += 1
''')

replace_once("cloud_api/aster_multi_bb.py",
'''    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
    long_count = sum(1 for k in active if k.endswith("|LONG")); short_count = sum(1 for k in active if k.endswith("|SHORT"))
    long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
''',
'''    active = _position_map(client.position_risk()) if sent and not dry_run else pmap
    active_symbols = {k.split("|", 1)[0] for k in active}
    strategy_active_keys = {key for key in active if key in state or (settings.manual_symbol_selection_enabled and key in selected_keys)}
    long_count = sum(1 for k in strategy_active_keys if k.endswith("|LONG")); short_count = sum(1 for k in strategy_active_keys if k.endswith("|SHORT"))
    long_need = max(0, settings.long_slots - long_count); short_need = max(0, settings.short_slots - short_count)
''')

replace_once("cloud_api/aster_multi_bb.py",
'''        try:
            bracket_payload = client.leverage_brackets(symbol); maximum = max_contract_leverage(bracket_payload, symbol)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"leverage-data: {exc}"}); continue
        if maximum < settings.minimum_leverage:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"max {maximum}x < minimum {settings.minimum_leverage}x"}); continue
''',
'''        try:
            bracket_payload = client.leverage_brackets(symbol); maximum = max_contract_leverage(bracket_payload, symbol)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": f"leverage-data: {exc}"}); continue
        if maximum <= 0:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": "SYMBOL_LEVERAGE_DATA_UNAVAILABLE"}); continue
''')
replace_once("cloud_api/aster_multi_bb.py",
'''        try: plan = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd, entry_sizing_mode=settings.entry_sizing_mode, minimum_leverage=settings.minimum_leverage)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": str(exc)}); continue
''',
'''        try: plan, tier = _plan_new(client, info_map[symbol], prices[symbol], entry_margin_usd=settings.entry_margin_usd, entry_notional_usd=settings.entry_notional_usd, entry_sizing_mode=settings.entry_sizing_mode, minimum_leverage=settings.minimum_leverage)
        except Exception as exc:
            actions.append({"kind": "ENTRY_SKIP", "symbol": symbol, "reason": str(exc)}); continue
''')
replace_once("cloud_api/aster_multi_bb.py",
'''        entry_action = {"kind": "ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "notionalUsd": float(plan.notional_per_leg), "marginUsd": required, "entryMode": "immediate_fill"}
''',
'''        entry_action = {"kind": "ENTRY", "symbol": symbol, "side": side, "leverage": plan.leverage, "notionalUsd": float(plan.notional_per_leg), "marginUsd": required, "entryMode": "immediate_fill",
            "exchangeMaxLeverage": tier["exchangeMaxLeverage"], "forcedBelowConfiguredMinimum": tier["forcedBelowConfiguredMinimum"]}
''')

# Explicit diagnostic status instead of generic AAN/active text.
replace_once("cloud_api/aster_multi_bb.py",
'''    report = {"engine": ENGINE, "ordersSent": 0 if dry_run else sent, "simulatedActions": len(actions) if dry_run else 0,
''',
'''    entry_rows = [a for a in actions if a.get("kind") == "ENTRY"]
    entry_wait = [a for a in actions if a.get("kind") in {"ENTRY_SKIP", "ENTRY_MARGIN_WAIT"}]
    selected_open = bool(settings.manual_symbol_selection_enabled and any(key in active for key in selected_keys))
    if entry_rows: entry_status = "ENTRY_PLANNED" if dry_run else "ENTRY_SUBMITTED"; entry_reason = "verse Strategy 2 entry verwerkt"
    elif selected_open: entry_status = "POSITION_ALREADY_OPEN"; entry_reason = "geselecteerde munt heeft al een open Aster-positie"
    elif long_need <= 0 and short_need <= 0: entry_status = "WAITING_CAPACITY"; entry_reason = "Strategy 2 slots zijn gevuld"
    elif any(a.get("kind") == "ENTRY_MARGIN_WAIT" for a in entry_wait): entry_status = "WAITING_BUDGET"; entry_reason = "onvoldoende beschikbare margin"
    elif any(str(a.get("reason", "")).startswith("leverage-data:") or a.get("reason") == "SYMBOL_LEVERAGE_DATA_UNAVAILABLE" for a in entry_wait): entry_status = "WAITING_EXCHANGE"; entry_reason = str(entry_wait[0].get("reason", "Aster leverage-data tijdelijk niet beschikbaar"))
    elif entry_wait: entry_status = "ORDER_REJECTED"; entry_reason = str(entry_wait[0].get("reason", "Aster ordercheck afgewezen"))
    else: entry_status = "READY_FOR_ENTRY"; entry_reason = "verse exchange snapshot; geselecteerde munt is opnieuw entry-kandidaat"
    report = {"engine": ENGINE, "ordersSent": 0 if dry_run else sent, "simulatedActions": len(actions) if dry_run else 0,
              "entryStatus": entry_status, "entryReason": entry_reason,
''')
replace_once("cloud_api/aster_multi_bb.py",
'''        ref.set({"multiBbPositions": state, "multiBbReport": report, "multiBbAdoptionPending": False,
                 "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": "Multi DCA actief; vrije slots worden direct gevuld"}, merge=True)
''',
'''        ref.set({"multiBbPositions": state, "multiBbReport": report, "multiBbAdoptionPending": False,
                 "lastTickAt": datetime.now(timezone.utc), "phase": "RUNNING",
                 "lastReason": f"{entry_status}: {entry_reason}"}, merge=True)
''')

# Main: import preview helper, clear stale report on explicit start, and add a
# read-only authenticated tier endpoint used by the wizard.
replace_once("cloud_api/main.py",
'''from aster_multi_bb import ENGINE as MULTI_BB_ENGINE, MultiBbConfig, run_multi_bb_step\n''',
'''from aster_multi_bb import ENGINE as MULTI_BB_ENGINE, MultiBbConfig, run_multi_bb_step, leverage_tier_preview\n''')
replace_once("cloud_api/main.py",
'''        "enabled":True,"monitor":True,"pendingReopens":[],"multiBbAdoptionPending":True,"startedAt":now,"updatedAt":now},merge=True)
''',
'''        "enabled":True,"monitor":True,"pendingReopens":[],"multiBbAdoptionPending":True,"multiBbReport":{},
        "lastReason":"Strategy 2 start: verse exchange-evaluatie","startedAt":now,"updatedAt":now},merge=True)
''')
insert_after_block("cloud_api/main.py", '@app.get("/v1/me/aster/strategy2/focus/markets")', r'''@app.get("/v1/me/aster/strategy2/leverage-tiers")
def strategy2_leverage_tiers(
    symbol: str = Query(min_length=1, max_length=40),
    minimumLeverage: int | None = Query(default=None, ge=1, le=300),
    entryMarginUsd: float | None = Query(default=None, gt=0, le=100000),
    dcaMarginUsd: float | None = Query(default=None, gt=0, le=100000),
    user: dict[str, Any] = Depends(authenticated_user),
) -> dict[str, Any]:
    """Read-only account-specific Aster leverage tiers for Strategy 2 wizard."""
    uid = str(user["uid"]); raw = aster_strategy2_reference(uid).get().to_dict() or {}
    settings = MultiBbConfig.from_mapping(raw.get("settings"))
    overrides = settings.public_dict()
    if minimumLeverage is not None: overrides["minimumLeverage"] = int(minimumLeverage)
    if entryMarginUsd is not None:
        overrides["entryMarginUsd"] = float(entryMarginUsd); overrides["entrySizingMode"] = "margin"
    if dcaMarginUsd is not None: overrides["dcaMarginUsd"] = float(dcaMarginUsd)
    settings = MultiBbConfig.from_mapping(overrides)
    secret = load_aster_secret(user)
    client = AsterV3Client(signer_address=secret.signer_address, sign_message=local_eip712_signer(secret), live_authorized=False)
    try:
        result = leverage_tier_preview(client=client, symbol=symbol, settings=settings)
    except (AsterApiError, AsterValidationError, ValueError) as exc:
        raise HTTPException(409, f"Aster leverage tiers konden niet betrouwbaar worden gelezen: {exc}") from exc
    return {"readOnly": True, **result}
''')

# Web authenticated proxy for the read-only tier endpoint.
route = Path("web/app/api/exchanges/aster/strategy2/leverage-tiers/route.ts")
route.parent.mkdir(parents=True, exist_ok=True)
route.write_text('''import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";\n\nexport async function GET(request: Request) {\n  const url = new URL(request.url);\n  return proxyStrategy2Live(request, `/v1/me/aster/strategy2/leverage-tiers${url.search}`, "GET");\n}\n''', encoding="utf-8")

# Wizard: load and display the real tiers for every selected manual symbol.
replace_once("web/components/aster-strategy2-maker.tsx",
'''type ManualSymbol = { symbol: string; side: ManualSide };\n''',
'''type ManualSymbol = { symbol: string; side: ManualSide };\ntype TierPreview = { symbol: string; source: string; tiers: Array<{ floor: number; cap: number; maxLeverage: number }>; nextTier?: { floor: number; cap: number; maxLeverage: number } | null; estimatedDcasToNextTier?: number | null; entryPlan?: { leverage: number; projectedNotional: number; forcedBelowConfiguredMinimum: boolean } | null; currentNotional?: number; currentLeverage?: number; };\n''')
replace_once("web/components/aster-strategy2-maker.tsx",
'''  const [markets, setMarkets] = useState<string[]>([]), [marketSearch, setMarketSearch] = useState(""), [marketBusy, setMarketBusy] = useState(false), [marketAttempted, setMarketAttempted] = useState(false);\n''',
'''  const [markets, setMarkets] = useState<string[]>([]), [marketSearch, setMarketSearch] = useState(""), [marketBusy, setMarketBusy] = useState(false), [marketAttempted, setMarketAttempted] = useState(false);\n  const [tierPreviews, setTierPreviews] = useState<Record<string, TierPreview>>({}), [tierBusy, setTierBusy] = useState(false);\n''')
replace_once("web/components/aster-strategy2-maker.tsx",
'''  useEffect(() => { if (wizard && v.manualEnabled && !marketAttempted) void loadMarkets(); }, [wizard, v.manualEnabled, marketAttempted]);\n\n  const selected = new Set(v.manualSymbols.map((x) => x.symbol));\n''',
'''  useEffect(() => { if (wizard && v.manualEnabled && !marketAttempted) void loadMarkets(); }, [wizard, v.manualEnabled, marketAttempted]);\n  useEffect(() => {\n    if (!wizard || !v.manualEnabled || !v.manualSymbols.length) { setTierPreviews({}); return; }\n    let cancelled = false; setTierBusy(true);\n    void Promise.all(v.manualSymbols.map(async ({ symbol }) => {\n      const q = new URLSearchParams({ symbol, minimumLeverage: String(Math.max(1, Math.round(n(v.minLeverage)))), entryMarginUsd: String(Math.max(.01, n(v.entryMargin))), dcaMarginUsd: String(Math.max(.01, n(v.dcaMargin))) });\n      const result = await authenticatedRequest(`/api/exchanges/aster/strategy2/leverage-tiers?${q.toString()}`) as TierPreview;\n      return [symbol, result] as const;\n    })).then((rows) => { if (!cancelled) setTierPreviews(Object.fromEntries(rows)); }).catch((e) => { if (!cancelled) setMessage(e instanceof Error ? e.message : "Aster leverage tiers konden niet worden geladen."); }).finally(() => { if (!cancelled) setTierBusy(false); });\n    return () => { cancelled = true; };\n  }, [wizard, v.manualEnabled, v.manualSymbols, v.minLeverage, v.entryMargin, v.dcaMargin]);\n\n  const selected = new Set(v.manualSymbols.map((x) => x.symbol));\n''')
replace_once("web/components/aster-strategy2-maker.tsx",
'''      <div className="manual-symbol-selected">{v.manualSymbols.map((row) => <div key={row.symbol}><b>{row.symbol}</b><span><button type="button" className={row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" className={row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)} aria-label={`${row.symbol} verwijderen`}>×</button></div>)}</div>\n''',
'''      <div className="manual-symbol-selected">{v.manualSymbols.map((row) => { const preview = tierPreviews[row.symbol]; const entryLev = preview?.entryPlan?.leverage || preview?.currentLeverage || 0; return <div key={row.symbol} style={{display:"grid",gap:6}}><div style={{display:"flex",alignItems:"center",gap:8}}><b>{row.symbol}</b><span><button type="button" className={row.side === "LONG" ? "active long" : ""} onClick={() => setSymbolSide(row.symbol, "LONG")}>LONG</button><button type="button" className={row.side === "SHORT" ? "active short" : ""} onClick={() => setSymbolSide(row.symbol, "SHORT")}>SHORT</button></span><button type="button" className="remove" onClick={() => removeSymbol(row.symbol)} aria-label={`${row.symbol} verwijderen`}>×</button></div>{tierBusy && !preview ? <small>Leverage tiers laden…</small> : preview ? <div style={{display:"grid",gap:3,fontSize:12,opacity:.92}}><b>Aster leverage tiers</b>{preview.tiers.slice(0,6).map((t,i) => <span key={`${row.symbol}-${i}`}>{t.cap > 0 ? `$${t.floor.toLocaleString()} – $${t.cap.toLocaleString()}` : `Vanaf $${t.floor.toLocaleString()}`}: max {t.maxLeverage}×</span>)}{preview.nextTier && <strong>Volgende daling: {entryLev}× → {preview.nextTier.maxLeverage}× vanaf ongeveer ${preview.nextTier.floor.toLocaleString()} totaal</strong>}{preview.estimatedDcasToNextTier != null && <span>Geschat aantal DCA's tot volgende tier: {preview.estimatedDcasToNextTier}</span>}{preview.nextTier && entryLev > preview.nextTier.maxLeverage && <span className="inline-warning">Let op: bij verdere DCA verlaagt Strategy 2 automatisch de leverage van de hele positie naar de hoogste leverage die Aster toestaat en gaat daarna verder.</span>}</div> : <small>Geen betrouwbare tierdata beschikbaar; Strategy 2 zal geen willekeurige hoge leverage gebruiken.</small>}</div>; })}</div>\n''')
replace_once("web/components/aster-strategy2-maker.tsx",
'''    { title: "Minimum leverage", help: "Een munt valt af als Aster minder ondersteunt. Een toegestane munt gebruikt de hoogste leverage die Aster voor de geplande order toestaat.", body: <Field label="Minimum leverage (×)" value={v.minLeverage} set={x => setV({ ...v, minLeverage: x })} /> },\n''',
'''    { title: "Minimum leverage", help: "Strategy 2 gebruikt de hoogste veilige leverage uit de actuele Aster tiers. Als een hogere positietier later een lagere maximumleverage afdwingt, wint de Aster-limiet: de hele positie wordt automatisch verlaagd en de bot blijft actief.", body: <Field label="Minimum leverage (×)" value={v.minLeverage} set={x => setV({ ...v, minLeverage: x })} /> },\n''')

# Backend tests: pure tier math + source contract for re-entry and diagnostics.
Path("cloud_api/test_strategy2_reentry_leverage_tiers.py").write_text(r'''from pathlib import Path

from aster_leverage_tiers import normalized_tiers, maximum_for_notional, resolve_entry, resolve_dca, tier_preview


HYPE = [{"symbol":"HYPEUSDT","brackets":[
    {"notionalFloor":"0","notionalCap":"3000","initialLeverage":300,"maintMarginRatio":"0.004"},
    {"notionalFloor":"3000","notionalCap":"10000","initialLeverage":75,"maintMarginRatio":"0.01"},
    {"notionalFloor":"10000","notionalCap":"0","initialLeverage":50,"maintMarginRatio":"0.02"},
]}]
ALT = [{"symbol":"ALTUSDT","brackets":[
    {"notionalFloor":"0","notionalCap":"5000","initialLeverage":100,"maintMarginRatio":"0.005"},
    {"notionalFloor":"5000","notionalCap":"0","initialLeverage":50,"maintMarginRatio":"0.02"},
]}]


def test_tiers_are_exchange_rows_not_symbol_hardcodes():
    assert [x["maxLeverage"] for x in normalized_tiers(HYPE,"HYPEUSDT")] == [300,75,50]
    assert [x["maxLeverage"] for x in normalized_tiers(ALT,"ALTUSDT")] == [100,50]
    source=Path("aster_leverage_tiers.py").read_text()
    assert "HYPEUSDT" not in source and "3000" not in source


def test_maximum_is_based_on_total_notional():
    assert maximum_for_notional(HYPE,"HYPEUSDT",2999) == 300
    assert maximum_for_notional(HYPE,"HYPEUSDT",3001) == 75
    assert maximum_for_notional(HYPE,"HYPEUSDT",10001) == 50


def test_margin_entry_finds_self_consistent_lower_tier_instead_of_stopping():
    result=resolve_entry(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=20,entry_notional_usd=1,entry_sizing_mode="margin")
    assert result["leverage"] == 75
    assert result["orderNotional"] == 1500
    assert result["forcedBelowConfiguredMinimum"] is True


def test_entry_stays_at_highest_tier_when_size_allows_it():
    result=resolve_entry(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=5,entry_notional_usd=1,entry_sizing_mode="margin")
    assert result["leverage"] == 300
    assert result["orderNotional"] == 1500


def test_long_or_short_share_the_same_contract_tier_math():
    # Side is deliberately absent: Aster leverage is contract-wide.
    result=resolve_dca(HYPE,"HYPEUSDT",current_notional=2900,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    assert result["leverage"] == 75 and result["tierReduction"] is True
    assert result["projectedNotional"] == 3050
    assert result["additionalMarginRequired"] > 0


def test_dca_inside_tier_keeps_leverage():
    result=resolve_dca(HYPE,"HYPEUSDT",current_notional=1500,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    assert result["leverage"] == 300 and result["tierReduction"] is False


def test_repeated_dca_never_steps_leverage_back_up():
    first=resolve_dca(HYPE,"HYPEUSDT",current_notional=2900,current_leverage=300,dca_margin_usd=2,configured_minimum=300)
    second=resolve_dca(HYPE,"HYPEUSDT",current_notional=first["projectedNotional"],current_leverage=first["leverage"],dca_margin_usd=2,configured_minimum=300)
    assert first["leverage"] == 75 and second["leverage"] == 75


def test_unlimited_dca_can_cross_multiple_tiers_by_repeated_resolution():
    notional=2900; leverage=300; seen=[]
    for _ in range(100):
        step=resolve_dca(HYPE,"HYPEUSDT",current_notional=notional,current_leverage=leverage,dca_margin_usd=100,configured_minimum=300)
        leverage=step["leverage"]; notional=step["projectedNotional"]; seen.append(leverage)
        if leverage == 50: break
    assert 75 in seen and 50 in seen


def test_preview_estimates_next_tier_dcas_without_trading():
    preview=tier_preview(HYPE,"HYPEUSDT",configured_minimum=300,entry_margin_usd=5,entry_notional_usd=1,entry_sizing_mode="margin",dca_margin_usd=2)
    assert preview["source"] == "/fapi/v3/leverageBracket"
    assert preview["nextTier"]["maxLeverage"] == 75
    assert preview["estimatedDcasToNextTier"] is not None


def test_reentry_and_diagnostics_contract_is_explicit_in_runtime_source():
    source=Path("aster_multi_bb.py").read_text()
    assert "REENTRY_STATE_CLEARED" in source
    assert "selected_keys" in source
    for status in ("READY_FOR_ENTRY","ENTRY_PLANNED","ENTRY_SUBMITTED","POSITION_ALREADY_OPEN","WAITING_CAPACITY","WAITING_BUDGET","WAITING_EXCHANGE","ORDER_REJECTED"):
        assert status in source
    assert '"lastReason": f"{entry_status}: {entry_reason}"' in source


def test_start_clears_stale_pending_reopens_and_old_report_then_forces_first_tick():
    source=Path("main.py").read_text()
    assert '"pendingReopens":[]' in source
    assert '"multiBbReport":{}' in source
    assert 'first=_run_aster_strategy2_tick(uid,dry_run=settings.mode!="live")' in source


def test_managed_dca_may_change_entire_contract_leverage_only_with_explicit_opt_in():
    source=Path("aster_execution.py").read_text()
    assert "allow_existing_contract_leverage_change" in source
    multi=Path("aster_multi_bb.py").read_text()
    assert "allow_existing_contract_leverage_change=True" in multi
    assert "INSUFFICIENT_MARGIN_FOR_TIER_LEVERAGE_REDUCTION" in multi
''', encoding="utf-8")

Path("web/tests/aster-leverage-tiers-wizard.test.mjs").write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const route = readFileSync(new URL("../app/api/exchanges/aster/strategy2/leverage-tiers/route.ts", import.meta.url), "utf8");

test("manual coin picker loads server-authoritative Aster leverage tiers", () => {
  assert.match(maker, /strategy2\/leverage-tiers/);
  assert.match(maker, /Aster leverage tiers/);
  assert.match(maker, /Volgende daling/);
  assert.match(maker, /Geschat aantal DCA's tot volgende tier/);
  assert.match(route, /proxyStrategy2Live/);
});

test("wizard warns that the whole position changes leverage and bot continues", () => {
  assert.match(maker, /de hele positie/);
  assert.match(maker, /automatisch de leverage/);
  assert.doesNotMatch(maker, /HYPE boven \$3000/);
});
''', encoding="utf-8")

print("Strategy 2 re-entry + leverage tier patch applied")
