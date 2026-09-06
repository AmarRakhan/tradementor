import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (path) => readFile(new URL(path, import.meta.url), "utf8");

test("Aavansh variant is branded and pinned to V46 build 263 lineage", async () => {
  const [layout, manifest, version] = await Promise.all([
    read("../app/layout.tsx"),
    read("../public/manifest.webmanifest"),
    read("../lib/app-version.ts"),
  ]);
  assert.match(version, /WEBAPP_VERSION = "46"/);
  assert.match(layout, /Aavansh Trading – A New Beginning/);
  assert.match(layout, /aavansh-base-build": "263"/);
  assert.match(layout, /data-app-variant="aavansh"/);
  assert.match(layout, /A NEW BEGINNING · GEÏSOLEERDE VARIANT · BASIS V46 BUILD 263/);
  const parsed = JSON.parse(manifest);
  assert.equal(parsed.name, "Aavansh Trading – A New Beginning");
  assert.equal(parsed.short_name, "Aavansh Trading");
});

test("Aavansh branding is presentation-only and preserves technical TradeMentor keys", async () => {
  const enhancer = await read("../components/aavansh-branding.tsx");
  assert.match(enhancer, /replaceBrandText/);
  assert.match(enhancer, /tradementor-logo\.png/);
  assert.match(enhancer, /aavansh-logo\.png/);
  assert.doesNotMatch(enhancer, /localStorage\.setItem/);
  assert.doesNotMatch(enhancer, /authenticatedRequest/);
});

test("portfolio snapshot removes the large growth and index presentation while retaining controls and status facts", async () => {
  const css = await read("../app/aavansh-variant.css");
  assert.match(css, /grid-template-columns:repeat\(3,minmax\(0,1fr\)\)/);
  assert.match(css, /\.active-trades-index>\.ati-head/);
  assert.match(css, /\.active-trades-index>strong/);
  assert.match(css, /display:none!important/);
  assert.match(css, /\.active-trades-index>small/);
  assert.match(css, /\.portfolio-growth>\.portfolio-growth-daily/);
  assert.match(css, /\.portfolio-close-all/);
  assert.match(css, /\.portfolio-baseline-reset/);
  assert.match(css, /grid-column:1\/-1/);
});
