"use client";

export type ProfitLockLevelDraft = { profitUsd: string; hedgePercent: string };

const REFERENCE = "file_00000000e8dc82108202dd2e1397c131";

export const DEFAULT_PROFIT_LOCK_LEVELS: ProfitLockLevelDraft[] = [
  { profitUsd: "5", hedgePercent: "20" },
  { profitUsd: "10", hedgePercent: "40" },
  { profitUsd: "15", hedgePercent: "60" },
  { profitUsd: "20", hedgePercent: "80" },
  { profitUsd: "25", hedgePercent: "100" },
];

export function parseProfitLockLevels(value: unknown): ProfitLockLevelDraft[] {
  if (!Array.isArray(value) || !value.length) return DEFAULT_PROFIT_LOCK_LEVELS.map((row) => ({ ...row }));
  const rows = value.flatMap((raw) => {
    if (!raw || typeof raw !== "object") return [];
    const item = raw as Record<string, unknown>;
    const profit = Number(item.profitUsd ?? item.profit);
    const hedge = Number(item.hedgePercent ?? item.hedge);
    return Number.isFinite(profit) && Number.isFinite(hedge)
      ? [{ profitUsd: String(profit), hedgePercent: String(hedge) }]
      : [];
  });
  return rows.length ? rows : DEFAULT_PROFIT_LOCK_LEVELS.map((row) => ({ ...row }));
}

export function validateProfitLockLevels(rows: ProfitLockLevelDraft[]): string | null {
  if (!rows.length) return "Voeg minimaal één Profit Lock-level toe.";
  let previousProfit = 0;
  let previousHedge = 0;
  for (const row of rows) {
    const profit = Number(String(row.profitUsd).replace(",", "."));
    const hedge = Number(String(row.hedgePercent).replace(",", "."));
    if (!Number.isFinite(profit) || profit <= previousProfit) return "Profit-levels moeten positief en strikt oplopend zijn.";
    if (!Number.isFinite(hedge) || hedge <= previousHedge || hedge > 100) return "Hedge-percentages moeten strikt oplopen tot maximaal 100%.";
    previousProfit = profit;
    previousHedge = hedge;
  }
  if (Math.abs(previousHedge - 100) > 1e-9) return "Het laatste Profit Lock-level moet 100% hedge zijn.";
  return null;
}

export function AsterProfitLockLadderPanel({
  enabled,
  levels,
  conflictCount,
  onEnabledChange,
  onLevelsChange,
}: {
  enabled: boolean;
  levels: ProfitLockLevelDraft[];
  conflictCount: number;
  onEnabledChange: (enabled: boolean) => void;
  onLevelsChange: (levels: ProfitLockLevelDraft[]) => void;
}) {
  const updateLevel = (index: number, key: keyof ProfitLockLevelDraft, value: string) => {
    const next = levels.map((row, rowIndex) => rowIndex === index ? { ...row, [key]: value.replace(",", ".") } : row);
    onLevelsChange(next);
  };
  const addLevel = () => {
    if (levels.length >= 20) return;
    const beforeLast = levels.slice(0, -1);
    const last = levels[levels.length - 1] || { profitUsd: "25", hedgePercent: "100" };
    const previous = beforeLast[beforeLast.length - 1];
    const previousProfit = Number(previous?.profitUsd || 0);
    const lastProfit = Number(last.profitUsd || previousProfit + 5);
    const previousHedge = Number(previous?.hedgePercent || 0);
    const suggestedProfit = Math.max(previousProfit + 0.01, (previousProfit + lastProfit) / 2);
    const suggestedHedge = Math.min(99, Math.max(previousHedge + 1, (previousHedge + 100) / 2));
    onLevelsChange([...beforeLast, { profitUsd: String(Number(suggestedProfit.toFixed(2))), hedgePercent: String(Number(suggestedHedge.toFixed(1))) }, last]);
  };
  const removeLevel = (index: number) => {
    if (levels.length <= 1 || index === levels.length - 1) return;
    onLevelsChange(levels.filter((_, rowIndex) => rowIndex !== index));
  };

  return <section className={`pll-settings ${enabled ? "is-on" : "is-off"}`} data-reference={REFERENCE}>
    <div className="pll-toggle-row">
      <div><span className="pll-new">NEW</span><b>Profit Lock Ladder</b><small>Zet opgebouwde winst automatisch trapsgewijs vast met een SHORT-hedge.</small></div>
      <button type="button" role="switch" aria-checked={enabled} className={enabled ? "on" : ""} onClick={() => onEnabledChange(!enabled)}><i />{enabled ? "ON" : "OFF"}</button>
    </div>
    {enabled ? <div className="pll-expanded">
      <div className="pll-rules">
        <p>✓ Hoofdposities zijn altijd <strong>LONG</strong></p>
        <p>✓ DCA blijft LONG bijkopen bij dalingen</p>
        <p>✓ SHORT wordt alleen gebruikt als profit lock</p>
        <p>✓ De bestaande SHORT wordt tijdens de cycle niet automatisch kleiner</p>
        <p>✓ SHORT kan nooit groter worden dan LONG</p>
        <p>✓ Een volgende trede vereist een nieuw netto cycle-profitniveau</p>
        <p>✓ 100% = LONG + Profit Lock SHORT sluiten en nieuwe cycle</p>
      </div>
      <div className="pll-explain"><b>Hoe werkt het?</b><p>De ladder kijkt naar LONG PnL + Profit Lock SHORT PnL + gerealiseerde cycle-winst − cycle-fees. Bij een nieuw winstlevel wordt alleen extra SHORT toegevoegd. Daalt de koers, dan blijft die SHORT staan en mag LONG verder DCA'en.</p></div>
      {conflictCount > 0 ? <div className="pll-warning">⚠ Er {conflictCount === 1 ? "staat" : "staan"} nog {conflictCount} normale SHORT-{conflictCount === 1 ? "positie" : "posities"}. Profit Lock Ladder neemt die niet over of sluit die niet automatisch.</div> : null}
      <div className="pll-ladder-head"><div><small>PROFIT LADDER LEVELS</small><b>Netto cycle-profit → hedge</b></div><button type="button" onClick={addLevel} disabled={levels.length >= 20}>+ Level</button></div>
      <div className="pll-table">
        <div className="pll-tr pll-th"><span>Level</span><span>Net Profit (USDT)</span><span>Hedge</span><span /></div>
        {levels.map((row, index) => <div className="pll-tr" key={`${index}-${levels.length}`}>
          <strong>{index + 1}</strong>
          <label><i>+$</i><input inputMode="decimal" value={row.profitUsd} onChange={(event) => updateLevel(index, "profitUsd", event.target.value)} /></label>
          <label><input inputMode="decimal" value={row.hedgePercent} onChange={(event) => updateLevel(index, "hedgePercent", event.target.value)} /><i>%</i></label>
          {index === levels.length - 1 ? <em>Close + restart</em> : <button type="button" className="pll-remove" onClick={() => removeLevel(index)}>×</button>}
        </div>)}
      </div>
      <div className="pll-direction"><div><small>TRADINGRICHTING</small><strong><i /> LONG <b>(Only)</b></strong></div><span>SHORT-primary is niet beschikbaar zolang Profit Lock Ladder actief is. De SHORT-kant wordt uitsluitend automatisch als winstslot gebruikt.</span></div>
      <div className="pll-note">Bestaande DCA- en TP-instellingen blijven opgeslagen. Gewone TP wordt tijdens deze modus niet uitgevoerd, omdat de ladder de veilige cycle-exit beheert.</div>
    </div> : null}

    <style>{`
      .pll-settings{grid-column:1/-1;border:1px solid rgba(214,181,90,.24);border-radius:12px;background:linear-gradient(180deg,rgba(6,20,16,.96),rgba(2,9,7,.96));overflow:hidden;transition:border-color .18s,box-shadow .18s}.pll-settings.is-on{border-color:#16e99a;box-shadow:0 0 0 1px rgba(22,233,154,.16),0 0 24px rgba(22,233,154,.08)}
      .pll-toggle-row{min-height:55px;padding:9px 10px;display:flex;align-items:center;justify-content:space-between;gap:12px}.pll-toggle-row>div{display:grid;grid-template-columns:auto 1fr;align-items:center;gap:2px 7px}.pll-toggle-row b{font-size:14px;color:#f3f8f5}.pll-toggle-row small{grid-column:1/-1;color:#94a59d;font-size:8.5px;line-height:1.3}.pll-new{padding:2px 5px;border-radius:999px;background:#20e6a0;color:#02130d;font-size:7px;font-weight:950;letter-spacing:.05em}.pll-toggle-row>button{display:flex;align-items:center;gap:5px;min-width:62px;height:31px;padding:0 8px;border:1px solid rgba(109,128,119,.45);border-radius:999px;background:#111c18;color:#91a098;font-size:8px;font-weight:900}.pll-toggle-row>button i{width:17px;height:17px;border-radius:50%;background:#718079}.pll-toggle-row>button.on{justify-content:flex-end;border-color:#21dc99;background:linear-gradient(90deg,#0a7b55,#16d98f);color:#fff}.pll-toggle-row>button.on i{background:#fff;box-shadow:0 0 8px rgba(255,255,255,.55)}
      .pll-expanded{display:grid;grid-template-columns:1fr .9fr;gap:7px;padding:0 9px 9px}.pll-rules,.pll-explain{padding:8px;border:1px solid rgba(53,116,88,.42);border-radius:10px;background:rgba(12,34,26,.72)}.pll-rules p{margin:3px 0;color:#d7e3dc;font-size:8.7px;line-height:1.35}.pll-rules p::first-letter{color:#22e29a}.pll-rules strong{color:#75f4bd}.pll-explain b{font-size:10px;color:#dfeae5}.pll-explain p{margin:5px 0 0;color:#a9bbb2;font-size:8.2px;line-height:1.45}.pll-warning{grid-column:1/-1;padding:7px 8px;border:1px solid rgba(255,137,91,.48);border-radius:9px;background:rgba(125,54,20,.2);color:#ffc09e;font-size:8.5px;line-height:1.35}
      .pll-ladder-head{grid-column:1/-1;display:flex;align-items:end;justify-content:space-between;margin-top:2px}.pll-ladder-head>div{display:grid;gap:1px}.pll-ladder-head small{color:#22e29a;font-size:7px;letter-spacing:.12em}.pll-ladder-head b{font-size:10px}.pll-ladder-head button{height:27px;padding:0 9px;border:1px solid rgba(34,226,154,.42);border-radius:7px;background:rgba(21,108,76,.25);color:#8af4c5;font-size:8px;font-weight:800}.pll-ladder-head button:disabled{opacity:.35}
      .pll-table{grid-column:1/-1;display:grid;border:1px solid rgba(43,89,69,.5);border-radius:10px;overflow:hidden}.pll-tr{display:grid;grid-template-columns:48px 1.15fr 1fr 92px;min-height:35px;align-items:center;border-top:1px solid rgba(50,84,69,.34)}.pll-tr:first-child{border-top:0}.pll-tr>*{padding:5px 7px;min-width:0}.pll-th{min-height:27px;background:rgba(8,25,19,.95);color:#799087;font-size:7px;text-transform:uppercase;letter-spacing:.04em}.pll-tr>strong{font-size:9px;color:#cfdcd5}.pll-tr label{display:flex!important;align-items:center!important;gap:2px!important;margin:0!important;border-left:1px solid rgba(50,84,69,.3)}.pll-tr label input{height:24px!important;padding:0 3px!important;border:0!important;background:transparent!important;color:#fff;font-size:10px!important}.pll-tr label i{font-style:normal;color:#57eab1;font-size:8px;font-weight:800}.pll-tr>em{font-size:7.5px;color:#5af0b6;font-style:normal;text-align:right}.pll-remove{justify-self:end;width:24px;height:24px;border:0;border-radius:6px;background:rgba(255,96,122,.08);color:#ff849b;font-size:15px}
      .pll-direction{grid-column:1/-1;display:grid;grid-template-columns:145px 1fr;align-items:center;gap:9px;padding:8px;border:1px solid rgba(34,226,154,.28);border-radius:9px;background:rgba(8,29,21,.7)}.pll-direction>div{display:grid;gap:3px}.pll-direction small{font-size:7px;color:#789287;letter-spacing:.08em}.pll-direction strong{font-size:10px;color:#a8f5d2}.pll-direction strong i{display:inline-block;width:9px;height:9px;margin-right:4px;border:2px solid #27e59e;border-radius:50%;box-shadow:0 0 0 2px rgba(39,229,158,.12)}.pll-direction strong b{font-size:8px;color:#668076}.pll-direction>span{font-size:8px;color:#9cafA5;line-height:1.35}.pll-note{grid-column:1/-1;padding:6px 8px;border-radius:8px;background:rgba(91,125,196,.08);color:#8fa2ad;font-size:7.7px;line-height:1.35}
      @media(max-width:520px){.pll-expanded{grid-template-columns:1fr}.pll-rules,.pll-explain,.pll-warning,.pll-ladder-head,.pll-table,.pll-direction,.pll-note{grid-column:1}.pll-tr{grid-template-columns:38px 1.2fr .9fr 72px}.pll-direction{grid-template-columns:1fr}.pll-toggle-row b{font-size:12px}}
    `}</style>
  </section>;
}
