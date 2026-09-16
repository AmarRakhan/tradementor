from __future__ import annotations

from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[1]


def read(rel: str) -> str:
    return (ROOT / rel).read_text(encoding="utf-8")


def write(rel: str, text: str) -> None:
    path = ROOT / rel
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected exactly one match, found {count}")
    return text.replace(old, new, 1)


BACKEND = '''from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import time

DEFAULT_TIMEFRAME = "15m"
SUPPORTED_TIMEFRAMES = ("1m", "5m", "15m", "1h", "4h", "1d")
TIMEFRAME_MS = {
    "1m": 60_000,
    "5m": 5 * 60_000,
    "15m": 15 * 60_000,
    "1h": 60 * 60_000,
    "4h": 4 * 60 * 60_000,
    "1d": 24 * 60 * 60_000,
}
PERIOD = 20
STDDEV_MULTIPLIER = 2.0
CACHE_TTL_SECONDS = 5.0
PREORDER_MARKET_TTL_SECONDS = 1


def normalize_bollinger_timeframe(value: Any) -> str:
    raw = str(value or DEFAULT_TIMEFRAME).strip().lower()
    aliases = {"1u": "1h", "4u": "4h"}
    timeframe = aliases.get(raw, raw)
    if timeframe not in SUPPORTED_TIMEFRAMES:
        raise ValueError(f"Ongeldig Bollinger-timeframe: {value}")
    return timeframe


def _maximum_kline_age_ms(timeframe: str) -> int:
    # The latest Aster row is the current, still-forming candle. Allow one full
    # selected interval plus five minutes of transport/scheduling slack. This
    # preserves the previous 20-minute freshness limit for the 15m default.
    return TIMEFRAME_MS[timeframe] + 5 * 60_000


@dataclass(frozen=True)
class BollingerEntrySnapshot:
    symbol: str
    side: str
    timeframe: str
    live_price: float
    lower_band: float
    upper_band: float
    latest_kline_open_ms: int
    checked_at_ms: int


class BollingerEntryRejected(ValueError):
    def __init__(self, reason_code: str, symbol: str, side: str, snapshot: BollingerEntrySnapshot | None = None):
        self.reason_code = reason_code
        self.symbol = str(symbol).upper()
        self.side = str(side).upper()
        self.snapshot = snapshot
        super().__init__(f"{self.symbol} {self.side}: {reason_code}")


# Cache is isolated by BOTH symbol and timeframe so changing 15m -> 1m can
# never reuse bands from the prior interval.
_BAND_CACHE: dict[tuple[str, str], tuple[float, float, float, int]] = {}


def _finite(value: Any) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("non-finite market value")
    return number


def _row_close(row: Any) -> float:
    if isinstance(row, (list, tuple)) and len(row) > 4:
        return _finite(row[4])
    if isinstance(row, dict):
        return _finite(row.get("close", row.get("c")))
    raise ValueError("invalid kline row")


def _row_open_ms(row: Any) -> int:
    if isinstance(row, (list, tuple)) and row:
        return int(float(row[0]))
    if isinstance(row, dict):
        return int(float(row.get("openTime", row.get("open_time", row.get("t", 0)))))
    return 0


def _guarded_public_read(client: Any, path: str, *, invalid_message: str) -> Any:
    """Use AsterV3Client's guarded public transport for a near-submit read."""
    reader = getattr(client, "_public_get", None)
    if not callable(reader):
        raise AttributeError("guarded public market reader unavailable")
    return reader(path, ttl_seconds=PREORDER_MARKET_TTL_SECONDS, invalid_message=invalid_message)


def _read_klines(client: Any, symbol: str, timeframe: str, *, force_refresh: bool) -> list[Any]:
    symbol = str(symbol).upper()
    timeframe = normalize_bollinger_timeframe(timeframe)
    if force_refresh and callable(getattr(client, "_public_get", None)):
        # Query order deliberately remains separate from the normal scanner key,
        # keeping the pre-order validation on its own <=1 second cache.
        payload = _guarded_public_read(
            client,
            f"/fapi/v1/klines?interval={timeframe}&symbol={symbol}&limit=25",
            invalid_message=f"Aster {timeframe}-candles konden niet betrouwbaar worden gelezen",
        )
        if not isinstance(payload, list):
            raise ValueError(f"invalid {timeframe} kline payload")
        return [row for row in payload if isinstance(row, (list, tuple, dict))]
    rows = client.klines(symbol=symbol, interval=timeframe, limit=25)
    if not isinstance(rows, list):
        raise ValueError(f"invalid {timeframe} kline payload")
    return rows


def _current_bands(client: Any, symbol: str, timeframe: str, *, now_ms: int, force_refresh: bool) -> tuple[float, float, int]:
    symbol = str(symbol).upper()
    timeframe = normalize_bollinger_timeframe(timeframe)
    cache_key = (symbol, timeframe)
    cached = _BAND_CACHE.get(cache_key)
    if not force_refresh and cached and time.monotonic() - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1], cached[2], cached[3]
    rows = _read_klines(client, symbol, timeframe, force_refresh=force_refresh)
    if len(rows) < PERIOD:
        raise ValueError(f"insufficient {timeframe} klines")
    window = rows[-PERIOD:]
    closes = [_row_close(row) for row in window]
    latest_open_ms = _row_open_ms(window[-1])
    maximum_age_ms = _maximum_kline_age_ms(timeframe)
    if latest_open_ms <= 0 or latest_open_ms > now_ms + 60_000 or now_ms - latest_open_ms > maximum_age_ms:
        raise ValueError(f"stale {timeframe} kline")
    mean = sum(closes) / PERIOD
    variance = sum((value - mean) ** 2 for value in closes) / PERIOD
    sigma = math.sqrt(max(0.0, variance))
    lower = mean - STDDEV_MULTIPLIER * sigma
    upper = mean + STDDEV_MULTIPLIER * sigma
    if lower <= 0 or upper <= 0 or lower > upper:
        raise ValueError(f"invalid {timeframe} Bollinger bands")
    _BAND_CACHE[cache_key] = (time.monotonic(), lower, upper, latest_open_ms)
    return lower, upper, latest_open_ms


def _latest_price(client: Any, symbol: str, *, force_refresh: bool) -> float:
    symbol = str(symbol).upper()
    payload: Any = None
    if force_refresh and callable(getattr(client, "_public_get", None)):
        payload = _guarded_public_read(
            client,
            f"/fapi/v3/ticker/price?symbol={symbol}",
            invalid_message="Aster-prijs kon niet betrouwbaar worden gelezen",
        )
    else:
        single = getattr(client, "ticker_price", None)
        if callable(single):
            payload = single(symbol=symbol)
        else:
            rows = client.ticker_prices()
            payload = next((row for row in rows if isinstance(row, dict) and str(row.get("symbol", "")).upper() == symbol), None)
    if not isinstance(payload, dict):
        raise ValueError("invalid live ticker")
    price = _finite(payload.get("price"))
    if price <= 0:
        raise ValueError("invalid live price")
    return price


def _event(side: str, passed: bool) -> str:
    return f"BB_ENTRY_FILTER_{side}_{'PASS' if passed else 'REJECT'}"


def _log(*, symbol: str, side: str, timeframe: str, live_price: float | None, lower: float | None, upper: float | None,
         checked_at_ms: int, stage: str, passed: bool, reason: str) -> None:
    print(
        f"{_event(side, passed)} symbol={symbol} side={side} livePrice={live_price if live_price is not None else 'NA'} "
        f"lowerBand={lower if lower is not None else 'NA'} upperBand={upper if upper is not None else 'NA'} "
        f"timeframe={timeframe} timestampMs={checked_at_ms} enabled=true stage={stage} result={'PASS' if passed else 'REJECT'} reason={reason}",
        flush=True,
    )


def require_bollinger_entry(client: Any, *, symbol: str, side: str, enabled: bool,
                            timeframe: str = DEFAULT_TIMEFRAME,
                            live_price: float | None = None, force_refresh: bool = False,
                            stage: str = "candidate", now_ms: int | None = None) -> BollingerEntrySnapshot | None:
    """Fail closed for one NEW primary entry; disabled mode is a true no-op.

    The selected timeframe's klines define the existing Bollinger formula. The
    decision uses a live/current price and does not add a candle-close rule.
    Strict inequalities intentionally reject equality with the relevant band.
    """
    if not enabled:
        return None
    symbol = str(symbol).upper()
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise BollingerEntryRejected("BB_INVALID_SIDE", symbol, side)
    checked_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        selected_timeframe = normalize_bollinger_timeframe(timeframe)
        lower, upper, latest_open_ms = _current_bands(client, symbol, selected_timeframe, now_ms=checked_at_ms, force_refresh=force_refresh)
        price = _latest_price(client, symbol, force_refresh=force_refresh) if live_price is None else _finite(live_price)
        if price <= 0:
            raise ValueError("invalid live price")
    except Exception as exc:
        log_timeframe = str(timeframe or DEFAULT_TIMEFRAME)
        _log(symbol=symbol, side=side, timeframe=log_timeframe, live_price=None, lower=None, upper=None, checked_at_ms=checked_at_ms,
             stage=stage, passed=False, reason="BB_DATA_UNAVAILABLE_OR_STALE")
        raise BollingerEntryRejected("BB_DATA_UNAVAILABLE_OR_STALE", symbol, side) from exc
    snapshot = BollingerEntrySnapshot(symbol, side, selected_timeframe, price, lower, upper, latest_open_ms, checked_at_ms)
    passed = price < lower if side == "LONG" else price > upper
    reason = "PRICE_BELOW_LOWER_BAND" if side == "LONG" and passed else \
             "PRICE_ABOVE_UPPER_BAND" if side == "SHORT" and passed else \
             "PRICE_NOT_BELOW_LOWER_BAND" if side == "LONG" else "PRICE_NOT_ABOVE_UPPER_BAND"
    _log(symbol=symbol, side=side, timeframe=selected_timeframe, live_price=price, lower=lower, upper=upper, checked_at_ms=checked_at_ms,
         stage=stage, passed=passed, reason=reason)
    if not passed:
        raise BollingerEntryRejected(reason, symbol, side, snapshot)
    return snapshot
'''


CARD = '''"use client";

export type BollingerEntryTimeframe = "1m" | "5m" | "15m" | "1h" | "4h" | "1d";

type Props = {
  enabled: boolean;
  busy: boolean;
  timeframe: BollingerEntryTimeframe;
  message?: string;
  onToggle: (next: boolean) => void;
  onTimeframeChange: (next: BollingerEntryTimeframe) => void;
};

export const BOLLINGER_ENTRY_FILTER_REFERENCE = "file_00000000938481f4912fc885bdf10916";
export const BOLLINGER_ENTRY_TIMEFRAMES: Array<{ value: BollingerEntryTimeframe; label: string }> = [
  { value: "1m", label: "1m" },
  { value: "5m", label: "5m" },
  { value: "15m", label: "15m" },
  { value: "1h", label: "1u" },
  { value: "4h", label: "4u" },
  { value: "1d", label: "1d" },
];

export function AsterBollingerEntryFilter15mCard({ enabled, busy, timeframe, message, onToggle, onTimeframeChange }: Props) {
  const activeLabel = BOLLINGER_ENTRY_TIMEFRAMES.find((item) => item.value === timeframe)?.label || "15m";
  return <section className="bb-entry-filter-card" data-reference={BOLLINGER_ENTRY_FILTER_REFERENCE} aria-label="Bollinger instapfilter">
    <div className="bb-entry-main">
      <div className="bb-entry-copy">
        <div className="bb-entry-title-row"><span className="bb-entry-new">NEW</span><strong>Bollinger instapfilter</strong></div>
        <p>Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band.</p>
        <small>Live prijs vs {activeLabel} Bollinger Bands · optioneel</small>
        {message ? <em>{message}</em> : null}
      </div>
      <button type="button" className={`bb-entry-toggle ${enabled ? "is-on" : "is-off"}`} role="switch" aria-checked={enabled} disabled={busy}
        onClick={() => onToggle(!enabled)}>
        <span>OFF</span><i aria-hidden="true" /><span>ON</span>
      </button>
    </div>
    {enabled ? <div className="bb-entry-timeframes" role="radiogroup" aria-label="Bollinger timeframe">
      {BOLLINGER_ENTRY_TIMEFRAMES.map((item) => <button key={item.value} type="button" role="radio" aria-checked={timeframe === item.value}
        className={timeframe === item.value ? "is-active" : ""} disabled={busy} onClick={() => onTimeframeChange(item.value)}>{item.label}</button>)}
    </div> : null}
    <style>{`.bb-entry-filter-card{grid-column:1/-1;display:grid;gap:8px;width:100%;min-width:0;padding:10px 11px;border:1px solid rgba(37,224,155,.34);border-radius:11px;background:linear-gradient(100deg,rgba(4,31,22,.91),rgba(3,18,13,.94));box-shadow:inset 0 0 20px rgba(38,226,157,.025)}.bb-entry-main{display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;min-width:0}.bb-entry-copy{min-width:0;display:grid;gap:3px}.bb-entry-title-row{display:flex;align-items:center;gap:6px;min-width:0}.bb-entry-title-row strong{color:#e9f5ef;font-size:10px;font-weight:900;letter-spacing:.01em}.bb-entry-new{display:inline-flex;align-items:center;justify-content:center;height:15px;padding:0 5px;border:1px solid rgba(47,239,169,.6);border-radius:4px;background:rgba(17,114,76,.28);color:#52f1b1;font-size:6px;font-weight:1000;letter-spacing:.08em}.bb-entry-copy p{margin:0;color:#a9b9b1;font-size:8px;line-height:1.35}.bb-entry-copy small{color:#5e8978;font-size:7px;line-height:1.3}.bb-entry-copy em{color:#75c9a5;font-size:6.5px;font-style:normal;line-height:1.25}.bb-entry-toggle{display:grid;grid-template-columns:auto 19px auto;align-items:center;gap:4px;min-width:76px;height:30px;padding:0 7px;border:1px solid rgba(62,110,89,.55);border-radius:16px;background:rgba(2,10,8,.75);color:#60746a;font-size:6px;font-weight:1000;letter-spacing:.08em;transition:.16s ease}.bb-entry-toggle i{position:relative;width:19px;height:12px;border-radius:8px;background:#26372f;box-shadow:inset 0 0 0 1px rgba(109,143,126,.24)}.bb-entry-toggle i:after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;border-radius:50%;background:#8c9b94;transition:.16s ease}.bb-entry-toggle.is-on{border-color:rgba(43,236,165,.72);color:#45eca9;box-shadow:0 0 12px rgba(43,236,165,.08)}.bb-entry-toggle.is-on i{background:rgba(31,190,130,.42)}.bb-entry-toggle.is-on i:after{left:9px;background:#48f0ad;box-shadow:0 0 7px rgba(72,240,173,.42)}.bb-entry-toggle:disabled,.bb-entry-timeframes button:disabled{opacity:.55}.bb-entry-timeframes{display:grid;grid-template-columns:repeat(6,minmax(0,1fr));gap:4px;width:100%;min-width:0}.bb-entry-timeframes button{min-width:0;height:25px;padding:0;border:1px solid rgba(62,110,89,.48);border-radius:7px;background:rgba(2,12,9,.72);color:#718a7e;font-size:7px;font-weight:900;line-height:1;transition:.14s ease}.bb-entry-timeframes button.is-active{border-color:rgba(49,239,171,.82);background:linear-gradient(180deg,rgba(26,145,99,.42),rgba(10,82,57,.38));color:#56f0b3;box-shadow:inset 0 0 9px rgba(49,239,171,.08),0 0 8px rgba(49,239,171,.06)}@media(max-width:430px){.bb-entry-filter-card{gap:7px;padding:9px}.bb-entry-main{gap:8px}.bb-entry-copy p{max-width:245px}.bb-entry-toggle{min-width:72px;padding:0 6px}.bb-entry-timeframes{gap:3px}.bb-entry-timeframes button{height:24px;font-size:6.8px}}`}</style>
  </section>;
}
'''


WEB_TEST = '''import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const bridge = readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../components/aster-bollinger-entry-filter-15m-card.tsx", import.meta.url), "utf8");

test("Bollinger timeframe UI matches approved contract and stays above Profit Lock", () => {
  assert.match(card, /file_00000000938481f4912fc885bdf10916/);
  assert.match(card, /<strong>Bollinger instapfilter<\\/strong>/);
  assert.doesNotMatch(card, /<strong>Bollinger instapfilter 15m<\\/strong>/);
  for (const label of ["1m", "5m", "15m", "1u", "4u", "1d"]) assert.match(card, new RegExp(`label: "${label}"`));
  assert.match(card, /value: "1h", label: "1u"/);
  assert.match(card, /value: "4h", label: "4u"/);
  assert.match(card, /grid-template-columns:repeat\\(6,minmax\\(0,1fr\\)\\)/);
  const bb = bridge.indexOf("<AsterBollingerEntryFilter15mCard");
  const pll = bridge.indexOf("<AsterProfitLockLadderPanel");
  assert.ok(bb >= 0 && pll > bb, "Bollinger card must render immediately before Profit Lock Ladder");
});

test("enabled state and selected timeframe persist independently with 15m default", () => {
  assert.match(bridge, /useState<BollingerEntryTimeframe>\\("15m"\\)/);
  assert.match(bridge, /bollingerEntryFilter15mEnabled === true/);
  assert.match(bridge, /bollingerEntryFilterTimeframe/);
  assert.match(bridge, /toggleBollingerEntryFilter/);
  assert.match(bridge, /changeBollingerTimeframe/);
  assert.match(bridge, /window\\.dispatchEvent\\(new Event\\("aster-strategy2-settings-changed"\\)\\)/);
});
'''


BACKEND_TEST = '''from __future__ import annotations

import time
import pytest

import aster_bollinger_entry_filter as bb
from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry
from aster_multi_bb_core import MultiBbConfig


INTERVAL_MS = {
    "1m": 60_000,
    "5m": 300_000,
    "15m": 900_000,
    "1h": 3_600_000,
    "4h": 14_400_000,
    "1d": 86_400_000,
}


class TimeframeMarket:
    def __init__(self):
        self.calls: list[tuple[str, str]] = []

    def klines(self, *, symbol, interval, limit):
        assert interval in INTERVAL_MS
        assert limit == 25
        self.calls.append((symbol, interval))
        step = INTERVAL_MS[interval]
        now = int(time.time() * 1000)
        last_open = now // step * step
        start = last_open - 19 * step
        return [[start + i * step, "0", "0", "0", str(100 + i * 0.1), "0"] for i in range(20)]


class GuardedMarket(TimeframeMarket):
    def __init__(self):
        super().__init__()
        self.public_reads: list[str] = []

    def _public_get(self, path, *, ttl_seconds, invalid_message):
        assert ttl_seconds == 1
        self.public_reads.append(path)
        if "/klines?" in path:
            interval = path.split("interval=", 1)[1].split("&", 1)[0]
            symbol = path.split("symbol=", 1)[1].split("&", 1)[0]
            return self.klines(symbol=symbol, interval=interval, limit=25)
        if "/ticker/price?" in path:
            return {"price": "1"}
        raise AssertionError(path)


def test_config_backward_compatible_default_and_ui_aliases():
    cfg = MultiBbConfig.from_mapping({})
    assert cfg.bollinger_entry_filter_timeframe == "15m"
    assert cfg.public_dict()["bollingerEntryFilterTimeframe"] == "15m"
    assert MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "1u"}).bollinger_entry_filter_timeframe == "1h"
    assert MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "4u"}).bollinger_entry_filter_timeframe == "4h"
    with pytest.raises(ValueError):
        MultiBbConfig.from_mapping({"bollingerEntryFilterTimeframe": "30m"})


def test_filter_off_is_true_noop_even_with_invalid_timeframe():
    market = TimeframeMarket()
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=False, timeframe="invalid") is None
    assert market.calls == []


@pytest.mark.parametrize("timeframe", ["1m", "5m", "15m", "1h", "4h", "1d"])
def test_all_six_intervals_reach_datasource(timeframe):
    market = TimeframeMarket()
    symbol = f"T{timeframe.replace('m','M').replace('h','H').replace('d','D')}USDT"
    result = require_bollinger_entry(market, symbol=symbol, side="LONG", enabled=True, timeframe=timeframe,
                                     live_price=1, force_refresh=False)
    assert result is not None
    assert result.timeframe == timeframe
    assert market.calls == [(symbol, timeframe)]


def test_timeframe_change_cannot_reuse_old_band_cache():
    bb._BAND_CACHE.clear()
    market = TimeframeMarket()
    require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, timeframe="15m", live_price=1)
    require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, timeframe="1m", live_price=1)
    assert market.calls == [("BTCUSDT", "15m"), ("BTCUSDT", "1m")]
    assert ("BTCUSDT", "15m") in bb._BAND_CACHE
    assert ("BTCUSDT", "1m") in bb._BAND_CACHE


@pytest.mark.parametrize("timeframe", ["1m", "15m", "1h", "4h", "1d"])
def test_preorder_guarded_read_uses_selected_exchange_interval(timeframe):
    market = GuardedMarket()
    result = require_bollinger_entry(market, symbol="ETHUSDT", side="LONG", enabled=True, timeframe=timeframe,
                                     live_price=1, force_refresh=True, stage="pre_order")
    assert result is not None
    assert market.public_reads[0] == f"/fapi/v1/klines?interval={timeframe}&symbol=ETHUSDT&limit=25"


def test_missing_or_stale_selected_timeframe_fails_closed():
    class EmptyMarket:
        def klines(self, *, symbol, interval, limit):
            return []
    with pytest.raises(BollingerEntryRejected) as exc:
        require_bollinger_entry(EmptyMarket(), symbol="SOLUSDT", side="LONG", enabled=True, timeframe="4h", live_price=1)
    assert exc.value.reason_code == "BB_DATA_UNAVAILABLE_OR_STALE"
'''


SIMULATION = '''from __future__ import annotations

import json
import math
import time

from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry

INTERVAL_MS = {"1m": 60_000, "5m": 300_000, "15m": 900_000, "1h": 3_600_000, "4h": 14_400_000, "1d": 86_400_000}


class SyntheticMarket:
    def __init__(self, timeframe: str, closes: list[float]):
        self.timeframe = timeframe
        self.closes = closes

    def klines(self, *, symbol, interval, limit):
        assert interval == self.timeframe
        step = INTERVAL_MS[interval]
        now = int(time.time() * 1000)
        last_open = now // step * step
        start = last_open - (len(self.closes) - 1) * step
        return [[start + i * step, "0", "0", "0", str(close), "0"] for i, close in enumerate(self.closes)]


def bands(closes: list[float]):
    window = closes[-20:]
    mean = sum(window) / len(window)
    sigma = math.sqrt(sum((x - mean) ** 2 for x in window) / len(window))
    return mean - 2 * sigma, mean + 2 * sigma


def decision(market, timeframe, side, price, lower, upper, expected):
    allowed = True
    reason = "PASS"
    try:
        require_bollinger_entry(market, symbol="TESTUSDT", side=side, enabled=True, timeframe=timeframe,
                                live_price=price, force_refresh=True, stage="simulation")
    except BollingerEntryRejected as exc:
        allowed = False
        reason = exc.reason_code
    row = {"symbol":"TESTUSDT","side":side,"selectedTimeframe":timeframe,"currentPrice":price,
           "lowerBand":lower,"upperBand":upper,"filterEnabled":True,"entryAllowed":allowed,"reason":reason}
    print("SIM_RESULT " + json.dumps(row, sort_keys=True))
    assert allowed is expected, row


def run(timeframe):
    closes = [100 + i * .25 for i in range(20)]
    lower, upper = bands(closes)
    market = SyntheticMarket(timeframe, closes)
    middle = (lower + upper) / 2
    decision(market, timeframe, "LONG", middle, lower, upper, False)
    decision(market, timeframe, "LONG", lower - .01, lower, upper, True)
    decision(market, timeframe, "LONG", middle, lower, upper, False)
    decision(market, timeframe, "SHORT", upper + .01, lower, upper, True)


for tf in ("1m", "15m", "1h"):
    run(tf)

# Datasource interval contract for all six choices is separately asserted by
# test_aster_bollinger_entry_filter_timeframes.py.
print("SIMULATION_OK timeframes=1m,15m,1h datasourceValidated=1m,5m,15m,1h,4h,1d")
'''


def patch_backend() -> None:
    write("cloud_api/aster_bollinger_entry_filter.py", BACKEND)


def patch_core() -> None:
    rel = "cloud_api/aster_multi_bb_core.py"
    text = read(rel)
    text = replace_once(
        text,
        "from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry",
        "from aster_bollinger_entry_filter import BollingerEntryRejected, DEFAULT_TIMEFRAME, normalize_bollinger_timeframe, require_bollinger_entry",
        "core import",
    )
    text = replace_once(
        text,
        "    bollinger_entry_filter_15m_enabled: bool = False\n    entry_margin_usd: float = 5.0",
        "    bollinger_entry_filter_15m_enabled: bool = False\n    bollinger_entry_filter_timeframe: str = DEFAULT_TIMEFRAME\n    entry_margin_usd: float = 5.0",
        "core dataclass timeframe",
    )
    text = replace_once(
        text,
        "            bollinger_entry_filter_15m_enabled=bool(raw.get(\"bollingerEntryFilter15mEnabled\", raw.get(\"bollinger_entry_filter_15m_enabled\", False))),\n            entry_margin_usd=entry_margin_usd,",
        "            bollinger_entry_filter_15m_enabled=bool(raw.get(\"bollingerEntryFilter15mEnabled\", raw.get(\"bollinger_entry_filter_15m_enabled\", False))),\n            bollinger_entry_filter_timeframe=normalize_bollinger_timeframe(raw.get(\"bollingerEntryFilterTimeframe\", raw.get(\"bollinger_entry_filter_timeframe\", DEFAULT_TIMEFRAME))),\n            entry_margin_usd=entry_margin_usd,",
        "core mapping timeframe",
    )
    text = replace_once(
        text,
        "            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n            \"entryMarginUsd\": self.entry_margin_usd,",
        "            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n            \"bollingerEntryFilterTimeframe\": self.bollinger_entry_filter_timeframe,\n            \"entryMarginUsd\": self.entry_margin_usd,",
        "core public timeframe",
    )
    text = replace_once(
        text,
        "require_bollinger_entry(client, symbol=symbol, side=candidate_side, enabled=True, live_price=prices[symbol],\n                                        force_refresh=False, stage=\"candidate\", now_ms=timestamp_ms)",
        "require_bollinger_entry(client, symbol=symbol, side=candidate_side, enabled=True, timeframe=settings.bollinger_entry_filter_timeframe,\n                                        live_price=prices[symbol], force_refresh=False, stage=\"candidate\", now_ms=timestamp_ms)",
        "candidate selected timeframe",
    )
    text = replace_once(
        text,
        "require_bollinger_entry(client, symbol=symbol, side=side, enabled=settings.bollinger_entry_filter_15m_enabled,\n                                        live_price=None, force_refresh=True, stage=\"pre_order\")",
        "require_bollinger_entry(client, symbol=symbol, side=side, enabled=settings.bollinger_entry_filter_15m_enabled,\n                                        timeframe=settings.bollinger_entry_filter_timeframe, live_price=None, force_refresh=True, stage=\"pre_order\")",
        "preorder selected timeframe",
    )
    text = replace_once(
        text,
        '              "bollingerEntryFilter15mEnabled": settings.bollinger_entry_filter_15m_enabled,\n               "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled,',
        '              "bollingerEntryFilter15mEnabled": settings.bollinger_entry_filter_15m_enabled, "bollingerEntryFilterTimeframe": settings.bollinger_entry_filter_timeframe,\n               "asymmetricHedgeModeEnabled": settings.asymmetric_hedge_enabled,',
        "report selected timeframe",
    )
    write(rel, text)


def patch_card() -> None:
    write("web/components/aster-bollinger-entry-filter-15m-card.tsx", CARD)


def patch_bridge() -> None:
    rel = "web/components/aster-profit-lock-ladder-bridge.tsx"
    text = read(rel)
    text = replace_once(
        text,
        'import { AsterBollingerEntryFilter15mCard } from "./aster-bollinger-entry-filter-15m-card";',
        'import { AsterBollingerEntryFilter15mCard, type BollingerEntryTimeframe } from "./aster-bollinger-entry-filter-15m-card";',
        "bridge import",
    )
    anchor = 'const percent = (value: unknown) => `${new Intl.NumberFormat("nl-NL", { maximumFractionDigits: 1 }).format(Number(value) || 0)}%`;\n'
    helper = anchor + '''\nfunction normalizeBollingerTimeframe(value: unknown): BollingerEntryTimeframe {\n  const raw = String(value || "15m").toLowerCase();\n  if (raw === "1u") return "1h";\n  if (raw === "4u") return "4h";\n  return (["1m", "5m", "15m", "1h", "4h", "1d"] as const).includes(raw as BollingerEntryTimeframe) ? raw as BollingerEntryTimeframe : "15m";\n}\n'''
    text = replace_once(text, anchor, helper, "bridge normalize helper")
    text = replace_once(
        text,
        '  const [bbEnabled, setBbEnabled] = useState(false);\n  const [bbBusy, setBbBusy] = useState(false);',
        '  const [bbEnabled, setBbEnabled] = useState(false);\n  const [bbTimeframe, setBbTimeframe] = useState<BollingerEntryTimeframe>("15m");\n  const [bbBusy, setBbBusy] = useState(false);',
        "bridge timeframe state",
    )
    text = replace_once(
        text,
        '      if (!bbBusy) setBbEnabled(next.settings.bollingerEntryFilter15mEnabled === true);',
        '      if (!bbBusy) {\n        setBbEnabled(next.settings.bollingerEntryFilter15mEnabled === true);\n        setBbTimeframe(normalizeBollingerTimeframe(next.settings.bollingerEntryFilterTimeframe));\n      }',
        "bridge refresh timeframe",
    )
    text = replace_once(
        text,
        '      const nextSettings = { ...latestSettings, bollingerEntryFilter15mEnabled: next };',
        '      const nextSettings = { ...latestSettings, bollingerEntryFilter15mEnabled: next, bollingerEntryFilterTimeframe: bbTimeframe };',
        "bridge toggle preserves timeframe",
    )
    marker = '  async function save() {'
    change_fn = '''  async function changeBollingerTimeframe(next: BollingerEntryTimeframe) {\n    if (bbBusy || next === bbTimeframe) return;\n    const previous = bbTimeframe;\n    setBbTimeframe(next); setBbBusy(true); setBbMessage("Timeframe opslaan…");\n    try {\n      const latestSnapshot = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;\n      const latestSettings = extract(latestSnapshot).settings;\n      const nextSettings = { ...latestSettings, bollingerEntryFilterTimeframe: next };\n      const response = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {\n        method: "PUT",\n        body: JSON.stringify({ settings: nextSettings }),\n      }) as Record<string, unknown>;\n      const strategy2 = response.strategy2 && typeof response.strategy2 === "object" ? response.strategy2 as Record<string, unknown> : {};\n      const saved = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : nextSettings;\n      const confirmed = normalizeBollingerTimeframe(saved.bollingerEntryFilterTimeframe);\n      setSettings(saved); setBbTimeframe(confirmed);\n      setBbMessage(`${confirmed === "1h" ? "1u" : confirmed === "4h" ? "4u" : confirmed} · actief voor volgende primaire entry-check.`);\n      window.dispatchEvent(new Event("aster-strategy2-settings-changed"));\n    } catch (error) {\n      setBbTimeframe(previous);\n      setBbMessage(error instanceof Error ? error.message : "Bollinger-timeframe kon niet worden opgeslagen.");\n    } finally { setBbBusy(false); }\n  }\n\n'''
    text = replace_once(text, marker, change_fn + marker, "bridge change timeframe function")
    text = replace_once(
        text,
        '<AsterBollingerEntryFilter15mCard enabled={bbEnabled} busy={bbBusy} message={bbMessage} onToggle={(next) => void toggleBollingerEntryFilter(next)} />',
        '<AsterBollingerEntryFilter15mCard enabled={bbEnabled} busy={bbBusy} timeframe={bbTimeframe} message={bbMessage} onToggle={(next) => void toggleBollingerEntryFilter(next)} onTimeframeChange={(next) => void changeBollingerTimeframe(next)} />',
        "bridge card props",
    )
    write(rel, text)


def patch_tests() -> None:
    write("web/tests/aster-bollinger-entry-filter-15m.test.mjs", WEB_TEST)
    write("cloud_api/test_aster_bollinger_entry_filter_timeframes.py", BACKEND_TEST)
    write("cloud_api/simulate_aster_bollinger_entry_timeframes.py", SIMULATION)


def main() -> None:
    patch_backend()
    patch_core()
    patch_card()
    patch_bridge()
    patch_tests()
    print("Applied selectable Bollinger entry timeframes: 1m,5m,15m,1h,4h,1d")


if __name__ == "__main__":
    main()
