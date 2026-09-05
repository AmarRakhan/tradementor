from pathlib import Path

root = Path(__file__).resolve().parents[1]

# 1) Match the reference number formatting and percentage semantics.
component = root / "web/components/portfolio-impact-battle.tsx"
text = component.read_text()
text = text.replace('return `US$ ${sign}${money.format(Math.abs(normalized))}`;', 'return `$${sign}${money.format(Math.abs(normalized))}`;')
text = text.replace('  const longPercent = snapshot.longExposure > 0 ? snapshot.longPnl / snapshot.longExposure * 100 : 0;\n  const shortPercent = snapshot.shortExposure > 0 ? snapshot.shortPnl / snapshot.shortExposure * 100 : 0;', '  const equityBasis = equity && Math.abs(equity) > 0.01 ? Math.abs(equity) : 0;\n  const longPercent = equityBasis ? snapshot.longPnl / equityBasis * 100 : 0;\n  const shortPercent = equityBasis ? snapshot.shortPnl / equityBasis * 100 : 0;')
component.write_text(text)

# 2) Put the hero battle card above the metric strip on Aster, as in the approved reference.
page = root / "web/app/page.tsx"
text = page.read_text()
metric_start = '      {!positionsOnly && <section className="metric-strip" aria-label="Portefeuilleoverzicht">'
battle_start = '      {!positionsOnly && (destination === "aster" ? <PortfolioImpactBattle'
if metric_start in text and battle_start in text and text.index(metric_start) < text.index(battle_start):
    battle_end = '      </section>)}\n'
    bs = text.index(battle_start)
    be = text.index(battle_end, bs) + len(battle_end)
    battle = text[bs:be]
    text = text[:bs] + text[be:]
    ms = text.index(metric_start)
    text = text[:ms] + battle + '\n' + text[ms:]
page.write_text(text)

# 3) Tighten proportions to the reference card ratio and mobile rhythm.
css = root / "web/components/portfolio-impact-battle.module.css"
text = css.read_text()
text = text.replace('overflow:hidden;min-height:268px;margin:18px 0 20px;', 'overflow:hidden;aspect-ratio:2.328/1;min-height:0;margin:18px 0 20px;')
text = text.replace('@media(max-width:700px){.card{min-height:258px;margin:14px 0 16px;border-radius:19px}.sidePanel{top:13px;width:29%;min-width:0;padding:11px 10px 10px;border-radius:13px}.longPanel{left:10px}.shortPanel{right:10px}.sideTitle{font-size:12px;gap:4px;margin-bottom:7px}.sideTitle i{font-size:15px}.sidePanel small{font-size:8.5px}.sidePanel>strong{font-size:15px;white-space:nowrap}.sidePanel em{font-size:9px}.sidePanel b{font-size:11px;white-space:nowrap}.divider{margin:7px 0 6px}.positionCount{margin-top:6px;font-size:9px}.centerPanel{top:10px;width:42%;padding:6px 7px 10px}.centerTitle{font-size:8px;letter-spacing:.07em}.centerTitle i{width:5px;height:5px}.centerPanel>strong{font-size:21px;white-space:nowrap}.centerPanel>span{font-size:10px}.cinematicBase,.bullLayer{inset:10% -13% 14%;background-position:center 55%;background-size:cover}.impact{top:47%;width:48px;height:48px}.battleFooter{left:10px;right:10px;bottom:9px;padding-top:21px}.status{font-size:10px;letter-spacing:.045em}.balanceRow{grid-template-columns:52px 1fr 52px;gap:6px;margin-top:6px}.share strong{font-size:15px}.share small{font-size:6px}.balanceTrack{height:13px}}', '@media(max-width:700px){.card{aspect-ratio:2.30/1;min-height:0;margin:12px 0 14px;border-radius:18px}.sidePanel{top:8px;width:27.5%;min-width:0;padding:7px 7px 6px;border-radius:11px}.longPanel{left:9px}.shortPanel{right:9px}.sideTitle{font-size:10px;gap:3px;margin-bottom:4px}.sideTitle i{font-size:12px}.sidePanel small{font-size:7px}.sidePanel>strong{font-size:12px;white-space:nowrap}.sidePanel em{font-size:7.5px}.sidePanel b{font-size:9px;white-space:nowrap}.divider{margin:4px 0}.positionCount{margin-top:4px;font-size:7.5px}.centerPanel{top:6px;width:41%;padding:4px 5px 6px}.centerTitle{font-size:7px;letter-spacing:.06em}.centerTitle i{width:4px;height:4px}.centerPanel>strong{font-size:18px;white-space:nowrap}.centerPanel>span{font-size:8px}.cinematicBase,.bullLayer{inset:10% -10% 12%;background-position:center 54%;background-size:cover}.impact{top:48%;width:38px;height:38px}.battleFooter{left:8px;right:8px;bottom:6px;padding-top:14px}.status{font-size:8px;letter-spacing:.035em}.balanceRow{grid-template-columns:43px 1fr 43px;gap:5px;margin-top:4px}.share strong{font-size:12px}.share small{font-size:5px}.balanceTrack{height:10px}.longFill,.shortFill{top:1px;bottom:1px}}')
text = text.replace('@media(max-width:380px){.card{min-height:248px}', '@media(max-width:380px){.card{aspect-ratio:2.24/1;min-height:0}')
css.write_text(text)
print("Portfolio Impact visual parity refinement applied")
