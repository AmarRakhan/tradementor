"""Pure rules for the isolated, time-boxed Bitcoin arena."""

from __future__ import annotations

ALLOWED_DURATIONS = {60, 300, 900, 3600, 14400, 86400}
MIN_STAKE_USD = 10.0
MAX_STAKE_USD = 500.0


def validate_trade(duration_seconds: int, stake_usd: float) -> None:
    if int(duration_seconds) not in ALLOWED_DURATIONS:
        raise ValueError("Ongeldige looptijd")
    if not MIN_STAKE_USD <= float(stake_usd) <= MAX_STAKE_USD:
        raise ValueError(f"Inzet moet tussen ${MIN_STAKE_USD:.0f} en ${MAX_STAKE_USD:.0f} liggen")


def price_result(short: bool, entry_price: float, exit_price: float) -> float:
    if entry_price <= 0 or exit_price <= 0:
        return 0.0
    raw = (exit_price / entry_price - 1.0) * 100.0
    return -raw if short else raw


def directional_signal(closes: list[float]) -> dict[str, float | str]:
    """Always return a direction; low evidence stays visible as low confidence."""
    clean = [float(value) for value in closes if float(value) > 0]
    if len(clean) < 20:
        return {"direction": "long", "confidence": 50.0, "reason": "Beperkte candledata; richting heeft minimale zekerheid"}
    fast = sum(clean[-5:]) / 5
    slow = sum(clean[-20:]) / 20
    movement = (fast / slow - 1.0) * 100.0
    confidence = min(99.0, 50.0 + abs(movement) * 120.0)
    return {
        "direction": "long" if movement > 0 else "short",
        "confidence": confidence,
        "reason": "Korte candletrend ligt boven de langzame trend" if movement > 0 else "Korte candletrend ligt onder de langzame trend",
    }


def rolling_backtest(closes: list[float], timestamps: list[int] | None = None, limit: int = 1000) -> dict:
    """Walk-forward test: every prediction only sees prices available at that moment."""
    clean = [float(value) for value in closes if float(value) > 0]
    times = list(timestamps or range(len(clean)))
    usable = min(len(clean), len(times))
    rows: list[dict] = []
    for index in range(max(19, usable - limit - 1), usable - 1):
        signal = directional_signal(clean[max(0, index - 79):index + 1])
        short = signal["direction"] == "short"
        movement = price_result(short, clean[index], clean[index + 1])
        rows.append({
            "id": f"backtest-{times[index]}",
            "direction": signal["direction"],
            "confidence": signal["confidence"],
            "predictionPrice": clean[index],
            "expiryPrice": clean[index + 1],
            "resultPercentage": movement,
            "outcome": "win" if movement > 0 else "loss",
            "predictedAtEpochMs": int(times[index]),
        })
    rows = rows[-limit:]
    wins = [row for row in rows if row["outcome"] == "win"]
    return {
        "predictions": list(reversed(rows)),
        "won": len(wins),
        "lost": len(rows) - len(wins),
        "averageWinningPercentage": sum(float(row["resultPercentage"]) for row in wins) / len(wins) if wins else 0.0,
    }
