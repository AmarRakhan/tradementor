package com.tradementor.app.scanner

import android.util.Log
import com.tradementor.app.api.AdvisorRecommendation
import com.tradementor.app.api.Candle
import com.tradementor.app.repository.MarketRepository
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import kotlinx.coroutines.delay
import kotlin.math.pow
import kotlin.math.sqrt
import java.util.concurrent.ConcurrentHashMap

class AdvisorEngine(private val repository: MarketRepository) {

    data class OpenTradeAssessment(
        val winRate: Double,
        val currentPrice: Double,
        val advice: String,
        val reason: String
    )

    data class AddOnAssessment(val approved: Boolean, val winRate: Double, val qualityScore: Double, val currentPrice: Double, val reason: String)

    suspend fun assessAddOn(trade: TrackedTrade, minimumWinRate: Double, minimumScore: Double): AddOnAssessment? {
        val market = repository.getMarkets().orEmpty().firstOrNull { it.market.name.equals(trade.symbol, true) }
            ?: return AddOnAssessment(false, 0.0, 0.0, 0.0, "Marktdata ontbreekt voor deze pair.")
        val currentPrice = market.context.markPrice.toDoubleOrNull()?.takeIf { it > 0.0 }
            ?: return AddOnAssessment(false, 0.0, 0.0, 0.0, "Actuele koers ontbreekt.")
        val adversePct = if (trade.shortDirection) (currentPrice / trade.entryPrice - 1.0) * 100.0 else (1.0 - currentPrice / trade.entryPrice) * 100.0
        if (adversePct < 0.20) return AddOnAssessment(false, 0.0, 0.0, currentPrice, "Nog geen zinvolle terugloop.")
        if (adversePct > trade.maxAdversePercentage.coerceAtLeast(1.0) * 0.70) return AddOnAssessment(false, 0.0, 0.0, currentPrice, "Tegenbeweging is te groot.")
        val scores = listOf("5m" to 240, "15m" to 1440).map { (tf, horizon) ->
            scoreCandleSeries(trade.symbol, currentPrice, tf, repository.getChartCandles(trade.symbol, tf, 500, forceRefresh = true), trade.profitPercentage, trade.maxAdversePercentage, 75, horizon, !trade.shortDirection, trade.shortDirection)
        }.filterNotNull()
        val strictWinRate = maxOf(80.0, minimumWinRate)
        val strictScore = maxOf(70.0, minimumScore)
        val winRate = scores.minOfOrNull { it.winRate } ?: 0.0
        val quality = scores.minOfOrNull { it.qualityScore } ?: 0.0
        val directionConfirmed = scores.size == 2 && scores.all { it.shortDirection == trade.shortDirection }
        val approved = directionConfirmed && winRate >= strictWinRate && quality >= strictScore
        val reason = when {
            approved -> "5m en 15m bevestigen dezelfde richting."
            scores.size < 2 -> "Niet genoeg betrouwbare 5m- en 15m-data."
            !directionConfirmed -> "5m en 15m bevestigen de huidige richting niet allebei."
            winRate < strictWinRate -> "Winkans ${"%.0f".format(winRate)}% is lager dan vereist ${"%.0f".format(strictWinRate)}%."
            quality < strictScore -> "Kwaliteit ${"%.0f".format(quality)} is lager dan vereist ${"%.0f".format(strictScore)}."
            else -> "Hercontrole niet sterk genoeg."
        }
        return AddOnAssessment(approved, winRate, quality, currentPrice, reason)
    }

    companion object {
        private val scanResultCache = ConcurrentHashMap<String, ConcurrentHashMap<String, AdvisorRecommendation>>()
        private val processedMarketCache = ConcurrentHashMap<String, MutableSet<String>>()
    }

    suspend fun scoreCandleSeries(
        symbol: String,
        price: Double,
        timeframe: String,
        candles: List<Candle>,
        profitPercentage: Double,
        maxAdversePercentage: Double = 1.0,
        minimumSamples: Int,
        outcomeMinutes: Int,
        allowLong: Boolean,
        allowShort: Boolean
    ): AdvisorRecommendation? = withContext(Dispatchers.Default) {
        if (timeframeMinutes(timeframe) > outcomeMinutes) null else analyzeTimeframe(
            symbol = symbol,
            price = price,
            timeframe = timeframe,
            candles = candles,
            profitPercentage = profitPercentage,
            maxAdversePercentage = maxAdversePercentage,
            minimumSamples = minimumSamples,
            outcomeMinutes = outcomeMinutes,
            forcedShortDirection = when {
                allowLong && !allowShort -> false
                allowShort && !allowLong -> true
                else -> null
            }
        )
    }

    suspend fun assessOpenTrade(trade: TrackedTrade, now: Long = System.currentTimeMillis()): OpenTradeAssessment? {
        val remainingMinutes = ((trade.expiresAt - now) / 60_000L).toInt().coerceAtLeast(1)
        if (trade.expiresAt <= now) return null
        val market = repository.getMarkets().orEmpty().firstOrNull { it.market.name == trade.symbol } ?: return null
        val currentPrice = market.context.markPrice.toDoubleOrNull()?.takeIf { it > 0.0 } ?: return null
        val target = if (trade.shortDirection) {
            trade.entryPrice * (1.0 - trade.profitPercentage / 100.0)
        } else {
            trade.entryPrice * (1.0 + trade.profitPercentage / 100.0)
        }
        val requiredMove = if (trade.shortDirection) {
            ((currentPrice - target) / currentPrice) * 100.0
        } else {
            ((target - currentPrice) / currentPrice) * 100.0
        }
        if (requiredMove <= 0.0) return OpenTradeAssessment(100.0, currentPrice, "Vasthouden", "Het oorspronkelijke profitdoel is bereikt.")
        val timeframe = baseAnalysisTimeframe(remainingMinutes)
        val score = scoreCandleSeries(
            symbol = trade.symbol,
            price = currentPrice,
            timeframe = timeframe,
            candles = repository.getChartCandles(trade.symbol, timeframe, 500),
            profitPercentage = requiredMove,
            maxAdversePercentage = trade.maxAdversePercentage,
            minimumSamples = 50,
            outcomeMinutes = remainingMinutes,
            allowLong = !trade.shortDirection,
            allowShort = trade.shortDirection
        ) ?: return null
        val advice = when {
            score.winRate >= 50.0 -> "Vasthouden"
            score.winRate >= 25.0 -> "Let op"
            else -> "Lage kans"
        }
        val reason = when (advice) {
            "Vasthouden" -> "Het oorspronkelijke doel blijft historisch haalbaar vanuit de actuele koers."
            "Let op" -> "De kans op het oorspronkelijke doel is afgenomen; blijf de trade volgen."
            else -> "De kans om het oorspronkelijke doel op tijd te bereiken is momenteel laag."
        }
        return OpenTradeAssessment(score.winRate, currentPrice, advice, reason)
    }

    suspend fun validateForEntry(
        recommendation: AdvisorRecommendation,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        minimumWinRate: Double,
        minimumScore: Double
    ): AdvisorRecommendation? {
        val currentPrice = repository.getCurrentPrice(recommendation.symbol)?.takeIf { it > 0.0 } ?: return null
        val drift = kotlin.math.abs(currentPrice - recommendation.price) / recommendation.price * 100.0
        val allowedDrift = (profitPercentage * 0.25).coerceIn(0.10, 0.50)
        val refreshed = if (drift <= allowedDrift) {
            recommendation.copy(
                price = currentPrice,
                targetPrice = if (recommendation.shortDirection) currentPrice * (1.0 - profitPercentage / 100.0)
                    else currentPrice * (1.0 + profitPercentage / 100.0)
            )
        } else {
            val outcomeMinutes = when (recommendation.analysisTimeframe) {
                "1m" -> 30
                "5m" -> 4 * 60
                "15m" -> 24 * 60
                else -> 7 * 24 * 60
            }
            scoreCandleSeries(
                symbol = recommendation.symbol,
                price = currentPrice,
                timeframe = recommendation.analysisTimeframe,
                candles = repository.getChartCandles(recommendation.symbol, recommendation.analysisTimeframe, 500, forceRefresh = true),
                profitPercentage = profitPercentage,
                maxAdversePercentage = maxAdversePercentage,
                minimumSamples = 50,
                outcomeMinutes = outcomeMinutes,
                allowLong = !recommendation.shortDirection,
                allowShort = recommendation.shortDirection
            )
        }
        return refreshed?.takeIf {
            it.shortDirection == recommendation.shortDirection &&
                it.winRate >= minimumWinRate && it.qualityScore >= minimumScore
        }
    }

    suspend fun analyze(
        minimumWinRate: Double = 80.0,
        profitPercentage: Double = 1.0,
        maxAdversePercentage: Double = 1.0,
        minimumSamples: Int = 50,
        outcomeMinutes: Int = 24 * 60,
        allowLong: Boolean = true,
        allowShort: Boolean = true,
        excludedSymbols: Set<String> = emptySet(),
        onProgress: suspend (results: List<AdvisorRecommendation>, completed: Int, total: Int) -> Unit = { _, _, _ -> }
    ): List<AdvisorRecommendation> = withContext(Dispatchers.Default) { coroutineScope {
        val markets = repository.getMarkets().orEmpty()
            .filterNot { it.market.name.uppercase() in excludedSymbols }
            .sortedByDescending { it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0 }
        val plans = listOf(
            AnalysisPlan("1m", 30),
            AnalysisPlan("5m", 4 * 60),
            AnalysisPlan("15m", 24 * 60),
            AnalysisPlan("2h", 7 * 24 * 60)
        )
        val quarterHourBucket = System.currentTimeMillis() / (15 * 60_000L)
        val scanKey = listOf("multi-timeframe-risk-v2", quarterHourBucket, profitPercentage, maxAdversePercentage, allowLong, allowShort).joinToString("|")
        val cachedScores = scanResultCache.getOrPut(scanKey) { ConcurrentHashMap() }
        val processedMarkets = processedMarketCache.getOrPut(scanKey) { ConcurrentHashMap.newKeySet() }
        val recommendations = cachedScores.values
            .filter { it.winRate >= minimumWinRate && it.symbol.uppercase() !in excludedSymbols }
            .toMutableList()
        // Every non-active market participates in the lightweight first pass.
        // Deep candle analysis rotates through stable groups, so the complete
        // universe is covered without exceeding the phone's API budget.
        val deepBatchSize = 30
        val rotationUniverse = markets.sortedBy { it.market.name }
        val batchCount = ((rotationUniverse.size + deepBatchSize - 1) / deepBatchSize).coerceAtLeast(1)
        val batchIndex = (quarterHourBucket % batchCount).toInt()
        val scanMarkets = rotationUniverse.drop(batchIndex * deepBatchSize).take(deepBatchSize)
        val remainingMarkets = scanMarkets.filterNot { it.market.name in processedMarkets }
        val marketsWithCandleData = ConcurrentHashMap.newKeySet<String>()

        val lightweightCompleted = (markets.size - scanMarkets.size).coerceAtLeast(0)
        var completed = lightweightCompleted + scanMarkets.size - remainingMarkets.size
        Log.d("TradeMentorAdvisor", "universe=${markets.size} deepBatch=${batchIndex + 1}/$batchCount size=${scanMarkets.size}")
        withContext(Dispatchers.Main) {
            onProgress(recommendations.sortedByDescending { it.winRate }, completed, markets.size)
        }
        remainingMarkets.chunked(1).forEach { batch ->
            val batchResults = batch.map { market ->
                async {
                    val candidates = plans.mapNotNull { plan ->
                        val outcome = runCatching {
                            val candleData = repository.getChartCandles(market.market.name, plan.timeframe, 500)
                            if (candleData.isNotEmpty()) marketsWithCandleData += market.market.name
                            Log.d("TradeMentorAdvisor", "${market.market.name} ${plan.timeframe} candles=${candleData.size}")
                            analyzeTimeframe(
                                symbol = market.market.name,
                                price = market.context.markPrice.toDoubleOrNull() ?: 0.0,
                                timeframe = plan.timeframe,
                                candles = candleData,
                                profitPercentage = profitPercentage,
                                maxAdversePercentage = maxAdversePercentage,
                                minimumSamples = minimumSamples,
                                outcomeMinutes = plan.outcomeMinutes,
                                forcedShortDirection = when {
                                    allowLong && !allowShort -> false
                                    allowShort && !allowLong -> true
                                    else -> null
                                }
                            )
                        }
                        outcome.exceptionOrNull()?.let { error ->
                            Log.e("TradeMentorAdvisor", "${market.market.name} ${plan.timeframe} failed", error)
                        }
                        outcome.getOrNull().also { recommendation ->
                            if (recommendation == null && outcome.isSuccess) Log.w("TradeMentorAdvisor", "${market.market.name} ${plan.timeframe} produced no score")
                        }
                    }
                    candidates.maxByOrNull { it.winRate }
                }
            }.awaitAll()
            batchResults.filterNotNull().forEach { recommendation ->
                cachedScores[recommendation.symbol] = recommendation
                if (recommendation.winRate >= minimumWinRate) recommendations += recommendation
            }
            processedMarkets += batch.map { it.market.name }
            completed += batch.size
            withContext(Dispatchers.Main) {
                onProgress(recommendations.sortedByDescending { it.winRate }, completed, markets.size)
            }
            delay(1_000)
        }
        if (remainingMarkets.isNotEmpty() && marketsWithCandleData.isEmpty()) {
            error("Geen historische marktdata ontvangen; scanresultaat is niet geldig")
        }
        recommendations.sortedByDescending { it.winRate }
    } }

    suspend fun scoreScannerResults(
        symbols: List<String>,
        shortDirection: Boolean,
        outcomeMinutes: Int,
        profitPercentage: Double = 1.0,
        maxAdversePercentage: Double = 1.0,
        minimumSamples: Int = 50
    ): List<AdvisorRecommendation> = withContext(Dispatchers.Default) { coroutineScope {
        val symbolSet = symbols.toSet()
        val markets = repository.getMarkets().orEmpty().filter { it.market.name in symbolSet }
        // The visible list needs one dependable score per pair. A single suitable
        // interval avoids four large downloads and still yields 50 independent outcomes.
        val timeframes = listOf(baseAnalysisTimeframe(outcomeMinutes))
        val scores = mutableListOf<AdvisorRecommendation>()
        markets.chunked(8).forEach { batch ->
            val batchResults = batch.map { market ->
                async {
                    timeframes.mapNotNull { timeframe ->
                        runCatching {
                            analyzeTimeframe(
                                symbol = market.market.name,
                                price = market.context.markPrice.toDoubleOrNull() ?: 0.0,
                                timeframe = timeframe,
                                candles = repository.getChartCandles(market.market.name, timeframe, 1_500),
                                profitPercentage = profitPercentage,
                                maxAdversePercentage = maxAdversePercentage,
                                minimumSamples = minimumSamples,
                                outcomeMinutes = outcomeMinutes,
                                forcedShortDirection = shortDirection
                            )
                        }.getOrNull()
                    }.maxByOrNull { it.winRate }
                }
            }.awaitAll()
            scores += batchResults.filterNotNull()
        }
        scores.sortedByDescending { it.winRate }
    } }

    private fun analyzeTimeframe(
        symbol: String,
        price: Double,
        timeframe: String,
        candles: List<Candle>,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        minimumSamples: Int,
        outcomeMinutes: Int,
        forcedShortDirection: Boolean?
    ): AdvisorRecommendation? {
        val clean = candles.mapNotNull { candle ->
            val open = candle.open.toDoubleOrNull() ?: return@mapNotNull null
            val high = candle.high.toDoubleOrNull() ?: return@mapNotNull null
            val low = candle.low.toDoubleOrNull() ?: return@mapNotNull null
            val close = candle.close.toDoubleOrNull() ?: return@mapNotNull null
            val volume = candle.volume.toDoubleOrNull() ?: return@mapNotNull null
            Values(open, high, low, close, volume)
        }
        val horizonBars = (outcomeMinutes / timeframeMinutes(timeframe)).coerceAtLeast(1)
        if (clean.size < 80 + horizonBars) {
            Log.w("TradeMentorAdvisor", "$symbol insufficient clean=${clean.size} required=${80 + horizonBars} raw=${candles.size}")
            return null
        }

        val latestIndex = clean.lastIndex
        val longRules = matchedRules(clean, latestIndex, false)
        val shortRules = matchedRules(clean, latestIndex, true)
        val longResult = evaluate(clean, longRules, false, horizonBars, profitPercentage, maxAdversePercentage, minimumSamples)
        val shortResult = evaluate(clean, shortRules, true, horizonBars, profitPercentage, maxAdversePercentage, minimumSamples)
        val best = when (forcedShortDirection) {
            true -> shortResult
            false -> longResult
            null -> listOfNotNull(longResult, shortResult).maxByOrNull { it.first }
        } ?: return null
        return AdvisorRecommendation(
            symbol = symbol,
            shortDirection = best.third,
            price = price.takeIf { it > 0.0 } ?: clean.last().close,
            analysisTimeframe = timeframe,
            winRate = best.first,
            sampleCount = best.second,
            indicators = best.fourth,
            targetPrice = if (best.third) {
                (price.takeIf { it > 0.0 } ?: clean.last().close) * (1.0 - profitPercentage / 100.0)
            } else {
                (price.takeIf { it > 0.0 } ?: clean.last().close) * (1.0 + profitPercentage / 100.0)
            },
            tradeType = tradeType(outcomeMinutes),
            expectedDuration = expectedDuration(outcomeMinutes),
            confidence = when {
                best.second >= 35 -> "Hoog"
                best.second >= 20 -> "Gemiddeld"
                else -> "Beperkt"
            },
            maxAdversePercentage = maxAdversePercentage,
            qualityScore = qualityScore(
                winRate = best.first,
                profit = profitPercentage,
                risk = maxAdversePercentage,
                sampleCount = best.second,
                indicatorCount = best.fourth.size,
                candles = clean
            ),
            riskLabel = riskLabel(best.first, profitPercentage, maxAdversePercentage)
        )
    }

    private fun evaluate(
        candles: List<Values>,
        rules: List<String>,
        shortDirection: Boolean,
        horizonBars: Int,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        minimumSamples: Int
    ): Result? {
        val latestFeatures = situationFeatures(candles, candles.lastIndex) ?: return null
        val rankedCandidates = (55 until candles.size - horizonBars).mapNotNull { index ->
            val historicalRules = matchedRules(candles, index, shortDirection)
            val historicalFeatures = situationFeatures(candles, index) ?: return@mapNotNull null
            val ruleMismatch = (rules.toSet() union historicalRules.toSet()).count { rule ->
                (rule in rules) != (rule in historicalRules)
            }
            val featureDistance = latestFeatures.indices.sumOf { feature ->
                kotlin.math.abs(latestFeatures[feature] - historicalFeatures[feature])
            }
            index to (ruleMismatch * 10.0 + featureDistance)
        }.sortedBy { it.second }
        val matchingIndices = mutableListOf<Int>()
        val minimumSpacing = (horizonBars / 8).coerceAtLeast(1)
        rankedCandidates.forEach { candidate ->
            if (matchingIndices.size < minimumSamples && matchingIndices.none { kotlin.math.abs(it - candidate.first) < minimumSpacing }) {
                matchingIndices += candidate.first
            }
        }
        if (matchingIndices.isEmpty()) return null
        val evaluatedIndices = matchingIndices.sorted()
        var successes = 0
        evaluatedIndices.forEach { index ->
            val entry = candles[index].close
            val target = if (shortDirection) entry * (1.0 - profitPercentage / 100.0) else entry * (1.0 + profitPercentage / 100.0)
            val stop = if (shortDirection) {
                entry * (1.0 + maxAdversePercentage / 100.0)
            } else {
                entry * (1.0 - maxAdversePercentage / 100.0)
            }
            val outcomeWindow = candles.subList(index + 1, index + horizonBars + 1)
            var succeeded = false
            for (candle in outcomeWindow) {
                val stopped = if (shortDirection) candle.high >= stop else candle.low <= stop
                if (stopped) break
                val targetHit = if (shortDirection) candle.low <= target else candle.high >= target
                if (targetHit) {
                    succeeded = true
                    break
                }
            }
            if (succeeded) successes++
        }
        // Bayesian smoothing prevents tiny samples from producing misleading 0%/100%
        // scores while still ensuring every market with usable history gets a score.
        val smoothedWinRate = (successes + 2.0) * 100.0 / (evaluatedIndices.size + 4.0)
        val explanation = rules.ifEmpty { listOf("Prijsstructuur", "Momentum", "Volatiliteit") }
        return Result(smoothedWinRate, evaluatedIndices.size, shortDirection, explanation)
    }

    private fun situationFeatures(candles: List<Values>, index: Int): DoubleArray? {
        if (index < 20) return null
        val window = candles.subList(index - 19, index + 1)
        val closes = window.map { it.close }
        val price = closes.last().takeIf { it > 0.0 } ?: return null
        val mean = closes.average().coerceAtLeast(1e-12)
        val returns = closes.zipWithNext { first, second -> (second - first) / first.coerceAtLeast(1e-12) }
        val volatility = sqrt(returns.sumOf { it * it } / returns.size)
        val averageVolume = window.dropLast(1).map { it.volume }.average().coerceAtLeast(1e-12)
        return doubleArrayOf(
            ((price - closes[18]) / closes[18].coerceAtLeast(1e-12)) * 100.0,
            ((price - closes[14]) / closes[14].coerceAtLeast(1e-12)) * 100.0,
            ((price - mean) / mean) * 100.0,
            volatility * 100.0,
            ((window.last().high - window.last().low) / price) * 100.0,
            (window.last().volume / averageVolume).coerceAtMost(10.0)
        )
    }

    private fun matchedRules(candles: List<Values>, index: Int, shortDirection: Boolean): List<String> {
        if (index < 55) return emptyList()
        // A bounded lookback keeps this calculation linear and avoids blocking the UI.
        // Two hundred candles are ample for EMA50 while preserving recent market context.
        val start = (index - 199).coerceAtLeast(0)
        val window = candles.subList(start, index + 1)
        val closes = window.map { it.close }
        val volumes = window.map { it.volume }
        val current = closes.last()
        val last20 = closes.takeLast(20)
        val mean = last20.average()
        val deviation = sqrt(last20.sumOf { (it - mean).pow(2) } / 20)
        val upper = mean + 2 * deviation
        val lower = mean - 2 * deviation
        val ema20 = ema(closes, 20)
        val ema50 = ema(closes, 50)
        val rsi = rsi(closes, 14)
        val averageVolume = volumes.dropLast(1).takeLast(20).average()
        val rules = mutableListOf<String>()
        if (shortDirection) {
            if (current > upper) rules += "Boven bovenste BB"
            if (rsi >= 65) rules += "RSI hoog"
            if (current < ema20) rules += "Onder EMA20"
            if (ema20 < ema50) rules += "Bearish EMA-trend"
            if (current < closes[closes.lastIndex - 10]) rules += "Negatief momentum"
        } else {
            if (current < lower) rules += "Onder onderste BB"
            if (rsi <= 35) rules += "RSI laag"
            if (current > ema20) rules += "Boven EMA20"
            if (ema20 > ema50) rules += "Bullish EMA-trend"
            if (current > closes[closes.lastIndex - 10]) rules += "Positief momentum"
        }
        if (averageVolume > 0.0 && volumes.last() >= averageVolume * 1.5) rules += "Volume spike"
        return rules
    }

    private fun ema(values: List<Double>, period: Int): Double {
        val multiplier = 2.0 / (period + 1.0)
        var result = values.first()
        values.forEachIndexed { index, value -> if (index > 0) result = (value - result) * multiplier + result }
        return result
    }

    private fun rsi(values: List<Double>, period: Int): Double {
        val changes = values.zipWithNext { first, second -> second - first }.takeLast(period)
        val gain = changes.filter { it > 0 }.sum() / period
        val loss = -changes.filter { it < 0 }.sum() / period
        if (loss == 0.0) return 100.0
        return 100.0 - 100.0 / (1.0 + gain / loss)
    }

    private fun timeframeMinutes(timeframe: String) = when (timeframe) {
        "1m" -> 1
        "3m" -> 3
        "5m" -> 5
        "15m" -> 15
        "30m" -> 30
        "1h" -> 60
        "2h" -> 120
        "4h" -> 240
        "8h" -> 480
        "12h" -> 720
        "1d" -> 1_440
        "3d" -> 4_320
        "1w" -> 10_080
        else -> 60
    }

    private fun baseAnalysisTimeframe(outcomeMinutes: Int) = when {
        outcomeMinutes <= 15 -> "1m"
        outcomeMinutes <= 60 -> "5m"
        outcomeMinutes <= 24 * 60 -> "15m"
        else -> "2h"
    }

    private fun tradeType(outcomeMinutes: Int) = when {
        outcomeMinutes <= 30 -> "Snelle trade"
        outcomeMinutes <= 4 * 60 -> "Korte trade"
        outcomeMinutes <= 24 * 60 -> "Intradaytrade"
        else -> "Swing trade"
    }

    private fun expectedDuration(outcomeMinutes: Int) = when {
        outcomeMinutes <= 30 -> "10–30 minuten"
        outcomeMinutes <= 4 * 60 -> "30 minuten–4 uur"
        outcomeMinutes <= 24 * 60 -> "4–24 uur"
        else -> "1–7 dagen"
    }

    private fun qualityScore(
        winRate: Double,
        profit: Double,
        risk: Double,
        sampleCount: Int,
        indicatorCount: Int,
        candles: List<Values>
    ): Double {
        val breakEven = risk / (profit + risk).coerceAtLeast(0.01) * 100.0
        val riskAdjusted = (50.0 + winRate - breakEven).coerceIn(0.0, 100.0)
        val chancePoints = winRate.coerceIn(0.0, 100.0) * 0.35
        val riskPoints = riskAdjusted * 0.25
        val reliabilityPoints = (sampleCount / 50.0).coerceIn(0.0, 1.0) * 15.0
        val confirmationPoints = (indicatorCount / 4.0).coerceIn(0.0, 1.0) * 15.0
        val recent = candles.takeLast(60)
        val positiveVolumeRatio = recent.count { it.volume > 0.0 } / recent.size.coerceAtLeast(1).toDouble()
        val averageRange = recent.map { (it.high - it.low) / it.close.coerceAtLeast(1e-12) * 100.0 }.average().takeUnless { it.isNaN() } ?: 0.0
        val volatilityQuality = when {
            averageRange in 0.15..5.0 -> 1.0
            averageRange in 0.05..8.0 -> 0.65
            else -> 0.25
        }
        val marketPoints = ((positiveVolumeRatio + volatilityQuality) / 2.0) * 10.0
        return (chancePoints + riskPoints + reliabilityPoints + confirmationPoints + marketPoints).coerceIn(0.0, 100.0)
    }

    private fun riskLabel(winRate: Double, profit: Double, risk: Double): String {
        val breakEven = risk / (profit + risk).coerceAtLeast(0.01) * 100.0
        return when {
            winRate >= breakEven + 8.0 -> "Sterk"
            winRate > breakEven -> "Voorzichtig"
            else -> "Ongunstig risico"
        }
    }

    private data class Values(val open: Double, val high: Double, val low: Double, val close: Double, val volume: Double)
    private data class Result(val first: Double, val second: Int, val third: Boolean, val fourth: List<String>)
    private data class AnalysisPlan(val timeframe: String, val outcomeMinutes: Int)
}
