import { chromium } from "playwright";
import { readFile, writeFile, copyFile } from "node:fs/promises";
import http from "node:http";
import path from "node:path";
const dir=path.dirname(new URL(import.meta.url).pathname);
await copyFile(process.env.LWC_JS,path.join(dir,"lwc.js"));
const server=http.createServer(async(req,res)=>{const f=req.url.split("?")[0].slice(1)||"harness.html";try{const b=await readFile(path.join(dir,f));res.writeHead(200,{"content-type":f.endsWith(".js")?"text/javascript":"text/html"});res.end(b)}catch{res.writeHead(404);res.end()}}).listen(4635);
const browser=await chromium.launch();
const results=[];
const sleep=(ms)=>new Promise(r=>setTimeout(r,ms));
async function run(mode){
  const ctx=await browser.newContext({viewport:{width:390,height:700},hasTouch:true,isMobile:true,deviceScaleFactor:2});
  const page=await ctx.newPage();
  await page.goto(`http://127.0.0.1:4635/harness.html?mode=${mode}`);await sleep(400);
  const cdp=await ctx.newCDPSession(page);
  const touch=async(type,x,y)=>cdp.send("Input.dispatchTouchEvent",{type,touchPoints:type==="touchEnd"?[]:[{x,y}]});
  const drag=async(x1,x2,y,hold=0)=>{await touch("touchStart",x1,y);if(hold)await sleep(hold);const n=12;for(let i=1;i<=n;i++){await touch("touchMove",x1+(x2-x1)*i/n,y);await sleep(16)}await touch("touchEnd",x2,y);await sleep(900)};
  // 1. Press-and-hold (crosshair) on the chart, as when tapping a label slowly.
  await drag(200,150,160,600);
  const a=await page.evaluate(()=>window.range());
  // 2. Normal quick swipe to look back: must pan.
  await drag(120,320,160,0);
  const b=await page.evaluate(()=>window.range());
  const panned=Math.abs(b.from-a.from)>3;
  // 3. Price-scale memory: manual range survives rebuild-style restore.
  await page.evaluate(()=>window.setPs({from:240,to:270}));
  const ps=await page.evaluate(()=>window.ps());
  await page.screenshot({path:path.join(dir,`touch-${mode}.png`)});
  results.push({mode,afterHold:a,afterSwipe:b,swipePanned:panned,priceScale:ps});
  await ctx.close();
}
async function runVertical(mode){
  const ctx=await browser.newContext({viewport:{width:390,height:700},hasTouch:true,isMobile:true,deviceScaleFactor:2});
  const page=await ctx.newPage();
  await page.goto(`http://127.0.0.1:4635/harness.html?mode=${mode}`);await sleep(400);
  const cdp=await ctx.newCDPSession(page);
  const touch=async(type,x,y)=>cdp.send("Input.dispatchTouchEvent",{type,touchPoints:type==="touchEnd"?[]:[{x,y}]});
  const drag=async(x1,y1,x2,y2)=>{await touch("touchStart",x1,y1);const n=12;for(let i=1;i<=n;i++){await touch("touchMove",x1+(x2-x1)*i/n,y1+(y2-y1)*i/n);await sleep(16)}await touch("touchEnd",x2,y2);await sleep(900)};
  const p0=await page.evaluate(()=>window.ps());
  await drag(180,240,180,90); // straight up, fresh chart, axis never touched
  const p1=await page.evaluate(()=>window.ps());
  const vertMoved=Math.abs(p1.range.from-p0.range.from)>.3;
  // Fresh page: horizontal swipe must keep auto scale.
  await page.reload();await sleep(400);
  const cdp2=await ctx.newCDPSession(page);
  const t2=async(type,x,y)=>cdp2.send("Input.dispatchTouchEvent",{type,touchPoints:type==="touchEnd"?[]:[{x,y}]});
  await t2("touchStart",120,160);for(let i=1;i<=12;i++){await t2("touchMove",120+200*i/12,160+4*i/12);await sleep(16)}await t2("touchEnd",320,164);await sleep(900);
  const p2=await page.evaluate(()=>window.ps());
  // Tap only: auto scale stays.
  await t2("touchStart",200,160);await sleep(60);await t2("touchEnd",200,160);await sleep(400);
  const p3=await page.evaluate(()=>window.ps());
  await page.screenshot({path:path.join(dir,`vertical-${mode}.png`)});
  const r={mode,vertical:true,vertMoved,before:p0.range.from,after:p1.range.from,autoAfterHorizontal:p2.auto,autoAfterTap:p3.auto};
  results.push(r);
  console.log(`::notice title=QA637 ${mode}::vertMoved=${vertMoved} from ${p0.range.from.toFixed(2)} -> ${p1.range.from.toFixed(2)} autoAfterHorizontal=${p2.auto} autoAfterTap=${p3.auto}`);
  await ctx.close();
}
await run("old");await run("new");await runVertical("new");await runVertical("v637");
await browser.close();server.close();
await writeFile(path.join(dir,"result.json"),JSON.stringify(results,null,2));
console.log(JSON.stringify(results,null,2));
for(const r of results.filter(r=>!r.vertical))console.log(`::notice title=QA635 ${r.mode}::swipePanned=${r.swipePanned} afterHold=${r.afterHold.from.toFixed(1)} afterSwipe=${r.afterSwipe.from.toFixed(1)} priceAuto=${r.priceScale.auto} priceFrom=${r.priceScale.range&&r.priceScale.range.from.toFixed(2)}`);
const old=results.find(r=>r.mode==="old"),neu=results.find(r=>r.mode==="new"&&!r.vertical);
const v=results.find(r=>r.mode==="v637");
if(!v.vertMoved||v.autoAfterHorizontal!==true||v.autoAfterTap!==true){console.error("FAIL: 637 vertical");process.exit(1)}
if(!neu.swipePanned){console.error("FAIL: new config does not pan after press-and-hold");process.exit(1)}
if(neu.priceScale.auto!==false||Math.abs(neu.priceScale.range.from-240)>.01){console.error("FAIL: price scale restore");process.exit(1)}
console.log(old.swipePanned?"NOTE: old config also panned (bug not reproduced in headless)":"REPRODUCED: old config blocked the swipe after press-and-hold");
console.log("PASS");
