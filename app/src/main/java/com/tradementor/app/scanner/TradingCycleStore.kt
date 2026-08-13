package com.tradementor.app.scanner

import android.content.Context

object TradingCycleStore {
    private const val PREFS = "trading_cycle"
    private const val STARTED_AT = "started_at"
    private const val START_PORTFOLIO_VALUE = "start_portfolio_value"
    private const val TARGET_PERCENTAGE = "target_percentage"
    private const val LOCKED = "target_reached_locked"

    fun startedAt(context: Context): Long = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getLong(STARTED_AT, 0L)

    fun startPortfolioValue(context: Context): Double = java.lang.Double.longBitsToDouble(
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getLong(START_PORTFOLIO_VALUE, java.lang.Double.doubleToRawLongBits(0.0))
    )

    fun targetPercentage(context: Context): Double = java.lang.Double.longBitsToDouble(
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getLong(TARGET_PERCENTAGE, java.lang.Double.doubleToRawLongBits(10.0))
    ).coerceIn(1.0, 1_000.0)

    fun targetValue(context: Context): Double = startPortfolioValue(context) * (1.0 + targetPercentage(context) / 100.0)
    fun isLocked(context: Context): Boolean = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean(LOCKED, false)

    fun updateTarget(context: Context, percentage: Double) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong(TARGET_PERCENTAGE, java.lang.Double.doubleToRawLongBits(percentage.coerceIn(1.0, 1_000.0)))
            .apply()
    }

    fun lockAtTarget(context: Context) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(LOCKED, true).apply()
    }

    fun startNew(context: Context, portfolioValue: Double, targetPercentage: Double = 10.0, startedAt: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong(STARTED_AT, startedAt)
            .putLong(START_PORTFOLIO_VALUE, java.lang.Double.doubleToRawLongBits(portfolioValue.coerceAtLeast(0.0)))
            .putLong(TARGET_PERCENTAGE, java.lang.Double.doubleToRawLongBits(targetPercentage.coerceIn(1.0, 1_000.0)))
            .putBoolean(LOCKED, false)
            .apply()
    }

    fun syncFromCloud(context: Context, status: TradingCycleStatus) {
        if (status.status == "inactive" || status.startPortfolioValue <= 0.0) return
        startNew(
            context = context,
            portfolioValue = status.startPortfolioValue,
            targetPercentage = status.targetPercentage,
            startedAt = status.startedAtEpochMs.takeIf { it > 0L } ?: startedAt(context).takeIf { it > 0L } ?: System.currentTimeMillis()
        )
        if (status.status in setOf("closing", "completed", "completed_with_failures") || status.targetReached) {
            lockAtTarget(context)
        }
    }
}

object TradingCyclePolicy {
    fun normalizedTargetPercentage(value: Double): Double = value.coerceIn(1.0, 1_000.0)

    fun targetValue(startValue: Double, targetPercentage: Double): Double =
        startValue.coerceAtLeast(0.0) * (1.0 + normalizedTargetPercentage(targetPercentage) / 100.0)

    fun targetReached(startValue: Double, currentValue: Double, targetPercentage: Double): Boolean =
        startValue > 0.0 && currentValue + 1e-9 >= targetValue(startValue, targetPercentage)
}
