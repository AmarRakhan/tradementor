from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def replace_once(path: str, old: str, new: str) -> None:
    file = ROOT / path
    text = file.read_text()
    if old not in text:
        raise SystemExit(f"anchor not found in {path}: {old[:100]!r}")
    if text.count(old) != 1:
        raise SystemExit(f"anchor not unique in {path}: {old[:100]!r}")
    file.write_text(text.replace(old, new, 1))


helper = r'''from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math
import time

TIMEFRAME = "15m"
PERIOD = 20
STDDEV_MULTIPLIER = 2.0
MAX_KLINE_AGE_MS = 20 * 60 * 1000
CACHE_TTL_SECONDS = 5.0


@dataclass(frozen=True)
class BollingerEntrySnapshot:
    symbol: str
    side: str
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


_BAND_CACHE: dict[str, tuple[float, float, float, int]] = {}


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


def _current_bands(client: Any, symbol: str, *, now_ms: int, force_refresh: bool) -> tuple[float, float, int]:
    symbol = str(symbol).upper()
    cached = _BAND_CACHE.get(symbol)
    if not force_refresh and cached and time.monotonic() - cached[0] <= CACHE_TTL_SECONDS:
        return cached[1], cached[2], cached[3]
    rows = client.klines(symbol=symbol, interval=TIMEFRAME, limit=25)
    if not isinstance(rows, list) or len(rows) < PERIOD:
        raise ValueError("insufficient 15m klines")
    window = rows[-PERIOD:]
    closes = [_row_close(row) for row in window]
    latest_open_ms = _row_open_ms(window[-1])
    if latest_open_ms <= 0 or latest_open_ms > now_ms + 60_000 or now_ms - latest_open_ms > MAX_KLINE_AGE_MS:
        raise ValueError("stale 15m kline")
    mean = sum(closes) / PERIOD
    variance = sum((value - mean) ** 2 for value in closes) / PERIOD
    sigma = math.sqrt(max(0.0, variance))
    lower = mean - STDDEV_MULTIPLIER * sigma
    upper = mean + STDDEV_MULTIPLIER * sigma
    if lower <= 0 or upper <= 0 or lower > upper:
        raise ValueError("invalid 15m Bollinger bands")
    _BAND_CACHE[symbol] = (time.monotonic(), lower, upper, latest_open_ms)
    return lower, upper, latest_open_ms


def _latest_price(client: Any, symbol: str) -> float:
    payload = client.ticker_price(symbol=str(symbol).upper())
    if not isinstance(payload, dict):
        raise ValueError("invalid live ticker")
    price = _finite(payload.get("price"))
    if price <= 0:
        raise ValueError("invalid live price")
    return price


def _event(side: str, passed: bool) -> str:
    return f"BB_ENTRY_FILTER_{side}_{'PASS' if passed else 'REJECT'}"


def _log(*, symbol: str, side: str, live_price: float | None, lower: float | None, upper: float | None,
         checked_at_ms: int, stage: str, passed: bool, reason: str) -> None:
    print(
        f"{_event(side, passed)} symbol={symbol} side={side} livePrice={live_price if live_price is not None else 'NA'} "
        f"lowerBand={lower if lower is not None else 'NA'} upperBand={upper if upper is not None else 'NA'} "
        f"timeframe={TIMEFRAME} timestampMs={checked_at_ms} enabled=true stage={stage} result={'PASS' if passed else 'REJECT'} reason={reason}",
        flush=True,
    )


def require_bollinger_entry(client: Any, *, symbol: str, side: str, enabled: bool,
                            live_price: float | None = None, force_refresh: bool = False,
                            stage: str = "candidate", now_ms: int | None = None) -> BollingerEntrySnapshot | None:
    """Fail closed for one NEW primary entry; disabled mode is a true no-op.

    15m klines define the bands. The decision uses a live/current price and does
    not wait for a candle close. Strict inequalities intentionally reject exact
    equality with the relevant band.
    """
    if not enabled:
        return None
    symbol = str(symbol).upper()
    side = str(side).upper()
    if side not in {"LONG", "SHORT"}:
        raise BollingerEntryRejected("BB_INVALID_SIDE", symbol, side)
    checked_at_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
    try:
        lower, upper, latest_open_ms = _current_bands(client, symbol, now_ms=checked_at_ms, force_refresh=force_refresh)
        price = _latest_price(client, symbol) if live_price is None else _finite(live_price)
        if price <= 0:
            raise ValueError("invalid live price")
    except Exception as exc:
        _log(symbol=symbol, side=side, live_price=None, lower=None, upper=None, checked_at_ms=checked_at_ms,
             stage=stage, passed=False, reason="BB_DATA_UNAVAILABLE_OR_STALE")
        raise BollingerEntryRejected("BB_DATA_UNAVAILABLE_OR_STALE", symbol, side) from exc
    snapshot = BollingerEntrySnapshot(symbol, side, price, lower, upper, latest_open_ms, checked_at_ms)
    passed = price < lower if side == "LONG" else price > upper
    reason = "PRICE_BELOW_LOWER_BAND" if side == "LONG" and passed else \
             "PRICE_ABOVE_UPPER_BAND" if side == "SHORT" and passed else \
             "PRICE_NOT_BELOW_LOWER_BAND" if side == "LONG" else "PRICE_NOT_ABOVE_UPPER_BAND"
    _log(symbol=symbol, side=side, live_price=price, lower=lower, upper=upper, checked_at_ms=checked_at_ms,
         stage=stage, passed=passed, reason=reason)
    if not passed:
        raise BollingerEntryRejected(reason, symbol, side, snapshot)
    return snapshot
'''
(ROOT / "cloud_api/aster_bollinger_entry_filter.py").write_text(helper)

# Core config: persisted/public default false and a single central gate for every new primary seat.
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "from aster_close_guard import CloseEvidence, AsterCloseBlocked\n",
    "from aster_close_guard import CloseEvidence, AsterCloseBlocked\nfrom aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "    minimum_leverage: int = 50\n    entry_margin_usd: float = 5.0\n",
    "    minimum_leverage: int = 50\n    bollinger_entry_filter_15m_enabled: bool = False\n    entry_margin_usd: float = 5.0\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "            minimum_leverage=minimum_leverage,\n            entry_margin_usd=entry_margin_usd,\n",
    "            minimum_leverage=minimum_leverage,\n            bollinger_entry_filter_15m_enabled=bool(raw.get(\"bollingerEntryFilter15mEnabled\", raw.get(\"bollinger_entry_filter_15m_enabled\", False))),\n            entry_margin_usd=entry_margin_usd,\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "            \"longSlots\": self.long_slots, \"shortSlots\": self.short_slots, \"minimumLeverage\": self.minimum_leverage,\n",
    "            \"longSlots\": self.long_slots, \"shortSlots\": self.short_slots, \"minimumLeverage\": self.minimum_leverage,\n            \"bollingerEntryFilter15mEnabled\": self.bollinger_entry_filter_15m_enabled,\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "        paired = bool(settings.asymmetric_hedge_enabled)\n",
    "        if settings.bollinger_entry_filter_15m_enabled:\n            try:\n                require_bollinger_entry(client, symbol=symbol, side=side, enabled=True, live_price=prices[symbol],\n                                        force_refresh=False, stage=\"candidate\", now_ms=timestamp_ms)\n            except BollingerEntryRejected as exc:\n                actions.append({\"kind\": \"ENTRY_SKIP\", \"symbol\": symbol, \"side\": side, \"reason\": exc.reason_code, \"bollingerEntryFilter15m\": True})\n                continue\n        paired = bool(settings.asymmetric_hedge_enabled)\n",
)
replace_once(
    "cloud_api/aster_multi_bb_core.py",
    "        else:\n            try:\n                result = execute_leg_once(client, plan, side=PositionSide(side), action=\"OPEN\", id_prefix=f\"mbb-open-{hashlib.sha256((uid+symbol+side+str(timestamp_ms)).encode()).hexdigest()[:12]}\", confirm=True,\n                                          new_position_leverage=plan.leverage, before_submit=before_order)\n            except NewPositionLeverageBlocked as exc:\n",
    "        else:\n            def entry_before_submit(intent: Any) -> None:\n                require_bollinger_entry(client, symbol=symbol, side=side, enabled=settings.bollinger_entry_filter_15m_enabled,\n                                        live_price=None, force_refresh=True, stage=\"pre_order\")\n                if before_order is not None:\n                    before_order(intent)\n            try:\n                result = execute_leg_once(client, plan, side=PositionSide(side), action=\"OPEN\", id_prefix=f\"mbb-open-{hashlib.sha256((uid+symbol+side+str(timestamp_ms)).encode()).hexdigest()[:12]}\", confirm=True,\n                                          new_position_leverage=plan.leverage, before_submit=entry_before_submit)\n            except BollingerEntryRejected as exc:\n                actions.append({\"kind\": \"ENTRY_SKIP\", \"symbol\": symbol, \"side\": side, \"reason\": exc.reason_code, \"bollingerEntryFilter15m\": True, \"stage\": \"pre_order\"})\n                continue\n            except NewPositionLeverageBlocked as exc:\n",
)

card = r'''"use client";

type Props = {
  enabled: boolean;
  busy: boolean;
  message?: string;
  onToggle: (next: boolean) => void;
};

export const BOLLINGER_ENTRY_FILTER_REFERENCE = "file_00000000409081f49fd5473a5a7ee770";

export function AsterBollingerEntryFilter15mCard({ enabled, busy, message, onToggle }: Props) {
  return <section className="bb-entry-filter-card" data-reference={BOLLINGER_ENTRY_FILTER_REFERENCE} aria-label="Bollinger instapfilter 15m">
    <div className="bb-entry-copy">
      <div className="bb-entry-title-row"><span className="bb-entry-new">NEW</span><strong>Bollinger instapfilter 15m</strong></div>
      <p>Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band.</p>
      <small>Live prijs vs 15m Bollinger Bands · optioneel</small>
      {message ? <em>{message}</em> : null}
    </div>
    <button type="button" className={`bb-entry-toggle ${enabled ? "is-on" : "is-off"}`} role="switch" aria-checked={enabled} disabled={busy}
      onClick={() => onToggle(!enabled)}>
      <span>OFF</span><i aria-hidden="true" /><span>ON</span>
    </button>
    <style>{`.bb-entry-filter-card{grid-column:1/-1;display:grid;grid-template-columns:minmax(0,1fr) auto;align-items:center;gap:12px;width:100%;min-width:0;padding:10px 11px;border:1px solid rgba(37,224,155,.34);border-radius:11px;background:linear-gradient(100deg,rgba(4,31,22,.91),rgba(3,18,13,.94));box-shadow:inset 0 0 20px rgba(38,226,157,.025)}.bb-entry-copy{min-width:0;display:grid;gap:3px}.bb-entry-title-row{display:flex;align-items:center;gap:6px;min-width:0}.bb-entry-title-row strong{color:#e9f5ef;font-size:10px;font-weight:900;letter-spacing:.01em}.bb-entry-new{display:inline-flex;align-items:center;justify-content:center;height:15px;padding:0 5px;border:1px solid rgba(47,239,169,.6);border-radius:4px;background:rgba(17,114,76,.28);color:#52f1b1;font-size:6px;font-weight:1000;letter-spacing:.08em}.bb-entry-copy p{margin:0;color:#a9b9b1;font-size:8px;line-height:1.35}.bb-entry-copy small{color:#5e8978;font-size:7px;line-height:1.3}.bb-entry-copy em{color:#75c9a5;font-size:6.5px;font-style:normal;line-height:1.25}.bb-entry-toggle{display:grid;grid-template-columns:auto 19px auto;align-items:center;gap:4px;min-width:76px;height:30px;padding:0 7px;border:1px solid rgba(62,110,89,.55);border-radius:16px;background:rgba(2,10,8,.75);color:#60746a;font-size:6px;font-weight:1000;letter-spacing:.08em;transition:.16s ease}.bb-entry-toggle i{position:relative;width:19px;height:12px;border-radius:8px;background:#26372f;box-shadow:inset 0 0 0 1px rgba(109,143,126,.24)}.bb-entry-toggle i:after{content:"";position:absolute;top:2px;left:2px;width:8px;height:8px;border-radius:50%;background:#8c9b94;transition:.16s ease}.bb-entry-toggle.is-on{border-color:rgba(43,236,165,.72);color:#45eca9;box-shadow:0 0 12px rgba(43,236,165,.08)}.bb-entry-toggle.is-on i{background:rgba(31,190,130,.42)}.bb-entry-toggle.is-on i:after{left:9px;background:#48f0ad;box-shadow:0 0 7px rgba(72,240,173,.42)}.bb-entry-toggle:disabled{opacity:.55}@media(max-width:430px){.bb-entry-filter-card{gap:8px;padding:9px}.bb-entry-copy p{max-width:245px}.bb-entry-toggle{min-width:72px;padding:0 6px}}`}</style>
  </section>;
}
'''
(ROOT / "web/components/aster-bollinger-entry-filter-15m-card.tsx").write_text(card)

replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    'import { authenticatedRequest } from "@/lib/cloud-client";\n',
    'import { authenticatedRequest } from "@/lib/cloud-client";\nimport { AsterBollingerEntryFilter15mCard } from "./aster-bollinger-entry-filter-15m-card";\n',
)
replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    '  const [detailOpen, setDetailOpen] = useState(false);\n',
    '  const [detailOpen, setDetailOpen] = useState(false);\n  const [bbEnabled, setBbEnabled] = useState(false);\n  const [bbBusy, setBbBusy] = useState(false);\n  const [bbMessage, setBbMessage] = useState("");\n',
)
replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    '      setSettings(next.settings);\n      setSummary(next.summary);\n',
    '      setSettings(next.settings);\n      setSummary(next.summary);\n      if (!bbBusy) setBbEnabled(next.settings.bollingerEntryFilter15mEnabled === true);\n',
)
replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    '  }, [dirty]);\n',
    '  }, [dirty, bbBusy]);\n',
)
replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    '  async function save() {\n',
    '''  async function toggleBollingerEntryFilter(next: boolean) {\n    if (bbBusy) return;\n    const previous = bbEnabled;\n    setBbEnabled(next); setBbBusy(true); setBbMessage("Opslaan…");\n    try {\n      const latestSnapshot = await authenticatedRequest("/api/exchanges/aster", { cache: "no-store" }) as Record<string, unknown>;\n      const latestSettings = extract(latestSnapshot).settings;\n      const nextSettings = { ...latestSettings, bollingerEntryFilter15mEnabled: next };\n      const response = await authenticatedRequest("/api/exchanges/aster/strategy2/settings", {\n        method: "PUT",\n        body: JSON.stringify({ settings: nextSettings }),\n      }) as Record<string, unknown>;\n      const strategy2 = response.strategy2 && typeof response.strategy2 === "object" ? response.strategy2 as Record<string, unknown> : {};\n      const saved = strategy2.settings && typeof strategy2.settings === "object" ? strategy2.settings as Record<string, unknown> : nextSettings;\n      const confirmed = saved.bollingerEntryFilter15mEnabled === true;\n      setSettings(saved); setBbEnabled(confirmed);\n      setBbMessage(confirmed ? "ON · nieuwe primaire stoelen worden gefilterd." : "OFF · bestaande entrylogica blijft ongewijzigd.");\n      window.dispatchEvent(new Event("aster-strategy2-settings-changed"));\n    } catch (error) {\n      setBbEnabled(previous);\n      setBbMessage(error instanceof Error ? error.message : "Bollinger instapfilter kon niet worden opgeslagen.");\n    } finally { setBbBusy(false); }\n  }\n\n  async function save() {\n''',
)
replace_once(
    "web/components/aster-profit-lock-ladder-bridge.tsx",
    '  const settingsUi = settingsHost ? createPortal(<div className="pll-bridge-wrap" data-reference={REFERENCE}>\n    <AsterProfitLockLadderPanel enabled={enabled}',
    '  const settingsUi = settingsHost ? createPortal(<div className="pll-bridge-wrap" data-reference={REFERENCE}>\n    <AsterBollingerEntryFilter15mCard enabled={bbEnabled} busy={bbBusy} message={bbMessage} onToggle={(next) => void toggleBollingerEntryFilter(next)} />\n    <AsterProfitLockLadderPanel enabled={enabled}',
)

backend_tests = r'''from __future__ import annotations

import time
import pytest

from aster_bollinger_entry_filter import BollingerEntryRejected, require_bollinger_entry
from aster_multi_bb_core import MultiBbConfig


class FakeMarket:
    def __init__(self, closes, price, *, open_ms=None):
        self.closes = list(closes)
        self.price = float(price)
        self.open_ms = int(open_ms if open_ms is not None else time.time() * 1000 // 900_000 * 900_000)
        self.kline_calls = 0
        self.ticker_calls = 0

    def klines(self, *, symbol, interval, limit):
        assert interval == "15m" and limit == 25
        self.kline_calls += 1
        start = self.open_ms - (len(self.closes) - 1) * 900_000
        return [[start + i * 900_000, "0", "0", "0", str(close), "0"] for i, close in enumerate(self.closes)]

    def ticker_price(self, *, symbol):
        self.ticker_calls += 1
        return {"symbol": symbol, "price": str(self.price)}


def bands(closes):
    mean = sum(closes[-20:]) / 20
    sigma = (sum((x - mean) ** 2 for x in closes[-20:]) / 20) ** .5
    return mean - 2 * sigma, mean + 2 * sigma


def test_config_defaults_off_and_roundtrips_true():
    off = MultiBbConfig.from_mapping({})
    assert off.bollinger_entry_filter_15m_enabled is False
    assert off.public_dict()["bollingerEntryFilter15mEnabled"] is False
    on = MultiBbConfig.from_mapping({"bollingerEntryFilter15mEnabled": True})
    assert on.bollinger_entry_filter_15m_enabled is True
    assert on.public_dict()["bollingerEntryFilter15mEnabled"] is True


def test_disabled_is_true_noop_and_makes_no_market_calls():
    market = FakeMarket(range(81, 101), 80)
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=False) is None
    assert market.kline_calls == 0 and market.ticker_calls == 0


def test_long_is_strictly_below_lower_band_only():
    closes = list(range(81, 101)); lower, _ = bands(closes); market = FakeMarket(closes, lower - .001)
    assert require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower - .001, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="BTCUSDT", side="LONG", enabled=True, live_price=lower + .001, force_refresh=True)


def test_short_is_strictly_above_upper_band_only():
    closes = list(range(81, 101)); _, upper = bands(closes); market = FakeMarket(closes, upper + .001)
    assert require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper + .001, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="ETHUSDT", side="SHORT", enabled=True, live_price=upper - .001, force_refresh=True)


def test_intrabar_price_can_change_from_reject_to_pass_without_candle_close():
    closes = list(range(81, 101)); lower, upper = bands(closes); market = FakeMarket(closes, (lower + upper) / 2)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="SOLUSDT", side="LONG", enabled=True, live_price=(lower + upper) / 2, force_refresh=True)
    assert require_bollinger_entry(market, symbol="SOLUSDT", side="LONG", enabled=True, live_price=lower - .01, force_refresh=True)
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="SOLUSDT", side="SHORT", enabled=True, live_price=(lower + upper) / 2, force_refresh=True)
    assert require_bollinger_entry(market, symbol="SOLUSDT", side="SHORT", enabled=True, live_price=upper + .01, force_refresh=True)


def test_preorder_forces_fresh_live_price_and_rejects_stale_pass():
    closes = list(range(81, 101)); lower, upper = bands(closes); market = FakeMarket(closes, lower - 1)
    assert require_bollinger_entry(market, symbol="XRPUSDT", side="LONG", enabled=True, force_refresh=True, stage="candidate")
    market.price = (lower + upper) / 2
    with pytest.raises(BollingerEntryRejected): require_bollinger_entry(market, symbol="XRPUSDT", side="LONG", enabled=True, force_refresh=True, stage="pre_order")
    assert market.ticker_calls == 2


def test_stale_15m_data_fails_closed():
    old = int(time.time() * 1000) - 25 * 60 * 1000
    market = FakeMarket(range(81, 101), 70, open_ms=old)
    with pytest.raises(BollingerEntryRejected) as exc: require_bollinger_entry(market, symbol="DOGEUSDT", side="LONG", enabled=True, force_refresh=True)
    assert exc.value.reason_code == "BB_DATA_UNAVAILABLE_OR_STALE"
'''
(ROOT / "cloud_api/test_aster_bollinger_entry_filter.py").write_text(backend_tests)

web_test = r'''import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

const bridge = readFileSync(new URL("../components/aster-profit-lock-ladder-bridge.tsx", import.meta.url), "utf8");
const card = readFileSync(new URL("../components/aster-bollinger-entry-filter-15m-card.tsx", import.meta.url), "utf8");

test("Bollinger entry filter reference and approved copy are present above Profit Lock", () => {
  assert.match(card, /file_00000000409081f49fd5473a5a7ee770/);
  assert.match(card, /Bollinger instapfilter 15m/);
  assert.match(card, /Open LONG alleen onder de onderste band en SHORT alleen boven de bovenste band\./);
  assert.match(card, /Live prijs vs 15m Bollinger Bands · optioneel/);
  const bb = bridge.indexOf("<AsterBollingerEntryFilter15mCard");
  const pll = bridge.indexOf("<AsterProfitLockLadderPanel");
  assert.ok(bb >= 0 && pll > bb, "Bollinger card must render immediately before Profit Lock Ladder");
});

test("toggle persists only explicit per-user boolean and defaults visually off", () => {
  assert.match(bridge, /bollingerEntryFilter15mEnabled === true/);
  assert.match(bridge, /bollingerEntryFilter15mEnabled: next/);
  assert.match(bridge, /useState\(false\)/);
});
'''
(ROOT / "web/tests/aster-bollinger-entry-filter-15m.test.mjs").write_text(web_test)

print("Bollinger entry filter patch applied")
