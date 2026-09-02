from pathlib import Path
p=Path(__file__).resolve().parents[1]/'web/app/page.tsx'
s=p.read_text(encoding='utf-8')
s=s.replace('import { AsterPerformancePanel } from "@/components/aster-performance-panel";\n','')
s=s.replace('      {!positionsOnly && destination === "aster" && <fieldset className="aster-action-gate" disabled={!asterActionsEnabled}><AsterPerformancePanel snapshot={snapshot.data} onChanged={onRefresh} /></fieldset>}\n','')
s=s.replace('        {destination === "aster" && <TodayRealizedMetric onChanged={onRefresh} available={snapshot.data?.historyAvailable === true} positions={view.positions} equity={view.equity} availableToTrade={view.available} openPnl={netOpenPnl} trades={realizedEvents.length ? realizedEvents.map((event) => ({ symbol: String(event.symbol ?? ""), side: "", size: 0, entry: 0, exit: 0, pnl: asNumber(event.realizedPnlUsd), openedAt: "", closedAt: String(event.closedAt ?? ""), strategy: "", dcaCount: 0 })) : view.closedTrades} />}\n','')
# User-facing navigation is strictly four primary tabs. Markets is injected by MarketsNavigationBridge immediately left of Aster.
old='''const destinations: Array<{ id: Destination; label: string; glyph: string }> = [\n  { id: "hyperliquid", label: "HYPERLIQUID", glyph: "HL" },\n  { id: "aster", label: "ASTER", glyph: "AS" },\n  { id: "journey", label: "JOURNEY", glyph: "J" },\n  { id: "positions", label: "POSITIONS", glyph: "P" },\n  { id: "risk", label: "RISICO", glyph: "R" },\n  { id: "wallet", label: "WALLET", glyph: "W" },\n  { id: "admin", label: "ADMIN", glyph: "A" },\n];'''
new='''const destinations: Array<{ id: Destination; label: string; glyph: string }> = [\n  { id: "aster", label: "ASTER", glyph: "AS" },\n  { id: "journey", label: "JOURNEY", glyph: "J" },\n  { id: "wallet", label: "WALLET", glyph: "W" },\n];'''
if old in s:s=s.replace(old,new)
# Never restore a removed legacy destination into the visible shell.
s=s.replace('let initial = route || (destinationIds.has(saved as Destination) ? saved as Destination : "hyperliquid");','let initial = route && ["aster","journey","wallet"].includes(route) ? route : (["aster","journey","wallet"].includes(String(saved)) ? saved as Destination : "aster");')
p.write_text(s,encoding='utf-8')
print('phase4 applied')
