"use client";
import { useEffect, useRef, useState } from "react";

// Extreme Spike 1.1 (besluiten Amar 22-10-2026)
// - Een wijde Bollinger-filter: BB(20,k). Een niveau betekent "vanaf k" (k en verder).
// - Exclusief met de gewone Bollinger-filter. Alleen nieuwe instappen worden gefilterd.
// - LONG en SHORT apart aan/uit, elk met een eigen tijdframe, Spike-TP en optionele trailing.
// - De bot stapt in op de actuele prijs tijdens de lopende candle (realtime), niet op candle-close.
import {
  SPIKE_LEVELS, SPIKE_MIN_DISTANCE_MAX, SPIKE_MIN_DISTANCE_RECOMMENDED, SPIKE_TIMEFRAMES, SPIKE_TP_MAX, SPIKE_TP_MIN, spikeValidationError,
  type SpikeConfig, type SpikeSideConfig,
} from "@/lib/extreme-spike-settings.mjs";
export {
  spikeConfigFromSettings, spikeSettingsPayload, spikeValidationError, sameSpikeConfig,
} from "@/lib/extreme-spike-settings.mjs";
export type { EntryFilterMode, SpikeConfig, SpikeLevel, SpikeSideConfig, SpikeTimeframe } from "@/lib/extreme-spike-settings.mjs";
const FRAMES = SPIKE_TIMEFRAMES;

type Props = {
  config: SpikeConfig;
  disabled?: boolean;
  message?: string;
  onSave: (next: SpikeConfig) => void;
};

function SideEditor({ label, value, disabled, onChange }: { label: "LONG" | "SHORT"; value: SpikeSideConfig; disabled?: boolean; onChange: (next: SpikeSideConfig) => void }) {
  const set = (patch: Partial<SpikeSideConfig>) => onChange({ ...value, ...patch });
  return <div className={`es-side ${value.enabled ? "on" : "off"}`} data-testid={`spike-side-${label.toLowerCase()}`}>
    <div className="es-side-head">
      <strong>{label}</strong>
      <button type="button" role="switch" aria-checked={value.enabled} disabled={disabled} onClick={() => set({ enabled: !value.enabled })}>{value.enabled ? "AAN" : "UIT"}</button>
    </div>
    {value.enabled ? <>
      <div className="es-timeframe"><small>Tijdframe</small><div>{FRAMES.map((tf) => <button type="button" key={tf} disabled={disabled} aria-pressed={value.timeframe === tf} className={value.timeframe === tf ? "selected" : ""} onClick={() => set({ timeframe: tf })}>{value.timeframe === tf ? "✓ " : ""}{tf === "1h" ? "1u" : tf === "4h" ? "4u" : tf}</button>)}</div></div>
      <label className="es-field"><small>Minimale afstand tot het gemiddelde (%) · aanbevolen {SPIKE_MIN_DISTANCE_RECOMMENDED}%</small>
        <input type="number" inputMode="decimal" min="0" max={SPIKE_MIN_DISTANCE_MAX} step="0.1" disabled={disabled} value={value.minDistancePct} data-testid={`spike-min-distance-${label.toLowerCase()}`} onChange={(e) => set({ minDistancePct: Number(e.target.value) })} /></label>
      <p className="es-hint">{value.minDistancePct > 0
        ? `De bot stapt pas in als de koers minstens ${value.minDistancePct}% ${label === "LONG" ? "onder" : "boven"} het gemiddelde van de laatste 20 candles staat én de gekozen Bollinger-band raakt. In een rustige markt is de band soms maar 0,5–1% van het gemiddelde; dat is dan een gewone ${label === "LONG" ? "daling" : "stijging"} en geen spike. Hoger = minder, maar echtere spikes. Lager = meer instappen, ook in rustige markten. 0 = uit.`
        : `Uit: de bot stapt in zodra de band geraakt wordt, ook als die maar een fractie van een procent van het gemiddelde ligt (rustige markt). Aanbevolen is ${SPIKE_MIN_DISTANCE_RECOMMENDED}%.`}</p>
      <label className="es-field"><small>Spike take profit (% koersbeweging)</small>
        <input type="number" inputMode="decimal" min={SPIKE_TP_MIN} max={SPIKE_TP_MAX} step="0.1" disabled={disabled} value={value.takeProfitPct} onChange={(e) => set({ takeProfitPct: Number(e.target.value) })} /></label>
      <div className="es-trailing">
        <button type="button" role="switch" aria-checked={value.trailingEnabled} disabled={disabled} onClick={() => set({ trailingEnabled: !value.trailingEnabled })}>Trailing {value.trailingEnabled ? "AAN" : "UIT"}</button>
        {value.trailingEnabled ? <label className="es-field"><small>Terugval vanaf hoogste punt (%)</small>
          <input type="number" inputMode="decimal" min="0.05" step="0.05" disabled={disabled} value={value.trailingPct} onChange={(e) => set({ trailingPct: Number(e.target.value) })} /></label> : null}
      </div>
      <p className="es-hint">{value.trailingEnabled
        ? `Vanaf ${value.takeProfitPct}% winst volgt de bot het hoogste punt en sluit bij ${value.trailingPct}% terugval (minimaal ${Math.max(0, value.takeProfitPct - value.trailingPct).toFixed(2)}%).`
        : `Sluit bij ${value.takeProfitPct}% koersbeweging vanaf de instapprijs.`} Na een Auto Hedge geldt de normale TP.</p>
    </> : <p className="es-hint">Geen Spike-instappen aan deze kant.</p>}
  </div>;
}

export function AsterExtremeSpikeEntryCard({ config, disabled, message, onSave }: Props) {
  const [draft, setDraft] = useState<SpikeConfig>(config);
  const [expanded, setExpanded] = useState(false);
  // Build 613: het scherm leest de instellingen elke paar seconden opnieuw; dat gaf telkens een nieuw config-object
  // en wiste wat je net had aangeklikt. Nu alleen bijwerken als de opgeslagen inhoud echt verandert, en een
  // niet-opgeslagen keuze blijft staan (behalve als de server precies jouw keuze terugmeldt).
  const configKey = JSON.stringify(config);
  const lastKey = useRef(configKey);
  useEffect(() => {
    const previous = lastKey.current;
    if (previous === configKey) return;
    lastKey.current = configKey;
    setDraft((current) => {
      const currentKey = JSON.stringify(current);
      return currentKey === previous || currentKey === configKey ? config : current;
    });
  }, [configKey, config]);
  const dirty = JSON.stringify(draft) !== configKey;
  const error = spikeValidationError(draft);
  const patch = (value: Partial<SpikeConfig>) => setDraft({ ...draft, ...value });
  // Build 615 (melding Amar 23-10 01:28): terug van Spike naar Bollinger (of Geen filter) moet direct werken.
  // Die keuzes hebben geen extra velden in deze kaart, dus ze worden meteen opgeslagen; daarna verschijnt de
  // Bollinger-kaart met zijn eigen schakelaar en tijdframes. Extreme Spike blijft een concept tot "opslaan".
  const selectMode = (mode: SpikeConfig["mode"]) => {
    const next = { ...draft, mode };
    setDraft(next);
    if (mode !== "EXTREME_SPIKE" && mode !== config.mode) onSave(next);
  };
  return <section className="extreme-entry-card" aria-label="Instapfilter" data-testid="extreme-spike-entry">
    <div className="es-heading"><strong>Instapfilter</strong><small>Kies hoe de bot nieuwe instappen beoordeelt. Bestaande posities veranderen niet.</small></div>
    <div className="es-mode" role="radiogroup" aria-label="Instapmodus">
      {([["OFF", "Geen extra filter"], ["BOLLINGER", "Bollinger Band"], ["EXTREME_SPIKE", "Extreme Spike"]] as const).map(([mode, title]) =>
        <button key={mode} type="button" role="radio" aria-checked={draft.mode === mode} disabled={disabled} className={draft.mode === mode ? "selected" : ""} onClick={() => selectMode(mode)}><span aria-hidden="true">{draft.mode === mode ? "◉" : "○"}</span>{title}</button>)}
    </div>
    <p className="es-note">Bollinger en Extreme Spike kunnen niet tegelijk aan staan.</p>
    {draft.mode === "EXTREME_SPIKE" && <div className="es-detail">
      <header><span className="es-flash">ϟ</span><span><strong>Extreme Spike</strong><small>Instap zodra de live prijs de wijde Bollinger-band raakt: LONG onder de band, SHORT erboven.</small></span></header>
      <div className="es-level"><small>Bollinger-band (vanaf)</small>
        <button type="button" disabled={disabled} aria-expanded={expanded} aria-controls="spike-level-menu" onClick={() => setExpanded(!expanded)}>20,{draft.level} <em>en verder</em><span>⌄</span></button>
        {expanded && <div id="spike-level-menu" role="listbox" aria-label="Spike-niveau">{SPIKE_LEVELS.map((level) =>
          <button type="button" key={level} role="option" aria-selected={draft.level === level} onClick={() => { patch({ level }); setExpanded(false); }}>20,{level} <small>vanaf {level}σ</small> {draft.level === level ? "✓" : ""}</button>)}</div>}
      </div>
      <SideEditor label="LONG" value={draft.long} disabled={disabled} onChange={(long) => patch({ long })} />
      <SideEditor label="SHORT" value={draft.short} disabled={disabled} onChange={(short) => patch({ short })} />
    </div>}
    {error ? <p role="alert" className="es-error">{error}</p> : null}
    {message ? <p role="status" aria-live="polite" className="es-save-feedback">{message}</p> : null}
    <button type="button" className="es-save" disabled={disabled || !dirty || Boolean(error)} onClick={() => onSave(draft)}>{dirty ? "Instapfilter opslaan" : "Opgeslagen"}</button>
    <style>{`.extreme-entry-card{grid-column:1/-1;padding:12px;border:1px solid rgba(40,205,127,.4);border-radius:14px;background:linear-gradient(150deg,#02170e,#050806);color:#eaf5ef;font-family:inherit}.es-heading{display:grid;gap:3px}.es-heading strong{font-size:15px}.extreme-entry-card small{font-size:11px;color:#9caf9e}.es-mode{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:6px;margin:12px 0}.es-mode button{padding:11px 4px;background:#07130e;color:#f0f6ee;border:1px solid #426344;border-radius:10px;font-weight:700;font-size:11px}.es-mode button span{color:#1aefa6;margin-right:5px}.es-note{padding:10px;border:1px solid #95761c;color:#eac671;border-radius:10px;background:#251c051c;font-size:10px;margin:0}.es-detail{margin-top:10px;padding:11px;border:1px solid #058f57;border-radius:12px;display:grid;gap:12px}.es-detail header{display:flex;align-items:center;gap:10px}.es-detail header>span:nth-child(2){flex:1;display:grid;gap:3px}.es-detail header strong{font-size:14px}.es-flash{display:grid;place-items:center;border-radius:50%;width:32px;height:32px;background:#07512f;color:#42ffbd;font-size:26px}.es-level{position:relative;display:grid;gap:6px}.es-level>button{width:100%;text-align:left;border:1px solid #0aa36e;border-radius:8px;padding:10px;background:#061b14;color:#eafef0;font-size:13px}.es-level>button em{font-style:normal;color:#9caf9e;font-size:11px;margin-left:4px}.es-level>button span{float:right}.es-level [role=listbox]{position:absolute;z-index:40;left:0;right:0;top:100%;background:#06100d;border:1px solid #14bb77;border-radius:8px;max-height:260px;overflow:auto}.es-level [role=option]{display:block;width:100%;text-align:left;background:transparent;color:#eefcf5;border:0;border-bottom:1px solid #254738;padding:11px;font-size:12px}.es-level [aria-selected=true]{background:#075b36}.es-side{display:grid;gap:9px;padding:10px;border:1px solid #2a4a35;border-radius:10px;background:#04110b}.es-side.off{opacity:.8}.es-side-head{display:flex;align-items:center;justify-content:space-between}.es-side-head strong{font-size:13px}.es-side-head button,.es-trailing>button{min-height:30px;padding:0 12px;border-radius:999px;border:1px solid #426344;background:#07130e;color:#d9eee1;font-size:10px;font-weight:900}.es-side-head button[aria-checked=true],.es-trailing>button[aria-checked=true]{border-color:#0af291;background:#063721;color:#8ff4c6}.es-timeframe{display:grid;gap:6px}.es-timeframe>div{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:5px}.es-timeframe button{padding:10px 0;color:#f1f9ef;border-radius:8px;border:1px solid #38603d;background:#07170d;font-size:10px}.extreme-entry-card .es-mode button.selected,.extreme-entry-card .es-timeframe button.selected,.extreme-entry-card .es-timeframe button[aria-pressed=true]{border-color:#0af291!important;background:#0af291!important;background-image:none!important;color:#02170e!important;font-weight:900!important;box-shadow:0 0 10px #0af29188!important}.extreme-entry-card .es-mode button.selected span{color:#02170e!important}.es-field{display:grid;gap:5px}.es-field input{width:100%;min-height:38px;padding:0 10px;border:1px solid #0aa36e;border-radius:8px;background:#061b14;color:#eafef0;font-size:14px}.es-trailing{display:grid;gap:8px}.es-trailing>button{justify-self:start}.es-hint{margin:0;font-size:10px;color:#9caf9e;line-height:1.35}.es-error{margin:10px 0 0;padding:8px 10px;border:1px solid #c0533f;border-radius:9px;color:#ffb3a5;background:#2a0d08;font-size:11px}.es-save-feedback{margin:10px 0 0;padding:7px 10px;border:1px solid rgba(33,214,154,.3);border-radius:9px;color:#d1e9db;background:#06251a;font-size:11px;overflow-wrap:anywhere}.es-save{width:100%;margin-top:10px;min-height:40px;border:1px solid rgba(33,214,154,.52);border-radius:10px;background:rgba(19,115,78,.25);color:#8ff4c6;font-size:12px;font-weight:900}.es-save:disabled{opacity:.4}@media(max-width:420px){.es-mode button{font-size:9px}.es-timeframe button{font-size:9px}}`}</style>
  </section>;
}
