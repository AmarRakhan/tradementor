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
 const overflow=await page.evaluate(()=>document.documentElement.scrollWidth-window.innerWidth);
 assert.ok(overflow<=0,`horizontal overflow at ${width}: ${overflow}`);
 await page.close();
}
await browser.close();console.log("Extreme Spike visual screenshots captured and checked");