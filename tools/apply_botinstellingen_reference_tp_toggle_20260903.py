from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text(encoding="utf-8")
    if old not in text:
        raise SystemExit(f"Expected snippet not found in {path}: {old[:120]!r}")
    p.write_text(text.replace(old, new, 1), encoding="utf-8")


maker = "web/components/aster-strategy2-maker.tsx"
replace_once(maker,
'''  maxDca: string; tp: string; mode: "paper" | "live";\n  manualEnabled: boolean; manualSymbols: ManualSymbol[];''',
'''  maxDca: string; tp: string; tpEnabled: boolean; mode: "paper" | "live";\n  manualEnabled: boolean; manualSymbols: ManualSymbol[];''')
replace_once(maker,
'''  minLeverage: "50", entryMargin: "5", dcaDistance: "0.30", dcaMargin: "2", maxDca: "3", tp: "1.5", mode: "live",''',
'''  minLeverage: "50", entryMargin: "5", dcaDistance: "0.30", dcaMargin: "2", maxDca: "3", tp: "1.5", tpEnabled: true, mode: "live",''')
replace_once(maker,
'''      tp: String(Number(x.takeProfit ?? .015) * 100), mode: x.mode === "paper" ? "paper" : "live",''',
'''      tp: String(Number(x.takeProfit ?? .015) * 100), tpEnabled: x.takeProfitEnabled !== false, mode: x.mode === "paper" ? "paper" : "live",''')
replace_once(maker,
'''      takeProfit: n(v.tp) / 100, entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,''',
'''      takeProfit: n(v.tp) / 100, takeProfitEnabled: v.tpEnabled, entryMode: "immediate_fill", marginMode: "cross", autoRestart: true,''')
replace_once(maker,
'''      if (settings.maxDca > MAX_DCA) throw new Error(`Globale DCA-limiet mag maximaal ${MAX_DCA} zijn.`);\n      if (settings.entryMarginUsd * settings.minimumLeverage < 5)''',
'''      if (settings.maxDca > MAX_DCA) throw new Error(`Globale DCA-limiet mag maximaal ${MAX_DCA} zijn.`);\n      if (settings.takeProfitEnabled && (!Number.isFinite(Number(v.tp.replace(",", "."))) || Number(v.tp.replace(",", ".")) <= 0)) throw new Error("Take Profit moet een positief numeriek percentage zijn.");\n      if (settings.entryMarginUsd * settings.minimumLeverage < 5)''')
replace_once(maker,
'''<span>DCA globaal max {v.maxDca}</span><span>TP {v.tp}%</span><span>CROSS</span>''',
'''<span>DCA globaal max {v.maxDca}</span><span>TP {v.tpEnabled ? `${v.tp}%` : "UIT"}</span><span>CROSS</span>''')
replace_once(maker,
'''      <Field label="Take Profit (%)" value={v.tp} set={(value) => change({ ...v, tp: value })} />''',
'''      <div className={`tp-setting ${v.tpEnabled ? "enabled" : "disabled"}`}>
        <label className="tp-toggle-row"><span><b>Take Profit</b><small>{v.tpEnabled ? "Automatisch sluiten is actief" : "Automatisch sluiten is volledig uit"}</small></span><button type="button" role="switch" aria-checked={v.tpEnabled} className="tp-toggle" onClick={() => change({ ...v, tpEnabled: !v.tpEnabled })}><i />{v.tpEnabled ? "AAN" : "UIT"}</button></label>
        <Field label="Take Profit (%)" value={v.tp} set={(value) => change({ ...v, tp: value })} disabled={!v.tpEnabled} />
      </div>''')
replace_once(maker,
'''function Field({ label, value, set, text = false, onBlur }: { label: string; value: string; set: (value: string) => void; text?: boolean; onBlur?: () => void }) {\n  return <label>{label}<input inputMode={text ? undefined : "decimal"} value={value} onChange={(event) => set(text ? event.target.value : event.target.value.replace(",", "."))} onBlur={onBlur} /></label>;\n}''',
'''function Field({ label, value, set, text = false, onBlur, disabled = false }: { label: string; value: string; set: (value: string) => void; text?: boolean; onBlur?: () => void; disabled?: boolean }) {\n  return <label>{label}<input disabled={disabled} inputMode={text ? undefined : "decimal"} value={value} onChange={(event) => set(text ? event.target.value : event.target.value.replace(",", "."))} onBlur={onBlur} /></label>;\n}''')

multi = "cloud_api/aster_multi_bb.py"
replace_once(multi,
'''    unlimited_dca: bool = False\n    take_profit: float = .015\n    manual_symbol_selection_enabled: bool = False''',
'''    unlimited_dca: bool = False\n    take_profit: float = .015\n    take_profit_enabled: bool = True\n    manual_symbol_selection_enabled: bool = False''')
replace_once(multi,
'''            unlimited_dca=bool(raw.get("unlimitedDca", False)),\n            take_profit=_f(raw.get("takeProfit"), .015),\n            manual_symbol_selection_enabled=manual_enabled,''',
'''            unlimited_dca=bool(raw.get("unlimitedDca", False)),\n            take_profit=_f(raw.get("takeProfit"), .015),\n            take_profit_enabled=bool(raw.get("takeProfitEnabled", True)),\n            manual_symbol_selection_enabled=manual_enabled,''')
replace_once(multi,
'''        if self.max_dca < 0: raise ValueError("Max DCA mag niet negatief zijn")\n        if not .001 <= self.take_profit <= .20: raise ValueError("Take Profit moet tussen 0,1% en 20% liggen")''',
'''        if self.max_dca < 0: raise ValueError("Max DCA mag niet negatief zijn")\n        if not math.isfinite(self.take_profit) or self.take_profit <= 0: raise ValueError("Take Profit moet een positief eindig percentage zijn")''')
replace_once(multi,
'''            "dcaMarginUsd": self.dca_margin_usd, "maxDca": self.max_dca, "unlimitedDca": self.unlimited_dca, "takeProfit": self.take_profit,''',
'''            "dcaMarginUsd": self.dca_margin_usd, "maxDca": self.max_dca, "unlimitedDca": self.unlimited_dca, "takeProfit": self.take_profit, "takeProfitEnabled": self.take_profit_enabled,''')
replace_once(multi,
'''    tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)\n    tp_distance_usd = abs(tp_price - mark)\n    tp_distance_pct = tp_distance_usd / mark * 100\n    expected_pnl_at_tp = ((tp_price - entry) if side == "LONG" else (entry - tp_price)) * qty\n    current_pnl = ((mark - entry) if side == "LONG" else (entry - mark)) * qty\n    portfolio_value_at_tp = account_equity + (expected_pnl_at_tp - current_pnl) if account_equity > 0 else None''',
'''    tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit) if settings.take_profit_enabled else None\n    tp_distance_usd = abs(tp_price - mark) if tp_price is not None else None\n    tp_distance_pct = tp_distance_usd / mark * 100 if tp_distance_usd is not None else None\n    expected_pnl_at_tp = (((tp_price - entry) if side == "LONG" else (entry - tp_price)) * qty) if tp_price is not None else None\n    current_pnl = ((mark - entry) if side == "LONG" else (entry - mark)) * qty\n    portfolio_value_at_tp = account_equity + (expected_pnl_at_tp - current_pnl) if account_equity > 0 and expected_pnl_at_tp is not None else None''')
replace_once(multi,
'''        "takeProfitPct": settings.take_profit * 100,''',
'''        "takeProfitEnabled": settings.take_profit_enabled,\n        "takeProfitPct": settings.take_profit * 100 if settings.take_profit_enabled else None,''')
replace_once(multi,
'''        tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)\n        tp_due = mark >= tp_price if side == "LONG" else mark <= tp_price\n        if tp_due:''',
'''        tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)\n        tp_due = settings.take_profit_enabled and (mark >= tp_price if side == "LONG" else mark <= tp_price)\n        if tp_due:''')

css_path = Path("web/app/strategy2-reference.css")
css = css_path.read_text(encoding="utf-8")
marker = "/* Botinstellingen definitive dark-green/gold reference 2026-09-03 */"
if marker not in css:
    css += r'''

/* Botinstellingen definitive dark-green/gold reference 2026-09-03 */
#strategy-2-maker.strategy-two-card {
  --s2-gold: #d6b55a;
  --s2-green: #18c98b;
  --s2-deep: #07110e;
  --s2-panel: rgba(8, 25, 20, .92);
  background: radial-gradient(circle at 82% 6%, rgba(20, 183, 122, .12), transparent 34%), linear-gradient(180deg, #07110e 0%, #040908 100%);
  border: 1px solid rgba(214,181,90,.55);
  border-radius: 18px;
  padding: 14px;
  box-shadow: 0 18px 50px rgba(0,0,0,.34), inset 0 0 0 1px rgba(20,183,122,.04);
  overflow: hidden;
}
#strategy-2-maker .strategy-title-row { margin-bottom: 6px; align-items: center; }
#strategy-2-maker .strategy-title-row h2 { margin: 1px 0 0; font-size: clamp(19px, 4.8vw, 24px); line-height: 1.05; }
#strategy-2-maker .strategy-title-row .kicker { color: var(--s2-gold); font-size: 10px; letter-spacing: .16em; }
#strategy-2-maker .strategy-state { border-color: rgba(214,181,90,.5); background: rgba(214,181,90,.08); min-width: 52px; text-align:center; }
#strategy-2-maker .strategy-state.on { color: #65e6b2; border-color: rgba(24,201,139,.58); background: rgba(24,201,139,.10); }
#strategy-2-maker .strategy-intro { margin: 0 0 8px; font-size: 11px; line-height: 1.35; opacity: .76; }
#strategy-2-maker .strategy-facts { display:grid; grid-template-columns: repeat(3,minmax(0,1fr)); gap:5px; margin:0 0 8px; }
#strategy-2-maker .strategy-facts span { min-width:0; padding:5px 6px; border:1px solid rgba(214,181,90,.22); border-radius:9px; background:rgba(255,255,255,.025); font-size:10px; text-align:center; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
#strategy-2-maker .compact-scan { display:grid; grid-template-columns:repeat(4,minmax(0,1fr)); gap:5px; padding:7px; margin:0 0 8px; border:1px solid rgba(24,201,139,.18); border-radius:12px; background:rgba(4,18,14,.8); font-size:10px; line-height:1.25; }
#strategy-2-maker .compact-scan small, #strategy-2-maker .compact-scan .entry-hold-reason { grid-column:1/-1; }
#strategy-2-maker .strategy-power-control { padding:7px 9px; min-height:46px; margin-bottom:8px; border:1px solid rgba(214,181,90,.26); border-radius:12px; background:var(--s2-panel); }
#strategy-2-maker .strategy-power-control span b { font-size:12px; }
#strategy-2-maker .strategy-power-control span small { font-size:9px; }
#strategy-2-maker .strategy-power-control button { min-height:34px; padding:0 11px; border-radius:10px; }
#strategy-2-maker .compact-settings-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:7px; }
#strategy-2-maker .compact-settings-grid > label, #strategy-2-maker .position-settings-grid label, #strategy-2-maker .tp-setting > label { margin:0; gap:3px; font-size:10px; }
#strategy-2-maker .position-settings-grid { grid-column:1/-1; display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; }
#strategy-2-maker .compact-settings-grid input { min-width:0; height:36px; padding:0 9px; border-radius:9px; border-color:rgba(214,181,90,.26); background:rgba(0,0,0,.22); font-size:13px; }
#strategy-2-maker .compact-settings-grid input:focus { border-color:rgba(24,201,139,.7); box-shadow:0 0 0 2px rgba(24,201,139,.10); }
#strategy-2-maker .compact-settings-grid input:disabled { opacity:.5; cursor:not-allowed; }
#strategy-2-maker .tp-setting { display:grid; grid-template-columns:minmax(0,1fr); gap:5px; padding:7px; border:1px solid rgba(214,181,90,.28); border-radius:11px; background:rgba(214,181,90,.035); }
#strategy-2-maker .tp-toggle-row { display:flex; align-items:center; justify-content:space-between; gap:8px; }
#strategy-2-maker .tp-toggle-row span { display:grid; gap:1px; }
#strategy-2-maker .tp-toggle-row b { font-size:11px; }
#strategy-2-maker .tp-toggle-row small { font-size:9px; opacity:.7; }
#strategy-2-maker .tp-toggle { display:inline-flex; align-items:center; gap:6px; min-height:30px; padding:0 8px; border:1px solid rgba(214,181,90,.34); border-radius:999px; background:rgba(255,255,255,.03); font-size:9px; font-weight:800; }
#strategy-2-maker .tp-toggle i { width:16px; height:16px; border-radius:50%; background:#58615e; box-shadow:0 0 0 3px rgba(255,255,255,.035); }
#strategy-2-maker .tp-setting.enabled .tp-toggle { color:#7bf0bd; border-color:rgba(24,201,139,.5); background:rgba(24,201,139,.08); }
#strategy-2-maker .tp-setting.enabled .tp-toggle i { background:var(--s2-green); }
#strategy-2-maker .manual-symbol-toggle { grid-column:1/-1; min-height:44px; margin:0; padding:7px 9px; border-radius:11px; border-color:rgba(214,181,90,.22); }
#strategy-2-maker .manual-symbol-toggle b { font-size:11px; }
#strategy-2-maker .manual-symbol-toggle small { font-size:9px; line-height:1.2; }
#strategy-2-maker .manual-symbol-picker { grid-column:1/-1; margin:0; }
#strategy-2-maker .maker-nav { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:7px; margin-top:9px !important; padding-bottom:max(4px,env(safe-area-inset-bottom)); }
#strategy-2-maker .maker-nav button { min-width:0; min-height:39px; padding:7px 8px; border-radius:10px; font-size:10px; white-space:normal; line-height:1.15; }
#strategy-2-maker .maker-nav button:first-child { border-color:rgba(24,201,139,.5); background:linear-gradient(180deg,rgba(24,201,139,.19),rgba(24,201,139,.08)); }
@media (max-width: 430px) {
  #strategy-2-maker.strategy-two-card { padding:10px; border-radius:15px; }
  #strategy-2-maker .strategy-intro { display:none; }
  #strategy-2-maker .strategy-facts { gap:4px; margin-bottom:6px; }
  #strategy-2-maker .strategy-facts span { padding:4px 3px; font-size:8.5px; }
  #strategy-2-maker .compact-scan { gap:3px; padding:5px; margin-bottom:6px; font-size:9px; }
  #strategy-2-maker .strategy-power-control { margin-bottom:6px; }
  #strategy-2-maker .compact-settings-grid, #strategy-2-maker .position-settings-grid { gap:5px; }
  #strategy-2-maker .compact-settings-grid input { height:34px; font-size:12px; }
  #strategy-2-maker .maker-nav { gap:5px; }
  #strategy-2-maker .maker-nav button { min-height:38px; font-size:9px; }
}
@media (max-width: 350px) {
  #strategy-2-maker .position-settings-grid { grid-template-columns:1fr; }
  #strategy-2-maker .compact-settings-grid { grid-template-columns:1fr 1fr; }
  #strategy-2-maker .maker-nav { grid-template-columns:1fr; }
}
'''
    css_path.write_text(css, encoding="utf-8")

Path("cloud_api/test_strategy2_tp_toggle_20260903.py").write_text(r'''from aster_multi_bb import MultiBbConfig, position_action_preview


def test_take_profit_accepts_free_positive_values_and_persists_toggle():
    for pct in (0.1, 0.25, 0.5, 1, 3.75, 19, 19.5, 23.75, 50):
        cfg = MultiBbConfig.from_mapping({"takeProfit": pct / 100, "takeProfitEnabled": True})
        assert cfg.take_profit == pct / 100
        assert cfg.public_dict()["takeProfitEnabled"] is True


def test_take_profit_disabled_suppresses_preview_target_but_keeps_value():
    cfg = MultiBbConfig.from_mapping({"takeProfit": 0.2375, "takeProfitEnabled": False})
    assert cfg.take_profit == 0.2375
    preview = position_action_preview(row={"positionSide":"LONG","entryPrice":100,"markPrice":130,"positionAmt":1}, state={}, settings=cfg, account_equity=1000)
    assert preview["takeProfitEnabled"] is False
    assert preview["takeProfitPct"] is None
    assert preview["tpPrice"] is None


def test_take_profit_rejects_non_positive_values_even_when_disabled():
    import pytest
    with pytest.raises(ValueError):
        MultiBbConfig.from_mapping({"takeProfit": 0, "takeProfitEnabled": False})
''', encoding="utf-8")

Path("web/tests/strategy2-botsettings-reference-tp-toggle.test.mjs").write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const maker = readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");
const css = readFileSync(new URL("../app/strategy2-reference.css", import.meta.url), "utf8");

test("Botinstellingen keeps real controls and adds persistent TP toggle", () => {
  for (const text of ["Aster live bot", "Instellingen opslaan", "Veilig simuleren", "Readiness controleren", "Zelf munten kiezen"]) assert.match(maker, new RegExp(text));
  assert.match(maker, /takeProfitEnabled: v\.tpEnabled/);
  assert.match(maker, /x\.takeProfitEnabled !== false/);
  assert.match(maker, /role="switch" aria-checked=\{v\.tpEnabled\}/);
  assert.match(maker, /disabled=\{!v\.tpEnabled\}/);
});

test("Botinstellingen reference styling is compact mobile-safe dark green and gold", () => {
  assert.match(css, /Botinstellingen definitive dark-green\/gold reference 2026-09-03/);
  assert.match(css, /#strategy-2-maker \.compact-settings-grid/);
  assert.match(css, /safe-area-inset-bottom/);
  assert.match(css, /@media \(max-width: 430px\)/);
});
''', encoding="utf-8")

print("Botinstellingen + TP toggle patch applied")
