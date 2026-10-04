"use client";

export type ActiveZoneSeatSummary = {
  runtimeTruthCanonical: boolean;
  activeZone: number | null;
  perZoneLong: number;
  perZoneShort: number;
  occupiedLongActiveZone: number;
  occupiedShortActiveZone: number;
  zoneOpenCounts: Record<string, { long: number; short: number; total: number }>;
  zoneOpenCountsReliable: boolean;
};

export type ActiveZoneSeatState = {
  displayActiveZone: number | null;
  seatZoneInSync: boolean;
  occupiedLongActiveZone: number;
  occupiedShortActiveZone: number;
  activeLongLabel: string;
  activeShortLabel: string;
  longPercent: number;
  shortPercent: number;
};

const pct = (value: number, capacity: number) =>
  capacity <= 0 ? 0 : Math.min(100, Math.max(0, value / capacity * 100));

export function resolveActiveZoneSeatState(
  summary: ActiveZoneSeatSummary | null,
  liveActiveZone: number | null,
): ActiveZoneSeatState {
  if (!summary) {
    return {
      displayActiveZone: liveActiveZone,
      seatZoneInSync: false,
      occupiedLongActiveZone: 0,
      occupiedShortActiveZone: 0,
      activeLongLabel: "— / —",
      activeShortLabel: "— / —",
      longPercent: 0,
      shortPercent: 0,
    };
  }

  const displayActiveZone = summary.runtimeTruthCanonical
    ? summary.activeZone
    : (liveActiveZone ?? summary.activeZone);
  const backendZoneMatches =
    displayActiveZone !== null && summary.activeZone === displayActiveZone;
  const breakdown =
    displayActiveZone === null
      ? null
      : summary.zoneOpenCounts[String(displayActiveZone)] || null;
  const resolvedCounts = backendZoneMatches
    ? {
        long: summary.occupiedLongActiveZone,
        short: summary.occupiedShortActiveZone,
      }
    : displayActiveZone !== null && summary.zoneOpenCountsReliable
      ? { long: breakdown?.long ?? 0, short: breakdown?.short ?? 0 }
      : null;

  const seatZoneInSync = resolvedCounts !== null;
  const occupiedLongActiveZone = resolvedCounts?.long ?? 0;
  const occupiedShortActiveZone = resolvedCounts?.short ?? 0;

  return {
    displayActiveZone,
    seatZoneInSync,
    occupiedLongActiveZone,
    occupiedShortActiveZone,
    activeLongLabel: seatZoneInSync
      ? `${occupiedLongActiveZone} / ${summary.perZoneLong}`
      : "— / —",
    activeShortLabel: seatZoneInSync
      ? `${occupiedShortActiveZone} / ${summary.perZoneShort}`
      : "— / —",
    longPercent: seatZoneInSync
      ? pct(occupiedLongActiveZone, summary.perZoneLong)
      : 0,
    shortPercent: seatZoneInSync
      ? pct(occupiedShortActiveZone, summary.perZoneShort)
      : 0,
  };
}

export function ActiveZoneSeatBlock({
  summary,
  liveActiveZone,
  className = "",
}: {
  summary: ActiveZoneSeatSummary | null;
  liveActiveZone: number | null;
  className?: string;
}) {
  const state = resolveActiveZoneSeatState(summary, liveActiveZone);
  return (
    <div className={`aps-zone-seat-group aps-active-zone-seat-block ${className}`.trim()}>
      <strong className="aps-zone-group-title">Actieve zone</strong>
      <div className="aps-zone-meters">
        <div className="long">
          <span>LONG</span>
          <i><u style={{ width: `${state.longPercent}%` }} /></i>
          <b>{state.activeLongLabel}</b>
        </div>
        <div className="short">
          <span>SHORT</span>
          <i><u style={{ width: `${state.shortPercent}%` }} /></i>
          <b>{state.activeShortLabel}</b>
        </div>
      </div>
    </div>
  );
}
