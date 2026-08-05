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
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.repository.WalletRepository
import com.reown.appkit.client.AppKit
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
            ExistingWorkPolicy.KEEP,
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
        val configJson = prefs.getString("config", null) ?: return Result.success()
        val config = runCatching { Gson().fromJson(configJson, BackgroundScanConfig::class.java) }.getOrNull()
            ?: return Result.failure()
        val watchlistEnabled = config.enabled
        val autoTradingEnabled = AutoTradingStore.isEnabled(applicationContext)
        if (!watchlistEnabled && !autoTradingEnabled) return Result.success()

        ScannerProgressStore.update(applicationContext, "account")
        return try {
            val repository = MarketRepository()
            var portfolioValue = 0.0
            var availableToTrade = 0.0
            var maintenanceMargin = 0.0
            AppKit.getAccount()?.address?.takeIf { it.isNotBlank() }?.let { walletAddress ->
                runCatching { WalletRepository().load(walletAddress) }.getOrNull()?.let { wallet ->
                    portfolioValue = wallet.portfolioValue
                    availableToTrade = wallet.availableToTrade
                    maintenanceMargin = wallet.account.crossMaintenanceMarginUsed.toDoubleOrNull() ?: 0.0
                    val positions = wallet.account.assetPositions
                    val symbols = positions.map { it.position.coin.uppercase() }.toSet()
                    ProfitableTradeClosureNotifier.reconcile(applicationContext, symbols, wallet.recentFills)
                    ActiveHyperliquidPositionStore.update(
                        applicationContext,
                        longCount = positions.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) > 0.0 },
                        shortCount = positions.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) < 0.0 },
                        symbols = symbols
                    )
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
            if (autoTradingEnabled) {
                ScannerProgressStore.update(applicationContext, "protection")
                val selectedForProtection = StrategyProfileStore.activeDefinition(applicationContext)
                val protection = TradingGatewayClient().protectOpenPositions(
                    LocalTradingGatewayStore.url(applicationContext), profile.profitTarget,
                    if (selectedForProtection.id == "strategy_2") minOf(profile.stopLoss, 1.5) else profile.stopLoss,
                    selectedForProtection.id
                )
                if (protection.failed.isNotEmpty() || !protection.scanAndBuyEnabled) {
                    AutoTradingStore.setEnabled(applicationContext, false)
                    ScannerProgressStore.update(applicationContext, "error")
                    return Result.failure()
                }
            }
            val activeStrategy = StrategyProfileStore.activeDefinition(applicationContext)
            if (!activeStrategy.executionReady || activeStrategy.id !in setOf("strategy_1", "strategy_2")) {
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
            } else executionSettings.maxActiveTrades
            if (activeStrategy.id == "strategy_2") {
                QuantumShieldCapacityStore.save(applicationContext, effectiveMaximum)
            }
            val marketLeverages = repository.getMarkets().orEmpty().associate { it.market.name.uppercase() to it.market.maxLeverage }
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
            val gatewayClient = TradingGatewayClient()
            val recommendations = advisorEngine.analyze(
                minimumWinRate = profile.minimumWinRate,
                profitPercentage = profile.profitTarget,
                maxAdversePercentage = profile.stopLoss,
                outcomeMinutes = 7 * 24 * 60,
                allowLong = profile.allowLong,
                allowShort = profile.allowShort,
                excludedSymbols = activeSymbols,
                onProgress = { partialResults, completed, total ->
                    ScannerProgressStore.update(applicationContext, "scanning", completed, total)
                    partialResults.filter { it.qualityScore >= profile.minimumScore }
                        .forEach { recommendation ->
                            val normalizedSymbol = recommendation.symbol.uppercase()
                            if (normalizedSymbol in handledThisScan) return@forEach
                            if (!evaluatedThisScan.add(normalizedSymbol)) return@forEach
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
                                profile.profitTarget,
                                profile.stopLoss,
                                profile.minimumWinRate,
                                profile.minimumScore
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
                            } else executionSettings.positionSizeUsd
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
                                    profitPercentage = profile.profitTarget,
                                    timeframe = recommendation.tradeType,
                                    startedAt = addedAt,
                                    expiresAt = addedAt + 7L * 24 * 60 * 60_000L,
                                    historicalWinRate = entry.winRate,
                                    remainingWinRate = entry.winRate,
                                    strategyId = activeStrategy.id,
                                    strategyName = activeStrategy.name,
                                    indicators = entry.indicators,
                                    maxAdversePercentage = profile.stopLoss,
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
                                                if (activeStrategy.id == "strategy_2") minOf(leverage, 3) else leverage
                                            },
                                            entry.price,
                                            profile.profitTarget
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
                                                profile.profitTarget,
                                                if (activeStrategy.id == "strategy_2") minOf(profile.stopLoss, 1.5) else profile.stopLoss,
                                                activeStrategy.id
                                            )
                                        }.onSuccess {
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
            ).filter { it.qualityScore >= profile.minimumScore }
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
            ScannerProgressStore.update(applicationContext, "idle", recommendations.size, recommendations.size, summary)
            Result.success()
        } catch (error: Exception) {
            Log.e("TradeMentorBackground", "Background scan failed", error)
            ScannerProgressStore.update(applicationContext, "error")
            // A trading scan must never enter an automatic error loop. Keep the
            // safety stop visible until the user starts a new controlled run.
            Result.failure()
        }
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
