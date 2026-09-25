"use client";

/*
  FRIENDS visual sources of truth:
  A file_00000000482c820eb79648deaf26728b / e319405b-1385-4db6-a1ce-b24595e91366
  B file_0000000020e881f7a6b8ed2dbcb30de1 / f2917f9c-e5c1-4358-9ce6-3524d76f73d4
  C file_00000000c5d0820ea69cedf6cfd83029 / adf534c8-6fe4-484d-adaa-288160e5420e
  D file_00000000ff74820bb4f33e59ac402422 / 129eb42f-8cfe-40ca-8641-5f0592fe3155
*/

import { useCallback, useEffect, useMemo, useState } from "react";
import { useAuthSession } from "@/components/auth-provider";
import styles from "./friends-view.module.css";

type Period = "1D" | "7D" | "30D" | "ALL";
type ProfileTab = "overview" | "stats" | "settings" | "strategies";
type Screen = "ranking" | "profile" | "compare";

type Performance = {
  reliable: boolean;
  period: Period;
  growthPercent: number | null;
  averageDailyPercent: number | null;
  winningDaysPercent: number | null;
  maxDrawdownPercent: number | null;
  volatilityPercent: number | null;
  measuredDays: number;
  sparkline: number[];
};

type Risk = {
  score: number;
  label: string;
  configuredLeverage: number;
  dcaDistancePercent: number;
  maxDca: number;
  stopLossEnabled: boolean;
  protectionEnabled: boolean;
  bollingerFilterEnabled: boolean;
  components: {
    leverage: number;
    dcaAggressiveness: number;
    positionBuildUp: number;
    protection: number;
    historical: number;
  };
};

type Trader = {
  friendId: string;
  isMe: boolean;
  name: string;
  initial: string;
  presence: string;
  lastActiveAt: string | null;
  rank: number | null;
  performance: Performance;
  risk: Risk;
  strategies: Array<{ id: string; name: string; accent: string }>;
  settings: Array<{ key: string; label: string; value: string; icon: string }>;
  learningPoints: Array<{ title: string; text: string }>;
  dataStatus: string;
};

type OverviewPayload = {
  period: Period;
  group: {
    traders: number;
    averageDailyGrowthPercent: number | null;
    averageRiskScore: number | null;
    privacy: string;
  };
  traders: Trader[];
};

type Insight = { id: string; friendId: string; name: string; initial: string; text: string; createdAt: string | null };

const periods: Array<{ id: Period; label: string }> = [
  { id: "1D", label: "1D" },
  { id: "7D", label: "7D" },
  { id: "30D", label: "30D" },
  { id: "ALL", label: "Alles" },
];

function fmt(value: number | null | undefined, digits = 1, suffix = "%") {
  return value == null || !Number.isFinite(value) ? "—" : `${value >= 0 ? "+" : ""}${value.toFixed(digits)}${suffix}`;
}

function compact(value: number | null | undefined, digits = 1) {
  return value == null || !Number.isFinite(value) ? "—" : value.toFixed(digits);
}

function Icon({ name, size = 22 }: { name: string; size?: number }) {
  const common = { width: size, height: size, viewBox: "0 0 24 24", fill: "none", stroke: "currentColor", strokeWidth: 1.9, strokeLinecap: "round" as const, strokeLinejoin: "round" as const, "aria-hidden": true };
  if (name === "users") return <svg {...common}><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>;
  if (name === "shield") return <svg {...common}><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><path d="m9 12 2 2 4-4"/></svg>;
  if (name === "trophy") return <svg {...common}><path d="M8 21h8M12 17v4M7 4h10v4a5 5 0 0 1-10 0V4Z"/><path d="M7 6H4v2a4 4 0 0 0 4 4M17 6h3v2a4 4 0 0 1-4 4"/></svg>;
  if (name === "scale") return <svg {...common}><path d="M12 3v18M5 7h14M5 7l-3 6h6L5 7Zm14 0-3 6h6l-3-6ZM8 21h8"/></svg>;
  if (name === "target") return <svg {...common}><circle cx="12" cy="12" r="9"/><circle cx="12" cy="12" r="5"/><circle cx="12" cy="12" r="1.5"/></svg>;
  if (name === "filter") return <svg {...common}><path d="M4 5h16l-6 7v5l-4 2v-7L4 5Z"/></svg>;
  if (name === "layers") return <svg {...common}><path d="m12 2 9 5-9 5-9-5 9-5Z"/><path d="m3 12 9 5 9-5M3 17l9 5 9-5"/></svg>;
  if (name === "light") return <svg {...common}><path d="M9 18h6M10 22h4"/><path d="M8.5 14.5A6 6 0 1 1 15.5 14.5C14.6 15.2 14 16 14 18h-4c0-2-.6-2.8-1.5-3.5Z"/></svg>;
  if (name === "chart") return <svg {...common}><path d="M3 3v18h18"/><path d="m7 15 4-4 3 3 6-7"/></svg>;
  if (name === "bars") return <svg {...common}><path d="M4 20V10M10 20V4M16 20v-7M22 20V8"/></svg>;
  if (name === "restart") return <svg {...common}><path d="M3 12a9 9 0 1 0 3-6.7L3 8"/><path d="M3 3v5h5"/></svg>;
  if (name === "bolt") return <svg {...common}><path d="m13 2-9 12h8l-1 8 9-12h-8l1-8Z"/></svg>;
  if (name === "back") return <svg {...common}><path d="m15 18-6-6 6-6"/></svg>;
  if (name === "chevron") return <svg {...common}><path d="m9 18 6-6-6-6"/></svg>;
  if (name === "heart") return <svg {...common}><path d="M20.8 4.6a5.5 5.5 0 0 0-7.8 0L12 5.6l-1-1a5.5 5.5 0 0 0-7.8 7.8l1 1L12 21l7.8-7.6 1-1a5.5 5.5 0 0 0 0-7.8Z"/></svg>;
  return <svg {...common}><circle cx="12" cy="12" r="9"/><path d="M12 8v4l3 2"/></svg>;
}

function Avatar({ trader, large = false }: { trader: Pick<Trader, "initial" | "name" | "isMe">; large?: boolean }) {
  return <div className={`${styles.avatar} ${large ? styles.avatarLarge : ""} ${trader.isMe ? styles.avatarMe : ""}`} aria-label={trader.name}>{trader.initial}</div>;
}

function Sparkline({ values }: { values: number[] }) {
  if (!values?.length) return <div className={styles.sparkEmpty}>Nog onvoldoende data</div>;
  const width = 154, height = 46, pad = 3;
  const min = Math.min(...values), max = Math.max(...values);
  const span = Math.max(.0001, max - min);
  const points = values.map((value, index) => {
    const x = pad + index * ((width - pad * 2) / Math.max(1, values.length - 1));
    const y = height - pad - ((value - min) / span) * (height - pad * 2);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return <svg className={styles.spark} viewBox={`0 0 ${width} ${height}`} role="img" aria-label="Genormaliseerde rendementslijn"><polyline points={points} /></svg>;
}

function PeriodTabs({ value, onChange }: { value: Period; onChange: (next: Period) => void }) {
  return <div className={styles.periodTabs}>{periods.map(item =>
    <button type="button" key={item.id} className={value === item.id ? styles.periodActive : ""} onClick={() => onChange(item.id)}>{item.label}</button>
  )}</div>;
}

function RiskPill({ risk }: { risk: Risk }) {
  const tone = risk.score >= 7.5 ? styles.riskHigh : risk.score >= 6 ? styles.riskRaised : risk.score >= 3.5 ? styles.riskBalanced : styles.riskLow;
  return <span className={`${styles.riskPill} ${tone}`}><Icon name="shield" size={15}/>{risk.label}</span>;
}

function StrategyTags({ rows }: { rows: Trader["strategies"] }) {
  return <div className={styles.strategyTags}>{rows.length ? rows.map(row =>
    <span key={row.id} data-accent={row.accent}>{row.name}</span>
  ) : <span data-accent="muted">Nog onvoldoende data</span>}</div>;
}

function Metric({ label, value, accent = false }: { label: string; value: string; accent?: boolean }) {
  return <div className={styles.metric}><span>{label}</span><strong className={accent ? styles.accent : ""}>{value}</strong></div>;
}

function MainRanking({ data, period, onPeriod, onTrader, onCompare, insights, onInsight }: {
  data: OverviewPayload; period: Period; onPeriod: (p: Period) => void; onTrader: (t: Trader) => void;
  onCompare: () => void; insights: Insight[]; onInsight: () => void;
}) {
  return <div className={styles.screen} data-friends-screen="ranking">
    <header className={styles.hero}>
      <div className={styles.heroTitle}><span className={styles.heroIcon}><Icon name="users" size={30}/></span><div><h1>Friends</h1><p>Leer van elkaar. Groei slim.</p></div></div>
      <div className={styles.heroQuote}>“Rendement vertelt één helft. Risico de andere.”</div>
    </header>

    <section className={styles.groupKpis}>
      <div><Icon name="users"/><strong>{data.group.traders}</strong><span>traders in je groep</span></div>
      <div><Icon name="chart"/><strong>{fmt(data.group.averageDailyGrowthPercent)}</strong><span>gem. daggroei</span></div>
      <div><Icon name="shield"/><strong>{data.group.averageRiskScore == null ? "—" : `${data.group.averageRiskScore.toFixed(1)}/10`}</strong><span>gem. risico</span></div>
    </section>

    <div className={styles.periodLine}><PeriodTabs value={period} onChange={onPeriod}/></div>

    <section>
      <div className={styles.sectionHeading}><div><Icon name="trophy"/><h2>Ranking {period === "1D" ? "vandaag" : period.toLowerCase()}</h2></div><span>Rendement én risico</span></div>
      <div className={styles.traderList}>
        {data.traders.map(trader => <button type="button" className={styles.traderCard} key={trader.friendId} onClick={() => onTrader(trader)}>
          <div className={styles.rankCell} data-rank={trader.rank || "none"}>{trader.rank ?? "—"}</div>
          <Avatar trader={trader}/>
          <div className={styles.traderIdentity}><strong>{trader.name}{trader.isMe ? <span className={styles.meMark}>JIJ</span> : null}</strong><span><i className={trader.presence === "Online" ? styles.online : styles.away}/>{trader.presence}</span></div>
          <div className={styles.growthCell}><strong>{trader.performance.reliable ? fmt(trader.performance.growthPercent) : "—"}</strong><span>{period}</span></div>
          <div className={styles.sparkCell}><Sparkline values={trader.performance.sparkline}/></div>
          <div className={styles.cardRisk}><RiskPill risk={trader.risk}/></div>
          <div className={styles.cardStats}>
            <Metric label="Gem. per dag" value={fmt(trader.performance.averageDailyPercent)} accent/>
            <Metric label="Risicoscore" value={`${trader.risk.score.toFixed(1)}/10`}/>
            <Metric label="Max drawdown" value={fmt(trader.performance.maxDrawdownPercent)}/>
            <Metric label="Leverage" value={`${trader.risk.configuredLeverage}x`}/>
          </div>
          <div className={styles.cardStrategies}><span>Top strategieën</span><StrategyTags rows={trader.strategies}/></div>
          <span className={styles.cardChevron}><Icon name="chevron" size={20}/></span>
        </button>)}
      </div>
    </section>

    <div className={styles.privacyStrip}><Icon name="shield" size={18}/><span>{data.group.privacy} — focus op leren, niet op bedragen.</span></div>

    <section className={styles.twoPanels}>
      <article className={styles.infoPanel}><div className={styles.panelTitle}><Icon name="layers"/><h3>Meest gebruikte strategieën</h3></div>
        {["Zone Strategy","Aster Focus","Sniper"].map(name => {
          const count=data.traders.filter(t=>t.strategies.some(s=>s.name===name)).length;
          return <div className={styles.barRow} key={name}><span>{name}</span><div><i style={{width:`${data.traders.length ? count/data.traders.length*100 : 0}%`}}/></div><b>{count}/{data.traders.length}</b></div>;
        })}
      </article>
      <article className={styles.infoPanel}><div className={styles.panelTitle}><Icon name="shield"/><h3>Risico in context</h3></div>
        <p className={styles.explain}>Hogere leverage is geen “winnaar”. De score combineert leverage, DCA, positie-opbouw, bescherming en historische drawdown/volatiliteit.</p>
        <button type="button" className={styles.secondaryCta} onClick={onCompare}><Icon name="scale"/>Vergelijk risico's<Icon name="chevron" size={18}/></button>
      </article>
    </section>

    <section className={styles.insights}>
      <div className={styles.sectionHeading}><div><Icon name="light"/><h2>Laatste inzichten</h2></div><button type="button" onClick={onInsight}>Deel inzicht</button></div>
      {insights.length ? insights.slice(0,4).map(row => <article key={row.id} className={styles.insightRow}><div className={styles.miniAvatar}>{row.initial}</div><div><strong>{row.name}</strong><p>{row.text}</p></div><Icon name="heart" size={18}/></article>) :
        <div className={styles.emptyPanel}>Nog geen gedeelde inzichten.</div>}
    </section>
  </div>;
}

function Profile({ trader, tab, setTab, period, onPeriod, onBack, onCompare }: {
  trader: Trader; tab: ProfileTab; setTab: (t: ProfileTab) => void; period: Period; onPeriod: (p: Period)=>void; onBack:()=>void; onCompare:()=>void;
}) {
  const tabs: Array<[ProfileTab,string]> = [["overview","Overzicht"],["stats","Statistieken"],["settings","Instellingen"],["strategies","Strategieën"]];
  return <div className={styles.screen} data-friends-screen="profile">
    <button type="button" className={styles.backButton} onClick={onBack}><Icon name="back"/>Terug naar Friends</button>
    <header className={styles.profileHeader}><Avatar trader={trader} large/><div className={styles.profileIdentity}><h1>{trader.name}{trader.isMe ? <span className={styles.meMark}>JIJ</span> : null}</h1><span><i className={trader.presence === "Online" ? styles.online : styles.away}/>{trader.presence}</span><p>Rendement, strategie en risico in één profiel.</p></div><RiskPill risk={trader.risk}/></header>
    <nav className={styles.profileTabs}>{tabs.map(([id,label])=><button type="button" key={id} className={tab===id?styles.profileTabActive:""} onClick={()=>setTab(id)}>{label}</button>)}</nav>

    {tab === "overview" && <div className={styles.profileStack}>
      <section className={styles.performanceHero}><div className={styles.sectionHeading}><div><Icon name="bars"/><h2>Prestaties {period === "1D" ? "vandaag" : period}</h2></div><PeriodTabs value={period} onChange={onPeriod}/></div>
        <div className={styles.performanceMain}><div><strong>{trader.performance.reliable?fmt(trader.performance.growthPercent):"—"}</strong><span>{trader.performance.reliable ? period : "Nog onvoldoende data"}</span></div><Sparkline values={trader.performance.sparkline}/></div>
        <div className={styles.fourStats}><Metric label="Gem. per dag" value={fmt(trader.performance.averageDailyPercent)} accent/><Metric label="Winstgevende dagen" value={trader.performance.winningDaysPercent==null?"—":`${trader.performance.winningDaysPercent.toFixed(0)}%`}/><Metric label="Max drawdown" value={fmt(trader.performance.maxDrawdownPercent)}/><Metric label="Risicoscore" value={`${trader.risk.score.toFixed(1)}/10`} accent/></div>
      </section>
      <RiskProfile trader={trader}/>
      <StrategySection trader={trader}/>
      <Learning trader={trader}/>
      <button type="button" className={styles.primaryCta} onClick={()=>setTab("settings")}><Icon name="shield"/>Bekijk instellingen<Icon name="chevron"/></button>
    </div>}

    {tab === "stats" && <div className={styles.profileStack}>
      <section className={styles.infoPanel}><div className={styles.sectionHeading}><div><Icon name="chart"/><h2>Statistieken</h2></div><PeriodTabs value={period} onChange={onPeriod}/></div>
        <div className={styles.statGrid}><Metric label="Rendement" value={fmt(trader.performance.growthPercent)} accent/><Metric label="Gem. per dag" value={fmt(trader.performance.averageDailyPercent)}/><Metric label="Winstgevende dagen" value={trader.performance.winningDaysPercent==null?"—":`${trader.performance.winningDaysPercent.toFixed(0)}%`}/><Metric label="Max drawdown" value={fmt(trader.performance.maxDrawdownPercent)}/><Metric label="Volatiliteit" value={fmt(trader.performance.volatilityPercent)}/><Metric label="Meetdagen" value={String(trader.performance.measuredDays)}/></div>
        <div className={styles.largeSpark}><Sparkline values={trader.performance.sparkline}/></div>
      </section>
      <RiskProfile trader={trader}/>
    </div>}

    {tab === "settings" && <Settings trader={trader} onCompare={onCompare}/>}

    {tab === "strategies" && <div className={styles.profileStack}><StrategySection trader={trader}/>
      <section className={styles.infoPanel}><div className={styles.panelTitle}><Icon name="chart"/><h3>Strategieperformance</h3></div><p className={styles.explain}>Per-strategie rendement wordt alleen getoond zodra een betrouwbare procentuele basis beschikbaar is. Dollar-PnL wordt nooit gedeeld.</p><div className={styles.emptyPanel}>Nog onvoldoende genormaliseerde strategie-data.</div></section>
    </div>}
  </div>;
}

function RiskProfile({ trader }: { trader: Trader }) {
  const rows = [
    ["Leverage-risico", trader.risk.components.leverage, "chart"],
    ["DCA-agressie", trader.risk.components.dcaAggressiveness, "layers"],
    ["Positie-opbouw", trader.risk.components.positionBuildUp, "users"],
    ["Bescherming", trader.risk.components.protection, "shield"],
  ] as const;
  return <section className={styles.infoPanel}><div className={styles.sectionHeading}><div><Icon name="shield"/><h2>Risicoprofiel</h2></div><RiskPill risk={trader.risk}/></div>
    <div className={styles.riskGrid}>{rows.map(([label,value,icon])=><div className={styles.riskFactor} key={label}><div><Icon name={icon}/><span>{label}</span><b>{value.toFixed(1)}/10</b></div><div className={styles.riskTrack}><i style={{width:`${value*10}%`}}/></div></div>)}</div>
  </section>;
}

function StrategySection({ trader }: { trader: Trader }) {
  return <section className={styles.infoPanel}><div className={styles.sectionHeading}><div><Icon name="target"/><h2>Top strategieën</h2></div><span>Max. drie</span></div>
    <div className={styles.strategyCards}>{trader.strategies.length ? trader.strategies.map(row=><article key={row.id} data-accent={row.accent}><Icon name={row.id==="sniper"?"bolt":row.id==="zone"?"layers":"target"}/><h3>{row.name}</h3><p>Gebruik en risicoprofiel op basis van echte opgeslagen strategie-evidence.</p></article>) : <div className={styles.emptyPanel}>Nog onvoldoende strategie-data.</div>}</div>
  </section>;
}

function Learning({ trader }: { trader: Trader }) {
  return <section className={styles.infoPanel}><div className={styles.sectionHeading}><div><Icon name="light"/><h2>Wat je van {trader.name} kunt leren</h2></div><span>Evidence-based</span></div>
    <div className={styles.learningList}>{trader.learningPoints.map((point,index)=><div key={point.title}><b>{index+1}</b><span><strong>{point.title}</strong><small>{point.text}</small></span></div>)}</div>
  </section>;
}

function Settings({ trader, onCompare }: { trader: Trader; onCompare: ()=>void }) {
  const factorRows = [
    ["Leverage risico", trader.risk.components.leverage],
    ["DCA tempo", trader.risk.components.dcaAggressiveness],
    ["Positie-opbouw", trader.risk.components.positionBuildUp],
    ["Bescherming", 10-trader.risk.components.protection],
    ["Totale risicoklasse", trader.risk.score],
  ] as const;
  const reasons = [
    trader.risk.configuredLeverage >= 50 ? `${trader.risk.configuredLeverage}x ingestelde leverage verhoogt het theoretische risico.` : `${trader.risk.configuredLeverage}x leverage houdt de leveragecomponent relatief beperkt.`,
    trader.risk.maxDca > 0 ? `DCA gebruikt maximaal ${trader.risk.maxDca} stappen met circa ${trader.risk.dcaDistancePercent.toFixed(2)}% afstand.` : "DCA is niet actief binnen de gedeelde configuratie.",
    trader.risk.stopLossEnabled || trader.risk.protectionEnabled ? "Actieve beschermingsregels verlagen de downside-component van de totaalscore." : "Geen expliciete stoploss/protection evidence verhoogt de beschermingscomponent.",
  ];
  return <div className={styles.profileStack} data-friends-settings="true">
    <section><div className={styles.sectionHeading}><div><Icon name="shield"/><h2>{trader.name} instellingen</h2></div><span>Privacy-safe</span></div>
      <p className={styles.sectionIntro}>Bekijk alleen instellingen die veilig als metadata of verhouding gedeeld kunnen worden. Absolute portfolio- en positiedollars blijven verborgen.</p>
      <div className={styles.settingsGrid}>{trader.settings.map(row=><article key={row.key}><span className={styles.settingIcon}><Icon name={row.icon}/></span><div><small>{row.label}</small><strong>{row.value}</strong></div><Icon name="chevron" size={18}/></article>)}</div>
    </section>
    <section className={styles.infoPanel}><div className={styles.sectionHeading}><div><Icon name="shield"/><h2>Risico afgeleid uit instellingen</h2></div><span>Server-side</span></div>
      <div className={styles.riskBands}>{factorRows.map(([label,value])=><div key={label}><span>{label}</span><div>{Array.from({length:5}).map((_,index)=><i key={index} className={index < Math.round(value/2) ? styles.bandOn : ""}/>)}</div><b>{value <= 3.4 ? "Laag" : value <= 5.9 ? "Matig" : value <= 7.4 ? "Hoog" : "Zeer hoog"}</b></div>)}</div>
      <div className={styles.whyBox}><Icon name="light"/><div><strong>Waarom is dit een {trader.risk.label.toLowerCase()} risicoprofiel?</strong>{reasons.map(row=><p key={row}>{row}</p>)}</div></div>
    </section>
    <button type="button" className={styles.primaryCta} onClick={onCompare}><Icon name="users"/>Vergelijk met jouw setup<Icon name="chevron"/></button>
  </div>;
}

function Compare({ traders, period, onPeriod, onBack }: { traders: Trader[]; period: Period; onPeriod:(p:Period)=>void; onBack:()=>void }) {
  const metrics = [
    ["Dagelijkse groei", (t:Trader)=>fmt(t.performance.averageDailyPercent)],
    ["Rendement periode", (t:Trader)=>fmt(t.performance.growthPercent)],
    ["Risicoscore", (t:Trader)=>`${t.risk.score.toFixed(1)}/10`],
    ["Max drawdown", (t:Trader)=>fmt(t.performance.maxDrawdownPercent)],
    ["Leverage", (t:Trader)=>`${t.risk.configuredLeverage}x`],
    ["DCA afstand", (t:Trader)=>`${t.risk.dcaDistancePercent.toFixed(2)}%`],
  ] as const;
  return <div className={styles.screen} data-friends-screen="compare">
    <button type="button" className={styles.backButton} onClick={onBack}><Icon name="back"/>Terug naar Friends</button>
    <header className={styles.compareHero}><div className={styles.heroTitle}><span className={styles.heroIcon}><Icon name="scale" size={30}/></span><div><h1>Vergelijk & leer</h1><p>Rendement versus risico. Verschillende stijlen, dezelfde data.</p></div></div><PeriodTabs value={period} onChange={onPeriod}/></header>
    <section className={styles.compareAvatars}>{traders.map(t=><div key={t.friendId}><Avatar trader={t}/><span>{t.name}</span>{t.isMe?<small>JIJ</small>:null}</div>)}</section>
    <section><div className={styles.sectionHeading}><div><Icon name="bars"/><h2>Rendement vs risico</h2></div><span>Geen risicometric is een “winnaar”</span></div>
      <div className={styles.compareGrid}>{metrics.map(([label,get])=><article key={label}><h3>{label}</h3>{traders.map(t=><div key={t.friendId}><span>{t.name}</span><b>{get(t)}</b></div>)}</article>)}</div>
    </section>
    <section className={styles.infoPanel}><div className={styles.panelTitle}><Icon name="light"/><h3>Belangrijk om te onthouden</h3></div><p className={styles.explain}>Hoger rendement kan samengaan met hoger risico. Vergelijk daarom altijd drawdown, leverage, DCA-opbouw en bescherming voordat je ideeën uit een andere setup overneemt.</p></section>
    <section><div className={styles.sectionHeading}><div><Icon name="shield"/><h2>Wie gebruikt welk risicoprofiel?</h2></div><span>Beschrijvend, niet rangschikkend</span></div><div className={styles.comparePeople}>{traders.map(t=><article key={t.friendId}><Avatar trader={t}/><strong>{t.name}</strong><RiskPill risk={t.risk}/><StrategyTags rows={t.strategies}/></article>)}</div></section>
  </div>;
}

export function FriendsView() {
  const { idToken, cloudReady } = useAuthSession();
  const [period, setPeriod] = useState<Period>("1D");
  const [data, setData] = useState<OverviewPayload | null>(null);
  const [screen, setScreen] = useState<Screen>("ranking");
  const [selectedId, setSelectedId] = useState<string>("");
  const [profileTab, setProfileTab] = useState<ProfileTab>("overview");
  const [insights, setInsights] = useState<Insight[]>([]);
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  const request = useCallback(async (url: string, init?: RequestInit) => {
    const token = await idToken();
    const response = await fetch(url, { ...init, cache:"no-store", headers:{ Authorization:`Bearer ${token}`, "Content-Type":"application/json", ...(init?.headers||{}) } });
    if (!response.ok) {
      const detail = await response.json().catch(()=>({}));
      throw new Error(String(detail.detail || "Friends-data kon niet worden geladen."));
    }
    return response.json();
  }, [idToken]);

  useEffect(() => {
    if (!cloudReady) return;
    let cancelled=false;
    setLoading(true); setError("");
    request(`/api/friends?period=${period}`).then((payload:OverviewPayload)=>{if(!cancelled)setData(payload);}).catch(reason=>{if(!cancelled)setError(reason instanceof Error?reason.message:"Friends-data kon niet worden geladen.");}).finally(()=>{if(!cancelled)setLoading(false);});
    return ()=>{cancelled=true;};
  }, [cloudReady, period, request]);

  useEffect(() => {
    if (!cloudReady) return;
    request("/api/friends/insights").then(payload=>setInsights(Array.isArray(payload.insights)?payload.insights:[])).catch(()=>setInsights([]));
  }, [cloudReady, request]);

  const selected = useMemo(()=>data?.traders.find(row=>row.friendId===selectedId) || null,[data,selectedId]);

  const openTrader=(trader:Trader)=>{setSelectedId(trader.friendId);setProfileTab("overview");setScreen("profile");window.scrollTo({top:0,behavior:"smooth"});};
  const openCompare=()=>{setScreen("compare");window.scrollTo({top:0,behavior:"smooth"});};
  const goRanking=()=>{setScreen("ranking");window.scrollTo({top:0,behavior:"smooth"});};

  const shareInsight=async()=>{
    const text=window.prompt("Deel een kort trading-inzicht met je Friends (max. 280 tekens):");
    if(!text?.trim()) return;
    try {
      await request("/api/friends/insights",{method:"POST",body:JSON.stringify({text:text.trim()})});
      const payload=await request("/api/friends/insights");
      setInsights(Array.isArray(payload.insights)?payload.insights:[]);
    } catch(reason) {
      setError(reason instanceof Error?reason.message:"Inzicht delen is niet gelukt.");
    }
  };

  if (!cloudReady || loading) return <div className={styles.loading}><span/><p>Friends wordt veilig geladen…</p></div>;
  if (error && !data) return <div className={styles.error}><Icon name="shield"/><h2>Friends tijdelijk niet beschikbaar</h2><p>{error}</p></div>;
  if (!data) return null;

  return <div className={styles.root}>
    {error ? <div className={styles.toast}>{error}<button type="button" onClick={()=>setError("")}>×</button></div> : null}
    {screen==="ranking" && <MainRanking data={data} period={period} onPeriod={setPeriod} onTrader={openTrader} onCompare={openCompare} insights={insights} onInsight={()=>void shareInsight()}/>}
    {screen==="profile" && selected && <Profile trader={selected} tab={profileTab} setTab={setProfileTab} period={period} onPeriod={setPeriod} onBack={goRanking} onCompare={openCompare}/>}
    {screen==="compare" && <Compare traders={data.traders} period={period} onPeriod={setPeriod} onBack={selected?()=>setScreen("profile"):goRanking}/>}
  </div>;
}
