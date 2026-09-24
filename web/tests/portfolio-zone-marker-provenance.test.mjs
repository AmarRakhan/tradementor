import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

test("Build 415 Portfolio Koers tooltip can identify zone-base and exposure-balancer entries",async()=>{
  const component=await readFile(new URL("../components/portfolio-koers-chart.tsx",import.meta.url),"utf8");
  assert.ok(component.includes("originZones?:number[]"));
  assert.ok(component.includes("soldierRoles?:string[]"));
  assert.ok(component.includes('"exposure-balancer"'));
  assert.ok(component.includes('"basis-soldaat"'));
});
