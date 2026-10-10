import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
const snapshot = readFileSync(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
const history = readFileSync(new URL("../components/closed-trades-history-modal.tsx", import.meta.url), "utf8");
const proxy = readFileSync(new URL("../app/api/exchanges/aster/closed-trades/history/route.ts", import.meta.url), "utf8");
test("both snapshot tiles share a single history component", () => {
 assert.match(snapshot, /onClick=\{\(\) => onOpenHistory\("all"\)\}/);
 assert.match(snapshot, /onClick=\{\(\) => onOpenHistory\("today"\)\}/);
 assert.match(snapshot, /<ClosedTradesHistoryModal/);
});
test("history uses the authenticated existing proxy with server-side scope", () => {
 assert.match(history, /authenticatedRequest\(/);
 assert.match(history, /scope: mode/);
 assert.match(proxy, /proxyCloud\(/);
 assert.match(proxy, /incoming\.has\("scope"\)/);
});
test("missing recorded margin and duration remain unavailable", () => {
 assert.match(history, /verifiedClosedTradeMargin\(row\)/);
 assert.match(history, /closedTradeDurationMs\(row\)/);
 assert.match(history, /Niet beschikbaar/);
});
