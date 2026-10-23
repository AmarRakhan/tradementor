"""Spike 1.1 realtime-trigger (besluit Amar 22-10-2026: spikes gebeuren in seconden).

Werking
- De Spike-band (BB(20,k) uit 20 afgesloten candles) ligt vast vanaf het begin van
  elke candle. De scanner zet die referentie in een geheugencache
  (``aster_extreme_spike_filter``). Deze module vergelijkt elke live markprijs met
  die vaste band. Dat is pure rekenkunde: geen REST-call en geen Firestore per tick.
- Raakt de prijs de band voor een kant die aan staat, dan wordt de gewone
  account-tick direct gestart. Die neemt de beslissing met álle bestaande
  controles: stoelen, prijszones, verse ticker, Firestore-claim tegen dubbele orders,
  en de normale MARKET-orderroute. Deze module plaatst zelf nooit een order.
- Kandidaat-munten komen uit ``multiBbReport.spikeWatch``. Dat schrijft de scanner
  elke tick mee in het accountdocument dat de realtime-loader toch al leest.

Abonnementen worden over meerdere websocketverbindingen verdeeld (max. 200 per
verbinding), los van de bestaande realtime-worker voor open posities. Die blijft
ongewijzigd.
"""
from __future__ import annotations

import math
import threading
import time
from dataclasses import dataclass
from typing import Any, Callable, Iterable

from aster_extreme_spike_filter import (
    TIMEFRAMES,
    cached_spike_reference,
    normalize_level,
    spike_band_price,
)

MAX_SYMBOLS_PER_CONNECTION = 200
MAX_CONNECTIONS = 2
MAX_WATCH_SYMBOLS = MAX_SYMBOLS_PER_CONNECTION * MAX_CONNECTIONS
# Een rapport ouder dan dit (bijv. bot gestopt) telt niet meer als watchlist.
WATCH_MAX_AGE_MS = 15 * 60 * 1000


@dataclass(frozen=True)
class SpikeWatch:
    uid: str
    symbols: tuple[str, ...]
    level: str
    long_timeframe: str
    short_timeframe: str
    long_enabled: bool
    short_enabled: bool
    # Build 621 (statistiek): munten met genoeg hefboom volgens de scanner, en munten
    # met al een open positie per kant. Leeg = onbekend (telt niet als verhandelbaar).
    long_min_distance_pct: float = 0.0
    short_min_distance_pct: float = 0.0
    tradable: frozenset[str] = frozenset()
    open_long: frozenset[str] = frozenset()
    open_short: frozenset[str] = frozenset()

    def tradable_for(self, symbol: str, side: str) -> bool:
        if symbol not in self.tradable:
            return False
        return symbol not in (self.open_long if side == "LONG" else self.open_short)

    def sides(self) -> tuple[tuple[str, str], ...]:
        out = []
        if self.long_enabled:
            out.append(("LONG", self.long_timeframe))
        if self.short_enabled:
            out.append(("SHORT", self.short_timeframe))
        return tuple(out)


def _float(value: Any) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return 0.0
    return number if math.isfinite(number) and number > 0 else 0.0


def watch_from_control(uid: str, raw: dict[str, Any], *, now_ms: int) -> SpikeWatch | None:
    """Lees de Spike-watchlist uit een asterStrategy2-document (al opgehaald door de loader)."""
    if not isinstance(raw, dict) or not bool(raw.get("enabled", False)):
        return None
    report = raw.get("multiBbReport") if isinstance(raw.get("multiBbReport"), dict) else {}
    watch = report.get("spikeWatch") if isinstance(report.get("spikeWatch"), dict) else None
    if not watch:
        return None
    try:
        updated = int(watch.get("updatedAtMs") or 0)
    except (TypeError, ValueError):
        return None
    if updated <= 0 or now_ms - updated > WATCH_MAX_AGE_MS:
        return None
    symbols = tuple(dict.fromkeys(
        str(s).upper().strip() for s in (watch.get("symbols") or []) if str(s).strip()))[:MAX_WATCH_SYMBOLS]
    long_tf = str(watch.get("longTimeframe") or "")
    short_tf = str(watch.get("shortTimeframe") or "")
    def symbol_set(name: str) -> frozenset[str]:
        raw_list = watch.get(name) if isinstance(watch.get(name), list) else []
        return frozenset(str(s).upper().strip() for s in raw_list if str(s).strip())
    result = SpikeWatch(uid=str(uid), symbols=symbols, level=normalize_level(watch.get("level")),
                        long_timeframe=long_tf, short_timeframe=short_tf,
                        long_enabled=bool(watch.get("longEnabled")) and long_tf in TIMEFRAMES,
                        short_enabled=bool(watch.get("shortEnabled")) and short_tf in TIMEFRAMES,
                        long_min_distance_pct=_float(watch.get("longMinDistancePct")),
                        short_min_distance_pct=_float(watch.get("shortMinDistancePct")),
                        tradable=symbol_set("tradableSymbols"), open_long=symbol_set("openLong"),
                        open_short=symbol_set("openShort"))
    return result if result.symbols and result.sides() else None


def shard_mapping(watches: Iterable[SpikeWatch]) -> list[dict[str, set[str]]]:
    """symbol -> uids, verdeeld over vaste verbindingen (stabiel op alfabet)."""
    mapping: dict[str, set[str]] = {}
    for watch in watches:
        for symbol in watch.symbols:
            mapping.setdefault(symbol, set()).add(watch.uid)
    symbols = sorted(mapping)[:MAX_WATCH_SYMBOLS]
    shards: list[dict[str, set[str]]] = [dict() for _ in range(MAX_CONNECTIONS)]
    for index, symbol in enumerate(symbols):
        shards[index // MAX_SYMBOLS_PER_CONNECTION][symbol] = mapping[symbol]
    return shards


class SpikeTrigger:
    """Beslist in het geheugen of een live prijs een Spike-band raakt."""

    def __init__(self, warm_reference: Callable[[str, str, int], bool] | None = None,
                 warm_per_second: float = 5.0, stats: Any = None) -> None:
        # Build 621: optionele statistiek per niveau (aster_spike_stats.SpikeStats).
        self._stats = stats
        self._watches: dict[str, SpikeWatch] = {}
        self._fired: dict[tuple[str, str, str, int], float] = {}
        self._lock = threading.Lock()
        # Ontbrekende referentie (scan liep op een ander proces): zelf ophalen,
        # gedoseerd zodat 350 munten de Aster-limieten niet raken.
        self._warm_reference = warm_reference
        self._warm_interval = 1.0 / max(0.1, float(warm_per_second))
        self._last_warm = 0.0
        self._warming: set[tuple[str, str]] = set()

    def _try_warm(self, symbol: str, timeframe: str, now_ms: int) -> bool:
        if self._warm_reference is None:
            return False
        key = (symbol, timeframe)
        with self._lock:
            now = time.monotonic()
            if key in self._warming or now - self._last_warm < self._warm_interval:
                return False
            self._last_warm = now
            self._warming.add(key)
        try:
            return bool(self._warm_reference(symbol, timeframe, now_ms))
        except Exception:
            return False
        finally:
            with self._lock:
                self._warming.discard(key)

    def replace_watches(self, watches: Iterable[SpikeWatch]) -> None:
        with self._lock:
            self._watches = {w.uid: w for w in watches}

    def watch_for(self, uid: str) -> SpikeWatch | None:
        with self._lock:
            return self._watches.get(uid)

    def crossings(self, uid: str, symbol: str, price: float, now_ms: int) -> list[tuple[str, int]]:
        """Kanten waarvan de band geraakt is en die voor deze candle nog niet zijn afgevuurd."""
        watch = self.watch_for(uid)
        if watch is None or not (isinstance(price, (int, float)) and math.isfinite(price) and price > 0):
            return []
        out: list[tuple[str, int]] = []
        observed: set[str] = set()
        for side, timeframe in watch.sides():
            reference = cached_spike_reference(symbol, timeframe, now_ms)
            if reference is None and self._try_warm(symbol, timeframe, now_ms):
                reference = cached_spike_reference(symbol, timeframe, now_ms)
            if reference is None:
                continue  # nog geen referentie: volgende prijsbericht of de minuut-scan vult hem
            closes, live_close_ms = reference
            if self._stats is not None and timeframe not in observed:
                observed.add(timeframe)
                try:
                    self._stats.observe(uid=uid, symbol=symbol, timeframe=timeframe, closes=closes,
                                        live_close_ms=live_close_ms, price=float(price),
                                        tradable_long=watch.tradable_for(symbol, "LONG"),
                                        tradable_short=watch.tradable_for(symbol, "SHORT"),
                                        now_ms=now_ms)
                except Exception:
                    pass  # statistiek mag de trigger nooit hinderen
            band = spike_band_price(list(closes), side=side, level=watch.level,
                                    min_distance_pct=(watch.long_min_distance_pct if side == "LONG"
                                                      else watch.short_min_distance_pct))
            if band is None:
                continue
            hit = price <= band if side == "LONG" else price >= band
            if not hit:
                continue
            with self._lock:
                if (uid, symbol, side, live_close_ms) in self._fired:
                    continue
            out.append((side, live_close_ms))
        if self._stats is not None:
            try:
                self._stats.maybe_flush(now_ms)
            except Exception:
                pass
        return out

    def mark_fired(self, uid: str, symbol: str, side: str, live_close_ms: int) -> None:
        with self._lock:
            now = time.monotonic()
            self._fired[(uid, symbol, side, live_close_ms)] = now
            if len(self._fired) > 20000:
                cutoff = now - 3 * 86400
                self._fired = {k: v for k, v in self._fired.items() if v >= cutoff}


def make_spike_evaluator(trigger: SpikeTrigger,
                         run_account_tick: Callable[[str, str], dict[str, Any]],
                         now_ms: Callable[[], int] = lambda: int(time.time() * 1000)):
    """Evaluate-callback voor AsterRealtimeWorker.

    Alleen bij een geraakte band wordt de (dure) account-tick gestart. Is het account
    bezet (lock of lease), dan wordt het niet als afgevuurd gemarkeerd. Het volgende
    prijsbericht (~1 s later) probeert het opnieuw.
    """
    def evaluate(uid: str, event: Any) -> dict[str, Any] | None:
        symbol = str(event.symbol).upper()
        hits = trigger.crossings(uid, symbol, float(event.mark_price), now_ms())
        if not hits:
            return None
        result = run_account_tick(uid, symbol) or {}
        if str(result.get("status", "")) not in {"account-busy", "lease-busy"}:
            for side, live_close_ms in hits:
                trigger.mark_fired(uid, symbol, side, live_close_ms)
        return {**result, "spikeRealtime": True, "spikeSides": [side for side, _ in hits]}
    return evaluate
