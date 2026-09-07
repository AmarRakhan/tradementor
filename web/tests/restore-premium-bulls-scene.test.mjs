import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";

const css = readFileSync(new URL("../components/portfolio-impact-battle.module.css", import.meta.url), "utf8");

test("Portfolio Impact keeps premium animated frame scene visible", () => {
  const card = css.match(/\.card\{[^}]+\}/)?.[0] || "";
  const scene = css.match(/\.scene\{[^}]+\}/)?.[0] || "";
  assert.doesNotMatch(card, /portfolio-impact-bulls\.webp/);
  assert.doesNotMatch(scene, /display\s*:\s*none/);
});
