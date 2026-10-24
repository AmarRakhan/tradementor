import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import { drawdownCaption, formatDrawdown, normalizeDrawdown } from "../lib/entry-drawdown.mjs";

// Build 652 (Amar 24-10): links LONG, rechts SHORT max drawdown, gemiddeld vanaf instap; ook op het Auto Hedge-scherm.

test("getal: één decimaal, Nederlandse komma, echt minteken; onbekend is een streepje", () => {
  assert.equal(formatDrawdown(4.8), "−4,8%");
  assert.equal(formatDrawdown(31.234), "−31,2%");
  assert.equal(formatDrawdown(0), "0,0%");
  assert.equal(formatDrawdown(null), "—");
  assert.equal(formatDrawdown(Number.NaN), "—");
});

test("ondertekst zegt wat het getal is, of dat het nog berekend wordt", () => {
  assert.equal(drawdownCaption({ avgMaxDrawdownPct: 4.8, count: 70 }, false), "Gemiddeld vanaf instap");
  assert.equal(drawdownCaption({ avgMaxDrawdownPct: null, count: 0 }, true), "Wordt berekend…");
  assert.equal(drawdownCaption(null, false), "Nog geen posities");
});

test("serverantwoord wordt veilig ingelezen", () => {
  const data = normalizeDrawdown({ long: { avgMaxDrawdownPct: 4.8, count: 70 }, short: { avgMaxDrawdownPct: "x" }, refreshing: true });
  assert.deepEqual(data.long, { avgMaxDrawdownPct: 4.8, count: 70 });
  assert.deepEqual(data.short, { avgMaxDrawdownPct: null, count: 0 });
  assert.equal(data.refreshing, true);
  assert.equal(normalizeDrawdown(null).long.avgMaxDrawdownPct, null);
});

test("tegels en Auto Hedge-scherm gebruiken dezelfde lezing en dezelfde woorden", async () => {
  const [tiles, card, route] = await Promise.all([
    readFile(new URL("../components/entry-drawdown.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/short-recovery-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/entry-drawdown/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(tiles, /\{side\} MAX DRAWDOWN/);
  assert.match(tiles, /gem\. max drawdown/);
  assert.match(card, /<DrawdownReference data=\{drawdown\} side=\{protectedSide\}/);
  assert.match(card, /const protectedSide = up \? "SHORT" : "LONG";/);
  assert.ok(card.indexOf("<DrawdownReference") < card.indexOf('className="plah-unwind-fields"'), "boven de afbouwstappen");
  assert.match(route, /\/v1\/me\/aster\/entry-drawdown/);
  assert.doesNotMatch(tiles + card, /mediaan|P75|percentiel/i);
});
