package com.tradementor.app.scanner

import android.content.Context

data class SignalExecutionSettings(
    val positionSizeUsd: Double = 20.0,
    val maxActiveTrades: Int = 10
)

object QuantumShieldCapacityCalculator {
    /**
     * Chooses a position ceiling without user input. The ceiling never drops below the
     * number of positions that are already open; exits remain governed by their TP/SL.
     */
    fun calculate(
        activeTrades: Int,
        portfolioValue: Double,
        availableToTrade: Double,
        maintenanceMargin: Double,
        positionSizeUsd: Double,
        stopLossPercentage: Double
    ): Int {
        val current = activeTrades.coerceAtLeast(0)
        val equity = portfolioValue.coerceAtLeast(0.0)
        val free = availableToTrade.coerceAtLeast(0.0)
        val entry = positionSizeUsd.coerceAtLeast(10.0)
        if (equity <= 0.0 || free < entry) return current.coerceAtLeast(1)

        // Quantum Shield may allocate at most 35% of currently free collateral in one cycle.
        val capitalCeiling = current + kotlin.math.floor((free * 0.35) / entry).toInt()
        val lossPerAddition = entry * (stopLossPercentage.coerceIn(0.25, 1.5) / 100.0)
        val maintenancePerAddition = entry * 0.05
        fun projectedLiquidationRatio(maximum: Int): Double {
            val additions = (maximum - current).coerceAtLeast(0)
            val stressedEquity = equity - additions * lossPerAddition
            return if (stressedEquity <= 0.0) 100.0
            else ((maintenanceMargin + additions * maintenancePerAddition) / stressedEquity) * 100.0
        }

        return (current..minOf(400, capitalCeiling.coerceAtLeast(current)))
            .takeWhile { projectedLiquidationRatio(it) < 25.0 }
            .lastOrNull()
            ?.coerceAtLeast(1)
            ?: current.coerceAtLeast(1)
    }
}

object QuantumShieldCapacityStore {
    private const val PREFS = "quantum_shield_capacity"
    private const val MAXIMUM = "automatic_maximum"

    fun save(context: Context, maximum: Int) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putInt(MAXIMUM, maximum.coerceIn(1, 400)).apply()
    }

    fun load(context: Context, activeTrades: Int): Int = context
        .getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getInt(MAXIMUM, activeTrades.coerceAtLeast(1))
        .coerceIn(activeTrades.coerceAtLeast(1), 400)
}

object QuantumShieldPositionSizer {
    /** Autonomous Strategy 2 sizing. The 2.5% daily growth figure is an evaluation
     * target, never a reason to exceed the per-trade and portfolio risk rails. */
    fun calculate(
        portfolioValue: Double,
        availableToTrade: Double,
        maintenanceMargin: Double,
        activeTrades: Int,
        automaticMaximum: Int,
        stopLossPercentage: Double,
        winRate: Double,
        qualityScore: Double
    ): Double {
        val equity = portfolioValue.coerceAtLeast(0.0)
        val free = availableToTrade.coerceAtLeast(0.0)
        if (equity <= 0.0 || free < 10.0) return 0.0
        val liquidationRatio = (maintenanceMargin / equity).coerceIn(0.0, 1.0)
        val baseRiskFraction = when {
            liquidationRatio < 0.15 -> 0.0035
            liquidationRatio < 0.20 -> 0.0025
            else -> 0.00075
        }
        val confidence = (
            0.75 + ((winRate.coerceIn(70.0, 95.0) - 70.0) / 25.0) * 0.30 +
                ((qualityScore.coerceIn(60.0, 95.0) - 60.0) / 35.0) * 0.20
            ).coerceIn(0.75, 1.25)
        val occupancy = activeTrades.toDouble() / automaticMaximum.coerceAtLeast(1).toDouble()
        val capacityFactor = (1.0 - occupancy * 0.50).coerceIn(0.50, 1.0)
        val stopFraction = stopLossPercentage.coerceIn(0.25, 1.5) / 100.0
        val riskSized = equity * baseRiskFraction * confidence * capacityFactor / stopFraction
        // Small portfolios still need to be able to meet Hyperliquid's $10 minimum.
        // The loss-at-stop rail above remains decisive; this does not permit a $10
        // order when the calculated risk budget itself cannot support it.
        val minimumBufferedOrder = 10.50
        val exposureCap = maxOf(minimumBufferedOrder, minOf(equity * 0.08, free * 0.12))
        val amount = minOf(riskSized, exposureCap)
        if (amount >= minimumBufferedOrder) return kotlin.math.floor(amount * 100.0) / 100.0

        // Permit the exchange minimum only when its actual stop-loss amount remains
        // within 0.30% of equity and the account is not under margin pressure.
        val minimumOrderLoss = minimumBufferedOrder * stopFraction
        val minimumOrderIsSafe = free >= minimumBufferedOrder && liquidationRatio < 0.20 &&
            minimumOrderLoss <= equity * 0.0030
        return if (minimumOrderIsSafe) minimumBufferedOrder else 0.0
    }
}

object SignalExecutionSettingsStore {
    private const val PREFS = "signal_execution_settings"

    fun load(context: Context): SignalExecutionSettings {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return SignalExecutionSettings(
            positionSizeUsd = prefs.getFloat("position_size_usd", 20f).toDouble().coerceAtLeast(1.0),
            maxActiveTrades = prefs.getInt("max_active_trades", 10).coerceIn(1, 400)
        )
    }

    fun save(context: Context, settings: SignalExecutionSettings) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putFloat("position_size_usd", settings.positionSizeUsd.toFloat())
            .putInt("max_active_trades", settings.maxActiveTrades)
            .apply()
    }
}

object ActiveHyperliquidPositionStore {
    private const val PREFS = "signal_execution_settings"

    fun update(context: Context, longCount: Int, shortCount: Int, symbols: Set<String>) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putInt("actual_open_positions", (longCount + shortCount).coerceAtLeast(0))
            .putInt("actual_long_positions", longCount.coerceAtLeast(0))
            .putInt("actual_short_positions", shortCount.coerceAtLeast(0))
            .putLong("actual_open_positions_updated_at", System.currentTimeMillis())
            .putStringSet("actual_open_position_symbols", symbols.map { it.uppercase() }.toSet())
            .apply()
    }

    fun count(context: Context): Int = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getInt("actual_open_positions", 0).coerceAtLeast(0)
    fun longCount(context: Context): Int = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt("actual_long_positions", 0).coerceAtLeast(0)
    fun shortCount(context: Context): Int = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getInt("actual_short_positions", 0).coerceAtLeast(0)
    fun symbols(context: Context): Set<String> = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getStringSet("actual_open_position_symbols", emptySet()).orEmpty().map { it.uppercase() }.toSet()
}

object DirectionBalanceGate {
    private const val MAX_DIFFERENCE = 5
    fun permits(shortDirection: Boolean, longCount: Int, shortCount: Int): Boolean {
        val prospectiveLongs = longCount + if (shortDirection) 0 else 1
        val prospectiveShorts = shortCount + if (shortDirection) 1 else 0
        val currentDifference = kotlin.math.abs(longCount - shortCount)
        val prospectiveDifference = kotlin.math.abs(prospectiveLongs - prospectiveShorts)
        return if (currentDifference > MAX_DIFFERENCE) {
            prospectiveDifference < currentDifference
        } else {
            prospectiveDifference <= MAX_DIFFERENCE
        }
    }
}
