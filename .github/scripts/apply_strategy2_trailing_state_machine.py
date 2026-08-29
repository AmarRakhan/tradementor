from pathlib import Path


def replace_once(path: str, old: str, new: str) -> None:
    p = Path(path)
    text = p.read_text()
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"{path}: expected exactly one match, got {count}: {old[:100]!r}")
    p.write_text(text.replace(old, new, 1))


# Route Focus 2.0 live execution to the deterministic trailing state-machine.
replace_once(
    "cloud_api/aster_strategy2_focus_live.py",
    "from aster_strategy2_focus_v2 import run_focus_v2_live_step",
    "from aster_strategy2_focus_trailing import run_focus_v2_live_step",
)

# Add an explicit, persisted hedge-release setting while preserving the legacy
# recovery field for existing saved configs and old cycles.
replace_once(
    "cloud_api/aster_strategy2.py",
    "    focus_v2_recovery_rebound_pct: float = 0.003\n    focus_v2_portfolio_recovery_ratio: float = 0.99",
    "    focus_v2_recovery_rebound_pct: float = 0.003\n    # State-machine v4: distance from the frozen next-DCA at which the temporary hedge is fully released.\n    focus_v2_hedge_release_distance_pct: float = 0.0035\n    focus_v2_portfolio_recovery_ratio: float = 0.99",
)
replace_once(
    "cloud_api/aster_strategy2.py",
    "            focus_v2_recovery_rebound_pct=f(\"focusV2RecoveryReboundPct\",0.003),\n            focus_v2_portfolio_recovery_ratio=f(\"focusV2PortfolioRecoveryRatio\",0.99),",
    "            focus_v2_recovery_rebound_pct=f(\"focusV2RecoveryReboundPct\",0.003),\n            focus_v2_hedge_release_distance_pct=f(\"focusV2HedgeReleaseDistancePct\", f(\"focusV2RecoveryReboundPct\",0.0035)),\n            focus_v2_portfolio_recovery_ratio=f(\"focusV2PortfolioRecoveryRatio\",0.99),",
)
replace_once(
    "cloud_api/aster_strategy2.py",
    "            if not 0 < self.focus_v2_recovery_rebound_pct < .25: raise ValueError(\"Focus 2.0 recovery rebound is ongeldig\")\n            if not .5 <= self.focus_v2_portfolio_recovery_ratio <= 1.05:",
    "            if not 0 < self.focus_v2_recovery_rebound_pct < .25: raise ValueError(\"Focus 2.0 recovery rebound is ongeldig\")\n            if not 0 < self.focus_v2_hedge_release_distance_pct < .25: raise ValueError(\"Focus 2.0 hedge release distance is ongeldig\")\n            if not .5 <= self.focus_v2_portfolio_recovery_ratio <= 1.05:",
)
replace_once(
    "cloud_api/aster_strategy2.py",
    '"focusV2MaxHedgeRatio":self.focus_v2_max_hedge_ratio,"focusV2ReleaseRatio":self.focus_v2_release_ratio,"focusV2RecoveryReboundPct":self.focus_v2_recovery_rebound_pct,\n            "focusV2PortfolioRecoveryRatio":self.focus_v2_portfolio_recovery_ratio,',
    '"focusV2MaxHedgeRatio":self.focus_v2_max_hedge_ratio,"focusV2ReleaseRatio":self.focus_v2_release_ratio,"focusV2RecoveryReboundPct":self.focus_v2_recovery_rebound_pct,\n            "focusV2HedgeReleaseDistancePct":self.focus_v2_hedge_release_distance_pct,"focusV2PortfolioRecoveryRatio":self.focus_v2_portfolio_recovery_ratio,',
)

# Wizard defaults and persisted mapping. The existing internal UI variable
# `focusV2Rebound` becomes the user-facing hedge-release distance to minimize
# migration surface; the server receives a new explicit key as well as the old
# compatibility key.
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'focusDcaDistance:"2"',
    'focusDcaDistance:"0.30"',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'focusV2Rebound:"0.3"',
    'focusV2Rebound:"0.35"',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'focusV2ProfitHarvest:"10"',
    'focusV2ProfitHarvest:"5"',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'focusV2Rebound:String(Number(x.focusV2RecoveryReboundPct??.003)*100)',
    'focusV2Rebound:String(Number(x.focusV2HedgeReleaseDistancePct??x.focusV2RecoveryReboundPct??.0035)*100)',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'focusV2RecoveryReboundPct:num(v.focusV2Rebound)/100,focusV2PortfolioRecoveryRatio:',
    'focusV2RecoveryReboundPct:num(v.focusV2Rebound)/100,focusV2HedgeReleaseDistancePct:num(v.focusV2Rebound)/100,focusV2PortfolioRecoveryRatio:',
)

# Focus 2.0 copy must describe the actual v4 mechanics rather than the removed
# initial protected pair / Bollinger recovery model.
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'help:"Focus 2.0 beheert één beschermde LONG-cyclus. De SHORT is alleen de tijdelijke airbag tijdens daling."',
    'help:"Focus 2.0 start primary-only. De tegengestelde hedge wordt pas tegelijk met een geldige trailing-DCA geopend en na de ingestelde release-afstand volledig gesloten."',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'help:"Kies alleen hoeveel LONG-notional de cycle start. Focus 2.0 opent daarna automatisch de beschermende SHORT volgens het hedge-target."',
    'help:"Kies de startnotional. De cycle start zonder hedge; bescherming wordt pas bij de eerste geldige DCA-retracement geopend."',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'help:"Bij iedere geldige daling koopt Focus 2.0 LONG bij, leest daarna Aster opnieuw uit en vult de SHORT direct aan tot het nieuwe protection-target."',
    'help:"De DCA trailt continu op de ingestelde afstand. Bij raken: DCA + tijdelijke hedge. Tijdens de hedge wordt de volgende DCA-reference bevroren."',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'label="DCA-afstand (%)"',
    'label="Trailing DCA-afstand (%)"',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'title:"4 · Bescherming & herstel",help:"Tijdens de daling groeit de SHORT mee. Bij herstel zet Focus 2.0 eerst een SHORT-stop op Aster klaar. Daarna gaat de actieve SHORT volledig weg. Bij terugval komt de hedge automatisch terug."',
    'title:"4 · Tijdelijke hedge & release",help:"Na een DCA blijft de volgende DCA-reference frozen. Zodra de afstand tot die reference de ingestelde release bereikt, wordt 100% van de tijdelijke hedge reduce-only gesloten en hervat trailing."',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'label="Herstel vanaf recente low (%)"',
    'label="Hedge release-afstand (%)"',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    '<Field label="Re-hedge terugval (%)" value={v.focusV2Rehedge} set={x=>setV({...v,focusV2Rehedge:x})}/><small>Bij herstel: eerst SHORT-stop op Aster → daarna actieve SHORT volledig weg. Bij terugval komt de hedge automatisch terug.</small>',
    '<small>DCA actief → reference frozen. Release-afstand bereikt → hedge 100% reduce-only weg → trailing DCA hervat. Geen recovery/Bollinger-trigger.</small>',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    '<Toggle label="5m Bollinger-middle extra bevestiging" value={v.focusV2RequireMiddle} set={x=>setV({...v,focusV2RequireMiddle:x})}/>',
    '<small>Hedge-release gebruikt uitsluitend de harde configureerbare afstand tot de frozen DCA-reference.</small>',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    'help:"Bij de instelbare netto winsttrigger wordt alleen het ingestelde winstbedrag afgeroomd. De resterende LONG en de cycle blijven actief."',
    'help:"Bij de instelbare open-PnL winsttrigger wordt alleen het ingestelde bedrag uit de primary positie afgeroomd. DCA/trailing state blijft exact intact."',
)
replace_once(
    "web/components/aster-strategy2-maker.tsx",
    '<small>Na een succesvolle harvest wordt een nieuwe baseline gezet. Daarna telt Focus 2.0 opnieuw naar de volgende winsttrigger.</small>',
    '<small>Na partial profit blijft de trailing/frozen DCA-state ongewijzigd. Zodra open PnL opnieuw de trigger bereikt, wordt opnieuw het ingestelde bedrag afgeroomd.</small>',
)

print("Strategy 2 trailing state-machine integration patch applied")
