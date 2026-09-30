import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Build 477 detail pages replace the normal chart and snapshot instead of overlaying them", async () => {
  const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");

  assert.match(component, /type SnapshotDetailView = "portfolio" \| "price-zone" \| "scanner"/);
  assert.match(component, /detailView === "portfolio"/);
  assert.match(component, /detailView === "price-zone" \? <PriceZoneDetailsPage/);
  assert.match(component, /<ScannerStatusPage snapshot=\{scannerStatus\} onBack=\{closeDetail\}/);
  assert.match(component, /detailScrollY\.current = window\.scrollY/);
  assert.match(component, /window\.scrollTo\(\{ top: restoreY, behavior: "auto" \}\)/);

  const portal = component.slice(component.indexOf("return host ? createPortal("));
  const normalBranch = portal.slice(0, portal.indexOf(': detailView === "price-zone"'));
  assert.match(normalBranch, /<PortfolioKoersChart/);
  assert.match(normalBranch, /<Snapshot/);
  assert.doesNotMatch(portal.slice(portal.indexOf(': detailView === "price-zone"')), /<PortfolioKoersChart/);
});

test("Build 477 scanner status is read-only and exposes exact per-side runtime diagnostics", async () => {
  const [component, backend] = await Promise.all([
    readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8"),
    readFile(new URL("../../cloud_api/aster_multi_bb_core.py", import.meta.url), "utf8"),
  ]);

  const loader = component.match(/async function loadScannerStatus[\s\S]*?function readSnapshot/)?.[0] || "";
  assert.match(loader, /authenticatedRequest\("\/api\/exchanges\/aster", \{ cache: "no-store" \}\)/);
  assert.doesNotMatch(loader, /method:\s*"(POST|PUT|PATCH|DELETE)"/);

  for (const key of [
    "marketsScanned",
    "bbCandidates",
    "zoneAllowed",
    "blockedFilters",
    "ordersPlaced",
    "lastEntryAtMs",
    "availableCapacity",
  ]) {
    assert.match(component, new RegExp(key));
    assert.match(backend, new RegExp(key));
  }

  assert.match(backend, /"scannerDiagnostics": scanner_diagnostics/);
  assert.match(backend, /side_diag\["marketsScanned"\] \+= 1/);
  assert.match(backend, /side_diag\["bbCandidates"\] \+= 1/);
  assert.match(backend, /scanner_side_diagnostics\[side\]\["zoneAllowed"\] \+= 1/);
  assert.match(backend, /"mode": "live" if not dry_run else "simulation"/);
});

test("Build 477 scanner verdict only classifies fresh runtime facts", async () => {
  const component = await readFile(new URL("../components/aster-portfolio-snapshot-enhancer.tsx", import.meta.url), "utf8");
  const verdict = component.match(/function scannerVerdict[\s\S]*?function scannerConclusion/)?.[0] || "";

  for (const state of ["NORMAAL", "GEEN KANDIDATEN", "GEBLOKKEERD", "SCANNER STIL", "ORDERFOUT"]) {
    assert.match(component, new RegExp(state));
  }
  assert.match(verdict, /Date\.now\(\) - snapshot\.updatedAtMs > 120000/);
  assert.match(verdict, /snapshot\.entryStatus === "ORDER_REJECTED"/);
  assert.match(verdict, /freeCapacity > 0 && bbCandidates === 0/);
  assert.match(verdict, /bbCandidates > 0 && orders === 0 && blockers > 0/);
});
