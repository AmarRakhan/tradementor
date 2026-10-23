"""Build 621: Spike-statistiek per niveau (vraag Amar 23-10-2026).

Doel: achteraf kunnen zeggen hoeveel kandidaten er waren per niveau 20,2 · 20,3 · …
· 20,7+, los van het niveau dat nu is ingesteld.

Werking (alleen rekenwerk in het geheugen, geen REST-calls)
- De realtime-trigger ziet elke seconde de markprijs van elke bewaakte munt en kent
  de vaste referentie (20 afgesloten closes) van de lopende candle.
- Per munt, kant en candle wordt de diepste afwijking in sigma bijgehouden:
  LONG = (gemiddelde − prijs) / sd, SHORT = (prijs − gemiddelde) / sd.
- Is de candle afgelopen, dan telt hij mee: "≥ k" voor k = 2…7 (7 = 7 en hoger).
  Twee tellingen: álle bewaakte munten, en "verhandelbaar" (genoeg hefboom volgens de
  scanner én nog geen open positie op die kant).
- Elke minuut één schrijfactie per account: optellers per uur in
  ``asterStrategy2/{uid}/spikeStats/{YYYYMMDDHH}_{instantie}``. Bij meerdere
  instanties bestaat er per instantie een document; de lezer neemt dan de grootste.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
import math
import os
import secrets
import threading
import time
from typing import Any, Callable, Iterable

LEVELS = (2, 3, 4, 5, 6, 7)
EXAMPLE_MIN_SIGMA = 4.0
MAX_EXAMPLES_PER_FLUSH = 60
FLUSH_INTERVAL_SECONDS = 60.0
MAX_OPEN_ENTRIES = 50_000

INSTANCE_ID = (os.getenv("K_REVISION", "local")[-12:] + "-" + secrets.token_hex(3)).replace("/", "-")


def reference_stats(closes: Iterable[float]) -> tuple[float, float] | None:
    values = [float(v) for v in closes]
    if len(values) != 20 or not all(math.isfinite(v) and v > 0 for v in values):
        return None
    mean = sum(values) / 20
    deviation = math.sqrt(sum((v - mean) ** 2 for v in values) / 20)
    return (mean, deviation) if deviation > 0 else None


def hour_key(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, timezone.utc).strftime("%Y%m%d%H")


@dataclass
class _Peak:
    mean: float
    deviation: float
    tradable_long: bool
    tradable_short: bool
    long_sigma: float = float("-inf")
    short_sigma: float = float("-inf")


@dataclass
class _Bucket:
    candles: int = 0
    counts: dict[str, dict[str, dict[str, int]]] = field(default_factory=lambda: {
        side: {scope: {str(k): 0 for k in LEVELS} for scope in ("all", "tradable")}
        for side in ("LONG", "SHORT")})
    examples: list[dict[str, Any]] = field(default_factory=list)


class SpikeStats:
    def __init__(self, persist: Callable[[str, str, dict[str, Any]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._persist = persist
        self._clock = clock
        self._lock = threading.Lock()
        # (uid, symbol, timeframe, live_close_ms) -> _Peak
        self._open: dict[tuple[str, str, str, int], _Peak] = {}
        self._last_flush = clock()

    def observe(self, *, uid: str, symbol: str, timeframe: str, closes: Iterable[float],
                live_close_ms: int, price: float, tradable_long: bool, tradable_short: bool) -> None:
        if not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0):
            return
        key = (uid, symbol, timeframe, int(live_close_ms))
        with self._lock:
            peak = self._open.get(key)
            if peak is None:
                stats = reference_stats(closes)
                if stats is None:
                    return
                if len(self._open) >= MAX_OPEN_ENTRIES:
                    return
                peak = _Peak(stats[0], stats[1], bool(tradable_long), bool(tradable_short))
                self._open[key] = peak
            peak.long_sigma = max(peak.long_sigma, (peak.mean - price) / peak.deviation)
            peak.short_sigma = max(peak.short_sigma, (price - peak.mean) / peak.deviation)

    def _collect(self, now_ms: int) -> dict[tuple[str, str], dict[str, _Bucket]]:
        """Haal afgelopen candles uit het geheugen; gegroepeerd per (uid, uur) en tijdframe."""
        with self._lock:
            done = [key for key in self._open if key[3] <= now_ms]
            finished = [(key, self._open.pop(key)) for key in done]
        grouped: dict[tuple[str, str], dict[str, _Bucket]] = {}
        for (uid, symbol, timeframe, close_ms), peak in finished:
            bucket = grouped.setdefault((uid, hour_key(close_ms)), {}).setdefault(timeframe, _Bucket())
            bucket.candles += 1
            for side, sigma, tradable in (("LONG", peak.long_sigma, peak.tradable_long),
                                          ("SHORT", peak.short_sigma, peak.tradable_short)):
                for level in LEVELS:
                    if sigma >= level:
                        bucket.counts[side]["all"][str(level)] += 1
                        if tradable:
                            bucket.counts[side]["tradable"][str(level)] += 1
                if sigma >= EXAMPLE_MIN_SIGMA and len(bucket.examples) < MAX_EXAMPLES_PER_FLUSH:
                    bucket.examples.append({"symbol": symbol, "side": side, "timeframe": timeframe,
                                            "sigma": round(sigma, 2), "candleCloseMs": close_ms,
                                            "tradable": tradable})
        return grouped

    def maybe_flush(self, now_ms: int, *, force: bool = False) -> int:
        """Schrijf afgelopen candles weg (hooguit eens per minuut). Geeft het aantal documenten terug."""
        if self._persist is None:
            return 0
        if not force and self._clock() - self._last_flush < FLUSH_INTERVAL_SECONDS:
            return 0
        self._last_flush = self._clock()
        written = 0
        for (uid, hour), timeframes in self._collect(now_ms).items():
            payload = {timeframe: {"candles": bucket.candles, "counts": bucket.counts, "examples": bucket.examples}
                       for timeframe, bucket in timeframes.items()}
            try:
                self._persist(uid, hour, payload)
                written += 1
            except Exception as exc:  # statistiek is best effort; de handel gaat altijd voor
                print(f"SPIKE_STATS_PERSIST_FAILED {exc}", flush=True)
        return written


def firestore_persister(db: Any, increment: Callable[[int], Any], array_union: Callable[[list], Any],
                        server_now: Callable[[], datetime] = lambda: datetime.now(timezone.utc)):
    """Maak de persist-functie voor Firestore (optellers met Increment, voorbeelden met ArrayUnion)."""
    def persist(uid: str, hour: str, payload: dict[str, Any]) -> None:
        doc: dict[str, Any] = {"hour": hour, "instance": INSTANCE_ID, "updatedAt": server_now(),
                               "levels": [f"20,{k}" for k in LEVELS], "timeframes": {}}
        for timeframe, data in payload.items():
            counts = {side: {scope: {level: increment(value) for level, value in levels.items() if value}
                             for scope, levels in scopes.items()}
                      for side, scopes in data["counts"].items()}
            entry: dict[str, Any] = {"candles": increment(data["candles"]), "counts": counts}
            if data["examples"]:
                entry["examples"] = array_union(data["examples"])
            doc["timeframes"][timeframe] = entry
        (db.collection("asterStrategy2").document(uid).collection("spikeStats")
           .document(f"{hour}_{INSTANCE_ID}").set(doc, merge=True))
    return persist
