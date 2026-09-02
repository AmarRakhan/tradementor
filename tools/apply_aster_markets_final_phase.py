from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_required(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"missing anchor: {label}")
    return text.replace(old, new, 1)


def patch_page() -> None:
    p = ROOT / "web/app/page.tsx"
    s = p.read_text(encoding="utf-8")

    s = s.replace('import { AsterPerformancePanel } from "@/components/aster-performance-panel";\n', '')
    if 'import { MarketsPage } from "@/components/markets-page";' not in s:
        s = s.replace('import { JourneyView } from "@/components/journey-view";\n', 'import { JourneyView } from "@/components/journey-view";\nimport { MarketsPage } from "@/components/markets-page";\n')

    s = s.replace('type Destination = "hyperliquid" | "aster" | "journey" | "positions" | "risk" | "wallet" | "admin";',
                  'type Destination = "markets" | "hyperliquid" | "aster" | "journey" | "positions" | "risk" | "wallet" | "admin";')
    s = s.replace('const destinationIds = new Set<Destination>(["hyperliquid", "aster", "journey", "positions", "risk", "wallet", "admin"]);',
                  'const destinationIds = new Set<Destination>(["markets", "hyperliquid", "aster", "journey", "positions", "risk", "wallet", "admin"]);')

    start = s.index('const destinations: Array<{ id: Destination; label: string; glyph: string }> = [')
    end = s.index('];', start) + 2
    s = s[:start] + '''const destinations: Array<{ id: Destination; label: string; glyph: string }> = [
  { id: "markets", label: "MARKETS", glyph: "M" },
  { id: "aster", label: "ASTER", glyph: "AS" },
  { id: "journey", label: "JOURNEY", glyph: "J" },
  { id: "wallet", label: "WALLET", glyph: "W" },
];''' + s[end:]

    s = s.replace('let initial = route || (destinationIds.has(saved as Destination) ? saved as Destination : "hyperliquid");',
                  'let initial = route && ["markets","aster","journey","wallet"].includes(route) ? route : (["markets","aster","journey","wallet"].includes(String(saved)) ? saved as Destination : "aster");')
    s = s.replace('let initial = route && ["aster","journey","wallet"].includes(route) ? route : (["aster","journey","wallet"].includes(String(saved)) ? saved as Destination : "aster");',
                  'let initial = route && ["markets","aster","journey","wallet"].includes(route) ? route : (["markets","aster","journey","wallet"].includes(String(saved)) ? saved as Destination : "aster");')

    old_content = '{active === "admin" && adminDeviceAllowed ? <AdminPortal /> : active === "journey" ? <JourneyView snapshots={snapshots} /> : active === "wallet" ? <WalletView'
    if old_content in s:
        s = s.replace(old_content, '{active === "markets" ? <MarketsPage /> : active === "admin" && adminDeviceAllowed ? <AdminPortal /> : active === "journey" ? <JourneyView snapshots={snapshots} /> : active === "wallet" ? <WalletView', 1)

    s = s.replace('      {!positionsOnly && destination === "aster" && <fieldset className="aster-action-gate" disabled={!asterActionsEnabled}><AsterPerformancePanel snapshot={snapshot.data} onChanged={onRefresh} /></fieldset>}\n', '')
    # Historical calendar/result cards are removed from the visible Aster main page, while helper code may remain for internal/history use.
    marker = '        {destination === "aster" && <TodayRealizedMetric onChanged={onRefresh}'
    if marker in s:
        line_start = s.index(marker)
        line_end = s.index('\n', line_start) + 1
        s = s[:line_start] + s[line_end:]

    # Four visible main tabs are fixed; the old Hyperliquid visibility preference must not mutate the primary nav.
    s = s.replace('  const visibleDestinations = useMemo(\n    () => destinations.filter((item) => (item.id !== "hyperliquid" || showHyperliquidTab) && (item.id !== "admin" || adminDeviceAllowed)),\n    [showHyperliquidTab, adminDeviceAllowed],\n  );',
                  '  const visibleDestinations = useMemo(() => destinations, []);')

    p.write_text(s, encoding="utf-8")


def patch_tests() -> None:
    p = ROOT / "web/tests/rendered-html.test.mjs"
    s = p.read_text(encoding="utf-8")
    s = s.replace('for (const destination of ["hyperliquid", "aster", "risk", "wallet"]) {\n    assert.match(page, new RegExp(`id: "${destination}"`));\n  }',
                  'for (const destination of ["markets", "aster", "journey", "wallet"]) {\n    assert.match(page, new RegExp(`id: "${destination}"`));\n  }\n  const mainNav = page.slice(page.indexOf("const destinations:"), page.indexOf("const exchangeCopy:"));\n  assert.doesNotMatch(mainNav, /id: "(?:hyperliquid|positions|risk|admin)"/);')
    s = s.replace('assert.match(page, /id: "aster"[\\s\\S]*id: "positions"[\\s\\S]*id: "risk"/);',
                  'assert.match(page, /function PositionsPage/);\n  const mainNav = page.slice(page.indexOf("const destinations:"), page.indexOf("const exchangeCopy:"));\n  assert.doesNotMatch(mainNav, /id: "(?:positions|risk)"/);')
    s = s.replace('assert.match(page, /id: "admin"/);', 'assert.match(page, /<AdminPortal/);\n  assert.match(page, /destinationIds[\\s\\S]*"admin"/);')
    p.write_text(s, encoding="utf-8")


def patch_direct_settings_css() -> None:
    p = ROOT / "web/app/premium-next.css"
    s = p.read_text(encoding="utf-8")
    marker = '/* ASTER BOT DIRECT SETTINGS FINAL */'
    if marker in s:
        return
    s += r'''

/* ASTER BOT DIRECT SETTINGS FINAL */
.aster-bot-direct-settings{display:grid;gap:12px}.strategy-settings-group{border:1px solid rgba(255,255,255,.08);border-radius:14px;background:rgba(6,11,18,.45);overflow:hidden}.strategy-settings-group>summary{cursor:pointer;list-style:none;padding:13px 14px;font-weight:850;display:flex;align-items:center;justify-content:space-between;gap:8px}.strategy-settings-group>summary::-webkit-details-marker{display:none}.direct-settings-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:10px;padding:0 13px 13px}.direct-settings-grid>label{display:grid;gap:5px;font-size:11px;color:#9ca8b9}.direct-settings-grid input,.direct-settings-grid select{width:100%;min-width:0;border:1px solid rgba(255,255,255,.09);background:#080d15;color:#fff;border-radius:9px;padding:10px;font:inherit}.direct-profile-grid{display:grid;grid-template-columns:1fr 1fr;gap:10px}.direct-save-bar{position:sticky;bottom:72px;z-index:8;padding:10px;border:1px solid rgba(255,255,255,.08);border-radius:13px;background:rgba(8,13,21,.94);backdrop-filter:blur(12px)}.direct-save-bar button:first-child:disabled{opacity:.55}.profile-long>summary{color:#55df9f}.profile-short>summary{color:#ff7a87}
@media(max-width:760px){.direct-profile-grid,.direct-settings-grid{grid-template-columns:1fr}.direct-save-bar{bottom:74px;grid-template-columns:1fr}.aster-bot-direct-settings{gap:9px}}
'''
    p.write_text(s, encoding="utf-8")


def add_acceptance_test() -> None:
    p = ROOT / "web/tests/aster-markets-final-acceptance.test.mjs"
    p.write_text(r'''import test from "node:test";
import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";

const read = (name) => readFile(new URL(name, import.meta.url), "utf8");

test("main navigation is exactly Markets Aster Journey Wallet", async()=>{
  const page=await read("../app/page.tsx");
  const nav=page.slice(page.indexOf("const destinations:"),page.indexOf("const exchangeCopy:"));
  assert.match(nav,/id: "markets"[\s\S]*id: "aster"[\s\S]*id: "journey"[\s\S]*id: "wallet"/);
  assert.doesNotMatch(nav,/id: "(?:hyperliquid|positions|risk|admin)"/);
  assert.match(page,/active === "markets" \? <MarketsPage/);
});

test("Aster Bot is a direct dirty-state editor with LONG SHORT profiles and pair overrides",async()=>{
  const maker=await read("../components/aster-strategy2-maker.tsx");
  assert.match(maker,/<ProfilePanel side="LONG"/);assert.match(maker,/<ProfilePanel side="SHORT"/);
  assert.match(maker,/Pair override/);assert.match(maker,/Reset naar standaard/);assert.match(maker,/dirty/);
  assert.doesNotMatch(maker,/maker-overlay|STAP \{|STAP [0-9]|Strategy Maker openen/);
  assert.match(maker,/Actieve trades beschermd/);assert.match(maker,/dcaCount 3 behouden/);
});

test("Markets reuses Trade Center chart and exposes realtime quick-trade safety states",async()=>{
  const markets=await read("../components/markets-page.tsx");
  assert.match(markets,/SafeTradingChart/);assert.match(markets,/mode="aster-detail"/);assert.match(markets,/Open chart/);
  assert.match(markets,/OPENING/);assert.match(markets,/ACTIVE/);assert.match(markets,/FAILED/);
  assert.match(markets,/idempotencyKey/);assert.match(markets,/ACTIVE LONG/);assert.match(markets,/ACTIVE SHORT/);
  assert.match(markets,/pairOverrides/);assert.match(markets,/CUSTOM pair override server-side opgeslagen zonder cycle reset/);
});

test("Markets keeps Bollinger classification tied to the displayed live price and enriched bands",async()=>{
  const markets=await read("../components/markets-page.tsx");
  assert.match(markets,/classifyBb\(row\.lastPrice,update\.bbUpper,update\.bbLower,update\.bbStatus\)/);
  assert.match(markets,/BB 20 · 2σ/);assert.match(markets,/bbFilter/);assert.match(markets,/timeframe/);
});
''', encoding="utf-8")


def main() -> None:
    patch_page(); patch_tests(); patch_direct_settings_css(); add_acceptance_test()
    print("final Aster Markets integration applied")

if __name__ == "__main__":
    main()
