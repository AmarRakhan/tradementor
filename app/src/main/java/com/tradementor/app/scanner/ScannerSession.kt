package com.tradementor.app.scanner

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import com.tradementor.app.api.CustomScanSignal
import com.tradementor.app.api.ScanCondition
import com.tradementor.app.api.ScanMetric
import com.tradementor.app.api.ScanOperator
import com.tradementor.app.repository.MarketRepository

object ScannerSession {
    private val repository = MarketRepository()
    private var cachedMarkets = emptyList<com.tradementor.app.api.PerpetualMarket>()
    private var marketsCachedAt = 0L
    var results by mutableStateOf<List<CustomScanSignal>>(emptyList())
    var scanning by mutableStateOf(false)
    var progress by mutableIntStateOf(0)
    var total by mutableIntStateOf(0)
    var error by mutableStateOf<String?>(null)
    var hasLoaded by mutableStateOf(false)
    var activeConditions by mutableStateOf<List<ScanCondition>>(emptyList())
    var requireAll by mutableStateOf(true)

    val defaultCondition = ScanCondition(
        id = 1L,
        metric = ScanMetric.BollingerUpperDistance,
        operator = ScanOperator.GreaterThan,
        threshold = 0.0,
        label = "Prijs boven upper Bollinger Band",
        interval = "4h"
    )

    suspend fun preload() {
        if (hasLoaded || scanning) return
        scan(listOf(defaultCondition), true)
    }

    suspend fun scan(conditions: List<ScanCondition>, requireAll: Boolean) {
        activeConditions = conditions
        this.requireAll = requireAll
        if (scanning || conditions.isEmpty()) return
        scanning = true
        progress = 0
        error = null
        try {
            val now = System.currentTimeMillis()
            val markets = if (cachedMarkets.isNotEmpty() && now - marketsCachedAt < 60_000L) {
                cachedMarkets
            } else {
                repository.getMarkets().orEmpty().also {
                    cachedMarkets = it
                    marketsCachedAt = now
                }
            }
            total = markets.size
            results = repository.scanCustomConditions(markets, conditions, requireAll) { done, count ->
                progress = done
                total = count
            }
            hasLoaded = true
        } catch (_: Exception) {
            error = "De scan kon niet worden voltooid."
        } finally {
            scanning = false
        }
    }
}
