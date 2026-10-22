"""Extreme Spike admission mathematics (read-only, no orders or API transport).

Uses the previous 20 completed candle closes (BB(20,k)). The current live price is checked
against that fixed band during the running candle; never use a historical wick as live evidence.
"""
from __future__ import annotations
from dataclasses import dataclass
import math
from typing import Any
import hashlib
import threading

# Spike 1.1 (besluit Amar 22-10): elk niveau betekent "vanaf k sigma" — BB(20,k) en
# alles daarbuiten. Geen bovengrens meer: een sprong voorbij het volgende niveau
# mag niet tot een gemiste instap leiden.
LEVELS = {"2": (2.0,None), "3": (3.0,None), "4": (4.0,None),
          "5": (5.0,None), "6": (6.0,None), "7": (7.0,None)}
# Waarden uit Spike 1.0 (vensters) worden gelezen als hun ondergrens.
LEGACY_LEVELS = {"2-3":"2", "3-4":"3", "4-5":"4", "5-6":"5", "6-7":"6", "7+":"7"}
DEFAULT_LEVEL = "5"
DEFAULT_TIMEFRAME = "15m"
TIMEFRAMES = ("1m","5m","15m","1h","4h","1d")


def normalize_level(raw: Any) -> str:
    """Canonieke niveaucode; onbekende waarden blijven staan zodat validatie ze weigert."""
    if raw is None or str(raw).strip() == "":
        return DEFAULT_LEVEL
    value = str(raw).strip()
    if value.endswith(".0"):
        value = value[:-2]
    return LEGACY_LEVELS.get(value, value)
MODES = ("OFF","BOLLINGER","EXTREME_SPIKE")

class SpikeFilterRejected(ValueError):
    def __init__(self, reason: str):
        self.reason = reason
        super().__init__(reason)

@dataclass(frozen=True)
class SpikeSnapshot:
    side: str
    level: str
    timeframe: str
    wick: float
    band: float
    score: float
    overshoot_pct: float
    candle_close_ms: int

def normalize_mode(raw: Any, legacy_bb_enabled: bool) -> str:
    if raw is None:
        return "BOLLINGER" if legacy_bb_enabled else "OFF"
    mode = str(raw).strip().upper()
    if mode not in MODES:
        raise ValueError("INVALID_ENTRY_FILTER_MODE")
    return mode

def validate_settings(*, mode: str, level: str, long_tf: str, short_tf: str, legacy_bb_enabled: bool) -> None:
    level = normalize_level(level)
    if mode not in MODES:
        raise ValueError("INVALID_ENTRY_FILTER_MODE")
    if level not in LEVELS:
        raise ValueError("INVALID_SPIKE_LEVEL")
    if long_tf not in TIMEFRAMES or short_tf not in TIMEFRAMES:
        raise ValueError("INVALID_SPIKE_TIMEFRAME")
    if mode == "EXTREME_SPIKE" and legacy_bb_enabled:
        raise ValueError("FILTERS_MUTUALLY_EXCLUSIVE")
    if mode == "BOLLINGER" and not legacy_bb_enabled:
        raise ValueError("BOLLINGER_FLAG_NOT_ENABLED")

def evaluate_spike(*, side: str, level: str, timeframe: str,
                   previous_closes: list[float], candle_high: float,
                   candle_low: float, candle_close_ms: int, now_ms: int,
                   max_staleness_ms: int) -> SpikeSnapshot:
    level = normalize_level(level)
    if side not in ("LONG","SHORT") or level not in LEVELS or timeframe not in TIMEFRAMES:
        raise SpikeFilterRejected("SPIKE_INVALID_SETTINGS")
    if len(previous_closes) != 20:
        raise SpikeFilterRejected("SPIKE_INSUFFICIENT_CANDLES")
    if candle_close_ms <= 0 or now_ms - candle_close_ms > max_staleness_ms or candle_close_ms - now_ms > max_staleness_ms:
        raise SpikeFilterRejected("SPIKE_STALE_OR_UNCLOSED")
    if not all(math.isfinite(v) and v > 0 for v in previous_closes):
        raise SpikeFilterRejected("SPIKE_BAD_CANDLES")
    if not (math.isfinite(candle_high) and math.isfinite(candle_low) and 0 < candle_low <= candle_high):
        raise SpikeFilterRejected("SPIKE_BAD_WICK")
    mean = sum(previous_closes)/20
    deviation = math.sqrt(sum((v-mean)**2 for v in previous_closes)/20)
    if not deviation > 0:
        raise SpikeFilterRejected("SPIKE_ZERO_VOLATILITY")
    wick = candle_low if side == "LONG" else candle_high
    score = (mean-wick)/deviation if side == "LONG" else (wick-mean)/deviation
    minimum,maximum = LEVELS[level]
    if score < minimum or (maximum is not None and score >= maximum):
        raise SpikeFilterRejected("SPIKE_OUTSIDE_SELECTED_RANGE")
    band = mean + (-2 if side == "LONG" else 2)*deviation
    if band <= 0:
        raise SpikeFilterRejected("SPIKE_INVALID_BAND")
    overshoot = (band-wick)/band if side == "LONG" else (wick-band)/band
    return SpikeSnapshot(side,level,timeframe,wick,band,score,100*overshoot,candle_close_ms)

INTERVAL_MS = {"1m":60000,"5m":300000,"15m":900000,"1h":3600000,"4h":14400000,"1d":86400000}

# Referentie-cache: de 20 afgesloten closes veranderen niet binnen een candle.
# Sleutel (symbol, timeframe) -> (vorige 20 closes, sluittijd lopende candle).
# Alleen in het geheugen van dit proces: geen Firestore, en per munt hooguit één
# klines-aanroep per candle in plaats van één per scan of realtime-evaluatie.
_REFERENCE_CACHE: dict[tuple[str, str], tuple[tuple[float, ...], int]] = {}
_REFERENCE_LOCK = threading.Lock()
_REFERENCE_CACHE_MAX = 6000


def cached_spike_reference(symbol: str, timeframe: str, now_ms: int) -> tuple[tuple[float, ...], int] | None:
    """Gecachte referentie als die nog voor de lopende candle geldt, anders None."""
    key = (str(symbol).upper(), timeframe)
    with _REFERENCE_LOCK:
        hit = _REFERENCE_CACHE.get(key)
    if hit is None or timeframe not in INTERVAL_MS:
        return None
    closes, live_close_ms = hit
    if not (live_close_ms - INTERVAL_MS[timeframe] < now_ms <= live_close_ms):
        return None
    return hit


def _store_reference(symbol: str, timeframe: str, closes: list[float], live_close_ms: int) -> None:
    with _REFERENCE_LOCK:
        if len(_REFERENCE_CACHE) >= _REFERENCE_CACHE_MAX:
            _REFERENCE_CACHE.clear()
        _REFERENCE_CACHE[(str(symbol).upper(), timeframe)] = (tuple(closes), int(live_close_ms))


def clear_reference_cache() -> None:
    with _REFERENCE_LOCK:
        _REFERENCE_CACHE.clear()


def require_extreme_spike_entry(client: Any, *, symbol: str, side: str, level: str,
                                timeframe: str, now_ms: int, live_price: float | None = None) -> SpikeSnapshot:
    """Fail-closed adapter: use fresh ticker price when supplied by scanner.

    The candidate gate and final pre-order gate must both call this same
    function. Transport uses the existing client, not another scanner.
    """
    if timeframe not in TIMEFRAMES:
        raise SpikeFilterRejected("SPIKE_INVALID_TIMEFRAME")
    interval_ms = INTERVAL_MS[timeframe]
    try:
        cached = cached_spike_reference(symbol, timeframe, now_ms) if live_price is not None else None
        if cached is not None:
            previous_closes, live_close_ms = list(cached[0]), cached[1]
            current_price = float(live_price)
        else:
            rows = client.klines(symbol=str(symbol).upper(), interval=timeframe, limit=23)
            if not isinstance(rows, list) or len(rows) < 22:
                raise SpikeFilterRejected("SPIKE_INSUFFICIENT_CANDLES")
            def close_ms(row: Any) -> int:
                return int(row[6] if isinstance(row, (list, tuple)) else row["closeTime"])
            def value(row: Any, position: int, key: str) -> float:
                return float(row[position] if isinstance(row, (list, tuple)) else row[key])
            # Reference is fixed to 20 completed candles. Evaluate the latest
            # in-progress candle's CURRENT traded/last price, not its historical wick:
            # a wick could have hit the level and already reversed before this scan.
            completed = [row for row in rows if close_ms(row) < now_ms]
            live = [row for row in rows if close_ms(row) >= now_ms]
            if len(completed) < 20 or not live:
                raise SpikeFilterRejected("SPIKE_INSUFFICIENT_LIVE_CANDLES")
            signal = live[-1]
            previous_closes = [value(row,4,"close") for row in completed[-20:]]
            live_close_ms = close_ms(signal)
            if live_close_ms - now_ms > interval_ms:
                raise SpikeFilterRejected("SPIKE_INVALID_LIVE_CANDLE")
            current_price = float(live_price) if live_price is not None else value(signal, 4, "close")
            if all(math.isfinite(v) and v > 0 for v in previous_closes):
                _store_reference(symbol, timeframe, previous_closes, live_close_ms)
        if not math.isfinite(current_price) or current_price <= 0:
            raise SpikeFilterRejected("SPIKE_INVALID_LIVE_PRICE")
        return evaluate_spike(side=side,level=level,timeframe=timeframe,
            previous_closes=previous_closes,
            candle_high=current_price,candle_low=current_price,
            candle_close_ms=live_close_ms,now_ms=now_ms,
            max_staleness_ms=interval_ms+300000)
    except SpikeFilterRejected:
        raise
    except Exception as exc:
        raise SpikeFilterRejected("SPIKE_DATA_UNAVAILABLE") from exc

def spike_event_key(*, symbol: str, side: str, timeframe: str, candle_close_ms: int) -> str:
    """Deterministic event identity, independent of scheduler tick or TP cycle.

    This is not sufficient by itself for exactly-once execution. The order
    executor must durably claim/check this key atomically before submission.
    """
    if side not in ("LONG","SHORT") or timeframe not in TIMEFRAMES or candle_close_ms <= 0:
        raise SpikeFilterRejected("SPIKE_INVALID_EVENT_IDENTITY")
    raw=f"{symbol.upper()}|{side}|{timeframe}|{candle_close_ms}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:32]

def claim_spike_entry_once(account_ref: Any, *, event_key: str, symbol: str,
                           side: str, timeframe: str, now_ms: int) -> None:
    """Atomically reserve a spike event within the existing account document tree.

    Firestore document.create is create-if-absent. Never automatically release
    an uncertain claim: missing an opportunity is safer than duplicate entry.
    The canonical order executor still performs the only order submission.
    """
    if not event_key or len(event_key) != 32:
        raise SpikeFilterRejected("SPIKE_INVALID_EVENT_IDENTITY")
    try:
        account_ref.collection("spikeEntryClaims").document(event_key).create({
            "eventId": event_key,
            "symbol": str(symbol).upper(),
            "side": side,
            "timeframe": timeframe,
            "claimedAtMs": int(now_ms),
            "status": "RESERVED",
        })
    except Exception as exc:
        # Includes ALREADY_EXISTS, transport uncertainty, and permission issues.
        # Never retry the claim or place an order when reservation is unclear.
        raise SpikeFilterRejected("SPIKE_EVENT_CLAIM_FAILED_OR_REPLAY") from exc


# ---------------------------------------------------------------------------
# Spike 1.1: instellingen per kant (besluiten Amar 22-10-2026)
# ---------------------------------------------------------------------------
SPIKE_TP_MIN_PCT = 0.1
SPIKE_TP_MAX_PCT = 50.0
DEFAULT_SPIKE_TP_PCT = 1.0
DEFAULT_TRAILING_PCT = 0.3


def _flag(raw: Any, default: bool) -> bool:
    if raw is None:
        return default
    if isinstance(raw, str):
        return raw.strip().lower() in {"1", "true", "yes", "on"}
    return bool(raw)


def _pct(raw: Any, default: float) -> float:
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return default
    return value if math.isfinite(value) else default


def spike_settings_from_mapping(raw: dict[str, Any] | None) -> dict[str, Any]:
    """Eén canonieke lezing van de Spike-instellingen, voor scanner én hercontrole.

    Standaard: niveau 5 (BB 20,5), tijdframe 15m, LONG aan, SHORT uit,
    Spike-TP 1 % koersbeweging, trailing uit (afstand 0,3 %).
    """
    raw = raw or {}
    out: dict[str, Any] = {
        "level": normalize_level(raw.get("extremeSpikeLevel")),
        "longTimeframe": str(raw.get("extremeSpikeLongTimeframe") or DEFAULT_TIMEFRAME),
        "shortTimeframe": str(raw.get("extremeSpikeShortTimeframe") or DEFAULT_TIMEFRAME),
        "longEnabled": _flag(raw.get("extremeSpikeLongEnabled"), True),
        "shortEnabled": _flag(raw.get("extremeSpikeShortEnabled"), False),
    }
    for side in ("Long", "Short"):
        out[f"{side.lower()}TakeProfitPct"] = _pct(raw.get(f"extremeSpike{side}TakeProfitPct"), DEFAULT_SPIKE_TP_PCT)
        out[f"{side.lower()}TrailingEnabled"] = _flag(raw.get(f"extremeSpike{side}TrailingEnabled"), False)
        out[f"{side.lower()}TrailingPct"] = _pct(raw.get(f"extremeSpike{side}TrailingPct"), DEFAULT_TRAILING_PCT)
    return out


def validate_side_settings(spike: dict[str, Any]) -> None:
    for side in ("long", "short"):
        tp = spike[f"{side}TakeProfitPct"]
        if not SPIKE_TP_MIN_PCT <= tp <= SPIKE_TP_MAX_PCT:
            raise ValueError("INVALID_SPIKE_TAKE_PROFIT")
        if spike[f"{side}TrailingEnabled"]:
            trail = spike[f"{side}TrailingPct"]
            # Terugval moet kleiner zijn dan de TP, anders kan trailing met verlies sluiten.
            if not 0 < trail < tp:
                raise ValueError("INVALID_SPIKE_TRAILING")


def spike_side_enabled(spike: dict[str, Any], side: str) -> bool:
    return bool(spike["longEnabled"] if side == "LONG" else spike["shortEnabled"])


def spike_band_price(previous_closes: list[float], *, side: str, level: str) -> float | None:
    """Vaste instapprijs voor de lopende candle: BB(20,k)-onder/bovenband.

    Hangt alleen af van de 20 afgesloten closes en ligt dus vast vanaf het begin
    van de candle. Gebruikt door de realtime-trigger; de beslissing zelf blijft
    via evaluate_spike lopen.
    """
    level = normalize_level(level)
    if level not in LEVELS or side not in ("LONG", "SHORT") or len(previous_closes) != 20:
        return None
    if not all(math.isfinite(v) and v > 0 for v in previous_closes):
        return None
    mean = sum(previous_closes) / 20
    deviation = math.sqrt(sum((v - mean) ** 2 for v in previous_closes) / 20)
    if not deviation > 0:
        return None
    k = LEVELS[level][0]
    price = mean - k * deviation if side == "LONG" else mean + k * deviation
    return price if price > 0 else None


SPIKE_SETTINGS_VERSION = 2


def effective_entry_filter_mode(raw: dict[str, Any] | None) -> str:
    """Eén waarheid voor OFF/BOLLINGER/EXTREME_SPIKE, ook bij oude of halve records.

    - De bestaande Bollinger-schakelaar (die de huidige app schrijft) wint altijd:
      aan = BOLLINGER. Zo kan een verouderde entryFilterMode uit de 1.0-uitrol van
      13-10 nooit een werkende Bollinger-instelling overschrijven of de tick laten falen.
    - EXTREME_SPIKE geldt alleen als hij door de 1.1-instellingen is opgeslagen
      (extremeSpikeSettingsVersion == 2). Een achtergebleven 1.0-waarde wordt OFF:
      Spike gaat nooit vanzelf aan bij een deploy.
    """
    raw = raw or {}
    if _flag(raw.get("bollingerEntryFilter15mEnabled", raw.get("bollinger_entry_filter_15m_enabled")), False):
        return "BOLLINGER"
    mode = str(raw.get("entryFilterMode") or "").strip().upper()
    try:
        version = int(raw.get("extremeSpikeSettingsVersion") or 0)
    except (TypeError, ValueError):
        version = 0
    if mode == "EXTREME_SPIKE" and version == SPIKE_SETTINGS_VERSION:
        return "EXTREME_SPIKE"
    return "OFF"


def warm_spike_reference(client: Any, *, symbol: str, timeframe: str, now_ms: int) -> bool:
    """Vul de referentie-cache voor de lopende candle (realtime-watcher op een ander proces).

    Gebruikt dezelfde klines-lezing als de scanner. Geeft False bij elk probleem;
    de watcher triggert dan simpelweg niet (fail-closed), de minuut-scan blijft werken.
    """
    if cached_spike_reference(symbol, timeframe, now_ms) is not None:
        return True
    try:
        # live_price is alleen nodig om de lezing te laten slagen; de beslissing
        # valt hier niet, dus elke positieve prijs volstaat.
        require_extreme_spike_entry(client, symbol=symbol, side="LONG", level="2",
                                    timeframe=timeframe, now_ms=now_ms, live_price=1e-12)
    except SpikeFilterRejected:
        pass
    return cached_spike_reference(symbol, timeframe, now_ms) is not None
