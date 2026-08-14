package com.tradementor.app.scanner

import android.content.Context
import com.google.gson.Gson
import com.google.gson.JsonParser
import com.google.gson.reflect.TypeToken

data class DcaBotSettings(
    val baseOrderUsd: Double = 20.0,
    val safetyOrderUsd: Double = 20.0,
    val maxSafetyOrders: Int = 3,
    val priceDeviationPercentage: Double = 2.0,
    val shortPriceDeviationPercentage: Double = 2.0,
    val stepScale: Double = 1.0,
    val volumeScale: Double = 1.0,
    val maxActiveDeals: Int = 5,
    val takeProfitEnabled: Boolean = false,
    val takeProfitPercentage: Double = 1.5,
    val trailingTakeProfitEnabled: Boolean = false,
    val trailingDeviationPercentage: Double = 0.5,
    val stopLossEnabled: Boolean = false,
    val stopLossPercentage: Double = 8.0,
    val leverage: Int = 100,
    val minimumWinRate: Double = 65.0,
    val minimumQualityScore: Double = 65.0,
    val cooldownMinutes: Int = 15,
    val portfolioTargetPercentage: Double = 10.0,
    val topUniverseSize: Int = 50,
    val entryMode: String = "bollinger"
) {
    fun usesDirectEntry(): Boolean = entryMode == "direct"
    fun allowsShort(shortDirection: Boolean): Boolean = true

    /** Every add-on uses exactly the configured base-order amount. */
    fun orderValueFor(safetyOrderIndex: Int): Double = baseOrderUsd

    /**
     * Fixed ladder measured from the original fill: 2%, 4%, 6% ... .
     * safetyOrdersCompleted is zero before the first add-on.
     */
    fun deviationFor(shortDirection: Boolean, safetyOrdersCompleted: Int): Double =
        (if (shortDirection) shortPriceDeviationPercentage else priceDeviationPercentage) *
            (safetyOrdersCompleted.coerceAtLeast(0) + 1)

    fun maximumDealValueUsd(): Double = baseOrderUsd +
        (0 until maxSafetyOrders).sumOf(::orderValueFor)

    fun executionBlockReason(): String? = when {
        maximumDealValueUsd() > 100_000.0 ->
            "De maximale dealwaarde is hoger dan de veiligheidsgrens van $100.000."
        else -> null
    }

    fun validated(): DcaBotSettings = copy(
        baseOrderUsd = baseOrderUsd.coerceIn(10.0, 100_000.0),
        safetyOrderUsd = baseOrderUsd.coerceIn(10.0, 100_000.0),
        maxSafetyOrders = maxSafetyOrders.coerceIn(0, 20),
        priceDeviationPercentage = priceDeviationPercentage.coerceIn(0.25, 25.0),
        shortPriceDeviationPercentage = shortPriceDeviationPercentage.coerceIn(0.25, 25.0),
        stepScale = 1.0,
        volumeScale = 1.0,
        maxActiveDeals = maxActiveDeals.coerceIn(1, 500),
        takeProfitPercentage = takeProfitPercentage.coerceIn(0.25, 25.0),
        trailingDeviationPercentage = trailingDeviationPercentage.coerceIn(0.1, 10.0),
        stopLossPercentage = stopLossPercentage.coerceIn(1.0, 25.0),
        leverage = 100,
        minimumWinRate = minimumWinRate.coerceIn(50.0, 95.0),
        minimumQualityScore = minimumQualityScore.coerceIn(50.0, 95.0),
        cooldownMinutes = cooldownMinutes.coerceIn(1, 10_080),
        portfolioTargetPercentage = portfolioTargetPercentage.coerceIn(1.0, 1_000.0),
        topUniverseSize = topUniverseSize.coerceAtLeast(1),
        entryMode = if (entryMode == "direct") "direct" else "bollinger"
    )
}

object DcaBotSettingsStore {
    private const val PREFS = "dca_pulse_settings"
    private const val KEY = "settings"

    fun load(context: Context): DcaBotSettings = runCatching {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
            ?: return DcaBotSettings()
        val parsed = JsonParser.parseString(json).asJsonObject
        val loaded = Gson().fromJson(json, DcaBotSettings::class.java)
        loaded.copy(
            shortPriceDeviationPercentage = if (parsed.has("shortPriceDeviationPercentage")) loaded.shortPriceDeviationPercentage else loaded.priceDeviationPercentage,
            portfolioTargetPercentage = if (parsed.has("portfolioTargetPercentage")) loaded.portfolioTargetPercentage else 10.0,
            entryMode = if (parsed.has("entryMode")) loaded.entryMode else "bollinger"
        ).validated()
    }.getOrDefault(DcaBotSettings())

    fun save(context: Context, settings: DcaBotSettings) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, Gson().toJson(settings.validated()))
            .apply()
    }
}

/** Shared form contract used by every screen that edits DCA Pulse. */
data class DcaBotSettingsInput(
    val baseOrderUsd: String,
    val maxSafetyOrders: String,
    val longDeviationPercentage: String,
    val shortDeviationPercentage: String,
    val maxActiveDeals: String,
    val cooldownValue: String,
    val cooldownInHours: Boolean,
    val portfolioTargetPercentage: String,
    val topUniverseSize: String,
    val entryMode: String,
    val stopLossEnabled: Boolean
) {
    private fun decimal(value: String): Double? = value.replace(',', '.').toDoubleOrNull()

    fun applyTo(current: DcaBotSettings): DcaBotSettings {
        val parsedBaseOrder = decimal(baseOrderUsd)
        return current.copy(
        baseOrderUsd = parsedBaseOrder ?: current.baseOrderUsd,
        safetyOrderUsd = parsedBaseOrder ?: current.safetyOrderUsd,
        maxSafetyOrders = maxSafetyOrders.toIntOrNull() ?: current.maxSafetyOrders,
        priceDeviationPercentage = decimal(longDeviationPercentage) ?: current.priceDeviationPercentage,
        shortPriceDeviationPercentage = decimal(shortDeviationPercentage) ?: current.shortPriceDeviationPercentage,
        maxActiveDeals = maxActiveDeals.toIntOrNull() ?: current.maxActiveDeals,
        cooldownMinutes = cooldownValue.toIntOrNull()
            ?.let { it * if (cooldownInHours) 60 else 1 }
            ?: current.cooldownMinutes,
        portfolioTargetPercentage = decimal(portfolioTargetPercentage) ?: current.portfolioTargetPercentage,
        topUniverseSize = topUniverseSize.toIntOrNull() ?: current.topUniverseSize,
        entryMode = entryMode,
        stopLossEnabled = stopLossEnabled
    ).validated()
    }
}

object AsterUniverseRequest {
    fun normalizedSize(value: Int): Int = value.coerceAtLeast(1)
    fun endpointPath(value: Int): String = "/v1/me/market/aster-usdt?limit=${normalizedSize(value)}"
}

data class DcaDealState(
    val symbol: String,
    val shortDirection: Boolean,
    val initialEntryPrice: Double,
    val lastOrderPrice: Double,
    val safetyOrdersCompleted: Int = 0,
    val lastOrderAt: Long = System.currentTimeMillis(),
    val trailingActivated: Boolean = false,
    val bestTrailingPrice: Double? = null,
    val strategyId: String = "strategy_3"
)

object DcaDealStore {
    private const val PREFS = "dca_pulse_deals"
    private const val KEY = "deals"
    private fun canonicalSymbol(symbol: String): String = DcaPulseGate.normalizedBaseSymbol(symbol)

    fun load(context: Context): List<DcaDealState> = runCatching {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null)
            ?: return emptyList()
        val type = object : TypeToken<List<DcaDealState>>() {}.type
        Gson().fromJson<List<DcaDealState>>(json, type).orEmpty()
    }.getOrDefault(emptyList())

    @Synchronized
    fun upsert(context: Context, deal: DcaDealState) {
        val normalizedSymbol = canonicalSymbol(deal.symbol)
        val normalizedDeal = deal.copy(symbol = normalizedSymbol)
        val values = load(context).filterNot { canonicalSymbol(it.symbol) == normalizedSymbol } + normalizedDeal
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, Gson().toJson(values))
            .apply()
    }

    fun find(context: Context, symbol: String): DcaDealState? =
        load(context).firstOrNull { canonicalSymbol(it.symbol) == canonicalSymbol(symbol) }

    @Synchronized
    fun syncFromCloud(context: Context, deals: List<CloudDcaDeal>) {
        val local = load(context).associateBy { canonicalSymbol(it.symbol) }
        deals.forEach { cloud ->
            val previous = local[canonicalSymbol(cloud.symbol)]
            upsert(context, DcaDealState(
                symbol = cloud.symbol,
                shortDirection = cloud.shortDirection,
                initialEntryPrice = cloud.initialEntryPrice.takeIf { it > 0.0 } ?: previous?.initialEntryPrice ?: return@forEach,
                lastOrderPrice = cloud.lastOrderPrice.takeIf { it > 0.0 } ?: previous?.lastOrderPrice ?: return@forEach,
                safetyOrdersCompleted = cloud.safetyOrdersCompleted,
                lastOrderAt = previous?.lastOrderAt ?: System.currentTimeMillis(),
                strategyId = cloud.strategyId
            ))
        }
    }

    @Synchronized
    fun retainOpen(context: Context, openSymbols: Set<String>) {
        val normalized = openSymbols.map { canonicalSymbol(it) }.toSet()
        val retained = load(context).filter { canonicalSymbol(it.symbol) in normalized }
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, Gson().toJson(retained))
            .apply()
    }
}

object DcaPulseGate {
    fun normalizedBaseSymbol(symbol: String): String = symbol.substringAfterLast(':')
        .substringBefore('/')
        .substringBefore('-')
        .uppercase()

    private fun normalizedUnderlyingSymbol(symbol: String): String {
        val normalized = normalizedBaseSymbol(symbol).removeSuffix("USDT")
        return when {
            normalized.startsWith("1000") && normalized.length > 4 -> normalized.drop(4)
            normalized.startsWith("K") && normalized.length > 1 -> normalized.drop(1)
            else -> normalized
        }
    }

    fun isAllowedUniverseSymbol(symbol: String, universeSymbols: Set<String>): Boolean {
        val allowed = universeSymbols.map(::normalizedUnderlyingSymbol).toSet()
        return normalizedUnderlyingSymbol(symbol) in allowed
    }

    fun reachedDeviation(
        shortDirection: Boolean,
        currentPrice: Double,
        lastOrderPrice: Double,
        deviationPercentage: Double
    ): Boolean {
        if (currentPrice <= 0.0 || lastOrderPrice <= 0.0) return false
        val fraction = deviationPercentage.coerceAtLeast(0.0) / 100.0
        return if (shortDirection) currentPrice >= lastOrderPrice * (1.0 + fraction)
        else currentPrice <= lastOrderPrice * (1.0 - fraction)
    }

    fun pricePerformancePercentage(shortDirection: Boolean, currentPrice: Double, entryPrice: Double): Double {
        if (currentPrice <= 0.0 || entryPrice <= 0.0) return 0.0
        val raw = (currentPrice / entryPrice - 1.0) * 100.0
        return if (shortDirection) -raw else raw
    }

    fun takeProfitReached(shortDirection: Boolean, currentPrice: Double, averageEntryPrice: Double, percentage: Double): Boolean {
        if (currentPrice <= 0.0 || averageEntryPrice <= 0.0) return false
        val fraction = percentage.coerceAtLeast(0.0) / 100.0
        return if (shortDirection) currentPrice <= averageEntryPrice * (1.0 - fraction)
        else currentPrice >= averageEntryPrice * (1.0 + fraction)
    }

    fun updatedBestPrice(shortDirection: Boolean, currentPrice: Double, previousBest: Double?): Double =
        if (previousBest == null) currentPrice
        else if (shortDirection) minOf(previousBest, currentPrice) else maxOf(previousBest, currentPrice)

    fun trailingExitReached(shortDirection: Boolean, currentPrice: Double, bestPrice: Double, deviationPercentage: Double): Boolean {
        if (currentPrice <= 0.0 || bestPrice <= 0.0) return false
        val fraction = deviationPercentage.coerceAtLeast(0.0) / 100.0
        return if (shortDirection) currentPrice >= bestPrice * (1.0 + fraction)
        else currentPrice <= bestPrice * (1.0 - fraction)
    }
}

data class DcaCapacityState(
    val activeDeals: Int,
    val maximumDeals: Int
) {
    val remainingDeals: Int get() = (maximumDeals - activeDeals).coerceAtLeast(0)
    val overLimitDeals: Int get() = (activeDeals - maximumDeals).coerceAtLeast(0)
    val isFull: Boolean get() = activeDeals >= maximumDeals
}

/**
 * One source of truth for the DCA deal counter and automatic refill policy.
 * Every real open Hyperliquid position occupies one active-deal slot, including
 * positions opened before DCA Pulse was selected.
 */
object DcaCapacityPolicy {
    fun fromPositionCounts(longCount: Int, shortCount: Int, maximumDeals: Int): DcaCapacityState =
        DcaCapacityState(
            activeDeals = longCount.coerceAtLeast(0) + shortCount.coerceAtLeast(0),
            maximumDeals = maximumDeals.coerceAtLeast(1)
        )

    fun fromActiveCount(activeDeals: Int, maximumDeals: Int): DcaCapacityState =
        DcaCapacityState(
            activeDeals = activeDeals.coerceAtLeast(0),
            maximumDeals = maximumDeals.coerceAtLeast(1)
        )

    fun nextScanDelayMinutes(state: DcaCapacityState, configuredIntervalMinutes: Long): Long =
        if (state.isFull) configuredIntervalMinutes.coerceAtLeast(15L) else 1L

    /**
     * Pure refill simulation used by tests and diagnostics. Each accepted item
     * represents one unique pair whose order was filled successfully.
     */
    fun acceptedDirections(
        candidateDirections: List<Boolean>,
        initialLongs: Int,
        initialShorts: Int,
        maximumDeals: Int
    ): List<Boolean> {
        val accepted = mutableListOf<Boolean>()
        var longs = initialLongs.coerceAtLeast(0)
        var shorts = initialShorts.coerceAtLeast(0)
        val maximum = maximumDeals.coerceIn(1, 500)
        for (shortDirection in candidateDirections) {
            if (longs + shorts >= maximum) break
            if (!DirectionBalanceGate.permits(shortDirection, longs, shorts)) continue
            accepted += shortDirection
            if (shortDirection) shorts++ else longs++
        }
        return accepted
    }
}
