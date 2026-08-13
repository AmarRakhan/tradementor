import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const engine = await readFile(new URL("../lib/backtest-engine.ts", import.meta.url), "utf8");
const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
const component = await readFile(new URL("../components/backtest-comparison.tsx", import.meta.url), "utf8");

test("Positions exposes Live and two visibly separated backtests", () => {
  assert.match(page, /Live trading/);
  assert.match(page, /Backtest A\/B/);
  assert.match(component, /BACKTEST \{variant\} · FICTIEF/);
  assert.match(component, /Start beide backtests/);
});

test("backtests use independent state and one identical candle request", () => {
  assert.match(component, /Record<Variant,BacktestSettings>/);
  assert.match(component, /const A=runBacktest\(candles,settings\.A\),B=runBacktest\(candles,settings\.B\)/);
  assert.match(component, /interval=15m&limit=1000/);
});

test("simulator implements linear long and short PnL without double leverage", () => {
  assert.match(engine, /side === "LONG" \? exit - entry : entry - exit/);
  assert.doesNotMatch(engine, /pnl[^\n]*\*[^\n]*leverage/i);
});

test("weighted entry is quantity weighted and accounting is checked", () => {
  assert.match(engine, /fill\.price \* fill\.quantity/);
  assert.match(engine, /Math\.abs\(trades\.reduce/);
  assert.match(engine, /Conservatieve candlevolgorde: DCA vóór TP/);
});

test("simulation component has no live execution endpoint", () => {
  assert.doesNotMatch(component, /execution\/live|strategy2\/start|automation\/start/);
  assert.match(component, /echte orderuitvoering is technisch niet beschikbaar/);
});
