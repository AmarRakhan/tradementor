package com.tradementor.app.scanner

import android.content.Context
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.setValue

data class StrategyDefinition(
    val id: String,
    val name: String,
    val defined: Boolean,
    val enabledByDefault: Boolean,
    val specificationReady: Boolean = defined,
    val executionReady: Boolean = defined,
    val summary: String = ""
)

object StrategyProfileStore {
    private const val PREFS = "strategy_profiles"
    var revision by mutableIntStateOf(0)
        private set
    val definitions = listOf(
        StrategyDefinition("strategy_1", "TradeMentor Core", true, false, summary = "Onze bewezen technische selectie"),
        StrategyDefinition(
            "strategy_2",
            "Quantum Shield",
            defined = true,
            enabledByDefault = false,
            specificationReady = true,
            executionReady = true,
            summary = "Autonome portefeuillegroei met kapitaalbehoud als harde grens"
        ),
        StrategyDefinition(
            "strategy_3",
            "DCA Pulse",
            defined = true,
            enabledByDefault = true,
            specificationReady = true,
            executionReady = true,
            summary = "Multi-pair DCA-bot binnen het actuele Aster USDT Top-N-universum"
        ),
        StrategyDefinition("strategy_4", "Trend Voyager", false, false),
        StrategyDefinition("strategy_5", "Reversal Radar", false, false),
        StrategyDefinition("strategy_6", "Alpha Fusion", false, false)
    )

    private const val ACTIVE_KEY = "active_strategy_id"

    fun activeStrategyId(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val stored = prefs.getString(ACTIVE_KEY, null)
        if (stored != null && definitions.any { it.id == stored && it.specificationReady }) return stored
        val migrated = definitions.firstOrNull { it.defined && prefs.getBoolean("${it.id}_enabled", it.enabledByDefault) }
            ?.id ?: "strategy_3"
        prefs.edit().putString(ACTIVE_KEY, migrated).apply()
        return migrated
    }

    fun activeDefinition(context: Context): StrategyDefinition =
        definitions.firstOrNull { it.id == activeStrategyId(context) }
            ?: definitions.first { it.id == "strategy_3" }

    fun isEnabled(context: Context, id: String): Boolean {
        return activeStrategyId(context) == id
    }

    fun setEnabled(context: Context, id: String, enabled: Boolean) {
        val definition = definitions.firstOrNull { it.id == id } ?: return
        if (enabled && definition.specificationReady) {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(ACTIVE_KEY, id)
                .apply()
        } else if (!enabled && activeStrategyId(context) == id && id != "strategy_1") {
            context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
                .putString(ACTIVE_KEY, "strategy_1")
                .apply()
        }
        revision++
    }
}
