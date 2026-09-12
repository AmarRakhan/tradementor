from pathlib import Path

CHART_PATH = Path("web/components/trading-chart.tsx")
TEST_PATH = Path("web/tests/trading-chart-aster-detail.test.mjs")

chart = CHART_PATH.read_text(encoding="utf-8")

constants_anchor = 'const RISK_HISTORY_KEY = "tradementor.test.riskTimeline.v1";\n'
timezone_block = '''const RISK_HISTORY_KEY = "tradementor.test.riskTimeline.v1";
const AMSTERDAM_TIME_ZONE = "Europe/Amsterdam";

// Lightweight Charts keeps numeric timestamps in UTC. Only localize labels here;
// never shift exchange timestamps, so candle/fill matching remains exact and DST
// follows Europe/Amsterdam automatically (CEST in summer, CET in winter).
function chartTimeToDate(time: unknown): Date | null {
  if (typeof time === "number" && Number.isFinite(time)) return new Date(time * 1000);
  if (typeof time === "string") {
    const parsed = new Date(`${time}T00:00:00Z`);
    return Number.isFinite(parsed.getTime()) ? parsed : null;
  }
  if (time && typeof time === "object") {
    const value = time as { year?: number; month?: number; day?: number };
    if (Number.isFinite(value.year) && Number.isFinite(value.month) && Number.isFinite(value.day)) {
      return new Date(Date.UTC(Number(value.year), Number(value.month) - 1, Number(value.day)));
    }
  }
  return null;
}

const amsterdamCrosshairFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, day:"2-digit", month:"short", year:"2-digit", hour:"2-digit", minute:"2-digit", hourCycle:"h23" });
const amsterdamYearFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, year:"numeric" });
const amsterdamMonthFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, month:"short" });
const amsterdamDayFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, day:"2-digit", month:"short" });
const amsterdamMinuteFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, hour:"2-digit", minute:"2-digit", hourCycle:"h23" });
const amsterdamSecondFormatter = new Intl.DateTimeFormat("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, hour:"2-digit", minute:"2-digit", second:"2-digit", hourCycle:"h23" });

function formatAmsterdamChartTime(time: unknown) {
  const date = chartTimeToDate(time);
  if (!date) return "";
  const parts = Object.fromEntries(amsterdamCrosshairFormatter.formatToParts(date).map(part => [part.type, part.value]));
  return `${parts.day} ${parts.month} '${parts.year} ${parts.hour}:${parts.minute}`;
}

function formatAmsterdamTickMark(time: unknown, tickMarkType: number) {
  const date = chartTimeToDate(time);
  if (!date) return "";
  if (tickMarkType === 0) return amsterdamYearFormatter.format(date);
  if (tickMarkType === 1) return amsterdamMonthFormatter.format(date);
  if (tickMarkType === 2) return amsterdamDayFormatter.format(date);
  if (tickMarkType === 4) return amsterdamSecondFormatter.format(date);
  return amsterdamMinuteFormatter.format(date);
}

function formatAmsterdamDateTime(timestampMs: number) {
  return new Date(timestampMs).toLocaleString("nl-NL", { timeZone: AMSTERDAM_TIME_ZONE, hourCycle:"h23" });
}
'''

if 'const AMSTERDAM_TIME_ZONE = "Europe/Amsterdam";' not in chart:
    if constants_anchor not in chart:
        raise SystemExit("timezone constants anchor not found")
    chart = chart.replace(constants_anchor, timezone_block, 1)

create_chart_old = 'const chart = createChart(container, { width:container.clientWidth, height:Math.max(390,container.clientHeight), layout:'
create_chart_new = 'const chart = createChart(container, { width:container.clientWidth, height:Math.max(390,container.clientHeight), localization:{locale:"nl-NL",timeFormatter:formatAmsterdamChartTime}, layout:'
if create_chart_new not in chart:
    if create_chart_old not in chart:
        raise SystemExit("createChart localization anchor not found")
    chart = chart.replace(create_chart_old, create_chart_new, 1)

time_scale_old = 'timeScale:{borderColor:heritage?"#4b4325":"#1c3858",timeVisible:true,secondsVisible:false,rightOffset:focusV2?14:8}'
time_scale_new = 'timeScale:{borderColor:heritage?"#4b4325":"#1c3858",timeVisible:true,secondsVisible:false,tickMarkFormatter:formatAmsterdamTickMark,rightOffset:focusV2?14:8}'
if time_scale_new not in chart:
    if time_scale_old not in chart:
        raise SystemExit("timeScale formatter anchor not found")
    chart = chart.replace(time_scale_old, time_scale_new, 1)

crosshair_old = '{new Date(crosshair.time*1000).toLocaleString("nl-NL")}'
crosshair_new = '{formatAmsterdamDateTime(crosshair.time*1000)}'
if crosshair_new not in chart:
    if crosshair_old not in chart:
        raise SystemExit("crosshair readout anchor not found")
    chart = chart.replace(crosshair_old, crosshair_new, 1)

fill_old = '{new Date(event.timestampMs).toLocaleString("nl-NL")}'
fill_new = '{formatAmsterdamDateTime(event.timestampMs)}'
if fill_new not in chart:
    if fill_old not in chart:
        raise SystemExit("fill time anchor not found")
    chart = chart.replace(fill_old, fill_new, 1)

CHART_PATH.write_text(chart, encoding="utf-8")

test_text = TEST_PATH.read_text(encoding="utf-8")
test_name = 'test("Aster chart renders all chart timestamps in Europe/Amsterdam"'
if test_name not in test_text:
    test_text = test_text.rstrip() + '''\n\n\ntest("Aster chart renders all chart timestamps in Europe/Amsterdam", () => {\n  assert.match(chart, /AMSTERDAM_TIME_ZONE = "Europe\\/Amsterdam"/);\n  assert.match(chart, /localization:\\{locale:"nl-NL",timeFormatter:formatAmsterdamChartTime\\}/);\n  assert.match(chart, /tickMarkFormatter:formatAmsterdamTickMark/);\n  assert.match(chart, /formatAmsterdamDateTime\\(crosshair\\.time\\*1000\\)/);\n  assert.match(chart, /formatAmsterdamDateTime\\(event\\.timestampMs\\)/);\n  assert.doesNotMatch(chart, /UTC\\+2/);\n});\n'''
    TEST_PATH.write_text(test_text, encoding="utf-8")

print("Amsterdam chart timezone patch applied")
