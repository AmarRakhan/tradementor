package com.tradementor.app.mexc

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class MexcAutomationControlStateTest {
    @Test
    fun `active live automation shows stop`() {
        val state = mexcAutomationControlState(
            mode = MexcMode.LIVE,
            paperSessionActive = false,
            automationEnabled = true,
            automationMonitoring = true,
            automationProtectiveOnly = false,
        )

        assertEquals(MexcAutomationPrimaryAction.STOP, state.primaryAction)
        assertFalse(state.protectiveMonitoring)
    }

    @Test
    fun `protective monitor shows start so a stopped bot can restart`() {
        val state = mexcAutomationControlState(
            mode = MexcMode.LIVE,
            paperSessionActive = false,
            automationEnabled = false,
            automationMonitoring = true,
            automationProtectiveOnly = true,
        )

        assertEquals(MexcAutomationPrimaryAction.START, state.primaryAction)
        assertTrue(state.protectiveMonitoring)
    }

    @Test
    fun `inactive live automation shows start`() {
        val state = mexcAutomationControlState(
            mode = MexcMode.LIVE,
            paperSessionActive = false,
            automationEnabled = false,
            automationMonitoring = false,
            automationProtectiveOnly = false,
        )

        assertEquals(MexcAutomationPrimaryAction.START, state.primaryAction)
        assertFalse(state.protectiveMonitoring)
    }

    @Test
    fun `active paper session shows stop`() {
        val state = mexcAutomationControlState(
            mode = MexcMode.PAPER,
            paperSessionActive = true,
            automationEnabled = false,
            automationMonitoring = false,
            automationProtectiveOnly = false,
        )

        assertEquals(MexcAutomationPrimaryAction.STOP, state.primaryAction)
    }
}
