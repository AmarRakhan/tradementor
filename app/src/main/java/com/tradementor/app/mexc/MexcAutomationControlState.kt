package com.tradementor.app.mexc

enum class MexcAutomationPrimaryAction {
    START,
    STOP,
}

data class MexcAutomationControlState(
    val primaryAction: MexcAutomationPrimaryAction,
    val protectiveMonitoring: Boolean,
)

/**
 * Separates active order automation from monitoring that only protects
 * existing exposure. A protective monitor must never lock the UI on STOP:
 * the user must be able to explicitly start a new automation cycle again.
 */
fun mexcAutomationControlState(
    mode: MexcMode,
    paperSessionActive: Boolean,
    automationEnabled: Boolean,
    automationMonitoring: Boolean,
    automationProtectiveOnly: Boolean,
): MexcAutomationControlState {
    val liveTradingActive = mode == MexcMode.LIVE && automationEnabled && !automationProtectiveOnly
    val paperTradingActive = mode == MexcMode.PAPER && paperSessionActive
    return MexcAutomationControlState(
        primaryAction = if (liveTradingActive || paperTradingActive) {
            MexcAutomationPrimaryAction.STOP
        } else {
            MexcAutomationPrimaryAction.START
        },
        protectiveMonitoring = mode == MexcMode.LIVE &&
            automationMonitoring &&
            automationProtectiveOnly &&
            !automationEnabled,
    )
}
