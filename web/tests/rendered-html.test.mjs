import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  const { default: worker } = await import(workerUrl.href);

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the TradeMentor web shell", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Amar Crypto Bot 2026<\/title>/i);
  assert.doesNotMatch(html, /TRADEMENTOR TEST|NIET DE LIVE-VERSIE/);
  assert.match(html, /Beveiligde sessie controleren/);
  assert.match(html, /tradementor-logo\.png/);
  assert.doesNotMatch(html, /react-loading-skeleton|Your site is taking shape/);
});

test("keeps execution safe and exposes the test destinations", async () => {
  const [page, layout, packageJson, authGate, liveControl, hyperliquidControl, legalPage] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../components/auth-gate.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/exchange-live-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/hyperliquid-strategy-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/legal/page.tsx", import.meta.url), "utf8"),
  ]);

  for (const destination of ["hyperliquid", "aster", "risk", "wallet"]) {
    assert.match(page, new RegExp(`id: "${destination}"`));
  }
  assert.match(page, /DCA Pulse/);
  assert.match(page, /Live handel uit/);
  assert.match(page, /Privacy, voorwaarden en risicowaarschuwing/);
  assert.match(page, /Nieuwe exposure geblokkeerd/);
  assert.match(page, /Bekijk Premium/);
  assert.match(page, /Bruto PnL \/ positie/);
  assert.match(page, /TP komt alleen uit serverbewijs/);
  assert.match(page, /strategy2Tp:\s*parseStrategy2Tp\(row\.strategy2Tp\)/);
  assert.match(page, /DataOrigin origin="direct"/);
  assert.match(page, /DataOrigin origin="calculated"/);
  assert.match(page, /NETTO OPEN PNL/);
  assert.match(page, /ACTIVE TRADE CAPITAL/);
  assert.doesNotMatch(page, /<Metric label="OPEN PNL"/);
  assert.match(page, /reportedTradeCapital.*optionalFinancialNumber\(data\.activeTradeCapital\)/);
  assert.match(page, /derivedTradeCapital.*position\.size.*position\.leverage/);
  assert.match(page, /activeTradeCapital:\s*accountDataAvailable\s*&&\s*activeTradeCapital !== null/);
  assert.match(page, /exchange === "aster" \? reportedTradeCapital/);
  assert.ok(page.indexOf('className="direction-balance"') < page.indexOf('<AsterPerformancePanel'), "LONG/netto/SHORT must appear before Aster Performance");
  assert.match(page, /tradementor\.activeDestination/);
  assert.match(page, /Abonnementstatus komt straks alleen van de beveiligde server/);
  assert.match(layout, /title:\s*"Amar Crypto Bot 2026"/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(authGate, /Live handel staat na iedere nieuwe aanmelding standaard uit/);
  assert.match(authGate, /Bevestig je e-mailadres/);
  assert.match(liveControl, /Ik begrijp dat de actieve strategie daarna echte orders met echt geld kan uitvoeren/);
  assert.match(liveControl, /api\/execution\/preflight/);
  assert.match(hyperliquidControl, /Veilig simuleren/);
  assert.match(hyperliquidControl, /Scan & Buy starten/);
  assert.match(hyperliquidControl, /Cloudcontrole \(minuten\)/);
  assert.match(legalPage, /historische resultaten voorspellen geen toekomstige resultaten/i);
});

test("Multi BB always exposes a personal live on/off control without bypassing readiness", async () => {
  const [source, performance, proxy, startRoute] = await Promise.all([
    readFile(new URL("../components/aster-strategy2-maker.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-performance-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/secure-strategy2-live.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/strategy2/start/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(source, /Multi BB live bot/);
  assert.match(source, /role="switch"/);
  assert.match(source, /async function toggleLive/);
  assert.match(source, /if\(status\.pending\)return/);
  assert.match(source, /if\(liveReady\)\{await action\("start"\)/);
  assert.match(source, /await checkReadiness\(\)/);
  assert.match(source, /onConfirmed\(confirmed\)/);
  assert.match(source, /JSON\.stringify\(\{confirm:true,notional_usd:20\}\)/);
  assert.doesNotMatch(performance, /AsterStrategy2QuickControl/);
  assert.match(proxy, /strategy2Paths/);
  assert.match(proxy, /Authorization: authorization/);
  assert.match(startRoute, /proxyStrategy2Live/);
});

test("keeps every browser request scoped to the signed-in Firebase user", async () => {
  const [client, proxy, scannerStart, scannerSimulate] = await Promise.all([
    readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/cloud-proxy.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/hyperliquid/scanner/start/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/hyperliquid/scanner/simulate/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(client, /firebaseAuth\.currentUser/);
  assert.match(client, /getIdToken/);
  assert.match(proxy, /authorization\?\.startsWith\("Bearer "\)/);
  assert.match(scannerStart, /proxyCloud\(request, "\/v1\/me\/hyperliquid\/scanner\/start"/);
  assert.match(scannerSimulate, /proxyCloud\(request, "\/v1\/me\/hyperliquid\/scanner\/simulate"/);
  assert.doesNotMatch(proxy, /private.?key|secret.?key/i);
});

test("premium redesign preserves position information and responsive controls", async () => {
  const [page, premium, inventory, manifest] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/premium.css", import.meta.url), "utf8"),
    readFile(new URL("../docs/UI_INVENTORY_BEFORE_PREMIUM_REDESIGN.md", import.meta.url), "utf8"),
    readFile(new URL("../public/manifest.webmanifest", import.meta.url), "utf8"),
  ]);

  for (const label of ["Grootte", "Instap", "Actueel", "Open PnL", "Resultaat", "DCA-status", "bijgekocht", "Position active"]) {
    assert.match(page, new RegExp(label, "i"));
  }
  for (const filter of ["Grootste positie", "Kleinste positie", "Vaakst bijgekocht", "Hoogste profit", "Grootste verlies", "Hoogste leverage", "Pair A–Z", "Alleen Long", "Alleen Short", "Top 10 grootste"]) {
    assert.match(page, new RegExp(filter));
  }
  assert.match(page, /PositionCloseControl/);
  assert.match(page, /PositionResultMeter/);
  assert.match(premium, /\.position-financial-grid/);
  assert.match(premium, /premium-position-row \.position-data[\s\S]*grid-column:\s*auto/);
  assert.match(premium, /position-financial-grid > \.position-result-meter[\s\S]*grid-column:\s*auto/);
  assert.match(premium, /\.position-result-ring/);
  assert.match(premium, /grid-template-columns:\s*repeat\(var\(--mobile-nav-count, 5\),\s*minmax\(0,\s*1fr\)\)/);
  assert.match(premium, /max-width:\s*370px/);
  assert.match(premium, /min-width:\s*680px/);
  assert.match(premium, /min-width:\s*1180px/);
  assert.match(premium, /prefers-reduced-motion/);
  assert.match(inventory, /no-regression checklist/i);
  assert.match(manifest, /"display"\s*:\s*"standalone"/);
});

test("risk timeline is read-only, explainable and responsive", async () => {
  const [page, source, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/risk-timeline.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /id: "risk"/);
  assert.match(page, /<RiskTimeline snapshots=\{snapshots\}/);
  for (const range of ["1H", "4H", "24H", "7D", "30D", "90D", "ALL"]) assert.match(source, new RegExp(`id: "${range}"`));
  assert.match(source, /Dit scherm kan geen orders plaatsen/);
  assert.match(source, /Waarom deze score/);
  assert.match(source, /VEILIGE WAT-ALS ANALYSE/);
  assert.match(source, /POSITIECAPACITEIT OP BASIS VAN MAINTENANCE/);
  assert.match(source, /estimatePositionCapacity/);
  assert.match(source, /GESCHAT GEMIDDELD TOTAAL/);
  assert.match(source, /Waarschijnlijke bandbreedte/);
  assert.match(source, /capacityRiskLabel/);
  assert.match(source, /Instapbedrag per positie/);
  assert.match(source, /entryRiskLabel/);
  assert.match(source, /asterBaseNotional/);
  assert.match(source, /notionalUsd/);
  assert.match(source, /geen ordertoestemming/);
  assert.match(source, /Nog geen bruikbare schatting/);
  assert.match(source, /Ontbrekende waarden worden nooit als nul/);
  assert.doesNotMatch(source, /authenticatedRequest|positions.*close|strategy2.*start|scanner.*start/i);
  assert.match(styles, /\.risk-main-grid/);
  assert.match(styles, /prefers-reduced-motion/);
});

test("compact list is default, persistent and reuses the existing close flow", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /useState<"cards" \| "list">\("list"\)/);
  assert.match(page, /tradementor\.positionLayout\.\$\{destination\}/);
  assert.match(page, /CompactPositionRow/);
  assert.match(page, /CompactClosedTradeRow/);
  assert.match(page, /PositionFilterSheet/);
  assert.match(page, />Lijst</);
  assert.match(page, />Kaarten</);
  assert.match(page, /PositionCloseControl/);
  assert.doesNotMatch(page, /<select aria-label="Posities filteren"/);
  assert.match(styles, /\.compact-position-list/);
  assert.match(styles, /\.position-filter-layer/);
});

test("Aster strategy explanation compares configuration with observable behavior", async () => {
  const [panel, behavior] = await Promise.all([
    readFile(new URL("../components/aster-performance-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-strategy2-behavior.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(panel, /AsterStrategy2Behavior/);
  assert.match(behavior, /Wat is ingesteld en doet de bot wat hij hoort te doen/);
  assert.match(behavior, /Zo hoort het/);
  assert.match(behavior, /Werkelijk gezien/);
  assert.match(behavior, /state:"unknown"/);
  assert.match(behavior, /Gebalanceerde start/);
  assert.match(behavior, /DCA-grenzen/);
  assert.match(behavior, /Take Profit en herstart/);
  assert.match(behavior, /Portfolio Protection/);
});

test("every trade can create a durable authenticated support report", async () => {
  const [page, control, support, route] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/trade-report-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/support-center.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/feedback/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(page, /TradeReportControl/);
  assert.match(page, /<SupportCenter/);
  assert.match(control, /Uw aanvraag is verstuurd/);
  assert.match(control, /Automatisch meegestuurde tradecontext/);
  assert.match(control, /API-sleutels en wachtwoorden horen nooit/);
  assert.match(control, /authenticatedRequest\("\/api\/feedback"/);
  assert.match(support, /Mijn meldingen/);
  assert.match(support, /Antwoord TradeMentor/);
  assert.match(route, /\/v1\/me\/feedback/);
});

test("parallel premium interface preserves the trusted app and cannot trade while switching", async () => {
  const [page, premiumNext, preferenceRoute, inventory, cloudApi] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
    readFile(new URL("../app/api/preferences/interface/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../docs/PARALLEL_PREMIUM_INTERFACE_INVENTORY.md", import.meta.url), "utf8"),
    readFile(new URL("../../cloud_api/main.py", import.meta.url), "utf8"),
  ]);

  assert.match(page, /interfaceMode === "premium"/);
  assert.match(page, /PremiumExperience/);
  assert.match(page, /InterfaceModeSelector/);
  assert.match(page, /Vertrouwde weergave/);
  assert.match(page, /Premium-weergave/);
  assert.match(page, /Oude weergave/);
  assert.match(page, /aria-label="Terug naar de oude vertrouwde weergave"/);
  assert.match(page, /tradementor\.interfaceMode/);
  assert.match(page, /AsterStrategy2Maker/);
  assert.match(page, /HyperliquidStrategyControl/);
  assert.match(page, /ONVOLDOENDE GEGEVENS/);
  assert.match(page, /Binnenkort beschikbaar/);

  const switchFunction = page.match(/const changeInterfaceMode = async[\s\S]*?\n  };/i)?.[0] ?? "";
  assert.match(switchFunction, /api\/preferences\/interface/);
  assert.doesNotMatch(switchFunction, /scanner\/(start|stop)|strategy2\/(start|stop)|positions.*close|close-all/i);

  assert.match(preferenceRoute, /\/v1\/me\/preferences\/interface/);
  assert.match(cloudApi, /@app\.get\("\/v1\/me\/preferences\/interface"\)/);
  assert.match(cloudApi, /@app\.put\("\/v1\/me\/preferences\/interface"\)/);
  assert.match(inventory, /Existing trusted interface remains the default/);
  assert.match(premiumNext, /\.premium-app-shell/);
  assert.match(premiumNext, /@media \(max-width:980px\)/);
  assert.match(premiumNext, /prefers-reduced-motion/);
});

test("mobile app shells lock horizontal touch movement without blocking vertical scrolling", async () => {
  const [globalStyles, premiumNext] = await Promise.all([
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
  ]);

  assert.match(globalStyles, /html\s*\{[^}]*overflow-x:\s*hidden\s*!important/i);
  assert.match(globalStyles, /body\s*\{[^}]*overflow-x:\s*hidden\s*!important/i);
  assert.match(globalStyles, /\.app-shell\s*\{[^}]*touch-action:\s*pan-y/i);
  assert.match(globalStyles, /\.workspace\s*\{[^}]*overflow-x:\s*hidden/i);
  assert.match(premiumNext, /\.premium-app-shell\s*\{[^}]*touch-action:\s*pan-y/i);
  assert.match(premiumNext, /\.premium-workspace\s*\{[^}]*overflow-x:\s*hidden/i);
});

test("trusted mobile Aster layout uses compact proportions without hiding values", async () => {
  const premiumNext = await readFile(new URL("../app/premium-next.css", import.meta.url), "utf8");
  assert.match(premiumNext, /\.hero-panel[^}]*min-height:\s*232px\s*!important/i);
  assert.match(premiumNext, /\.hero-copy h1[^}]*font-size:\s*clamp\(28px,9vw,34px\)/i);
  assert.match(premiumNext, /\.metric-strip[^}]*repeat\(2,minmax\(0,1fr\)\)/i);
  assert.match(premiumNext, /\.direction-balance[^}]*repeat\(3,minmax\(0,1fr\)\)/i);
  assert.match(premiumNext, /\.strategy-behavior h2[^}]*font-size:\s*21px/i);
});

test("Positions reuses the trusted overview and adds an exchange-aware professional chart", async () => {
  const [page, chart, marketRoute, eventRoute, styles, equityHistory] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/trading-chart.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/market-data/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/exchanges/aster/trade-events/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
    readFile(new URL("../lib/portfolio-equity-history.ts", import.meta.url), "utf8"),
  ]);
  assert.match(page, /id: "aster"[\s\S]*id: "positions"[\s\S]*id: "risk"/);
  assert.match(page, /<SafeTradingChart selection=\{selection\}/);
  assert.match(chart, /class ChartErrorBoundary/);
  assert.match(chart, /if\(next\.time<last\.time\)return rows/);
  assert.match(page, /selectPortfolio/);
  assert.match(page, />Portfolio<\/button>/);
  assert.match(page, /<ExchangeView[\s\S]*positionsOnly/);
  assert.match(page, /selectedPositionId/);
  assert.match(chart, /CandlestickSeries/);
  assert.match(chart, /createSeriesMarkers/);
  assert.match(chart, /tradementor\.test\.portfolioEquity\.v1/);
  assert.match(chart, /PERSOONLIJKE EQUITY/);
  assert.doesNotMatch(chart, /entrySeries\.setData/);
  assert.match(chart, /createPriceLine\(\{ price:Number\(breakEvenPrice\)[\s\S]*title:"WINST VANAF"/);
  assert.match(chart, /VOLGENDE \$\{selection\.side\.toUpperCase\(\)\} DCA/);
  assert.match(chart, /title:next\?.*:`DCA \$\{Math\.round/s);
  assert.match(chart, /aster-confirmed-fills|aster\/trade-events/);
  assert.match(chart, /layoutVerifiedTradeMarkers/);
  assert.match(chart, /Werkelijke prijs/);
  assert.match(chart, /EMA 200/);
  assert.match(chart, /Bollinger Bands/);
  assert.match(chart, /\[\[upper,"rgba\(74,163,255,\.55\)"\],\[middle,"rgba\(85,227,255,\.42\)"\],\[lower,"rgba\(74,163,255,\.55\)"\]\]/);
  assert.match(chart, /priceLineVisible:false,lastValueVisible:false,crosshairMarkerVisible:false/);
  assert.match(chart, /RSI 14/);
  assert.match(chart, /MACD/);
  assert.match(chart, /requestFullscreen/);
  assert.match(chart, /wss:\/\/api\.hyperliquid\.xyz\/ws/);
  assert.match(chart, /wss:\/\/fstream\.asterdex\.com/);
  assert.match(marketRoute, /candleSnapshot/);
  assert.match(marketRoute, /fapi\.asterdex\.com\/fapi\/v1\/klines/);
  assert.match(eventRoute, /\/v1\/me\/aster\/trade-events/);
  assert.match(styles, /\.trading-terminal/);
  assert.match(styles, /@media\(max-width:760px\)/);
  assert.match(styles, /\.chart-canvas\s*\{[^}]*touch-action:\s*pan-y/i);
  assert.doesNotMatch(styles, /\.chart-canvas\s*\{[^}]*touch-action:\s*none/i);
  assert.match(chart, /handleScroll:\{mouseWheel:true,pressedMouseMove:true,horzTouchDrag:true,vertTouchDrag:true\}/);
  assert.match(chart, /handleScale:\{mouseWheel:true,pinch:true,axisPressedMouseMove:true\}/);
  assert.match(chart, /sanitizePortfolioEquityRows/);
  assert.match(page, /isCompletePortfolioSnapshot/);
  assert.match(equityHistory, /MAX_UNCONFIRMED_CHANGE_FACTOR\s*=\s*20/);
  assert.match(equityHistory, /expected.*hyperliquid.*aster/s);
});

test("admin portal is server-authorized and recovery never contains trading actions", async () => {
  const [page, admin, healthRoute, markerLayout] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/admin-portal.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/api/admin/health/route.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/trade-marker-layout.ts", import.meta.url), "utf8"),
  ]);
  assert.match(page, /id: "admin"/);
  assert.match(page, /<AdminPortal/);
  assert.match(page, /adminDeviceAllowed/);
  assert.match(page, /AdminMfaControl/);
  assert.match(page, /amar_rakhan@hotmail\.com/);
  assert.match(admin, /Geen beheeractie kan orders plaatsen/);
  assert.match(healthRoute, /\/v1\/admin\/health\/accounts/);
  assert.match(markerLayout, /Math\.max\(candle\.high,band\?\.upper/);
  assert.match(markerLayout, /Math\.min\(candle\.low,band\?\.lower/);
  assert.match(markerLayout, /events\.push\(event\)/);
});

test("mobile navigation keeps Wallet visible after Positions and Risk were added", async () => {
  const [page, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /\{ id: "wallet", label: "WALLET", glyph: "W" \}/);
  assert.match(page, /--mobile-nav-count/);
  assert.match(page, /tradementor\.navigation\.hyperliquid\.visible/);
  assert.match(page, /Hyperliquid-tab tonen/);
  assert.match(styles, /grid-template-columns:\s*repeat\(var\(--mobile-nav-count, 5\), minmax\(0, 1fr\)\)/);
});

test("Strategy 2 has one settings editor and its read-only summary opens the same maker", async () => {
  const [behavior, performance, styles] = await Promise.all([
    readFile(new URL("../components/aster-strategy2-behavior.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/aster-performance-panel.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/premium-next.css", import.meta.url), "utf8"),
  ]);
  assert.match(behavior, /Open Strategy Maker/);
  assert.match(behavior, /tradementor:open-strategy2-maker/);
  assert.doesNotMatch(behavior, /strategy2\/settings/);
  assert.doesNotMatch(behavior, /authenticatedRequest/);
  assert.match(behavior, /Basisorder per positie/);
  assert.match(behavior, /Portfolio Protection/);
  assert.match(performance, /AsterStrategy2Behavior snapshot=\{snapshot\}/);
  assert.match(styles, /\.strategy-inline-editor/);
});

test("positions expose confirmed DCA count and latest purchase sorting", async () => {
  const page = await readFile(new URL("../app/page.tsx", import.meta.url), "utf8");
  assert.match(page, /Laatst aangekocht/);
  assert.match(page, /filter === "latest"/);
  assert.match(page, /lastOrderAt/);
  assert.match(page, /dcaCount: asNumber\(row\.dcaCount\)/);
});

test("Aster calendar shows daily portfolio change without inventing missing history", async () => {
  const panel = await readFile(new URL("../components/aster-performance-panel.tsx", import.meta.url), "utf8");
  assert.match(panel, /Portfoliowaarde die dag/);
  assert.match(panel, /tradementor\.test\.portfolioEquity\.v1/);
  assert.match(panel, /values\.length > 1/);
  assert.match(panel, /Portefeuille .*—/);
  assert.match(panel, /change >= 0 \? "profit" : "loss"/);
});

test("Aster summary places Portfolio Groei between realized profit and closed trade count", async () => {
  const [page, card, styles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/portfolio-growth-card.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /className="metric realized-trades"/);
  assert.match(page, /<PortfolioGrowthCard onChanged=\{onChanged\}/);
  assert.match(page, /TRADES GESLOTEN/);
  assert.doesNotMatch(page, /realized-today-values/);
  assert.match(card, /PORTFOLIO GROEI/);
  assert.match(card, /Netto winst bij alles sluiten/);
  assert.match(card, /ALLES SLUITEN/);
  assert.match(card, /quote_id:data\.quoteId/);
  assert.match(styles, /\.portfolio-growth\.profit\{[^}]*border:/i);
  assert.match(styles, /\.portfolio-close-all:disabled/);
});

test("application zoom is blocked while deliberate chart gestures remain available", async () => {
  const [layout, guard, styles] = await Promise.all([
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/zoom-guard.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
  ]);
  assert.match(layout, /maximumScale:\s*1/);
  assert.match(layout, /userScalable:\s*false/);
  assert.match(layout, /<ZoomGuard\s*\/>/);
  assert.match(guard, /event\.touches\.length > 1/);
  assert.match(guard, /closest\("\.chart-canvas"\)/);
  assert.match(styles, /html\s*\{[^}]*touch-action:\s*pan-y/i);
  assert.match(styles, /body\s*\{[^}]*touch-action:\s*pan-y/i);
});

test("admin access requires Google Authenticator on every device", async () => {
  const [page, control, client, verifyRoute] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../components/admin-mfa-control.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/cloud-client.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/api/admin/device/verify/route.ts", import.meta.url), "utf8"),
  ]);
  assert.match(page, /AdminMfaControl/);
  assert.match(control, /Google Authenticator/);
  assert.match(control, /recoveryCodes/);
  assert.match(control, /12 uur/);
  assert.match(client, /tradementor\.admin\.credential\.v2/);
  assert.match(verifyRoute, /\/v1\/admin\/device\/verify/);
});

test("Suriname Heritage is a persistent presentation-only skin", async () => {
  const [page, layout, skinStyles, chart] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/layout.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/suriname-heritage.css", import.meta.url), "utf8"),
    readFile(new URL("../components/trading-chart.tsx", import.meta.url), "utf8"),
  ]);
  assert.match(page, /type AppSkin = "original" \| "suriname-heritage"/);
  assert.match(page, /tradementor\.appSkin/);
  assert.match(page, /Suriname Heritage/);
  assert.match(page, /Alleen visueel/);
  assert.match(layout, /suriname-heritage\.css/);
  assert.match(skinStyles, /suriname-heritage-hero-v1\.png/);
  assert.match(skinStyles, /html\[data-app-skin="suriname-heritage"\]/);
  assert.match(chart, /tradementor:skin-change/);
  assert.match(chart, /heritage\?"#031008":"#061225"/);
  assert.match(page, /data-destination=\{item\.id\}/);
  assert.match(skinStyles, /data-destination="aster"/);
  assert.match(skinStyles, /data-destination="wallet"/);
});

test("Suriname Heritage covers reusable surfaces across every main tab", async () => {
  const skinStyles = await readFile(new URL("../app/suriname-heritage.css", import.meta.url), "utf8");
  for (const selector of [
    ".support-center", ".aster-performance", ".performance-metrics>div",
    ".strategy-performance-grid>article", ".strategy-power-control", ".safety-card",
    ".compact-position-row", ".position-layout-choice", ".position-filter-sheet",
  ]) assert.match(skinStyles, new RegExp(selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")));
  assert.match(skinStyles, /\.compact-position-row\.positive/);
  assert.match(skinStyles, /\.compact-position-row\.negative/);
  assert.match(skinStyles, /button:disabled/);
});

test("live maintenance value remains inside the gauge and receives a severity color", async () => {
  const [page, skinStyles] = await Promise.all([
    readFile(new URL("../app/page.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/suriname-heritage.css", import.meta.url), "utf8"),
  ]);
  assert.match(page, /risk-orbit risk-\$\{view\.riskTone\}/);
  assert.match(page, /riskTone: riskNumber === null/);
  for (const tone of ["safe", "caution", "high", "critical", "unknown"]) assert.match(skinStyles, new RegExp(`risk-${tone}`));
  assert.match(skinStyles, /font-size:25px!important/);
  assert.match(skinStyles, /width:98px!important/);
});
