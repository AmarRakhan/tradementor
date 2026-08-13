package com.tradementor.app.api

import com.google.gson.annotations.SerializedName

data class MetaRequest(
    @SerializedName("type")
    val type: String = "metaAndAssetCtxs"
)

data class MetaResponse(
    @SerializedName("universe")
    val universe: List<Market>
)

data class Market(
    @SerializedName("name")
    val name: String,

    @SerializedName("maxLeverage")
    val maxLeverage: Int,

    @SerializedName("szDecimals")
    val sizeDecimals: Int,

    @SerializedName("isDelisted")
    val isDelisted: Boolean = false
)

data class AllMidsRequest(
    @SerializedName("type")
    val type: String = "allMids"
)

data class AssetContext(
    @SerializedName("markPx")
    val markPrice: String,

    @SerializedName("prevDayPx")
    val previousDayPrice: String,

    @SerializedName("dayNtlVlm")
    val dayNotionalVolume: String,

    @SerializedName("funding")
    val funding: String,

    @SerializedName("openInterest")
    val openInterest: String
)

data class PerpetualMarket(
    val market: Market,
    val context: AssetContext
) {
    val changePercentage: Double
        get() {
            val current = context.markPrice.toDoubleOrNull() ?: return 0.0
            val previous = context.previousDayPrice.toDoubleOrNull() ?: return 0.0
            return if (previous == 0.0) 0.0 else ((current - previous) / previous) * 100.0
        }
}

data class CandleSnapshotRequest(
    @SerializedName("type")
    val type: String = "candleSnapshot",

    @SerializedName("req")
    val request: CandleRequest
)

data class CandleRequest(
    @SerializedName("coin")
    val coin: String,

    @SerializedName("interval")
    val interval: String,

    @SerializedName("startTime")
    val startTime: Long,

    @SerializedName("endTime")
    val endTime: Long
)

data class Candle(
    @SerializedName("t")
    val openTime: Long,

    @SerializedName("T")
    val closeTime: Long,

    @SerializedName("c")
    val close: String,

    @SerializedName("o")
    val open: String,

    @SerializedName("h")
    val high: String,

    @SerializedName("l")
    val low: String,

    @SerializedName("v")
    val volume: String
)

data class ClearinghouseStateRequest(
    @SerializedName("user") val user: String,
    @SerializedName("type") val type: String = "clearinghouseState",
    @SerializedName("dex") val dex: String = ""
)

data class UserInfoRequest(
    @SerializedName("type") val type: String,
    @SerializedName("user") val user: String
)

data class InfoTypeRequest(
    @SerializedName("type") val type: String
)

data class HyperliquidSpotState(
    @SerializedName("balances") val balances: List<HyperliquidSpotBalance> = emptyList()
)

data class HyperliquidSpotBalance(
    @SerializedName("coin") val coin: String = "",
    @SerializedName("token") val token: Int = -1,
    @SerializedName("total") val total: String = "0",
    @SerializedName("hold") val hold: String = "0",
    @SerializedName("entryNtl") val entryNotional: String = "0"
)

data class HyperliquidAccountState(
    @SerializedName("marginSummary") val marginSummary: HyperliquidMarginSummary = HyperliquidMarginSummary(),
    @SerializedName("crossMarginSummary") val crossMarginSummary: HyperliquidMarginSummary = HyperliquidMarginSummary(),
    @SerializedName("withdrawable") val withdrawable: String = "0",
    @SerializedName("crossMaintenanceMarginUsed") val crossMaintenanceMarginUsed: String = "0",
    @SerializedName("assetPositions") val assetPositions: List<HyperliquidAssetPosition> = emptyList()
)

data class HyperliquidMarginSummary(
    @SerializedName("accountValue") val accountValue: String = "0",
    @SerializedName("totalNtlPos") val totalNotionalPosition: String = "0",
    @SerializedName("totalRawUsd") val totalRawUsd: String = "0",
    @SerializedName("totalMarginUsed") val totalMarginUsed: String = "0"
)

data class HyperliquidAssetPosition(
    @SerializedName("type") val type: String = "oneWay",
    @SerializedName("position") val position: HyperliquidPosition = HyperliquidPosition()
)

data class HyperliquidPosition(
    @SerializedName("coin") val coin: String = "",
    @SerializedName("szi") val signedSize: String = "0",
    @SerializedName("entryPx") val entryPrice: String? = null,
    @SerializedName("positionValue") val positionValue: String = "0",
    @SerializedName("unrealizedPnl") val unrealizedPnl: String = "0",
    @SerializedName("returnOnEquity") val returnOnEquity: String = "0",
    @SerializedName("liquidationPx") val liquidationPrice: String? = null,
    @SerializedName("marginUsed") val marginUsed: String = "0",
    @SerializedName("leverage") val leverage: HyperliquidLeverage = HyperliquidLeverage()
)

data class HyperliquidLeverage(
    @SerializedName("type") val type: String = "cross",
    @SerializedName("value") val value: Int = 1,
    @SerializedName("rawUsd") val rawUsd: String? = null
)

data class HyperliquidOpenOrder(
    @SerializedName("coin") val coin: String = "",
    @SerializedName("side") val side: String = "",
    @SerializedName("limitPx") val limitPrice: String = "0",
    @SerializedName("sz") val size: String = "0",
    @SerializedName("oid") val orderId: Long = 0,
    @SerializedName("timestamp") val timestamp: Long = 0
)

data class HyperliquidFill(
    @SerializedName("coin") val coin: String = "",
    @SerializedName("side") val side: String = "",
    @SerializedName("px") val price: String = "0",
    @SerializedName("sz") val size: String = "0",
    @SerializedName("closedPnl") val closedPnl: String = "0",
    @SerializedName("dir") val direction: String = "",
    @SerializedName("startPosition") val startPosition: String = "0",
    @SerializedName("fee") val fee: String = "0",
    @SerializedName("time") val time: Long = 0,
    @SerializedName("tid") val tradeId: Long = 0
)

enum class ScanRule(val title: String, val shortRule: Boolean) {
    BollingerAbove("Prijs boven upper Bollinger Band", true),
    BollingerBelow("Prijs onder lower Bollinger Band", false),
    RsiOverbought("RSI boven 70", true),
    RsiOversold("RSI onder 30", false),
    EmaBearish("Prijs onder EMA 20", true),
    EmaBullish("Prijs boven EMA 20", false),
    MacdBearish("MACD bearish", true),
    MacdBullish("MACD bullish", false),
    VolumeSpike("Volume spike boven 2× gemiddeld", false),
    BreakoutHigh("Breakout boven 20-candle high", false),
    BreakdownLow("Breakdown onder 20-candle low", true)
}

data class MultiIndicatorSignal(
    val symbol: String,
    val price: Double,
    val matchedRules: List<ScanRule>,
    val candleCloseTime: Long
)

enum class ScanMetric(val title: String, val unit: String = "") {
    Rsi("RSI", ""),
    DayVolumeUsd("24u-volume", "USD"),
    PriceChange24h("24u-koersverandering", "%"),
    FundingRate("Funding rate", "%"),
    OpenInterest("Open interest", ""),
    Price("Prijs", "USD"),
    BollingerUpperDistance("Bollinger Bands · prijs t.o.v. bovenste band", "%"),
    BollingerLowerDistance("Bollinger Bands · prijs t.o.v. onderste band", "%"),
    Ema20Distance("Afstand tot EMA 20", "%"),
    Ema50Distance("Afstand tot EMA 50", "%"),
    Sma20Distance("Afstand tot SMA 20", "%"),
    Sma50Distance("Afstand tot SMA 50", "%"),
    MacdPercent("MACD", "%"),
    VolumeRatio("Volume t.o.v. gemiddelde", "×"),
    Roc14("ROC 14", "%"),
    Stochastic14("Stochastic 14", ""),
    AtrPercent("ATR 14", "%"),
    CandleChange("Candleverandering", "%"),
    CandleVolume("Candlevolume", ""),
    BreakoutHigh20("Afstand tot 20-candle high", "%"),
    BreakdownLow20("Afstand tot 20-candle low", "%"),
    Volatility20("Volatiliteit 20", "%"),
    Momentum10("Momentum 10", "%"),
    WilliamsR("Williams %R", ""),
    Cci20("CCI 20", "")
}

enum class ScanOperator(val symbol: String, val words: String) {
    LessThan("<", "lager dan"),
    LessOrEqual("≤", "lager dan of gelijk aan"),
    GreaterThan(">", "hoger dan"),
    GreaterOrEqual("≥", "hoger dan of gelijk aan")
}

data class ScanCondition(
    val id: Long,
    val metric: ScanMetric,
    val operator: ScanOperator,
    val threshold: Double,
    val label: String,
    val interval: String = "4h"
)

data class CustomScanSignal(
    val symbol: String,
    val price: Double,
    val matchedConditionIds: List<Long>,
    val candleCloseTime: Long
)

data class TimeframeWinRate(
    val timeframe: String,
    val percentage: Double,
    val sampleCount: Int
)

data class RecommendedTrade(
    val symbol: String,
    val timeframe: String,
    val winRate: Double
)

data class AdvisorRecommendation(
    val symbol: String,
    val shortDirection: Boolean,
    val price: Double,
    val analysisTimeframe: String,
    val winRate: Double,
    val sampleCount: Int,
    val indicators: List<String>,
    val targetPrice: Double = 0.0,
    val tradeType: String = "Trade",
    val expectedDuration: String = "Onbekend",
    val confidence: String = "Beperkt",
    val maxAdversePercentage: Double = 1.0,
    val qualityScore: Double = 0.0,
    val riskLabel: String = "Voorzichtig"
)

enum class BollingerPosition {
    AboveUpper,
    BelowLower
}

data class BollingerSignal(
    val symbol: String,
    val price: Double,
    val middleBand: Double,
    val upperBand: Double,
    val lowerBand: Double,
    val distancePercentage: Double,
    val position: BollingerPosition,
    val candleCloseTime: Long
)
