import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const trades = await readFile(new URL("../components/aster-recent-trades.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../components/aster-trade-center.module.css", import.meta.url), "utf8");

test("trusted confirmed Aster values remain visible after a transient refresh failure", () => {
  assert.match(page, /hasTrustedSnapshot = Boolean\(snapshot\.data\) && \(snapshot\.serverConfirmed \|\| !snapshot\.error\)/);
  assert.match(page, /snapshot\.error && hasTrustedSnapshot \? "Laatste bevestigde gegevens"/);
  assert.match(page, /accountDataAvailable = connected/);
});

test("Tradecentrum does not claim Offline while confirmed trade data is still present", () => {
  assert.match(trades, /hasTrustedTradeSnapshot = Boolean\(snapshot\.data\) && snapshot\.serverConfirmed/);
  assert.match(trades, /snapshot\.error && !hasTrustedTradeSnapshot \? "Offline"/);
  assert.match(trades, /snapshot\.error \? "Delayed"/);
});

test("mobile Tradecentrum filters keep edge padding while horizontally scrolling", () => {
  assert.match(css, /scroll-padding-inline:12px/);
  assert.match(css, /\.filters:before,\.filters:after/);
});
