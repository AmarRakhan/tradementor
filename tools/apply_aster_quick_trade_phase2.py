from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"anchor missing: {label}")
    return text.replace(old, new, 1)

# 1) Backend execution path: one explicit symbol, same planning/execution/persistence primitives as Multi BB.
p = Path('cloud_api/aster_multi_bb.py')
s = p.read_text()
if 'def quick_trade_once(' not in s:
    anchor = '\ndef run_multi_bb_step(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: MultiBbConfig, uid: str,'
    fn = r'''
def quick_trade_once(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: MultiBbConfig, uid: str,
                     account: dict[str, Any], positions: list[dict[str, Any]], open_orders: list[dict[str, Any]],
                     symbol: str, side: str, idempotency_key: str, timestamp_ms: int, dry_run: bool = False) -> dict[str, Any]:
    """Open exactly one user-requested Strategy-2 cycle without invoking the automatic scanner.

    Uses the same exchange metadata, tier resolver, order planner, executor and persisted
    multiBbPositions state as the automatic engine. The stable idempotency key is part of
    both the exchange client id and cycle id, so browser retries cannot create a second cycle.
    """
    symbol = str(symbol).upper().strip(); side = str(side).upper().strip()
    if not symbol.endswith("USDT") or side not in {"LONG", "SHORT"}:
        raise ValueError("Ongeldige Aster USDT perpetual of richting")
    pmap = _position_map(positions)
    same_symbol = [key for key in pmap if key.startswith(symbol + "|")]
    if same_symbol:
        existing_side = same_symbol[0].split("|", 1)[1]
        raise ValueError(f"{symbol} heeft al een actieve {existing_side}-positie")
    for order in open_orders:
        if str(order.get("symbol", "")).upper() == symbol and str(order.get("positionSide", "")).upper() == side:
            raise ValueError(f"{symbol} {side} heeft al een pending exchange-order")
    info = client.public_exchange_info()
    row = next((x for x in info.get("symbols", []) if str(x.get("symbol", "")).upper() == symbol
                and str(x.get("quoteAsset", "USDT")).upper() == "USDT"
                and str(x.get("status", "TRADING")).upper() == "TRADING"), None)
    if row is None:
        raise ValueError(f"{symbol} is niet actief/verhandelbaar op Aster")
    prices = {str(x.get("symbol", "")).upper(): _f(x.get("price")) for x in client.ticker_prices()}
    mark = prices.get(symbol, 0.0)
    if mark <= 0:
        raise ValueError(f"Geen actuele Aster-prijs beschikbaar voor {symbol}")
    effective = settings.effective_profile(symbol, side)
    plan, tier = _plan_new(client, row, mark,
        entry_margin_usd=_f(effective.get("entryMarginUsd"), settings.entry_margin_usd),
        entry_notional_usd=_f(effective.get("entryNotionalUsd"), settings.entry_notional_usd),
        entry_sizing_mode=str(effective.get("entrySizingMode", settings.entry_sizing_mode)),
        minimum_leverage=max(1, _i(effective.get("minimumLeverage"), settings.minimum_leverage)))
    required = float(plan.notional_per_leg) / max(1, plan.leverage)
    available = _f(account.get("availableBalance", account.get("availableMargin")))
    if available < required * 1.05:
        raise ValueError(f"Onvoldoende beschikbare margin voor {symbol} {side}; minimaal ongeveer ${required * 1.05:.2f} nodig")
    cycle_id = hashlib.sha256((uid + symbol + side + idempotency_key).encode()).hexdigest()[:16]
    planned = {"status": "PLANNED", "symbol": symbol, "side": side, "cycleId": cycle_id,
               "leverage": plan.leverage, "marginUsd": required, "notionalUsd": float(plan.notional_per_leg),
               "exchangeMaxLeverage": tier.get("exchangeMaxLeverage"), "effectiveSettings": effective}
    if dry_run:
        return planned
    stable = hashlib.sha256((uid + symbol + side + idempotency_key).encode()).hexdigest()[:12]
    result = execute_leg_once(client, plan, side=PositionSide(side), action="OPEN", id_prefix=f"mbb-quick-{stable}",
                              confirm=True, new_position_leverage=plan.leverage)
    fill = result.get("result") or {}
    fill_price = _f(fill.get("avgPrice"), mark); fill_qty = _f(fill.get("executedQty"), float(plan.quantity))
    if fill_qty <= 0:
        raise RuntimeError(f"{symbol} {side}: Aster bevestigde geen geldige fill")
    state = dict(raw_state.get("multiBbPositions") or {})
    key = f"{symbol}|{side}"
    state[key] = {"cycleId": cycle_id, "dcaCount": 0, "lastBotFillPrice": fill_price,
                  "lastKnownQty": fill_qty, "lastKnownEntry": fill_price, "leverage": plan.leverage,
                  "cycleStartedAtMs": timestamp_ms, "updatedAtMs": timestamp_ms, "botManaged": True,
                  "manualQuickTrade": True, "quickTradeIdempotencyKey": idempotency_key}
    ref.set({"multiBbPositions": state, "phase": "RUNNING", "lastTickAt": datetime.now(timezone.utc),
             "lastReason": f"Markets quick trade: {symbol} {side} actief"}, merge=True)
    ref.collection("audit").add({"event": "MARKETS_QUICK_TRADE", "symbol": symbol, "side": side,
        "cycleId": cycle_id, "idempotencyKey": idempotency_key, "leverage": plan.leverage,
        "marginUsd": required, "notionalUsd": float(plan.notional_per_leg), "timestamp": datetime.now(timezone.utc)})
    return {**planned, "status": "ACTIVE", "fillPrice": fill_price, "fillQty": fill_qty}

'''
    s = replace_once(s, anchor, '\n' + fn + 'def run_multi_bb_step(*, client: Any, ref: Any, raw_state: dict[str, Any], settings: MultiBbConfig, uid: str,', 'quick_trade_once insertion')
p.write_text(s)

# 2) API route with persistent idempotency guard and manual-only seat growth.
p = Path('cloud_api/main.py')
s = p.read_text()
s = s.replace('from aster_multi_bb import ENGINE as MULTI_BB_ENGINE, MultiBbConfig, run_multi_bb_step, leverage_tier_preview',
              'from aster_multi_bb import ENGINE as MULTI_BB_ENGINE, MultiBbConfig, run_multi_bb_step, leverage_tier_preview, quick_trade_once')
if 'class AsterQuickTradeRequest' not in s:
    anchor = 'class AsterStrategySettingsRequest(BaseModel):\n    settings: dict[str, Any]\n'
    addition = '''class AsterStrategySettingsRequest(BaseModel):\n    settings: dict[str, Any]\n\n\nclass AsterQuickTradeRequest(BaseModel):\n    symbol: str = Field(min_length=3, max_length=40)\n    side: str = Field(pattern="^(LONG|SHORT)$")\n    idempotency_key: str = Field(min_length=12, max_length=160)\n    confirm: bool\n'''
    s = replace_once(s, anchor, addition, 'quick request model')
if '@app.post("/v1/me/aster/strategy2/quick-trade")' not in s:
    anchor = '@app.post("/v1/me/aster/strategy2/start")\ndef start_aster_strategy2'
    route = r'''@app.post("/v1/me/aster/strategy2/quick-trade")
def markets_quick_trade(request: AsterQuickTradeRequest, user: dict[str, Any] = Depends(authenticated_user)) -> dict[str, Any]:
    if not request.confirm:
        raise HTTPException(422, "Persoonlijke bevestiging ontbreekt")
    uid = str(user["uid"]); ref = aster_strategy2_reference(uid); raw = ref.get().to_dict() or {}
    try:
        settings = MultiBbConfig.from_mapping(raw.get("settings"))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    if not bool(raw.get("enabled")):
        raise HTTPException(409, "Aster Bot staat uit. Schakel Strategy 2 eerst in voordat je een Markets quick trade opent.")
    if settings.mode == "live":
        if not bool(raw.get("liveReady")):
            raise HTTPException(423, "Strategy 2 is nog niet LIVE READY")
        if os.getenv("ASTER_STRATEGY2_LIVE_ENABLED", "false").lower() != "true":
            raise HTTPException(423, "Productie-uitvoering staat centraal uit")
    symbol = request.symbol.upper().strip(); side = request.side.upper().strip()
    guard_id = hashlib.sha256((uid + request.idempotency_key).encode()).hexdigest()
    guard = ref.collection("quickTradeRequests").document(guard_id)
    now = datetime.now(timezone.utc)
    try:
        guard.create({"status": "OPENING", "symbol": symbol, "side": side, "idempotencyKey": request.idempotency_key, "createdAt": now, "updatedAt": now})
    except google_exceptions.AlreadyExists:
        previous = guard.get().to_dict() or {}
        if previous.get("status") == "ACTIVE" and isinstance(previous.get("result"), dict):
            return {"duplicate": True, **previous["result"]}
        if previous.get("status") == "FAILED":
            raise HTTPException(409, str(previous.get("failureReason") or "Deze quick trade is eerder afgewezen"))
        raise HTTPException(409, f"{symbol} {side} wordt al geopend; wacht op exchange-bevestiging")
    try:
        secret = load_aster_secret(user)
        client = AsterV3Client(signer_address=secret.signer_address, sign_message=local_eip712_signer(secret),
                               live_authorized=settings.mode == "live", before_order_submit=_block_order_during_close_all(uid))
        hedge = client.position_mode(); account = client.account_information(); positions = client.position_risk(); orders = client.open_orders()
        if not hedge:
            raise ValueError("Aster Hedge Mode staat uit")
        state = dict(raw.get("multiBbPositions") or {})
        active_total = len(state); active_side = sum(1 for key in state if key.endswith("|" + side))
        side_limit = settings.long_slots if side == "LONG" else settings.short_slots
        needs_side_growth = active_side >= side_limit
        needs_total_growth = active_total >= settings.maximum_positions or needs_side_growth
        if needs_total_growth and settings.maximum_positions >= 200:
            raise ValueError("Maximum van 200 Strategy 2-posities is bereikt")
        result = quick_trade_once(client=client, ref=ref, raw_state=raw, settings=settings, uid=uid,
            account=account, positions=positions, open_orders=orders, symbol=symbol, side=side,
            idempotency_key=request.idempotency_key, timestamp_ms=int(time.time() * 1000), dry_run=settings.mode != "live")
        # Capacity is grown only after the explicit user entry reached the Strategy-2 execution path.
        # Automatic scanner calls never enter this route and therefore can never auto-grow seats.
        if needs_total_growth:
            updated = settings.public_dict(); updated["maximumPositions"] = settings.maximum_positions + 1
            if side == "LONG": updated["longSlots"] = settings.long_slots + 1
            else: updated["shortSlots"] = settings.short_slots + 1
            saved = MultiBbConfig.from_mapping(updated)
            ref.set({"settings": saved.public_dict(), "configVersion": max(int(safe_float(raw.get("configVersion"))), saved.version) + 1,
                     "updatedAt": datetime.now(timezone.utc)}, merge=True)
            ref.collection("audit").add({"event": "MARKETS_MANUAL_SEAT_GROWTH", "symbol": symbol, "side": side,
                "oldTotal": settings.maximum_positions, "newTotal": saved.maximum_positions,
                "oldLong": settings.long_slots, "newLong": saved.long_slots,
                "oldShort": settings.short_slots, "newShort": saved.short_slots, "timestamp": datetime.now(timezone.utc)})
            result["seatGrowth"] = {"total": [settings.maximum_positions, saved.maximum_positions],
                                    "long": [settings.long_slots, saved.long_slots], "short": [settings.short_slots, saved.short_slots]}
        guard.set({"status": "ACTIVE", "result": result, "updatedAt": datetime.now(timezone.utc)}, merge=True)
        return result
    except HTTPException:
        raise
    except Exception as exc:
        guard.set({"status": "FAILED", "failureReason": str(exc), "updatedAt": datetime.now(timezone.utc)}, merge=True)
        ref.collection("audit").add({"event": "MARKETS_QUICK_TRADE_FAILED", "symbol": symbol, "side": side,
            "idempotencyKey": request.idempotency_key, "reason": str(exc), "timestamp": datetime.now(timezone.utc)})
        raise HTTPException(409, str(exc)) from exc


@app.post("/v1/me/aster/strategy2/start")
def start_aster_strategy2'''
    s = replace_once(s, anchor, route, 'quick trade route')
p.write_text(s)

# 3) Next API proxy route.
p = Path('web/app/api/exchanges/aster/strategy2/quick-trade/route.ts')
p.parent.mkdir(parents=True, exist_ok=True)
p.write_text('import { proxyStrategy2Live } from "@/lib/secure-strategy2-live";\nexport async function POST(request: Request) { return proxyStrategy2Live(request, "/v1/me/aster/strategy2/quick-trade", "POST"); }\n')

# 4) Markets UI: compact Buy buttons + fast confirmation sheet + effective profile preview.
p = Path('web/components/markets-page.tsx')
s = p.read_text()
if 'type QuickSide' not in s:
    s = s.replace('type SortDirection = "asc" | "desc";\n', 'type SortDirection = "asc" | "desc";\ntype QuickSide = "LONG" | "SHORT";\ntype QuickTrade = { row: MarketRow; side: QuickSide; effective: Record<string, unknown>; idempotencyKey: string };\n')
if 'const [quickTrade' not in s:
    anchor = '  const [error, setError] = useState("");\n  const generationRef = useRef(0);'
    new = '''  const [error, setError] = useState("");\n  const [quickTrade, setQuickTrade] = useState<QuickTrade | null>(null);\n  const [quickBusy, setQuickBusy] = useState(false);\n  const [quickMessage, setQuickMessage] = useState("");\n  const generationRef = useRef(0);'''
    s = replace_once(s, anchor, new, 'quick ui state')
if 'async function prepareQuickTrade' not in s:
    anchor = '  const updated = data?.updatedAt ? new Date(data.updatedAt).toLocaleTimeString("nl-NL", { hour: "2-digit", minute: "2-digit", second: "2-digit" }) : "—";\n\n'
    fn = r'''  async function prepareQuickTrade(row: MarketRow, side: QuickSide) {
    setQuickBusy(true); setQuickMessage("");
    try {
      const account = await authenticatedRequest("/api/exchanges/aster") as Record<string, unknown>;
      const strategy2 = account.strategy2 && typeof account.strategy2 === "object" ? account.strategy2 as Record<string, unknown> : {};
      const settings = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : {};
      const direction = (side === "LONG" ? settings.standardLong : settings.standardShort);
      const profile = direction && typeof direction === "object" ? { ...(direction as Record<string, unknown>) } : {};
      const overrides = settings.pairOverrides && typeof settings.pairOverrides === "object" ? settings.pairOverrides as Record<string, unknown> : {};
      const pair = overrides[row.symbol] && typeof overrides[row.symbol] === "object" ? overrides[row.symbol] as Record<string, unknown> : {};
      const effective = { ...settings, ...profile, ...pair };
      setQuickTrade({ row, side, effective, idempotencyKey: `${row.symbol}-${side}-${crypto.randomUUID()}` });
    } catch (reason) {
      setQuickMessage(reason instanceof Error ? reason.message : "Strategy 2-instellingen konden niet worden geladen.");
    } finally { setQuickBusy(false); }
  }

  async function confirmQuickTrade() {
    if (!quickTrade || quickBusy) return;
    setQuickBusy(true); setQuickMessage("");
    try {
      const result = await authenticatedRequest("/api/exchanges/aster/strategy2/quick-trade", { method: "POST", body: JSON.stringify({
        symbol: quickTrade.row.symbol, side: quickTrade.side, idempotency_key: quickTrade.idempotencyKey, confirm: true,
      }) }) as Record<string, unknown>;
      const cycle = String(result.cycleId || "");
      setQuickMessage(`${quickTrade.row.symbol} ${quickTrade.side} is ${String(result.status || "ACTIVE").toLowerCase()}${cycle ? ` · cycle ${cycle}` : ""}.`);
      setQuickTrade(null);
    } catch (reason) {
      setQuickMessage(reason instanceof Error ? reason.message : "Positie kon niet worden geopend.");
    } finally { setQuickBusy(false); }
  }

'''
    s = replace_once(s, anchor, anchor + fn, 'quick ui functions')
old_row = '''          {row.bbStatus && row.bbUpper !== null && row.bbMiddle !== null && row.bbLower !== null\n            ? <div className={`${styles.bbBadge} ${styles[row.bbStatus]}`} title={`Upper ${price(row.bbUpper)} · Mid ${price(row.bbMiddle)} · Lower ${price(row.bbLower)}`}><i />{statusLabel(row.bbStatus)}</div>\n            : <div className={styles.bbBadge} title="Bollinger-data wordt veilig gedoseerd opgehaald"><i />BB laden</div>}\n        </article>)}</div>}'''
new_row = '''          {row.bbStatus && row.bbUpper !== null && row.bbMiddle !== null && row.bbLower !== null\n            ? <div className={`${styles.bbBadge} ${styles[row.bbStatus]}`} title={`Upper ${price(row.bbUpper)} · Mid ${price(row.bbMiddle)} · Lower ${price(row.bbLower)}`}><i />{statusLabel(row.bbStatus)}</div>\n            : <div className={styles.bbBadge} title="Bollinger-data wordt veilig gedoseerd opgehaald"><i />BB laden</div>}\n          <div className={styles.quickActions}><button type="button" className={styles.buyLong} disabled={quickBusy} onClick={() => void prepareQuickTrade(row, "LONG")}>Buy Long</button><button type="button" className={styles.buyShort} disabled={quickBusy} onClick={() => void prepareQuickTrade(row, "SHORT")}>Buy Short</button></div>\n        </article>)}</div>}'''
if old_row in s:
    s = s.replace(old_row, new_row, 1)
if '{quickTrade && <div className={styles.quickOverlay}' not in s:
    anchor = '    {error && data && <div className={styles.staleWarning}>{error}</div>}\n  </section>;'
    overlay = '''    {error && data && <div className={styles.staleWarning}>{error}</div>}\n    {quickMessage && <div className={styles.quickMessage}>{quickMessage}</div>}\n    {quickTrade && <div className={styles.quickOverlay} role="presentation" onClick={() => !quickBusy && setQuickTrade(null)}><div className={styles.quickSheet} role="dialog" aria-modal="true" aria-label={`Open ${quickTrade.row.symbol} ${quickTrade.side}?`} onClick={(event) => event.stopPropagation()}>\n      <span className={styles.eyebrow}>STRATEGY 2 QUICK TRADE</span><h2>Open {quickTrade.row.symbol} {quickTrade.side}?</h2>\n      <div className={styles.quickSummary}><span>Profiel <b>STANDARD {quickTrade.side}</b></span><span>Margin <b>${Number(quickTrade.effective.entryMarginUsd ?? 0).toFixed(2)}</b></span><span>Leverage <b>{Number(quickTrade.effective.minimumLeverage ?? 0)}x</b></span><span>Max DCA <b>{String(quickTrade.effective.unlimitedDca === true ? "Onbeperkt" : quickTrade.effective.maxDca ?? "—")}</b></span><span>DCA bedrag <b>${Number(quickTrade.effective.dcaMarginUsd ?? 0).toFixed(2)}</b></span><span>TP <b>{(Number(quickTrade.effective.takeProfit ?? 0) * 100).toFixed(2)}%</b></span></div>\n      <p>De server controleert vóór de order opnieuw actuele Aster-leverage, minimumorder, precision, beschikbare margin, bestaande positie en pending orders.</p>\n      <div className={styles.quickConfirm}><button type="button" onClick={() => setQuickTrade(null)} disabled={quickBusy}>Annuleren</button><button type="button" className={quickTrade.side === "LONG" ? styles.buyLong : styles.buyShort} onClick={() => void confirmQuickTrade()} disabled={quickBusy}>{quickBusy ? "Openen…" : `Open ${quickTrade.side}`}</button></div>\n    </div></div>}\n  </section>;'''
    s = replace_once(s, anchor, overlay, 'quick confirmation sheet')
p.write_text(s)

# CSS additions
p = Path('web/components/markets-page.module.css')
s = p.read_text()
if '.quickActions' not in s:
    s += r'''
.quickActions{display:flex;gap:7px;grid-column:1/-1}.quickActions button,.quickConfirm button{min-height:38px;border:0;border-radius:10px;padding:0 13px;font-weight:800;cursor:pointer}.buyLong{background:#12b886;color:#031813}.buyShort{background:#ff6b6b;color:#210707}.quickOverlay{position:fixed;inset:0;z-index:1000;background:rgba(0,0,0,.68);display:flex;align-items:flex-end;justify-content:center;padding:16px}.quickSheet{width:min(520px,100%);background:#111722;border:1px solid rgba(255,255,255,.11);border-radius:20px 20px 14px 14px;padding:20px;box-shadow:0 -18px 60px rgba(0,0,0,.45)}.quickSheet h2{margin:7px 0 12px}.quickSheet p{font-size:13px;line-height:1.5;opacity:.78}.quickSummary{display:grid;grid-template-columns:1fr 1fr;gap:8px}.quickSummary span{display:flex;flex-direction:column;gap:2px;background:rgba(255,255,255,.045);padding:10px;border-radius:10px;font-size:12px}.quickSummary b{font-size:14px}.quickConfirm{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-top:15px}.quickConfirm>button:first-child{background:rgba(255,255,255,.08);color:inherit}.quickMessage{position:sticky;bottom:76px;z-index:20;margin:10px 0;padding:10px 12px;border-radius:10px;background:#161e2c;border:1px solid rgba(255,255,255,.1);font-size:13px}@media(min-width:760px){.quickActions{grid-column:auto}.quickOverlay{align-items:center}.quickSheet{border-radius:20px}}
'''
p.write_text(s)

# 5) Focused backend tests using mocked execution primitives.
p = Path('cloud_api/test_aster_quick_trade.py')
p.write_text(r'''from unittest.mock import patch
import pytest
from aster_multi_bb import MultiBbConfig, quick_trade_once

class Ref:
    def __init__(self): self.writes=[]
    def set(self, value, merge=False): self.writes.append(value)
    def collection(self, name): return self
    def add(self, value): self.writes.append(value)

class Client:
    def public_exchange_info(self): return {"symbols":[{"symbol":"BTCUSDT","quoteAsset":"USDT","status":"TRADING"}]}
    def ticker_prices(self): return [{"symbol":"BTCUSDT","price":"100"}]
    def leverage_brackets(self, symbol): return [{"symbol":symbol,"brackets":[{"initialLeverage":100,"notionalCap":100000}]}]

def cfg():
    return MultiBbConfig.from_mapping({"engine":"multi_bb_v1","maximumPositions":2,"longSlots":1,"shortSlots":1,
        "universeTopN":10,"entryMarginUsd":5,"entryNotionalUsd":500,"entrySizingMode":"margin","minimumLeverage":50,
        "dcaMarginUsd":2,"dcaDistance":.003,"maxDca":3,"takeProfit":.015,
        "standardLong":{"entryMarginUsd":7,"minimumLeverage":80,"maxDca":4}})

def test_quick_trade_rejects_existing_pair_before_order():
    with pytest.raises(ValueError, match="actieve LONG"):
        quick_trade_once(client=Client(), ref=Ref(), raw_state={}, settings=cfg(), uid="u", account={"availableBalance":100},
            positions=[{"symbol":"BTCUSDT","positionSide":"LONG","positionAmt":"1"}], open_orders=[], symbol="BTCUSDT", side="LONG", idempotency_key="abcdefghijkl", timestamp_ms=1)

def test_quick_trade_dry_run_uses_standard_long_profile():
    plan=type("P",(),{"notional_per_leg":700.0,"leverage":100,"quantity":7})()
    with patch("aster_multi_bb._plan_new", return_value=(plan,{"exchangeMaxLeverage":100})):
        out=quick_trade_once(client=Client(), ref=Ref(), raw_state={}, settings=cfg(), uid="u", account={"availableBalance":100},
            positions=[], open_orders=[], symbol="BTCUSDT", side="LONG", idempotency_key="abcdefghijkl", timestamp_ms=1, dry_run=True)
    assert out["effectiveSettings"]["entryMarginUsd"] == 7
    assert out["effectiveSettings"]["minimumLeverage"] == 80
    assert out["effectiveSettings"]["maxDca"] == 4
    assert out["status"] == "PLANNED"
''')

# 6) Lightweight source-contract tests for the frontend/API route.
p = Path('web/tests/markets-quick-trade.test.mjs')
p.write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

test("Markets exposes safe Strategy 2 quick trade controls", () => {
  const source=fs.readFileSync(new URL("../components/markets-page.tsx", import.meta.url),"utf8");
  assert.match(source,/Buy Long/); assert.match(source,/Buy Short/);
  assert.match(source,/Open .* LONG|Open \{quickTrade\.row\.symbol\}/);
  assert.match(source,/idempotency_key/); assert.match(source,/strategy2\/quick-trade/);
});

test("Next route proxies quick trade through secure Strategy 2 live proxy", () => {
  const source=fs.readFileSync(new URL("../app/api/exchanges/aster/strategy2/quick-trade/route.ts", import.meta.url),"utf8");
  assert.match(source,/proxyStrategy2Live/); assert.match(source,/\/v1\/me\/aster\/strategy2\/quick-trade/);
});
''')
print('phase2 patch applied')
