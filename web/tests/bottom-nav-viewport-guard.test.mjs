import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("bottom navigation stays anchored on iOS after the keyboard closes", async () => {
  const [layout, guard, css] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/bottom-nav-viewport-guard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/bottom-nav-viewport.css", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /import \{ BottomNavViewportGuard \} from "@\/components\/bottom-nav-viewport-guard"/);
  assert.match(layout, /<BottomNavViewportGuard \/>/);
  assert.match(layout, /import "\.\/bottom-nav-viewport\.css"/);
  assert.ok(layout.indexOf('"./bottom-nav-viewport.css"') > layout.indexOf('"./globals.css"'), "loaded after globals.css");

  // Touch devices only, display only.
  assert.match(guard, /\(pointer: coarse\)/);
  assert.doesNotMatch(guard, /fetch\(|firestore|setDoc|updateDoc/i);
  // Hide while typing, re-anchor after close / foreground.
  assert.match(guard, /data-soft-keyboard/);
  assert.match(guard, /focusin/);
  assert.match(guard, /focusout/);
  assert.match(guard, /window\.scrollTo\(window\.scrollX, window\.scrollY\)/);
  assert.match(guard, /visibilitychange/);
  assert.match(guard, /pageshow/);
  // No re-anchor on ordinary toolbar resizes while scrolling.
  assert.match(guard, /awaitingRestore && height >= fullHeight - 80/);
  // Checkboxes and toggles never hide the navigation.
  assert.match(guard, /"checkbox", "radio"/);

  assert.match(css, /html\[data-soft-keyboard="open"\] \.bottom-nav/);
  assert.match(css, /pointer-events: none/);
  assert.match(css, /\.bottom-nav, \.premium-bottom-nav \{\s*transform: translate3d\(0, 0, 0\)/);
});
