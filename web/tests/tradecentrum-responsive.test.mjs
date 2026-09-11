import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const layout = await readFile(new URL("../app/layout.tsx", import.meta.url), "utf8");
const css = await readFile(new URL("../app/tradecentrum-responsive.css", import.meta.url), "utf8");

test("Tradecentrum loads its cross-device reference lock after the existing global styles", () => {
  const base = layout.indexOf('import "./aster-tables.css"');
  const responsive = layout.indexOf('import "./tradecentrum-responsive.css"');
  assert.ok(base >= 0);
  assert.ok(responsive > base);
});

test("iPhone and Fold use one identical six-column ratio instead of breakpoint pixel columns", () => {
  assert.match(css, /--tc-columns:minmax\(0,30fr\) minmax\(0,15fr\) minmax\(0,17fr\) minmax\(0,14fr\) minmax\(0,9fr\) minmax\(0,15fr\)/);
  assert.match(css, /grid-template-columns:var\(--tc-columns\)!important/);
  assert.match(css, /@media\(max-width:380px\)[\s\S]*grid-template-columns:var\(--tc-columns\)!important/);
  assert.doesNotMatch(css, /grid-template-columns:[^;]*(?:84px|77px|46px|44px|52px|45px|24px)/);
});

test("all six columns remain visible and centered on narrow devices", () => {
  assert.match(css, /\[role="table"\]>\[role="row"\]:first-child>span:not\(:first-child\)[\s\S]*text-align:center!important/);
  assert.match(css, /\[role="row"\]:not\(:first-child\)>:nth-child\(n\+2\)[\s\S]*justify-self:center!important/);
  assert.match(css, /button\[role="cell"\]>span:first-child[\s\S]*display:grid!important/);
});

test("reference subtitle is not hidden by the legacy phone breakpoint", () => {
  assert.match(css, />header p\{[\s\S]*display:block!important/);
  assert.match(css, /@media\(max-width:700px\)[\s\S]*>header p\{[\s\S]*display:block!important/);
});

test("approved close controls keep three equal scopes and a bright actionable profit CTA", () => {
  assert.match(css, /div\[aria-label="Winstposities sluiten per richting"\][\s\S]*grid-template-columns:repeat\(3,minmax\(0,1fr\)\)!important/);
  assert.match(css, /button:nth-child\(1\)::before\{content:"↑"\}/);
  assert.match(css, /button:nth-child\(2\)::before\{content:"↓"\}/);
  assert.match(css, /button:nth-child\(3\)::before\{content:"×"\}/);
  assert.match(css, />footer>button:not\(:disabled\)[\s\S]*background:linear-gradient\(135deg,#19d7a6,#32e9b8\)!important/);
});
