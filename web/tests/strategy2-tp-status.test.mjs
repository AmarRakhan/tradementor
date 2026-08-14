import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");

test("Positions renders only the server Strategy-2 and Strategy-3 TP contracts", () => {
  assert.match(page, /strategy2Tp:\s*parseStrategy2Tp\(row\.strategy2Tp\)/);
  assert.match(page, /strategy3Tp:\s*parseStrategy3Tp\(row\.strategy3Tp\)/);
  assert.match(page, /Netto \{net\} · doel/);
  assert.match(page, /paidFeesUsd/);
  assert.match(page, /fundingUsd/);
  assert.match(page, /estimatedCloseFeeUsd/);
  assert.match(page, /Laatste serverbeoordeling/);
  assert.match(page, /value\.scheduler\.warning/);
  assert.match(page, /Fase \{value\.phase/);
  assert.match(page, /protection \{value\.protection\.active/);
  assert.match(page, /trailing \{value\.trailing\.active/);
  assert.doesNotMatch(page, /Geen netto TP-status/);
});

test("missing or unrecognized server evidence cannot become a TP result", () => {
  assert.match(page, /function parseStrategyTp/);
  assert.match(page, /function parseStrategy2Tp/);
  assert.match(page, /function parseStrategy3Tp/);
  assert.match(page, /Niet betrouwbaar te bepalen/);
  assert.match(page, /return null/);
  assert.match(page, /De server heeft geen volledig, bewezen netto TP-contract geleverd/);
  assert.match(page, /isManagedStrategyPosition\(position\).*StrategyTpPanel/s);
  assert.doesNotMatch(page, /position\.pnl\s*>?=?.*takeProfit/);
  assert.doesNotMatch(page, /resultPercent\s*>?=?.*TP bereikt/);
});

test("unreliable evidence never renders invented zero-valued amounts", () => {
  assert.match(page, /takeProfitTargetUsd:optionalFinancialNumber/);
  assert.match(page, /takeProfitPercent:optionalFinancialNumber/);
  assert.match(page, /estimatedCloseFeeUsd:optionalFinancialNumber/);
  assert.match(page, /value\.takeProfitTargetUsd === null.*"—"/s);
  assert.match(page, /value\.estimatedCloseFeeUsd === null \? "—"/);
});
