export type RealizedTrade = {
  symbol?: unknown;
  side?: unknown;
  realizedPnlUsd?: unknown;
  closedAt?: unknown;
};

export type RealizedDay = {
  date: string;
  total: number;
  trades: number;
  wins: number;
  losses: number;
};

const amount = (value: unknown) => {
  const parsed = Number(value);
  return Number.isFinite(parsed) ? parsed : 0;
};

export function localDayKey(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}

export function realizedCalendar(trades: RealizedTrade[], now = new Date()): { today: RealizedDay; days: RealizedDay[] } {
  const grouped = new Map<string, RealizedDay>();
  for (const trade of trades) {
    const closed = new Date(String(trade.closedAt ?? ""));
    if (Number.isNaN(closed.getTime())) continue;
    const date = localDayKey(closed);
    const pnl = amount(trade.realizedPnlUsd);
    const day = grouped.get(date) ?? { date, total: 0, trades: 0, wins: 0, losses: 0 };
    day.total += pnl;
    day.trades += 1;
    if (pnl > 0) day.wins += 1;
    if (pnl < 0) day.losses += 1;
    grouped.set(date, day);
  }
  const todayKey = localDayKey(now);
  const today = grouped.get(todayKey) ?? { date: todayKey, total: 0, trades: 0, wins: 0, losses: 0 };
  const days = [...grouped.values()].sort((left, right) => left.date.localeCompare(right.date));
  return { today, days };
}
