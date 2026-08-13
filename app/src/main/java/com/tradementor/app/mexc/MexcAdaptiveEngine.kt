package com.tradementor.app.mexc

import kotlin.math.abs
import kotlin.math.max

enum class MexcMode { PAPER, LIVE }
enum class MexcPhase { WAIT, LONG, DCA, HEDGE, PROTECT, RECOVERY, UNHEDGE, PROFIT, CLOSED, SAFETY_STOP }

data class MexcSettings(
    val strategyVersion: String = "adaptive_v2",
    val mode: MexcMode = MexcMode.PAPER,
    val paperEquity: Double = 400.0,
    val executionTimeframe: String = "3m",
    val riskTimeframe: String = "15m",
    val leverage: Int = MexcAdaptiveEngine.FIXED_LEVERAGE,
    val initialLongRatio: Double = 0.0625,
    val maxLongRatio: Double = 6.25,
    val dcaRatios: List<Double> = listOf(.075, .10, .125, .1875, .25, .375, .50),
    val minimumSpacing: Double = .005,
    val atrMultiplier: Double = .75,
    val cooldownSeconds: Long = 180,
    val takeProfit: Double = .005,
    val minimumNetProfit: Double = .002,
    val hedgeEnabled: Boolean = true,
    val hedgeDrawdownTrigger: Double = .075,
    val riskTrigger: Int = 80,
    val recoveryStep1: Int = 40,
    val recoveryStep2: Int = 55,
    val recoveryStep3: Int = 70,
    val recoveryStep4: Int = 85,
    val initialHedgeRatio: Double = .50,
    val maxHedgeRatio: Double = 1.0,
    val minimumEquityReserve: Double = .50,
    val maximumSessionDrawdown: Double = .20,
    val maximumMarginUsage: Double = .35,
    val maximumMarginRatio: Double = .60,
    val minimumLiquidationDistance: Double = .08,
    val takerFee: Double = .0006,
    val initialOrderNotional: Double = 70.0,
    val maximumDcaOrders: Int = 40,
    val dcaSpacing: Double = .005,
    val emergencyHedgeEnabled: Boolean = true,
    val emergencyEquityTrigger: Double = 95.0,
    val emergencyHedgeRatio: Double = 1.0,
    val rescueEnabled: Boolean = true,
    val rescueOrderNotional: Double = 10.0,
    val rescueTakeProfit: Double = .005,
    val maxFrozenCycles: Int = 1,
    val classicStopLoss: Boolean = false,
    val minimumAvailableBuffer: Double = 10.0,
)

data class MexcMarketPoint(
    val timeSeconds: Long,
    val price: Double,
    val atrPercent: Double,
    val lowerLow: Boolean,
    val riskScore: Int,
    val recoveryScore: Int
)

data class MexcSession(
    val startEquity: Double,
    val currentEquity: Double,
    val lowestEquity: Double,
    val phase: MexcPhase = MexcPhase.WAIT,
    val longNotional: Double = 0.0,
    val shortNotional: Double = 0.0,
    val hedgeEntry: Double = 0.0,
    val weightedEntry: Double = 0.0,
    val dcaCount: Int = 0,
    val lastDcaPrice: Double = 0.0,
    val lastOrderTime: Long = 0,
    val fees: Double = 0.0,
    val funding: Double = 0.0,
    val realizedPnl: Double = 0.0,
    val closed: Boolean = false,
    val reason: String = "Wachten op start"
) {
    val netExposure: Double get() = longNotional - shortNotional
    val hedgeRatio: Double get() = if (longNotional > 0) shortNotional / longNotional else 0.0
}

sealed interface MexcAction {
    data class OpenLong(val notional: Double) : MexcAction
    data class AddLong(val notional: Double, val index: Int) : MexcAction
    data class SetHedge(val targetNotional: Double) : MexcAction
    data object CloseSession : MexcAction
    data class SafetyStop(val reason: String) : MexcAction
    data class Blocked(val reason: String) : MexcAction
    data object Hold : MexcAction
}

object MexcAdaptiveEngine {
    const val FIXED_LEVERAGE = 200
    const val FIXED_MARGIN_MODE = "CROSS"
    val executionTimeframes = listOf("1m", "3m", "5m", "15m", "30m", "1h")
    val riskTimeframes = listOf("5m", "15m", "30m", "1h", "4h")

    fun validateV3(settings: MexcSettings): List<String> = buildList {
        if (settings.strategyVersion != "hedge_dca_v3") add("Onbekende MEXC-strategieversie")
        if (settings.initialOrderNotional <= 0) add("Initial order size moet positief zijn")
        if (settings.takeProfit !in 0.0001..0.10) add("Take-profit is ongeldig")
        if (settings.maximumDcaOrders !in 0..100) add("Maximum DCA is ongeldig")
        if (settings.dcaSpacing !in 0.0001..0.25) add("DCA spacing is ongeldig")
        if (settings.emergencyEquityTrigger <= 0) add("Emergency equity trigger is ongeldig")
        if (settings.emergencyHedgeRatio !in 0.01..1.0) add("Emergency hedge ratio is ongeldig")
        if (settings.rescueOrderNotional <= 0) add("Rescue order size is ongeldig")
        if (settings.rescueTakeProfit !in 0.0001..0.10) add("Rescue TP is ongeldig")
        if (settings.maxFrozenCycles !in 0..1) add("Max frozen cycles mag maximaal 1 zijn")
        if (settings.classicStopLoss) add("Test-3 gebruikt geen klassieke stop-loss")
    }

    fun validate(settings: MexcSettings): List<String> = buildList {
        if (settings.paperEquity < 10) add("Papervermogen moet minimaal 10 USDT zijn")
        if (settings.initialLongRatio !in .001..1.0) add("Eerste Long-ratio is ongeldig")
        if (settings.maxLongRatio < settings.initialLongRatio) add("Max Long moet boven de eerste order liggen")
        if (settings.initialHedgeRatio !in 0.0..settings.maxHedgeRatio) add("Initiële hedge is ongeldig")
        if (settings.maxHedgeRatio !in 0.0..1.0) add("Maximale hedge mag niet boven 100% liggen")
        if (settings.minimumEquityReserve !in .10..1.0) add("Equityreserve moet minimaal 10% zijn")
        if (settings.maximumSessionDrawdown !in .01..0.50) add("Nood-drawdown moet tussen 1% en 50% liggen")
        if (settings.maximumMarginRatio < .05 || settings.maximumMarginRatio >= 1.0) add("Maximale margin ratio moet tussen 5% en 100% liggen")
        if (settings.executionTimeframe !in executionTimeframes) add("Execution timeframe wordt niet ondersteund")
        if (settings.riskTimeframe !in riskTimeframes) add("Risk timeframe wordt niet ondersteund")
        if (listOf(settings.recoveryStep1,settings.recoveryStep2,settings.recoveryStep3,settings.recoveryStep4) != listOf(settings.recoveryStep1,settings.recoveryStep2,settings.recoveryStep3,settings.recoveryStep4).sorted()) add("Recovery-drempels moeten oplopen")
    }

    fun initialNotional(settings: MexcSettings, equity: Double) = equity * settings.initialLongRatio
    fun maximumLong(settings: MexcSettings, equity: Double) = equity * settings.maxLongRatio
    fun reserveLimitedLong(settings: MexcSettings, equity: Double): Double =
        equity * (1.0 - settings.minimumEquityReserve) * settings.leverage
    fun safeMaximumLong(settings: MexcSettings, equity: Double) =
        minOf(maximumLong(settings, equity), reserveLimitedLong(settings, equity))
    fun hedgeTriggerUsd(settings: MexcSettings, equity: Double) = equity * settings.hedgeDrawdownTrigger
    fun safeOrderNotional(requested: Double, exchangeMinimum: Double): Double? =
        requested.takeIf { it > 0.0 && it >= exchangeMinimum }

    fun fixedProfile(settings: MexcSettings): MexcSettings =
        if (settings.leverage == FIXED_LEVERAGE) settings else settings.copy(leverage = FIXED_LEVERAGE)

    /**
     * Conservative Cross-margin price buffer estimate. Cross uses the shared
     * session equity as collateral, so the isolated formula 1/leverage is not
     * applicable. A perfectly hedged book has no directional liquidation
     * distance; its maintenance burden is still monitored separately.
     */
    fun estimatedCrossLiquidationDistance(
        session: MexcSession,
        maintenanceRate: Double = .001,
        liquidationFeeRate: Double = .0004,
        projectedLongNotional: Double = session.longNotional,
        projectedShortNotional: Double = session.shortNotional,
    ): Double {
        val gross = projectedLongNotional + projectedShortNotional
        val net = abs(projectedLongNotional - projectedShortNotional)
        if (session.currentEquity <= 0.0) return 0.0
        if (net <= 0.0) return 1.0
        val maintenanceBurden = gross * (maintenanceRate + liquidationFeeRate)
        return ((session.currentEquity - maintenanceBurden) / net).coerceIn(0.0, 1.0)
    }

    fun estimatedCrossMarginRatio(
        session: MexcSession,
        maintenanceRate: Double = .001,
        liquidationFeeRate: Double = .0004,
    ): Double = if (session.currentEquity > 0.0) {
        ((session.longNotional + session.shortNotional) * (maintenanceRate + liquidationFeeRate) / session.currentEquity).coerceIn(0.0, 1.0)
    } else 1.0

    fun estimatedMarginUsage(settings: MexcSettings, session: MexcSession): Double =
        if (session.currentEquity > 0.0) (session.longNotional + session.shortNotional) / settings.leverage.coerceAtLeast(1) / session.currentEquity else 1.0

    fun decide(settings: MexcSettings, session: MexcSession, market: MexcMarketPoint, liquidationDistance: Double? = null, marginUsage: Double? = null, exchangeMinimumNotional: Double = 0.0): MexcAction {
        if (session.closed) return MexcAction.Hold
        val effectiveLiquidationDistance = liquidationDistance ?: estimatedCrossLiquidationDistance(
            session,
            projectedLongNotional = if (session.longNotional == 0.0) initialNotional(settings, session.startEquity) else session.longNotional,
        )
        val effectiveMarginUsage = marginUsage ?: estimatedMarginUsage(settings, session)
        val drawdown = ((session.startEquity - session.currentEquity) / session.startEquity).coerceAtLeast(0.0)
        if (session.longNotional == 0.0) {
            if (effectiveLiquidationDistance < settings.minimumLiquidationDistance) return MexcAction.Blocked("Cross-buffer voldoet niet aan minimale liquidatieafstand")
            val requested=initialNotional(settings,session.startEquity)
            val projectedMarginUsage = requested / settings.leverage.coerceAtLeast(1) / session.currentEquity.coerceAtLeast(0.01)
            if (projectedMarginUsage > settings.maximumMarginUsage) return MexcAction.Blocked("Eerste order overschrijdt maximale marginbelasting")
            return safeOrderNotional(requested,exchangeMinimumNotional)?.let{MexcAction.OpenLong(it)} ?: MexcAction.Blocked("ORDER BELOW EXCHANGE MINIMUM")
        }
        if (drawdown >= settings.maximumSessionDrawdown) return MexcAction.SafetyStop("Maximale sessiedrawdown bereikt")
        if (effectiveLiquidationDistance < settings.minimumLiquidationDistance) return MexcAction.SafetyStop("Liquidatieafstand te klein")
        if (effectiveMarginUsage > settings.maximumMarginUsage) return MexcAction.SafetyStop("Maximale marginbelasting bereikt")

        val longPnl = (market.price / session.weightedEntry - 1.0) * session.longNotional
        val shortPnl = if (session.shortNotional > 0 && session.hedgeEntry > 0) -(market.price / session.hedgeEntry - 1.0) * session.shortNotional else 0.0
        val netPnl = longPnl + shortPnl + session.realizedPnl - session.fees - session.funding
        val target = session.weightedEntry * (1 + settings.takeProfit)
        if (market.price >= target && netPnl >= session.startEquity * settings.minimumNetProfit) return MexcAction.CloseSession

        val shouldHedge = settings.hedgeEnabled && (drawdown >= settings.hedgeDrawdownTrigger || market.riskScore >= settings.riskTrigger)
        if (shouldHedge) return MexcAction.SetHedge(session.longNotional * settings.initialHedgeRatio.coerceAtMost(settings.maxHedgeRatio))
        if (session.shortNotional > 0) {
            val targetRatio = when {
                market.recoveryScore >= settings.recoveryStep4 -> 0.0
                market.recoveryScore >= settings.recoveryStep3 -> .125
                market.recoveryScore >= settings.recoveryStep2 -> .25
                market.recoveryScore >= settings.recoveryStep1 -> .375
                else -> settings.initialHedgeRatio
            }
            return MexcAction.SetHedge(session.longNotional * targetRatio.coerceAtMost(settings.maxHedgeRatio))
        }

        val spacing = max(settings.minimumSpacing, market.atrPercent * settings.atrMultiplier)
        val cooledDown = market.timeSeconds - session.lastOrderTime >= settings.cooldownSeconds
        val fellEnough = session.lastDcaPrice > 0 && market.price <= session.lastDcaPrice * (1 - spacing)
        if (market.lowerLow && cooledDown && fellEnough && session.dcaCount < settings.dcaRatios.size) {
            val requested = session.startEquity * settings.dcaRatios[session.dcaCount]
            val allowed = (safeMaximumLong(settings, session.startEquity) - session.longNotional).coerceAtLeast(0.0)
            val order=minOf(requested,allowed)
            if (allowed > 0) return safeOrderNotional(order,exchangeMinimumNotional)?.let{MexcAction.AddLong(it,session.dcaCount+1)} ?: MexcAction.Blocked("ORDER BELOW EXCHANGE MINIMUM")
        }
        return MexcAction.Hold
    }

    fun executePaper(settings: MexcSettings, session: MexcSession, market: MexcMarketPoint, action: MexcAction): MexcSession {
        fun fee(notional: Double) = abs(notional) * settings.takerFee
        return when (action) {
            is MexcAction.OpenLong -> session.copy(phase=MexcPhase.LONG,longNotional=action.notional,weightedEntry=market.price,lastDcaPrice=market.price,lastOrderTime=market.timeSeconds,fees=session.fees+fee(action.notional),reason="Eerste Long geopend")
            is MexcAction.AddLong -> { val total=session.longNotional+action.notional; session.copy(phase=MexcPhase.DCA,longNotional=total,weightedEntry=(session.weightedEntry*session.longNotional+market.price*action.notional)/total,dcaCount=action.index,lastDcaPrice=market.price,lastOrderTime=market.timeSeconds,fees=session.fees+fee(action.notional),reason="DCA ${action.index} uitgevoerd") }
            is MexcAction.SetHedge -> {
                val delta = action.targetNotional - session.shortNotional
                val nextEntry = when {
                    action.targetNotional <= 0.0 -> 0.0
                    delta > 0.0 && session.shortNotional > 0.0 ->
                        (session.hedgeEntry * session.shortNotional + market.price * delta) / action.targetNotional
                    delta > 0.0 -> market.price
                    else -> session.hedgeEntry
                }
                session.copy(
                    phase = if (action.targetNotional > 0) MexcPhase.PROTECT else MexcPhase.UNHEDGE,
                    shortNotional = action.targetNotional,
                    hedgeEntry = nextEntry,
                    fees = session.fees + fee(delta),
                    lastOrderTime = market.timeSeconds,
                    reason = if (action.targetNotional > 0) "Bescherming actief" else "Hedge afgebouwd"
                )
            }
            MexcAction.CloseSession -> closePaper(settings,session,market,"Netto take-profit bereikt")
            is MexcAction.SafetyStop -> closePaper(settings,session,market,action.reason).copy(phase=MexcPhase.SAFETY_STOP)
            is MexcAction.Blocked -> session.copy(reason=action.reason)
            MexcAction.Hold -> markToMarket(session,market)
        }
    }

    private fun markToMarket(session:MexcSession, market:MexcMarketPoint):MexcSession {
        if(session.longNotional<=0) return session
        val longPnl=(market.price/session.weightedEntry-1)*session.longNotional
        val shortPnl=if(session.shortNotional>0 && session.hedgeEntry>0) -(market.price/session.hedgeEntry-1)*session.shortNotional else 0.0
        val equity=session.startEquity+longPnl+shortPnl-session.fees-session.funding
        return session.copy(currentEquity=equity,lowestEquity=minOf(session.lowestEquity,equity))
    }

    private fun closePaper(settings:MexcSettings,session:MexcSession,market:MexcMarketPoint,reason:String):MexcSession {
        val marked=markToMarket(session,market); val closingFee=(session.longNotional+session.shortNotional)*settings.takerFee
        return marked.copy(currentEquity=marked.currentEquity-closingFee,lowestEquity=minOf(marked.lowestEquity,marked.currentEquity-closingFee),longNotional=0.0,shortNotional=0.0,hedgeEntry=0.0,fees=marked.fees+closingFee,phase=MexcPhase.CLOSED,closed=true,reason=reason)
    }
}
