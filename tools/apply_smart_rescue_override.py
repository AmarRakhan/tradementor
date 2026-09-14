from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    if new in text:
        return
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one patch anchor, found {count}")
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def patch_pair_overlay() -> None:
    path = ROOT / "web/components/aster-pair-settings-overlay.tsx"
    replace_once(path,
        'import { authenticatedRequest } from "@/lib/cloud-client";\n',
        'import { authenticatedRequest } from "@/lib/cloud-client";\nimport { AsterSmartRescueOverride } from "@/components/aster-smart-rescue-override";\n')
    replace_once(path,
        '  const [symbol, setSymbol] = useState(""); const [open, setOpen] = useState(false); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");\n',
        '  const [symbol, setSymbol] = useState(""); const [open, setOpen] = useState(false); const [smartSymbol, setSmartSymbol] = useState(""); const [busy, setBusy] = useState(false); const [message, setMessage] = useState("");\n')
    old = '  const launch = useCallback(() => { const pair = currentPairFromDom(); if (!pair) return; setSymbol(pair); setOpen(true); void load(pair); }, [load]);\n'
    new = '''  const launch = useCallback(async () => {
    const pair = currentPairFromDom(); if (!pair) return;
    setBusy(true); setMessage("");
    try {
      const payload = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;
      const strategy2 = payload.strategy2 && typeof payload.strategy2 === "object" ? payload.strategy2 as Record<string, unknown> : {};
      const positions = strategy2.multiBbPositions && typeof strategy2.multiBbPositions === "object" ? strategy2.multiBbPositions as Record<string, unknown> : {};
      const managed = positions[`${pair}|LONG`];
      const smart = managed && typeof managed === "object" ? (managed as Record<string, unknown>).smartRescue : null;
      if (smart && typeof smart === "object") { setOpen(false); setSmartSymbol(pair); return; }
      setSmartSymbol(""); setSymbol(pair); setOpen(true); await load(pair);
    } catch (error) {
      setSymbol(pair); setOpen(true); setSmartSymbol("");
      setMessage(error instanceof Error ? error.message : "Actieve trade-strategie kon niet betrouwbaar worden vastgesteld.");
    } finally { setBusy(false); }
  }, [load]);
'''
    replace_once(path, old, new)
    replace_once(path,
        '  if (!open) return null;\n',
        '  if (smartSymbol) return <AsterSmartRescueOverride symbol={smartSymbol} onClose={() => setSmartSymbol("")} />;\n  if (!open) return null;\n')


def patch_backend_routes() -> None:
    path = ROOT / "cloud_api/main.py"
    text = path.read_text(encoding="utf-8")
    marker = '@app.put("/v1/me/aster/strategy2/settings")\n'
    if 'def get_smart_rescue_active_cycle(' in text:
        return
    if text.count(marker) != 1:
        raise RuntimeError("main.py Smart Rescue route insertion anchor changed")
    block = r'''
def _smart_rescue_override_context(user: dict[str, Any], symbol: str, raw: dict[str, Any] | None = None) -> tuple[str, dict[str, Any], dict[str, Any], dict[str, Any]]:
    from aster_smart_rescue_override import active_cycle_summary
    normalized = "".join(ch for ch in str(symbol).upper() if ch.isalnum())
    if not normalized.endswith("USDT") or len(normalized) < 6 or len(normalized) > 40:
        raise HTTPException(422, "Ongeldig Aster USDT-symbool")
    uid = str(user["uid"]); state_doc = raw if isinstance(raw, dict) else (aster_strategy2_reference(uid).get().to_dict() or {})
    state = state_doc.get("multiBbPositions") if isinstance(state_doc.get("multiBbPositions"), dict) else {}
    key = f"{normalized}|LONG"; outer = state.get(key)
    if not isinstance(outer, dict) or not isinstance(outer.get("smartRescue"), dict):
        raise HTTPException(409, f"{normalized}: geen actieve Smart Rescue-cycle")
    secret = load_aster_secret(user)
    client = AsterV3Client(signer_address=secret.signer_address, sign_message=local_eip712_signer(secret), live_authorized=False)
    try: exchange_rows = client.position_risk(normalized)
    except (AsterApiError, AsterValidationError, ValueError) as exc:
        raise HTTPException(409, f"Actieve Smart Rescue-positie kon niet betrouwbaar bij Aster worden gelezen: {exc}") from exc
    position = next((row for row in exchange_rows if str(row.get("symbol", "")).upper() == normalized and str(row.get("positionSide", "")).upper() == "LONG" and abs(safe_float(row.get("positionAmt"))) > 0), None)
    if not isinstance(position, dict):
        raise HTTPException(409, f"{normalized}: Smart Rescue-cycle is niet meer actief op Aster")
    summary = active_cycle_summary(smart_state=outer["smartRescue"], outer_state=outer, position=position)
    return normalized, outer, position, summary


@app.get("/v1/me/aster/strategy2/smart-rescue/{symbol}")
def get_smart_rescue_active_cycle(symbol: str, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    normalized, _outer, _position, summary = _smart_rescue_override_context(user, symbol)
    return {"active": True, "ordersSent": 0, "readOnly": True, "symbol": normalized,
        "pairLabel": f"{normalized[:-4]}/USDT", "current": summary}


@app.put("/v1/me/aster/strategy2/smart-rescue/{symbol}/extend")
def extend_smart_rescue_active_cycle(symbol: str, payload: dict[str, Any], user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    """Extend only future Smart Rescue levels. This route has no order path."""
    from aster_smart_rescue_override import active_cycle_summary, extend_future_levels
    uid = str(user["uid"]); ref = aster_strategy2_reference(uid); initial = ref.get().to_dict() or {}
    queue_enabled = _strategy2_order_queue_enabled(initial); queue_token = None; legacy_lease = False
    if queue_enabled:
        queue_token = _acquire_strategy2_queue_lease(ref)
        if not queue_token: raise HTTPException(409, "Strategy 2 verwerkt nu een andere actie; probeer de uitbreiding opnieuw")
    else:
        legacy_lease = _acquire_mexc_automation_lease(ref)
        if not legacy_lease: raise HTTPException(409, "Strategy 2 verwerkt nu een andere actie; probeer de uitbreiding opnieuw")
    try:
        latest = ref.get().to_dict() or {}
        normalized, outer, position, _summary = _smart_rescue_override_context(user, symbol, latest)
        requested_cycle = str(payload.get("cycleId") or "")
        live_cycle = str(outer.get("cycleId") or "")
        if not requested_cycle or requested_cycle != live_cycle:
            raise HTTPException(409, "Deze Smart Rescue-cycle is intussen gewijzigd of gesloten; open het menu opnieuw")
        try:
            new_total = int(round(float(payload.get("newTotalDca"))))
            new_range = float(payload.get("newRescueRangePercent"))
            growth = float(payload.get("futureGrowthMultiplier"))
        except (TypeError, ValueError, OverflowError) as exc:
            raise HTTPException(422, "Smart Rescue uitbreiding bevat ongeldige getallen") from exc
        now_ms = int(time.time() * 1000)
        try:
            updated_smart = extend_future_levels(outer["smartRescue"], new_total_dca=new_total,
                new_rescue_range_percent=new_range, future_growth_multiplier=growth, timestamp_ms=now_ms)
        except ValueError as exc: raise HTTPException(422, str(exc)) from exc
        state = latest.get("multiBbPositions") if isinstance(latest.get("multiBbPositions"), dict) else {}
        updated_outer = dict(outer); updated_outer["smartRescue"] = updated_smart; updated_outer["updatedAtMs"] = now_ms
        updated_state = dict(state); updated_state[f"{normalized}|LONG"] = updated_outer
        now = datetime.now(timezone.utc)
        ref.set({"multiBbPositions": updated_state, "updatedAt": now,
            "lastReason": f"Smart Rescue {normalized}: actieve ladder uitgebreid naar {new_total} DCA's; geen order geplaatst"},
            merge=["multiBbPositions", "updatedAt", "lastReason"])
        ref.collection("audit").add({"event": "SMART_RESCUE_LADDER_EXTENDED", "user": uid, "symbol": normalized,
            "cycleId": live_cycle, "newTotalDca": new_total, "newRescueRangePercent": new_range,
            "futureGrowthMultiplier": growth, "ordersSent": 0, "timestamp": now, "timestampMs": now_ms})
        summary = active_cycle_summary(smart_state=updated_smart, outer_state=updated_outer, position=position)
        return {"active": True, "saved": True, "ordersSent": 0, "symbol": normalized,
            "pairLabel": f"{normalized[:-4]}/USDT", "current": summary}
    finally:
        if queue_token: _release_strategy2_queue_lease(ref, str(queue_token))
        elif legacy_lease: ref.set({"leaseUntil": datetime.now(timezone.utc)}, merge=True)


'''
    path.write_text(text.replace(marker, block + marker, 1), encoding="utf-8")


def main() -> None:
    patch_pair_overlay()
    patch_backend_routes()


if __name__ == "__main__":
    main()
