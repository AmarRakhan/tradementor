from pathlib import Path

chart = Path('web/components/trading-chart.tsx')
src = chart.read_text(encoding='utf-8')

# Add pure label-layout helper import.
anchor = 'import type { AsterAccountDisplay } from "@/lib/aster-account-display";\n'
addition = 'import { layoutFocusLabelYs } from "@/lib/focus-chart-label-layout.mjs";\n'
assert anchor in src
if addition not in src:
    src = src.replace(anchor, anchor + addition)

# State now stores the true price-line Y and collision-resolved label Y separately.
old_state = '  const [focusLevelY, setFocusLevelY] = useState<Record<string, number>>({});\n'
new_state = '  const [focusLevelY, setFocusLevelY] = useState<Record<string, {realY:number;labelY:number}>>({});\n'
assert old_state in src
src = src.replace(old_state, new_state)

old_sync = '''  syncFocusLevelsRef.current=()=>{if(!focusV2||!priceSeriesRef.current||!containerRef.current){setFocusLevelY({});return}const height=Math.max(1,containerRef.current.clientHeight),minGap=22,pad=12;const points=focusLevels.map(row=>{const y=priceSeriesRef.current!.priceToCoordinate(row.price);return{key:row.key,y:y===null?NaN:Number(y)}}).filter(point=>Number.isFinite(point.y)).sort((a,b)=>a.y-b.y);for(let i=1;i<points.length;i++)points[i].y=Math.max(points[i].y,points[i-1].y+minGap);if(points.length){const overflow=points.at(-1)!.y-(height-pad);if(overflow>0)for(const point of points)point.y-=overflow;const under=pad-points[0].y;if(under>0)for(const point of points)point.y+=under}const next:Record<string,number>={};for(const point of points)next[point.key]=point.y;setFocusLevelY(next)};\n'''
new_sync = '''  syncFocusLevelsRef.current=()=>{if(!focusV2||!priceSeriesRef.current||!containerRef.current){setFocusLevelY({});return}const height=Math.max(1,containerRef.current.clientHeight);const real:Record<string,number>={};for(const row of focusLevels){const y=priceSeriesRef.current.priceToCoordinate(row.price);if(y!==null&&Number.isFinite(Number(y)))real[row.key]=Number(y)}const labels=layoutFocusLabelYs(real,height,24,16);const next:Record<string,{realY:number;labelY:number}>={};for(const [key,realY] of Object.entries(real)){next[key]={realY,labelY:Number(labels[key]??realY)}}setFocusLevelY(next)};\n'''
assert old_sync in src, 'focus label collision block changed unexpectedly'
src = src.replace(old_sync, new_sync)

old_overlay = '''{focusV2&&focusLevels.length>0&&<div className="focus-level-overlay" aria-hidden="true">{focusLevels.map(level=>Number.isFinite(focusLevelY[level.key])?<div key={level.key} className={`focus-level-segment ${level.key}`} data-focus-chart-label={level.key} style={{top:`${focusLevelY[level.key]}px`,color:level.color,left:"12px",right:"88px",maxWidth:"none",overflow:"hidden"}}><i style={{minWidth:0,flex:"1 1 auto"}}/><span style={{marginLeft:"8px",flex:"0 0 auto",whiteSpace:"nowrap",maxWidth:"100%"}}>{level.label}</span></div>:null)}</div>}'''
new_overlay = '''{focusV2&&focusLevels.length>0&&<div className="focus-level-overlay" aria-hidden="true" data-focus-label-overlay="true">{focusLevels.map(level=>{const layout=focusLevelY[level.key];if(!layout||!Number.isFinite(layout.realY)||!Number.isFinite(layout.labelY))return null;const delta=layout.labelY-layout.realY;return <div key={level.key} className={`focus-level-segment ${level.key}`} data-focus-chart-label={level.key} style={{top:`${layout.realY}px`,color:level.color}}><i className="focus-price-line"/><b className="focus-label-leader" aria-hidden="true" style={{display:Math.abs(delta)>2?"block":"none",top:`${Math.min(0,delta)}px`,height:`${Math.abs(delta)}px`}}/><span className="focus-line-label" style={{top:`${delta}px`}}>{level.label}</span></div>})}</div>}'''
assert old_overlay in src, 'current short-label overlay block not found'
src = src.replace(old_overlay, new_overlay)

chart.write_text(src, encoding='utf-8')

layout = Path('web/lib/focus-chart-label-layout.mjs')
layout.write_text('''/** Collision-resolve chart labels without moving their underlying price lines. */\nexport function layoutFocusLabelYs(realByKey, height, minGap = 24, pad = 16) {\n  const h = Math.max(1, Number(height) || 1);\n  const gap = Math.max(1, Number(minGap) || 24);\n  const edge = Math.max(0, Number(pad) || 0);\n  const points = Object.entries(realByKey || {})\n    .map(([key, y]) => ({ key, realY: Number(y), labelY: Number(y) }))\n    .filter((p) => Number.isFinite(p.realY))\n    .sort((a, b) => a.realY - b.realY);\n  if (!points.length) return {};\n\n  // Forward pass guarantees the minimum vertical separation.\n  points[0].labelY = Math.max(edge, points[0].labelY);\n  for (let i = 1; i < points.length; i++) {\n    points[i].labelY = Math.max(points[i].realY, points[i - 1].labelY + gap);\n  }\n\n  // Shift the group upward if it would leave the bottom edge.\n  const maxY = Math.max(edge, h - edge);\n  const overflow = points[points.length - 1].labelY - maxY;\n  if (overflow > 0) for (const p of points) p.labelY -= overflow;\n\n  // Backward pass preserves spacing after clamping the bottom.\n  for (let i = points.length - 2; i >= 0; i--) {\n    points[i].labelY = Math.min(points[i].labelY, points[i + 1].labelY - gap);\n  }\n\n  // If the whole cluster is too high, move it down as one unit.\n  const underflow = edge - points[0].labelY;\n  if (underflow > 0) for (const p of points) p.labelY += underflow;\n\n  const result = {};\n  for (const p of points) result[p.key] = Math.max(edge, Math.min(maxY, p.labelY));\n  return result;\n}\n''', encoding='utf-8')

css = Path('web/app/globals.css')
css_src = css.read_text(encoding='utf-8')
marker = '/* focus-v7-definitive-chart-labels */'
if marker not in css_src:
    css_src += '''\n\n/* focus-v7-definitive-chart-labels */\n.aster-detail-chart .chart-stage{position:relative;overflow:hidden}\n.aster-detail-chart .focus-level-overlay{position:absolute;inset:0;z-index:8;pointer-events:none;overflow:hidden}\n.aster-detail-chart .focus-level-segment{position:absolute;left:12px;right:92px;height:0;overflow:visible;pointer-events:none}\n.aster-detail-chart .focus-price-line{position:absolute;left:52%;right:0;top:-1px;height:2px;min-width:18px;border-radius:999px;background:currentColor;box-shadow:0 0 8px color-mix(in srgb,currentColor 35%,transparent);opacity:.9}\n.aster-detail-chart .focus-line-label{position:absolute;right:0;top:0;transform:translateY(-50%);display:block;max-width:min(190px,62vw);padding:4px 8px;border:1px solid color-mix(in srgb,currentColor 72%,transparent);border-radius:999px;background:rgba(3,13,22,.94);box-shadow:0 4px 14px rgba(0,0,0,.38);color:currentColor;font-size:10px;font-weight:900;line-height:1.1;letter-spacing:.015em;white-space:nowrap;overflow:hidden;text-overflow:ellipsis}\n.aster-detail-chart .focus-label-leader{position:absolute;right:10px;width:0;border-right:1px dashed currentColor;opacity:.78}\n@media(max-width:500px){.aster-detail-chart .focus-level-segment{left:8px;right:92px}.aster-detail-chart .focus-price-line{left:42%}.aster-detail-chart .focus-line-label{max-width:158px;padding:4px 7px;font-size:9px;letter-spacing:0}}\n@media(min-width:501px){.aster-detail-chart .focus-line-label{max-width:220px}}\n'''
css.write_text(css_src, encoding='utf-8')

print('patched definitive Strategy-2 chart labels; backend untouched')
