package com.tradementor.app.scanner

import com.tradementor.app.repository.MarketRepository
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.delay
import kotlinx.coroutines.withContext

data class BacktestTrade(
    val symbol: String,
    val shortDirection: Boolean,
    val signalTime: Long,
    val entryPrice: Double,
    val targetPrice: Double,
    val predictedWinRate: Double,
    val qualityScore: Double,
    val indicators: List<String>,
    val succeeded: Boolean,
    val stopped: Boolean,
    val resolvedAfterHours: Int?,
    val analysisTimeframe: String,
    val selectionReason: String,
    val outcomeReason: String,
    val bestFavourableMove: Double,
    val worstAdverseMove: Double,
    val returnPercentage: Double
)

data class BacktestReport(val trades: List<BacktestTrade>) {
    val succeeded: Int get() = trades.count { it.succeeded }
    val failed: Int get() = trades.size - succeeded
    val successRate: Double get() = if (trades.isEmpty()) 0.0 else succeeded * 100.0 / trades.size
    val averagePrediction: Double get() = trades.map { it.predictedWinRate }.average().takeUnless { it.isNaN() } ?: 0.0
}

class BacktestEngine(private val repository: MarketRepository) {
    private val advisor = AdvisorEngine(repository)

    suspend fun run(
        weeksAgo: Int = 4,
        signalCount: Int = 50,
        profitPercentage: Double = 1.0,
        maxAdversePercentage: Double = 20.0,
        onProgress: suspend (Int, Int) -> Unit = { _, _ -> }
    ): BacktestReport = withContext(Dispatchers.Default) {
        val marketsNeeded = (signalCount / 10).coerceIn(10, 25)
        val checkpointsPerMarket = (signalCount + marketsNeeded - 1) / marketsNeeded
        val markets = repository.getMarkets().orEmpty()
            .sortedByDescending { it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0 }
            .take(marketsNeeded)
        val total = markets.size * checkpointsPerMarket
        val results = mutableListOf<BacktestTrade>()
        var completed = 0
        val now = System.currentTimeMillis()
        val timeframe = when {
            weeksAgo <= 12 -> "2h"
            weeksAgo <= 52 -> "4h"
            else -> "1d"
        }
        val intervalHours = when (timeframe) { "2h" -> 2; "4h" -> 4; else -> 24 }
        val horizonBars = 7 * 24 / intervalHours
        val periodEnd = now - 7L * 24L * 60L * 60_000L
        val periodStart = periodEnd - weeksAgo * 7L * 24L * 60L * 60_000L
        val candleCount = (weeksAgo * 7 * 24 / intervalHours + 350).coerceIn(500, 4_000)

        markets.forEach { market ->
            val candles = runCatching { repository.getChartCandles(market.market.name, timeframe, candleCount) }.getOrDefault(emptyList())
            val firstIndex = candles.indexOfFirst { it.closeTime >= periodStart }.takeIf { it >= 0 } ?: 180
            val lastIndex = candles.indexOfLast { it.closeTime <= periodEnd }
            val usableStart = firstIndex.coerceAtLeast(180)
            val usableSpan = (lastIndex - usableStart).coerceAtLeast(0)
            val spacing = (usableSpan / checkpointsPerMarket.coerceAtLeast(1)).coerceAtLeast(1)
            repeat(checkpointsPerMarket) { checkpoint ->
                val signalIndex = (usableStart + checkpoint * spacing).coerceAtMost(lastIndex)
                if (signalIndex >= 180 && signalIndex + horizonBars < candles.size) {
                    val historyOnly = candles.subList(0, signalIndex + 1)
                    val entry = candles[signalIndex].close.toDoubleOrNull() ?: 0.0
                    val recommendation = runCatching {
                        advisor.scoreCandleSeries(
                            symbol = market.market.name,
                            price = entry,
                            timeframe = timeframe,
                            candles = historyOnly,
                            profitPercentage = profitPercentage,
                            maxAdversePercentage = maxAdversePercentage,
                            minimumSamples = 30,
                            outcomeMinutes = 7 * 24 * 60,
                            allowLong = true,
                            allowShort = true
                        )
                    }.getOrNull()
                    if (recommendation != null && entry > 0.0) {
                        val target = recommendation.targetPrice
                        val stop = if (recommendation.shortDirection) entry * (1 + maxAdversePercentage / 100.0)
                        else entry * (1 - maxAdversePercentage / 100.0)
                        var success = false
                        var stopped = false
                        var resolvedBars: Int? = null
                        var bestFavourable = 0.0
                        var worstAdverse = 0.0
                        candles.subList(signalIndex + 1, signalIndex + horizonBars + 1).forEachIndexed { index, candle ->
                            val high = candle.high.toDoubleOrNull() ?: entry
                            val low = candle.low.toDoubleOrNull() ?: entry
                            if (!success && !stopped) {
                                val favourable = if (recommendation.shortDirection) (entry - low) / entry * 100.0 else (high - entry) / entry * 100.0
                                val adverse = if (recommendation.shortDirection) (high - entry) / entry * 100.0 else (entry - low) / entry * 100.0
                                bestFavourable = maxOf(bestFavourable, favourable)
                                worstAdverse = maxOf(worstAdverse, adverse)
                                stopped = if (recommendation.shortDirection) high >= stop else low <= stop
                                if (!stopped) success = if (recommendation.shortDirection) low <= target else high >= target
                                if (success || stopped) resolvedBars = index + 1
                            }
                        }
                        results += BacktestTrade(
                            symbol = recommendation.symbol,
                            shortDirection = recommendation.shortDirection,
                            signalTime = candles[signalIndex].closeTime,
                            entryPrice = entry,
                            targetPrice = target,
                            predictedWinRate = recommendation.winRate,
                            qualityScore = recommendation.qualityScore,
                            indicators = recommendation.indicators,
                            succeeded = success,
                            stopped = stopped,
                            resolvedAfterHours = resolvedBars?.times(intervalHours),
                            analysisTimeframe = timeframe,
                            selectionReason = recommendation.indicators.joinToString(" + ").ifBlank { "Prijsstructuur, momentum en volatiliteit" },
                            outcomeReason = when {
                                success -> "Profitdoel van ${String.format("%.1f", profitPercentage)}% werd vóór de risicogrens geraakt."
                                stopped -> "De maximale tegenbeweging van ${String.format("%.1f", maxAdversePercentage)}% werd vóór het profitdoel geraakt."
                                else -> "Het profitdoel werd binnen zeven dagen niet geraakt; de trade liep niet tegen de risicogrens."
                            },
                            bestFavourableMove = bestFavourable,
                            worstAdverseMove = worstAdverse,
                            returnPercentage = when {
                                success -> profitPercentage
                                stopped -> -maxAdversePercentage
                                else -> {
                                    val expiryClose = candles[signalIndex + horizonBars].close.toDoubleOrNull() ?: entry
                                    if (recommendation.shortDirection) (entry - expiryClose) / entry * 100.0
                                    else (expiryClose - entry) / entry * 100.0
                                }
                            }
                        )
                    }
                }
                completed++
                withContext(Dispatchers.Main) { onProgress(completed, total) }
            }
            delay(250)
        }
        BacktestReport(results.sortedByDescending { it.signalTime }.take(signalCount))
    }
}
