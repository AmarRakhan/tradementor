package com.tradementor.app.scanner

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class QuantumShieldRiskEngineTest {
    @Test
    fun `small healthy portfolio can place hyperliquid minimum order`() {
        val amount = QuantumShieldPositionSizer.calculate(
            portfolioValue = 59.24,
            availableToTrade = 57.96,
            maintenanceMargin = 0.64,
            activeTrades = 1,
            automaticMaximum = 2,
            stopLossPercentage = 1.5,
            winRate = 80.0,
            qualityScore = 80.0
        )
        assertEquals(10.50, amount, 0.001)
    }

    @Test
    fun `minimum approved signal on small healthy account still reaches exchange minimum`() {
        val amount = QuantumShieldPositionSizer.calculate(
            portfolioValue = 59.24,
            availableToTrade = 57.96,
            maintenanceMargin = 0.64,
            activeTrades = 1,
            automaticMaximum = 2,
            stopLossPercentage = 1.5,
            winRate = 72.0,
            qualityScore = 70.0
        )
        assertEquals(10.50, amount, 0.001)
    }

    @Test
    fun `position size grows with capital but remains exposure capped`() {
        val amount = QuantumShieldPositionSizer.calculate(
            portfolioValue = 500.0,
            availableToTrade = 300.0,
            maintenanceMargin = 20.0,
            activeTrades = 3,
            automaticMaximum = 12,
            stopLossPercentage = 1.5,
            winRate = 85.0,
            qualityScore = 85.0
        )
        assertTrue(amount > 20.0)
        assertTrue(amount <= 36.0) // 12% of free collateral is the tightest cap.
    }

    @Test
    fun `no order is allowed without hyperliquid minimum free collateral`() {
        val amount = QuantumShieldPositionSizer.calculate(
            portfolioValue = 500.0,
            availableToTrade = 9.99,
            maintenanceMargin = 0.0,
            activeTrades = 0,
            automaticMaximum = 10,
            stopLossPercentage = 1.5,
            winRate = 90.0,
            qualityScore = 90.0
        )
        assertEquals(0.0, amount, 0.001)
    }

    @Test
    fun `higher liquidation pressure reduces autonomous size`() {
        val safe = QuantumShieldPositionSizer.calculate(500.0, 400.0, 20.0, 1, 10, 1.5, 85.0, 85.0)
        val pressured = QuantumShieldPositionSizer.calculate(500.0, 400.0, 120.0, 1, 10, 1.5, 85.0, 85.0)
        assertTrue(pressured < safe)
    }

    @Test
    fun `automatic trade ceiling never falls below already open positions`() {
        val maximum = QuantumShieldCapacityCalculator.calculate(
            activeTrades = 38,
            portfolioValue = 420.0,
            availableToTrade = 0.0,
            maintenanceMargin = 100.0,
            positionSizeUsd = 20.0,
            stopLossPercentage = 1.5
        )
        assertEquals(38, maximum)
    }
}
