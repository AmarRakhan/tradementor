import test from "node:test";
import assert from "node:assert/strict";
import { existsSync, statSync } from "node:fs";

const video = new URL("../public/portfolio-impact-bull-bear-master.mp4", import.meta.url);
const poster = new URL("../public/portfolio-impact-bull-bear-neutral.webp", import.meta.url);

test("Bull Bear master media is committed before production merge", () => {
  assert.equal(existsSync(video), true, "Missing permanent Bull Bear master video");
  assert.equal(existsSync(poster), true, "Missing permanent neutral Bull Bear poster");
  assert.ok(statSync(video).size > 100_000, "Master video is unexpectedly small");
  assert.ok(statSync(poster).size > 10_000, "Neutral poster is unexpectedly small");
});
