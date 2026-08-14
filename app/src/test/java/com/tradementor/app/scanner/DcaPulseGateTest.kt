package com.tradementor.app.scanner

import com.tradementor.app.api.HyperliquidFill
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class DcaPulseGateTest {
    @Test
    fun asterUniverseGateNormalizesHyperliquidSymbols() {
        val allowed = setOf("BTCUSDT", "ETHUSDT", "SOLUSDT", "1000PEPEUSDT")
        assertTrue(DcaPulseGate.isAllowedUniverseSymbol("BTC", allowed))
        assertTrue(DcaPulseGate.isAllowedUniverseSymbol("xyz:SOL", allowed))
        assertTrue(DcaPulseGate.isAllowedUniverseSymbol("kBTC", allowed))
        assertTrue(DcaPulseGate.isAllowedUniverseSymbol("kPEPE", allowed))
        assertFalse(DcaPulseGate.isAllowedUniverseSymbol("DOG", allowed))
    }

    @Test
    fun longAndShortDeviationMoveAgainstPosition() {
        assertTrue(DcaPulseGate.reachedDeviation(false, 98.0, 100.0, 2.0))
        assertFalse(DcaPulseGate.reachedDeviation(false, 99.0, 100.0, 2.0))
        assertTrue(DcaPulseGate.reachedDeviation(true, 102.0, 100.0, 2.0))
        assertFalse(DcaPulseGate.reachedDeviation(true, 101.0, 100.0, 2.0))
    }

    @Test
    fun runningDealUsesEqualOrdersAndOriginalEntryLadder() {
        val settings = DcaBotSettings(
            baseOrderUsd = 20.0,
            safetyOrderUsd = 10.0,
            maxSafetyOrders = 3,
            shortPriceDeviationPercentage = 8.0,
            volumeScale = 2.0,
            stepScale = 1.5
        )
        assertEquals(20.0, settings.orderValueFor(0), 0.001)
        assertEquals(20.0, settings.orderValueFor(1), 0.001)
        assertEquals(20.0, settings.orderValueFor(2), 0.001)
        assertEquals(80.0, settings.maximumDealValueUsd(), 0.001)
        assertEquals(2.0, settings.deviationFor(false, 0), 0.001)
        assertEquals(4.0, settings.deviationFor(false, 1), 0.001)
        assertEquals(6.0, settings.deviationFor(false, 2), 0.001)
        assertTrue(DcaPulseGate.reachedDeviation(false, 96.0, 100.0, settings.deviationFor(false, 1)))
        assertEquals(16.0, settings.deviationFor(true, 1), 0.001)
        assertTrue(DcaPulseGate.reachedDeviation(true, 116.0, 100.0, settings.deviationFor(true, 1)))
    }

    @Test
    fun balanceAllowsAtMostThreePositionDifference() {
        assertTrue(DirectionBalanceGate.permits(false, 2, 0))
        assertFalse(DirectionBalanceGate.permits(false, 3, 0))
        assertTrue(DirectionBalanceGate.permits(true, 3, 0))
    }

    @Test
    fun trailingExitTracksBestPriceInBothDirections() {
        assertEquals(112.0, DcaPulseGate.updatedBestPrice(false, 112.0, 110.0), 0.001)
        assertTrue(DcaPulseGate.trailingExitReached(false, 110.88, 112.0, 1.0))
        assertEquals(88.0, DcaPulseGate.updatedBestPrice(true, 88.0, 90.0), 0.001)
        assertTrue(DcaPulseGate.trailingExitReached(true, 88.88, 88.0, 1.0))
    }

    @Test
    fun everyOpenPositionOccupiesOneDcaDealSlot() {
        val state = DcaCapacityPolicy.fromPositionCounts(
            longCount = 4,
            shortCount = 7,
            maximumDeals = 50
        )

        assertEquals(11, state.activeDeals)
        assertEquals(39, state.remainingDeals)
        assertFalse(state.isFull)
    }

    @Test
    fun dcaRefillsQuicklyUntilFullThenUsesQuarterHourMonitoring() {
        val stillFilling = DcaCapacityPolicy.fromActiveCount(activeDeals = 11, maximumDeals = 50)
        val full = DcaCapacityPolicy.fromActiveCount(activeDeals = 50, maximumDeals = 50)

        assertEquals(1L, DcaCapacityPolicy.nextScanDelayMinutes(stillFilling, 15L))
        assertEquals(15L, DcaCapacityPolicy.nextScanDelayMinutes(full, 15L))
    }

    @Test
    fun everyDcaInputUpdatesTheSameSettingsObject() {
        val original = DcaBotSettings(minimumWinRate = 72.0, minimumQualityScore = 73.0)
        val updated = DcaBotSettingsInput(
            baseOrderUsd = "15,50",
            maxSafetyOrders = "6",
            longDeviationPercentage = "2,5",
            shortDeviationPercentage = "8",
            maxActiveDeals = "70",
            cooldownValue = "2",
            cooldownInHours = true,
            portfolioTargetPercentage = "15",
            topUniverseSize = "137",
            entryMode = "direct",
            stopLossEnabled = true
        ).applyTo(original)

        assertEquals(15.5, updated.baseOrderUsd, 0.001)
        assertEquals(15.5, updated.safetyOrderUsd, 0.001)
        assertEquals(6, updated.maxSafetyOrders)
        assertEquals(2.5, updated.priceDeviationPercentage, 0.001)
        assertEquals(8.0, updated.shortPriceDeviationPercentage, 0.001)
        assertEquals(70, updated.maxActiveDeals)
        assertEquals(120, updated.cooldownMinutes)
        assertEquals(15.0, updated.portfolioTargetPercentage, 0.001)
        assertEquals(137, updated.topUniverseSize)
        assertTrue(updated.usesDirectEntry())
        assertTrue(updated.stopLossEnabled)
        assertEquals(72.0, updated.minimumWinRate, 0.001)
        assertEquals(73.0, updated.minimumQualityScore, 0.001)
    }

    @Test
    fun arbitraryPositiveUniverseInputIsPassedToAsterEndpointWithoutPresetRounding() {
        assertEquals("/v1/me/market/aster-usdt?limit=1", AsterUniverseRequest.endpointPath(0))
        assertEquals("/v1/me/market/aster-usdt?limit=137", AsterUniverseRequest.endpointPath(137))
        assertEquals("/v1/me/market/aster-usdt?limit=999", AsterUniverseRequest.endpointPath(999))
    }

    @Test
    fun top200CanInternallyFill150BalancedUniqueDealsWithoutRealOrders() {
        val syntheticTop200 = (1..200).map { rank -> rank % 2 == 0 }
        val accepted = DcaCapacityPolicy.acceptedDirections(
            candidateDirections = syntheticTop200,
            initialLongs = 0,
            initialShorts = 0,
            maximumDeals = 150
        )

        assertEquals(150, accepted.size)
        assertEquals(75, accepted.count { !it })
        assertEquals(75, accepted.count { it })
    }

    @Test
    fun freePositionsFillForMultipleMaximumSettingsWithoutRealOrders() {
        listOf(5, 20, 30, 70, 100, 150, 200).forEach { maximum ->
            val alternatingDirections = (1..500).map { index -> index % 2 == 0 }
            val accepted = DcaCapacityPolicy.acceptedDirections(
                candidateDirections = alternatingDirections,
                initialLongs = 0,
                initialShorts = 0,
                maximumDeals = maximum
            )
            assertEquals("maximum=$maximum", maximum, accepted.size)
            assertTrue("maximum=$maximum balance", kotlin.math.abs(
                accepted.count { !it } - accepted.count { it }
            ) <= 1)
        }
    }

    @Test
    fun partiallyFilledPortfolioContinuesUntilConfiguredMaximum() {
        val candidates = (1..200).map { index -> index % 2 == 0 }
        val accepted = DcaCapacityPolicy.acceptedDirections(
            candidateDirections = candidates,
            initialLongs = 5,
            initialShorts = 8,
            maximumDeals = 70
        )

        assertEquals(57, accepted.size)
        val finalLongs = 5 + accepted.count { !it }
        val finalShorts = 8 + accepted.count { it }
        assertEquals(70, finalLongs + finalShorts)
        assertTrue(kotlin.math.abs(finalLongs - finalShorts) <= 3)
    }

    @Test
    fun directEntryKeepsManualExitAndDcaAddOnRulesSeparate() {
        val settings = DcaBotSettings(
            entryMode = "direct",
            baseOrderUsd = 12.0,
            maxSafetyOrders = 3,
            priceDeviationPercentage = 2.0,
            shortPriceDeviationPercentage = 8.0,
            takeProfitEnabled = false,
            trailingTakeProfitEnabled = false
        ).validated()

        assertTrue(settings.usesDirectEntry())
        assertFalse(settings.takeProfitEnabled)
        assertFalse(settings.trailingTakeProfitEnabled)
        assertEquals(12.0, settings.orderValueFor(0), 0.001)
        assertEquals(2.0, settings.deviationFor(false, 0), 0.001)
        assertEquals(8.0, settings.deviationFor(true, 0), 0.001)
    }

    @Test
    fun directModeEndToEndSimulationFillsEveryFreeSlotWithUniqueBalancedPairs() {
        val settings = DcaBotSettings(
            entryMode = "direct",
            topUniverseSize = 150,
            maxActiveDeals = 70,
            baseOrderUsd = 12.0,
            takeProfitEnabled = false,
            trailingTakeProfitEnabled = false
        ).validated()
        val alreadyActive = (1..13).map { "PAIR$it" }.toSet()
        val rankedTop150 = (1..150).map { rank -> "PAIR$rank" to if (rank % 2 == 0) 8.0 else -8.0 }
        val eligibleUnique = rankedTop150
            .filterNot { it.first in alreadyActive }
            .distinctBy { it.first }
        val acceptedDirections = DcaCapacityPolicy.acceptedDirections(
            candidateDirections = eligibleUnique.map { it.second < 0.0 },
            initialLongs = 5,
            initialShorts = 8,
            maximumDeals = settings.maxActiveDeals
        )

        assertTrue(settings.usesDirectEntry())
        assertEquals(57, acceptedDirections.size)
        assertEquals(70, 13 + acceptedDirections.size)
        assertTrue(kotlin.math.abs(
            (5 + acceptedDirections.count { !it }) - (8 + acceptedDirections.count { it })
        ) <= 3)
        assertFalse(settings.takeProfitEnabled)
        assertFalse(settings.trailingTakeProfitEnabled)
    }

    @Test
    fun maxActiveDealsSupports150AndCapsOnlyAt500() {
        assertEquals(150, DcaBotSettings(maxActiveDeals = 150).validated().maxActiveDeals)
        assertEquals(500, DcaBotSettings(maxActiveDeals = 999).validated().maxActiveDeals)
    }

    @Test
    fun closeAllTargetsOf80And300PercentKeepTheSameStartAndTriggerOnlyAtTarget() {
        val start = 400.0
        assertEquals(720.0, TradingCyclePolicy.targetValue(start, 80.0), 0.001)
        assertFalse(TradingCyclePolicy.targetReached(start, 719.99, 80.0))
        assertTrue(TradingCyclePolicy.targetReached(start, 720.0, 80.0))

        assertEquals(1_600.0, TradingCyclePolicy.targetValue(start, 300.0), 0.001)
        assertFalse(TradingCyclePolicy.targetReached(start, 1_599.99, 300.0))
        assertTrue(TradingCyclePolicy.targetReached(start, 1_600.0, 300.0))
        assertEquals(start, 400.0, 0.0)
    }

    @Test
    fun pricePerformanceIsUnleveragedAndDirectionAware() {
        assertEquals(-2.0, DcaPulseGate.pricePerformancePercentage(false, 98.0, 100.0), 0.001)
        assertEquals(-2.0, DcaPulseGate.pricePerformancePercentage(true, 102.0, 100.0), 0.001)
        assertEquals(2.0, DcaPulseGate.pricePerformancePercentage(true, 98.0, 100.0), 0.001)
    }

    @Test
    fun scannerRestartsOnlyWhenEnabledNotFullAndProgressIsStale() {
        val now = 1_000_000L
        assertTrue(ScannerContinuityPolicy.shouldRestart(true, "scanning", now - 91_000L, now, 11, 30))
        assertTrue(ScannerContinuityPolicy.shouldRestart(true, "idle", now - 91_000L, now, 11, 30))
        assertFalse(ScannerContinuityPolicy.shouldRestart(true, "scanning", now - 30_000L, now, 11, 30))
        assertFalse(ScannerContinuityPolicy.shouldRestart(true, "refill_wait", now - 120_000L, now, 11, 30))
        assertFalse(ScannerContinuityPolicy.shouldRestart(true, "idle", now - 120_000L, now, 30, 30))
        assertFalse(ScannerContinuityPolicy.shouldRestart(false, "idle", now - 120_000L, now, 11, 30))
    }

    @Test
    fun loweringMaximumBelowOpenCountShowsOverLimitAndAcceptsNoNewDeals() {
        val state = DcaCapacityPolicy.fromActiveCount(activeDeals = 81, maximumDeals = 80)
        assertTrue(state.isFull)
        assertEquals(1, state.overLimitDeals)
        assertEquals(0, state.remainingDeals)
        assertTrue(DcaCapacityPolicy.acceptedDirections(listOf(false, true), 40, 41, 80).isEmpty())
    }

    @Test
    fun manuallyClosedProfitableShortIsRecordedAsWon() {
        val trade = TrackedTrade(
            id = 1L,
            symbol = "kBONK",
            shortDirection = true,
            entryPrice = 0.000020,
            profitPercentage = 1.5,
            timeframe = "Open positie",
            startedAt = 1_000L,
            expiresAt = Long.MAX_VALUE,
            outcome = TradeOutcome.Pending
        )
        val result = TradeClosureReconciler.reconcileClosedTrade(
            trade,
            listOf(HyperliquidFill(
                coin = "kBONK",
                direction = "Close Short",
                closedPnl = "1.09",
                fee = "0.01",
                price = "0.000019",
                time = 2_000L
            ))
        )

        requireNotNull(result)
        assertEquals(TradeOutcome.Succeeded, result.outcome)
        assertEquals(1.09, result.realizedPnl ?: 0.0, 0.0001)
        assertEquals(2_000L, result.closedAt)
        assertEquals("Handmatig met winst gesloten", result.exitAdvice)
    }

    @Test
    fun splitCloseFillsAreAggregatedBeforeClassifyingResult() {
        val trade = TrackedTrade(
            id = 2L, symbol = "BTC", shortDirection = false, entryPrice = 100.0,
            profitPercentage = 1.0, timeframe = "Open positie", startedAt = 1_000L,
            expiresAt = Long.MAX_VALUE
        )
        val result = TradeClosureReconciler.reconcileClosedTrade(trade, listOf(
            HyperliquidFill(coin = "BTC", direction = "Close Long", closedPnl = "0.40", fee = "0.02", time = 2_000L),
            HyperliquidFill(coin = "BTC", direction = "Close Long", closedPnl = "0.69", fee = "0.03", time = 2_100L)
        ))

        requireNotNull(result)
        assertEquals(1.09, result.realizedPnl ?: 0.0, 0.0001)
        assertEquals(0.05, result.feesPaidUsd, 0.0001)
        assertEquals(2_100L, result.closedAt)
    }

    @Test
    fun invalidTextKeepsEveryExistingSettingInsteadOfResettingAnotherScreen() {
        val original = DcaBotSettings(
            baseOrderUsd = 44.0,
            safetyOrderUsd = 44.0,
            maxSafetyOrders = 9,
            priceDeviationPercentage = 3.0,
            shortPriceDeviationPercentage = 11.0,
            maxActiveDeals = 88,
            cooldownMinutes = 77,
            portfolioTargetPercentage = 19.0,
            topUniverseSize = 222,
            stopLossEnabled = true
        )
        val unchanged = DcaBotSettingsInput(
            baseOrderUsd = "",
            maxSafetyOrders = "",
            longDeviationPercentage = "",
            shortDeviationPercentage = "",
            maxActiveDeals = "",
            cooldownValue = "",
            cooldownInHours = true,
            portfolioTargetPercentage = "",
            topUniverseSize = "",
            entryMode = original.entryMode,
            stopLossEnabled = true
        ).applyTo(original)

        assertEquals(original, unchanged)
    }
}
