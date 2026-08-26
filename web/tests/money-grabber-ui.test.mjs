import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";

const maker=readFileSync(new URL("../components/aster-strategy2-maker.tsx",import.meta.url),"utf8");
const proxy=readFileSync(new URL("../lib/secure-strategy2-live.ts",import.meta.url),"utf8");

test("Money Grabber is default off, separate from Portfolio Protection, and isolated to Multi-pair",()=>{
  assert.match(maker,/moneyGrabber:false/);
  assert.match(maker,/moneyGrabberEnabled:v\.tradingMode==="multi_pair"&&v\.moneyGrabber/);
  assert.match(maker,/protectionEnabled:v\.protection/);
  assert.match(maker,/v\.tradingMode==="multi_pair"&&mg\.enabled/);
});

test("wizard keeps separate LONG and SHORT DCA controls plus Money Grabber activation preview",()=>{
  assert.match(maker,/Max LONG DCA/);
  assert.match(maker,/Max SHORT DCA/);
  assert.match(maker,/Nieuwe Money Grabber-ronde starten/);
  assert.match(maker,/Start ronde/);
});

test("both authenticated Money Grabber routes use the Strategy 2 proxy",()=>{
  assert.match(proxy,/money-grabber\/activation-preview/);
  assert.match(proxy,/money-grabber\/start-round/);
  assert.match(proxy,/money-grabber\/shadow/);
});

test("Money Grabber browser endpoints exist with their exact safe HTTP methods",()=>{
  const root=new URL("../app/api/exchanges/aster/strategy2/money-grabber/",import.meta.url);
  const preview=readFileSync(new URL("activation-preview/route.ts",root),"utf8");
  const start=readFileSync(new URL("start-round/route.ts",root),"utf8");
  const shadow=readFileSync(new URL("shadow/route.ts",root),"utf8");
  assert.match(preview,/export async function GET/);
  assert.match(start,/export async function POST/);
  assert.match(shadow,/export async function GET/);
  assert.doesNotMatch(preview+shadow,/export async function POST/);
});
