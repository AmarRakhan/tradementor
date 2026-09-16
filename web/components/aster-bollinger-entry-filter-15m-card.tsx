"use client";

export type BollingerEntryTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

type Props = {
  enabled: boolean;
  busy: boolean;
  timeframe: BollingerEntryTimeframe;
  message?: string;
  onToggle: (next: boolean) => void;
  onTimeframeChange: (next: BollingerEntryTimeframe) => void;
};

export const BOLLINGER_ENTRY_FILTER_REFERENCE = "file_00000000938481f4912fc885bdf10916";
export const BOLLINGER_ENTRY_TIMEFRAMES: Array<{ value: BollingerEntryTimeframe; label: string }> = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1u" },
  { value: "4h", label: "4u" },
  { value: "1d", label: "1d" },
];

export function AsterBollingerEntryFilter15mCard({ enabled, busy, timeframe, message, onToggle, onTimeframeChange }: Props) {
  const activeLabel = BOLLINGER_ENTRY_TIMEFRAMES.find((item) => item.value === timeframe)?.label || "15m";
  return <section className="bb-entry-filter-card" data-reference={BOLLINGER_ENTRY_FILTER_REFERENCE} aria-label="Bollinger instapfilter">
    <div className="bb-entry-main">
      <div className="bb-entry-copy">
        <div className="bb-entry-title-row"><span className="bb-entry-new">NEW</span><strong>Bollinger instapfilter</strong></div>
        <p>Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band.</p>
        <small>Live prijs vs {activeLabel} Bollinger Bands · optioneel</small>
        {message ? <em>{message}</em> : null}
      </div>
      <button type="button" className={`bb-entry-toggle ${enabled ? "is-on" : "is-off"}`} role="switch" aria-checked={enabled} disabled={busy}
        onClick={() => onToggle(!enabled)}>
        <span>OFF</span><i aria-hidden="true" /><span>ON</span>
      </button>
    </div>
    {enabled ? <div className="bb-entry-timeframes" role="radiogroup" aria-label="Bollinger timeframe">
      {BOLLINGER_ENTRY_TIMEFRAMES.map((item) => <button key={item.value} type="button" role="radio" aria-checked={timeframe === item.value}
        className={timeframe === item.value ? "is-active" : ""} disabled={busy} onClick={() => onTimeframeChange(item.value)}>{item.label}</button>)}
    </div> : null}
    <style>{`.bb-entry-filter-card{grid-column:1/-1;display:grid;gap:8px;width:100%;min-width:0;padding:10px 11px;border:1px solid rgba(37,224,155,.34);border-radius:11px;background:linear-gradient(100deg,rgba(4,31,22,.91),rgba(3,18,13,.94));box-shadow:inset 0 0 20px rgba(38,226,157,.025)}.bb-entry-main{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;min-width:0}.bb-entry-copy{min-width:0;display:grid;gap:3px}.bb-entry-title-row{display:flex;align-items:center;gap:6px;min-width:0}.bb-entry-title-row strong{color:#e9f5ef;font-size:10px;font-weight:900;letter-spacing:.01em}.bb-entry-new{display:inline-flex;align-items:center;justify-content:center;height:15px;padding:0 5px;border:1px solid rgba(47,239,169,.6);border-radius:4px;background:rgba(17,114,76,.28);color:#52f1b1;font-size:6px;font-weight:1000;letter-spacing:.08em}.bb-entry-copy p{margin:0;color:#a9b9b1;font-size:8px;line-height:1.35}.bb-entry-copy small{color:#5e8978;font-size:7px;line-height:1.3}.bb-entry-copy em{color:#75c9a5;font-size:6.5px;font-style:normal;line-height:1.25}.bb-entry-toggle{display:grid;grid-template-columns:auto 19px auto;align-items:center;gap:4px;min-width:76px;height:30px;padding:0 7px;border:1px solid rgba(62,110,89,.55);border-radius:16px;background:rgba(2,10,8,.75);color:#60746a;font-size:6px;font-weight:1000;letter-spacing:.08em;transition:.16s ease}.bb-entry-toggle i{position:relative;width:19px;height:12px;border-radius:8px;background:#26372f;box-shadow:inset 0 0 0 1px rgba(109,143,126,.24)}.bb-entry-toggle i:after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;border-radius:50%;background:#8c9b94;transition:.16s ease}.bb-entry-toggle.is-on{border-color:rgba(43,236,165,.72);color:#45eca9;box-shadow:0 0 12px rgba(43,236,165,.08)}.bb-entry-toggle.is-on i{background:rgba(31,190,130,.42)}.bb-entry-toggle.is-on i:after{left:9px;background:#48f0ad;box-shadow:0 0 7px rgba(72,240,173,.42)}.bb-entry-toggle:disabled,.bb-entry-timeframes button:disabled{opacity:.55}.bb-entry-timeframes{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;width:100%;min-width:0}.bb-entry-timeframes button{min-width:0;height:25px;padding:0;border:1px solid rgba(62,110,89,.48);border-radius:7px;background:rgba(2,12,9,.72);color:#718a7e;font-size:7px;font-weight:900;line-height:1;transition:.14s ease}.bb-entry-timeframes button.is-active{border-color:rgba(49,239,171,.82);background:linear-gradient(180deg,rgba(26,145,99,.42),rgba(10,82,57,.38));color:#56f0b3;box-shadow:inset 0 0 9px rgba(49,239,171,.08),0 0 8px rgba(49,239,171,.06)}@media(max-width:430px){.bb-entry-filter-card{gap:7px;padding:9px}.bb-entry-main{gap:8px}.bb-entry-copy p{max-width:245px}.bb-entry-toggle{min-width:72px;padding:0 6px}.bb-entry-timeframes{gap:3px}.bb-entry-timeframes button{height:24px;font-size:6.8px}}`}</style>
  </section>;
}
