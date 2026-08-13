package com.tradementor.app.mexc

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class MexcAdaptiveEngineTest {
    private val settings = MexcSettings(paperEquity = 400.0, takerFee = 0.0006)

    @Test fun `1 ratios and reserve cap scale from session equity`() {
        assertEquals(25.0, MexcAdaptiveEngine.initialNotional(settings, 400.0), 0.0001)
        assertEquals(2_500.0, MexcAdaptiveEngine.maximumLong(settings, 400.0), 0.0001)
        assertEquals(2_500.0, MexcAdaptiveEngine.safeMaximumLong(settings, 400.0), 0.0001)
        val reserveLimited = settings.copy(leverage = 2, minimumEquityReserve = 0.5)
        assertEquals(400.0, MexcAdaptiveEngine.safeMaximumLong(reserveLimited, 400.0), 0.0001)
        assertTrue(MexcAdaptiveEngine.validate(settings.copy(executionTimeframe="1m",riskTimeframe="5m")).isEmpty())
        assertTrue(MexcAdaptiveEngine.validate(settings.copy(executionTimeframe="5m",riskTimeframe="30m")).isEmpty())
        assertTrue(MexcAdaptiveEngine.validate(settings.copy(executionTimeframe="15m",riskTimeframe="1h")).isEmpty())
        assertTrue(MexcAdaptiveEngine.validate(settings.copy(executionTimeframe="2m")).isNotEmpty())
    }

    @Test fun `2 DCA requires spacing lower low cooldown and respects cap`() {
        val base = MexcSession(400.0, 400.0, 400.0, longNotional = 25.0, weightedEntry = 100.0, lastDcaPrice = 100.0, lastOrderTime = 100)
        val tooSoon = point(time = 200, price = 98.0, lowerLow = true)
        assertTrue(MexcAdaptiveEngine.decide(settings, base, tooSoon) is MexcAction.Hold)
        val ready = point(time = 400, price = 98.0, lowerLow = true)
        val action = MexcAdaptiveEngine.decide(settings, base, ready)
        assertTrue(action is MexcAction.AddLong)
        assertEquals(30.0, (action as MexcAction.AddLong).notional, 0.0001)
        val capped = base.copy(longNotional = MexcAdaptiveEngine.safeMaximumLong(settings, 400.0))
        assertTrue(MexcAdaptiveEngine.decide(settings, capped, ready) is MexcAction.Hold)
    }

    @Test fun `3 hedge keeps its own entry and unwinds during recovery`() {
        val base = MexcSession(400.0, 360.0, 360.0, longNotional = 100.0, weightedEntry = 100.0, lastDcaPrice = 95.0)
        val protect = MexcAdaptiveEngine.decide(settings, base, point(time = 500, price = 90.0, risk = 90))
        assertTrue(protect is MexcAction.SetHedge)
        val hedged = MexcAdaptiveEngine.executePaper(settings, base, point(time = 500, price = 90.0, risk = 90), protect)
        assertEquals(50.0, hedged.shortNotional, 0.0001)
        assertEquals(90.0, hedged.hedgeEntry, 0.0001)
        val recover = MexcAdaptiveEngine.decide(settings, hedged.copy(currentEquity = 390.0), point(time = 900, price = 96.0, recovery = 85))
        assertEquals(0.0, (recover as MexcAction.SetHedge).targetNotional, 0.0001)
    }

    @Test fun `4 safety engine stops on drawdown liquidation distance and margin`() {
        val base = MexcSession(400.0, 300.0, 300.0, longNotional = 25.0, weightedEntry = 100.0, lastDcaPrice = 100.0)
        assertTrue(MexcAdaptiveEngine.decide(settings, base, point()) is MexcAction.SafetyStop)
        val healthy = base.copy(currentEquity = 395.0)
        assertTrue(MexcAdaptiveEngine.decide(settings, healthy, point(), liquidationDistance = .05) is MexcAction.SafetyStop)
        assertTrue(MexcAdaptiveEngine.decide(settings, healthy, point(), marginUsage = .50) is MexcAction.SafetyStop)
    }

    @Test fun `5 deterministic end to end backtest stays bounded and never enlarges tiny orders`() {
        val candles = (0 until 600).map { i ->
            val wave = when {
                i % 120 < 55 -> 100.0 - (i % 120) * .18
                else -> 90.1 + ((i % 120) - 55) * .22
            }
            MexcCandle(i * 180L, wave, wave * 1.002, wave * .998, wave, 1_000.0)
        }
        val result = MexcBacktester.run(settings, candles)
        assertEquals(400.0, result.startEquity, 0.0001)
        assertTrue(result.endEquity.isFinite())
        assertTrue(result.maxDrawdownPercent in 0.0..100.0)
        assertTrue(result.maxExposure <= MexcAdaptiveEngine.safeMaximumLong(settings, settings.paperEquity) + 0.001)
        assertNull(MexcAdaptiveEngine.safeOrderNotional(4.99, 5.0))
        assertEquals(5.0, MexcAdaptiveEngine.safeOrderNotional(5.0, 5.0)!!, 0.0001)
        val signal = MexcSignalCalculator.point(candles.takeLast(20), candles.filterIndexed { index, _ -> index % 5 == 0 }.takeLast(20))
        assertTrue(signal.atrPercent >= 0.0)
        assertTrue(signal.riskScore in 0..100)
    }

    @Test fun `6 cross 200 uses shared equity buffer instead of isolated leverage distance`() {
        val leveraged = MexcAdaptiveEngine.fixedProfile(settings.copy(leverage = 1, minimumLiquidationDistance = .08))
        assertEquals(200, leveraged.leverage)
        val empty = MexcSession(125.20, 125.20, 125.20)
        val firstOrder = MexcAdaptiveEngine.initialNotional(leveraged, empty.startEquity)
        val distance = MexcAdaptiveEngine.estimatedCrossLiquidationDistance(
            empty, .001, .0004, projectedLongNotional = firstOrder,
        )
        assertEquals(1.0, distance, 0.000001)
        val action = MexcAdaptiveEngine.decide(
            leveraged, empty, point(), liquidationDistance = distance,
            marginUsage = MexcAdaptiveEngine.estimatedMarginUsage(leveraged, empty),
            exchangeMinimumNotional = 6.49,
        )
        assertTrue(action is MexcAction.OpenLong)
        val candles = (0 until 120).map { i -> MexcCandle(i * 60L, 100.0, 101.0, 99.0, 100.0, 1_000.0) }
        val result = MexcBacktester.run(leveraged, candles, maintenanceMarginRate=.001, liquidationFeeRate=.0004)
        assertTrue(result.estimatedLiquidationDistancePercent >= 8.0)
        assertTrue(result.peakMarginUsagePercent < 1.0)
    }

    @Test fun `7 cross risk increases with gross exposure while a balanced hedge reduces direction risk`() {
        val naked = MexcSession(125.0, 125.0, 125.0, longNotional = 500.0)
        val hedged = naked.copy(shortNotional = 500.0)
        assertTrue(MexcAdaptiveEngine.estimatedCrossMarginRatio(hedged) > MexcAdaptiveEngine.estimatedCrossMarginRatio(naked))
        assertTrue(MexcAdaptiveEngine.estimatedCrossLiquidationDistance(naked) < 1.0)
        assertEquals(1.0, MexcAdaptiveEngine.estimatedCrossLiquidationDistance(hedged), 0.000001)
    }

    private fun point(
        time: Long = 1_000,
        price: Double = 100.0,
        lowerLow: Boolean = false,
        risk: Int = 10,
        recovery: Int = 10
    ) = MexcMarketPoint(time, price, .01, lowerLow, risk, recovery)
}
