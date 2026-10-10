"use client";

type Rec = Record<string, unknown>;
const object = (value: unknown): Rec => value && typeof value === "object" && !Array.isArray(value) ? value as Rec : {};
const numeric = (value: unknown, fallback = 0) => value === undefined || value === null || value === "" || !Number.isFinite(Number(value)) ? fallback : Number(value);
const capacity = (value: unknown, fallback: number) => Math.max(0, Math.round(numeric(value, fallback)));

/** Read-only presentation of the account-scoped Aster exchange/settings truth.
 * Never persists settings and never submits orders. */
export function AsterSlotOverview({ account }: { account: unknown }) {
  const root = object(account);
  const payload = Object.keys(object(root.data)).length ? object(root.data) : root;
  const strategy = object(payload.strategy2);
  const settings = object(strategy.settings);
  const report = Object.keys(object(strategy.multiBb)).length ? object(strategy.multiBb) : object(strategy.multiBbReport);
  const state = object(strategy.state);
  const zoneSettings = object(settings.priceZoneSeats);
  const zoneEnabled = Object.keys(zoneSettings).length ? zoneSettings.enabled === true : settings.zoneSoldiersEnabled === true;

  const configuredLong = capacity(settings.longSlots, 20);
  const configuredShort = capacity(settings.shortSlots, 10);
  const globalCap = Math.max(1, capacity(settings.maximumPositions, configuredLong + configuredShort));
  const zoneLongEnabled = numeric(zoneSettings.longSeatsPerZone, numeric(settings.zoneBaseLongSoldiers, 2)) > 0;
  const zoneShortEnabled = numeric(zoneSettings.shortSeatsPerZone, numeric(settings.zoneBaseShortSoldiers, 2)) > 0;
  const longCapacity = zoneEnabled ? (zoneLongEnabled ? globalCap : 0) : configuredLong;
  const shortCapacity = zoneEnabled ? (zoneShortEnabled ? globalCap : 0) : configuredShort;
  const totalCapacity = zoneEnabled ? globalCap : longCapacity + shortCapacity;

  const positions = Array.isArray(payload.positions) ? payload.positions.filter(row => row && typeof row === "object") as Rec[] : [];
  const hasExchangeTruth = Array.isArray(payload.positions) && (positions.length > 0 || numeric(payload.activePositions, -1) === 0);
  const long = hasExchangeTruth ? positions.filter(row => String(row.side ?? row.positionSide ?? "").toUpperCase() === "LONG").length : capacity(state.longLegs ?? report.activeLong, 0);
  const short = hasExchangeTruth ? positions.filter(row => String(row.side ?? row.positionSide ?? "").toUpperCase() === "SHORT").length : capacity(state.shortLegs ?? report.activeShort, 0);
  const total = long + short;
  const freeGlobal = Math.max(0, globalCap - total);
  const freeLong = settings.smartRescueEnabled === true ? Math.max(0, globalCap - long) : zoneEnabled ? (zoneLongEnabled ? freeGlobal : 0) : Math.max(0, configuredLong - long);
  const freeShort = settings.smartRescueEnabled === true ? 0 : zoneEnabled ? (zoneShortEnabled ? freeGlobal : 0) : Math.max(0, configuredShort - short);
  const fill = (used: number, max: number) => max > 0 ? Math.min(100, used / max * 100) : 0;
  const reportCurrent = numeric(report.configVersion, -1) === numeric(state.configVersion ?? settings.version ?? strategy.version, -2);
  const candidates = reportCurrent ? capacity(report.candidateCount, 0) : 0;

  return <section className="slot-overview" aria-label="Slot-overzicht">
    <header><span className="slot-icon">◇</span><div><b>Slot-overzicht</b><small>Bezetting van beschikbare botslots</small></div><span className="slot-cross">⇄ <b>CROSS</b></span><span className="slot-candidates">♙ <b>{candidates}</b> kandidaten</span></header>
    <div className="slot-row long"><strong>LONG</strong><i><u style={{width:`${fill(long,longCapacity)}%`}} /></i><b>{long} / {longCapacity}</b><em>{freeLong} vrij</em></div>
    <div className="slot-row short"><strong>SHORT</strong><i><u style={{width:`${fill(short,shortCapacity)}%`}} /></i><b>{short} / {shortCapacity}</b><em>{freeShort} vrij</em></div>
    <div className="slot-row total"><strong>Totaal</strong><i><u style={{width:`${fill(total,totalCapacity)}%`}} /></i><b>{total} / {totalCapacity}</b><em>{Math.max(0,totalCapacity-total)} vrij</em></div>
  </section>;
}
