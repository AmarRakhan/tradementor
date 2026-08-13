export type PortfolioEquityRow = {
  at: number;
  total: number;
  hyperliquid?: number | null;
  aster?: number | null;
};

const MAX_UNCONFIRMED_CHANGE_FACTOR = 20;

function positive(value: unknown) {
  const number = Number(value);
  return Number.isFinite(number) && number > 0 ? number : null;
}

export function sanitizePortfolioEquityRows(input: unknown[]): PortfolioEquityRow[] {
  const accepted: PortfolioEquityRow[] = [];
  const expected = new Set<"hyperliquid" | "aster">();

  for (const raw of [...input].sort((a, b) => Number((a as PortfolioEquityRow)?.at) - Number((b as PortfolioEquityRow)?.at))) {
    if (!raw || typeof raw !== "object") continue;
    const source = raw as Record<string, unknown>;
    const at = Number(source.at);
    const total = positive(source.total);
    if (!Number.isFinite(at) || at <= 0 || total === null) continue;

    const hasComponents = Object.prototype.hasOwnProperty.call(source, "hyperliquid") || Object.prototype.hasOwnProperty.call(source, "aster");
    const hyperliquid = positive(source.hyperliquid);
    const aster = positive(source.aster);
    if (hasComponents && ([...expected].some((exchange) => exchange === "hyperliquid" ? hyperliquid === null : aster === null))) continue;

    const previous = accepted.at(-1);
    if (previous) {
      const factor = total / previous.total;
      if (factor < 1 / MAX_UNCONFIRMED_CHANGE_FACTOR || factor > MAX_UNCONFIRMED_CHANGE_FACTOR) continue;
    }

    const row: PortfolioEquityRow = { at, total, hyperliquid, aster };
    accepted.push(row);
    if (hyperliquid !== null) expected.add("hyperliquid");
    if (aster !== null) expected.add("aster");
  }
  return accepted;
}

export function isCompletePortfolioSnapshot(previous: PortfolioEquityRow | undefined, next: PortfolioEquityRow) {
  if (!previous) return true;
  if (positive(previous.hyperliquid) !== null && positive(next.hyperliquid) === null) return false;
  if (positive(previous.aster) !== null && positive(next.aster) === null) return false;
  const factor = next.total / previous.total;
  return factor >= 1 / MAX_UNCONFIRMED_CHANGE_FACTOR && factor <= MAX_UNCONFIRMED_CHANGE_FACTOR;
}
