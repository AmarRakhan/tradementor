package com.tradementor.app.scanner

import android.content.Context

object TradingCycleStore {
    private const val PREFS = "trading_cycle"
    private const val STARTED_AT = "started_at"
    private const val START_PORTFOLIO_VALUE = "start_portfolio_value"

    fun startedAt(context: Context): Long = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getLong(STARTED_AT, 0L)

    fun startPortfolioValue(context: Context): Double = java.lang.Double.longBitsToDouble(
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .getLong(START_PORTFOLIO_VALUE, java.lang.Double.doubleToRawLongBits(0.0))
    )

    fun startNew(context: Context, portfolioValue: Double, startedAt: Long = System.currentTimeMillis()) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putLong(STARTED_AT, startedAt)
            .putLong(START_PORTFOLIO_VALUE, java.lang.Double.doubleToRawLongBits(portfolioValue.coerceAtLeast(0.0)))
            .apply()
    }
}
