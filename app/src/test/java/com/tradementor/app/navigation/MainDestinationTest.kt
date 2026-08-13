package com.tradementor.app.navigation

import org.junit.Assert.assertEquals
import org.junit.Test

class MainDestinationTest {
    @Test
    fun `main navigation contains exactly the four master destinations`() {
        assertEquals(
            listOf("MEXC", "HYPERLIQUID", "ASTER", "WALLET"),
            mainDestinations().map { it.label },
        )
    }

    @Test
    fun `legacy or missing tab selection safely restores Hyperliquid`() {
        assertEquals(MainDestination.Hyperliquid, restoreMainDestination(null))
        assertEquals(MainDestination.Hyperliquid, restoreMainDestination("signals"))
        assertEquals(MainDestination.Wallet, restoreMainDestination("wallet"))
    }
}
