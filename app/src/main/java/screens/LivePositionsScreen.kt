package com.tradementor.app.screens

import android.content.Context
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Slider
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.window.Dialog
import androidx.compose.ui.window.DialogProperties
import com.reown.appkit.client.AppKit
import com.tradementor.app.cloud.CloudAccountRepository
import com.tradementor.app.repository.WalletOverview
import com.tradementor.app.repository.WalletOverviewCache
import com.tradementor.app.repository.WalletRepository
import com.tradementor.app.api.HyperliquidAssetPosition
import com.tradementor.app.api.HyperliquidPosition
import com.tradementor.app.api.HyperliquidFill
import com.tradementor.app.scanner.TradeHistoryStore
import com.tradementor.app.scanner.TradeOutcome
import com.tradementor.app.scanner.TrackedTrade
import com.tradementor.app.scanner.LiveOutcomeLedger
import com.tradementor.app.scanner.ActiveHyperliquidPositionStore
import com.tradementor.app.scanner.LocalTradingGatewayStore
import com.tradementor.app.scanner.TradingGatewayClient
import com.tradementor.app.scanner.ConsensusProfileStore
import com.tradementor.app.scanner.ProfitableTradeClosureNotifier
import com.tradementor.app.scanner.SignalExecutionSettingsStore
import com.tradementor.app.scanner.AddOnTradeStore
import com.tradementor.app.scanner.AdvisorEngine
import com.tradementor.app.scanner.HyperliquidOrderPlanner
import com.tradementor.app.scanner.QuantumShieldCapacityCalculator
import com.tradementor.app.scanner.DcaBotSettingsStore
import com.tradementor.app.scanner.DcaBotSettings
import com.tradementor.app.scanner.DcaBotSettingsInput
import com.tradementor.app.scanner.DcaDealStore
import com.tradementor.app.scanner.DcaCapacityPolicy
import com.tradementor.app.scanner.DcaPulseGate
import com.tradementor.app.scanner.BackgroundScanConfig
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.AutoTradingStore
import com.tradementor.app.scanner.NotificationMode
import com.tradementor.app.scanner.NotificationStyle
import com.tradementor.app.scanner.TradingCycleStore
import com.tradementor.app.scanner.TradeClosureReconciler
import com.tradementor.app.scanner.ScannerProgressStore
import com.tradementor.app.scanner.ScannerContinuityPolicy
import com.tradementor.app.scanner.TakeAllProfitsPreview
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorTextButton
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.async
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.coroutineScope
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val PositionsBg = Color(0xFF05070B)
private val PositionsCard = Color(0xFF101723)
private val PositionsMuted = Color(0xFF8C92A3)
private val PositionsGreen = Color(0xFF08C887)
private val PositionsRed = Color(0xFFFF496A)
private val PositionsBlue = Color(0xFF2F68FF)
private enum class PositionView(val label: String) { Active("Actief"), Succeeded("Gewonnen"), Expired("Verloren") }
private enum class PositionSort(val label: String) {
    ClosestTarget("Dichtst bij doel"), Profit("Hoogste profit"), Loss("Grootste verlies"),
    Duration("Langste open"), Newest("Meest recent"), PositionSize("Grootste positie"),
    Leverage("Hoogste leverage"), Liquidation("Dichtst bij liquidatie")
}
private data class ManualCloseRequest(
    val symbol: String,
    val pnl: Double,
    val positionValue: Double,
    val shortDirection: Boolean,
    val percentage: Int = 100
)

@Composable
fun LivePositionsScreen(
    onOpenWallet: () -> Unit,
    onOpenStrategySettings: () -> Unit = {},
    modifier: Modifier = Modifier,
) {
    val context = LocalContext.current
    val repository = remember { WalletRepository() }
    var address by remember { mutableStateOf(AppKit.getAccount()?.address.orEmpty()) }
    var overview by remember(address) { mutableStateOf(WalletOverviewCache.get(address)) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshDelayMs by remember { mutableStateOf(15_000L) }
    var closeRequest by remember { mutableStateOf<ManualCloseRequest?>(null) }
    var closeMessage by remember { mutableStateOf<String?>(null) }
    var takeAllProfitsPreview by remember { mutableStateOf<TakeAllProfitsPreview?>(null) }
    var takeAllProfitsBusy by remember { mutableStateOf(false) }
    var addOnRequest by remember { mutableStateOf<Pair<String, AdvisorEngine.AddOnAssessment>?>(null) }
    var addOnAssessments by remember { mutableStateOf<Map<String, AdvisorEngine.AddOnAssessment>>(emptyMap()) }
    var addOnAnalysisTotal by remember { mutableStateOf(0) }
    var addOnAnalysisCompleted by remember { mutableStateOf(0) }
    var addOnBusy by remember { mutableStateOf<String?>(null) }
    var analysisTradeId by remember { mutableStateOf<Long?>(null) }
    var analysisSymbol by remember { mutableStateOf<String?>(null) }
    var positionView by remember { mutableStateOf(PositionView.Active) }
    var positionSort by remember { mutableStateOf(PositionSort.ClosestTarget) }
    var addOnOpportunitiesOnly by remember { mutableStateOf(false) }
    var nearAddOnOpportunitiesOnly by remember { mutableStateOf(false) }
    var filterMenuExpanded by remember { mutableStateOf(false) }
    var scannerEnabled by remember { mutableStateOf(AutoTradingStore.isEnabled(context)) }
    var scannerProgress by remember { mutableStateOf(ScannerProgressStore.load(context)) }
    var optimisticActiveCount by remember { mutableStateOf(ActiveHyperliquidPositionStore.count(context)) }
    var optimisticLongCount by remember { mutableStateOf(ActiveHyperliquidPositionStore.longCount(context)) }
    var optimisticShortCount by remember { mutableStateOf(ActiveHyperliquidPositionStore.shortCount(context)) }
    var performanceFlipped by remember { mutableStateOf(false) }
    var dcaDashboardOpen by remember { mutableStateOf(false) }
    var executionSettings by remember { mutableStateOf(SignalExecutionSettingsStore.load(context)) }
    var maxActiveTradesText by remember { mutableStateOf(executionSettings.maxActiveTrades.toString()) }
    var maxActiveTradesSlider by remember { mutableStateOf(executionSettings.maxActiveTrades.toFloat()) }
    val closeClient = remember { TradingGatewayClient() }
    val advisorEngine = remember { AdvisorEngine(MarketRepository()) }
    val scope = rememberCoroutineScope()
    val activeProfile = remember { ConsensusProfileStore.load(context) }
    val activeStrategy = com.tradementor.app.scanner.StrategyProfileStore.activeDefinition(context)
    var dcaSettings by remember { mutableStateOf(DcaBotSettingsStore.load(context)) }
    val activeProfitTarget = if (activeStrategy.id == "strategy_3") dcaSettings.takeProfitPercentage else activeProfile.profitTarget
    val activeStopLoss = when (activeStrategy.id) {
        "strategy_2" -> minOf(activeProfile.stopLoss, 1.5)
        "strategy_3" -> dcaSettings.stopLossPercentage
        else -> activeProfile.stopLoss
    }

    takeAllProfitsPreview?.let { preview ->
        AlertDialog(
            onDismissRequest = { if (!takeAllProfitsBusy) takeAllProfitsPreview = null },
            title = { Text("Take All Profits") },
            text = {
                Column(verticalArrangement = Arrangement.spacedBy(7.dp)) {
                    Text("${preview.eligibleCount} posities blijven naar verwachting netto groen.")
                    Text("Geschatte brutowinst: ${signedUsdPosition(preview.estimatedGrossProfitUsd)}")
                    Text("Na veiligheidsbuffer: ${signedUsdPosition(preview.estimatedNetProfitUsd)}", color = PositionsGreen, fontWeight = FontWeight.Bold)
                    Text("Rode posities blijven open. Scan & Buy wordt uitgeschakeld zodat vrijgekomen plaatsen niet direct opnieuw worden gevuld.", color = PositionsMuted, fontSize = 11.sp)
                }
            },
            confirmButton = {
                TradeMentorTextButton(
                    enabled = !takeAllProfitsBusy && preview.eligibleCount > 0,
                    onClick = {
                        takeAllProfitsBusy = true
                        scope.launch {
                            runCatching {
                                closeClient.executeTakeAllProfits(
                                    LocalTradingGatewayStore.url(context),
                                    "take-all-profits-${System.currentTimeMillis()}"
                                )
                            }.onSuccess { result ->
                                val closedSymbols = result.closed.map { it.symbol.uppercase() }.toSet()
                                if (closedSymbols.isNotEmpty()) {
                                    TradeHistoryStore.save(context, TradeHistoryStore.load(context).map { trade ->
                                        if (trade.closedAt == null && trade.symbol.uppercase() in closedSymbols) {
                                            trade.copy(exitAdvice = "Take All Profits")
                                        } else trade
                                    })
                                }
                                AutoTradingStore.setEnabled(context, false)
                                scannerEnabled = false
                                closeMessage = "${result.closedCount} winstposities gesloten. De echte netto winst wordt verwerkt in Profit vandaag en Profit totaal."
                                takeAllProfitsPreview = null
                            }.onFailure { failure ->
                                closeMessage = failure.message ?: "Take All Profits kon niet veilig worden uitgevoerd"
                            }
                            takeAllProfitsBusy = false
                        }
                    }
                ) { Text(if (takeAllProfitsBusy) "Veilig sluitenâ€¦" else "Sluit ${preview.eligibleCount} winstposities") }
            },
            dismissButton = {
                TradeMentorTextButton(
                    label = "Annuleren",
                    enabled = !takeAllProfitsBusy,
                    onClick = { takeAllProfitsPreview = null }
                )
            }
        )
    }

    LaunchedEffect(address, scannerEnabled, activeProfitTarget) {
        if (address.isBlank() || !scannerEnabled || activeStrategy.id == "strategy_3") return@LaunchedEffect
        runCatching {
            closeClient.protectOpenPositions(
                LocalTradingGatewayStore.url(context), activeProfitTarget, activeStopLoss, activeStrategy.id,
                takeProfitEnabled = false,
                trailingTakeProfitEnabled = false,
                stopLossEnabled = false
            )
        }.onSuccess { protection ->
            if (protection.failed.isNotEmpty() || !protection.scanAndBuyEnabled) {
                AutoTradingStore.setEnabled(context, false)
                scannerEnabled = false
                closeMessage = "Scan & Buy is gestopt: niet iedere positie kon veilig met een take-profit worden beschermd."
            } else if (protection.repaired.isNotEmpty()) {
                closeMessage = "Take-profitcontrole voltooid: ${protection.repaired.size} posities beschermd" +
                    "."
            }
        }.onFailure {
            AutoTradingStore.setEnabled(context, false)
            scannerEnabled = false
            closeMessage = "Scan & Buy is gestopt omdat de take-profitcontrole niet kon worden bevestigd."
        }
    }

    LaunchedEffect(Unit) {
        val migration = context.getSharedPreferences("live_positions_migration", Context.MODE_PRIVATE)
        if (!migration.getBoolean("old_watchlist_cleared_build_87", false)) {
            TradeHistoryStore.save(context, emptyList())
            migration.edit().putBoolean("old_watchlist_cleared_build_87", true).apply()
        }
        if (address.isBlank()) {
            runCatching { CloudAccountRepository.linkedWallet() }
                .onSuccess { cloudAddress ->
                    if (cloudAddress.isNotBlank()) address = cloudAddress
                }
        }
        var lastCloudWalletAttempt = 0L
        while (true) {
            val connectedAddress = AppKit.getAccount()?.address.orEmpty()
            if (connectedAddress.isNotBlank()) {
                address = connectedAddress
            } else if (address.isBlank() && System.currentTimeMillis() - lastCloudWalletAttempt >= 15_000L) {
                lastCloudWalletAttempt = System.currentTimeMillis()
                runCatching { CloudAccountRepository.linkedWallet() }
                    .onSuccess { cloudAddress ->
                        if (cloudAddress.isNotBlank()) address = cloudAddress
                    }
            }
            scannerEnabled = AutoTradingStore.isEnabled(context)
            scannerProgress = ScannerProgressStore.load(context)
            optimisticActiveCount = ActiveHyperliquidPositionStore.count(context)
            optimisticLongCount = ActiveHyperliquidPositionStore.longCount(context)
            optimisticShortCount = ActiveHyperliquidPositionStore.shortCount(context)
            val latestExecutionSettings = SignalExecutionSettingsStore.load(context)
            if (latestExecutionSettings != executionSettings) {
                executionSettings = latestExecutionSettings
                maxActiveTradesText = latestExecutionSettings.maxActiveTrades.toString()
                maxActiveTradesSlider = latestExecutionSettings.maxActiveTrades.toFloat()
            }
            dcaSettings = DcaBotSettingsStore.load(context)
            delay(1_000)
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
            runCatching { closeClient.health(LocalTradingGatewayStore.url(context)) }
                .onSuccess { health ->
                    if (health.tradingEnabled != AutoTradingStore.isEnabled(context)) {
                        AutoTradingStore.setEnabled(context, health.tradingEnabled)
                        scannerEnabled = health.tradingEnabled
                    }
                }
            delay(10_000)
        }
    }

    LaunchedEffect(address) {
        if (address.isBlank()) {
            overview = null
            loading = false
            return@LaunchedEffect
        }
        while (true) {
            loading = overview == null
            runCatching { repository.load(address) }
                .onSuccess {
                    overview = it
                    WalletOverviewCache.put(address, it)
                    if (activeStrategy.id == "strategy_3") {
                        scope.launch {
                            runCatching { closeClient.dcaDeals(LocalTradingGatewayStore.url(context)) }
                                .onSuccess { deals -> DcaDealStore.syncFromCloud(context, deals) }
                        }
                    }
                    if (activeStrategy.id == "strategy_3") {
                        scope.launch {
                            runCatching {
                                if (scannerEnabled) closeClient.evaluateTradingCycle(LocalTradingGatewayStore.url(context), it.portfolioValue)
                                else closeClient.tradingCycleStatus(LocalTradingGatewayStore.url(context), it.portfolioValue)
                            }
                                .onSuccess { cycle ->
                                    TradingCycleStore.syncFromCloud(context, cycle)
                                    if (cycle.targetReached) {
                                        TradingCycleStore.lockAtTarget(context)
                                        AutoTradingStore.setEnabled(context, false)
                                        scannerEnabled = false
                                        closeMessage = "Portfoliodoel bereikt · alle posities gesloten · start Scan & Buy handmatig voor een nieuwe cyclus."
                                    }
                                }
                        }
                    }
                    val positions = it.account.assetPositions
                    ensureExternalPositionsTracked(context, positions, it.recentFills)
                    syncPersistentTradeDetails(context, positions, it.recentFills)
                    ProfitableTradeClosureNotifier.reconcile(
                        context,
                        positions.map { asset -> asset.position.coin.uppercase() }.toSet(),
                        it.recentFills
                    )
                    ActiveHyperliquidPositionStore.update(
                        context,
                        longCount = positions.count { asset -> (asset.position.signedSize.toDoubleOrNull() ?: 0.0) > 0.0 },
                        shortCount = positions.count { asset -> (asset.position.signedSize.toDoubleOrNull() ?: 0.0) < 0.0 },
                        symbols = positions.map { asset -> asset.position.coin.uppercase() }.toSet()
                    )
                    AddOnTradeStore.retainOpen(context, positions.map { it.position.coin.uppercase() }.toSet())
                    error = null
                    refreshDelayMs = 15_000L
                }
                .onFailure {
                    error = if (overview == null) {
                        it.message ?: "Posities konden niet worden geladen."
                    } else {
                        "Hyperliquid is tijdelijk druk. De laatst geladen posities blijven zichtbaar; opnieuw proberen over ${refreshDelayMs / 1_000} seconden."
                    }
                    refreshDelayMs = (refreshDelayMs * 2).coerceAtMost(60_000L)
                }
            loading = false
            delay(refreshDelayMs)
        }
    }

    LaunchedEffect(scannerEnabled, scannerProgress.phase, scannerProgress.updatedAt, overview?.account?.assetPositions?.size, dcaSettings.maxActiveDeals) {
        while (scannerEnabled && activeStrategy.id == "strategy_3") {
            val confirmedOpen = overview?.account?.assetPositions?.count {
                (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0
            } ?: 0
            if (ScannerContinuityPolicy.shouldRestart(
                    enabled = scannerEnabled,
                    phase = scannerProgress.phase,
                    updatedAt = scannerProgress.updatedAt,
                    now = System.currentTimeMillis(),
                    activeDeals = confirmedOpen,
                    maximumDeals = dcaSettings.maxActiveDeals
                )
            ) {
                BackgroundScannerScheduler.runNow(context)
            }
            delay(15_000L)
        }
    }

    LaunchedEffect(overview?.account?.assetPositions?.joinToString { it.position.coin }) {
        while (overview != null) {
            val profile = ConsensusProfileStore.load(context)
            val open = overview?.account?.assetPositions.orEmpty().map { it.position.coin.uppercase() }.toSet()
            val eligibleTrades = TradeHistoryStore.load(context).filter {
                it.closedAt == null && it.symbol.uppercase() in open && !AddOnTradeStore.hasAdded(context, it.symbol)
            }.distinctBy { DcaPulseGate.normalizedBaseSymbol(it.symbol) }
            addOnAnalysisTotal = eligibleTrades.size
            addOnAnalysisCompleted = 0
            val results = mutableMapOf<String, AdvisorEngine.AddOnAssessment>()
            eligibleTrades.chunked(4).forEach { group ->
                val assessed = coroutineScope {
                    group.map { trade ->
                        async {
                            val assessment = runCatching {
                                advisorEngine.assessAddOn(trade, profile.minimumWinRate, profile.minimumScore)
                            }.getOrNull() ?: AdvisorEngine.AddOnAssessment(false, 0.0, 0.0, 0.0, "Analyse tijdelijk niet beschikbaar.")
                            trade.symbol.uppercase() to assessment
                        }
                    }.awaitAll()
                }
                results.putAll(assessed)
                addOnAnalysisCompleted = results.size
                addOnAssessments = results.toMap()
            }
            delay(15 * 60_000L)
        }
    }

    LazyColumn(
        modifier = modifier.fillMaxSize().background(PositionsBg).padding(horizontal = 16.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 18.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Hyperliquid", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.ExtraBold, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.fillMaxWidth())
                    Text("Werkelijke Hyperliquid-posities · automatisch bijgewerkt", color = PositionsMuted, fontSize = 11.sp)
                }
                Surface(color = Color(0xFF0B332B), shape = RoundedCornerShape(18.dp)) {
                    Text("LIVE ACCOUNT", color = PositionsGreen, fontSize = 9.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp))
                }
            }
            TradeMentorTextButton(
                label = "DCA STRATEGY SETTINGS",
                onClick = onOpenStrategySettings,
                modifier = Modifier.fillMaxWidth(),
                color = PositionsBlue,
                fontSize = 10.sp,
                fontWeight = FontWeight.Bold,
            )
            Surface(
                onClick = {
                    val requested = !scannerEnabled
                    scope.launch {
                        runCatching {
                            val startedCycle = if (requested && activeStrategy.id == "strategy_3") {
                                val startPortfolio = overview
                                    ?.portfolioValue
                                    ?: error("Portfolio/positions data wordt nog opgehaald. Probeer het zo opnieuw.")
                                closeClient.startTradingCycle(
                                    LocalTradingGatewayStore.url(context),
                                    dcaSettings.portfolioTargetPercentage,
                                    startPortfolio
                                )
                            } else null
                            closeClient.setLiveTrading(LocalTradingGatewayStore.url(context), requested)
                            if (requested && activeStrategy.id != "strategy_3") {
                                val protection = closeClient.protectOpenPositions(
                                    LocalTradingGatewayStore.url(context),
                                    activeProfitTarget,
                                    activeStopLoss,
                                    activeStrategy.id,
                                    takeProfitEnabled = false,
                                    trailingTakeProfitEnabled = false,
                                    stopLossEnabled = false
                                )
                                check(protection.failed.isEmpty() && protection.scanAndBuyEnabled) {
                                    "Niet iedere positie kon veilig met een take-profit worden beschermd."
                                }
                            }
                            startedCycle
                        }.onSuccess { startedCycle ->
                            startedCycle?.let { TradingCycleStore.syncFromCloud(context, it) }
                            AutoTradingStore.setEnabled(context, requested)
                            scannerEnabled = requested
                            if (requested) {
                                BackgroundScannerScheduler.runNow(context)
                            }
                        }.onFailure { failure ->
                            if (requested) {
                                runCatching {
                                    closeClient.setLiveTrading(LocalTradingGatewayStore.url(context), false)
                                }
                            }
                            AutoTradingStore.setEnabled(context, false)
                            scannerEnabled = false
                            closeMessage = failure.message ?: "Scan & Buy kon niet worden bijgewerkt"
                        }
                    }
                },
                color = if (scannerEnabled) Color(0xFF0B332B) else Color(0xFF171D27),
                shape = RoundedCornerShape(11.dp),
                modifier = Modifier.padding(top = 7.dp).height(122.dp)
            ) {
                Column(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp)) {
                    val now = System.currentTimeMillis()
                    val staleThresholdMs = 90_000L
                    val isMonitoring = scannerProgress.phase == "monitoring"
                    val isRefillWaiting = scannerProgress.phase == "refill_wait"
                    val configuredMonitoringMinutes = (BackgroundScannerScheduler.load(context)?.intervalMinutes ?: 15L).coerceAtLeast(15L)
                    val monitoringLabel = if (isMonitoring) {
                        scannerProgress.summary.ifBlank {
                            "Maximale actieve deals bereikt. Scanner controleert automatisch elke ${configuredMonitoringMinutes} minuten."
                        }
                    } else ""
                    val isScannerRunning = scannerProgress.phase !in setOf("idle", "monitoring", "error") &&
                        now - scannerProgress.updatedAt <= staleThresholdMs
                    val scanLabel = when (scannerProgress.phase) {
                        "account" -> "Account controleren"
                        "protection" -> "Take-profits controleren"
                        "scanning" -> if (scannerProgress.total > 0) {
                            "Scannen ${scannerProgress.completed}/${scannerProgress.total} · ${(scannerProgress.fraction * 100).toInt()}%"
                        } else "Markten scannen"
                        "refill_wait" -> scannerProgress.summary.ifBlank { "Automatische vervolgscan wordt voorbereid" }
                        "error" -> "Veilig gestopt · controle nodig"
                        else -> if (scannerEnabled) scannerProgress.summary.ifBlank { "Ruststand · automatische controle actief" } else "Tik om automatisch handelen te starten"
                    }
                    val baseScanLabel = when {
                        isMonitoring -> monitoringLabel.ifBlank { "Maximale actieve deals bereikt. Scanner controleert automatisch." }
                        isRefillWaiting -> scannerProgress.summary.ifBlank { "Automatische vervolgscan wordt voorbereid" }
                        !scannerEnabled -> "Tik om automatisch handelen te starten"
                        isScannerRunning -> scanLabel
                        scannerProgress.phase == "scanning" -> "Scannerstatus verlopen · automatische herstart wordt voorbereid"
                        else -> "Ruststand · automatische controle actief"
                    }
                    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            if (isMonitoring) "○  SCAN & BUY · PAUZE" else if (scannerEnabled) "●  SCAN & BUY · AAN" else "○  SCAN & BUY · UIT",
                            color = if (isMonitoring || scannerEnabled) PositionsGreen else PositionsMuted,
                            fontSize = 10.sp,
                            fontWeight = FontWeight.Black,
                            modifier = Modifier.weight(1f)
                        )
                        Text(baseScanLabel, color = PositionsMuted, fontSize = 8.sp, maxLines = 2)
                    }
                    if (scannerEnabled && !isScannerRunning && !isMonitoring && !isRefillWaiting) {
                        Text(
                            "Automatische controle actief",
                            modifier = Modifier.align(Alignment.End).padding(top = 6.dp),
                            color = PositionsGreen,
                            fontSize = 9.sp,
                            fontWeight = FontWeight.ExtraBold
                        )
                    }
                    if (scannerEnabled && isScannerRunning) {
                        LinearProgressIndicator(
                            progress = { if (scannerProgress.total > 0) scannerProgress.fraction else 0f },
                            modifier = Modifier.fillMaxWidth().padding(top = 6.dp).height(4.dp),
                            color = PositionsGreen,
                            trackColor = Color(0xFF243142)
                        )
                    }
                }
            }
        }

        if (address.isBlank()) {
            item {
                Surface(color = PositionsCard, shape = RoundedCornerShape(20.dp)) {
                    Column(Modifier.fillMaxWidth().padding(20.dp), horizontalAlignment = Alignment.CenterHorizontally) {
                        Text("Koppel eerst je wallet", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        Text("Daarna verschijnen hier uitsluitend je echte Hyperliquid-posities.", color = PositionsMuted, fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
                        Spacer(Modifier.height(15.dp))
                        TradeMentorPrimaryButton(
                            label = "Wallet koppelen",
                            onClick = onOpenWallet,
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                }
            }
        } else {
            val cycleStartedAt = TradingCycleStore.startedAt(context)
            val trackedHistory = TradeHistoryStore.load(context)
            val completedHistory = (trackedHistory + LiveOutcomeLedger.loadCompleted(context))
                .filter { it.outcome != TradeOutcome.Pending }
                .distinctBy { it.id }
                .sortedByDescending { it.closedAt ?: it.expiresAt }
            val cycleCompletedHistory = completedHistory.filter { it.startedAt >= cycleStartedAt }
            val wonTrades = cycleCompletedHistory.count { it.outcome == TradeOutcome.Succeeded || it.lateTargetReachedAt != null }
            val lostTrades = cycleCompletedHistory.count { it.outcome == TradeOutcome.Failed && it.lateTargetReachedAt == null }
            val confirmedActiveTrades = overview?.account?.assetPositions?.count {
                (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0
            } ?: 0
            val activeTrades = maxOf(confirmedActiveTrades, optimisticActiveCount)
            val openSymbols = overview?.account?.assetPositions.orEmpty()
                .filter { (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0 }
                .map { DcaPulseGate.normalizedBaseSymbol(it.position.coin) }
                .toSet()
            val dcaDeals = DcaDealStore.load(context).filter { DcaPulseGate.normalizedBaseSymbol(it.symbol) in openSymbols }
            val dcaAddOnCount = dcaDeals.sumOf { it.safetyOrdersCompleted }
            val confirmedLongTrades = overview?.account?.assetPositions?.count {
                (it.position.signedSize.toDoubleOrNull() ?: 0.0) > 0.0
            } ?: 0
            val longTrades = maxOf(confirmedLongTrades, optimisticLongCount)
            val confirmedShortTrades = overview?.account?.assetPositions?.count {
                (it.position.signedSize.toDoubleOrNull() ?: 0.0) < 0.0
            } ?: 0
            val shortTrades = maxOf(confirmedShortTrades, optimisticShortCount)
            val dcaCapacity = DcaCapacityPolicy.fromPositionCounts(
                longCount = longTrades,
                shortCount = shortTrades,
                maximumDeals = dcaSettings.maxActiveDeals
            )
            val activeDcaDeals = dcaCapacity.activeDeals
            val successRate = if (wonTrades + lostTrades == 0) 0.0 else wonTrades * 100.0 / (wonTrades + lostTrades)
            overview?.let { data ->
                item {
                    val crossAccountValue = data.account.crossMarginSummary.accountValue.toDoubleOrNull() ?: 0.0
                    val riskAccountValue = if (
                        data.accountMode == "unifiedAccount" || data.accountMode == "portfolioMargin"
                    ) data.portfolioValue else crossAccountValue
                    val maintenanceMargin = data.account.crossMaintenanceMarginUsed.toDoubleOrNull() ?: 0.0
                    val riskPercentage = if (riskAccountValue > 0.0) {
                        (maintenanceMargin / riskAccountValue * 100.0).coerceIn(0.0, 100.0)
                    } else 0.0
                    Surface(color = Color(0xFF0D2140), shape = RoundedCornerShape(18.dp)) {
                        Row(
                            Modifier.fillMaxWidth().padding(horizontal = 15.dp, vertical = 13.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text("PORTFOLIO VALUE", color = Color(0xFF8EB2FF), fontSize = 9.sp, fontWeight = FontWeight.ExtraBold)
                                Text(usdPosition(data.portfolioValue), color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Black)
                            }
                            RiskGauge(riskPercentage, Modifier.weight(0.95f))
                            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                                Text("AVAILABLE TO TRADE", color = PositionsGreen, fontSize = 9.sp, fontWeight = FontWeight.ExtraBold)
                                Text(usdPosition(data.availableToTrade), color = PositionsGreen, fontSize = 22.sp, fontWeight = FontWeight.Black)
                            }
                        }
                    }
                }
                if (activeStrategy.id == "strategy_3") item {
                    val startValue = TradingCycleStore.startPortfolioValue(context)
                    val targetPercentage = TradingCycleStore.targetPercentage(context)
                    val targetValue = startValue * (1.0 + targetPercentage / 100.0)
                    val currentPortfolioValue = data.portfolioValue
                    val growthPercentage = if (startValue > 0.0) (currentPortfolioValue - startValue) / startValue * 100.0 else 0.0
                    val progress = if (targetPercentage > 0.0) (growthPercentage / targetPercentage).coerceIn(0.0, 1.0) else 0.0
                    val longValue = data.account.assetPositions.filter { (it.position.signedSize.toDoubleOrNull() ?: 0.0) > 0.0 }
                        .sumOf { kotlin.math.abs(it.position.positionValue.toDoubleOrNull() ?: 0.0) }
                    val shortValue = data.account.assetPositions.filter { (it.position.signedSize.toDoubleOrNull() ?: 0.0) < 0.0 }
                        .sumOf { kotlin.math.abs(it.position.positionValue.toDoubleOrNull() ?: 0.0) }
                    Surface(color = Color(0xFF101A2A), shape = RoundedCornerShape(18.dp)) {
                        Column(Modifier.fillMaxWidth().padding(14.dp)) {
                            Text("DCA PORTFOLIOCYCLUS", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
                            Row(Modifier.fillMaxWidth().padding(top = 9.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                                Column { Text("START", color = PositionsMuted, fontSize = 8.sp); Text(usdPosition(startValue), color = Color.White, fontWeight = FontWeight.Bold) }
                                Column(horizontalAlignment = Alignment.CenterHorizontally) { Text("HUIDIG", color = PositionsMuted, fontSize = 8.sp); Text(usdPosition(currentPortfolioValue), color = Color.White, fontWeight = FontWeight.Bold) }
                                Column(horizontalAlignment = Alignment.End) { Text("DOEL +${String.format(Locale.US, "%.1f", targetPercentage)}%", color = PositionsMuted, fontSize = 8.sp); Text(usdPosition(targetValue), color = PositionsGreen, fontWeight = FontWeight.Bold) }
                            }
                            LinearProgressIndicator(progress = { progress.toFloat() }, modifier = Modifier.fillMaxWidth().padding(top = 10.dp), color = PositionsGreen, trackColor = Color(0xFF243142))
                            Text("Nog ${usdPosition((targetValue - currentPortfolioValue).coerceAtLeast(0.0))} · ${String.format(Locale.US, "%.2f", growthPercentage)}% groei", color = PositionsMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 5.dp))
                            Row(Modifier.fillMaxWidth().padding(top = 9.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                                Text("LONG $longTrades · ${usdPosition(longValue)}", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                                Text("SHORT $shortTrades · ${usdPosition(shortValue)}", color = PositionsRed, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                }
            }
            item {
                val rotation by animateFloatAsState(if (performanceFlipped) 180f else 0f, tween(420), label = "performanceFlip")
                Surface(
                    color = Color(0xFF0D2140),
                    shape = RoundedCornerShape(18.dp),
                    modifier = Modifier.fillMaxWidth().height(150.dp).graphicsLayer {
                        rotationY = rotation
                        cameraDistance = 14f * density
                    }.then(if (activeStrategy.id == "strategy_3") Modifier.clickable { performanceFlipped = !performanceFlipped } else Modifier)
                ) performanceCard@{
                    if (!performanceFlipped) {
                        Column(Modifier.fillMaxWidth().padding(14.dp)) {
                            Text(if (activeStrategy.id == "strategy_3") "DCA PULSE · $activeDcaDeals/${dcaSettings.maxActiveDeals} ACTIEVE DEALS" else "PRESTATIES", color = Color(0xFF8EB2FF), fontSize = 10.sp, fontWeight = FontWeight.Bold)
                            if (activeStrategy.id == "strategy_3" && dcaCapacity.overLimitDeals > 0) {
                                Text(
                                    "${dcaCapacity.overLimitDeals} boven de ingestelde limiet · scanner koopt niet bij",
                                    color = PositionsRed,
                                    fontSize = 9.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                            val displayedMaximum = if (activeStrategy.id == "strategy_2") QuantumShieldCapacityCalculator.calculate(
                                activeTrades = activeTrades,
                                portfolioValue = overview?.portfolioValue ?: 0.0,
                                availableToTrade = overview?.availableToTrade ?: 0.0,
                                maintenanceMargin = overview?.account?.crossMaintenanceMarginUsed?.toDoubleOrNull() ?: 0.0,
                                positionSizeUsd = executionSettings.positionSizeUsd,
                                stopLossPercentage = minOf(activeProfile.stopLoss, 1.5)
                            ) else if (activeStrategy.id == "strategy_3") dcaSettings.maxActiveDeals else executionSettings.maxActiveTrades
                            Row(Modifier.fillMaxWidth().padding(top = 9.dp), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                PositionStat(if (activeStrategy.id == "strategy_2") "Actief / auto" else "Actief / max", "${if (activeStrategy.id == "strategy_3") activeDcaDeals else activeTrades} / $displayedMaximum", PositionsBlue, Modifier.weight(1f)) { performanceFlipped = true }
                                PositionStat("LONG", longTrades.toString(), PositionsGreen, Modifier.weight(1f))
                                PositionStat("SHORT", shortTrades.toString(), PositionsRed, Modifier.weight(1f))
                            }
                            Row(Modifier.fillMaxWidth().padding(top = 7.dp), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                                PositionStat("Afgerond", "$wonTrades WIN", PositionsGreen, Modifier.weight(1f))
                                PositionStat("Doel niet op tijd", "$lostTrades LATE", PositionsRed, Modifier.weight(1f))
                                PositionStat("Resultaat", if (wonTrades + lostTrades == 0) "— SCORE" else String.format(Locale.US, "%.0f%% SCORE", successRate), Color(0xFFFFC857), Modifier.weight(1f))
                            }
                        }
                    } else {
                        val data = overview
                        if (activeStrategy.id == "strategy_2") {
                            val automaticMaximum = QuantumShieldCapacityCalculator.calculate(
                                activeTrades, data?.portfolioValue ?: 0.0, data?.availableToTrade ?: 0.0,
                                data?.account?.crossMaintenanceMarginUsed?.toDoubleOrNull() ?: 0.0,
                                executionSettings.positionSizeUsd, minOf(activeProfile.stopLoss, 1.5)
                            )
                            Column(Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(14.dp)) {
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Column(Modifier.weight(1f)) {
                                        Text("QUANTUM AUTO-LIMIET · $automaticMaximum TRADES", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                                        Text("Automatisch bepaald uit vermogen, vrije marge, instapbedrag en liquidatierisico.", color = PositionsMuted, fontSize = 8.sp)
                                    }
                                    TradeMentorTextButton(
                                        label = "Terug",
                                        onClick = { performanceFlipped = false },
                                        color = Color.White
                                    )
                                }
                                Text("Je kunt deze limiet niet handmatig aanpassen zolang Quantum Shield actief is. De limiet wordt bij iedere scan opnieuw veilig berekend.", color = Color.White, fontSize = 10.sp, modifier = Modifier.padding(top = 12.dp))
                            }
                            return@performanceCard
                        }
                        if (activeStrategy.id == "strategy_3") {
                            Column(Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(14.dp)) {
                                Text("DCA PULSE · $activeDcaDeals/${dcaSettings.maxActiveDeals} ACTIEVE DEALS", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                                Text("$dcaAddOnCount DCA-bijkopen uitgevoerd. Bijkopen tellen niet als extra actieve deal.", color = Color.White, fontSize = 10.sp, modifier = Modifier.padding(top = 8.dp))
                                Text("Basis en iedere DCA ${usdPosition(dcaSettings.baseOrderUsd)} · maximaal ${dcaSettings.maxSafetyOrders} bijkopen per pair", color = PositionsMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 6.dp))
                                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                                    TradeMentorTextButton(label = "Instellingen", onClick = { dcaDashboardOpen = true }, modifier = Modifier.weight(1f))
                                    TradeMentorTextButton(label = "Terug", onClick = { performanceFlipped = false }, modifier = Modifier.weight(1f))
                                }
                            }
                            return@performanceCard
                        }
                        val selectedMaximum = maxActiveTradesSlider.toInt().coerceIn(1, 400)
                        val accountValue = data?.portfolioValue ?: 0.0
                        val maintenance = data?.account?.crossMaintenanceMarginUsed?.toDoubleOrNull() ?: 0.0
                        val entryAmount = executionSettings.positionSizeUsd.coerceAtLeast(10.0)
                        val stressLossPerTrade = entryAmount * (activeProfile.stopLoss.coerceIn(1.0, 50.0) / 100.0)
                        val maintenancePerTrade = entryAmount * 0.05
                        fun projectedRisk(maximum: Int): Double {
                            val additions = (maximum - activeTrades).coerceAtLeast(0)
                            val stressedValue = accountValue - additions * stressLossPerTrade
                            return if (stressedValue > 0.0) {
                                ((maintenance + additions * maintenancePerTrade) / stressedValue * 100.0).coerceIn(0.0, 100.0)
                            } else 100.0
                        }
                        val capitalMaximum = activeTrades + ((data?.availableToTrade ?: 0.0) / entryAmount).toInt()
                        val recommendedMaximum = (activeTrades..minOf(400, capitalMaximum.coerceAtLeast(activeTrades)))
                            .takeWhile { projectedRisk(it) < 30.0 }
                            .lastOrNull() ?: activeTrades
                        val selectedRisk = projectedRisk(selectedMaximum)
                        val selectedColor = when {
                            selectedRisk < 30.0 -> PositionsGreen
                            selectedRisk < 40.0 -> Color(0xFFFFD166)
                            selectedRisk < 50.0 -> Color(0xFFFF9F43)
                            else -> PositionsRed
                        }
                        fun saveMaximum(maximum: Int) {
                            val safeMaximum = maximum.coerceIn(activeTrades.coerceAtLeast(1), 400)
                            executionSettings = executionSettings.copy(maxActiveTrades = safeMaximum)
                            maxActiveTradesText = safeMaximum.toString()
                            maxActiveTradesSlider = safeMaximum.toFloat()
                            SignalExecutionSettingsStore.save(context, executionSettings)
                            scope.launch {
                                runCatching { closeClient.syncMaximum(LocalTradingGatewayStore.url(context), "", safeMaximum) }
                            }
                            if (AutoTradingStore.isEnabled(context) && safeMaximum > activeTrades) {
                                BackgroundScannerScheduler.runNow(context)
                            }
                        }
                        Column(Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(14.dp)) {
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text("GROEILIMIET · $selectedMaximum TRADES", color = selectedColor, fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                                    Text("Verwachte risicoscore vol: ${String.format(Locale.US, "%.1f%%", selectedRisk)} · advies $recommendedMaximum", color = PositionsMuted, fontSize = 8.sp)
                                }
                                TradeMentorTextButton(
                                    label = "Terug",
                                    onClick = { performanceFlipped = false },
                                    color = Color.White
                                )
                            }
                            Slider(
                                value = maxActiveTradesSlider,
                                onValueChange = { maxActiveTradesSlider = it },
                                onValueChangeFinished = { saveMaximum(maxActiveTradesSlider.toInt()) },
                                valueRange = activeTrades.coerceAtLeast(1).toFloat()..minOf(150, activeTrades + 80).coerceAtLeast(activeTrades + 1).toFloat(),
                                modifier = Modifier.height(28.dp)
                            )
                            Box(
                                Modifier.fillMaxWidth().height(8.dp).background(
                                    Brush.horizontalGradient(listOf(PositionsGreen, Color(0xFFFFD166), Color(0xFFFF9F43), PositionsRed)),
                                    RoundedCornerShape(8.dp)
                                )
                            )
                            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                Text("$activeTrades actief · \$${String.format(Locale.US, "%.0f", entryAmount)} per instap", color = PositionsMuted, fontSize = 8.sp, modifier = Modifier.weight(1f))
                                TradeMentorTextButton(
                                    label = "Gebruik veilig advies",
                                    onClick = { saveMaximum(recommendedMaximum) },
                                    modifier = Modifier.height(30.dp),
                                    fontSize = 9.sp,
                                    fontWeight = FontWeight.Bold,
                                    color = PositionsGreen
                                )
                            }
                        }
                    }
                }
            }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    PositionView.entries.forEach { option ->
                        val selected = positionView == option
                        PositionTab(option.label, selected, Modifier.weight(1f)) { positionView = option }
                    }
                }
            }
            item {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
                    if (positionView == PositionView.Active) {
                        Surface(
                            onClick = {
                                if (!takeAllProfitsBusy) {
                                    takeAllProfitsBusy = true
                                    scope.launch {
                                        runCatching {
                                            closeClient.previewTakeAllProfits(LocalTradingGatewayStore.url(context))
                                        }.onSuccess { takeAllProfitsPreview = it }
                                            .onFailure { closeMessage = it.message ?: "Winstposities konden niet worden gecontroleerd" }
                                        takeAllProfitsBusy = false
                                    }
                                }
                            },
                            color = Color(0xFF0B332B),
                            shape = RoundedCornerShape(11.dp),
                            modifier = Modifier.weight(1f)
                        ) {
                            Text(
                                if (takeAllProfitsBusy) "CONTROLERENâ€¦" else "TAKE ALL PROFITS",
                                color = PositionsGreen,
                                fontSize = 9.sp,
                                fontWeight = FontWeight.ExtraBold,
                                modifier = Modifier.padding(horizontal = 12.dp, vertical = 11.dp)
                            )
                        }
                    } else Spacer(Modifier.weight(1f))
                    Box(contentAlignment = Alignment.CenterEnd) {
                    Surface(
                        onClick = { filterMenuExpanded = true },
                        color = Color(0xFF0D1522),
                        shape = RoundedCornerShape(11.dp)
                    ) {
                        Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                            Text("Sortering  ", color = PositionsMuted, fontSize = 9.sp)
                            Text(when { addOnOpportunitiesOnly -> "Bijkoopkansen"; nearAddOnOpportunitiesOnly -> "Bijna bijkoopkans"; else -> positionSort.label }, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                            Text("  ⋮", color = PositionsBlue, fontSize = 16.sp, fontWeight = FontWeight.Black)
                        }
                    }
                    DropdownMenu(expanded = filterMenuExpanded, onDismissRequest = { filterMenuExpanded = false }) {
                        DropdownMenuItem(text = { Text("Dichtst bij profitdoel") }, onClick = {
                            positionSort = PositionSort.ClosestTarget; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Hoogste profit") }, onClick = {
                            positionSort = PositionSort.Profit; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Grootste verlies") }, onClick = {
                            positionSort = PositionSort.Loss; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Langste open") }, onClick = {
                            positionSort = PositionSort.Duration; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Meest recent") }, onClick = {
                            positionSort = PositionSort.Newest; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Grootste positie ($)") }, onClick = {
                            positionSort = PositionSort.PositionSize; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Hoogste leverage") }, onClick = {
                            positionSort = PositionSort.Leverage; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Dichtst bij liquidatie") }, onClick = {
                            positionSort = PositionSort.Liquidation; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Alleen bijkoopkansen") }, onClick = {
                            positionSort = PositionSort.Profit; addOnOpportunitiesOnly = true; nearAddOnOpportunitiesOnly = false; filterMenuExpanded = false
                        })
                        DropdownMenuItem(text = { Text("Bijna bijkoopkans") }, onClick = {
                            positionSort = PositionSort.Profit; addOnOpportunitiesOnly = false; nearAddOnOpportunitiesOnly = true; filterMenuExpanded = false
                        })
                    }
                    }
                }
            }
            if (positionView == PositionView.Active) item {
                val approvedCount = addOnAssessments.values.count { it.approved }
                val nearCount = addOnAssessments.values.count { !it.approved && it.winRate >= 70.0 && it.qualityScore >= 60.0 }
                val analyzing = addOnAnalysisCompleted < addOnAnalysisTotal
                Surface(color = Color(0xFF0D1522), shape = RoundedCornerShape(11.dp)) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                        if (activeStrategy.id != "strategy_3" && analyzing) CircularProgressIndicator(color = PositionsBlue, modifier = Modifier.size(15.dp), strokeWidth = 2.dp)
                        Text(
                            if (activeStrategy.id == "strategy_3") {
                                "DCA-controle $activeDcaDeals/$activeDcaDeals actieve deals · $dcaAddOnCount bijkopen uitgevoerd"
                            } else {
                                "  Bijkoopanalyse ${addOnAnalysisCompleted.coerceAtMost(addOnAnalysisTotal)}/$addOnAnalysisTotal · $approvedCount goedgekeurd · $nearCount bijna"
                            },
                            color = if (activeStrategy.id == "strategy_3" || approvedCount > 0) PositionsGreen else PositionsMuted,
                            fontSize = 9.sp,
                            fontWeight = FontWeight.Bold
                        )
                    }
                }
            }
            if (loading) item {
                Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
                    CircularProgressIndicator(color = PositionsBlue, modifier = Modifier.height(22.dp), strokeWidth = 2.dp)
                    Text(" Echte posities ophalen…", color = Color.White)
                }
            }
            error?.let { message -> item { Surface(color = Color(0xFF35151D), shape = RoundedCornerShape(16.dp)) { Text(message, color = Color(0xFFFF8A9D), modifier = Modifier.padding(15.dp)) } } }
            if (positionView != PositionView.Active) {
                val filteredHistory = completedHistory.filter { trade ->
                    when (positionView) {
                        PositionView.Succeeded -> trade.outcome == TradeOutcome.Succeeded || trade.lateTargetReachedAt != null
                        PositionView.Expired -> trade.outcome == TradeOutcome.Failed && trade.lateTargetReachedAt == null
                        PositionView.Active -> false
                    }
                }
                val history = when (positionSort) {
                    PositionSort.Duration -> filteredHistory.sortedByDescending { (it.closedAt ?: it.adviceUpdatedAt ?: it.expiresAt) - it.startedAt }
                    PositionSort.Newest -> filteredHistory.sortedByDescending { it.closedAt ?: it.lateTargetReachedAt ?: it.adviceUpdatedAt ?: 0L }
                    PositionSort.PositionSize -> filteredHistory.sortedByDescending { kotlin.math.abs(it.positionValueUsd ?: 0.0) }
                    PositionSort.Loss -> filteredHistory.sortedBy { it.realizedPnl ?: Double.POSITIVE_INFINITY }
                    PositionSort.Leverage -> filteredHistory.sortedByDescending { it.leverage ?: 0 }
                    PositionSort.Profit, PositionSort.ClosestTarget, PositionSort.Liquidation -> filteredHistory.sortedByDescending { it.realizedPnl ?: Double.NEGATIVE_INFINITY }
                }
                if (history.isEmpty()) item {
                    Box(Modifier.fillMaxWidth().padding(vertical = 65.dp), contentAlignment = Alignment.Center) {
                        Text(when (positionView) {
                            PositionView.Succeeded -> "Nog geen gewonnen trades."
                            PositionView.Expired -> "Nog geen verloren trades."
                            PositionView.Active -> ""
                        }, color = PositionsMuted)
                    }
                } else items(history, key = { "history-${it.id}" }) { trade ->
                    val livePosition = overview?.account?.assetPositions?.firstOrNull {
                        it.position.coin.equals(trade.symbol, true) &&
                            (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0
                    }?.position
                    val livePnl = livePosition?.unrealizedPnl?.toDoubleOrNull()
                    val displayedPnl = trade.realizedPnl ?: livePnl
                    val isDcaTrade = trade.strategyId == "strategy_3"
                    val dcaOrderLabel = "${trade.dcaSafetyOrdersCompleted + 1} orders · ${trade.dcaSafetyOrdersCompleted}× bijgekocht"
                    val durationEnd = trade.closedAt ?: if (livePosition != null) System.currentTimeMillis() else (trade.adviceUpdatedAt ?: trade.expiresAt)
                    val expanded = false
                    val rotation by animateFloatAsState(if (expanded) 180f else 0f, tween(420), label = "historyFlip")
                    Surface(color = PositionsCard, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth().height(126.dp).graphicsLayer {
                        rotationY = rotation
                        cameraDistance = 14f * density
                    }.clickable {
                        analysisTradeId = trade.id
                        analysisSymbol = trade.symbol
                    }) {
                        if (!expanded) Row(Modifier.fillMaxWidth().padding(horizontal = 13.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(trade.symbol, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold)
                                Text("${if (trade.shortDirection) "SHORT" else "LONG"}${trade.leverage?.let { " · ${it}×" }.orEmpty()}", color = if (trade.shortDirection) PositionsRed else PositionsGreen, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                                Text(
                                    (if (livePosition != null) "Nog actief sinds ${positionDate(trade.startedAt)}" else "Gesloten ${positionDate(trade.closedAt ?: trade.lateTargetReachedAt ?: durationEnd)}") + " · Positie ${usdPosition(kotlin.math.abs(trade.positionSizeUsd))}",
                                    color = PositionsMuted,
                                    fontSize = 8.sp,
                                    maxLines = 1
                                )
                                Text(tradeIndicatorLabel(trade), color = Color(0xFF8EB2FF), fontSize = 11.sp, lineHeight = 13.sp, maxLines = 1, modifier = Modifier.padding(top = 4.dp))
                            }
                            Column(Modifier.weight(0.72f), horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("DUUR", color = PositionsMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                                Text(tradeDuration(trade.startedAt, durationEnd), color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                                if (isDcaTrade) Text(dcaOrderLabel, color = Color(0xFF7DB7FF), fontSize = 9.sp, fontWeight = FontWeight.Black)
                            }
                            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                                Text(displayedPnl?.let(::signedUsdPosition) ?: "Wordt opgehaald", color = if ((displayedPnl ?: 0.0) >= 0.0) PositionsGreen else PositionsRed, fontSize = if (displayedPnl == null) 9.sp else 16.sp, fontWeight = FontWeight.ExtraBold)
                                Text(if (trade.lateTargetReachedAt != null) "LATER BEHAALD" else if (trade.outcome == TradeOutcome.Succeeded) "GESLAAGD" else "BUITEN TERMIJN", color = if (trade.outcome == TradeOutcome.Succeeded || trade.lateTargetReachedAt != null) PositionsGreen else Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                                if (!isDcaTrade) Text("TP ${String.format(Locale.US, "%.2f%%", trade.profitPercentage)}", color = PositionsMuted, fontSize = 9.sp)
                                else Text("Positie ${usdPosition(kotlin.math.abs(trade.positionValueUsd ?: trade.positionSizeUsd))}", color = PositionsMuted, fontSize = 9.sp)
                            }
                        } else Row(
                            Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(horizontal = 13.dp, vertical = 9.dp),
                            verticalAlignment = Alignment.CenterVertically
                        ) {
                            Column(Modifier.weight(1f)) {
                                Text("INSTAP", color = PositionsMuted, fontSize = 7.sp, fontWeight = FontWeight.Bold)
                                Text(pricePosition(trade.entryPrice.toString()), color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                                Text(positionDate(trade.startedAt), color = PositionsMuted, fontSize = 7.sp)
                            }
                            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("DOEL", color = PositionsMuted, fontSize = 7.sp, fontWeight = FontWeight.Bold)
                                Text(String.format(Locale.US, "%.2f%%", trade.profitPercentage), color = Color(0xFFFFC857), fontSize = 12.sp, fontWeight = FontWeight.ExtraBold)
                                Text(tradeDuration(trade.startedAt, durationEnd), color = PositionsMuted, fontSize = 7.sp)
                            }
                            Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                                Text("RESULTAAT", color = PositionsMuted, fontSize = 7.sp, fontWeight = FontWeight.Bold)
                                Text(displayedPnl?.let(::signedUsdPosition) ?: "Wordt opgehaald", color = if ((displayedPnl ?: 0.0) >= 0.0) PositionsGreen else PositionsRed, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                                Text(if (trade.lateTargetReachedAt != null) "Later behaald" else if (trade.outcome == TradeOutcome.Succeeded) "Op tijd behaald" else "Doel loopt door", color = PositionsMuted, fontSize = 7.sp)
                            }
                        }
                    }
                }
            }
            if (positionView == PositionView.Active) overview?.let { data ->
                val unsortedPositions = data.account.assetPositions.filter {
                    (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0 &&
                        (!addOnOpportunitiesOnly || (addOnAssessments[it.position.coin.uppercase()]?.approved == true && !AddOnTradeStore.hasAdded(context, it.position.coin))) &&
                        (!nearAddOnOpportunitiesOnly || addOnAssessments[it.position.coin.uppercase()]?.let { assessment ->
                            !assessment.approved && assessment.winRate >= 70.0 && assessment.qualityScore >= 60.0
                        } == true)
                }
                val positions = when (positionSort) {
                    PositionSort.Duration -> unsortedPositions.sortedBy { asset ->
                        trackedHistory.firstOrNull { it.closedAt == null && it.symbol.equals(asset.position.coin, true) }?.startedAt ?: Long.MAX_VALUE
                    }
                    PositionSort.Profit -> unsortedPositions.sortedByDescending { positionPriceMovePercentage(it.position) }
                    PositionSort.Loss -> unsortedPositions.sortedBy { positionPriceMovePercentage(it.position) }
                    PositionSort.Newest -> unsortedPositions.sortedByDescending { asset ->
                        trackedHistory.firstOrNull { it.closedAt == null && it.symbol.equals(asset.position.coin, true) }?.startedAt ?: 0L
                    }
                    PositionSort.PositionSize -> unsortedPositions.sortedByDescending {
                        kotlin.math.abs(it.position.positionValue.toDoubleOrNull() ?: 0.0)
                    }
                    PositionSort.Leverage -> unsortedPositions.sortedByDescending { it.position.leverage.value }
                    PositionSort.ClosestTarget -> unsortedPositions.sortedByDescending { asset ->
                        val p = asset.position
                        val entry = p.entryPrice?.toDoubleOrNull() ?: 0.0
                        val size = kotlin.math.abs(p.signedSize.toDoubleOrNull() ?: 0.0)
                        if (entry > 0.0 && size > 0.0) (p.unrealizedPnl.toDoubleOrNull() ?: 0.0) / (size * entry) else Double.NEGATIVE_INFINITY
                    }
                    PositionSort.Liquidation -> unsortedPositions.sortedBy { asset ->
                        val p = asset.position
                        val size = kotlin.math.abs(p.signedSize.toDoubleOrNull() ?: 0.0)
                        val current = if (size > 0.0) kotlin.math.abs(p.positionValue.toDoubleOrNull() ?: 0.0) / size else 0.0
                        val liquidation = p.liquidationPrice?.toDoubleOrNull() ?: return@sortedBy Double.POSITIVE_INFINITY
                        if (current > 0.0) kotlin.math.abs(liquidation / current - 1.0) else Double.POSITIVE_INFINITY
                    }
                }
                if (positions.isEmpty()) {
                    item {
                        Box(Modifier.fillMaxWidth().padding(vertical = 70.dp), contentAlignment = Alignment.Center) {
                            Text(when { addOnOpportunitiesOnly -> "Momenteel zijn er geen volledig bevestigde bijkoopkansen."; nearAddOnOpportunitiesOnly -> "Momenteel zijn er geen posities die bijna aan alle bijkoopvoorwaarden voldoen."; else -> "Je hebt momenteel geen echte open posities op Hyperliquid." }, color = PositionsMuted)
                        }
                    }
                } else items(positions, key = { it.position.coin }) { asset ->
                    val position = asset.position
                    val size = position.signedSize.toDoubleOrNull() ?: 0.0
                    val short = size < 0
                    val pnl = position.unrealizedPnl.toDoubleOrNull() ?: 0.0
                    val entryPrice = position.entryPrice?.toDoubleOrNull() ?: 0.0
                    val currentMovePct = positionPriceMovePercentage(position)
                    val targetPrice = if (entryPrice > 0.0) {
                        entryPrice * if (short) 1.0 - activeProfitTarget / 100.0 else 1.0 + activeProfitTarget / 100.0
                    } else 0.0
                    val expanded = false
                    val trackedTrade = trackedHistory.firstOrNull { it.closedAt == null && it.symbol.equals(position.coin, true) }
                    val dcaDeal = if (activeStrategy.id == "strategy_3") DcaDealStore.find(context, position.coin) else null
                    val dcaAdditions = dcaDeal?.safetyOrdersCompleted ?: trackedTrade?.dcaSafetyOrdersCompleted ?: 0
                    val dcaOrderLabel = "${dcaAdditions + 1} orders · ${dcaAdditions}× bijgekocht"
                    val wasAdded = AddOnTradeStore.hasAdded(context, position.coin)
                    val addOn = addOnAssessments[position.coin.uppercase()]
                    val opportunity = addOn?.approved == true && !wasAdded
                    val rotation by animateFloatAsState(if (expanded) 180f else 0f, tween(420), label = "positionFlip")
                    Surface(
                        color = when { wasAdded -> Color(0xFF10243A); opportunity -> Color(0xFF102B25); else -> PositionsCard },
                        shape = RoundedCornerShape(16.dp),
                        modifier = Modifier.fillMaxWidth()
                            .then(if (opportunity) Modifier.border(1.dp, PositionsGreen.copy(alpha = 0.65f), RoundedCornerShape(16.dp)) else Modifier)
                            .then(if (expanded) Modifier else Modifier.height(156.dp)).graphicsLayer {
                            rotationY = rotation
                            cameraDistance = 14f * density
                        }.clickable {
                            analysisTradeId = trackedTrade?.id
                            analysisSymbol = position.coin
                        }
                    ) {
                        if (!expanded) {
                            Row(Modifier.fillMaxWidth().padding(horizontal = 13.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                                Column(Modifier.weight(1f)) {
                                    Text(position.coin, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold)
                                    Text("${if (short) "SHORT" else "LONG"} · ${position.leverage.value}×", color = if (short) PositionsRed else PositionsGreen, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                                    Text(
                                        "${trackedTrade?.let { "Geopend ${positionDate(it.startedAt)}" } ?: "Datum onbekend"} · Positie ${usdPosition(kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0))}",
                                        color = PositionsMuted,
                                        fontSize = 8.sp,
                                    maxLines = 1
                                )
                                    Text(tradeIndicatorLabel(trackedTrade), color = Color(0xFF8EB2FF), fontSize = 11.sp, lineHeight = 13.sp, maxLines = 1, modifier = Modifier.padding(top = 5.dp))
                                }
                                Column(Modifier.weight(0.72f), horizontalAlignment = Alignment.CenterHorizontally) {
                                    Text("DUUR", color = PositionsMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                                    Text(trackedTrade?.let { tradeDuration(it.startedAt, System.currentTimeMillis()) } ?: "—", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                                    if (activeStrategy.id == "strategy_3") {
                                        Text(dcaOrderLabel, color = Color(0xFF7DB7FF), fontSize = 11.sp, lineHeight = 13.sp, maxLines = 2, fontWeight = FontWeight.Black)
                                    } else when {
                                        wasAdded -> Text("1× BIJGEKOCHT", color = Color(0xFF7DB7FF), fontSize = 9.sp, fontWeight = FontWeight.Black)
                                    opportunity -> TradeMentorTextButton(
                                        onClick = { addOnRequest = position.coin to addOn!! },
                                        modifier = Modifier.height(25.dp),
                                        fontSize = 9.sp,
                                        fontWeight = FontWeight.Black
                                    ) { Text("+ 1×", fontSize = 9.sp, fontWeight = FontWeight.Black) }
                                    }
                                }
                                Column(Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                                    Text(signedUsdPosition(pnl), color = if (pnl >= 0) PositionsGreen else PositionsRed, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold)
                                    Text("PRIJS ${String.format(Locale.US, "%+.2f%%", currentMovePct)}", color = if (currentMovePct >= 0) PositionsGreen else PositionsRed, fontSize = 9.sp, fontWeight = FontWeight.Bold)
                                    if (activeStrategy.id != "strategy_3") {
                                        Text("TP ${String.format(Locale.US, "%.2f%%", activeProfitTarget)} · ${pricePosition(targetPrice.toString())}", color = PositionsMuted, fontSize = 9.sp)
                                    } else {
                                        Text("Totaal ${usdPosition(kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0))}", color = PositionsMuted, fontSize = 9.sp)
                                    }
                                    Surface(
                                        onClick = {
                                            closeRequest = ManualCloseRequest(
                                                symbol = position.coin,
                                                pnl = pnl,
                                                positionValue = kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0),
                                                shortDirection = short
                                            )
                                        },
                                        color = PositionsRed.copy(alpha = 0.16f),
                                        shape = RoundedCornerShape(9.dp),
                                        modifier = Modifier.padding(top = 4.dp)
                                    ) {
                                        Text(
                                            "💰  SLUIT",
                                            color = PositionsRed,
                                            fontSize = 9.sp,
                                            fontWeight = FontWeight.ExtraBold,
                                            modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp)
                                        )
                                    }
                                }
                            }
                        } else {
                            Column(Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(15.dp)) {
                                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                                    Text(position.coin, color = Color.White, fontSize = 21.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f))
                                    Text(if (short) "SHORT" else "LONG", color = if (short) PositionsRed else PositionsGreen, fontWeight = FontWeight.Bold)
                                }
                                Text("${kotlin.math.abs(size)} ${position.coin} · ${position.leverage.value}× ${position.leverage.type}", color = PositionsMuted, fontSize = 11.sp)
                                Spacer(Modifier.height(9.dp))
                                PositionRow("Ongerealiseerde PNL", signedUsdPosition(pnl), if (pnl >= 0) PositionsGreen else PositionsRed)
                                PositionRow("Rendement", String.format(Locale.US, "%+.2f%%", (position.returnOnEquity.toDoubleOrNull() ?: 0.0) * 100.0), if (pnl >= 0) PositionsGreen else PositionsRed)
                                PositionRow("Instapprijs", pricePosition(position.entryPrice))
                                PositionRow("Positiewaarde", usdPosition(position.positionValue.toDoubleOrNull() ?: 0.0))
                                PositionRow("Marge gebruikt", usdPosition(position.marginUsed.toDoubleOrNull() ?: 0.0))
                                PositionRow("Liquidatieprijs", pricePosition(position.liquidationPrice))
                                if (activeStrategy.id != "strategy_3") {
                                    PositionRow("Ingestelde take-profit", "${String.format(Locale.US, "%.2f%%", activeProfitTarget)} · ${pricePosition(targetPrice.toString())}", Color(0xFFFFC857))
                                } else {
                                    PositionRow("DCA-orders", dcaOrderLabel, Color(0xFF7DB7FF))
                                }
                                PositionRow("Bijkoopanalyse", addOn?.reason ?: if (wasAdded) "Deze positie is al één keer bijgekocht." else "Wacht op heranalyse.", if (addOn?.approved == true) PositionsGreen else PositionsMuted)
                                if (wasAdded) PositionRow("Bijkoopstatus", "1× BIJGEKOCHT", Color(0xFF7DB7FF))
                                else if (opportunity) PositionRow("Heranalyse", "BIJKOOPKANS · ${String.format(Locale.US, "%.0f%%", addOn!!.winRate)}", PositionsGreen)
                                TradeMentorPrimaryButton(
                                    label = "Positie nu handmatig sluiten",
                                    onClick = {
                                        closeRequest = ManualCloseRequest(
                                            symbol = position.coin,
                                            pnl = pnl,
                                            positionValue = kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0),
                                            shortDirection = short
                                        )
                                    },
                                    modifier = Modifier.fillMaxWidth().padding(top = 9.dp)
                                )
                            }
                        }
                    }
                }
            }
        }
    }
    closeMessage?.let { message ->
        Surface(color = PositionsCard, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(16.dp)) {
            Text(message, color = Color.White, modifier = Modifier.padding(12.dp))
        }
    }
    if (dcaDashboardOpen) {
        DcaSettingsDashboard(
            initial = dcaSettings,
            onDismiss = { dcaDashboardOpen = false },
            onSave = saveDca@ { updated ->
                val currentTarget = TradingCycleStore.targetPercentage(context)
                if (TradingCycleStore.startedAt(context) > 0L && !TradingCycleStore.isLocked(context) && updated.portfolioTargetPercentage < currentTarget) {
                    closeMessage = "Tijdens een actieve DCA-cyclus kan het portfoliodoel alleen worden verhoogd."
                    return@saveDca
                }
                DcaBotSettingsStore.save(context, updated)
                dcaSettings = updated
                if (AutoTradingStore.isEnabled(context) &&
                    updated.maxActiveDeals > ActiveHyperliquidPositionStore.count(context)
                ) {
                    BackgroundScannerScheduler.runNow(context)
                }
                if (TradingCycleStore.startedAt(context) > 0L && !TradingCycleStore.isLocked(context)) {
                    TradingCycleStore.updateTarget(context, updated.portfolioTargetPercentage)
                    scope.launch {
                        runCatching { closeClient.updateTradingCycleTarget(LocalTradingGatewayStore.url(context), updated.portfolioTargetPercentage) }
                            .onFailure { closeMessage = it.message ?: "Portfoliodoel kon niet worden bijgewerkt" }
                    }
                }
                dcaDashboardOpen = false
                closeMessage = "DCA Pulse-instellingen opgeslagen."
            }
        )
    }
    analysisSymbol?.let { symbol ->
        val selectedTrade = TradeHistoryStore.load(context).firstOrNull { it.id == analysisTradeId }
            ?: LiveOutcomeLedger.loadCompleted(context).firstOrNull { it.id == analysisTradeId }
            ?: TradeHistoryStore.load(context).firstOrNull { it.symbol.equals(symbol, true) && it.closedAt == null }
        val selectedPosition = overview?.account?.assetPositions?.firstOrNull {
            it.position.coin.equals(symbol, true) && (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0
        }
        TradeAnalysisDialog(
            symbol = symbol,
            trade = selectedTrade,
            asset = selectedPosition,
            onDismiss = { analysisTradeId = null; analysisSymbol = null },
            isDcaStopLossEnabled = dcaSettings.stopLossEnabled
        )
    }

    closeRequest?.let { request ->
        AlertDialog(
            onDismissRequest = { closeRequest = null },
            title = { Text("${request.symbol} verkleinen of sluiten?") },
            text = {
                Column {
                    Text(
                        "${if (request.shortDirection) "SHORT" else "LONG"} · positie ${usdPosition(request.positionValue)}\n" +
                            "Actuele ongerealiseerde PNL: ${signedUsdPosition(request.pnl)}\n\nKies hoeveel je reduce-only wilt sluiten:"
                    )
                    Row(Modifier.fillMaxWidth().padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf(25, 50, 75, 100).forEach { percentage ->
                            Surface(
                                color = if (request.percentage == percentage) PositionsRed else PositionsCard,
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.weight(1f).clickable { closeRequest = request.copy(percentage = percentage) }
                            ) {
                                Text(
                                    "$percentage%", color = Color.White, fontSize = 10.sp,
                                    fontWeight = FontWeight.Bold, textAlign = androidx.compose.ui.text.style.TextAlign.Center,
                                    modifier = Modifier.padding(vertical = 10.dp)
                                )
                            }
                        }
                    }
                    Text(
                        if (request.percentage == 100) "Bij 100% worden beschermingsorders voor deze pair geannuleerd en wordt de volledige positie gesloten."
                        else "${request.percentage}% wordt gesloten; de resterende positie blijft actief. Deze actie kan niet ongedaan worden gemaakt.",
                        color = PositionsMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 10.dp)
                    )
                }
            },
            confirmButton = {
                TradeMentorTextButton(
                    color = PositionsRed,
                    onClick = {
                        closeRequest = null
                        scope.launch {
                            val token = LocalTradingGatewayStore.testToken(context)
                            runCatching { closeClient.closePosition(LocalTradingGatewayStore.url(context), token, request.symbol, request.percentage) }
                                .onSuccess { result ->
                                    closeMessage = if (result.closed) {
                                        if (request.percentage == 100) "${request.symbol} is volledig gesloten."
                                        else "${request.percentage}% van ${request.symbol} is reduce-only gesloten."
                                    } else "${request.symbol} kon niet worden bevestigd als gesloten."
                                }
                                .onFailure { closeMessage = "Sluiten mislukt: ${it.message}" }
                        }
                    }
                ) { Text("Sluit ${request.percentage}% reduce-only", color = PositionsRed) }
            },
            dismissButton = { TradeMentorTextButton(onClick = { closeRequest = null }) { Text("Annuleren") } }
        )
    }
    addOnRequest?.let { (symbol, assessment) ->
        val position = overview?.account?.assetPositions?.firstOrNull { it.position.coin.equals(symbol, true) }?.position
        AlertDialog(
            onDismissRequest = { if (addOnBusy == null) addOnRequest = null },
            title = { Text("$symbol één keer bijkopen?") },
            text = { Text("Bedrag: ${usdPosition(executionSettings.positionSizeUsd)}\nHeranalyse: ${String.format(Locale.US, "%.0f%%", assessment.winRate)} winrate · score ${assessment.qualityScore.toInt()}\n\nDe positie en het liquidatierisico worden groter. De take-profit wordt opnieuw ingesteld voor de volledige positie.") },
            confirmButton = {
                TradeMentorTextButton(
                    enabled = addOnBusy == null && position != null,
                    color = PositionsGreen,
                    onClick = {
                        val active = position ?: return@TradeMentorTextButton
                        addOnBusy = symbol
                        scope.launch {
                            val short = (active.signedSize.toDoubleOrNull() ?: 0.0) < 0
                            val intent = HyperliquidOrderPlanner.create(symbol, short, executionSettings.positionSizeUsd, active.leverage.value, assessment.currentPrice, activeProfitTarget)
                            runCatching { closeClient.executeAddOn(LocalTradingGatewayStore.url(context), LocalTradingGatewayStore.testToken(context), intent, activeProfitTarget) }
                                .onSuccess {
                                    AddOnTradeStore.markAdded(context, symbol)
                                    addOnAssessments = addOnAssessments - symbol.uppercase()
                                    closeMessage = "$symbol is één keer bijgekocht; take-profit is bijgewerkt."
                                    addOnRequest = null
                                }.onFailure { closeMessage = "Bijkopen mislukt: ${it.message}" }
                            addOnBusy = null
                        }
                    }
                ) { Text(if (addOnBusy == symbol) "Uitvoeren…" else "Bevestig 1× bijkopen", color = PositionsGreen) }
            },
            dismissButton = { TradeMentorTextButton(enabled = addOnBusy == null, onClick = { addOnRequest = null }) { Text("Annuleren") } }
        )
    }
}

private enum class LiveDcaTimeUnit(val label: String) { Minutes("Minuten"), Hours("Uren") }

@Composable
private fun DcaSettingsDashboard(
    initial: DcaBotSettings,
    onDismiss: () -> Unit,
    onSave: (DcaBotSettings) -> Unit
) {
    var baseOrder by remember { mutableStateOf(numberInput(initial.baseOrderUsd)) }
    var maximumDeals by remember { mutableStateOf(initial.maxActiveDeals.toString()) }
    var maximumAdds by remember { mutableStateOf(initial.maxSafetyOrders.toString()) }
    var longDeviation by remember { mutableStateOf(numberInput(initial.priceDeviationPercentage)) }
    var shortDeviation by remember { mutableStateOf(numberInput(initial.shortPriceDeviationPercentage)) }
    var timeUnit by remember { mutableStateOf(if (initial.cooldownMinutes >= 60 && initial.cooldownMinutes % 60 == 0) LiveDcaTimeUnit.Hours else LiveDcaTimeUnit.Minutes) }
    var cooldown by remember { mutableStateOf(if (timeUnit == LiveDcaTimeUnit.Hours) (initial.cooldownMinutes / 60).toString() else initial.cooldownMinutes.toString()) }
    var target by remember { mutableStateOf(numberInput(initial.portfolioTargetPercentage)) }
    var entryMode by remember { mutableStateOf(initial.entryMode) }
    var stopLossEnabled by remember { mutableStateOf(initial.stopLossEnabled) }
    var revealed by remember { mutableStateOf(false) }
    val rotation by animateFloatAsState(if (revealed) 0f else 90f, tween(420), label = "dcaDashboardFlip")
    LaunchedEffect(Unit) { revealed = true }

    fun draft() = DcaBotSettingsInput(
        baseOrderUsd = baseOrder,
        maxSafetyOrders = maximumAdds,
        longDeviationPercentage = longDeviation,
        shortDeviationPercentage = shortDeviation,
        maxActiveDeals = maximumDeals,
        cooldownValue = cooldown,
        cooldownInHours = timeUnit == LiveDcaTimeUnit.Hours,
        portfolioTargetPercentage = target,
        topUniverseSize = initial.topUniverseSize.toString(),
        entryMode = entryMode,
        stopLossEnabled = stopLossEnabled
    ).applyTo(initial)

    Dialog(onDismissRequest = { onSave(draft()) }, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(
            color = PositionsBg,
            modifier = Modifier.fillMaxSize().graphicsLayer { rotationY = rotation; cameraDistance = 18f * density }
        ) {
            Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("DCA PULSE", color = PositionsGreen, fontSize = 11.sp, fontWeight = FontWeight.Black)
                        Text("Instellingen", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Black)
                    }
                    TradeMentorTextButton(label = "Opslaan en sluiten", onClick = { onSave(draft()) })
                }
                Text("Gekoppeld aan Strategy > DCA Pulse. Beide schermen lezen en wijzigen exact dezelfde opgeslagen waarden; wijzigingen gelden ook voor lopende DCA-deals.", color = PositionsMuted, fontSize = 11.sp, modifier = Modifier.padding(bottom = 14.dp))
                Text("INSTAPMETHODE", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
                Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    listOf("bollinger" to "Bollinger", "direct" to "Direct vullen").forEach { (mode, label) ->
                        Surface(
                            color = if (entryMode == mode) Color(0xFF0B332B) else PositionsCard,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f).clickable { entryMode = mode }
                        ) { Text(label, color = if (entryMode == mode) PositionsGreen else Color.White, modifier = Modifier.padding(12.dp), fontWeight = FontWeight.Bold) }
                    }
                }
                Text(
                    if (entryMode == "direct") "Directe basisorders zonder uitstapprijs; unieke Top-N-pairs en richtingsbalans blijven verplicht."
                    else "Basisorders gebruiken de ingestelde 1m Bollinger-voorwaarden.",
                    color = PositionsMuted, fontSize = 10.sp, modifier = Modifier.padding(bottom = 10.dp)
                )
                DcaDashboardField("Basisorder in dollars", baseOrder, { baseOrder = it }, "De eerste order en iedere bijkoop gebruiken exact dit bedrag.")
                DcaDashboardField("Maximaal actieve deals", maximumDeals, { maximumDeals = it }, "Aantal unieke DCA-pairs; bijkopen tellen niet als nieuwe deal.")
                DcaDashboardField("Maximaal bijkopen per pair", maximumAdds, { maximumAdds = it }, "Verhogen ontgrendelt volgende niveaus voor bestaande DCA-posities.")
                DcaDashboardField("Long-deviation (%)", longDeviation, { longDeviation = it }, "Afstand onder de oorspronkelijke long-instap per volgend niveau.")
                DcaDashboardField("Short-deviation (%)", shortDeviation, { shortDeviation = it }, "Afstand boven de oorspronkelijke short-instap per volgend niveau.")
                Text("TIJD TUSSEN AANKOPEN", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
                Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    LiveDcaTimeUnit.entries.forEach { unit ->
                        Surface(
                            color = if (timeUnit == unit) Color(0xFF0B332B) else PositionsCard,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.weight(1f).clickable { timeUnit = unit }
                        ) { Text(unit.label, color = if (timeUnit == unit) PositionsGreen else Color.White, modifier = Modifier.padding(12.dp), fontWeight = FontWeight.Bold) }
                    }
                }
                DcaDashboardField("Wachttijd", cooldown, { cooldown = it }, "Minimale tijd voordat dezelfde pair opnieuw mag worden bijgekocht.")
                DcaDashboardField("Portfoliodoel (%)", target, { target = it }, "Close All vanaf de vastgezette Available to trade-startwaarde. Tijdens een cyclus alleen verhogen.")
                DcaDashboardToggle("Stop-loss activeren", stopLossEnabled) { stopLossEnabled = it }
                DcaDashboardHelp("Stop-loss status", if (stopLossEnabled) "INGESCHAKELD" else "UIT")
                TradeMentorPrimaryButton(label = "Instellingen opslaan", onClick = { onSave(draft()) }, modifier = Modifier.fillMaxWidth().height(52.dp))
                Spacer(Modifier.height(30.dp))
            }
        }
    }
}

@Composable
private fun DcaDashboardToggle(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp),
        horizontalArrangement = Arrangement.SpaceBetween,
        verticalAlignment = Alignment.CenterVertically
    ) {
        Text(label, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
        Switch(checked = checked, onCheckedChange = onChecked)
    }
}

@Composable
private fun DcaDashboardHelp(label: String, value: String) {
    Surface(color = Color(0xFF152238), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp)) {
        Column(Modifier.padding(11.dp)) {
            Row(Modifier.fillMaxWidth()) {
                Text(label, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(value, color = Color(0xFF6EA8FF), fontSize = 10.sp, fontWeight = FontWeight.Black)
            }
            Text(
                if (value == "INGESCHAKELD") "Automatische sluiting op stop-loss is actief." else "Stop-loss staat uit; sluiting blijft handmatig.",
                color = Color(0xFF8C92A3), fontSize = 9.sp, modifier = Modifier.padding(top = 3.dp)
            )
        }
    }
}

@Composable
private fun DcaDashboardField(label: String, value: String, onValue: (String) -> Unit, explanation: String) {
    OutlinedTextField(
        value = value,
        onValueChange = { onValue(it.filter { char -> char.isDigit() || char == '.' || char == ',' }) },
        label = { Text(label) },
        supportingText = { Text(explanation, color = PositionsMuted, fontSize = 9.sp) },
        singleLine = true,
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth().padding(bottom = 5.dp)
    )
}

private fun numberInput(value: Double): String = if (value % 1.0 == 0.0) value.toInt().toString() else String.format(Locale.US, "%.2f", value)

private fun positionPriceMovePercentage(position: HyperliquidPosition): Double {
    val size = position.signedSize.toDoubleOrNull() ?: return 0.0
    val entry = position.entryPrice?.toDoubleOrNull() ?: return 0.0
    val current = if (size != 0.0) kotlin.math.abs(position.positionValue.toDoubleOrNull() ?: 0.0) / kotlin.math.abs(size) else 0.0
    return DcaPulseGate.pricePerformancePercentage(size < 0.0, current, entry)
}

private fun ensureExternalPositionsTracked(
    context: Context,
    positions: List<HyperliquidAssetPosition>,
    fills: List<HyperliquidFill>
) {
    val existing = TradeHistoryStore.load(context)
    val activeSymbols = existing.filter { it.closedAt == null }.map { it.symbol.uppercase() }.toSet()
    val settings = SignalExecutionSettingsStore.load(context)
    val target = ConsensusProfileStore.load(context).profitTarget
    val additions = positions.mapNotNull { asset ->
        val position = asset.position
        val symbol = position.coin.uppercase()
        if (symbol in activeSymbols) return@mapNotNull null
        val size = position.signedSize.toDoubleOrNull() ?: return@mapNotNull null
        if (size == 0.0) return@mapNotNull null
        val short = size < 0.0
        val openingFill = fills.asSequence()
            .filter { it.coin.equals(symbol, true) }
            .filter { kotlin.math.abs(it.startPosition.toDoubleOrNull() ?: Double.NaN) < 0.00000001 }
            .filter { if (short) it.direction.contains("Open Short", true) else it.direction.contains("Open Long", true) }
            .maxByOrNull { it.time }
        val startedAt = openingFill?.time?.takeIf { it > 0 } ?: System.currentTimeMillis()
        TrackedTrade(
            id = startedAt + kotlin.math.abs(symbol.hashCode().toLong()),
            symbol = position.coin,
            shortDirection = short,
            entryPrice = position.entryPrice?.toDoubleOrNull() ?: openingFill?.price?.toDoubleOrNull() ?: return@mapNotNull null,
            profitPercentage = target,
            timeframe = "Open positie",
            startedAt = startedAt,
            expiresAt = Long.MAX_VALUE,
            strategyId = "external_hyperliquid",
            strategyName = "Extern via Hyperliquid",
            indicators = listOf("Live Hyperliquid-positie", "Verse 5m + 15m-heranalyse vereist"),
            maxAdversePercentage = 1.0,
            positionSizeUsd = settings.positionSizeUsd,
            leverage = position.leverage.value,
            positionValueUsd = position.positionValue.toDoubleOrNull(),
            liquidationPrice = position.liquidationPrice?.toDoubleOrNull()
        )
    }
    if (additions.isNotEmpty()) TradeHistoryStore.save(context, additions + existing)
}

private fun syncPersistentTradeDetails(
    context: Context,
    positions: List<HyperliquidAssetPosition>,
    recentFills: List<HyperliquidFill>
) {
    val trades = TradeHistoryStore.load(context)
    if (trades.isEmpty()) return
    val currentBySymbol = positions.associateBy { it.position.coin.uppercase() }
    val updated = trades.map { trade ->
        if (trade.closedAt != null) return@map trade
        val symbol = trade.symbol.uppercase()
        val active = currentBySymbol[symbol]?.position
        if (active != null) {
            val size = kotlin.math.abs(active.signedSize.toDoubleOrNull() ?: 0.0)
            val positionValue = active.positionValue.toDoubleOrNull()
            trade.copy(
                leverage = active.leverage.value,
                positionValueUsd = positionValue,
                liquidationPrice = active.liquidationPrice?.toDoubleOrNull(),
                lastPrice = if (size > 0.0 && positionValue != null) positionValue / size else trade.lastPrice
            )
        } else {
            TradeClosureReconciler.reconcileClosedTrade(trade, recentFills) ?: trade
        }
    }
    if (updated != trades) TradeHistoryStore.save(context, updated)
}

private fun tradeSelectionReason(trade: TrackedTrade?): String {
    if (trade == null) return "live Hyperliquid-positie; oorspronkelijke scannerwaarden ontbreken"
    val evidence = trade.indicators.filter { it.isNotBlank() }.take(2)
    if (evidence.isNotEmpty()) return evidence.joinToString(" + ")
    return when {
        trade.strategyId == "external_hyperliquid" -> "extern geopend en daarna door TradeMentor bewaakt"
        trade.historicalWinRate != null -> "historische winkans ${String.format(Locale.US, "%.0f%%", trade.historicalWinRate)} op ${trade.timeframe}"
        else -> "voldeed bij instap aan ${trade.strategyName}"
    }
}

private fun tradeIndicatorLabel(trade: TrackedTrade?): String {
    if (trade?.strategyId == "strategy_3") return "DCA"
    val raw = trade?.indicators?.firstOrNull { it.isNotBlank() }
        ?: return if (trade?.strategyId == "external_hyperliquid") "EXTERN" else "LIVE"
    val normalized = raw
        .replace("Gekozen omdat:", "", ignoreCase = true)
        .replace("Relative Strength Index", "RSI", ignoreCase = true)
        .trim()
    return normalized.take(32)
}

@Composable
private fun TradeAnalysisDialog(
    symbol: String,
    trade: TrackedTrade?,
    asset: HyperliquidAssetPosition?,
    onDismiss: () -> Unit,
    isDcaStopLossEnabled: Boolean
) {
    val context = LocalContext.current
    val position = asset?.position
    val short = trade?.shortDirection ?: ((position?.signedSize?.toDoubleOrNull() ?: 0.0) < 0.0)
    val pnl = trade?.realizedPnl ?: position?.unrealizedPnl?.toDoubleOrNull()
    val isOpen = position != null
    val evidence = trade?.indicators.orEmpty().filter { it.isNotBlank() }
    val leverage = trade?.leverage ?: position?.leverage?.value
    val positionValue = position?.positionValue?.toDoubleOrNull() ?: trade?.positionValueUsd ?: trade?.positionSizeUsd
    val dcaDeal = DcaDealStore.find(context, symbol)
    val isDcaTrade = trade?.strategyId == "strategy_3" || dcaDeal != null
    val dcaAdditions = dcaDeal?.safetyOrdersCompleted ?: trade?.dcaSafetyOrdersCompleted ?: 0
    var revealed by remember { mutableStateOf(false) }
    val rotation by animateFloatAsState(if (revealed) 0f else 90f, tween(420), label = "tradeFullscreenFlip")
    LaunchedEffect(Unit) { revealed = true }
    val analysis = when {
        trade == null -> "$symbol is op Hyperliquid aangetroffen zonder volledige oorspronkelijke TradeMentor-scanregistratie. De app kan de actuele positie en het risico analyseren, maar mag geen verzonnen instapargumenten tonen."
        trade.strategyId == "external_hyperliquid" -> "$symbol is buiten de scanner geopend en daarna door TradeMentor opgenomen voor bewaking. Daarom zijn er geen oorspronkelijke scannerwaarden waarmee een persoonlijke instapkeuze kan worden onderbouwd."
        else -> buildString {
            append("Op ${positionDate(trade.startedAt)} koos ${trade.strategyName} voor een ${if (short) "short" else "long"} positie in $symbol. ")
            if (evidence.isNotEmpty()) append("De doorslaggevende opgeslagen signalen waren ${evidence.joinToString(", ")}. ")
            trade.historicalWinRate?.let { append("De historische validatie bij instap gaf ${String.format(Locale.US, "%.1f%%", it)} winkans. ") }
            append("Het koersdoel was ${String.format(Locale.US, "%.2f%%", trade.profitPercentage)}")
            if (!isDcaTrade || isDcaStopLossEnabled) {
                append(" en de maximaal geaccepteerde tegenbeweging ${String.format(Locale.US, "%.2f%%", trade.maxAdversePercentage)}")
            }
            append(". ")
            append("De positieomvang was ${usdPosition(trade.positionSizeUsd)}${leverage?.let { " met ${it}× hefboom" }.orEmpty()}. ")
            append(if (isOpen) "De positie loopt nog; het getoonde resultaat is daarom ongerealiseerd en kan veranderen." else "De positie is gesloten; het getoonde resultaat is gerealiseerd voor zover Hyperliquid de sluitingsfill heeft geleverd.")
        }
    }

    Dialog(onDismissRequest = onDismiss, properties = DialogProperties(usePlatformDefaultWidth = false)) {
        Surface(color = PositionsBg, modifier = Modifier.fillMaxSize().graphicsLayer { rotationY = rotation; cameraDistance = 18f * density }) {
            Column(
                Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 20.dp, vertical = 18.dp)
            ) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("PERSOONLIJKE TRADE-ANALYSE", color = Color(0xFF8EB2FF), fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                        Text(symbol, color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.Black)
                        Text(if (short) "SHORT" else "LONG", color = if (short) PositionsRed else PositionsGreen, fontSize = 13.sp, fontWeight = FontWeight.ExtraBold)
                    }
                    TradeMentorTextButton(onClick = onDismiss) { Text("SLUITEN", color = Color.White) }
                }
                Spacer(Modifier.height(16.dp))
                Surface(color = Color(0xFF0D2140), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
                    Column(Modifier.padding(16.dp)) {
                        Text("WAAROM GEKOZEN", color = PositionsGreen, fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                        Text(tradeSelectionReason(trade), color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 6.dp))
                        Text(analysis, color = Color(0xFFD5D9E4), fontSize = 12.sp, modifier = Modifier.padding(top = 12.dp))
                    }
                }
                Spacer(Modifier.height(14.dp))
                Text("TRADEWAARDEN", color = Color(0xFFFFC857), fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                trade?.let {
                    PositionRow("Strategie", it.strategyName)
                    PositionRow("Tijdsframe", it.timeframe)
                    PositionRow("Instapmoment", positionDate(it.startedAt))
                    PositionRow("Instapprijs", pricePosition(it.entryPrice.toString()))
                    PositionRow("Positieomvang", usdPosition(it.positionSizeUsd))
                    PositionRow("Historische winkans", it.historicalWinRate?.let { rate -> String.format(Locale.US, "%.1f%%", rate) } ?: "Niet opgeslagen")
                    if (!isDcaTrade || isDcaStopLossEnabled) {
                        PositionRow("Take-profit", String.format(Locale.US, "%.2f%%", it.profitPercentage), Color(0xFFFFC857))
                        PositionRow("Maximale tegenbeweging", String.format(Locale.US, "%.2f%%", it.maxAdversePercentage), PositionsRed)
                    } else {
                        PositionRow("DCA-orders", "${dcaAdditions + 1} orders · ${dcaAdditions}× bijgekocht", Color(0xFF7DB7FF))
                        PositionRow("Uitstap", "Handmatig of portfoliodoel", PositionsGreen)
                    }
                }
                leverage?.let { PositionRow("Hefboom", "${it}×") }
                positionValue?.let { PositionRow("Actuele positiewaarde", usdPosition(kotlin.math.abs(it))) }
                position?.let {
                    PositionRow("Marge gebruikt", usdPosition(it.marginUsed.toDoubleOrNull() ?: 0.0))
                    PositionRow("Liquidatieprijs", pricePosition(it.liquidationPrice))
                    PositionRow("Rendement", String.format(Locale.US, "%+.2f%%", (it.returnOnEquity.toDoubleOrNull() ?: 0.0) * 100.0), if ((pnl ?: 0.0) >= 0.0) PositionsGreen else PositionsRed)
                }
                PositionRow(if (isOpen) "Open PNL" else "Gerealiseerd resultaat", pnl?.let(::signedUsdPosition) ?: "Wordt opgehaald", if ((pnl ?: 0.0) >= 0.0) PositionsGreen else PositionsRed)
                if (evidence.isNotEmpty()) {
                    Spacer(Modifier.height(16.dp))
                    Text("OPGESLAGEN SIGNALEN EN WAARDEN", color = Color(0xFFFFC857), fontSize = 11.sp, fontWeight = FontWeight.ExtraBold)
                    evidence.forEachIndexed { index, value ->
                        Surface(color = PositionsCard, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(top = 8.dp)) {
                            Text("${index + 1}. $value", color = Color.White, fontSize = 12.sp, modifier = Modifier.padding(12.dp))
                        }
                    }
                }
                Spacer(Modifier.height(24.dp))
                Text("Historische analyse en modeluitkomsten zijn geen winstgarantie. Open PNL kan veranderen tot de positie werkelijk is gesloten.", color = PositionsMuted, fontSize = 9.sp)
                Spacer(Modifier.height(30.dp))
            }
        }
    }
}

@Composable private fun RiskGauge(riskPercentage: Double, modifier: Modifier = Modifier) {
    val riskColor = when {
        riskPercentage < 30.0 -> PositionsGreen
        riskPercentage < 50.0 -> Color(0xFFFFD166)
        riskPercentage < 70.0 -> Color(0xFFFF9F43)
        else -> PositionsRed
    }
    val riskLabel = when {
        riskPercentage < 30.0 -> "VEILIG"
        riskPercentage < 50.0 -> "VOLGEN"
        riskPercentage < 70.0 -> "VERLAGEN"
        riskPercentage < 85.0 -> "HOOG"
        riskPercentage < 95.0 -> "KRITIEK"
        else -> "LIQ. GEVAAR"
    }
    Column(modifier, horizontalAlignment = Alignment.CenterHorizontally) {
        Text("NAAR LIQUIDATIE", color = riskColor, fontSize = 9.sp, fontWeight = FontWeight.ExtraBold)
        Box(contentAlignment = Alignment.BottomCenter, modifier = Modifier.size(width = 76.dp, height = 38.dp)) {
            Canvas(Modifier.size(width = 72.dp, height = 36.dp)) {
                val stroke = Stroke(width = 7.dp.toPx())
                drawArc(Color(0xFF253149), 180f, 180f, false, style = stroke)
                drawArc(riskColor, 180f, 180f * (riskPercentage / 100.0).toFloat(), false, style = stroke)
            }
            Text(String.format(Locale.US, "%.2f%%", riskPercentage), color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Black)
        }
        Text(riskLabel, color = riskColor, fontSize = 8.sp, fontWeight = FontWeight.Bold)
    }
}

@Composable private fun PositionRow(label: String, value: String, color: Color = Color.White) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(label, color = PositionsMuted, fontSize = 12.sp, modifier = Modifier.weight(1f))
        Text(value, color = color, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable private fun PositionStat(label: String, value: String, color: Color, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    Surface(color = PositionsCard, shape = RoundedCornerShape(12.dp), modifier = modifier.then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)) {
        Column(Modifier.padding(horizontal = 5.dp, vertical = 4.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(value, color = color, fontSize = 15.sp, fontWeight = FontWeight.ExtraBold, maxLines = 1)
            Text(label, color = PositionsMuted, fontSize = 7.sp, maxLines = 1)
        }
    }
}

@Composable private fun PositionTab(label: String, selected: Boolean, modifier: Modifier = Modifier, onClick: () -> Unit) {
    Surface(
        onClick = onClick,
        color = if (selected) Color(0xFF16274A) else PositionsCard,
        shape = RoundedCornerShape(12.dp),
        modifier = modifier
    ) {
        Column(Modifier.padding(horizontal = 5.dp, vertical = 8.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Text(label, color = if (selected) Color.White else PositionsMuted, fontSize = 9.sp, fontWeight = if (selected) FontWeight.ExtraBold else FontWeight.SemiBold, maxLines = 1)
            Surface(
                color = if (selected) PositionsBlue else Color.Transparent,
                shape = RoundedCornerShape(2.dp),
                modifier = Modifier.padding(top = 5.dp).fillMaxWidth(0.42f).height(2.dp)
            ) {}
        }
    }
}

private fun tradeDuration(startedAt: Long, endedAt: Long): String {
    val totalMinutes = ((endedAt - startedAt).coerceAtLeast(0L) / 60_000L)
    val days = totalMinutes / (24 * 60)
    val hours = (totalMinutes % (24 * 60)) / 60
    val minutes = totalMinutes % 60
    return when {
        days > 0 -> "${days}d ${hours}u"
        hours > 0 -> "${hours}u ${minutes}m"
        else -> "${minutes}m"
    }
}

private fun positionDate(timestamp: Long): String = SimpleDateFormat("dd MMM yyyy · HH:mm", Locale("nl", "NL")).format(Date(timestamp))

private fun usdPosition(value: Double) = NumberFormat.getCurrencyInstance(Locale.US).format(value)
private fun signedUsdPosition(value: Double) = (if (value >= 0) "+" else "") + usdPosition(value)
private fun pricePosition(value: String?) = value?.toDoubleOrNull()?.let { NumberFormat.getNumberInstance(Locale.US).apply { maximumFractionDigits = 8 }.format(it) } ?: "—"
