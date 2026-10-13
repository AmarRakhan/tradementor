import assert from "node:assert/strict";import{mkdir}from"node:fs/promises";import{chromium}from"playwright";
await mkdir("artifacts/extreme-spike",{recursive:true});const browser=await chromium.launch({headless:true});
for(const width of [320,390,430,768,1280]){
 const page=await browser.newPage({viewport:{width,height:920},deviceScaleFactor:1});
 await page.goto("http://127.0.0.1:4174/tests/visual/extreme-spike.html",{waitUntil:"networkidle"});
 await page.getByTestId("extreme-spike-entry").waitFor();
 assert.equal(await page.getByRole("radio",{name:/Extreme Spike/}).getAttribute("aria-checked"),"true");
 await page.screenshot({path:`artifacts/extreme-spike/card-${width}.png`,fullPage:true});
 await page.getByRole("button",{name:/5 – 6/}).click();
 assert.equal(await page.getByRole("option").count(),6);
 await page.screenshot({path:`artifacts/extreme-spike/dropdown-${width}.png`,fullPage:true});
 const option=page.getByRole("option",{name:/6 – 7/});
 const point=await option.boundingBox();
 assert.ok(point && point.width>0 && point.height>0,`sigma option not visible at ${width}`);
 const reachable=await option.evaluate(el=>{
   const r=el.getBoundingClientRect();
   const x=Math.max(0,Math.min(innerWidth-1,r.left+r.width/2));
   const y=Math.max(0,Math.min(innerHeight-1,r.top+r.height/2));
   return document.elementFromPoint(x,y)===el || el.contains(document.elementFromPoint(x,y));
 });
 assert.ok(reachable,`sigma option is clipped or covered at ${width}`);
 await option.click();
 assert.equal(await page.getByRole("button",{name:/6 – 7/}).count(),1);

 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
 assert.ok(overflow<=0,`horizontal overflow at ${width}: ${overflow}`);
 await page.close();
}
await browser.close();console.log("Extreme Spike visual screenshots captured and checked");