"use client";

type CheckState = "ok" | "attention" | "unknown";
type Check = { title: string; expected: string; observed: string; state: CheckState };
function n(value: unknown, fallback = 0) { const parsed = Number(value); return Number.isFinite(parsed) ? parsed : fallback; }
function pct(value: unknown) { return `${(n(value) * 100).toFixed(2)}%`; }
function usd(value: unknown) { return new Intl.NumberFormat("nl-NL", { style: "currency", currency: "USD", maximumFractionDigits: 2 }).format(n(value)); }

export function AsterStrategy2Behavior({ snapshot }: { snapshot: Record<string, unknown> | null }) {
  const state = (snapshot?.strategy2 && typeof snapshot.strategy2 === "object" ? snapshot.strategy2 : {}) as Record<string, unknown>;
  const settings = (state.settings && typeof state.settings === "object" ? state.settings : {}) as Record<string, unknown>;
  const positions = Array.isArray(snapshot?.positions) ? snapshot.positions as Array<Record<string, unknown>> : [];
  const strategyPositions = positions.filter(position => String(position.strategyId ?? "") === "aster-strategy-2");
  const configured = Object.keys(settings).length > 0;
  const target = Math.max(0, Math.round(n(settings.maximumPairs))), targetLong = settings.maximumLongPositions===undefined?Math.ceil(target/2):Math.max(0,Math.round(n(settings.maximumLongPositions))), targetShort = settings.maximumShortPositions===undefined?Math.floor(target/2):Math.max(0,Math.round(n(settings.maximumShortPositions)));
  const actualLong = n(state.longLegs);
  const actualShort = n(state.shortLegs);
  const actual = actualLong + actualShort, enabled = state.enabled === true, phase = String(state.phase || "DRAFT").toUpperCase();
  const maxLongDca = n(settings.longMaxDca), maxShortDca = n(settings.shortMaxDca), maxObservedDca = strategyPositions.reduce((highest,p)=>Math.max(highest,n(p.dcaCount)),0);
  const checks: Check[] = [
    { title:"Botstatus",expected:enabled?"De engine hoort actief te monitoren en handelen volgens deze configuratie.":"De engine hoort geen nieuwe exposure te openen.",observed:enabled?`Actief · fase ${phase}`:`Uit · fase ${phase}`,state:enabled?(phase==="DRAFT"||phase==="CONFIGURED"?"attention":"ok"):"ok" },
    { title:"Gebalanceerde start",expected:`${targetLong} LONG en ${targetShort} SHORT zo snel mogelijk opbouwen; daarna maximaal één normale nieuwe positie per minuut.`,observed:`${actualLong} LONG en ${actualShort} SHORT (${actual}/${target})`,state:!enabled?"unknown":actual>target||Math.abs(actualLong-actualShort)>1?"attention":actual===target?"ok":"unknown" },
    { title:"DCA-grenzen",expected:settings.dcaEnabled===false?"Geen DCA-orders uitvoeren.":`Maximaal ${maxLongDca} LONG- en ${maxShortDca} SHORT-DCA-stappen per kant.`,observed:strategyPositions.length?`Hoogste bewezen Strategy-2-DCA-aantal: ${maxObservedDca}`:"Geen bewezen Strategy-2-posities om te controleren.",state:strategyPositions.length?(maxObservedDca>Math.max(maxLongDca,maxShortDca)?"attention":"ok"):"unknown" },
    { title:"Take Profit en herstart",expected:`Bij netto ${pct(settings.takeProfit)} vanaf weighted entry volledig sluiten wanneer protection dit veilig vindt${settings.autoRestart===false?". Niet automatisch herstarten.":", daarna klein herstarten met de nieuwste Base Order."}`,observed:"Een concrete TP-close is pas bewijsbaar uit exchange-fills en audit-events; huidige positie-snapshot alleen is onvoldoende.",state:"unknown" },
    { title:"Portfolio Protection",expected:settings.protectionEnabled===false?"Protection staat uit; normale harvestregels blijven gelden.":`Vanaf circa ${pct(settings.cautionDrawdown)} drawdown risico opvoeren en bestaande tegenovergestelde exposure zo nodig beschermen.`,observed:String(state.riskMode||state.protectionStatus||"Geen protection-event in de huidige publieke snapshot"),state:"unknown" },
  ];
  const attention=checks.filter(c=>c.state==="attention").length, known=checks.filter(c=>c.state!=="unknown").length;
  function openSettings(){
    document.getElementById("strategy-2-maker")?.scrollIntoView({ behavior:"smooth", block:"start" });
    window.dispatchEvent(new Event("tradementor:open-strategy2-maker"));
  }
  return <section className="strategy-behavior" aria-labelledby="strategy-behavior-title">
    <header><div><span>STRATEGY 2 · UITLEG EN CONTROLE</span><h2 id="strategy-behavior-title">Wat is ingesteld en doet de bot wat hij hoort te doen?</h2><p>Dit overzicht leest dezelfde serverbevestigde configuratie als de Strategy Maker. Wijzigen gebeurt op één plek.</p></div><div className="behavior-header-actions"><div className={`behavior-verdict ${attention?"attention":"ok"}`}><strong>{attention?`${attention} aandachtspunt${attention===1?"":"en"}`:"Geen zichtbare afwijking"}</strong><small>{known}/{checks.length} controles nu bewijsbaar</small></div>{configured&&<button className="inline-settings-action" type="button" onClick={openSettings}>Open Strategy Maker</button>}</div></header>
    {!configured?<div className="strategy-behavior-empty"><strong>Nog geen opgeslagen Strategy-2-configuratie</strong><span>Open Strategy Maker om de eerste instellingen vast te leggen.</span></div>:<>
      <div className="strategy-config-summary"><Config label="Naam" value={String(settings.name||"Dual Profit Harvest DCA")}/><Config label="Basisorder per positie" value={usd(settings.baseNotional)}/><Config label="Take Profit" value={pct(settings.takeProfit)}/><Config label="Startposities" value={`${target} (${targetLong} LONG / ${targetShort} SHORT)`}/><Config label="Aster USDT-universum" value={`Top ${n(settings.universeTopN)} · min. 24h volume ${usd(settings.minimumQuoteVolume24hUsdt||10000000)}`}/><Config label="Leverage / margin" value={`${n(settings.leverage)}× · ${String(settings.marginMode||"—")}`}/><Config label="LONG / SHORT DCA" value={settings.dcaEnabled===false?"Uit":`${pct(settings.longDcaDistance)} / ${pct(settings.shortDcaDistance)}`}/><Config label="DCA-limiet" value={settings.dcaEnabled===false?"Uit":`${maxLongDca} LONG / ${maxShortDca} SHORT`}/><Config label="Auto Restart" value={settings.autoRestart===false?"Uit":"Aan"}/><Config label="Protection" value={settings.protectionEnabled===false?"Uit":`Aan vanaf ${pct(settings.cautionDrawdown)} drawdown`}/><Config label="Strategy Budget" value={pct(settings.strategyBudget)}/><Config label="Uitvoering" value={String(settings.mode||"paper").toUpperCase()}/></div>
      <div className="strategy-behavior-list">{checks.map(check=><article key={check.title} className={check.state}><div className="behavior-state" aria-label={check.state==="ok"?"Klopt":check.state==="attention"?"Aandacht nodig":"Nog niet bewijsbaar"}>{check.state==="ok"?"✓":check.state==="attention"?"!":"?"}</div><div><h3>{check.title}</h3><dl><div><dt>Zo hoort het</dt><dd>{check.expected}</dd></div><div><dt>Werkelijk gezien</dt><dd>{check.observed}</dd></div></dl></div></article>)}</div>
    </>}</section>;
}
function Config({label,value}:{label:string;value:string}){return <div><span>{label}</span><strong>{value}</strong></div>}
