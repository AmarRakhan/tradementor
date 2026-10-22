// Kostenpunt: browser-polling mag alleen draaien als de app zichtbaar is.
// Elke setInterval in web/components en web/lib moet ofwel document.visibilityState
// controleren, ofwel op de lijst van niet-netwerk-timers staan.
import { test } from "node:test";
import assert from "node:assert/strict";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const root = new URL("..", import.meta.url).pathname;

// Timers die geen API aanroepen (DOM-synchronisatie, service-worker-update).
const NON_NETWORK = new Set([
  "components/aster-portfolio-snapshot-enhancer.tsx:sync",
  "components/aster-profit-pot-snapshot-bridge.tsx:sync",
  "components/aster-profit-sweep-settings-bridge.tsx:sync",
  "components/pwa-registration.tsx:updateWorker",
]);

function files(dir) {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    if (statSync(full).isDirectory()) return files(full);
    return /\.(tsx?|mjs)$/.test(name) ? [full] : [];
  });
}

test("alle netwerk-pollers pauzeren als de app niet zichtbaar is", () => {
  const offenders = [];
  for (const file of [...files(join(root, "components")), ...files(join(root, "lib"))]) {
    const rel = relative(root, file);
    const lines = readFileSync(file, "utf8").split("\n");
    lines.forEach((line, index) => {
      const match = line.match(/setInterval\(\s*([A-Za-z_]\w*)?/);
      if (!match) return;
      // Alleen de callback zelf telt, niet een losse visibilitychange-handler eronder.
      const body = lines.slice(index, index + 4).join(" ")
        .slice(line.indexOf("setInterval"))
        .split(/const (onVisible|onVisibility|visible)\b|addEventListener/)[0];
      if (body.includes("visibilityState")) return;
      if (match[1] && NON_NETWORK.has(`${rel}:${match[1]}`)) return;
      offenders.push(`${rel}:${index + 1}`);
    });
  }
  assert.deepEqual(offenders, [], `Onbewaakte setInterval-pollers:\n${offenders.join("\n")}`);
});
