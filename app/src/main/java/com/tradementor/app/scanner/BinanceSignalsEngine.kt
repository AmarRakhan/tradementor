package com.tradementor.app.scanner

import com.tradementor.app.api.AdvisorRecommendation
import com.tradementor.app.api.CatalogMarket
import com.tradementor.app.repository.BinanceMarketRepository
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope

class BinanceSignalsEngine(
    private val candleRepository: BinanceMarketRepository,
    private val advisorEngine: AdvisorEngine
) {
    suspend fun analyze(
        markets: List<CatalogMarket>,
        analysisTimeframe: String,
        outcomeMinutes: Int,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        minimumWinRate: Double,
        allowLong: Boolean,
        allowShort: Boolean
    ): List<AdvisorRecommendation> = coroutineScope {
        val recommendations = mutableListOf<AdvisorRecommendation>()
        markets.filter { it.category.equals("Spot", true) }
            .sortedByDescending { it.usdVolume24h }
            .take(30)
            .chunked(6)
            .forEach { batch ->
                recommendations += batch.map { market ->
                    async {
                        runCatching {
                            advisorEngine.scoreCandleSeries(
                                symbol = market.baseSymbol,
                                price = market.usdPrice,
                                timeframe = analysisTimeframe,
                                candles = candleRepository.getCandles(market.pair, analysisTimeframe, 1_000),
                                profitPercentage = profitPercentage,
                                maxAdversePercentage = maxAdversePercentage,
                                minimumSamples = 50,
                                outcomeMinutes = outcomeMinutes,
                                allowLong = allowLong,
                                allowShort = allowShort
                            )
                        }.getOrNull()
                    }
                }.awaitAll().filterNotNull().filter { it.winRate >= minimumWinRate }
            }
        recommendations.sortedByDescending { it.winRate }
    }
}
