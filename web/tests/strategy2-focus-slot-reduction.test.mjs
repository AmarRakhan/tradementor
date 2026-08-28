import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const maker = await readFile(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8");

test("Multi-Focus count can drain live slots without turning the bot off", () => {
  assert.match(maker, /focusDesiredSlotCount/);
  assert.match(maker, /focusSlotDraining/);
  assert.match(maker, /Afbouwen naar/);
  assert.match(maker, /blijven volledig beheerd/);
  assert.match(maker, /niet opnieuw geopend/);
  assert.doesNotMatch(maker, /focusSlotReductionBlocked/);
  assert.doesNotMatch(maker, /Verlaag eerst het live aantal/);
});
