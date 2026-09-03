import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const component = readFileSync(new URL("../components/pull-to-refresh.tsx", import.meta.url), "utf8");
const styles = readFileSync(new URL("../components/pull-to-refresh.module.css", import.meta.url), "utf8");
const page = readFileSync(new URL("../app/page.tsx", import.meta.url), "utf8");

test("mobile pull-to-refresh visibly refreshes server snapshots", () => {
  assert.match(component, /TRIGGER_DISTANCE = 72/);
  assert.match(component, /window\.addEventListener\("touchmove", touchMove, \{ passive: false \}\)/);
  assert.match(component, /event\.preventDefault\(\)/);
  assert.match(component, /await onRefresh\(\)/);
  assert.match(component, /Gegevens worden vernieuwd/);
  assert.match(styles, /\.refreshing span\{animation:spin/);
  assert.match(styles, /@media\(min-width:701px\)/);
  assert.match(page, /<PullToRefresh onRefresh=\{refreshAll\} \/>/);
});
