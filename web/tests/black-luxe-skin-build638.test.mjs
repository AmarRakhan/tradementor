import test from "node:test";
import assert from "node:assert/strict";
import { readFile, readdir } from "node:fs/promises";
import { execFileSync } from "node:child_process";
import { fileURLToPath } from "node:url";

const web = (p) => new URL(`../${p}`, import.meta.url);
const repoRoot = fileURLToPath(new URL("../../", import.meta.url));

test("Black Luxe is a selectable skin and the default when nothing was chosen", async () => {
  const page = await readFile(web("app/page.tsx"), "utf8");
  assert.match(page, /type AppSkin = "original" \| "suriname-heritage" \| "ultra-rivalry" \| "black-luxe"/);
  assert.match(page, /const DEFAULT_APP_SKIN: AppSkin = "black-luxe"/);
  assert.match(page, /useState<AppSkin>\(DEFAULT_APP_SKIN\)/);
  // a saved choice is always respected
  assert.match(page, /savedSkin === "original" \|\| savedSkin === "suriname-heritage" \|\| savedSkin === "ultra-rivalry" \|\| savedSkin === "black-luxe" \? savedSkin : DEFAULT_APP_SKIN/);
  assert.match(page, /onChange\("black-luxe"\)/);
  assert.match(page, /<strong>Black Luxe<\/strong>/);
  const layout = await readFile(web("app/layout.tsx"), "utf8");
  const imports = [...layout.matchAll(/import "\.\/([\w.-]+\.css)";/g)].map((m) => m[1]);
  assert.equal(imports.at(-1), "black-luxe.css", "Black Luxe must be the last stylesheet");
});

test("Black Luxe only changes colours (no layout, no network, no bull/bear media)", async () => {
  const css = await readFile(web("app/black-luxe.css"), "utf8");
  // Every section mirrored from a base stylesheet may only carry colour declarations.
  // (The Suriname Heritage mirror keeps Heritage's own finishing, which is what the app looks like today.)
  const generated = css.split("/* hand-written finishing touches */")[0];
  const sections = generated.split(/\/\* from /).slice(1).filter((s) => !s.startsWith("suriname-heritage.css"));
  const colourish = /^(--.*|background.*|border.*|box-shadow|outline.*|color|fill|stroke|text-shadow|caret-color|accent-color|column-rule.*|text-decoration.*)$/;
  for (const section of sections) {
    const body = section.slice(section.indexOf("*/") + 2);
    for (const m of body.matchAll(/[{;]([-a-zA-Z]+):/g)) assert.match(m[1].toLowerCase(), colourish, `non-colour property ${m[1]} in ${section.slice(0, 40)}`);
  }
  assert.doesNotMatch(css, /fetch\(|WebSocket|\/api\//);
  assert.doesNotMatch(css, /bull-bear|portfolio-impact-battle/);
  for (const name of await readdir(web("components"))) {
    if (!name.startsWith("portfolio-impact") || !name.endsWith(".module.css")) continue;
    assert.doesNotMatch(await readFile(web(`components/${name}`), "utf8"), /BLACK-LUXE/, `${name} must stay untouched`);
  }
});

test("black-luxe.css is exactly what the generator produces from the current CSS", async () => {
  const before = await readFile(web("app/black-luxe.css"), "utf8");
  execFileSync("python3", ["tools/generate_black_luxe_skin.py"], { cwd: repoRoot, stdio: "ignore" });
  const after = await readFile(web("app/black-luxe.css"), "utf8");
  assert.equal(after, before, "run python3 tools/generate_black_luxe_skin.py and commit the result");
});
