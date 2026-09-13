"use client";

type Props = {
  enabled: boolean;
  busy: boolean;
  message?: string;
  onToggle: (next: boolean) => void;
};

export const BOLLINGER_ENTRY_FILTER_REFERENCE = "file_00000000409081f49fd5473a5a7ee770";

export function AsterBollingerEntryFilter15mCard({ enabled, busy, message, onToggle }: Props) {
  return <section className="bb-entry-filter-card" data-reference={BOLLINGER_ENTRY_FILTER_REFERENCE} aria-label="Bollinger instapfilter 15m">
    <div className="bb-entry-copy">
      <div className="bb-entry-title-row"><span className="bb-entry-new">NEW</span><strong>Bollinger instapfilter 15m</strong></div>
      <p>Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band.</p>
      <small>Live prijs vs 15m Bollinger Bands · optioneel</small>
      {message ? <em>{message}</em> : null}
    </div>
    <button type="button" className={`bb-entry-toggle ${enabled ? "is-on" : "is-off"}`} role="switch" aria-checked={enabled} disabled={busy}
      onClick={() => onToggle(!enabled)}>
      <span>OFF</span><i aria-hidden="true" /><span>ON</span>
    </button>
    <style>{`.bb-entry-filter-card{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;min-width:0;padding:10px 11px;border:1px solid rgba(37,224,155,.34);border-radius:11px;background:linear-gradient(100deg,rgba(4,31,22,.91),rgba(3,18,13,.94));box-shadow:inset 0 0 20px rgba(38,226,157,.025)}.bb-entry-copy{min-width:0;display:grid;gap:3px}.bb-entry-title-row{display:flex;align-items:center;gap:6px;min-width:0}.bb-entry-title-row strong{color:#e9f5ef;font-size:10px;font-weight:900;letter-spacing:.01em}.bb-entry-new{display:inline-flex;align-items:center;justify-content:center;height:15px;padding:0 5px;border:1px solid rgba(47,239,169,.6);border-radius:4px;background:rgba(17,114,76,.28);color:#52f1b1;font-size:6px;font-weight:1000;letter-spacing:.08em}.bb-entry-copy p{margin:0;color:#a9b9b1;font-size:8px;line-height:1.35}.bb-entry-copy small{color:#5e8978;font-size:7px;line-height:1.3}.bb-entry-copy em{color:#75c9a5;font-size:6.5px;font-style:normal;line-height:1.25}.bb-entry-toggle{display:grid;grid-template-columns:auto 19px auto;align-items:center;gap:4px;min-width:76px;height:30px;padding:0 7px;border:1px solid rgba(62,110,89,.55);border-radius:16px;background:rgba(2,10,8,.75);color:#60746a;font-size:6px;font-weight:1000;letter-spacing:.08em;transition:.16s ease}.bb-entry-toggle i{position:relative;width:19px;height:12px;border-radius:8px;background:#26372f;box-shadow:inset 0 0 0 1px rgba(109,143,126,.24)}.bb-entry-toggle i:after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;border-radius:50%;background:#8c9b94;transition:.16s ease}.bb-entry-toggle.is-on{border-color:rgba(43,236,165,.72);color:#45eca9;box-shadow:0 0 12px rgba(43,236,165,.08)}.bb-entry-toggle.is-on i{background:rgba(31,190,130,.42)}.bb-entry-toggle.is-on i:after{left:9px;background:#48f0ad;box-shadow:0 0 7px rgba(72,240,173,.42)}.bb-entry-toggle:disabled{opacity:.55}@media(max-width:430px){.bb-entry-filter-card{gap:8px;padding:9px}.bb-entry-copy p{max-width:245px}.bb-entry-toggle{min-width:72px;padding:0 6px}}`}</style>
  </section>;
}
