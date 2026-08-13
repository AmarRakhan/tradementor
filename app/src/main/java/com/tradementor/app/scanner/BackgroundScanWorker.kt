package com.tradementor.app.scanner

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.os.Build
import android.util.Log
import androidx.core.app.NotificationCompat
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import com.google.gson.Gson
import com.tradementor.app.MainActivity
import com.tradementor.app.R
import com.tradementor.app.api.ScanCondition
import com.tradementor.app.api.HyperliquidPosition
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.repository.WalletRepository
import com.reown.appkit.client.AppKit
import com.tradementor.app.cloud.CloudAccountRepository
import kotlinx.coroutines.CancellationException
import java.util.concurrent.TimeUnit

enum class NotificationMode(val title: String) {
    NewMatches("Alleen nieuwe matches"),
    ChangedCount("Als het aantal verandert"),
    EveryScan("Na iedere scan")
}

enum class NotificationStyle(val title: String) {
    Sound("Geluid"),
    Vibrate("Alleen trillen"),
    Silent("Stil")
}

data class BackgroundScanConfig(
    val enabled: Boolean,
    val strategyName: String,
    val requireAll: Boolean,
    val conditions: List<ScanCondition>,
    val intervalMinutes: Long,
    val notificationMode: NotificationMode,
    val notificationStyle: NotificationStyle
)

object AutoTradingStore {
    private const val PREFS = "automatic_trading"
    private const val ENABLED = "scan_and_buy_enabled"

    fun isEnabled(context: Context): Boolean = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getBoolean(ENABLED, false)

    fun setEnabled(context: Context, enabled: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(ENABLED, enabled).apply()
        BackgroundScannerScheduler.refresh(context)
    }
}

object BackgroundScannerScheduler {
    private const val UNIQUE_WORK = "tradementor_background_scanner"
    private const val UNIQUE_IMMEDIATE_WORK = "tradementor_scanner_run_now"
    private const val CONFIG_PREFS = "background_scanner"

    fun update(context: Context, config: BackgroundScanConfig) {
        context.getSharedPreferences(CONFIG_PREFS, Context.MODE_PRIVATE)
            .edit().putString("config", Gson().toJson(config)).apply()
        val workManager = WorkManager.getInstance(context)
        if (!config.enabled && !AutoTradingStore.isEnabled(context)) {
            workManager.cancelUniqueWork(UNIQUE_WORK)
            return
        }
        val request = PeriodicWorkRequestBuilder<BackgroundScanWorker>(
            config.intervalMinutes.coerceAtLeast(15), TimeUnit.MINUTES
        ).setConstraints(
            Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build()
        ).build()
        // Configuration is read from preferences at the start of every cycle.
        // KEEP prevents a UI refresh from cancelling a scan that is already running.
        workManager.enqueueUniquePeriodicWork(UNIQUE_WORK, ExistingPeriodicWorkPolicy.KEEP, request)
    }

    fun load(context: Context): BackgroundScanConfig? = runCatching {
        val json = context.getSharedPreferences(CONFIG_PREFS, Context.MODE_PRIVATE).getString("config", null)
            ?: return null
        Gson().fromJson(json, BackgroundScanConfig::class.java)
    }.getOrNull()

    fun runNow(context: Context) {
        if (!AutoTradingStore.isEnabled(context)) return
        ScannerProgressStore.update(context, "account")
        val request = OneTimeWorkRequestBuilder<BackgroundScanWorker>()
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        WorkManager.getInstance(context).enqueueUniqueWork(
            UNIQUE_IMMEDIATE_WORK,
            ExistingWorkPolicy.REPLACE,
            request
        )
    }

    fun refresh(context: Context) {
        val current = load(context) ?: BackgroundScanConfig(
            enabled = false, strategyName = "TradeMentor consensus", requireAll = true,
            conditions = emptyList(), intervalMinutes = 15,
            notificationMode = NotificationMode.NewMatches, notificationStyle = NotificationStyle.Silent
        )
        update(context, current)
    }
}

class BackgroundScanWorker(
    appContext: Context,
    params: WorkerParameters
) : CoroutineWorker(appContext, params) {
    override suspend fun doWork(): Result {
        val prefs = applicationContext.getSharedPreferences("background_scanner", Context.MODE_PRIVATE)
        val configJson = prefs.getString("config", null)
        if (configJson == null) {
            ScannerProgressStore.update(applicationContext, "idle", 0, 0, "Scannerconfig ontbreekt")
            return Result.success()
        }
        val config = runCatching { Gson().fromJson(configJson, BackgroundScanConfig::class.java) }.getOrNull()
            ?: run {
                ScannerProgressStore.update(applicationContext, "error", 0, 0, "Scannerconfig kan niet worden gelezen")
                return Result.success()
            }
        val watchlistEnabled = config.enabled
        val autoTradingEnabled = AutoTradingStore.isEnabled(applicationContext)
        if (!watchlistEnabled && !autoTradingEnabled) {
            ScannerProgressStore.update(applicationContext, "idle", 0, 0, "Scanner uitgeschakeld")
            return Result.success()
        }

        ScannerProgressStore.update(applicationContext, "account")
        return try {
            val repository = MarketRepository()
            var portfolioValue = 0.0
            var availableToTrade = 0.0
            var maintenanceMargin = 0.0
            var livePositions: List<HyperliquidPosition> = emptyList()
            val walletAddress = AppKit.getAccount()?.address?.takeIf { it.isNotBlank() }
                ?: runCatching { CloudAccountRepository.linkedWallet() }.getOrNull()
            walletAddress?.takeIf { it.isNotBlank() }?.let { walletAddress ->
                runCatching { WalletRepository().load(walletAddress) }.getOrNull()?.let { wallet ->
                    portfolioValue = wallet.portfolioValue
                    availableToTrade = wallet.availableToTrade
                    maintenanceMargin = wallet.account.crossMaintenanceMarginUsed.toDoubleOrNull() ?: 0.0
                    val positions = wallet.account.assetPositions
                    livePositions = positions.map { it.position }
                    val symbols = positions.map { it.position.coin }.toSet()
                    val normalizedSymbols = symbols.map { DcaPulseGate.normalizedBaseSymbol(it) }.toSet()
                    ProfitableTradeClosureNotifier.reconcile(applicationContext, symbols, wallet.recentFills)
                    ActiveHyperliquidPositionStore.update(
                        applicationContext,
                        longCount = positions.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) > 0.0 },
                        shortCount = positions.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) < 0.0 },
                        symbols = normalizedSymbols
                    )
                    DcaDealStore.retainOpen(applicationContext, normalizedSymbols)
                }
            }
            val checkTime = System.currentTimeMillis()
            var trackedTrades = TradeHistoryStore.load(applicationContext)
            val cycleStartedAt = TradingCycleStore.startedAt(applicationContext)
            trackedTrades.filter {
                it.outcome == TradeOutcome.Pending && it.startedAt >= cycleStartedAt
            }.forEach { trade ->
                val barrierOutcome = runCatching {
                    repository.getTradeBarrierOutcome(
                        trade.symbol,
                        trade.entryPrice,
                        trade.profitPercentage,
                        trade.maxAdversePercentage,
                        trade.shortDirection,
                        trade.startedAt,
                        minOf(checkTime, trade.expiresAt)
                    )
                }.onFailure { error ->
                    // Missing historical candles must not prevent protection or a new scan.
                    Log.w(
                        "TradeMentorBackground",
                        "Barrier check skipped for ${trade.symbol}: ${error.message}"
                    )
                }.getOrNull() ?: return@forEach
                if (barrierOutcome != 0 || trade.expiresAt <= checkTime) {
                    trackedTrades = trackedTrades.map {
                        if (it.id == trade.id) it.copy(
                            outcome = if (barrierOutcome == 1) TradeOutcome.Succeeded else TradeOutcome.Failed,
                            remainingWinRate = if (barrierOutcome == 1) 100.0 else 0.0,
                            exitAdvice = if (barrierOutcome == 1) "Doel bereikt" else "Doel niet binnen de looptijd bereikt",
                            adviceUpdatedAt = checkTime
                        ) else it
                    }
                }
            }
            TradeHistoryStore.save(applicationContext, trackedTrades)
            val activeSymbols = trackedTrades.filter {
                it.outcome == TradeOutcome.Pending && it.startedAt >= cycleStartedAt
            }
                .map { it.symbol.uppercase() }.toSet() + ActiveHyperliquidPositionStore.symbols(applicationContext)
            val executionSettings = SignalExecutionSettingsStore.load(applicationContext)
            var activeTradeCount = ActiveHyperliquidPositionStore.count(applicationContext)
            val profile = ConsensusProfileStore.load(applicationContext)
            val activeStrategy = StrategyProfileStore.activeDefinition(applicationContext)
            val dcaSettings = DcaBotSettingsStore.load(applicationContext)
            val gatewayClient = TradingGatewayClient()
            if (activeStrategy.id == "strategy_3") {
                runCatching { gatewayClient.dcaDeals(LocalTradingGatewayStore.url(applicationContext)) }
                    .onSuccess { DcaDealStore.syncFromCloud(applicationContext, it) }
                dcaSettings.executionBlockReason()?.let { reason ->
                    if (autoTradingEnabled) AutoTradingStore.setEnabled(applicationContext, false)
                    ScannerProgressStore.update(applicationContext, "idle", 0, 0, "DCA Pulse geblokkeerd: $reason")
                    return Result.success()
                }
                if (autoTradingEnabled) {
                    runCatching {
                        gatewayClient.updateTradingCycleTarget(
                            LocalTradingGatewayStore.url(applicationContext),
                            dcaSettings.portfolioTargetPercentage
                        )
                    }
                    val cycle = gatewayClient.evaluateTradingCycle(LocalTradingGatewayStore.url(applicationContext), portfolioValue)
                    TradingCycleStore.syncFromCloud(applicationContext, cycle)
                    if (cycle.targetReached) {
                        AutoTradingStore.setEnabled(applicationContext, false)
                        TradingCycleStore.lockAtTarget(applicationContext)
                        ScannerProgressStore.update(applicationContext, "idle", 0, 0, "Portfoliodoel bereikt · scanner uitgeschakeld voor handmatige controle")
                        return Result.success()
                    }
                }
            }
            val effectiveProfitTarget = if (activeStrategy.id == "strategy_3") 1.0 else profile.profitTarget
            val dcaStopLossEnabled = activeStrategy.id == "strategy_3" && dcaSettings.stopLossEnabled
            val effectiveStopLoss = if (activeStrategy.id == "strategy_3") 25.0 else if (activeStrategy.id == "strategy_2") minOf(profile.stopLoss, 1.5) else profile.stopLoss
            if (autoTradingEnabled && activeStrategy.id != "strategy_3") {
                ScannerProgressStore.update(applicationContext, "protection")
                val protection = runCatching {
                    gatewayClient.protectOpenPositions(
                        LocalTradingGatewayStore.url(applicationContext), effectiveProfitTarget,
                        effectiveStopLoss,
                        activeStrategy.id,
                        takeProfitEnabled = false,
                        trailingTakeProfitEnabled = false,
                        stopLossEnabled = dcaStopLossEnabled
                    )
                }.onFailure { error ->
                    Log.w("TradeMentorBackground", "Bescherming tijdelijk niet gelukt: ${error.message}")
                    ScannerProgressStore.update(applicationContext, "error", 0, 0, "Bescherming tijdelijk niet gelukt")
                }.getOrNull()

                if (protection == null) {
                    return Result.success()
                }
                if (protection.failed.isNotEmpty() || !protection.scanAndBuyEnabled) {
                    AutoTradingStore.setEnabled(applicationContext, false)
                    val message = if (protection.failed.isNotEmpty()) {
                        protection.failed.joinToString(prefix = "Bescherming faalt voor: ", postfix = "") { it["symbol"].toString() }
                    } else {
                        "Scan & Buy voorlopig uitgeschakeld"
                    }
                    ScannerProgressStore.update(applicationContext, "error", 0, 0, message)
                    return Result.success()
                }
            }
            if (!activeStrategy.executionReady || activeStrategy.id !in setOf("strategy_1", "strategy_2", "strategy_3")) {
                ScannerProgressStore.update(applicationContext, "idle", 0, 0, "${activeStrategy.name}: uitvoering vergrendeld")
                return Result.success()
            }
            val effectiveMaximum = if (activeStrategy.id == "strategy_2") {
                QuantumShieldCapacityCalculator.calculate(
                    activeTrades = activeTradeCount,
                    portfolioValue = portfolioValue,
                    availableToTrade = availableToTrade,
                    maintenanceMargin = maintenanceMargin,
                    positionSizeUsd = executionSettings.positionSizeUsd,
                    stopLossPercentage = minOf(profile.stopLoss, 1.5)
                )
            } else if (activeStrategy.id == "strategy_3") dcaSettings.maxActiveDeals else executionSettings.maxActiveTrades
            if (activeStrategy.id == "strategy_2") {
                QuantumShieldCapacityStore.save(applicationContext, effectiveMaximum)
            }
            val marketLeverages = repository.getMarkets().orEmpty().associate { it.market.name.uppercase() to it.market.maxLeverage }
            val topUniverseSize = if (activeStrategy.id == "strategy_3") dcaSettings.topUniverseSize.coerceIn(1, 500) else 50
            var universeFailureReason: String? = null
            val top50Symbols = if (activeStrategy.id == "strategy_3") {
                runCatching {
                    gatewayClient.coinMarketCapTop(LocalTradingGatewayStore.url(applicationContext), topUniverseSize)
                        .symbols
                        .map { it.symbol.uppercase() }
                        .take(topUniverseSize)
                        .toSet()
                        .also {
                            if (it.isNotEmpty()) {
                                prefs.edit().putStringSet(DcaUniverseRequest.cacheKey(topUniverseSize), it).apply()
                            }
                        }
                }.getOrElse { error ->
                    Log.w("TradeMentorBackground", "Top-50 ophalen mislukt: ${error.message}")
                    universeFailureReason = error.message ?: "CoinMarketCap-universum niet beschikbaar"
                    prefs.getStringSet(DcaUniverseRequest.cacheKey(topUniverseSize), emptySet()).orEmpty()
                }
            } else emptySet()
            if (activeStrategy.id == "strategy_3" && top50Symbols.isEmpty()) {
                val message = "Top-$topUniverseSize controle mislukt · geen orders · ${universeFailureReason.orEmpty()}"
                ScannerProgressStore.update(applicationContext, "refill_wait", 0, topUniverseSize, message)
                if (autoTradingEnabled) {
                    scheduleAutoRestart(applicationContext, config, delayMinutes = 1L)
                }
                return Result.success()
            }
            val tradableUniverseCount = if (activeStrategy.id == "strategy_3") {
                repository.getMarkets().orEmpty().count { DcaPulseGate.isTop50(it.market.name, top50Symbols) }
            } else 0
            val handledThisScan = mutableSetOf<String>()
            val evaluatedThisScan = mutableSetOf<String>()
            val addedSymbols = mutableSetOf<String>()
            var orderAttempts = 0
            var ordersPlaced = 0
            var balanceRejected = 0
            var capacityRejected = 0
            var liveValidationRejected = 0
            var riskSizingRejected = 0
            val orderRejections = mutableListOf<String>()
            val advisorEngine = AdvisorEngine(repository)

            val dcaBollingerBySymbol = if (activeStrategy.id == "strategy_3" && autoTradingEnabled) {
                val activeMarkets = repository.getMarkets().orEmpty().filter {
                    it.market.name.uppercase() in livePositions.map { position -> position.coin.uppercase() }.toSet()
                }
                repository.scanBollingerBands(activeMarkets, interval = "1m", period = 20, deviationMultiplier = 2.0)
                    .associateBy { it.symbol.uppercase() }
            } else emptyMap()

            if (activeStrategy.id == "strategy_3" && autoTradingEnabled) {
                livePositions.forEach { position ->
                    val state = DcaDealStore.find(applicationContext, position.coin) ?: return@forEach
                    val size = position.signedSize.toDoubleOrNull() ?: return@forEach
                    val averageEntry = position.entryPrice?.toDoubleOrNull() ?: return@forEach
                    val absoluteSize = kotlin.math.abs(size)
                    if (absoluteSize <= 0.0) return@forEach
                    val currentPrice = kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0) / absoluteSize
                    if (currentPrice <= 0.0) return@forEach
                    val updatedState = state

                    if (updatedState.safetyOrdersCompleted >= dcaSettings.maxSafetyOrders) return@forEach
                    if (!dcaSettings.allowsShort(updatedState.shortDirection)) return@forEach
                    val cooldownMillis = dcaSettings.cooldownMinutes * 60_000L
                    if (System.currentTimeMillis() - updatedState.lastOrderAt < cooldownMillis) return@forEach
                    val requiredDeviation = dcaSettings.deviationFor(updatedState.shortDirection, updatedState.safetyOrdersCompleted)
                    if (!DcaPulseGate.reachedDeviation(
                            updatedState.shortDirection, currentPrice, updatedState.initialEntryPrice, requiredDeviation
                        )
                    ) return@forEach
                    val bb = dcaBollingerBySymbol[position.coin.uppercase()] ?: return@forEach
                    val bbMatches = if (updatedState.shortDirection) {
                        bb.position == com.tradementor.app.api.BollingerPosition.AboveUpper
                    } else bb.position == com.tradementor.app.api.BollingerPosition.BelowLower
                    if (!bbMatches) return@forEach
                    val safetyOrderValue = dcaSettings.orderValueFor(updatedState.safetyOrdersCompleted)
                    if (safetyOrderValue < 10.0 || safetyOrderValue > availableToTrade) {
                        riskSizingRejected++
                        return@forEach
                    }
                    val intent = runCatching {
                        HyperliquidOrderPlanner.create(
                            position.coin,
                            updatedState.shortDirection,
                            safetyOrderValue,
                            marketLeverages[position.coin.uppercase()] ?: position.leverage.value,
                            currentPrice,
                            dcaSettings.takeProfitPercentage
                        )
                    }.getOrNull() ?: return@forEach
                    orderAttempts++
                    runCatching {
                        gatewayClient.executeAddOn(
                            LocalTradingGatewayStore.url(applicationContext),
                            LocalTradingGatewayStore.testToken(applicationContext),
                            intent,
                            dcaSettings.takeProfitPercentage,
                            strategyId = activeStrategy.id,
                            safetyOrderIndex = updatedState.safetyOrdersCompleted + 1,
                            maxSafetyOrders = dcaSettings.maxSafetyOrders,
                            maxDealValueUsd = dcaSettings.maximumDealValueUsd(),
                            maxAdversePercentage = dcaSettings.stopLossPercentage,
                            takeProfitEnabled = false,
                            trailingTakeProfitEnabled = false,
                            trailingDeviationPercentage = dcaSettings.trailingDeviationPercentage,
                            stopLossEnabled = dcaStopLossEnabled
                        )
                    }.onSuccess { execution ->
                        val completedOrders = updatedState.safetyOrdersCompleted + 1
                        DcaDealStore.upsert(
                            applicationContext,
                            updatedState.copy(
                                lastOrderPrice = execution.fillPrice.takeIf { it > 0.0 } ?: currentPrice,
                                safetyOrdersCompleted = completedOrders,
                                lastOrderAt = System.currentTimeMillis(),
                                trailingActivated = false,
                                bestTrailingPrice = null
                            )
                        )
                        TradeHistoryStore.save(
                            applicationContext,
                            TradeHistoryStore.load(applicationContext).map { trade ->
                                if (trade.closedAt == null && trade.strategyId == "strategy_3" && trade.symbol.equals(position.coin, true)) {
                                    trade.copy(dcaSafetyOrdersCompleted = completedOrders)
                                } else trade
                            }
                        )
                        availableToTrade = (availableToTrade - safetyOrderValue).coerceAtLeast(0.0)
                        ordersPlaced++
                    }.onFailure { error ->
                        orderRejections += "${position.coin}: DCA-order ${error.message ?: "geweigerd"}"
                    }
                }
            }

            val autoTradingStrategies = activeStrategy.id in setOf("strategy_1", "strategy_2", "strategy_3")
            val capacityReached = autoTradingEnabled && autoTradingStrategies && activeTradeCount >= effectiveMaximum
            if (capacityReached) {
                val monitoringMinutes = 15L
                ScannerProgressStore.update(
                    applicationContext,
                    "monitoring",
                    activeTradeCount,
                    effectiveMaximum,
                    "Maximale actieve deals bereikt (${activeTradeCount}/$effectiveMaximum) · ${monitoringMinutes}m controle"
                )
                scheduleAutoRestart(
                    context = applicationContext,
                    config = config.copy(intervalMinutes = monitoringMinutes),
                    delayMinutes = monitoringMinutes
                )
                return Result.success()
            }

            val dcaMovementBySymbol = if (activeStrategy.id == "strategy_3") {
                repository.getMarkets().orEmpty().associate {
                    it.market.name.uppercase() to kotlin.math.abs(it.changePercentage)
                }
            } else emptyMap()
            val recommendations = if (activeStrategy.id == "strategy_3") advisorEngine.analyzeDcaPulse(
                top50Symbols = top50Symbols,
                directEntry = dcaSettings.usesDirectEntry(),
                excludedSymbols = activeSymbols,
                onProgress = progress@ { partialResults, completed, total ->
                    ScannerProgressStore.update(applicationContext, "scanning", completed, total)
                    processRecommendations@ for (recommendation in partialResults) {
                        val normalizedSymbol = recommendation.symbol.uppercase()
                        if (!handledThisScan.add(normalizedSymbol)) continue@processRecommendations
                        val longNow = ActiveHyperliquidPositionStore.longCount(applicationContext)
                        val shortNow = ActiveHyperliquidPositionStore.shortCount(applicationContext)
                        if (!DirectionBalanceGate.permits(recommendation.shortDirection, longNow, shortNow)) {
                            balanceRejected++; continue@processRecommendations
                        }
                        if (activeTradeCount >= effectiveMaximum) { capacityRejected++; continue@processRecommendations }
                        val positionSize = dcaSettings.baseOrderUsd
                        if (positionSize < 10.0) { riskSizingRejected++; continue@processRecommendations }
                        val addedAt = System.currentTimeMillis()
                        val intent = HyperliquidOrderPlanner.create(
                            recommendation.symbol, recommendation.shortDirection, positionSize,
                            marketLeverages[normalizedSymbol] ?: 1, recommendation.price, 1.0
                        )
                        if (!autoTradingEnabled) continue@processRecommendations
                        orderAttempts++
                        runCatching {
                            gatewayClient.syncMaximum(LocalTradingGatewayStore.url(applicationContext), "", effectiveMaximum)
                            gatewayClient.executeOneTest(
                                LocalTradingGatewayStore.url(applicationContext), "", intent, 1.0, 25.0,
                                activeStrategy.id, takeProfitEnabled = false,
                                trailingTakeProfitEnabled = false, stopLossEnabled = dcaStopLossEnabled,
                                topUniverseSize = topUniverseSize
                            )
                        }.onSuccess { execution ->
                            TradeHistoryStore.addIfPairAvailable(applicationContext, TrackedTrade(
                                id = addedAt, symbol = recommendation.symbol,
                                shortDirection = recommendation.shortDirection, entryPrice = execution.fillPrice,
                                profitPercentage = 0.0, timeframe = "DCA Pulse", startedAt = addedAt,
                                expiresAt = Long.MAX_VALUE, historicalWinRate = 0.0, remainingWinRate = 0.0,
                                strategyId = activeStrategy.id, strategyName = activeStrategy.name,
                                indicators = recommendation.indicators, maxAdversePercentage = 100.0,
                                positionSizeUsd = positionSize
                            ))
                            val oldLong = ActiveHyperliquidPositionStore.longCount(applicationContext)
                            val oldShort = ActiveHyperliquidPositionStore.shortCount(applicationContext)
                            ActiveHyperliquidPositionStore.update(
                                applicationContext,
                                oldLong + if (recommendation.shortDirection) 0 else 1,
                                oldShort + if (recommendation.shortDirection) 1 else 0,
                                ActiveHyperliquidPositionStore.symbols(applicationContext) + normalizedSymbol
                            )
                            DcaDealStore.upsert(applicationContext, DcaDealState(
                                symbol = recommendation.symbol, shortDirection = recommendation.shortDirection,
                                initialEntryPrice = execution.fillPrice.takeIf { it > 0 } ?: recommendation.price,
                                lastOrderPrice = execution.fillPrice.takeIf { it > 0 } ?: recommendation.price
                            ))
                            activeTradeCount++; ordersPlaced++; addedSymbols += recommendation.symbol
                        }.onFailure { orderRejections += "${recommendation.symbol}: ${it.message ?: "order geweigerd"}" }
                    }
                }
            ) else advisorEngine.analyze(
                minimumWinRate = if (activeStrategy.id == "strategy_3") dcaSettings.minimumWinRate else profile.minimumWinRate,
                profitPercentage = effectiveProfitTarget,
                maxAdversePercentage = effectiveStopLoss,
                outcomeMinutes = 7 * 24 * 60,
                allowLong = profile.allowLong,
                allowShort = profile.allowShort,
                excludedSymbols = activeSymbols,
                onProgress = progress@ { partialResults, completed, total ->
                    ScannerProgressStore.update(applicationContext, "scanning", completed, total)
                    // DCA Pulse waits for the complete comparison. Otherwise the first
                    // analyzed market could buy before a harder-moving top-50 pair is seen.
                    if (activeStrategy.id == "strategy_3" && completed < total) return@progress
                    val requiredScore = if (activeStrategy.id == "strategy_3") dcaSettings.minimumQualityScore else profile.minimumScore
                    val prioritizedResults = if (activeStrategy.id == "strategy_3") {
                        partialResults.sortedByDescending { dcaMovementBySymbol[it.symbol.uppercase()] ?: 0.0 }
                    } else partialResults
                    prioritizedResults.filter { it.qualityScore >= requiredScore }
                        .forEach { recommendation ->
                            val normalizedSymbol = recommendation.symbol.uppercase()
                            if (normalizedSymbol in handledThisScan) return@forEach
                            if (!evaluatedThisScan.add(normalizedSymbol)) return@forEach
                            if (activeStrategy.id == "strategy_3" && !DcaPulseGate.isTop50(normalizedSymbol, top50Symbols)) {
                                liveValidationRejected++
                                return@forEach
                            }
                            if (activeStrategy.id == "strategy_3" && !dcaSettings.allowsShort(recommendation.shortDirection)) {
                                liveValidationRejected++
                                return@forEach
                            }
                            val longNow = ActiveHyperliquidPositionStore.longCount(applicationContext)
                            val shortNow = ActiveHyperliquidPositionStore.shortCount(applicationContext)
                            if (!DirectionBalanceGate.permits(recommendation.shortDirection, longNow, shortNow)) {
                                balanceRejected++
                                return@forEach
                            }
                            if (activeTradeCount >= effectiveMaximum) {
                                capacityRejected++
                                return@forEach
                            }
                            val entry = advisorEngine.validateForEntry(
                                recommendation,
                                effectiveProfitTarget,
                                effectiveStopLoss,
                                if (activeStrategy.id == "strategy_3") dcaSettings.minimumWinRate else profile.minimumWinRate,
                                requiredScore
                            ) ?: run {
                                liveValidationRejected++
                                return@forEach
                            }
                            val autonomousPositionSize = if (activeStrategy.id == "strategy_2") {
                                QuantumShieldPositionSizer.calculate(
                                    portfolioValue, availableToTrade, maintenanceMargin,
                                    activeTradeCount, effectiveMaximum, minOf(profile.stopLoss, 1.5),
                                    entry.winRate, entry.qualityScore
                                )
                            } else if (activeStrategy.id == "strategy_3") dcaSettings.baseOrderUsd else executionSettings.positionSizeUsd
                            if (autonomousPositionSize < 10.0) {
                                riskSizingRejected++
                                return@forEach
                            }
                            // Only mark it handled after the final live-price validation. A temporary
                            // price/candle miss may then be retried later in this same scan.
                            if (!handledThisScan.add(normalizedSymbol)) return@forEach
                            val addedAt = System.currentTimeMillis()
                            val added = TradeHistoryStore.addIfPairAvailable(
                                applicationContext,
                                TrackedTrade(
                                    id = addedAt,
                                    symbol = entry.symbol,
                                    shortDirection = entry.shortDirection,
                                    entryPrice = entry.price,
                                    profitPercentage = effectiveProfitTarget,
                                    timeframe = recommendation.tradeType,
                                    startedAt = addedAt,
                                    expiresAt = addedAt + 7L * 24 * 60 * 60_000L,
                                    historicalWinRate = entry.winRate,
                                    remainingWinRate = entry.winRate,
                                    strategyId = activeStrategy.id,
                                    strategyName = activeStrategy.name,
                                    indicators = entry.indicators,
                                    maxAdversePercentage = effectiveStopLoss,
                                    positionSizeUsd = autonomousPositionSize
                                )
                            )
                            if (added) {
                                addedSymbols += entry.symbol
                                val intent = runCatching {
                                    HyperliquidOrderPlanner.create(
                                            entry.symbol,
                                            entry.shortDirection,
                                        autonomousPositionSize,
                                            (marketLeverages[entry.symbol.uppercase()] ?: 1).let { leverage ->
                                                when (activeStrategy.id) {
                                                    "strategy_2" -> minOf(leverage, 3)
                                                    "strategy_3" -> minOf(leverage, dcaSettings.leverage)
                                                    else -> leverage
                                                }
                                            },
                                            entry.price,
                                            effectiveProfitTarget
                                        )
                                }.getOrNull()
                                if (intent != null) {
                                    OrderIntentStore.addIfAbsent(applicationContext, intent)
                                    val token = LocalTradingGatewayStore.testToken(applicationContext)
                                    if (autoTradingEnabled) {
                                        orderAttempts++
                                        runCatching {
                                            gatewayClient.syncMaximum(LocalTradingGatewayStore.url(applicationContext), token, effectiveMaximum)
                                           gatewayClient.executeOneTest(
                                               LocalTradingGatewayStore.url(applicationContext), token, intent,
                                               effectiveProfitTarget,
                                               effectiveStopLoss,
                                               activeStrategy.id,
                                                takeProfitEnabled = false,
                                                trailingTakeProfitEnabled = false,
                                                trailingDeviationPercentage = 0.0,
                                                stopLossEnabled = dcaStopLossEnabled,
                                                topUniverseSize = topUniverseSize
                                            )
                                        }.onSuccess { execution ->
                                            val oldLong = ActiveHyperliquidPositionStore.longCount(applicationContext)
                                            val oldShort = ActiveHyperliquidPositionStore.shortCount(applicationContext)
                                            ActiveHyperliquidPositionStore.update(
                                                applicationContext,
                                                longCount = oldLong + if (entry.shortDirection) 0 else 1,
                                                shortCount = oldShort + if (entry.shortDirection) 1 else 0,
                                                symbols = ActiveHyperliquidPositionStore.symbols(applicationContext) + entry.symbol.uppercase()
                                            )
                                            activeTradeCount++
                                            ordersPlaced++
                                            if (activeStrategy.id == "strategy_3") {
                                                DcaDealStore.upsert(
                                                    applicationContext,
                                                    DcaDealState(
                                                        symbol = entry.symbol,
                                                        shortDirection = entry.shortDirection,
                                                        initialEntryPrice = execution.fillPrice.takeIf { it > 0.0 } ?: entry.price,
                                                        lastOrderPrice = execution.fillPrice.takeIf { it > 0.0 } ?: entry.price
                                                    )
                                                )
                                            }
                                        }.onFailure { error ->
                                            // A rejected cloud order is not an active trade. Remove the
                                            // provisional history row so a later scan can try the pair again.
                                            TradeHistoryStore.save(
                                                applicationContext,
                                                TradeHistoryStore.load(applicationContext).filterNot { it.id == addedAt }
                                            )
                                            Log.e(
                                                "TradeMentorBackground",
                                                "Order execution failed for ${entry.symbol}: ${error.message}",
                                                error
                                            )
                                            orderRejections += "${entry.symbol}: ${error.message ?: "order geweigerd"}"
                                        }
                                    }
                                }
                            }
                        }
                }
            ).filter {
                it.qualityScore >= if (activeStrategy.id == "strategy_3") dcaSettings.minimumQualityScore else profile.minimumScore
            }.filter {
                activeStrategy.id != "strategy_3" ||
                    (DcaPulseGate.isTop50(it.symbol, top50Symbols) && dcaSettings.allowsShort(it.shortDirection))
            }
            val symbols = recommendations.map { it.symbol }.toSet()
            val previous = prefs.getStringSet("last_symbols", emptySet()).orEmpty()
            val shouldNotify = when (config.notificationMode) {
                NotificationMode.NewMatches -> (symbols - previous).isNotEmpty()
                NotificationMode.ChangedCount -> symbols.size != previous.size
                NotificationMode.EveryScan -> true
            }
            prefs.edit().putStringSet("last_symbols", symbols).apply()
            if (shouldNotify || addedSymbols.isNotEmpty()) showNotification(config, symbols, addedSymbols)
            val summary = when {
                ordersPlaced > 0 -> "${recommendations.size} kandidaten · $ordersPlaced gekocht"
                orderAttempts > 0 -> "${recommendations.size} kandidaten · ${orderRejections.joinToString(" · ").take(140)}"
                recommendations.isNotEmpty() -> {
                    val reasons = listOfNotNull(
                        liveValidationRejected.takeIf { it > 0 }?.let { "$it livecontrole" },
                        riskSizingRejected.takeIf { it > 0 }?.let { "$it risicolimiet/minimumorder" },
                        balanceRejected.takeIf { it > 0 }?.let { "$it richtingsbalans" },
                        capacityRejected.takeIf { it > 0 }?.let { "$it positielimiet" }
                    )
                    "${recommendations.size} kandidaten · ${reasons.joinToString(" · ").ifBlank { "geen uitvoerbare kandidaat" }}"
                }
                else -> "0 kandidaten voldeden aan de strategie"
            }
            val capacityAfterRun = DcaCapacityPolicy.fromActiveCount(activeTradeCount, effectiveMaximum)
            val nextDelayMinutes = if (activeStrategy.id == "strategy_3") {
                DcaCapacityPolicy.nextScanDelayMinutes(capacityAfterRun, config.intervalMinutes)
            } else config.intervalMinutes
            val progressPhase = when {
                autoTradingEnabled && activeStrategy.id == "strategy_3" && capacityAfterRun.isFull -> "monitoring"
                autoTradingEnabled && activeStrategy.id == "strategy_3" -> "refill_wait"
                else -> "idle"
            }
            val universeSummary = if (activeStrategy.id == "strategy_3") {
                "$tradableUniverseCount/$topUniverseSize verhandelbare markten gescand"
            } else ""
            val detailedSummary = listOf(summary, universeSummary).filter { it.isNotBlank() }.joinToString(" · ")
            val progressSummary = when (progressPhase) {
                "refill_wait" -> "$detailedSummary · ${capacityAfterRun.activeDeals}/${capacityAfterRun.maximumDeals} actief · vervolgscan over ${nextDelayMinutes} min"
                "monitoring" -> "${capacityAfterRun.activeDeals}/${capacityAfterRun.maximumDeals} actief · vol · automatische controle over ${nextDelayMinutes} min"
                else -> detailedSummary
            }
            ScannerProgressStore.update(
                applicationContext,
                progressPhase,
                recommendations.size,
                recommendations.size,
                progressSummary
            )

            if (autoTradingEnabled && activeStrategy.id in setOf("strategy_1", "strategy_2", "strategy_3")) {
                scheduleAutoRestart(context = applicationContext, config = config, delayMinutes = nextDelayMinutes)
            }
            Result.success()
        } catch (error: Exception) {
            Log.e("TradeMentorBackground", "Background scan failed", error)
            if (error is CancellationException) {
                ScannerProgressStore.update(applicationContext, "idle", 0, 0, "Scanner onderbroken · klaar voor volgende cyclus")
                return Result.success()
            }
            ScannerProgressStore.update(applicationContext, "error")
            // A trading scan must never enter an automatic error loop. Keep the
            // safety stop visible until the user starts a new controlled run.
            Result.success()
        }
    }

    private fun scheduleAutoRestart(context: Context, config: BackgroundScanConfig, delayMinutes: Long) {
        val workManager = WorkManager.getInstance(context)
        val minDelayMinutes = delayMinutes.coerceAtLeast(1L)
        val immediateWorkName = "tradementor_scanner_run_now"
        val request = OneTimeWorkRequestBuilder<BackgroundScanWorker>()
            .setInitialDelay(minDelayMinutes, TimeUnit.MINUTES)
            .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
            .build()
        workManager.enqueueUniqueWork(
            immediateWorkName,
            ExistingWorkPolicy.REPLACE,
            request
        )
    }

    private fun showNotification(config: BackgroundScanConfig, symbols: Set<String>, newSymbols: Set<String>) {
        val manager = applicationContext.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        val channelId = "scanner_${config.notificationStyle.name.lowercase()}"
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            val importance = if (config.notificationStyle == NotificationStyle.Silent) NotificationManager.IMPORTANCE_LOW else NotificationManager.IMPORTANCE_DEFAULT
            val channel = NotificationChannel(channelId, "Scanner ${config.notificationStyle.title}", importance).apply {
                enableVibration(config.notificationStyle == NotificationStyle.Vibrate || config.notificationStyle == NotificationStyle.Sound)
                if (config.notificationStyle != NotificationStyle.Sound) setSound(null, null)
            }
            manager.createNotificationChannel(channel)
        }
        val intent = Intent(applicationContext, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(applicationContext, 0, intent, PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE)
        val focusSymbols = if (newSymbols.isNotEmpty()) newSymbols else symbols
        val body = if (focusSymbols.isEmpty()) "Geen paren voldoen momenteel." else focusSymbols.take(6).joinToString(", ") + if (focusSymbols.size > 6) " en ${focusSymbols.size - 6} meer" else ""
        val notification = NotificationCompat.Builder(applicationContext, channelId)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle("${config.strategyName}: ${symbols.size} matches")
            .setContentText(body)
            .setStyle(NotificationCompat.BigTextStyle().bigText(body))
            .setContentIntent(pendingIntent)
            .setAutoCancel(true)
            .setSilent(config.notificationStyle == NotificationStyle.Silent)
            .build()
        manager.notify(2027, notification)
    }
}
