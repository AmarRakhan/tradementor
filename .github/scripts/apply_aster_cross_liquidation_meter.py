from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    if old not in text:
        raise SystemExit(f"expected block not found in {path}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))


replace_once(
    "cloud_api/aster_state.py",
    "from typing import Any\n",
    "from typing import Any\n\nfrom aster_cross_risk import cross_account_risk\n",
)
replace_once(
    "cloud_api/aster_state.py",
    "    active = [row for row in positions if abs(_number(row.get(\"positionAmt\"))) > 0]\n    active_trade_capital = sum(\n",
    "    active = [row for row in positions if abs(_number(row.get(\"positionAmt\"))) > 0]\n    cross_risk = cross_account_risk(account, positions)\n    active_trade_capital = sum(\n",
)
replace_once(
    "cloud_api/aster_state.py",
    "        \"maintenanceMargin\": maintenance,\n        \"marginRatio\": maintenance / equity if equity > 0 else (1.0 if active else 0.0),\n",
    "        \"maintenanceMargin\": maintenance,\n        **cross_risk,\n        # Backwards-compatible ratio; authoritative new clients consume liquidationRiskPct/source.\n        \"marginRatio\": cross_risk[\"liquidationRiskPct\"] / 100.0,\n",
)
replace_once(
    "cloud_api/aster_state.py",
    "                \"maintenanceMargin\": \"totalMaintMargin\",\n                \"positionUnrealizedPnl\": \"unRealizedProfit\",\n",
    "                \"maintenanceMargin\": \"totalMaintMargin\",\n                \"marginBalance\": \"totalMarginBalance\",\n                \"positionUnrealizedPnl\": \"unRealizedProfit\",\n",
)
replace_once(
    "cloud_api/aster_state.py",
    "                \"marginRatio\": \"totalMaintMargin / totalMarginBalance\",\n",
    "                \"liquidationRiskPct\": \"Aster account margin ratio when supplied; otherwise totalMaintMargin / totalMarginBalance * 100\",\n                \"maintenanceMarginPct\": \"totalMaintMargin / gross cross notional * 100\",\n                \"marginRatio\": \"liquidationRiskPct / 100 (legacy alias)\",\n",
)
replace_once(
    "cloud_api/aster_state.py",
    "            \"dataSource\": \"ASTER_API\",\n            \"leverage\": max(1, int(_number(row.get(\"leverage\")) or 1)),\n",
    "            \"dataSource\": \"ASTER_API\",\n            \"marginType\": str(row.get(\"marginType\", \"isolated\" if row.get(\"isolated\") is True else \"cross\")).lower(),\n            \"leverage\": max(1, int(_number(row.get(\"leverage\")) or 1)),\n",
)

replace_once(
    "web/app/page.tsx",
    "    riskLabel = \"MAINTENANCE\";\n    riskNumber = accountDataAvailable ? asNumber(data.marginRatio) * 100 : null;\n",
    "    riskLabel = \"MAINTENANCE MARGIN\";\n    riskNumber = accountDataAvailable ? (asterAccountDisplay?.maintenanceMarginPercent ?? null) : null;\n",
)
replace_once(
    "web/app/page.tsx",
    "    riskDetail: riskNumber === null ? \"Nog geen betrouwbare waarde\" : exchange === \"aster\" ? \"0% is ruim · 100% is liquidatiegrens\" : \"Rechtstreeks uit account- en positiedata\",\n",
    "    riskDetail: riskNumber === null ? \"Nog geen betrouwbare waarde\" : exchange === \"aster\" ? (asterAccountDisplay?.maintenanceDetail ?? \"Gewogen Aster maintenance-rate\") : \"Rechtstreeks uit account- en positiedata\",\n",
)
replace_once(
    "web/app/page.tsx",
    "<small>{display?.liquidationDetail ?? \"Geen betrouwbare Aster margin ratio\"}</small>",
    "<small>{display?.liquidationDetail ?? \"Geen bevestigde cross-account liquidatieratio\"}{display?.positionCountIncluded !== null && display?.positionCountIncluded !== undefined ? ` · ${display.positionCountIncluded} posities` : \"\"}</small>",
)

css = Path("web/app/globals.css")
style = """

/* Aster cross-risk meters: compact, distinct maintenance vs liquidation gauges. */
.hero-panel .risk-orbits{gap:10px;align-items:center}
.hero-panel .risk-orbits .risk-orbit{width:152px;height:152px;min-width:152px;min-height:152px}
.hero-panel .risk-orbits .risk-core strong{font-size:34px}
.hero-panel .risk-orbits .risk-core small{max-width:118px;font-size:7px;line-height:1.35}
.hero-panel .risk-orbits .liquidation-risk{transform:scale(1.03)}
@media(max-width:700px){.hero-panel .risk-orbits{gap:8px}.hero-panel .risk-orbits .risk-orbit{width:136px;height:136px;min-width:136px;min-height:136px}.hero-panel .risk-orbits .risk-core strong{font-size:30px}.hero-panel .risk-orbits .risk-core small{max-width:108px;font-size:6.5px}}
"""
if "Aster cross-risk meters: compact" not in css.read_text():
    css.write_text(css.read_text() + style)
