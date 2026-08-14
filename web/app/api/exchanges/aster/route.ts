import { proxyCloud } from "@/lib/cloud-proxy";
import { proxyStrategy3Live } from "@/lib/secure-strategy3-live";

type JsonRecord = Record<string, unknown>;

function rows(value: unknown): JsonRecord[] {
  return Array.isArray(value) ? value.filter((row): row is JsonRecord => Boolean(row) && typeof row === "object") : [];
}

function positionKey(row: JsonRecord) {
  return `${String(row.symbol ?? "").toUpperCase()}|${String(row.side ?? row.positionSide ?? "").toUpperCase()}`;
}

/** Merge server-owned contracts without deriving TP from browser-visible PnL. */
export function mergeAsterProjectStatus(production: JsonRecord, isolated: JsonRecord): JsonRecord {
  const productionRows = rows(production.positions);
  const isolatedRows = rows(isolated.positions);
  const isolatedByKey = new Map(isolatedRows.map((row) => [positionKey(row), row]));
  const seen = new Set<string>();
  const positions = productionRows.map((productionRow) => {
    const key = positionKey(productionRow);
    seen.add(key);
    const isolatedRow = isolatedByKey.get(key);
    const strategyId = String(isolatedRow?.strategyId ?? productionRow.strategyId ?? "");
    if (!isolatedRow || strategyId !== "aster-strategy-3") return productionRow;
    return {
      ...productionRow,
      ...isolatedRow,
      strategy2Tp: productionRow.strategy2Tp,
      strategy3Tp: isolatedRow.strategy3Tp,
    };
  });
  for (const isolatedRow of isolatedRows) {
    const key = positionKey(isolatedRow);
    if (!seen.has(key) && isolatedRow.strategyId === "aster-strategy-3") positions.push(isolatedRow);
  }
  return {
    ...production,
    positions,
    strategy2: production.strategy2,
    strategy3: isolated.strategy3,
  };
}

export async function GET(request: Request) {
  const [productionResponse, isolatedResponse] = await Promise.all([
    proxyCloud(request, "/v1/me/aster/status", "GET"),
    proxyStrategy3Live(request, "/v1/me/aster/status", "GET"),
  ]);
  if (!productionResponse.ok) return isolatedResponse;
  if (!isolatedResponse.ok) return productionResponse;
  const [production, isolated] = await Promise.all([
    productionResponse.json() as Promise<JsonRecord>,
    isolatedResponse.json() as Promise<JsonRecord>,
  ]);
  return Response.json(mergeAsterProjectStatus(production, isolated), {
    headers: { "cache-control": "no-store" },
  });
}
