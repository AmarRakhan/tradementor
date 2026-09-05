import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const read=(p)=>readFile(new URL(`../${p}`,import.meta.url),"utf8");

test("Journey remains read-only and follows existing portfolio-growth APIs",async()=>{
 const page=await read("app/page.tsx"),view=await read("components/journey-view.tsx");
 assert.match(page,/id: "aster"[\s\S]{0,100}id: "journey"/);
 assert.match(page,/active === "journey" \? <JourneyView snapshots=\{snapshots\} \/>/);
 assert.match(view,/portfolio-growth\/daily/);assert.match(view,/portfolio-growth'/);
 assert.doesNotMatch(view,/method:\s*["']POST/);assert.doesNotMatch(view,/strategy2\/start|automation\/close-all|positions\/.*close/);
});

test("Journey uses compound level and forecast arithmetic with dynamic goal fallback",async()=>{
 const view=await read("components/journey-view.tsx");
 assert.match(view,/Math\.log\(goal\/equity\)\/Math\.log\(1\+rate\)/);
 assert.match(view,/Math\.log\(equity\/baseline\)\/Math\.log\(1\+rate\)/);
 assert.match(view,/targetPortfolio\?\?growth\?\.target\?\?growth\?\.goal\?\?FALLBACK_GOAL/);
 assert.match(view,/levelProgress/);assert.match(view,/toNextPct/);assert.match(view,/averageDailyPercentage/);
});

test("Journey calendar is historical, selectable and navigates both directions",async()=>{
 const view=await read("components/journey-view.tsx");
 assert.match(view,/d\.date<=todayIso/);assert.match(view,/key=\{d\.date\}/);
 assert.match(view,/aria-label="Vorige vier dagen"/);assert.match(view,/shift\(-1\)/);
 assert.match(view,/aria-label="Volgende vier dagen"/);assert.match(view,/shift\(1\)/);
 assert.match(view,/setSelected\(d\.date\)/);assert.match(view,/aria-pressed/);
 assert.doesNotMatch(view,/for\(let i=0;i<18/);
});

test("Journey mobile carousel exposes exactly four cards per viewport with snap and touch scrolling",async()=>{
 const [view,css]=await Promise.all([read("components/journey-view.tsx"),read("components/journey-view.css")]);
 assert.match(view,/className="j26Strip"/);assert.match(view,/className={`j26Day/);
 assert.match(css,/grid-auto-columns:calc\(\(100% - 15px\)\/4\)/);
 assert.match(css,/scroll-snap-type:x mandatory/);assert.match(css,/scroll-snap-align:start/);
 assert.match(css,/touch-action:pan-x pan-y/);assert.match(css,/@media\(max-width:380px\)/);
});

test("Journey presents the approved hero hierarchy and compact detail/achievement blocks",async()=>{
 const view=await read("components/journey-view.tsx");
 for(const token of ["Jouw reis naar","1 level = gemiddelde daggroei","Volgend level","RESTEREND TOT DOEL","PROGNOSE","JOURNEY KALENDER","JOUW DAGELIJKSE VOORTGANG","DETAILS —","Beste dag","Laatste grote winst","Vandaag verdiend"]) assert.match(view,new RegExp(token.replace(/[.*+?^${}()|[\]\\]/g,"\\$&")));
 assert.match(view,/j26Orb/);assert.match(view,/j26Achievements/);assert.match(view,/j26Detail/);
});
