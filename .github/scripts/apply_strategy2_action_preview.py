from pathlib import Path


def replace_once(text: str, old: str, new: str, label: str) -> str:
    if old not in text:
        raise SystemExit(f"patch anchor missing: {label}")
    if text.count(old) != 1:
        raise SystemExit(f"patch anchor not unique: {label} ({text.count(old)})")
    return text.replace(old, new, 1)


backend = Path("cloud_api/aster_multi_bb.py")
text = backend.read_text()
helper = '''\n\ndef position_action_preview(*, row: dict[str, Any], state: dict[str, Any], settings: MultiBbConfig, account_equity: float = 0.0) -> dict[str, Any]:
    """Expose the exact next Strategy 2 DCA/TP levels used by the execution engine."""
    side = str(row.get("positionSide", "")).upper()
    entry = _f(row.get("entryPrice"))
    mark = _f(row.get("markPrice"), entry)
    qty = abs(_f(row.get("positionAmt")))
    if side not in {"LONG", "SHORT"} or entry <= 0 or mark <= 0 or qty <= 0:
        return {}
    tp_price = entry * (1 + settings.take_profit if side == "LONG" else 1 - settings.take_profit)
    tp_distance_usd = abs(tp_price - mark)
    tp_distance_pct = tp_distance_usd / mark * 100
    expected_pnl_at_tp = ((tp_price - entry) if side == "LONG" else (entry - tp_price)) * qty
    current_pnl = ((mark - entry) if side == "LONG" else (entry - mark)) * qty
    portfolio_value_at_tp = account_equity + (expected_pnl_at_tp - current_pnl) if account_equity > 0 else None
    dca_count = _i(state.get("dcaCount"))
    anchor = _f(state.get("lastBotFillPrice"), entry)
    dca_allowed = settings.unlimited_dca or dca_count < settings.max_dca
    next_dca_price = anchor * (1 - settings.dca_distance if side == "LONG" else 1 + settings.dca_distance) if dca_allowed and anchor > 0 else None
    next_dca_distance_usd = abs(next_dca_price - mark) if next_dca_price else None
    next_dca_distance_pct = next_dca_distance_usd / mark * 100 if next_dca_distance_usd is not None else None
    return {
        "takeProfitPct": settings.take_profit * 100,
        "tpPrice": tp_price,
        "tpDistanceUsd": tp_distance_usd,
        "tpDistancePct": tp_distance_pct,
        "expectedPnlAtTp": expected_pnl_at_tp,
        "portfolioValueAtTp": portfolio_value_at_tp,
        "nextDcaPrice": next_dca_price,
        "nextDcaDistanceUsd": next_dca_distance_usd,
        "nextDcaDistancePct": next_dca_distance_pct,
        "nextDcaNumber": dca_count + 1 if next_dca_price else None,
        "unlimitedDca": settings.unlimited_dca,
    }
'''
text = replace_once(text, '\n\ndef _brackets(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:', helper + '\n\ndef _brackets(payload: list[dict[str, Any]], symbol: str) -> list[dict[str, Any]]:', 'backend helper insertion')
old_reconcile = '        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms}); state[key] = st\n'
new_reconcile = '''        st.update({"lastKnownQty": qty, "lastKnownEntry": entry, "leverage": leverage, "updatedAtMs": timestamp_ms})
        account_equity = _f(account.get("totalMarginBalance", account.get("marginBalance", account.get("equity", account.get("totalWalletBalance")))))
        st.update(position_action_preview(row=row, state=st, settings=settings, account_equity=account_equity))
        state[key] = st
'''
text = replace_once(text, old_reconcile, new_reconcile, 'backend reconciliation preview')
backend.write_text(text)

recent = Path("web/components/aster-recent-trades.tsx")
text = recent.read_text()
text = replace_once(text,
    'import { SafeTradingChart, type AirbagChartEvent, type DcaChartLevel, type TradeSelection, type FocusV2Cockpit } from "@/components/trading-chart";',
    'import { SafeTradingChart, type AirbagChartEvent, type DcaChartLevel, type PlannedActionLevel, type TradeSelection, type FocusV2Cockpit } from "@/components/trading-chart";',
    'planned level import')
old_block = '''  const detailNextDca=detailDcaLevels[0] || null;
  const detailMainSide=String(detailAirbag?.mainSide||detail?.selection.side||"").toUpperCase();
  const detailHedgeSide=String(detailAirbag?.hedgeSide||"").toUpperCase();
  const detailFocusV2Cockpit=detail&&String(detail.selection.strategy2Role||"").toUpperCase()==="FOCUS_V2_LONG"&&focusV2Cockpit&&normalizedSymbol(String(focusV2Cockpit.symbol||""))===normalizedSymbol(detail.selection.symbol)?focusV2Cockpit:null;
'''
new_block = '''  const detailNextDca=detailDcaLevels[0] || null;
  const detailMainSide=String(detailAirbag?.mainSide||detail?.selection.side||"").toUpperCase();
  const detailHedgeSide=String(detailAirbag?.hedgeSide||"").toUpperCase();
  const detailRuntime=detail?multiDcaPositions[`${normalizedSymbol(detail.selection.symbol)}|${detailMainSide}`]||null:null;
  const detailNextDcaPrice=finite(detailRuntime?.nextDcaPrice)??finite(detailNextDca?.price);
  const detailNextDcaNumber=finite(detailRuntime?.nextDcaNumber)??finite(detailNextDca?.number)??((detailDcaCount??0)+1);
  const detailNextDcaDistanceUsd=finite(detailRuntime?.nextDcaDistanceUsd);
  const detailNextDcaDistancePct=finite(detailRuntime?.nextDcaDistancePct);
  const detailTpPct=finite(detailRuntime?.takeProfitPct);
  const detailTpPrice=finite(detailRuntime?.tpPrice);
  const detailTpDistanceUsd=finite(detailRuntime?.tpDistanceUsd);
  const detailTpDistancePct=finite(detailRuntime?.tpDistancePct);
  const detailExpectedPnlAtTp=finite(detailRuntime?.expectedPnlAtTp);
  const detailPortfolioAtTp=finite(detailRuntime?.portfolioValueAtTp)??(accountDisplay.equityNumber!==null&&detailExpectedPnlAtTp!==null&&detailPnl!==null?accountDisplay.equityNumber+(detailExpectedPnlAtTp-detailPnl):null);
  const actionDistance=(kind:"DCA"|"TP",usd:number|null,pctValue:number|null)=>{if(usd===null||pctValue===null)return"—";const down=(detailMainSide==="LONG"&&kind==="DCA")||(detailMainSide==="SHORT"&&kind==="TP");return `Nog US$ ${amount(Math.abs(usd))} / ${Math.abs(pctValue).toFixed(2).replace(".",",")}% ${down?"dalen":"stijgen"}`};
  const detailDcaDistanceLabel=actionDistance("DCA",detailNextDcaDistanceUsd,detailNextDcaDistancePct);
  const detailTpDistanceLabel=actionDistance("TP",detailTpDistanceUsd,detailTpDistancePct);
  const detailChartDcaLevels=detailNextDcaPrice&&detailNextDcaPrice>0?[{number:Number(detailNextDcaNumber||1),price:detailNextDcaPrice},...detailDcaLevels.filter(level=>Math.abs(level.price-detailNextDcaPrice)>1e-10)]:detailDcaLevels;
  const detailPlannedLevels:PlannedActionLevel[]=[
    ...(detailNextDcaPrice&&detailNextDcaPrice>0?[{key:"dca" as const,price:detailNextDcaPrice,label:`VOLGENDE ${detailMainSide} DCA · ${money(detailNextDcaPrice)} · ${detailDcaDistanceLabel}`,color:"#ffd166"}]:[]),
    ...(detailTpPrice&&detailTpPrice>0?[{key:"tp" as const,price:detailTpPrice,label:`TP ${detailTpPct!==null?`${detailTpPct.toFixed(2).replace(".",",")}%`:""} · ${money(detailTpPrice)} · ${detailTpDistanceLabel}`,color:"#b978ff"}]:[]),
  ];
  const detailFocusV2Cockpit=detail&&String(detail.selection.strategy2Role||"").toUpperCase()==="FOCUS_V2_LONG"&&focusV2Cockpit&&normalizedSymbol(String(focusV2Cockpit.symbol||""))===normalizedSymbol(detail.selection.symbol)?focusV2Cockpit:null;
'''
text = replace_once(text, old_block, new_block, 'detail preview calculations')
text = replace_once(text, 'dcaLevels={detailDcaLevels} selectedActionId={detail.selectedActionId}', 'dcaLevels={detailChartDcaLevels} plannedActionLevels={detailPlannedLevels} selectedActionId={detail.selectedActionId}', 'chart preview props')
start = text.find('<div className={styles.summary}><div><span>Positie</span>')
end_token = '</div>{detailAirbag&&<section'
end = text.find(end_token, start)
if start < 0 or end < 0:
    raise SystemExit('summary block anchors missing')
summary = '''<div className={styles.summary}><div><span>Positie</span><strong className={detail.status === "OPEN" ? styles.profit : styles.neutral}>{detail.status || "—"}</strong></div><div><span>Entry prijs (gem.)</span><strong>{money(detailAverageEntry)}</strong></div><div><span>{detail.status === "CLOSED" ? "Exit prijs" : "Huidige prijs"}</span><strong>{money(detail.status === "CLOSED" ? detail.exitPrice : detailCurrentPrice)}</strong></div><div><span>{detail.status === "CLOSED" ? "Realized P&L" : "Unrealized P&L"}</span><strong className={(detailPnl ?? 0) >= 0 ? styles.profit : styles.loss}>{money(detailPnl, true)}</strong></div><div><span>Aantal DCA</span><strong>{detailDcaCount === null || detailDcaCount === undefined ? "—" : Math.round(detailDcaCount)}</strong></div><div><span>Volgende {detailMainSide} DCA prijs</span><strong>{detailNextDcaPrice?`${money(detailNextDcaPrice)} · DCA ${Math.round(Number(detailNextDcaNumber||1))}`:"Geen volgende DCA beschikbaar"}</strong></div><div><span>Afstand tot volgende DCA</span><strong>{detailNextDcaPrice?detailDcaDistanceLabel:"Geen volgende DCA beschikbaar"}</strong></div><div><span>Take Profit ingesteld</span><strong>{detailTpPct===null?"—":`${detailTpPct.toFixed(2).replace(".",",")}%`}</strong></div><div><span>TP prijs</span><strong>{money(detailTpPrice)}</strong></div><div><span>Afstand tot TP</span><strong>{detailTpPrice?detailTpDistanceLabel:"—"}</strong></div><div><span>Verwachte winst bij TP</span><strong className={styles.profit}>{money(detailExpectedPnlAtTp,true)}</strong></div><div><span>Portfoliowaarde bij TP</span><strong>{money(detailPortfolioAtTp)}</strong></div>'''
text = text[:start] + summary + text[end + len('</div>'):]
recent.write_text(text)

chart = Path("web/components/trading-chart.tsx")
text = chart.read_text()
text = replace_once(text, 'export type DcaChartLevel = { number: number; price: number };\nexport type AirbagChartEvent', 'export type DcaChartLevel = { number: number; price: number };\nexport type PlannedActionLevel = { key: "dca" | "tp"; price: number; label: string; color?: string };\nexport type AirbagChartEvent', 'planned action type')
text = replace_once(text, 'const EMPTY_DCA_LEVELS: DcaChartLevel[] = [];', 'const EMPTY_DCA_LEVELS: DcaChartLevel[] = [];\nconst EMPTY_PLANNED_LEVELS: PlannedActionLevel[] = [];', 'planned defaults')
text = replace_once(text,
'export function SafeTradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, selectedActionId, airbagEvents = [], cockpit, accountDisplay }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; selectedActionId?: string; airbagEvents?: AirbagChartEvent[]; cockpit?: FocusV2Cockpit|null; accountDisplay?: AsterAccountDisplay | null }) {\n  return <ChartErrorBoundary resetKey={`${selection.exchange}:${selection.id}:${selection.symbol}:${mode}`}><TradingChart selection={selection} mode={mode} focusAtMs={focusAtMs} breakEvenPrice={breakEvenPrice} dcaLevels={dcaLevels} selectedActionId={selectedActionId} airbagEvents={airbagEvents} cockpit={cockpit} accountDisplay={accountDisplay} /></ChartErrorBoundary>;\n}',
'export function SafeTradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, plannedActionLevels = EMPTY_PLANNED_LEVELS, selectedActionId, airbagEvents = [], cockpit, accountDisplay }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; plannedActionLevels?: PlannedActionLevel[]; selectedActionId?: string; airbagEvents?: AirbagChartEvent[]; cockpit?: FocusV2Cockpit|null; accountDisplay?: AsterAccountDisplay | null }) {\n  return <ChartErrorBoundary resetKey={`${selection.exchange}:${selection.id}:${selection.symbol}:${mode}`}><TradingChart selection={selection} mode={mode} focusAtMs={focusAtMs} breakEvenPrice={breakEvenPrice} dcaLevels={dcaLevels} plannedActionLevels={plannedActionLevels} selectedActionId={selectedActionId} airbagEvents={airbagEvents} cockpit={cockpit} accountDisplay={accountDisplay} /></ChartErrorBoundary>;\n}', 'safe chart props')
text = replace_once(text,
'export function TradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, selectedActionId, airbagEvents = [], cockpit, accountDisplay }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; selectedActionId?: string; airbagEvents?: AirbagChartEvent[]; cockpit?: FocusV2Cockpit|null; accountDisplay?: AsterAccountDisplay | null }) {',
'export function TradingChart({ selection, mode = "default", focusAtMs, breakEvenPrice, dcaLevels = EMPTY_DCA_LEVELS, plannedActionLevels = EMPTY_PLANNED_LEVELS, selectedActionId, airbagEvents = [], cockpit, accountDisplay }: { selection: TradeSelection; mode?: TradingChartMode; focusAtMs?: number; breakEvenPrice?: number; dcaLevels?: DcaChartLevel[]; plannedActionLevels?: PlannedActionLevel[]; selectedActionId?: string; airbagEvents?: AirbagChartEvent[]; cockpit?: FocusV2Cockpit|null; accountDisplay?: AsterAccountDisplay | null }) {', 'chart props')
text = replace_once(text, '  const dcaLevelsSignature=useMemo(()=>dcaLevels.map(level=>`${Number(level.number)}:${Number(level.price)}`).join("|"),[dcaLevels]);', '  const dcaLevelsSignature=useMemo(()=>dcaLevels.map(level=>`${Number(level.number)}:${Number(level.price)}`).join("|"),[dcaLevels]);\n  const plannedActionLevelsSignature=useMemo(()=>plannedActionLevels.map(level=>`${level.key}:${Number(level.price)}:${level.label}`).join("|"),[plannedActionLevels]);', 'planned signature')
text = text.replace('axisLabelVisible:true, title:next?`VOLGENDE ${selection.side.toUpperCase()} DCA`:`DCA ${Math.round(Number(level.number))}`', 'axisLabelVisible:false, title:""', 1)
needle = '      validDcaLevels.forEach((level,index)=>{\n        const next=index===0;\n        priceSeries.createPriceLine({ price:Number(level.price), color:next?"#ffd166":"#496985", lineWidth:next?2:1, lineStyle:next?0:2, axisLabelVisible:false, title:"" });\n      });\n'
if needle not in text:
    raise SystemExit('chart DCA price line anchor missing')
text = text.replace(needle, needle + '      plannedActionLevels.filter(level=>level.key==="tp"&&Number.isFinite(level.price)&&level.price>0).forEach(level=>priceSeries.createPriceLine({price:Number(level.price),color:level.color||"#b978ff",lineWidth:2,lineStyle:0,axisLabelVisible:false,title:""}));\n', 1)
text = replace_once(text, '  },[datasetVersion,chartType,activeIndicators,selection,tradeEventsSignature,skin,mode,focusAtMs,breakEvenPrice,dcaLevelsSignature,selectedActionId,airbagEventsSignature,focusV2]);', '  },[datasetVersion,chartType,activeIndicators,selection,tradeEventsSignature,skin,mode,focusAtMs,breakEvenPrice,dcaLevelsSignature,plannedActionLevelsSignature,selectedActionId,airbagEventsSignature,focusV2]);', 'chart rebuild deps')
old_sync = '  syncFocusLevelsRef.current=()=>{if(!focusV2||!priceSeriesRef.current||!containerRef.current){setFocusLevelY({});return}const height=Math.max(1,containerRef.current.clientHeight);const real:Record<string,number>={};for(const row of focusLevels){const y=priceSeriesRef.current.priceToCoordinate(row.price);if(y!==null&&Number.isFinite(Number(y)))real[row.key]=Number(y)}const labels=layoutFocusLabelYs(real,height,24,16);const next:Record<string,{realY:number;labelY:number}>={};for(const [key,realY] of Object.entries(real)){next[key]={realY,labelY:Number(labels[key]??realY)}}setFocusLevelY(next)};\n  useEffect(()=>{if(!focusV2)return;const id=requestAnimationFrame(()=>syncFocusLevelsRef.current());return()=>cancelAnimationFrame(id)},[focusV2,focusLevels,candles]);'
new_sync = '  const plannedOverlayLevels=useMemo(()=>mode==="aster-detail"&&!focusV2?plannedActionLevels.filter(level=>Number.isFinite(level.price)&&level.price>0).map(level=>({...level,color:level.color||(level.key==="dca"?"#ffd166":"#b978ff")})):[] as Array<{key:string;price:number;label:string;color:string}>,[mode,focusV2,plannedActionLevelsSignature]);\n  const chartOverlayLevels=focusV2?focusLevels:plannedOverlayLevels;\n  syncFocusLevelsRef.current=()=>{if(!chartOverlayLevels.length||!priceSeriesRef.current||!containerRef.current){setFocusLevelY({});return}const height=Math.max(1,containerRef.current.clientHeight);const real:Record<string,number>={};for(const row of chartOverlayLevels){const y=priceSeriesRef.current.priceToCoordinate(row.price);if(y!==null&&Number.isFinite(Number(y)))real[row.key]=Number(y)}const labels=layoutFocusLabelYs(real,height,24,16);const next:Record<string,{realY:number;labelY:number}>={};for(const [key,realY] of Object.entries(real)){next[key]={realY,labelY:Number(labels[key]??realY)}}setFocusLevelY(next)};\n  useEffect(()=>{if(!chartOverlayLevels.length)return;const id=requestAnimationFrame(()=>syncFocusLevelsRef.current());return()=>cancelAnimationFrame(id)},[focusV2,focusLevels,plannedActionLevelsSignature,candles]);'
text = replace_once(text, old_sync, new_sync, 'chart overlay sync')
text = replace_once(text, '{focusV2&&focusLevels.length>0&&<div className="focus-level-overlay" aria-hidden="true" data-focus-label-overlay="true">{focusLevels.map(level=>', '{chartOverlayLevels.length>0&&<div className="focus-level-overlay" aria-hidden="true" data-focus-label-overlay="true">{chartOverlayLevels.map(level=>', 'planned overlay render')
chart.write_text(text)

Path("cloud_api/test_strategy2_action_preview.py").write_text('''from aster_multi_bb import MultiBbConfig, position_action_preview\n\n\ndef cfg(**overrides):\n    base = dict(universeTopN=10, maximumPositions=2, longSlots=1, shortSlots=1, minimumLeverage=50, entryNotionalUsd=250, dcaDistance=.05, dcaMarginUsd=2, maxDca=3, takeProfit=.19)\n    base.update(overrides)\n    return MultiBbConfig.from_mapping(base)\n\n\ndef row(side, entry, mark, qty=2):\n    return {"positionSide": side, "entryPrice": entry, "markPrice": mark, "positionAmt": qty}\n\n\ndef test_long_preview_uses_real_19_percent_tp_and_portfolio_delta():\n    preview = position_action_preview(row=row("LONG",100,105), state={"dcaCount":0,"lastBotFillPrice":100}, settings=cfg(), account_equity=161.65)\n    assert preview["takeProfitPct"] == 19\n    assert preview["tpPrice"] == 119\n    assert preview["nextDcaPrice"] == 95\n    assert round(preview["expectedPnlAtTp"], 8) == 38\n    assert round(preview["portfolioValueAtTp"], 8) == 189.65\n\n\ndef test_short_preview_reverses_dca_and_tp_direction():\n    preview = position_action_preview(row=row("SHORT",100,95), state={"dcaCount":0,"lastBotFillPrice":100}, settings=cfg())\n    assert preview["tpPrice"] == 81\n    assert preview["nextDcaPrice"] == 105\n    assert preview["tpDistanceUsd"] == 14\n    assert preview["nextDcaDistanceUsd"] == 10\n\n\ndef test_normal_dca_cap_removes_next_level():\n    preview = position_action_preview(row=row("LONG",100,100), state={"dcaCount":3,"lastBotFillPrice":90}, settings=cfg())\n    assert preview["nextDcaPrice"] is None\n    assert preview["nextDcaDistanceUsd"] is None\n\n\ndef test_unlimited_dca_keeps_next_level_after_many_fills():\n    preview = position_action_preview(row=row("LONG",100,90), state={"dcaCount":99,"lastBotFillPrice":90}, settings=cfg(unlimitedDca=True))\n    assert preview["nextDcaPrice"] == 85.5\n    assert preview["nextDcaNumber"] == 100\n''')
print('Strategy 2 action preview patch applied')
