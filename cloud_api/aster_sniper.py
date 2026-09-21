"""Pure SNIPER strategy logic. No network, Firestore or order submission lives here."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any
import math


ENTRY_CHECK_NAMES = (
    "Bollinger Band locatie",
    "Momentum",
    "Trendfilter",
    "Volume bevestiging",
    "Orderflow",
    "Orderboek",
    "Liquiditeit",
    "Spread check",
    "Volatiliteit",
    "Kosten check",
    "Liquidatiebuffer",
    "Historische edge",
)


def number(value: Any) -> float:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return 0.0
    return result if math.isfinite(result) else 0.0


@dataclass(frozen=True)
class SniperSettings:
    enabled: bool = False
    max_trade_seconds: int = 180
    tp_min_percent: float = .18
    tp_max_percent: float = .45
    max_loss_usd: float = .10
    max_concurrent: int = 3
    margin_per_trade_usd: float = 1.0
    leverage: int = 20
    cooldown_seconds: int = 60
    attempts_per_coin: int = 3
    max_daily_loss_usd: float = 5.0
    profit_lock_percent: float = .10
    universe_top_n: int = 60

    @classmethod
    def from_mapping(cls, raw: dict[str, Any] | None) -> "SniperSettings":
        raw = raw or {}
        def f(key: str, default: float) -> float:
            value = number(raw.get(key, default))
            return value if value else default
        value = cls(
            enabled=bool(raw.get("enabled", False)),
            max_trade_seconds=int(f("maxTradeSeconds", 180)),
            tp_min_percent=f("tpMinPercent", .18),
            tp_max_percent=f("tpMaxPercent", .45),
            max_loss_usd=f("maxLossUsd", .10),
            max_concurrent=int(f("maxConcurrent", 3)),
            margin_per_trade_usd=f("marginPerTradeUsd", 1.0),
            leverage=int(f("leverage", 20)),
            cooldown_seconds=int(f("cooldownSeconds", 60)),
            attempts_per_coin=int(f("attemptsPerCoin", 3)),
            max_daily_loss_usd=f("maxDailyLossUsd", 5.0),
            profit_lock_percent=f("profitLockPercent", .10),
            universe_top_n=int(f("universeTopN", 60)),
        )
        return value.validated()

    def validated(self) -> "SniperSettings":
        if not 30 <= self.max_trade_seconds <= 900:
            raise ValueError("Sniper tradeduur moet tussen 30 en 900 seconden liggen")
        if not .05 <= self.tp_min_percent <= self.tp_max_percent <= 3:
            raise ValueError("Sniper TP-zone is ongeldig")
        if not .01 <= self.max_loss_usd <= 1_000:
            raise ValueError("Sniper max verlies per trade is ongeldig")
        if not 1 <= self.max_concurrent <= 20:
            raise ValueError("Sniper max concurrent moet tussen 1 en 20 liggen")
        if not .10 <= self.margin_per_trade_usd <= 100_000:
            raise ValueError("Sniper margin per trade is ongeldig")
        if not 1 <= self.leverage <= 200:
            raise ValueError("Sniper leverage moet tussen 1x en 200x liggen")
        if not 5 <= self.cooldown_seconds <= 86_400:
            raise ValueError("Sniper cooldown is ongeldig")
        if not 1 <= self.attempts_per_coin <= 20:
            raise ValueError("Sniper pogingen per coin is ongeldig")
        if not .10 <= self.max_daily_loss_usd <= 1_000_000:
            raise ValueError("Sniper max dagverlies is ongeldig")
        if not 10 <= self.universe_top_n <= 200:
            raise ValueError("Sniper universe Top-N is ongeldig")
        return self

    def public_dict(self) -> dict[str, Any]:
        return {
            "enabled": self.enabled,
            "maxTradeSeconds": self.max_trade_seconds,
            "tpMinPercent": self.tp_min_percent,
            "tpMaxPercent": self.tp_max_percent,
            "maxLossUsd": self.max_loss_usd,
            "maxConcurrent": self.max_concurrent,
            "marginPerTradeUsd": self.margin_per_trade_usd,
            "leverage": self.leverage,
            "cooldownSeconds": self.cooldown_seconds,
            "attemptsPerCoin": self.attempts_per_coin,
            "maxDailyLossUsd": self.max_daily_loss_usd,
            "profitLockPercent": self.profit_lock_percent,
            "universeTopN": self.universe_top_n,
        }


def _series(candles: list[list[Any]], index: int) -> list[float]:
    return [number(row[index]) for row in candles if isinstance(row, list) and len(row) > index and number(row[index]) > 0]


def _sma(values: list[float], size: int) -> float:
    return sum(values[-size:]) / size if len(values) >= size else 0.0


def _bollinger(closes: list[float], size: int = 20) -> tuple[float, float, float]:
    if len(closes) < size:
        return 0.0, 0.0, 0.0
    sample = closes[-size:]
    middle = sum(sample) / size
    variance = sum((x - middle) ** 2 for x in sample) / size
    dev = math.sqrt(variance)
    return middle - 2 * dev, middle, middle + 2 * dev


def _atr_percent(candles: list[list[Any]], size: int = 14) -> float:
    if len(candles) < size + 1:
        return 0.0
    ranges = []
    previous = number(candles[-size-1][4])
    for row in candles[-size:]:
        high, low, close = number(row[2]), number(row[3]), number(row[4])
        if min(high, low, close, previous) <= 0:
            return 0.0
        ranges.append(max(high-low, abs(high-previous), abs(low-previous)))
        previous = close
    current = number(candles[-1][4])
    return (sum(ranges) / len(ranges)) / current if current > 0 else 0.0


def _historical_edge(closes: list[float], side: str, horizon: int = 3) -> float:
    if len(closes) < 30 + horizon:
        return 0.0
    wins = total = 0
    for index in range(max(1, len(closes)-80), len(closes)-horizon):
        before, after = closes[index], closes[index+horizon]
        if before <= 0:
            continue
        move = after / before - 1
        wins += int(move > 0 if side == "LONG" else move < 0)
        total += 1
    return wins / total if total else 0.0


def evaluate_candidate(
    symbol: str,
    *,
    candles_1m: list[list[Any]],
    candles_3m: list[list[Any]],
    candles_5m: list[list[Any]],
    ticker_24h: dict[str, Any],
    book: dict[str, Any],
    depth: dict[str, Any],
    settings: SniperSettings,
) -> dict[str, Any]:
    closes1 = _series(candles_1m, 4)
    closes3 = _series(candles_3m, 4)
    closes5 = _series(candles_5m, 4)
    volumes = _series(candles_1m, 5)
    if min(len(closes1), len(closes3), len(closes5)) < 25:
        return {"symbol": symbol, "eligible": False, "score": 0, "side": "", "reason": "Onvoldoende candledata", "checks": []}

    price = closes1[-1]
    fast = _sma(closes3, 8)
    slow = _sma(closes5, 20)
    momentum = closes1[-1] / closes1[-4] - 1 if closes1[-4] > 0 else 0.0
    if fast > slow and momentum > 0:
        side = "LONG"
    elif fast < slow and momentum < 0:
        side = "SHORT"
    else:
        side = "LONG" if momentum >= 0 else "SHORT"

    lower, middle, upper = _bollinger(closes1)
    bid = number(book.get("bidPrice"))
    ask = number(book.get("askPrice"))
    spread = (ask-bid) / ((ask+bid)/2) if ask > bid > 0 else 1.0
    bids = depth.get("bids") if isinstance(depth.get("bids"), list) else []
    asks = depth.get("asks") if isinstance(depth.get("asks"), list) else []
    bid_notional = sum(number(row[0]) * number(row[1]) for row in bids[:20] if isinstance(row, list) and len(row) >= 2)
    ask_notional = sum(number(row[0]) * number(row[1]) for row in asks[:20] if isinstance(row, list) and len(row) >= 2)
    depth_total = bid_notional + ask_notional
    imbalance = bid_notional / depth_total if depth_total > 0 else .5

    latest_volume = volumes[-1] if volumes else 0.0
    average_volume = _sma(volumes, min(20, len(volumes))) if volumes else 0.0
    row = candles_1m[-1]
    quote_volume = number(ticker_24h.get("quoteVolume"))
    taker_buy = number(row[9]) if len(row) > 9 else 0.0
    total_quote = number(row[7]) if len(row) > 7 else 0.0
    taker_ratio = taker_buy / total_quote if total_quote > 0 else .5
    atr = _atr_percent(candles_1m)
    edge = _historical_edge(closes1, side)
    expected_tp = max(settings.tp_min_percent / 100, min(settings.tp_max_percent / 100, max(atr * .75, settings.tp_min_percent / 100)))
    estimated_roundtrip_cost = .0008 + spread

    checks = [
        ("Bollinger Band locatie", lower > 0 and lower <= price <= upper),
        ("Momentum", momentum > 0 if side == "LONG" else momentum < 0),
        ("Trendfilter", fast > slow if side == "LONG" else fast < slow),
        ("Volume bevestiging", average_volume > 0 and latest_volume >= average_volume * .60),
        ("Orderflow", taker_ratio >= .50 if side == "LONG" else taker_ratio <= .50),
        ("Orderboek", imbalance >= .50 if side == "LONG" else imbalance <= .50),
        ("Liquiditeit", quote_volume >= 1_000_000 and depth_total >= max(5_000, settings.margin_per_trade_usd * settings.leverage * 5)),
        ("Spread check", spread <= .0008),
        ("Volatiliteit", .00025 <= atr <= .025),
        ("Kosten check", estimated_roundtrip_cost < expected_tp),
        ("Liquidatiebuffer", settings.leverage * max(atr, .0001) < .75),
        ("Historische edge", edge >= .50),
    ]
    score = sum(int(passed) for _, passed in checks)
    timeframe = "15s" if abs(momentum) >= .0025 and spread <= .0004 else ("1m" if abs(momentum) >= .0015 else "3m")
    return {
        "symbol": symbol.upper(),
        "side": side,
        "timeframe": timeframe,
        "eligible": score == len(ENTRY_CHECK_NAMES),
        "score": score,
        "price": price,
        "tpPercent": round(expected_tp * 100, 6),
        "checks": [{"name": name, "passed": passed} for name, passed in checks],
        "metrics": {
            "momentumPercent": momentum * 100,
            "atrPercent": atr * 100,
            "spreadPercent": spread * 100,
            "orderBookBidRatio": imbalance,
            "takerBuyRatio": taker_ratio,
            "historicalEdge": edge,
            "quoteVolume24h": quote_volume,
        },
        "reason": "12/12 checks · live entry gereed" if score == 12 else f"{score}/12 checks · wachten",
    }


def exit_decision(trade: dict[str, Any], position: dict[str, Any], *, now_ms: int, settings: SniperSettings) -> dict[str, Any]:
    quantity = abs(number(position.get("positionAmt", position.get("quantity"))))
    mark = number(position.get("markPrice"))
    pnl = number(position.get("unRealizedProfit", position.get("unrealizedPnl")))
    notional = quantity * mark
    opened = int(number(trade.get("openedAtMs")))
    elapsed = max(0, now_ms-opened)
    tp_percent = number(trade.get("tpPercent")) or settings.tp_min_percent
    pnl_percent = (pnl/notional*100) if notional > 0 else 0.0
    peak = max(number(trade.get("peakPnlPercent")), pnl_percent)
    base = {"pnlUsd": pnl, "pnlPercent": pnl_percent, "peakPnlPercent": peak}
    if pnl <= -settings.max_loss_usd:
        return {"action": "CLOSE_LOSS", "reason": "Max verlies per trade bereikt", **base}
    if pnl_percent >= tp_percent:
        return {"action": "CLOSE_TP", "reason": "Dynamische Sniper TP bereikt", **base}
    if peak >= settings.profit_lock_percent and pnl_percent <= peak - settings.profit_lock_percent:
        return {"action": "CLOSE_PROFIT_LOCK", "reason": "Sniper profit lock beschermt behaalde winst", **base}
    if elapsed >= settings.max_trade_seconds * 1000:
        return {"action": "CLOSE_TIMEOUT", "reason": "Harde Sniper tradeduur verstreken", **base}
    return {"action": "HOLD", "reason": "Trade blijft binnen Sniper grenzen", **base}


def backtest_candles(candles: list[list[Any]], settings: SniperSettings) -> dict[str, Any]:
    """Conservative candle-only replay; orderbook/orderflow checks cannot be reconstructed historically."""
    closes = _series(candles, 4)
    if len(closes) < 60:
        return {"trades": 0, "wins": 0, "losses": 0, "grossMovePercent": 0.0,
            "netMovePercent": 0.0, "reliable": False,
            "limitations": ["Onvoldoende 1m-candles voor een betekenisvolle replay"]}
    notional=max(settings.margin_per_trade_usd*settings.leverage,.01)
    loss_cap=settings.max_loss_usd/notional
    fee_rate=.0008       # 0.08% roundtrip assumption
    spread_rate=.0002    # 0.02% historical spread proxy
    slippage_rate=.0002  # 0.02% roundtrip slippage proxy
    cost_rate=fee_rate+spread_rate+slippage_rate
    horizon=max(1,min(3,settings.max_trade_seconds//60))
    gross_moves=[];net_moves=[];targets=[]
    # Signal is calculated at bar i and execution is delayed to bar i+1 to
    # model at least one historical bar of latency instead of perfect fills.
    for i in range(25,len(candles)-horizon-2,4):
        history=candles[:i+1]
        local_closes=_series(history,4)
        if len(local_closes)<25:continue
        fast=sum(local_closes[-4:])/4;slow=sum(local_closes[-20:])/20
        momentum=local_closes[-1]/local_closes[-4]-1 if local_closes[-4]>0 else 0.0
        side=1 if fast>slow and momentum>=0 else -1 if fast<slow and momentum<=0 else (1 if momentum>=0 else -1)
        entry=number(candles[i+1][4])
        if entry<=0:continue
        atr=_atr_percent(history)
        target=max(settings.tp_min_percent/100,min(settings.tp_max_percent/100,
            max(atr*.75,settings.tp_min_percent/100)))
        gross=None
        for row in candles[i+2:i+2+horizon]:
            high,low=number(row[2]),number(row[3])
            if high<=0 or low<=0:continue
            favorable=(high/entry-1) if side>0 else (entry/low-1)
            adverse=(entry/low-1) if side>0 else (high/entry-1)
            # If both boundaries are touched inside one 1m candle, assume the
            # loss boundary happened first; this prevents optimistic ordering.
            if adverse>=loss_cap:
                gross=-loss_cap;break
            if favorable>=target:
                gross=target;break
        if gross is None:
            exit_price=number(candles[i+1+horizon][4])
            if exit_price<=0:continue
            raw=(exit_price/entry-1)*side
            gross=min(target,max(-loss_cap,raw))
        net=gross-cost_rate
        gross_moves.append(gross);net_moves.append(net);targets.append(target)
    wins=sum(1 for move in net_moves if move>0)
    return {
        "trades":len(net_moves),"wins":wins,"losses":len(net_moves)-wins,
        "winRate":wins/len(net_moves) if net_moves else 0.0,
        "grossMovePercent":sum(gross_moves)*100,
        "netMovePercent":sum(net_moves)*100,
        "averageTargetPercent":(sum(targets)/len(targets)*100) if targets else 0.0,
        "reliable":bool(net_moves),
        "assumptions":{"roundtripFeePercent":fee_rate*100,"spreadProxyPercent":spread_rate*100,
            "slippageProxyPercent":slippage_rate*100,"latencyModel":"entry on next 1m close",
            "sameCandleTpAndStopOrdering":"stop-first"},
        "limitations":["Historische orderbook/orderflow-data ontbreekt; dit is geen volledige 12/12 Sniper-replay",
            "1m-candles kunnen de exacte volgorde van intrabar ticks niet bewijzen"],
    }

