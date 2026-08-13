package com.tradementor.app.scanner

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

enum class TradeOutcome { Pending, Succeeded, Failed, ManuallyClosed }

data class TrackedTrade(
    val id: Long,
    val symbol: String,
    val shortDirection: Boolean,
    val entryPrice: Double,
    val profitPercentage: Double,
    val timeframe: String,
    val startedAt: Long,
    val expiresAt: Long,
    val historicalWinRate: Double? = null,
    val outcome: TradeOutcome = TradeOutcome.Pending,
    val exchange: String = "Hyperliquid",
    val marketType: String = "Perpetuals",
    val quoteCurrency: String = "USD",
    val strategyId: String = "unattributed",
    val strategyName: String = "Niet vastgelegd",
    val indicators: List<String> = emptyList(),
    val exitAdvice: String? = null,
    val remainingWinRate: Double? = null,
    val adviceReason: String? = null,
    val adviceUpdatedAt: Long? = null,
    val lowChanceChecks: Int = 0,
    val lastPrice: Double? = null,
    val maxAdversePercentage: Double = 1.0,
    val positionSizeUsd: Double = 20.0,
    val leverage: Int? = null,
    val realizedPnl: Double? = null,
    val feesPaidUsd: Double = 0.0,
    val fundingPaidUsd: Double = 0.0,
    val positionValueUsd: Double? = null,
    val dcaSafetyOrdersCompleted: Int = 0,
    val liquidationPrice: Double? = null,
    val closedAt: Long? = null,
    val lateTargetReachedAt: Long? = null
) {
    fun isPositionOpen(): Boolean = closedAt == null && outcome == TradeOutcome.Pending
}

object TradeHistoryStore {
    private const val PREFS = "trade_history"
    private const val KEY = "trades"

    fun load(context: Context): List<TrackedTrade> = try {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
            ?: return emptyList()
        val type = object : TypeToken<List<TrackedTrade>>() {}.type
        Gson().fromJson<List<TrackedTrade>>(json, type).orEmpty().map { trade ->
            trade.copy(
                exchange = runCatching { trade.exchange }.getOrNull().orEmpty().ifBlank { "Hyperliquid" },
                marketType = runCatching { trade.marketType }.getOrNull().orEmpty().ifBlank { "Perpetuals" },
                quoteCurrency = runCatching { trade.quoteCurrency }.getOrNull().orEmpty().ifBlank { "USD" },
                strategyId = runCatching { trade.strategyId }.getOrNull().orEmpty().ifBlank { "unattributed" },
                strategyName = runCatching { trade.strategyName }.getOrNull().orEmpty().ifBlank { "Niet vastgelegd" },
                indicators = runCatching { trade.indicators }.getOrNull().orEmpty(),
                remainingWinRate = trade.remainingWinRate ?: trade.historicalWinRate,
                closedAt = trade.closedAt ?: if (trade.outcome == TradeOutcome.Succeeded) trade.expiresAt else null
            )
        }
    } catch (_: Exception) {
        emptyList()
    }

    fun add(context: Context, trade: TrackedTrade) = save(context, listOf(trade) + load(context))

    @Synchronized
    fun removeUnconfirmedScannerRecordsBefore(context: Context, cutoff: Long): Int {
        val cycleStartedAt = TradingCycleStore.startedAt(context)
        val existing = load(context)
        val removable = existing.filter {
            it.startedAt >= cycleStartedAt && it.startedAt < cutoff &&
                it.strategyName.startsWith("Backtest-consensus") && it.realizedPnl == null
        }
        if (removable.isEmpty()) return 0
        val removableIds = removable.map { it.id }.toSet()
        LiveOutcomeLedger.removeTradeIds(context, removableIds)
        save(context, existing.filterNot { it.id in removableIds })
        return removable.size
    }

    @Synchronized
    fun removeByIds(context: Context, tradeIds: Set<Long>): Int {
        if (tradeIds.isEmpty()) return 0
        val existing = load(context)
        val foundIds = existing.asSequence().map { it.id }.filter { it in tradeIds }.toSet()
        if (foundIds.isEmpty()) return 0
        LiveOutcomeLedger.removeTradeIds(context, foundIds)
        save(context, existing.filterNot { it.id in foundIds })
        return foundIds.size
    }

    @Synchronized
    fun addIfPairAvailable(context: Context, trade: TrackedTrade): Boolean {
        if (trade.strategyId.startsWith("strategy_")) {
            val active = StrategyProfileStore.activeDefinition(context)
            if (trade.strategyId != active.id || !active.executionReady) return false
        }
        val existing = load(context)
        val cycleStartedAt = TradingCycleStore.startedAt(context)
        val pairAlreadyActive = existing.any {
            it.startedAt >= cycleStartedAt &&
                it.isPositionOpen() &&
                it.symbol.equals(trade.symbol, ignoreCase = true)
        }
        if (pairAlreadyActive) return false
        save(context, listOf(trade) + existing)
        return true
    }

    fun save(context: Context, trades: List<TrackedTrade>) {
        LiveOutcomeLedger.archiveCompleted(context, trades)
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
            .edit()
            .putString(KEY, Gson().toJson(trades))
            .apply()
    }

    fun timeframeMillis(timeframe: String): Long = when (timeframe) {
        "1 min" -> 60_000L
        "3 min" -> 3 * 60_000L
        "5 min" -> 5 * 60_000L
        "10 min" -> 10 * 60_000L
        "15 min" -> 15 * 60_000L
        "30 min" -> 30 * 60_000L
        "1 uur" -> 60 * 60_000L
        "2 uur" -> 2 * 60 * 60_000L
        "4 uur" -> 4 * 60 * 60_000L
        "6 uur" -> 6 * 60 * 60_000L
        "8 uur" -> 8 * 60 * 60_000L
        "12 uur" -> 12 * 60 * 60_000L
        "18 uur" -> 18 * 60 * 60_000L
        "24 uur" -> 24 * 60 * 60_000L
        "2 dagen" -> 2 * 24 * 60 * 60_000L
        "3 dagen" -> 3 * 24 * 60 * 60_000L
        "7 dagen" -> 7 * 24 * 60 * 60_000L
        else -> 60 * 60_000L
    }
}
