package com.tradementor.app.scanner

import android.content.Context
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken

enum class OrderEnvironment { Testnet, Mainnet }
enum class OrderIntentStatus { AwaitingApiWallet, ReadyForTestnet, Submitted, Rejected }

data class HyperliquidOrderIntent(
    val id: Long,
    val symbol: String,
    val shortDirection: Boolean,
    val positionValueUsd: Double,
    val leverage: Int,
    val estimatedMarginUsd: Double,
    val entryPrice: Double,
    val targetPrice: Double,
    val environment: OrderEnvironment = OrderEnvironment.Testnet,
    val status: OrderIntentStatus = OrderIntentStatus.AwaitingApiWallet,
    val explanation: String = "Testnet-order wacht op een goedgekeurde API-wallet"
)

object HyperliquidOrderPlanner {
    fun create(symbol: String, shortDirection: Boolean, positionValueUsd: Double, maxLeverage: Int, entryPrice: Double, profitPercentage: Double): HyperliquidOrderIntent {
        require(positionValueUsd >= 10.0) { "Hyperliquid-orders moeten minimaal $10 positiewaarde hebben." }
        require(entryPrice > 0.0)
        val leverage = maxLeverage.coerceAtLeast(1)
        val target = if (shortDirection) entryPrice * (1.0 - profitPercentage / 100.0) else entryPrice * (1.0 + profitPercentage / 100.0)
        return HyperliquidOrderIntent(
            id = System.currentTimeMillis(), symbol = symbol, shortDirection = shortDirection,
            positionValueUsd = positionValueUsd, leverage = leverage,
            estimatedMarginUsd = positionValueUsd / leverage,
            entryPrice = entryPrice, targetPrice = target
        )
    }
}

object OrderIntentStore {
    private const val PREFS = "hyperliquid_order_intents"
    private const val KEY = "items"
    fun load(context: Context): List<HyperliquidOrderIntent> = runCatching {
        val json = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(KEY, null) ?: return emptyList()
        val type = object : TypeToken<List<HyperliquidOrderIntent>>() {}.type
        Gson().fromJson<List<HyperliquidOrderIntent>>(json, type).orEmpty()
    }.getOrDefault(emptyList())
    @Synchronized fun addIfAbsent(context: Context, intent: HyperliquidOrderIntent) {
        val current = load(context)
        if (current.any { it.symbol.equals(intent.symbol, true) && it.status != OrderIntentStatus.Rejected }) return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString(KEY, Gson().toJson((listOf(intent) + current).take(500))).apply()
    }
}
