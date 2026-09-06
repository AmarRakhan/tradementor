import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";

const maker = fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Multi BB entry sizing keeps margin semantics with independent LONG and SHORT values", () => {
  assert.match(maker, /Instap LONG/);
  assert.match(maker, /Instap SHORT/);
  assert.match(maker, /entrySizingMode: "margin"/);
  assert.match(maker, /DCA-bedrag LONG/);
  assert.match(maker, /DCA-bedrag SHORT/);
  assert.doesNotMatch(maker, /focusExposurePreview/);
});
