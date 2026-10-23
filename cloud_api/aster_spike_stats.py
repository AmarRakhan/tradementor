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
# Build 622: doorschiet-meting na een spike (vraag Amar 23-10 10:54: hoe ver schiet hij
# nog door na het instappunt, en hoeveel daling zit er vóór de TP → Auto Hedge-drempel).
TP_LEVELS_PCT = (0.5, 1.0, 2.0)
DRAWDOWN_EDGES_PCT = (0.1, 0.2, 0.3, 0.4, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0, 5.0)
EXCURSION_HORIZON_MS = 4 * 60 * 60 * 1000
EXCURSION_EXAMPLE_MIN_LEVEL = 4
MAX_ACTIVE_EXCURSIONS = 20_000
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


def drawdown_bucket(value_pct: float) -> str:
    """Kleinste grens waar de daling onder valt, bijv. 0,27 % → "0.3"; boven 5 % → "gt5"."""
    for edge in DRAWDOWN_EDGES_PCT:
        if value_pct <= edge + 1e-12:
            return f"{edge:g}"
    return "gt5"


def _tp_key(tp: float) -> str:
    return f"{tp:g}"


@dataclass
class _Excursion:
    side: str
    level: int
    timeframe: str
    entry: float
    start_ms: int
    tradable: bool
    max_adverse_pct: float = 0.0
    max_favorable_pct: float = 0.0
    drawdown_before_tp: dict[str, float | None] = field(
        default_factory=lambda: {_tp_key(tp): None for tp in TP_LEVELS_PCT})

    def update(self, price: float) -> None:
        move = (price - self.entry) / self.entry * 100.0
        favorable = move if self.side == "LONG" else -move
        self.max_adverse_pct = max(self.max_adverse_pct, -favorable)
        self.max_favorable_pct = max(self.max_favorable_pct, favorable)
        for tp in TP_LEVELS_PCT:
            key = _tp_key(tp)
            if self.drawdown_before_tp[key] is None and favorable >= tp:
                self.drawdown_before_tp[key] = self.max_adverse_pct

    def finished(self, now_ms: int) -> bool:
        return (all(v is not None for v in self.drawdown_before_tp.values())
                or now_ms - self.start_ms >= EXCURSION_HORIZON_MS)


def _empty_excursion_side() -> dict[str, Any]:
    return {str(k): {"count": 0, "tradable": 0,
                     "tp": {_tp_key(tp): {"reached": 0, "reachedTradable": 0,
                                         "drawdownBefore": {}, "drawdownBeforeTradable": {}}
                            for tp in TP_LEVELS_PCT},
                     "maxDrawdown": {}, "maxDrawdownTradable": {}}
            for k in LEVELS}


@dataclass
class _Bucket:
    candles: int = 0
    counts: dict[str, dict[str, dict[str, int]]] = field(default_factory=lambda: {
        side: {scope: {str(k): 0 for k in LEVELS} for scope in ("all", "tradable")}
        for side in ("LONG", "SHORT")})
    examples: list[dict[str, Any]] = field(default_factory=list)
    excursions: dict[str, dict[str, Any]] = field(default_factory=lambda: {
        "LONG": _empty_excursion_side(), "SHORT": _empty_excursion_side()})
    excursion_examples: list[dict[str, Any]] = field(default_factory=list)


class SpikeStats:
    def __init__(self, persist: Callable[[str, str, dict[str, Any]], None] | None = None,
                 clock: Callable[[], float] = time.monotonic) -> None:
        self._persist = persist
        self._clock = clock
        self._lock = threading.Lock()
        # (uid, symbol, timeframe, live_close_ms) -> _Peak
        self._open: dict[tuple[str, str, str, int], _Peak] = {}
        # (uid, symbol) -> {(side, level, timeframe): _Excursion}
        self._active: dict[tuple[str, str], dict[tuple[str, int, str], _Excursion]] = {}
        self._active_count = 0
        self._done: list[tuple[str, str, _Excursion]] = []
        self._last_flush = clock()

    def observe(self, *, uid: str, symbol: str, timeframe: str, closes: Iterable[float],
                live_close_ms: int, price: float, tradable_long: bool, tradable_short: bool,
                now_ms: int | None = None) -> None:
        if not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0):
            return
        now_ms = int(time.time() * 1000) if now_ms is None else int(now_ms)
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
            long_sigma = (peak.mean - price) / peak.deviation
            short_sigma = (price - peak.mean) / peak.deviation
            peak.long_sigma = max(peak.long_sigma, long_sigma)
            peak.short_sigma = max(peak.short_sigma, short_sigma)
            # Build 622: lopende doorschiet-metingen bijwerken, daarna nieuwe starten.
            active = self._active.setdefault((uid, symbol), {})
            for track_key, track in list(active.items()):
                track.update(price)
                if track.finished(now_ms):
                    del active[track_key]
                    self._active_count -= 1
                    self._done.append((uid, symbol, track))
            for side, sigma, tradable in (("LONG", long_sigma, tradable_long), ("SHORT", short_sigma, tradable_short)):
                for level in LEVELS:
                    track_key = (side, level, timeframe)
                    if sigma >= level and track_key not in active and self._active_count < MAX_ACTIVE_EXCURSIONS:
                        active[track_key] = _Excursion(side, level, timeframe, float(price), now_ms, bool(tradable))
                        self._active_count += 1

    def _collect(self, now_ms: int) -> dict[tuple[str, str], dict[str, _Bucket]]:
        """Haal afgelopen candles uit het geheugen; gegroepeerd per (uid, uur) en tijdframe."""
        with self._lock:
            done = [key for key in self._open if key[3] <= now_ms]
            finished = [(key, self._open.pop(key)) for key in done]
            # Metingen van munten die geen prijs meer krijgen, sluiten op de horizon.
            for pair, active in list(self._active.items()):
                for track_key, track in list(active.items()):
                    if track.finished(now_ms):
                        del active[track_key]
                        self._active_count -= 1
                        self._done.append((pair[0], pair[1], track))
                if not active:
                    del self._active[pair]
            excursions, self._done = self._done, []
        grouped: dict[tuple[str, str], dict[str, _Bucket]] = {}
        for uid, symbol, track in excursions:
            bucket = grouped.setdefault((uid, hour_key(track.start_ms)), {}).setdefault(track.timeframe, _Bucket())
            row = bucket.excursions[track.side][str(track.level)]
            row["count"] += 1
            row["tradable"] += int(track.tradable)
            for tp_key, drawdown in track.drawdown_before_tp.items():
                if drawdown is None:
                    continue
                cell = row["tp"][tp_key]
                label = drawdown_bucket(drawdown)
                cell["reached"] += 1
                cell["drawdownBefore"][label] = cell["drawdownBefore"].get(label, 0) + 1
                if track.tradable:
                    cell["reachedTradable"] += 1
                    cell["drawdownBeforeTradable"][label] = cell["drawdownBeforeTradable"].get(label, 0) + 1
            label = drawdown_bucket(track.max_adverse_pct)
            row["maxDrawdown"][label] = row["maxDrawdown"].get(label, 0) + 1
            if track.tradable:
                row["maxDrawdownTradable"][label] = row["maxDrawdownTradable"].get(label, 0) + 1
            if track.level >= EXCURSION_EXAMPLE_MIN_LEVEL and len(bucket.excursion_examples) < MAX_EXAMPLES_PER_FLUSH:
                bucket.excursion_examples.append({
                    "symbol": symbol, "side": track.side, "level": track.level, "timeframe": track.timeframe,
                    "entry": track.entry, "startMs": track.start_ms, "tradable": track.tradable,
                    "maxDrawdownPct": round(track.max_adverse_pct, 3),
                    "maxGainPct": round(track.max_favorable_pct, 3),
                    "drawdownBeforeTpPct": {k: (None if v is None else round(v, 3))
                                            for k, v in track.drawdown_before_tp.items()}})
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
            payload = {timeframe: {"candles": bucket.candles, "counts": bucket.counts, "examples": bucket.examples,
                                   "excursions": bucket.excursions, "excursionExamples": bucket.excursion_examples}
                       for timeframe, bucket in timeframes.items()}
            try:
                self._persist(uid, hour, payload)
                written += 1
            except Exception as exc:  # statistiek is best effort; de handel gaat altijd voor
                print(f"SPIKE_STATS_PERSIST_FAILED {exc}", flush=True)
        return written


def _increments(tree: Any, increment: Callable[[int], Any]) -> Any:
    """Geneste tellers → Increment; nullen en lege takken vallen weg (minder schrijfdata)."""
    if isinstance(tree, dict):
        out = {k: _increments(v, increment) for k, v in tree.items()}
        return {k: v for k, v in out.items() if v not in ({}, None)}
    if isinstance(tree, bool):
        return None
    if isinstance(tree, int):
        return increment(tree) if tree else None
    return None


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
            excursions = _increments(data.get("excursions") or {}, increment)
            if excursions:
                entry["excursions"] = excursions
            if data.get("excursionExamples"):
                entry["excursionExamples"] = array_union(data["excursionExamples"])
            doc["timeframes"][timeframe] = entry
        (db.collection("asterStrategy2").document(uid).collection("spikeStats")
           .document(f"{hour}_{INSTANCE_ID}").set(doc, merge=True))
    return persist
