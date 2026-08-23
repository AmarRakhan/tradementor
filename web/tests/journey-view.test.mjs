import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
const read=(p)=>readFile(new URL(`../${p}`,import.meta.url),"utf8");
test("Journey sits directly after Aster and is read-only",async()=>{const page=await read("app/page.tsx"),view=await read("components/journey-view.tsx");assert.match(page,/id: "aster"[\s\S]{0,100}id: "journey"/);assert.match(page,/active === "journey" \? <JourneyView snapshots=\{snapshots\} \/>/);assert.match(view,/portfolio-growth\/daily/);assert.match(view,/portfolio-growth'/);assert.doesNotMatch(view,/method:\s*["']POST/);assert.doesNotMatch(view,/strategy2\/start|automation\/close-all|positions\/.*close/)});
test("Journey compound projection and one circle per day are explicit",async()=>{const view=await read("components/journey-view.tsx");assert.match(view,/Math\.log\(GOAL\/equity\)\/Math\.log\(1\+rate\)/);assert.match(view,/key=\{d\.date\}/);assert.match(view,/GOAL=1_000_000/);assert.match(view,/todayLevels/);assert.match(view,/averageDailyPercentage/)});
