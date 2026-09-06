import test from "node:test";
import assert from "node:assert/strict";
import fs from "node:fs";
const maker=fs.readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
test("Money Grabber and portfolio protection are retired from active strategy UI",()=>{
  assert.doesNotMatch(maker,/Money Grabber|Portfolio Protection/);
  assert.match(maker,/Botinstellingen/);
});
test("new strategy exposes independent LONG and SHORT DCA configuration",()=>{
  for(const label of ["DCA-afstand LONG","DCA-afstand SHORT","DCA-bedrag LONG","DCA-bedrag SHORT","Max DCA LONG","Max DCA SHORT"]) assert.match(maker,new RegExp(label));
});
