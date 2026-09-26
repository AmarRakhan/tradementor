from pathlib import Path

# Build 438: reporting-only repair for daily portfolio performance.
# No trading/order/hedge execution files are touched.

# 1) Pure portfolio-performance helpers.
p = Path("cloud_api/portfolio_growth.py")
s = p.read_text(encoding="utf-8")
s = s.replace(
    "from datetime import datetime, timezone\n",
    "from datetime import date, datetime, time as datetime_time, timedelta, timezone\n",
)
if "from zoneinfo import ZoneInfo\n" not in s:
    s = s.replace(
        "from typing import Any, Iterable\n",
        "from typing import Any, Iterable\nfrom zoneinfo import ZoneInfo\n",
    )
s = s.replace(
    "PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION = 2",
    "PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION = 3",
)

marker = "\ndef daily_return_percentage("
if "def historical_day_windows(" not in s:
    helper = r'''

def historical_day_windows(
    candles: Iterable[dict[str, Any]], *, timezone_name: str,
    current_date: str, max_days: int = 14,
    boundary_tolerance_minutes: int = 90,
) -> list[dict[str, Any]]:
    """Return only completed local days with reliable start/end equity coverage.

    Partial days are excluded from the multi-day average instead of being
    presented as complete daily returns.
    """
    if max_days < 1:
        return []
    zone = ZoneInfo(str(timezone_name))
    today = date.fromisoformat(str(current_date))
    tolerance_ms = max(0, int(boundary_tolerance_minutes)) * 60_000
    grouped: dict[date, dict[str, Any]] = {}

    for row in candles:
        if not isinstance(row, dict):
            continue
        try:
            first_ms = int(_finite(row.get("firstSampleAtMs", row.get("atMs", 0))))
            last_ms = int(_finite(row.get("sourceAtMs", row.get("lastSampleAtMs", row.get("atMs", 0)))))
            opened = _finite(row.get("open", 0))
            closed = _finite(row.get("close", 0))
        except ValueError:
            continue
        if first_ms <= 0 or last_ms < first_ms or opened <= 0 or closed <= 0:
            continue
        first_local = datetime.fromtimestamp(first_ms / 1000, tz=timezone.utc).astimezone(zone)
        last_local = datetime.fromtimestamp(last_ms / 1000, tz=timezone.utc).astimezone(zone)
        if first_local.date() != last_local.date() or first_local.date() >= today:
            continue
        day = first_local.date()
        bucket = grouped.setdefault(day, {
            "date": day.isoformat(),
            "startAtMs": first_ms,
            "endAtMs": last_ms,
            "startEquity": opened,
            "endEquity": closed,
        })
        if first_ms < int(bucket["startAtMs"]):
            bucket["startAtMs"] = first_ms
            bucket["startEquity"] = opened
        if last_ms > int(bucket["endAtMs"]):
            bucket["endAtMs"] = last_ms
            bucket["endEquity"] = closed

    reliable: list[dict[str, Any]] = []
    for day in sorted(grouped):
        row = grouped[day]
        day_start = datetime.combine(day, datetime_time.min, tzinfo=zone)
        next_start = datetime.combine(day + timedelta(days=1), datetime_time.min, tzinfo=zone)
        day_start_ms = int(day_start.astimezone(timezone.utc).timestamp() * 1000)
        day_end_ms = int(next_start.astimezone(timezone.utc).timestamp() * 1000)
        if int(row["startAtMs"]) - day_start_ms > tolerance_ms:
            continue
        if day_end_ms - int(row["endAtMs"]) > tolerance_ms:
            continue
        if int(row["endAtMs"]) <= int(row["startAtMs"]):
            continue
        reliable.append(dict(row))
    return reliable[-int(max_days):]
'''
    if marker not in s:
        raise SystemExit("daily_return_percentage anchor missing")
    s = s.replace(marker, helper + marker, 1)
p.write_text(s, encoding="utf-8")

# 2) Backend migration: reconstruct completed reliable days once.
p = Path("cloud_api/main.py")
s = p.read_text(encoding="utf-8")
old_import = "from portfolio_growth import PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION, PORTFOLIO_GROWTH_START_DATE, average_daily_return, daily_return_percentage, estimate_close_value, external_cashflow_breakdown, external_cashflow_since, is_exposure_order, select_day_start_snapshot, utc_ms"
new_import = "from portfolio_growth import PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION, PORTFOLIO_GROWTH_START_DATE, average_daily_return, daily_return_percentage, estimate_close_value, external_cashflow_breakdown, external_cashflow_since, historical_day_windows, is_exposure_order, select_day_start_snapshot, utc_ms"
if old_import not in s and new_import not in s:
    raise SystemExit("portfolio_growth import anchor missing")
s = s.replace(old_import, new_import, 1)

old = '''        today_usd=(equity-day_net_cashflow)-reference_equity
        today=local_now.date().isoformat()
        transaction=db.transaction()
'''
new = '''        today_usd=(equity-day_net_cashflow)-reference_equity
        today=local_now.date().isoformat()

        # Build 438: schema v2 correctly neutralised today's deposit/withdrawal
        # but intentionally erased the older average. Rebuild only completed,
        # well-covered local days from durable account-equity candles. Each
        # day's external cashflow is removed independently.
        stored_preview=ref.get().to_dict() or {}
        daily_preview=dict(stored_preview.get("dailyGrowth") or {})
        preview_schema=int(safe_float(daily_preview.get("schemaVersion")))
        backfill_history:list[dict[str,Any]]=[]
        if preview_schema!=PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION:
            hourly_candles=_read_portfolio_chart_candles(user,"1u",400)
            windows=historical_day_windows(
                hourly_candles,timezone_name="Europe/Amsterdam",
                current_date=today,max_days=14,boundary_tolerance_minutes=90,
            )
            for window in windows:
                try:
                    ledger=client.income_history(
                        start_time=int(window["startAtMs"]),
                        end_time=int(window["endAtMs"]),limit=1000,
                    )
                    ledger=[row for row in ledger if isinstance(row,dict)]
                    if len(ledger)>=1000:
                        continue
                    historical_cashflow=external_cashflow_breakdown(ledger,int(window["startAtMs"]))
                    historical_net=safe_float(historical_cashflow.get("netExternalCashflowUsd"))
                    historical_pct=daily_return_percentage(
                        safe_float(window["startEquity"]),safe_float(window["endEquity"]),historical_net,
                    )
                    historical_usd=(safe_float(window["endEquity"])-historical_net)-safe_float(window["startEquity"])
                    backfill_history.append({
                        "date":str(window["date"]),
                        "startEquity":round(safe_float(window["startEquity"]),8),
                        "endEquity":round(safe_float(window["endEquity"]),8),
                        "usdChange":round(historical_usd,8),
                        "percentage":round(historical_pct,8),
                        "externalCashflowUsd":round(historical_net,8),
                        "source":"RECONSTRUCTED_HOURLY_EQUITY",
                    })
                except (AsterApiError,AsterSubmissionUncertain,AsterValidationError,HTTPException,ValueError,KeyError):
                    continue
        transaction=db.transaction()
'''
if old not in s:
    raise SystemExit("daily backfill insertion anchor missing")
s = s.replace(old, new, 1)

old = '''            if schema!=PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION:
                state={"schemaVersion":PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION,"measurementStartDate":today,
                    "completedReturnSum":0.0,"completedReturnCount":0,"history":[]}
            elif state.get("lastObservedDate")!=today and state.get("lastObservedDate"):
'''
new = '''            if schema!=PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION:
                restored=[row for row in backfill_history if isinstance(row,dict)]
                restored.sort(key=lambda row:str(row.get("date","")))
                restored=restored[-120:]
                state={"schemaVersion":PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION,
                    "measurementStartDate":str(restored[0].get("date")) if restored else today,
                    "completedReturnSum":sum(safe_float(row.get("percentage")) for row in restored),
                    "completedReturnCount":len(restored),"history":restored,
                    "historySource":"RECONSTRUCTED_HOURLY_EQUITY" if restored else "NO_RELIABLE_HISTORY",
                    "reconstructedHistoryCount":len(restored)}
            elif state.get("lastObservedDate")!=today and state.get("lastObservedDate"):
'''
if old not in s:
    raise SystemExit("schema migration anchor missing")
s = s.replace(old, new, 1)

old = '''                "measurementStartDate":str(state.get("measurementStartDate") or today),"referenceDate":today,
                "dayStartTimestampMs":reference_at_ms,"dayStartEquity":round(reference_equity,8),
'''
new = '''                "measurementStartDate":str(state.get("measurementStartDate") or today),"referenceDate":today,
                "averageHistorySource":str(state.get("historySource") or "DAILY_OBSERVATIONS"),
                "historicalDaysRestored":int(safe_float(state.get("reconstructedHistoryCount"))),
                "dayStartTimestampMs":reference_at_ms,"dayStartEquity":round(reference_equity,8),
'''
if old not in s:
    raise SystemExit("daily output audit anchor missing")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

# 3) Regression tests.
p = Path("cloud_api/test_portfolio_growth.py")
s = p.read_text(encoding="utf-8")
if "from zoneinfo import ZoneInfo\n" not in s:
    s = s.replace(
        "from datetime import datetime, timezone\n",
        "from datetime import datetime, timezone\nfrom zoneinfo import ZoneInfo\n",
    )
s = s.replace(
    "external_cashflow_since, is_exposure_order, select_day_start_snapshot, utc_ms)",
    "external_cashflow_since, historical_day_windows, is_exposure_order, select_day_start_snapshot, utc_ms)",
)
s = s.replace(
    "assert PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION == 2",
    "assert PORTFOLIO_DAILY_GROWTH_SCHEMA_VERSION == 3",
)
tests = r'''

def _ams_ms(year,month,day,hour,minute=0):
    zone=ZoneInfo("Europe/Amsterdam")
    return int(datetime(year,month,day,hour,minute,tzinfo=zone).astimezone(timezone.utc).timestamp()*1000)


def test_build438_reconstructs_only_complete_local_days_for_average():
    rows=[
        {"firstSampleAtMs":_ams_ms(2026,9,23,0,5),"sourceAtMs":_ams_ms(2026,9,23,0,55),"open":100,"close":102},
        {"firstSampleAtMs":_ams_ms(2026,9,23,23,0),"sourceAtMs":_ams_ms(2026,9,23,23,55),"open":98,"close":95},
        {"firstSampleAtMs":_ams_ms(2026,9,24,0,4),"sourceAtMs":_ams_ms(2026,9,24,0,55),"open":95,"close":94},
        {"firstSampleAtMs":_ams_ms(2026,9,24,23,0),"sourceAtMs":_ams_ms(2026,9,24,23,56),"open":90,"close":89},
        # Partial day: first observation is far too late and must not influence the average.
        {"firstSampleAtMs":_ams_ms(2026,9,25,8,0),"sourceAtMs":_ams_ms(2026,9,25,23,55),"open":89,"close":88},
    ]
    windows=historical_day_windows(
        rows,timezone_name="Europe/Amsterdam",current_date="2026-09-26",max_days=14,
    )
    assert [row["date"] for row in windows] == ["2026-09-23","2026-09-24"]
    assert windows[0]["startEquity"] == pytest.approx(100)
    assert windows[0]["endEquity"] == pytest.approx(95)
    assert windows[1]["startEquity"] == pytest.approx(95)
    assert windows[1]["endEquity"] == pytest.approx(89)


def test_build438_backfilled_day_keeps_deposit_neutral():
    start,end,deposit=95,189,100
    assert daily_return_percentage(start,end,deposit) == pytest.approx(-6.3157894737)
'''
if "test_build438_reconstructs_only_complete_local_days_for_average" not in s:
    s += tests
p.write_text(s, encoding="utf-8")

# Keep the Auto-Hedge UI regression contract aligned with the canonical build bump.
p = Path("web/tests/position-loss-auto-hedge.test.mjs")
s = p.read_text(encoding="utf-8")
s = s.replace('WEBAPP_BUILD_NUMBER = "437"', 'WEBAPP_BUILD_NUMBER = "438"')
p.write_text(s, encoding="utf-8")

# 4) Build number and release history.
p = Path("web/lib/app-version.ts")
s = p.read_text(encoding="utf-8")
if 'WEBAPP_BUILD_NUMBER = "437"' not in s:
    raise SystemExit("expected Build 437 app-version not found")
old = '''// Build 437: Portfolio Snapshot krijgt Zone-Soldaten quick actions en een volledig losse, opaque Command Center-pagina. Regressiecontract gesynchroniseerd. Release-contract pulse.
export const WEBAPP_BUILD_NUMBER = "437";'''
new = '''// Build 438: gemiddeld dagrendement herstelt betrouwbare historische dagen zonder stortingen/opnames als performance te tellen.
export const WEBAPP_BUILD_NUMBER = "438";'''
if old not in s:
    raise SystemExit("Build 437 app-version comment anchor missing")
s = s.replace(old, new, 1)
p.write_text(s, encoding="utf-8")

p = Path("web/lib/release-history.ts")
s = p.read_text(encoding="utf-8")
start = s.index("export const CURRENT_RELEASE: ReleaseHistoryEntry = {")
marker = "const HISTORICAL_RELEASES: ReleaseHistoryEntry[] = [\n"
end = s.index(marker)
old_current = s[start:end]
old_obj = old_current.replace(
    "export const CURRENT_RELEASE: ReleaseHistoryEntry = ", "", 1
).strip()
if not old_obj.endswith("};"):
    raise SystemExit("Build 437 release block shape changed")
old_obj = old_obj[:-1]
old_obj = old_obj.replace(
    'id: `v${WEBAPP_VERSION}-build-${WEBAPP_BUILD_NUMBER}-release-history`,',
    'id: "v46-build-437-zone-soldaten-command-center",',
    1,
)
old_obj = old_obj.replace("version: WEBAPP_VERSION,", 'version: "46",', 1)
old_obj = old_obj.replace("build: WEBAPP_BUILD_NUMBER,", 'build: "437",', 1)

new_current = '''export const CURRENT_RELEASE: ReleaseHistoryEntry = {
  id: `v${WEBAPP_VERSION}-build-${WEBAPP_BUILD_NUMBER}-release-history`,
  version: WEBAPP_VERSION,
  build: WEBAPP_BUILD_NUMBER,
  releasedAt: "2026-09-26",
  title: "Dagrendement 2.2 - betrouwbaar meerdaags gemiddelde",
  newItems: [
    "Gemiddeld per dag gebruikt opnieuw betrouwbare voltooide dagen uit de bestaande Portfolio Koers-equityhistorie.",
    "Iedere herstelde dag corrigeert stortingen en opnames afzonderlijk voordat het dagpercentage in het gemiddelde komt.",
    "De API publiceert de bron en het aantal herstelde historische dagen voor controleerbare diagnostiek.",
  ],
  problems: [
    "Build 433 zette bij de schema-migratie de gemiddelde-daghistorie bewust op nul; daardoor was Gemiddeld per dag tijdelijk praktisch gelijk aan Rendement vandaag.",
    "Een eerdere negatieve meerdaagse waarde kon daardoor verdwijnen zonder dat de onderliggende marktverliezen werkelijk waren hersteld.",
  ],
  causes: [
    "De cashflow-fix van Build 433 koos veiligheid boven behoud van mogelijk vervuilde oude daghistorie, maar reconstrueerde daarna de betrouwbare dagen niet opnieuw.",
  ],
  fixes: [
    "DailyGrowth schema v3 reconstrueert maximaal 14 voltooide Nederlandse kalenderdagen uit bevestigde 1u equity-candles.",
    "Alleen dagen met betrouwbare dekking rond zowel begin als einde van de kalenderdag worden meegenomen; partiele dagen worden overgeslagen.",
    "Per historische dag wordt de Aster income-ledger gelezen en externe cashflow uit het resultaat verwijderd voordat het gemiddelde wordt berekend.",
  ],
  now: [
    "Gemiddeld per dag is weer echt een meerdaags gemiddelde zodra betrouwbare historische dagen beschikbaar zijn.",
    "Rendement vandaag blijft een aparte, cashflow-neutrale dagmeting; Portfolio Impact blijft open P&L sinds de instapprijzen en is dus niet hetzelfde meetobject.",
    "Geen wijziging aan trading-, DCA-, TP/SL-, Auto-Hedge- of Zone-Soldaten executionlogica.",
  ],
  before: "Schema v2 startte de gemiddelde reeks opnieuw op de migratiedag.",
  after: "Schema v3 herstelt betrouwbare voltooide dagen en houdt stortingen/opnames rendement-neutraal.",
  technicalDetails: [
    "DailyGrowth schemaVersion 3.",
    "Historische bron: persisted 1u Aster account-equity candles + per-day signed external cashflow ledger.",
    "Onvolledige cashflow-ledger of onvoldoende dagdekking wordt fail-closed niet in het gemiddelde opgenomen.",
  ],
  confidence: "confirmed",
};
'''
s = (
    s[:start]
    + new_current
    + marker
    + "  "
    + old_obj.replace("\n", "\n  ")
    + ",\n"
    + s[end + len(marker):]
)
p.write_text(s, encoding="utf-8")
