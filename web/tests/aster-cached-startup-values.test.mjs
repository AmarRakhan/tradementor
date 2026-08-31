import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

test("Aster reload keeps last UID-scoped values visible while fresh server data loads", async () => {
  const display = await readFile(new URL("../lib/aster-account-display.ts", import.meta.url), "utf8");
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(display, /const reliable = Boolean\(data\) && configured && serverConfirmed/);
  assert.match(display, /const displayable = Boolean\(data\) && configured/);
  assert.match(display, /const equityNumber = displayable \? number\(data\?\.equity\) : null/);
  assert.match(display, /const availableNumber = displayable \? number\(data\?\.availableBalance\) : null/);
  assert.match(page, /Laatste bekende waarde · actuele data wordt opgehaald/);
});
