package com.tradementor.app.repository

import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.tradementor.app.api.AssetContext
import com.tradementor.app.api.AllMidsRequest
import com.tradementor.app.api.BollingerPosition
import com.tradementor.app.api.BollingerSignal
import com.tradementor.app.api.CandleRequest
import com.tradementor.app.api.CandleSnapshotRequest
import com.tradementor.app.api.CustomScanSignal
import com.tradementor.app.api.HyperliquidApi
import com.tradementor.app.api.MetaRequest
import com.tradementor.app.api.MetaResponse
import com.tradementor.app.api.MultiIndicatorSignal
import com.tradementor.app.api.PerpetualMarket
import com.tradementor.app.api.ScanRule
import com.tradementor.app.api.ScanCondition
import com.tradementor.app.api.ScanMetric
import com.tradementor.app.api.ScanOperator
import com.tradementor.app.api.TimeframeWinRate
import com.tradementor.app.api.RecommendedTrade
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.delay
import kotlin.math.pow
import kotlin.math.sqrt

class MarketRepository {

    companion object {
        @Volatile private var cachedPerpetualMarkets: List<PerpetualMarket> = emptyList()
    }

    private data class CandleCacheEntry(
        val storedAt: Long,
        val candles: List<com.tradementor.app.api.Candle>
    )

    private val scannerCandleCache = mutableMapOf<String, CandleCacheEntry>()

    private val api: HyperliquidApi by lazy {

        val client = OkHttpClient.Builder()
            .build()

        Retrofit.Builder()
            .baseUrl("https://api.hyperliquid.xyz/")
            .client(client)
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(HyperliquidApi::class.java)
    }

    suspend fun getMarkets(): List<PerpetualMarket>? {
        repeat(5) { attempt ->
            val response = api.getMeta(MetaRequest())
            if (response.isSuccessful) {
                val body = response.body()
                if (body != null && body.size() >= 2) {
                    val gson = Gson()
                    val meta = gson.fromJson(body[0], MetaResponse::class.java)
                    val contextType = object : TypeToken<List<AssetContext>>() {}.type
                    val contexts: List<AssetContext> = gson.fromJson(body[1], contextType)
                    val markets = meta.universe.zip(contexts)
                        .filter { (market, context) ->
                            !market.isDelisted &&
                                (context.markPrice.toDoubleOrNull() ?: 0.0) > 0.0
                        }
                        .map { (market, context) -> PerpetualMarket(market, context) }
                    if (markets.isNotEmpty()) cachedPerpetualMarkets = markets
                    return markets
                }
            }
            if (response.code() != 429) return cachedPerpetualMarkets.takeIf { it.isNotEmpty() }
            delay(1_000L * (attempt + 1))
        }
        return cachedPerpetualMarkets.takeIf { it.isNotEmpty() }
    }

    suspend fun getCurrentPrice(symbol: String): Double? = runCatching {
        api.getAllMids(AllMidsRequest()).takeIf { it.isSuccessful }?.body()?.get(symbol)?.toDoubleOrNull()
    }.getOrNull()

    suspend fun getChartCandles(
        symbol: String,
        interval: String,
        count: Int = 500,
        forceRefresh: Boolean = false
    ): List<com.tradementor.app.api.Candle> {
        val cacheKey = "chart|$symbol|$interval|$count"
        val cached = synchronized(scannerCandleCache) { scannerCandleCache[cacheKey] }
        if (!forceRefresh) cached?.takeIf { System.currentTimeMillis() - it.storedAt < 60_000L }?.let { return it.candles }
        val endTime = System.currentTimeMillis()
        repeat(3) { attempt ->
            val response = api.getCandles(
                CandleSnapshotRequest(
                    request = CandleRequest(
                        coin = symbol,
                        interval = interval,
                        startTime = endTime - intervalToMillis(interval) * count.toLong(),
                        endTime = endTime
                    )
                )
            )
            if (response.isSuccessful) {
                val candles = response.body().orEmpty().filter { it.closeTime <= endTime }.sortedBy { it.openTime }
                if (candles.isNotEmpty()) {
                    synchronized(scannerCandleCache) {
                        scannerCandleCache[cacheKey] = CandleCacheEntry(System.currentTimeMillis(), candles)
                    }
                }
                return candles
            }
            if (response.code() != 429 || attempt == 2) {
                error("Koersgrafiek kon niet worden opgehaald (HTTP ${response.code()}).")
            }
            delay(500L * (attempt + 1))
        }
        error("Koersgrafiek kon niet worden opgehaald.")
    }

    suspend fun getTradeChartCandles(
        symbol: String,
        interval: String,
        startedAt: Long,
        expiresAt: Long
    ): List<com.tradementor.app.api.Candle> {
        val intervalMillis = intervalToMillis(interval)
        val now = System.currentTimeMillis()
        val startTime = (startedAt - intervalMillis * 30L).coerceAtLeast(0L)
        val endTime = (expiresAt + intervalMillis * 30L).coerceAtMost(now)
        val response = api.getCandles(
            CandleSnapshotRequest(
                request = CandleRequest(symbol, interval, startTime, endTime)
            )
        )
        if (!response.isSuccessful) error("Historische tradegrafiek kon niet worden opgehaald.")
        return response.body().orEmpty().sortedBy { it.openTime }
    }

    suspend fun getHistoricalWinRates(
        symbol: String,
        profitPercentage: Double,
        shortDirection: Boolean
    ): List<TimeframeWinRate> {
        require(profitPercentage > 0.0)
        val endTime = System.currentTimeMillis()
        suspend fun loadCandles(interval: String): List<com.tradementor.app.api.Candle> {
            return getScannerCandles(
                symbol,
                interval,
                endTime - intervalToMillis(interval) * 1_500L,
                endTime
            )
                .filter { it.closeTime <= endTime }
                .sortedBy { it.openTime }
        }

        val minuteCandles = loadCandles("1m")
        val quarterHourCandles = getScannerCandles(
            symbol,
            "15m",
            endTime - intervalToMillis("15m") * 5_000L,
            endTime
        ).filter { it.closeTime <= endTime }.sortedBy { it.openTime }
        if (minuteCandles.size < 100 || quarterHourCandles.size < 100) {
            error("Onvoldoende historische candles beschikbaar.")
        }

        val shortHorizons = listOf(
            "1 min" to 1,
            "3 min" to 3,
            "5 min" to 5,
            "10 min" to 10
        )
        val longerHorizons = listOf(
            "15 min" to 1,
            "30 min" to 2,
            "1 uur" to 4,
            "2 uur" to 8,
            "4 uur" to 16,
            "6 uur" to 24,
            "8 uur" to 32,
            "12 uur" to 48,
            "18 uur" to 72,
            "24 uur" to 96,
            "2 dagen" to 192,
            "3 dagen" to 288,
            "7 dagen" to 672
        )
        val targetFactor = profitPercentage / 100.0

        fun calculateRates(
            candles: List<com.tradementor.app.api.Candle>,
            horizons: List<Pair<String, Int>>
        ): List<TimeframeWinRate> = horizons.map { (label, bars) ->
            fun situation(index: Int): DoubleArray? {
                if (index < 20) return null
                val closes = candles.subList(index - 19, index + 1).mapNotNull { it.close.toDoubleOrNull() }
                val highs = candles.subList(index - 19, index + 1).mapNotNull { it.high.toDoubleOrNull() }
                val lows = candles.subList(index - 19, index + 1).mapNotNull { it.low.toDoubleOrNull() }
                if (closes.size != 20 || highs.size != 20 || lows.size != 20) return null
                val price = closes.last().takeIf { it > 0.0 } ?: return null
                val sma20 = closes.average()
                val returns = closes.zipWithNext { first, second -> (second - first) / first.coerceAtLeast(1e-12) }
                val volatility = kotlin.math.sqrt(returns.sumOf { it * it } / returns.size)
                return doubleArrayOf(
                    (closes.last() - closes[18]) / closes[18].coerceAtLeast(1e-12),
                    (closes.last() - closes[14]) / closes[14].coerceAtLeast(1e-12),
                    (price - sma20) / sma20.coerceAtLeast(1e-12),
                    volatility,
                    (highs.last() - lows.last()) / price
                )
            }

            val currentSituation = situation(candles.lastIndex)
            val rankedCandidates = if (currentSituation == null) emptyList() else {
                (20 until candles.size - bars)
                    .mapNotNull { index ->
                        situation(index)?.let { historical ->
                            val distance = historical.indices.sumOf { feature ->
                                kotlin.math.abs(historical[feature] - currentSituation[feature])
                            }
                            index to distance
                        }
                    }
                    .sortedBy { it.second }
            }
            val comparableIndices = mutableListOf<Int>()
            val minimumSpacing = bars.coerceAtLeast(1)
            rankedCandidates.forEach { candidate ->
                if (comparableIndices.size < 50 && comparableIndices.none { kotlin.math.abs(it - candidate.first) < minimumSpacing }) {
                    comparableIndices += candidate.first
                }
            }
            var successes = 0
            comparableIndices.forEach { index ->
                val entry = candles[index].close.toDoubleOrNull() ?: return@forEach
                val success = if (shortDirection) {
                    val target = entry * (1.0 - targetFactor)
                    candles.subList(index + 1, index + bars + 1)
                        .mapNotNull { it.low.toDoubleOrNull() }
                        .minOrNull()?.let { it <= target } == true
                } else {
                    val target = entry * (1.0 + targetFactor)
                    candles.subList(index + 1, index + bars + 1)
                        .mapNotNull { it.high.toDoubleOrNull() }
                        .maxOrNull()?.let { it >= target } == true
                }
                if (success) successes++
            }
            TimeframeWinRate(
                timeframe = label,
                percentage = if (comparableIndices.size < 50) 0.0 else successes * 100.0 / comparableIndices.size,
                sampleCount = comparableIndices.size
            )
        }

        return calculateRates(minuteCandles, shortHorizons) +
            calculateRates(quarterHourCandles, longerHorizons)
    }

    suspend fun getWinRatesForSymbols(
        symbols: List<String>,
        profitPercentage: Double,
        shortDirection: Boolean,
        timeframe: String
    ): Map<String, Double> = coroutineScope {
        val results = mutableMapOf<String, Double>()
        symbols.distinct().chunked(12).forEach { batch ->
            val batchResults = batch.map { symbol ->
                async {
                    symbol to runCatching {
                        getSingleHistoricalWinRate(symbol, profitPercentage, shortDirection, timeframe)
                    }.getOrNull()
                }
            }.awaitAll()
            batchResults.forEach { (symbol, percentage) ->
                if (percentage != null) results[symbol] = percentage
            }
        }
        results
    }

    suspend fun getRecommendedTrades(
        symbols: List<String>,
        profitPercentage: Double,
        shortDirection: Boolean,
        minimumWinRate: Double = 90.0
    ): List<RecommendedTrade> = coroutineScope {
        val recommendations = mutableListOf<RecommendedTrade>()
        symbols.distinct().chunked(8).forEach { batch ->
            val batchResults = batch.map { symbol ->
                async {
                    runCatching {
                        getHistoricalWinRates(symbol, profitPercentage, shortDirection)
                            .maxByOrNull { it.percentage }
                            ?.takeIf { it.percentage >= minimumWinRate }
                            ?.let { RecommendedTrade(symbol, it.timeframe, it.percentage) }
                    }.getOrNull()
                }
            }.awaitAll()
            recommendations += batchResults.filterNotNull()
        }
        recommendations.sortedByDescending { it.winRate }
    }

    private suspend fun getSingleHistoricalWinRate(
        symbol: String,
        profitPercentage: Double,
        shortDirection: Boolean,
        timeframe: String
    ): Double {
        val shortTimeframes = mapOf("1 min" to 1, "3 min" to 3, "5 min" to 5, "10 min" to 10)
        val longTimeframes = mapOf(
            "15 min" to 1, "30 min" to 2, "1 uur" to 4, "2 uur" to 8,
            "4 uur" to 16, "6 uur" to 24, "8 uur" to 32, "12 uur" to 48,
            "18 uur" to 72, "24 uur" to 96, "2 dagen" to 192,
            "3 dagen" to 288, "7 dagen" to 672
        )
        val interval = if (timeframe in shortTimeframes) "1m" else "15m"
        val bars = shortTimeframes[timeframe] ?: longTimeframes[timeframe] ?: 96
        val endTime = System.currentTimeMillis()
        val candles = getScannerCandles(
            symbol,
            interval,
            endTime - intervalToMillis(interval) * 1_500L,
            endTime
        ).filter { it.closeTime <= endTime }.sortedBy { it.openTime }
        if (candles.size <= bars) error("Onvoldoende historische candles.")

        val targetFactor = profitPercentage / 100.0
        var samples = 0
        var successes = 0
        for (index in 0 until candles.size - bars step bars.coerceAtLeast(1)) {
            val entry = candles[index].close.toDoubleOrNull() ?: continue
            val success = if (shortDirection) {
                val target = entry * (1.0 - targetFactor)
                candles.subList(index + 1, index + bars + 1)
                    .mapNotNull { it.low.toDoubleOrNull() }
                    .minOrNull()?.let { it <= target } == true
            } else {
                val target = entry * (1.0 + targetFactor)
                candles.subList(index + 1, index + bars + 1)
                    .mapNotNull { it.high.toDoubleOrNull() }
                    .maxOrNull()?.let { it >= target } == true
            }
            samples++
            if (success) successes++
        }
        return if (samples == 0) 0.0 else successes * 100.0 / samples
    }

    suspend fun didTradeSucceed(
        symbol: String,
        entryPrice: Double,
        profitPercentage: Double,
        shortDirection: Boolean,
        startedAt: Long,
        expiresAt: Long
    ): Boolean {
        val duration = expiresAt - startedAt
        val interval = when {
            duration <= 60 * 60_000L -> "1m"
            duration <= 3L * 24 * 60 * 60_000L -> "15m"
            else -> "1h"
        }
        val response = api.getCandles(
            CandleSnapshotRequest(
                request = CandleRequest(symbol, interval, startedAt, expiresAt)
            )
        )
        if (!response.isSuccessful) error("Tradehistorie kon niet worden gecontroleerd.")
        val candles = response.body().orEmpty().filter { it.openTime < expiresAt && it.closeTime > startedAt }.sortedBy { it.closeTime }
        if (candles.isEmpty()) error("Geen candles voor deze trade beschikbaar.")
        val factor = profitPercentage / 100.0
        return if (shortDirection) {
            val target = entryPrice * (1.0 - factor)
            candles.mapNotNull { it.low.toDoubleOrNull() }.minOrNull()?.let { it <= target }
                ?: error("Geen geldige laagste koers beschikbaar.")
        } else {
            val target = entryPrice * (1.0 + factor)
            candles.mapNotNull { it.high.toDoubleOrNull() }.maxOrNull()?.let { it >= target }
                ?: error("Geen geldige hoogste koers beschikbaar.")
        }
    }

    /** 1 = profitdoel eerst geraakt, -1 = risicogrens eerst geraakt, 0 = geen van beide. */
    suspend fun getTradeBarrierOutcome(
        symbol: String,
        entryPrice: Double,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        shortDirection: Boolean,
        startedAt: Long,
        endAt: Long
    ): Int {
        val duration = endAt - startedAt
        val interval = when {
            duration <= 60 * 60_000L -> "1m"
            duration <= 3L * 24 * 60 * 60_000L -> "15m"
            else -> "1h"
        }
        val response = api.getCandles(
            CandleSnapshotRequest(request = CandleRequest(symbol, interval, startedAt, endAt))
        )
        if (!response.isSuccessful) error("Tradehistorie kon niet worden gecontroleerd.")
        val candles = response.body().orEmpty()
            .filter { it.openTime < endAt && it.closeTime > startedAt }
            .sortedBy { it.openTime }
        if (candles.isEmpty()) error("Geen candles voor deze trade beschikbaar.")
        val target = if (shortDirection) entryPrice * (1.0 - profitPercentage / 100.0)
            else entryPrice * (1.0 + profitPercentage / 100.0)
        val stop = if (shortDirection) entryPrice * (1.0 + maxAdversePercentage / 100.0)
            else entryPrice * (1.0 - maxAdversePercentage / 100.0)
        candles.forEach { candle ->
            val high = candle.high.toDoubleOrNull() ?: return@forEach
            val low = candle.low.toDoubleOrNull() ?: return@forEach
            val targetHit = if (shortDirection) low <= target else high >= target
            val stopHit = if (shortDirection) high >= stop else low <= stop
            // Bij beide grenzen in dezelfde candle kiezen we voorzichtig voor de risicogrens.
            if (stopHit) return -1
            if (targetHit) return 1
        }
        return 0
    }

    suspend fun scanBollingerBands(
        markets: List<PerpetualMarket>,
        interval: String = "4h",
        period: Int = 20,
        deviationMultiplier: Double = 2.0,
        onProgress: (Int, Int) -> Unit = { _, _ -> }
    ): List<BollingerSignal> = coroutineScope {
        val endTime = System.currentTimeMillis()
        val intervalMillis = intervalToMillis(interval)
        val startTime = endTime - (intervalMillis * (period + 10L))
        var completed = 0
        val results = mutableListOf<BollingerSignal>()

        markets.chunked(16).forEach { batch ->
            val batchResults = batch.map { market ->
                async {
                    val response = api.getCandles(
                        CandleSnapshotRequest(
                            request = CandleRequest(
                                coin = market.market.name,
                                interval = interval,
                                startTime = startTime,
                                endTime = endTime
                            )
                        )
                    )
                    val candles = if (response.isSuccessful) response.body().orEmpty() else emptyList()
                    calculateBollingerSignal(market.market.name, candles, period, deviationMultiplier)
                }
            }.awaitAll()
            results += batchResults.filterNotNull()
            completed += batch.size
            onProgress(completed, markets.size)
        }

        results.sortedByDescending { kotlin.math.abs(it.distancePercentage) }
    }

    suspend fun scanIndicators(
        markets: List<PerpetualMarket>,
        interval: String,
        rules: Set<ScanRule>,
        requireAll: Boolean,
        onProgress: (Int, Int) -> Unit = { _, _ -> }
    ): List<MultiIndicatorSignal> = coroutineScope {
        if (rules.isEmpty()) return@coroutineScope emptyList()
        val endTime = System.currentTimeMillis()
        val startTime = endTime - (intervalToMillis(interval) * 90L)
        var completed = 0
        val results = mutableListOf<MultiIndicatorSignal>()

        markets.chunked(8).forEach { batch ->
            val batchResults = batch.map { market ->
                async {
                    val response = api.getCandles(
                        CandleSnapshotRequest(
                            request = CandleRequest(market.market.name, interval, startTime, endTime)
                        )
                    )
                    val candles = if (response.isSuccessful) response.body().orEmpty() else emptyList()
                    calculateIndicatorSignal(market.market.name, candles, rules, requireAll)
                }
            }.awaitAll()
            results += batchResults.filterNotNull()
            completed += batch.size
            onProgress(completed, markets.size)
        }
        results.sortedByDescending { it.matchedRules.size }
    }

    suspend fun scanCustomConditions(
        markets: List<PerpetualMarket>,
        conditions: List<ScanCondition>,
        requireAll: Boolean,
        onProgress: (Int, Int) -> Unit = { _, _ -> }
    ): List<CustomScanSignal> = coroutineScope {
        if (conditions.isEmpty()) return@coroutineScope emptyList()
        val endTime = System.currentTimeMillis()
        val conditionsByInterval = conditions.groupBy { it.interval }
        val totalJobs = markets.size * conditionsByInterval.size
        var completed = 0
        val results = mutableListOf<CustomScanSignal>()

        markets.chunked(16).forEach { batch ->
            val batchResults = batch.map { market ->
                async {
                    val intervalSignals = conditionsByInterval.mapNotNull { (interval, intervalConditions) ->
                        val startTime = endTime - (intervalToMillis(interval) * 110L)
                        val candles = getScannerCandles(market.market.name, interval, startTime, endTime)
                        evaluateCustomConditions(market, candles, intervalConditions, false)
                    }
                    val matchedIds = intervalSignals.flatMap { it.matchedConditionIds }
                    val accepted = if (requireAll) matchedIds.size == conditions.size else matchedIds.isNotEmpty()
                    if (!accepted) null else CustomScanSignal(
                        symbol = market.market.name,
                        price = market.context.markPrice.toDoubleOrNull() ?: intervalSignals.first().price,
                        matchedConditionIds = matchedIds,
                        candleCloseTime = intervalSignals.maxOf { it.candleCloseTime }
                    )
                }
            }.awaitAll()
            results += batchResults.filterNotNull()
            completed += batch.size * conditionsByInterval.size
            onProgress(completed.coerceAtMost(totalJobs), totalJobs)
        }
        results.sortedByDescending { it.matchedConditionIds.size }
    }

    private suspend fun getScannerCandles(
        symbol: String,
        interval: String,
        startTime: Long,
        endTime: Long
    ): List<com.tradementor.app.api.Candle> {
        val key = "$symbol|$interval"
        val now = System.currentTimeMillis()
        scannerCandleCache[key]?.takeIf { now - it.storedAt < 30_000L }?.let { return it.candles }
        val response = api.getCandles(
            CandleSnapshotRequest(
                request = CandleRequest(symbol, interval, startTime, endTime)
            )
        )
        val candles = if (response.isSuccessful) response.body().orEmpty() else emptyList()
        if (candles.isNotEmpty()) scannerCandleCache[key] = CandleCacheEntry(now, candles)
        return candles
    }

    private fun evaluateCustomConditions(
        market: PerpetualMarket,
        rawCandles: List<com.tradementor.app.api.Candle>,
        conditions: List<ScanCondition>,
        requireAll: Boolean
    ): CustomScanSignal? {
        val candles = rawCandles.filter { it.closeTime <= System.currentTimeMillis() }.sortedBy { it.openTime }
        if (candles.size < 55) return null
        val closes = candles.mapNotNull { it.close.toDoubleOrNull() }
        val opens = candles.mapNotNull { it.open.toDoubleOrNull() }
        val highs = candles.mapNotNull { it.high.toDoubleOrNull() }
        val lows = candles.mapNotNull { it.low.toDoubleOrNull() }
        val volumes = candles.mapNotNull { it.volume.toDoubleOrNull() }
        if (listOf(closes.size, opens.size, highs.size, lows.size, volumes.size).any { it != candles.size }) return null

        val values = calculateMetricValues(market, closes, opens, highs, lows, volumes)
        val matched = conditions.filter { condition ->
            val value = values[condition.metric] ?: return@filter false
            when (condition.operator) {
                ScanOperator.LessThan -> value < condition.threshold
                ScanOperator.LessOrEqual -> value <= condition.threshold
                ScanOperator.GreaterThan -> value > condition.threshold
                ScanOperator.GreaterOrEqual -> value >= condition.threshold
            }
        }
        val accepted = if (requireAll) matched.size == conditions.size else matched.isNotEmpty()
        if (!accepted) return null
        return CustomScanSignal(
            symbol = market.market.name,
            price = closes.last(),
            matchedConditionIds = matched.map { it.id },
            candleCloseTime = candles.last().closeTime
        )
    }

    private fun calculateMetricValues(
        market: PerpetualMarket,
        closes: List<Double>,
        opens: List<Double>,
        highs: List<Double>,
        lows: List<Double>,
        volumes: List<Double>
    ): Map<ScanMetric, Double> {
        val price = closes.last()
        val sma20 = closes.takeLast(20).average()
        val sma50 = closes.takeLast(50).average()
        val std20 = sqrt(closes.takeLast(20).sumOf { (it - sma20).pow(2) } / 20)
        val upper = sma20 + 2 * std20
        val lower = sma20 - 2 * std20
        val ema20 = calculateEma(closes, 20)
        val ema50 = calculateEma(closes, 50)
        val macd = calculateEma(closes, 12) - calculateEma(closes, 26)
        val averageVolume = volumes.dropLast(1).takeLast(20).average()
        val high20 = highs.dropLast(1).takeLast(20).maxOrNull() ?: price
        val low20 = lows.dropLast(1).takeLast(20).minOrNull() ?: price
        val low14 = lows.takeLast(14).minOrNull() ?: price
        val high14 = highs.takeLast(14).maxOrNull() ?: price
        val stochastic = if (high14 == low14) 50.0 else ((price - low14) / (high14 - low14)) * 100
        val trueRanges = highs.indices.drop(1).map { index ->
            maxOf(highs[index] - lows[index], kotlin.math.abs(highs[index] - closes[index - 1]), kotlin.math.abs(lows[index] - closes[index - 1]))
        }
        val atr = trueRanges.takeLast(14).average()
        val typicalPrices = highs.indices.map { (highs[it] + lows[it] + closes[it]) / 3.0 }
        val typicalMean = typicalPrices.takeLast(20).average()
        val meanDeviation = typicalPrices.takeLast(20).sumOf { kotlin.math.abs(it - typicalMean) } / 20
        val cci = if (meanDeviation == 0.0) 0.0 else (typicalPrices.last() - typicalMean) / (0.015 * meanDeviation)

        return mapOf(
            ScanMetric.Rsi to calculateRsi(closes, 14),
            ScanMetric.DayVolumeUsd to (market.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0),
            ScanMetric.PriceChange24h to market.changePercentage,
            ScanMetric.FundingRate to ((market.context.funding.toDoubleOrNull() ?: 0.0) * 100),
            ScanMetric.OpenInterest to (market.context.openInterest.toDoubleOrNull() ?: 0.0),
            ScanMetric.Price to price,
            ScanMetric.BollingerUpperDistance to percentageDistance(price, upper),
            ScanMetric.BollingerLowerDistance to percentageDistance(price, lower),
            ScanMetric.Ema20Distance to percentageDistance(price, ema20),
            ScanMetric.Ema50Distance to percentageDistance(price, ema50),
            ScanMetric.Sma20Distance to percentageDistance(price, sma20),
            ScanMetric.Sma50Distance to percentageDistance(price, sma50),
            ScanMetric.MacdPercent to if (price == 0.0) 0.0 else (macd / price) * 100,
            ScanMetric.VolumeRatio to if (averageVolume == 0.0) 0.0 else volumes.last() / averageVolume,
            ScanMetric.Roc14 to percentageDistance(price, closes[closes.lastIndex - 14]),
            ScanMetric.Stochastic14 to stochastic,
            ScanMetric.AtrPercent to if (price == 0.0) 0.0 else (atr / price) * 100,
            ScanMetric.CandleChange to percentageDistance(closes.last(), opens.last()),
            ScanMetric.CandleVolume to volumes.last(),
            ScanMetric.BreakoutHigh20 to percentageDistance(price, high20),
            ScanMetric.BreakdownLow20 to percentageDistance(price, low20),
            ScanMetric.Volatility20 to if (sma20 == 0.0) 0.0 else (std20 / sma20) * 100,
            ScanMetric.Momentum10 to percentageDistance(price, closes[closes.lastIndex - 10]),
            ScanMetric.WilliamsR to if (high14 == low14) -50.0 else ((high14 - price) / (high14 - low14)) * -100,
            ScanMetric.Cci20 to cci
        )
    }

    private fun percentageDistance(value: Double, reference: Double): Double =
        if (reference == 0.0) 0.0 else ((value - reference) / reference) * 100

    private fun calculateIndicatorSignal(
        symbol: String,
        rawCandles: List<com.tradementor.app.api.Candle>,
        rules: Set<ScanRule>,
        requireAll: Boolean
    ): MultiIndicatorSignal? {
        val candles = rawCandles.filter { it.closeTime <= System.currentTimeMillis() }.sortedBy { it.openTime }
        if (candles.size < 35) return null
        val closes = candles.mapNotNull { it.close.toDoubleOrNull() }
        val highs = candles.mapNotNull { it.high.toDoubleOrNull() }
        val lows = candles.mapNotNull { it.low.toDoubleOrNull() }
        val volumes = candles.mapNotNull { it.volume.toDoubleOrNull() }
        if (closes.size != candles.size || highs.size != candles.size || lows.size != candles.size || volumes.size != candles.size) return null
        val price = closes.last()
        val previousCloses = closes.dropLast(1)
        val last20 = closes.takeLast(20)
        val middle = last20.average()
        val stdDev = sqrt(last20.sumOf { (it - middle).pow(2) } / 20)
        val upper = middle + 2 * stdDev
        val lower = middle - 2 * stdDev
        val rsi = calculateRsi(closes, 14)
        val ema20 = calculateEma(closes, 20)
        val macd = calculateEma(closes, 12) - calculateEma(closes, 26)
        val previousMacd = calculateEma(closes.dropLast(1), 12) - calculateEma(closes.dropLast(1), 26)
        val averageVolume = volumes.dropLast(1).takeLast(20).average()
        val previousHigh = highs.dropLast(1).takeLast(20).maxOrNull() ?: Double.MAX_VALUE
        val previousLow = lows.dropLast(1).takeLast(20).minOrNull() ?: Double.MIN_VALUE

        val matches = rules.filter { rule ->
            when (rule) {
                ScanRule.BollingerAbove -> price > upper
                ScanRule.BollingerBelow -> price < lower
                ScanRule.RsiOverbought -> rsi > 70
                ScanRule.RsiOversold -> rsi < 30
                ScanRule.EmaBearish -> price < ema20
                ScanRule.EmaBullish -> price > ema20
                ScanRule.MacdBearish -> macd < 0 && macd < previousMacd
                ScanRule.MacdBullish -> macd > 0 && macd > previousMacd
                ScanRule.VolumeSpike -> averageVolume > 0 && volumes.last() > averageVolume * 2
                ScanRule.BreakoutHigh -> price > previousHigh
                ScanRule.BreakdownLow -> price < previousLow
            }
        }
        val accepted = if (requireAll) matches.size == rules.size else matches.isNotEmpty()
        if (!accepted) return null
        return MultiIndicatorSignal(symbol, price, matches, candles.last().closeTime)
    }

    private fun calculateEma(values: List<Double>, period: Int): Double {
        if (values.isEmpty()) return 0.0
        val multiplier = 2.0 / (period + 1)
        return values.drop(1).fold(values.first()) { ema, value ->
            (value - ema) * multiplier + ema
        }
    }

    private fun calculateRsi(values: List<Double>, period: Int): Double {
        if (values.size <= period) return 50.0
        val changes = values.zipWithNext { first, second -> second - first }.takeLast(period)
        val averageGain = changes.filter { it > 0 }.sum() / period
        val averageLoss = -changes.filter { it < 0 }.sum() / period
        if (averageLoss == 0.0) return 100.0
        val relativeStrength = averageGain / averageLoss
        return 100.0 - (100.0 / (1.0 + relativeStrength))
    }

    private fun calculateBollingerSignal(
        symbol: String,
        candles: List<com.tradementor.app.api.Candle>,
        period: Int,
        multiplier: Double
    ): BollingerSignal? {
        val sortedCandles = candles
            .filter { it.closeTime <= System.currentTimeMillis() }
            .sortedBy { it.openTime }
        if (sortedCandles.size < period) return null
        val latest = sortedCandles.last()
        val closes = sortedCandles.takeLast(period).mapNotNull { it.close.toDoubleOrNull() }
        if (closes.size < period) return null

        val middle = closes.average()
        val standardDeviation = sqrt(closes.sumOf { (it - middle).pow(2) } / period)
        val upper = middle + (standardDeviation * multiplier)
        val lower = middle - (standardDeviation * multiplier)
        val price = closes.last()
        val position = when {
            price > upper -> BollingerPosition.AboveUpper
            price < lower -> BollingerPosition.BelowLower
            else -> return null
        }    
        val referenceBand = if (position == BollingerPosition.AboveUpper) upper else lower
        return BollingerSignal(
            symbol = symbol,
            price = price,
            middleBand = middle,
            upperBand = upper,
            lowerBand = lower,
            distancePercentage = ((price - referenceBand) / referenceBand) * 100.0,
            position = position,
            candleCloseTime = latest.closeTime
        )
    }

    private fun intervalToMillis(interval: String): Long = when (interval) {
        "1m" -> 60_000L
        "3m" -> 3 * 60_000L
        "5m" -> 5 * 60_000L
        "15m" -> 15 * 60_000L
        "30m" -> 30 * 60_000L
        "1h" -> 60 * 60_000L
        "2h" -> 2 * 60 * 60_000L
        "4h" -> 4 * 60 * 60_000L
        "8h" -> 8 * 60 * 60_000L
        "12h" -> 12 * 60 * 60_000L
        "1d" -> 24 * 60 * 60_000L
        "3d" -> 3 * 24 * 60 * 60_000L
        "1w" -> 7 * 24 * 60 * 60_000L
        else -> 4 * 60 * 60_000L
    }
}
