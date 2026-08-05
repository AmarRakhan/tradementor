package com.tradementor.app.screens

import android.content.Context
import android.widget.Toast
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.LocalTextStyle
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.foundation.rememberScrollState
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import kotlinx.coroutines.launch
import com.tradementor.app.api.CustomScanSignal
import com.tradementor.app.api.ScanCondition
import com.tradementor.app.api.ScanMetric
import com.tradementor.app.api.ScanOperator
import com.tradementor.app.api.TimeframeWinRate
import com.tradementor.app.api.AdvisorRecommendation
import com.tradementor.app.api.CatalogExchange
import com.tradementor.app.api.CatalogMarket
import com.tradementor.app.repository.ExchangeCatalogRepository
import com.tradementor.app.repository.MarketUniverseSelection
import com.tradementor.app.repository.BinanceMarketRepository
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.scanner.BackgroundScanConfig
import com.tradementor.app.scanner.SignalExecutionSettings
import com.tradementor.app.scanner.SignalExecutionSettingsStore
import com.tradementor.app.scanner.ActiveHyperliquidPositionStore
import com.tradementor.app.scanner.HyperliquidOrderPlanner
import com.tradementor.app.scanner.OrderIntentStore
import com.tradementor.app.scanner.LocalTradingGatewayStore
import com.tradementor.app.scanner.TradingGatewayClient
import com.tradementor.app.scanner.DirectionBalanceGate
import com.tradementor.app.scanner.AdvisorEngine
import com.tradementor.app.scanner.BinanceSignalsEngine
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.NotificationMode
import com.tradementor.app.scanner.NotificationStyle
import com.tradementor.app.scanner.TrackedTrade
import com.tradementor.app.scanner.TradeHistoryStore
import com.tradementor.app.scanner.ScannerSession
import com.tradementor.app.scanner.ConsensusProfileStore
import kotlinx.coroutines.delay
import java.text.DecimalFormat

private val ScannerBg = Color(0xFF05070B)
private val ScannerPanel = Color(0xFF101722)
private val ScannerRaised = Color(0xFF162033)
private val ScannerBlue = Color(0xFF2F68FF)
private val ScannerGreen = Color(0xFF08C887)
private val ScannerRed = Color(0xFFFF4964)
private val ScannerMuted = Color(0xFF8C92A3)
private val ScannerDivider = Color(0xFF232A38)

private enum class StrategyDirection(val title: String) { Short("SHORT"), Long("LONG") }

private data class SavedStrategy(
    val name: String,
    val direction: StrategyDirection,
    val interval: String,
    val requireAll: Boolean,
    val conditions: List<ScanCondition>
)

@Composable
fun ScannerScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val repository = remember { MarketRepository() }
    val catalogRepository = remember { ExchangeCatalogRepository() }
    val rotation = remember { Animatable(0f) }
    var settingsRequested by remember { mutableStateOf(false) }
    var settingsVisible by remember { mutableStateOf(false) }
    var requestedResult by remember { mutableStateOf<CustomScanSignal?>(null) }
    var requestedResultShortDirection by remember { mutableStateOf(false) }
    var displayedResult by remember { mutableStateOf<CustomScanSignal?>(null) }
    var requestedStrategyName by remember { mutableStateOf("TradeMentor Signals") }
    var requestedIndicators by remember { mutableStateOf<List<String>>(emptyList()) }
    var platform by remember { mutableStateOf(MarketUniverseSelection.exchangeName) }
    var marketType by remember { mutableStateOf(MarketUniverseSelection.marketType) }
    var quoteCurrency by remember { mutableStateOf(MarketUniverseSelection.quoteCurrency) }
    var exchangeCatalog by remember { mutableStateOf<List<CatalogExchange>>(emptyList()) }
    var catalogMarkets by remember { mutableStateOf<List<CatalogMarket>>(emptyList()) }
    var direction by remember { mutableStateOf(StrategyDirection.Short) }
    var interval by remember { mutableStateOf("1w") }
    var requireAll by remember { mutableStateOf(ScannerSession.requireAll) }
    var conditions by remember {
        mutableStateOf(ScannerSession.activeConditions.ifEmpty { listOf(ScannerSession.defaultCondition) })
    }
    var savedStrategies by remember { mutableStateOf(loadStrategies(context)) }
    val results = ScannerSession.results
    val scanning = ScannerSession.scanning
    val progress = ScannerSession.progress
    val total = ScannerSession.total
    val error = ScannerSession.error
    var scanVersion by remember { mutableIntStateOf(0) }

    fun closeAndScan() {
        settingsRequested = false
        scanVersion++
    }

    LaunchedEffect(Unit) {
        runCatching { catalogRepository.getTopExchanges(25) }.onSuccess { exchangeCatalog = it }
    }

    LaunchedEffect(platform, exchangeCatalog) {
        if (platform == "Hyperliquid") {
            catalogMarkets = emptyList()
            marketType = "Perpetuals"
            quoteCurrency = "USD"
        } else {
            val exchange = exchangeCatalog.firstOrNull { it.name == platform }
            catalogMarkets = runCatching { exchange?.let { catalogRepository.getMarkets(it.id) }.orEmpty() }.getOrDefault(emptyList())
            marketType = catalogMarkets.firstOrNull()?.category ?: "Spot"
            quoteCurrency = catalogMarkets.map { it.quoteSymbol }.firstOrNull { it in listOf("USDT", "USDC", "USD", "EUR", "BTC") }
                ?: catalogMarkets.firstOrNull()?.quoteSymbol.orEmpty()
        }
        MarketUniverseSelection.exchangeName = platform
        MarketUniverseSelection.exchangeId = exchangeCatalog.firstOrNull { it.name == platform }?.id ?: "hyperliquid"
        MarketUniverseSelection.marketType = marketType
        MarketUniverseSelection.quoteCurrency = quoteCurrency
    }

    LaunchedEffect(settingsRequested, requestedResult) {
        val targetResult = if (settingsRequested) null else requestedResult
        if (settingsRequested == settingsVisible && targetResult == displayedResult) return@LaunchedEffect
        rotation.animateTo(90f, tween(260))
        settingsVisible = settingsRequested
        displayedResult = targetResult
        rotation.snapTo(-90f)
        rotation.animateTo(0f, tween(320))
    }

    LaunchedEffect(platform, marketType, quoteCurrency, scanVersion) {
        if (scanVersion == 0 && ScannerSession.hasLoaded) return@LaunchedEffect
        if (platform != "Hyperliquid" || marketType != "Perpetuals" || quoteCurrency != "USD" || conditions.isEmpty()) {
            return@LaunchedEffect
        }
        ScannerSession.scan(conditions, requireAll)
    }

    PullToRefreshBox(
        isRefreshing = scanning,
        onRefresh = {
            if (!settingsVisible && displayedResult == null) scanVersion++
        },
        modifier = modifier.fillMaxSize().background(ScannerBg).graphicsLayer {
            rotationY = rotation.value
            cameraDistance = 18f * density
        }
    ) {
        if (settingsVisible) {
            StrategySettings(
                direction = direction,
                onDirection = { direction = it },
                interval = interval,
                requireAll = requireAll,
                onRequireAll = { requireAll = it },
                conditions = conditions,
                onAddCondition = { condition -> conditions = conditions + condition.copy(id = System.nanoTime(), interval = interval) },
                onRemoveCondition = { id -> conditions = conditions.filterNot { it.id == id } },
                savedStrategies = savedStrategies,
                onSaveStrategy = { name ->
                    val saved = SavedStrategy(name, direction, interval, requireAll, conditions)
                    savedStrategies = (savedStrategies.filterNot { it.name.equals(name, true) } + saved).sortedBy { it.name }
                    saveStrategies(context, savedStrategies)
                },
                onLoadStrategy = { saved ->
                    direction = saved.direction
                    interval = saved.interval
                    requireAll = saved.requireAll
                    conditions = saved.conditions.map { it.copy(id = System.nanoTime() + it.id) }
                },
                onDeleteStrategy = { saved ->
                    savedStrategies = savedStrategies - saved
                    saveStrategies(context, savedStrategies)
                },
                onBack = ::closeAndScan
            )
        } else if (displayedResult != null) {
            WinChanceScreen(
                result = displayedResult!!,
                shortDirection = requestedResultShortDirection,
                repository = repository,
                sourceStrategy = requestedStrategyName,
                sourceIndicators = requestedIndicators,
                sourceExchange = platform,
                sourceMarketType = marketType,
                sourceQuoteCurrency = quoteCurrency,
                onBack = { requestedResult = null }
            )
        } else {
            StrategyResults(
                repository = repository,
                platform = platform,
                onPlatform = { platform = it },
                platformOptions = listOf("Hyperliquid") + exchangeCatalog.map { it.name }.filterNot { it == "Hyperliquid" },
                marketType = marketType,
                onMarketType = { marketType = it; MarketUniverseSelection.marketType = it },
                marketTypeOptions = if (platform == "Hyperliquid") listOf("Perpetuals") else catalogMarkets.map { it.category }.distinct().sorted(),
                quoteCurrency = quoteCurrency,
                onQuoteCurrency = { quoteCurrency = it; MarketUniverseSelection.quoteCurrency = it },
                quoteOptions = if (platform == "Hyperliquid") listOf("USD") else catalogMarkets.map { it.quoteSymbol }.distinct().sorted(),
                externalMarkets = catalogMarkets.filter { it.quoteSymbol == quoteCurrency && it.category.equals(marketType, true) },
                direction = direction,
                interval = interval,
                conditions = conditions,
                requireAll = requireAll,
                results = results,
                scanning = scanning,
                progress = progress,
                total = total,
                error = error,
                onRetry = { scanVersion++ },
                onSettings = { settingsRequested = true },
                savedStrategies = savedStrategies,
                onSaveStrategy = { name ->
                    val saved = SavedStrategy(name, direction, interval, requireAll, conditions)
                    savedStrategies = (savedStrategies.filterNot { it.name.equals(name, true) } + saved).sortedBy { it.name }
                    saveStrategies(context, savedStrategies)
                },
                onLoadStrategy = { saved ->
                    direction = saved.direction
                    interval = saved.interval
                    requireAll = saved.requireAll
                    conditions = saved.conditions.map { it.copy(id = System.nanoTime() + it.id, interval = saved.interval) }
                    scanVersion++
                },
                onDeleteStrategy = { saved ->
                    savedStrategies = savedStrategies - saved
                    saveStrategies(context, savedStrategies)
                },
                onResultSelected = {
                    requestedResultShortDirection = direction == StrategyDirection.Short
                    requestedStrategyName = savedStrategies.firstOrNull { saved -> strategyMatches(saved, direction, interval, requireAll, conditions) }?.name
                        ?: suggestedStrategyName(direction, interval, conditions)
                    requestedIndicators = conditions.map { condition -> condition.metric.title }.distinct()
                    requestedResult = it
                },
                onAdvisorSelected = { recommendation ->
                    requestedResultShortDirection = recommendation.shortDirection
                    requestedStrategyName = "TradeMentor zelfstandige analyse"
                    requestedIndicators = recommendation.indicators
                    requestedResult = CustomScanSignal(
                        symbol = recommendation.symbol,
                        price = recommendation.price,
                        matchedConditionIds = emptyList(),
                        candleCloseTime = System.currentTimeMillis()
                    )
                }
            )
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalFoundationApi::class, ExperimentalLayoutApi::class)
@Composable
private fun StrategyResults(
    repository: MarketRepository,
    platform: String,
    onPlatform: (String) -> Unit,
    platformOptions: List<String>,
    marketType: String,
    onMarketType: (String) -> Unit,
    marketTypeOptions: List<String>,
    quoteCurrency: String,
    onQuoteCurrency: (String) -> Unit,
    quoteOptions: List<String>,
    externalMarkets: List<CatalogMarket>,
    direction: StrategyDirection,
    interval: String,
    conditions: List<ScanCondition>,
    requireAll: Boolean,
    results: List<CustomScanSignal>,
    scanning: Boolean,
    progress: Int,
    total: Int,
    error: String?,
    onRetry: () -> Unit,
    onSettings: () -> Unit,
    savedStrategies: List<SavedStrategy>,
    onSaveStrategy: (String) -> Unit,
    onLoadStrategy: (SavedStrategy) -> Unit,
    onDeleteStrategy: (SavedStrategy) -> Unit,
    onResultSelected: (CustomScanSignal) -> Unit,
    onAdvisorSelected: (AdvisorRecommendation) -> Unit
) {
    val context = LocalContext.current
    val tradeActionScope = rememberCoroutineScope()
    val advisorEngine = remember(repository) { AdvisorEngine(repository) }
    val binanceSignalsEngine = remember(repository) {
        BinanceSignalsEngine(BinanceMarketRepository(), advisorEngine)
    }
    var expanded by remember { mutableStateOf(false) }
    var typeExpanded by remember { mutableStateOf(false) }
    var quoteExpanded by remember { mutableStateOf(false) }
    var showSaveDialog by remember { mutableStateOf(false) }
    var strategyName by remember { mutableStateOf("") }
    val winTimeframe = "7 dagen"
    var resultWinRates by remember { mutableStateOf<Map<String, Double>>(emptyMap()) }
    var resultWinRatesLoading by remember { mutableStateOf(false) }
    val customEnabled = false
    val consensusProfile = remember { ConsensusProfileStore.load(context) }
    val strategyRevision = com.tradementor.app.scanner.StrategyProfileStore.revision
    val activeStrategy = com.tradementor.app.scanner.StrategyProfileStore.activeDefinition(context)
    val strategyScanEnabled = activeStrategy.specificationReady && activeStrategy.id in setOf("strategy_1", "strategy_2")
    val strategyExecutionEnabled = activeStrategy.executionReady
    val effectiveMinimumScore = if (activeStrategy.id == "strategy_2") {
        maxOf(consensusProfile.minimumScore, 75.0)
    } else consensusProfile.minimumScore
    var longEnabled by remember { mutableStateOf(consensusProfile.allowLong && !consensusProfile.allowShort) }
    var shortEnabled by remember { mutableStateOf(consensusProfile.allowShort && !consensusProfile.allowLong) }
    val minimumWinRateText = String.format(java.util.Locale.US, "%.1f", consensusProfile.minimumWinRate)
    var profitTargetText by remember { mutableStateOf(String.format(java.util.Locale.US, "%.2f", consensusProfile.profitTarget)) }
    var maxAdverseText by remember { mutableStateOf(String.format(java.util.Locale.US, "%.2f", consensusProfile.stopLoss)) }
    val advisorEnabled = true
    var advisorLoading by remember { mutableStateOf(false) }
    var advisorProgress by remember { mutableIntStateOf(0) }
    var advisorTotal by remember { mutableIntStateOf(0) }
    var recommendations by remember { mutableStateOf<List<AdvisorRecommendation>>(emptyList()) }
    var activeWatchlistSymbols by remember { mutableStateOf(emptySet<String>()) }
    var winRateDescending by remember { mutableStateOf(true) }
    var controlsExpanded by remember { mutableStateOf(false) }
    var autoScanning by remember { mutableStateOf(BackgroundScannerScheduler.load(context)?.enabled ?: true) }
    var executionSettings by remember { mutableStateOf(SignalExecutionSettingsStore.load(context)) }
    var marketLeverages by remember { mutableStateOf<Map<String, Int>>(emptyMap()) }
    var positionSizeText by remember { mutableStateOf(String.format(java.util.Locale.US, "%.2f", executionSettings.positionSizeUsd)) }
    var maxActiveTradesText by remember { mutableStateOf(executionSettings.maxActiveTrades.toString()) }
    val tradingGatewayClient = remember { TradingGatewayClient() }
    var liveExecutionMessage by remember { mutableStateOf<String?>(null) }
    val accent = if (direction == StrategyDirection.Short) ScannerRed else ScannerGreen
    val currentSavedStrategy = savedStrategies.firstOrNull {
        strategyMatches(it, direction, interval, requireAll, conditions)
    }
    val sortedResults = remember(results) { results.sortedBy { it.symbol } }

    LaunchedEffect(Unit) {
        marketLeverages = repository.getMarkets().orEmpty().associate { it.market.name.uppercase() to it.market.maxLeverage }
        while (true) {
            autoScanning = BackgroundScannerScheduler.load(context)?.enabled ?: autoScanning
            activeWatchlistSymbols = TradeHistoryStore.load(context)
                .filter { it.outcome == com.tradementor.app.scanner.TradeOutcome.Pending }
                .map { it.symbol.uppercase() }
                .toSet() + ActiveHyperliquidPositionStore.symbols(context)
            delay(2_000)
        }
    }

    LaunchedEffect(results.map { it.symbol }, winTimeframe, direction, profitTargetText) {
        resultWinRates = emptyMap()
        resultWinRatesLoading = results.isNotEmpty()
        if (results.isNotEmpty()) {
            resultWinRates = advisorEngine.scoreScannerResults(
                symbols = results.map { it.symbol },
                shortDirection = direction == StrategyDirection.Short,
                outcomeMinutes = winTimeframeMinutes(winTimeframe),
                profitPercentage = profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 1.0,
                minimumSamples = 50
            ).associate { it.symbol to it.winRate }
        }
        resultWinRatesLoading = false
    }
    LaunchedEffect(autoScanning, advisorEnabled, strategyScanEnabled, strategyExecutionEnabled, strategyRevision, longEnabled, shortEnabled, minimumWinRateText, profitTargetText, maxAdverseText, winTimeframe, platform, marketType, quoteCurrency, interval, externalMarkets.map { it.pair }) {
        if (!autoScanning) {
            advisorLoading = false
            recommendations = emptyList()
            return@LaunchedEffect
        }
        if (!advisorEnabled) {
            recommendations = emptyList()
            advisorLoading = false
            return@LaunchedEffect
        }
        if (!strategyScanEnabled) {
            recommendations = emptyList()
            advisorLoading = false
            liveExecutionMessage = "${activeStrategy.name} heeft nog geen bruikbare scannerregels"
            return@LaunchedEffect
        }
        // Wait until the user has finished typing. Without this debounce every
        // digit launched a complete market scan and triggered API rate limits.
        delay(750)
        val parsedProfitTarget = profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 }
        val parsedMaxAdverse = maxAdverseText.toDoubleOrNull()?.takeIf { it > 0.0 }
        if (parsedProfitTarget == null || parsedMaxAdverse == null) {
            advisorLoading = false
            return@LaunchedEffect
        }
        advisorLoading = true
        advisorProgress = 0
        advisorTotal = 0
        recommendations = emptyList()
        val breakEvenWinRate = parsedMaxAdverse / (parsedProfitTarget + parsedMaxAdverse) * 100.0
        val minimumWinRate = maxOf(
            consensusProfile.minimumWinRate,
            breakEvenWinRate + 2.0,
            if (activeStrategy.id == "strategy_2") 72.0 else 0.0
        ).coerceAtMost(99.0)
        val profitTarget = parsedProfitTarget
        val effectiveMaxAdverse = if (activeStrategy.id == "strategy_2") minOf(parsedMaxAdverse, 1.5) else parsedMaxAdverse
        val allowBoth = !longEnabled && !shortEnabled
        recommendations = when {
            platform == "Hyperliquid" && marketType == "Perpetuals" && quoteCurrency == "USD" -> advisorEngine.analyze(
                minimumWinRate = minimumWinRate,
                profitPercentage = profitTarget,
                maxAdversePercentage = effectiveMaxAdverse,
                outcomeMinutes = winTimeframeMinutes(winTimeframe),
                allowLong = longEnabled || allowBoth,
                allowShort = shortEnabled || allowBoth,
                excludedSymbols = activeWatchlistSymbols,
                onProgress = { partialResults, completed, totalMarkets ->
                    recommendations = partialResults
                    partialResults.filter { it.qualityScore >= effectiveMinimumScore }.forEach { recommendation ->
                        // Strategy 2 already controls candidate selection, but live execution remains
                        // fail-closed until all documented protective orders are technically enforced.
                        if (!strategyExecutionEnabled) return@forEach
                        val balancedLongs = ActiveHyperliquidPositionStore.longCount(context)
                        val balancedShorts = ActiveHyperliquidPositionStore.shortCount(context)
                        if (!DirectionBalanceGate.permits(recommendation.shortDirection, balancedLongs, balancedShorts)) return@forEach
                        val occupiedSlots = ActiveHyperliquidPositionStore.count(context)
                        val activeMaximum = if (activeStrategy.id == "strategy_2") com.tradementor.app.scanner.QuantumShieldCapacityStore.load(context, occupiedSlots) else executionSettings.maxActiveTrades
                        if (occupiedSlots >= activeMaximum) return@forEach
                        val entry = advisorEngine.validateForEntry(
                            recommendation,
                            profitTarget,
                            effectiveMaxAdverse,
                            minimumWinRate,
                            effectiveMinimumScore
                        ) ?: return@forEach
                        val addedAt = System.currentTimeMillis()
                        val added = TradeHistoryStore.addIfPairAvailable(
                            context,
                            TrackedTrade(
                                id = addedAt,
                                symbol = entry.symbol,
                                shortDirection = entry.shortDirection,
                                entryPrice = entry.price,
                                profitPercentage = profitTarget,
                                timeframe = entry.tradeType,
                                startedAt = addedAt,
                                expiresAt = addedAt + 7L * 24 * 60 * 60_000L,
                                historicalWinRate = entry.winRate,
                                remainingWinRate = entry.winRate,
                                exchange = platform,
                                marketType = marketType,
                                quoteCurrency = quoteCurrency,
                                strategyId = activeStrategy.id,
                                strategyName = activeStrategy.name,
                                indicators = entry.indicators,
                                maxAdversePercentage = effectiveMaxAdverse,
                                positionSizeUsd = executionSettings.positionSizeUsd
                            )
                        )
                        if (added) {
                            activeWatchlistSymbols = activeWatchlistSymbols + entry.symbol.uppercase()
                            val intent = runCatching {
                                HyperliquidOrderPlanner.create(
                                    entry.symbol, entry.shortDirection, executionSettings.positionSizeUsd,
                                    (marketLeverages[entry.symbol.uppercase()] ?: 1).let { if (activeStrategy.id == "strategy_2") minOf(it, 3) else it }, entry.price, profitTarget
                                )
                            }.getOrNull()
                            if (intent != null) {
                                OrderIntentStore.addIfAbsent(context, intent)
                                val token = LocalTradingGatewayStore.testToken(context)
                                if (false && token.isNotBlank()) {
                                    runCatching {
                                        tradingGatewayClient.syncMaximum(
                                            LocalTradingGatewayStore.url(context), token, activeMaximum
                                        )
                                        tradingGatewayClient.executeOneTest(
                                            LocalTradingGatewayStore.url(context), token, intent, profitTarget,
                                            effectiveMaxAdverse, activeStrategy.id
                                        )
                                    }.onSuccess { execution ->
                                        liveExecutionMessage = "${execution.symbol} uitgevoerd @ ${scannerPrice(execution.fillPrice)} · TP ${scannerPrice(execution.targetPrice)}"
                                    }.onFailure { failure ->
                                        liveExecutionMessage = "Order niet uitgevoerd: ${failure.message}"
                                    }
                                }
                            }
                        }
                    }
                    advisorProgress = completed
                    advisorTotal = totalMarkets
                }
            )
            platform.equals("Binance", true) && marketType.equals("Spot", true) -> binanceSignalsEngine.analyze(
                markets = externalMarkets,
                analysisTimeframe = interval,
                outcomeMinutes = winTimeframeMinutes(winTimeframe),
                profitPercentage = profitTarget,
                maxAdversePercentage = effectiveMaxAdverse,
                minimumWinRate = minimumWinRate,
                allowLong = longEnabled || allowBoth,
                allowShort = shortEnabled || allowBoth
            )
            else -> emptyList()
        }
        advisorLoading = false
    }

    val qualifiedRecommendations = recommendations.filter { it.qualityScore >= effectiveMinimumScore }
    LaunchedEffect(autoScanning, strategyExecutionEnabled, strategyRevision, advisorLoading, qualifiedRecommendations, activeWatchlistSymbols, platform, marketType, quoteCurrency) {
        if (autoScanning && strategyExecutionEnabled && !advisorLoading && qualifiedRecommendations.isNotEmpty()) {
            val profitTarget = profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 1.0
            val addedSymbols = mutableSetOf<String>()
            qualifiedRecommendations.forEach { recommendation ->
                val balancedLongs = ActiveHyperliquidPositionStore.longCount(context)
                val balancedShorts = ActiveHyperliquidPositionStore.shortCount(context)
                if (!DirectionBalanceGate.permits(recommendation.shortDirection, balancedLongs, balancedShorts)) return@forEach
                val occupiedSlots = ActiveHyperliquidPositionStore.count(context)
                val activeMaximum = if (activeStrategy.id == "strategy_2") com.tradementor.app.scanner.QuantumShieldCapacityStore.load(context, occupiedSlots) else executionSettings.maxActiveTrades
                if (occupiedSlots >= activeMaximum) return@forEach
                val minimumWinRate = minimumWinRateText.toDoubleOrNull()?.coerceIn(0.0, 99.0) ?: consensusProfile.minimumWinRate
                val entry = advisorEngine.validateForEntry(
                    recommendation,
                    profitTarget,
                    maxAdverseText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: consensusProfile.stopLoss,
                    minimumWinRate,
                    consensusProfile.minimumScore
                ) ?: return@forEach
                val addedAt = System.currentTimeMillis()
                val added = TradeHistoryStore.addIfPairAvailable(
                    context,
                    TrackedTrade(
                        id = addedAt,
                        symbol = entry.symbol,
                        shortDirection = entry.shortDirection,
                        entryPrice = entry.price,
                        profitPercentage = profitTarget,
                        timeframe = entry.tradeType,
                        startedAt = addedAt,
                        expiresAt = addedAt + 7L * 24 * 60 * 60_000L,
                        historicalWinRate = entry.winRate,
                        remainingWinRate = entry.winRate,
                        exchange = platform,
                        marketType = marketType,
                        quoteCurrency = quoteCurrency,
                        strategyId = activeStrategy.id,
                        strategyName = activeStrategy.name,
                        indicators = entry.indicators,
                        maxAdversePercentage = entry.maxAdversePercentage,
                        positionSizeUsd = executionSettings.positionSizeUsd
                    )
                )
                if (added) {
                    addedSymbols += entry.symbol.uppercase()
                    val intent = runCatching {
                        HyperliquidOrderPlanner.create(
                            entry.symbol, entry.shortDirection, executionSettings.positionSizeUsd,
                            (marketLeverages[entry.symbol.uppercase()] ?: 1).let { if (activeStrategy.id == "strategy_2") minOf(it, 3) else it }, entry.price, profitTarget
                        )
                    }.getOrNull()
                    if (intent != null) {
                        OrderIntentStore.addIfAbsent(context, intent)
                        val token = LocalTradingGatewayStore.testToken(context)
                        if (false && token.isNotBlank()) {
                            runCatching {
                                tradingGatewayClient.syncMaximum(
                                    LocalTradingGatewayStore.url(context), token, activeMaximum
                                )
                                tradingGatewayClient.executeOneTest(
                                    LocalTradingGatewayStore.url(context), token, intent, profitTarget,
                                    if (activeStrategy.id == "strategy_2") minOf(consensusProfile.stopLoss, 1.5) else consensusProfile.stopLoss,
                                    activeStrategy.id
                                )
                            }.onSuccess { execution ->
                                liveExecutionMessage = "${execution.symbol} uitgevoerd @ ${scannerPrice(execution.fillPrice)} · TP ${scannerPrice(execution.targetPrice)}"
                            }.onFailure { failure -> liveExecutionMessage = "Order niet uitgevoerd: ${failure.message}" }
                        }
                    }
                }
            }
            if (addedSymbols.isNotEmpty()) {
                activeWatchlistSymbols = activeWatchlistSymbols + addedSymbols
            }
        }
    }

    Column(modifier = Modifier.fillMaxSize().padding(horizontal = 12.dp).padding(top = 5.dp, bottom = 10.dp)) {
        liveExecutionMessage?.let { message ->
            Surface(color = if (message.startsWith("Order niet")) Color(0xFF3A1720) else Color(0xFF0B332B), shape = RoundedCornerShape(10.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 5.dp)) {
                Text(message, color = Color.White, fontSize = 9.sp, modifier = Modifier.padding(8.dp))
            }
        }
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f)) {
                Text("Signals", color = Color.White, fontSize = 23.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                val timeframeLabel = conditions.map { it.interval }.distinct().let { if (it.size > 1) "MULTI-TF" else it.firstOrNull() ?: interval }
                Text(
                    if (advisorEnabled) "STERKE SIGNALS · MULTI-TIMEFRAME" else "CUSTOM · ${direction.title} · $timeframeLabel · ${conditions.size} filter${if (conditions.size == 1) "" else "s"}",
                    color = if (advisorEnabled) Color(0xFFFFC857) else accent,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold
                )
            }
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                Surface(
                    color = ScannerBlue,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.size(34.dp).clickable(enabled = !scanning, onClick = onRetry)
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text("↻", color = Color.White, fontSize = 19.sp, fontWeight = FontWeight.Bold)
                    }
                }
                Surface(
                    color = ScannerRaised,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.size(34.dp).clickable(onClick = onSettings)
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text("⚙", color = Color.White, fontSize = 18.sp)
                    }
                }
            }
        }
        Spacer(Modifier.height(5.dp))
        Surface(color = if (autoScanning) Color(0xFF0B2B25) else ScannerPanel, shape = RoundedCornerShape(11.dp), modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth().padding(horizontal = 11.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(if (autoScanning) "Scan & Add to Watchlist · aan" else "Scan & Add to Watchlist · uit", color = if (autoScanning) ScannerGreen else Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                    Text(if (autoScanning) "Kansen worden alleen gevolgd, nooit gekocht" else "Geen nieuwe automatische watchlist-items", color = ScannerMuted, fontSize = 8.sp)
                }
                Switch(
                    checked = autoScanning,
                    onCheckedChange = { enabled ->
                        autoScanning = enabled
                        val current = BackgroundScannerScheduler.load(context) ?: BackgroundScanConfig(
                            enabled = enabled,
                            strategyName = "TradeMentor consensus",
                            requireAll = true,
                            conditions = emptyList(),
                            intervalMinutes = 15,
                            notificationMode = NotificationMode.NewMatches,
                            notificationStyle = NotificationStyle.Silent
                        )
                        BackgroundScannerScheduler.update(context, current.copy(enabled = enabled, intervalMinutes = 15))
                    },
                    colors = SwitchDefaults.colors(checkedThumbColor = Color.White, checkedTrackColor = ScannerGreen)
                )
            }
        }
        Spacer(Modifier.height(4.dp))
        Surface(color = Color(0xFF261F0D), shape = RoundedCornerShape(11.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(horizontal = 11.dp, vertical = 7.dp)) {
                Text("BEVEILIGDE MAINNET-UITVOERING", color = Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.ExtraBold)
                Text("Cloudorders blijven vergrendeld tot de agentwallet- en veiligheidstest is afgerond", color = Color.White, fontSize = 9.sp)
                Text("Iedere echte instap vereist een bevestigde reduce-only take-profit", color = ScannerMuted, fontSize = 8.sp)
            }
        }
        Spacer(Modifier.height(5.dp))
        Surface(
            color = ScannerPanel,
            shape = RoundedCornerShape(11.dp),
            modifier = Modifier.fillMaxWidth().clickable { controlsExpanded = !controlsExpanded }
        ) {
            Row(modifier = Modifier.padding(horizontal = 11.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("$platform · $marketType · $quoteCurrency", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, maxLines = 1)
                    Text(
                        "${when { longEnabled && !shortEnabled -> "LONG"; shortEnabled && !longEnabled -> "SHORT"; else -> "LONG + SHORT" }} · doel ${profitTargetText}% · max. tegen ${maxAdverseText}%",
                        color = ScannerMuted, fontSize = 9.sp, maxLines = 1
                    )
                }
                Text(if (controlsExpanded) "Sluiten  ▲" else "Wijzigen  ▼", color = ScannerBlue, fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
        }
        if (controlsExpanded) {
        Spacer(Modifier.height(4.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            OutlinedTextField(
                value = positionSizeText,
                onValueChange = { value ->
                    positionSizeText = value.filter { it.isDigit() || it == '.' }.take(8)
                    positionSizeText.toDoubleOrNull()?.takeIf { it >= 1.0 }?.let {
                        executionSettings = executionSettings.copy(positionSizeUsd = it)
                        SignalExecutionSettingsStore.save(context, executionSettings)
                    }
                },
                label = { Text("Instapbedrag $") },
                supportingText = { Text("Totale positiewaarde", fontSize = 8.sp) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                singleLine = true,
                modifier = Modifier.weight(1f),
                shape = RoundedCornerShape(12.dp),
                colors = scannerTextFieldColors()
            )
            OutlinedTextField(
                value = if (activeStrategy.id == "strategy_2") "Automatisch" else maxActiveTradesText,
                onValueChange = { value ->
                    if (activeStrategy.id == "strategy_2") return@OutlinedTextField
                    maxActiveTradesText = value.filter(Char::isDigit).take(3)
                    maxActiveTradesText.toIntOrNull()?.takeIf { it > 0 }?.let {
                        executionSettings = executionSettings.copy(maxActiveTrades = it.coerceAtMost(400))
                        SignalExecutionSettingsStore.save(context, executionSettings)
                    }
                },
                label = { Text("Max. actieve trades") },
                supportingText = { Text("Daarna wacht scanner", fontSize = 8.sp) },
                keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number),
                enabled = activeStrategy.id != "strategy_2",
                singleLine = true,
                modifier = Modifier.weight(1f),
                shape = RoundedCornerShape(12.dp),
                colors = scannerTextFieldColors()
            )
        }
        Text("Bij echte orderplaatsing gebruikt TradeMentor automatisch de maximale leverage van die markt. Marge = instapbedrag ÷ leverage.", color = ScannerMuted, fontSize = 8.sp)
        val occupiedSlots = ActiveHyperliquidPositionStore.count(context)
        val displayedMaximum = if (activeStrategy.id == "strategy_2") com.tradementor.app.scanner.QuantumShieldCapacityStore.load(context, occupiedSlots) else executionSettings.maxActiveTrades
        Text("$occupiedSlots echte posities · nog ${(displayedMaximum - occupiedSlots).coerceAtLeast(0)} plaatsen beschikbaar${if (activeStrategy.id == "strategy_2") " · Quantum automatisch" else ""}", color = if (occupiedSlots < displayedMaximum) ScannerGreen else ScannerRed, fontSize = 9.sp, fontWeight = FontWeight.Bold)
        Text("Richtingsbalans: ${ActiveHyperliquidPositionStore.longCount(context)} LONG · ${ActiveHyperliquidPositionStore.shortCount(context)} SHORT · achterstand wordt eerst aangevuld", color = ScannerMuted, fontSize = 8.sp)
        Spacer(Modifier.height(4.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            CompactSignalSelector("EXCHANGE", platform, platformOptions, expanded, { expanded = it }, onPlatform, Modifier.weight(1.25f))
            CompactSignalSelector("TYPE", marketType, marketTypeOptions, typeExpanded, { typeExpanded = it }, onMarketType, Modifier.weight(1f))
            CompactSignalSelector("QUOTE", quoteCurrency, quoteOptions, quoteExpanded, { quoteExpanded = it }, onQuoteCurrency, Modifier.weight(0.8f))
        }
        val fullyActive = platform == "Hyperliquid" && marketType == "Perpetuals" && quoteCurrency == "USD"
        val partiallyActive = platform.equals("Binance", true) && marketType.equals("Spot", true)
        val statusColor = when { fullyActive -> ScannerGreen; partiallyActive -> Color(0xFFFFC857); else -> ScannerMuted }
        Spacer(Modifier.height(4.dp))
        Text(
            when {
                fullyActive -> "● Volledig actief"
                partiallyActive -> "● Deels actief · Custom volgt"
                else -> "● Alleen catalogus"
            },
            color = statusColor,
            fontSize = 9.sp,
            modifier = Modifier.padding(horizontal = 2.dp)
        )
        Spacer(Modifier.height(3.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp), verticalAlignment = Alignment.CenterVertically) {
            Surface(
                color = if (longEnabled) ScannerGreen else ScannerRaised,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.clickable { longEnabled = !longEnabled }
            ) { Text("↗  LONG", color = if (longEnabled) Color.White else ScannerMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 15.dp, vertical = 9.dp)) }
            Surface(
                color = if (shortEnabled) ScannerRed else ScannerRaised,
                shape = RoundedCornerShape(10.dp),
                modifier = Modifier.clickable { shortEnabled = !shortEnabled }
            ) { Text("↘  SHORT", color = if (shortEnabled) Color.White else ScannerMuted, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 15.dp, vertical = 9.dp)) }
        }
        if (!customEnabled) {
            Spacer(Modifier.height(3.dp))
            Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                OutlinedTextField(
                    value = profitTargetText,
                    onValueChange = { profitTargetText = it.filter { char -> char.isDigit() || char == '.' }.take(5) },
                    label = { Text("Profit %") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(12.dp),
                    textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
                    colors = scannerTextFieldColors()
                )
                OutlinedTextField(
                    value = maxAdverseText,
                    onValueChange = { maxAdverseText = it.filter { char -> char.isDigit() || char == '.' }.take(5) },
                    label = { Text("Max. tegen %") },
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                    singleLine = true,
                    modifier = Modifier.weight(1f),
                    shape = RoundedCornerShape(12.dp),
                    textStyle = LocalTextStyle.current.copy(fontSize = 14.sp),
                    colors = scannerTextFieldColors()
                )
            }
            val profit = profitTargetText.toDoubleOrNull()
            val risk = maxAdverseText.toDoubleOrNull()
            if (profit != null && risk != null && profit > 0 && risk > 0) {
                val required = (risk / (profit + risk) * 100.0 + 2.0).coerceAtMost(99.0)
                Text("Sterk vanaf ongeveer ${String.format("%.1f%%", maxOf(65.0, required))} win rate", color = ScannerMuted, fontSize = 9.sp)
            }
            if (!longEnabled && !shortEnabled) Text("Beide richtingen worden onderzocht.", color = Color(0xFF9DB4FF), fontSize = 10.sp)
        }
        }
        Spacer(Modifier.height(3.dp))
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp)) {
            Text("Sterkste kansen", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
            Text(
                "Win rate ${if (winRateDescending) "↓" else "↑"}",
                color = ScannerBlue,
                fontSize = 11.sp,
                modifier = Modifier.clickable { winRateDescending = !winRateDescending }
            )
        }
        Spacer(Modifier.height(7.dp))
        HorizontalDivider(color = ScannerDivider)
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            when {
                advisorEnabled && advisorLoading && recommendations.isEmpty() -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = Color(0xFFFFC857))
                    Spacer(Modifier.height(10.dp))
                    Text("TradeMentor analyseert alle markten…", color = ScannerMuted)
                    Text("$advisorProgress van ${advisorTotal.takeIf { it > 0 } ?: "…"} markten", color = ScannerMuted, fontSize = 10.sp)
                }
                advisorEnabled && recommendations.isEmpty() -> Text(
                    "Er is momenteel geen signaal sterk genoeg. TradeMentor blijft de markt beoordelen.",
                    color = ScannerMuted,
                    textAlign = TextAlign.Center
                )
                advisorEnabled -> Column(modifier = Modifier.fillMaxSize()) {
                    if (advisorLoading) {
                        Text(
                            "$advisorProgress van $advisorTotal markten geanalyseerd · resultaten worden live aangevuld",
                            color = ScannerMuted,
                            fontSize = 10.sp,
                            modifier = Modifier.padding(vertical = 5.dp)
                        )
                    }
                    LazyColumn(modifier = Modifier.weight(1f)) {
                        val availableRecommendations = qualifiedRecommendations.filterNot { it.symbol.uppercase() in activeWatchlistSymbols }
                        val orderedRecommendations = if (winRateDescending) {
                            availableRecommendations.sortedByDescending { it.winRate }
                        } else {
                            availableRecommendations.sortedBy { it.winRate }
                        }
                        items(orderedRecommendations, key = { "${it.symbol}|${it.analysisTimeframe}|${it.shortDirection}" }) { recommendation ->
                            AdvisorResultRow(recommendation) {
                                val addedAt = System.currentTimeMillis()
                                val added = TradeHistoryStore.addIfPairAvailable(
                                    context,
                                    TrackedTrade(
                                        id = addedAt,
                                        symbol = recommendation.symbol,
                                        shortDirection = recommendation.shortDirection,
                                        entryPrice = recommendation.price,
                                        profitPercentage = profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 1.0,
                                        timeframe = recommendation.tradeType,
                                        startedAt = addedAt,
                                        expiresAt = addedAt + 7L * 24 * 60 * 60_000L,
                                        historicalWinRate = recommendation.winRate,
                                        remainingWinRate = recommendation.winRate,
                                        exchange = platform,
                                        marketType = marketType,
                                        quoteCurrency = quoteCurrency,
                                        strategyId = activeStrategy.id,
                                        strategyName = activeStrategy.name,
                                        indicators = recommendation.indicators,
                                        maxAdversePercentage = recommendation.maxAdversePercentage
                                    )
                                )
                                Toast.makeText(
                                    context,
                                    if (added) "${recommendation.symbol}/USD toegevoegd aan Live Watchlist"
                                    else "${recommendation.symbol}/USD staat al actief in Live Watchlist",
                                    Toast.LENGTH_SHORT
                                ).show()
                                if (added) activeWatchlistSymbols = activeWatchlistSymbols + recommendation.symbol.uppercase()
                                if (false && added) {
                                    activeWatchlistSymbols = activeWatchlistSymbols + recommendation.symbol.uppercase()
                                    val testValue = executionSettings.positionSizeUsd.coerceIn(10.0, 12.0)
                                    val intent = runCatching {
                                        HyperliquidOrderPlanner.create(
                                            recommendation.symbol,
                                            recommendation.shortDirection,
                                            testValue,
                                            (marketLeverages[recommendation.symbol.uppercase()] ?: 1).let { if (activeStrategy.id == "strategy_2") minOf(it, 3) else it },
                                            recommendation.price,
                                            profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 1.0
                                        )
                                    }.getOrNull()
                                    if (intent != null) {
                                        OrderIntentStore.addIfAbsent(context, intent)
                                        tradeActionScope.launch {
                                            runCatching {
                                                tradingGatewayClient.syncMaximum(
                                                    LocalTradingGatewayStore.url(context),
                                                    LocalTradingGatewayStore.testToken(context),
                                                    if (activeStrategy.id == "strategy_2") com.tradementor.app.scanner.QuantumShieldCapacityStore.load(context, ActiveHyperliquidPositionStore.count(context)) else executionSettings.maxActiveTrades
                                                )
                                                tradingGatewayClient.executeOneTest(
                                                    LocalTradingGatewayStore.url(context),
                                                    LocalTradingGatewayStore.testToken(context),
                                                    intent,
                                                    profitTargetText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 1.0,
                                                    if (activeStrategy.id == "strategy_2") minOf(consensusProfile.stopLoss, 1.5) else consensusProfile.stopLoss,
                                                    activeStrategy.id
                                                )
                                            }.onSuccess { execution ->
                                                liveExecutionMessage = "${execution.symbol} uitgevoerd @ ${scannerPrice(execution.fillPrice)} · TP ${scannerPrice(execution.targetPrice)}"
                                                Toast.makeText(context, "${execution.symbol}/USD cloudtest uitgevoerd", Toast.LENGTH_LONG).show()
                                            }.onFailure { failure ->
                                                liveExecutionMessage = "Order niet uitgevoerd: ${failure.message}"
                                                Toast.makeText(context, liveExecutionMessage, Toast.LENGTH_LONG).show()
                                            }
                                        }
                                    }
                                }
                            }
                            HorizontalDivider(color = ScannerDivider)
                        }
                    }
                }
                platform != "Hyperliquid" && !platform.equals("Binance", true) -> Text("Voor deze exchange is de historische candleadapter nog niet actief.", color = ScannerMuted)
                platform.equals("Binance", true) -> Text("Binance zelfstandige Signals zijn actief met Custom uit. Custom-filterregels volgen in de volgende adapterstap.", color = ScannerMuted, textAlign = TextAlign.Center)
                conditions.isEmpty() -> Text("Tik op het tandwiel en voeg een filter toe.", color = ScannerMuted)
                scanning -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = ScannerBlue)
                    Spacer(Modifier.height(11.dp))
                    Text("Candles analyseren: $progress van $total", color = Color.White)
                    Spacer(Modifier.height(8.dp))
                    LinearProgressIndicator(progress = { if (total == 0) 0f else progress.toFloat() / total }, modifier = Modifier.fillMaxWidth(0.72f), color = accent, trackColor = ScannerRaised)
                }
                error != null -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(error, color = ScannerRed)
                    Spacer(Modifier.height(10.dp))
                    Button(onClick = onRetry) { Text("Opnieuw scannen") }
                }
                sortedResults.isEmpty() -> Text("Geen paren voldoen nu aan deze strategie.", color = ScannerMuted, textAlign = TextAlign.Center)
                resultWinRatesLoading -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = ScannerBlue)
                    Spacer(Modifier.height(10.dp))
                    Text("Winkansen berekenen voor ${sortedResults.size} resultaten...", color = ScannerMuted)
                }
                sortedResults.none { result ->
                    val minimum = minimumWinRateText.toDoubleOrNull()?.coerceIn(0.0, 100.0) ?: 0.0
                    result.symbol.uppercase() !in activeWatchlistSymbols &&
                        resultWinRates[result.symbol]?.let { it >= minimum } == true
                } -> Text(
                    "Geen resultaten met een betrouwbare winkans vanaf ${minimumWinRateText.ifBlank { "0" }}%.",
                    color = ScannerMuted,
                    textAlign = TextAlign.Center
                )
                else -> LazyColumn(modifier = Modifier.fillMaxSize()) {
                    val minimum = minimumWinRateText.toDoubleOrNull()?.coerceIn(0.0, 100.0) ?: 0.0
                    val filteredResults = sortedResults.filter { result ->
                        result.symbol.uppercase() !in activeWatchlistSymbols &&
                        resultWinRates[result.symbol]?.let { it >= minimum } == true
                    }
                    items(filteredResults, key = { it.symbol }) { result ->
                        CustomResultRow(result, resultWinRates[result.symbol]) { onResultSelected(result) }
                        HorizontalDivider(color = ScannerDivider)
                    }
                }
            }
        }
    }

    if (showSaveDialog) {
        AlertDialog(
            onDismissRequest = { showSaveDialog = false },
            title = { Text("Strategie opslaan") },
            text = {
                Column {
                    Text("TradeMentor heeft een naam voorgesteld. Je mag deze aanpassen.")
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = strategyName,
                        onValueChange = { strategyName = it },
                        label = { Text("Strategienaam") },
                        singleLine = true,
                        colors = scannerTextFieldColors()
                    )
                }
            },
            confirmButton = {
                TextButton(onClick = {
                    if (strategyName.isNotBlank()) {
                        onSaveStrategy(strategyName.trim())
                        showSaveDialog = false
                    }
                }) { Text("Opslaan") }
            },
            dismissButton = {
                TextButton(onClick = { showSaveDialog = false }) { Text("Annuleren") }
            }
        )
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun CompactSignalSelector(
    label: String,
    value: String,
    options: List<String>,
    expanded: Boolean,
    onExpanded: (Boolean) -> Unit,
    onSelected: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    Box(modifier = modifier) {
        Surface(
            color = ScannerPanel,
            shape = RoundedCornerShape(12.dp),
            modifier = Modifier.fillMaxWidth().clickable { onExpanded(true) }
        ) {
            Row(modifier = Modifier.padding(horizontal = 11.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text(label, color = ScannerMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                    Text(value, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
                }
                Text("▾", color = ScannerMuted, fontSize = 12.sp)
            }
        }
        DropdownMenu(expanded = expanded, onDismissRequest = { onExpanded(false) }, modifier = Modifier.background(ScannerPanel)) {
            options.forEach { option ->
                DropdownMenuItem(
                    text = { Text(option, color = if (option == value) ScannerGreen else Color.White) },
                    onClick = { onSelected(option); onExpanded(false) }
                )
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun SignalSelector(
    label: String,
    value: String,
    options: List<String>,
    expanded: Boolean,
    onExpanded: (Boolean) -> Unit,
    onSelected: (String) -> Unit,
    modifier: Modifier = Modifier
) {
    ExposedDropdownMenuBox(expanded = expanded, onExpandedChange = { onExpanded(!expanded) }, modifier = modifier) {
        OutlinedTextField(
            value = value,
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            label = { Text(label) },
            modifier = Modifier.menuAnchor().fillMaxWidth(),
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            colors = scannerTextFieldColors()
        )
        DropdownMenu(expanded = expanded, onDismissRequest = { onExpanded(false) }, modifier = Modifier.background(ScannerPanel)) {
            options.forEach { option ->
                DropdownMenuItem(text = { Text(option, color = Color.White) }, onClick = { onSelected(option); onExpanded(false) })
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun AdvisorResultRow(recommendation: AdvisorRecommendation, onFollow: () -> Unit) {
    val directionColor = if (recommendation.shortDirection) ScannerRed else ScannerGreen
    val assessmentColor = when (recommendation.riskLabel) {
        "Sterk" -> ScannerGreen
        "Voorzichtig" -> Color(0xFFFFC857)
        else -> ScannerRed
    }
    Surface(
        color = ScannerPanel,
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)
    ) {
        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("${recommendation.symbol}/USD", color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Text(
                        "${if (recommendation.shortDirection) "SHORT" else "LONG"} · ${recommendation.tradeType}",
                        color = directionColor,
                        fontSize = 9.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
                Column(horizontalAlignment = Alignment.End) {
                    Text(String.format("%.1f%%", recommendation.winRate), color = winRateColor(recommendation.winRate), fontSize = 17.sp, fontWeight = FontWeight.ExtraBold)
                    Text("Win rate", color = ScannerMuted, fontSize = 9.sp)
                }
            }
            Spacer(Modifier.height(4.dp))
            Surface(color = assessmentColor.copy(alpha = 0.12f), shape = RoundedCornerShape(9.dp), modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(horizontal = 8.dp, vertical = 5.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Column(modifier = Modifier.weight(1f)) {
                            Text("TRADEMENTOR-SCORE", color = assessmentColor, fontSize = 7.sp, fontWeight = FontWeight.ExtraBold)
                            Text(recommendation.riskLabel, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                        }
                        Text("${recommendation.qualityScore.toInt()}", color = assessmentColor, fontSize = 17.sp, fontWeight = FontWeight.ExtraBold)
                        Text("/100", color = ScannerMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(3.dp))
                    Box(modifier = Modifier.fillMaxWidth().height(5.dp).background(ScannerDivider, RoundedCornerShape(20.dp))) {
                        Box(
                            modifier = Modifier.fillMaxWidth((recommendation.qualityScore / 100.0).coerceIn(0.0, 1.0).toFloat())
                                .height(5.dp).background(assessmentColor, RoundedCornerShape(20.dp))
                        )
                    }
                    Spacer(Modifier.height(3.dp))
                    Row {
                        Text("Verwacht ${recommendation.expectedDuration}", color = Color(0xFFB8C7FF), fontSize = 8.sp, modifier = Modifier.weight(1f))
                        Text("Data ${recommendation.confidence}", color = ScannerMuted, fontSize = 8.sp)
                    }
                    Text("Doel +${formatThreshold(kotlin.math.abs((recommendation.targetPrice / recommendation.price - 1.0) * 100.0))}% · max. tegen ${formatThreshold(recommendation.maxAdversePercentage)}%", color = ScannerMuted, fontSize = 8.sp)
                }
            }
            if (recommendation.indicators.isNotEmpty()) {
                Spacer(Modifier.height(4.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(5.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
                    recommendation.indicators.take(4).forEach { indicator ->
                        Surface(color = directionColor.copy(alpha = 0.13f), shape = RoundedCornerShape(8.dp)) {
                            Text(
                                friendlyIndicator(indicator),
                                color = directionColor,
                                fontSize = 8.sp,
                                fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                            )
                        }
                    }
                }
            }
            Spacer(Modifier.height(4.dp))
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 3.dp)) {
                Text("Instap  ${scannerPrice(recommendation.price)}", color = ScannerMuted, fontSize = 9.sp, modifier = Modifier.weight(1f))
                Text("Doel  ${scannerPrice(recommendation.targetPrice)}", color = directionColor, fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(4.dp))
            Surface(
                color = ScannerBlue,
                shape = RoundedCornerShape(8.dp),
                modifier = Modifier.fillMaxWidth().clickable(onClick = onFollow)
            ) {
                Text(
                    "Trade volgen  →",
                    color = Color.White,
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold,
                    textAlign = TextAlign.Center,
                    modifier = Modifier.padding(vertical = 5.dp)
                )
            }
        }
    }
}

private fun friendlyIndicator(indicator: String): String = when (indicator) {
    "Boven bovenste BB" -> "Bovenste Bollinger Band"
    "Onder onderste BB" -> "Onderste Bollinger Band"
    "Bearish EMA-trend" -> "Bearish EMA-trend"
    "Bullish EMA-trend" -> "Bullish EMA-trend"
    "Onder EMA20" -> "Onder EMA20"
    "Boven EMA20" -> "Boven EMA20"
    "Negatief momentum" -> "Dalend momentum"
    "Positief momentum" -> "Stijgend momentum"
    "RSI hoog" -> "RSI overbought"
    "RSI laag" -> "RSI oversold"
    else -> indicator
}

@Composable
private fun CustomResultRow(result: CustomScanSignal, winRate: Double?, recommendedTimeframe: String? = null, onClick: () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(vertical = 12.dp, horizontal = 4.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text("${result.symbol}/USD", color = Color.White, fontWeight = FontWeight.SemiBold)
            if (recommendedTimeframe != null) {
                Text("Advisor · $recommendedTimeframe", color = Color(0xFFFFC857), fontSize = 10.sp)
            }
        }
        Text(scannerPrice(result.price), color = Color.White, modifier = Modifier.weight(0.65f), textAlign = TextAlign.End)
        Text(
            winRate?.let { String.format("%.1f%%", it) } ?: "…",
            color = winRateColor(winRate),
            fontWeight = FontWeight.Bold,
            modifier = Modifier.weight(0.75f),
            textAlign = TextAlign.End
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun WinChanceScreen(
    result: CustomScanSignal,
    shortDirection: Boolean,
    repository: MarketRepository,
    sourceStrategy: String = "Chart-analyse",
    sourceIndicators: List<String> = emptyList(),
    sourceExchange: String = "Hyperliquid",
    sourceMarketType: String = "Perpetuals",
    sourceQuoteCurrency: String = "USD",
    onBack: () -> Unit
) {
    val context = LocalContext.current
    var profitText by remember(result.symbol) { mutableStateOf("1") }
    var requestedProfit by remember(result.symbol) { mutableStateOf(1.0) }
    var rates by remember(result.symbol) { mutableStateOf<List<TimeframeWinRate>>(emptyList()) }
    var loading by remember(result.symbol) { mutableStateOf(true) }
    var error by remember(result.symbol) { mutableStateOf<String?>(null) }
    var selectedRate by remember(result.symbol) { mutableStateOf<TimeframeWinRate?>(null) }

    LaunchedEffect(profitText) {
        delay(450)
        profitText.replace(',', '.').toDoubleOrNull()
            ?.takeIf { it > 0.0 }
            ?.let { requestedProfit = it }
    }

    LaunchedEffect(result.symbol, requestedProfit, shortDirection) {
        loading = true
        error = null
        try {
            rates = repository.getHistoricalWinRates(result.symbol, requestedProfit, shortDirection)
        } catch (_: Exception) {
            error = "De historische winkansen konden niet worden berekend."
        } finally {
            loading = false
        }
    }

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .combinedClickable(onClick = {}, onDoubleClick = onBack)
            .padding(horizontal = 18.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 16.dp, bottom = 28.dp)
    ) {
        item {
            Text("‹  Scannerresultaten", color = Color(0xFF75A0FF), modifier = Modifier.clickable(onClick = onBack).padding(vertical = 9.dp))
            Spacer(Modifier.height(12.dp))
            Text("${result.symbol}/USD", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
            Text(
                "Historische winkans · ${if (shortDirection) "SHORT" else "LONG"}",
                color = if (shortDirection) ScannerRed else ScannerGreen,
                fontSize = 13.sp,
                fontWeight = FontWeight.Bold
            )
            Spacer(Modifier.height(22.dp))
            Surface(color = ScannerPanel, shape = RoundedCornerShape(18.dp)) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Gewenste profit", color = Color.White, fontWeight = FontWeight.SemiBold)
                    Text("De winkansen worden automatisch herberekend zodra je het percentage wijzigt.", color = ScannerMuted, fontSize = 12.sp)
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = profitText,
                        onValueChange = { profitText = it },
                        label = { Text("Profit (%)") },
                        suffix = { Text("%") },
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth(),
                        colors = scannerTextFieldColors()
                    )
                }
            }
            Spacer(Modifier.height(20.dp))
            Text("Winkans per timeframe", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text("Doel: ${formatThreshold(requestedProfit)}% profit", color = ScannerMuted, fontSize = 12.sp)
            Spacer(Modifier.height(10.dp))
            Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 8.dp)) {
                Text("Timeframe", color = ScannerMuted, modifier = Modifier.weight(1f))
                Text("Slagingskans", color = ScannerMuted, modifier = Modifier.weight(1f), textAlign = TextAlign.End)
            }
            HorizontalDivider(color = ScannerDivider)
        }
        when {
            loading -> item {
                Box(Modifier.fillMaxWidth().padding(36.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = ScannerBlue)
                }
            }
            error != null -> item { Text(error!!, color = ScannerRed, modifier = Modifier.padding(16.dp)) }
            else -> items(rates.filterNot { it.timeframe == "7 dagen" }, key = { it.timeframe }) { rate ->
                Row(modifier = Modifier.fillMaxWidth().clickable(enabled = rate.sampleCount >= 50) { selectedRate = rate }.padding(horizontal = 14.dp, vertical = 15.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text(rate.timeframe, color = Color.White, fontSize = 16.sp, modifier = Modifier.weight(1f))
                    Text(
                        if (rate.sampleCount < 50) "Onvoldoende data (${rate.sampleCount}/50)" else String.format("%.1f%%", rate.percentage),
                        color = when {
                            rate.sampleCount < 50 -> ScannerMuted
                            rate.percentage >= 70 -> ScannerGreen
                            rate.percentage < 40 -> ScannerRed
                            else -> Color(0xFFFFC857)
                        },
                        fontSize = if (rate.sampleCount < 50) 11.sp else 18.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.weight(1f),
                        textAlign = TextAlign.End
                    )
                }
                HorizontalDivider(color = ScannerDivider)
            }
        }
        item {
            Spacer(Modifier.height(18.dp))
            Text(
                "De winkans telt een situatie als geslaagd zodra het profitdoel binnen de meetperiode wordt geraakt. Resultaten uit het verleden bieden geen garantie.",
                color = ScannerMuted,
                fontSize = 11.sp,
                lineHeight = 16.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }

    selectedRate?.let { rate ->
        AlertDialog(
            onDismissRequest = { selectedRate = null },
            title = { Text("Trade toevoegen?") },
            text = {
                Text(
                    "${result.symbol}/USD · ${if (shortDirection) "SHORT" else "LONG"}\n" +
                        "Doel: ${formatThreshold(requestedProfit)}% binnen ${rate.timeframe}\n" +
                        "Historische winkans: ${String.format("%.1f%%", rate.percentage)}"
                )
            },
            confirmButton = {
                TextButton(onClick = {
                    val now = System.currentTimeMillis()
                    val added = TradeHistoryStore.addIfPairAvailable(
                        context,
                        TrackedTrade(
                            id = now,
                            symbol = result.symbol,
                            shortDirection = shortDirection,
                            entryPrice = result.price,
                            profitPercentage = requestedProfit,
                            timeframe = "TradeMentor",
                            startedAt = now,
                            expiresAt = now + 7L * 24 * 60 * 60_000L,
                            historicalWinRate = rate.percentage,
                            remainingWinRate = rate.percentage,
                            exchange = sourceExchange,
                            marketType = sourceMarketType,
                            quoteCurrency = sourceQuoteCurrency,
                            strategyId = com.tradementor.app.scanner.StrategyProfileStore.activeStrategyId(context),
                            strategyName = com.tradementor.app.scanner.StrategyProfileStore.activeDefinition(context).name,
                            indicators = sourceIndicators
                        )
                    )
                    Toast.makeText(
                        context,
                        if (added) "${result.symbol}/USD toegevoegd aan Live Watchlist"
                        else "${result.symbol}/USD staat al actief in Live Watchlist",
                        Toast.LENGTH_SHORT
                    ).show()
                    selectedRate = null
                }) { Text("Toevoegen") }
            },
            dismissButton = {
                TextButton(onClick = { selectedRate = null }) { Text("Annuleren") }
            }
        )
    }
}

@OptIn(ExperimentalFoundationApi::class, ExperimentalLayoutApi::class, ExperimentalMaterial3Api::class)
@Composable
private fun StrategySettings(
    direction: StrategyDirection,
    onDirection: (StrategyDirection) -> Unit,
    interval: String,
    requireAll: Boolean,
    onRequireAll: (Boolean) -> Unit,
    conditions: List<ScanCondition>,
    onAddCondition: (ScanCondition) -> Unit,
    onRemoveCondition: (Long) -> Unit,
    savedStrategies: List<SavedStrategy>,
    onSaveStrategy: (String) -> Unit,
    onLoadStrategy: (SavedStrategy) -> Unit,
    onDeleteStrategy: (SavedStrategy) -> Unit,
    onBack: () -> Unit
) {
    val context = LocalContext.current
    val existingBackground = remember { BackgroundScannerScheduler.load(context) }
    var selectedMetric by remember { mutableStateOf(ScanMetric.Rsi) }
    var selectedOperator by remember { mutableStateOf(ScanOperator.LessThan) }
    var thresholdText by remember { mutableStateOf("20") }
    var metricExpanded by remember { mutableStateOf(false) }
    var operatorExpanded by remember { mutableStateOf(false) }
    var bollingerConditionExpanded by remember { mutableStateOf(false) }
    var strategyName by remember { mutableStateOf("") }
    var backgroundEnabled by remember { mutableStateOf(existingBackground?.enabled ?: false) }
    var backgroundInterval by remember { mutableStateOf(existingBackground?.intervalMinutes ?: 15L) }
    var notificationMode by remember { mutableStateOf(existingBackground?.notificationMode ?: NotificationMode.NewMatches) }
    var notificationStyle by remember { mutableStateOf(existingBackground?.notificationStyle ?: NotificationStyle.Sound) }
    var backgroundName by remember { mutableStateOf(existingBackground?.strategyName ?: "Mijn scanner") }
    val isBollingerMetric = selectedMetric == ScanMetric.BollingerUpperDistance ||
        selectedMetric == ScanMetric.BollingerLowerDistance

    LazyColumn(modifier = Modifier.fillMaxSize().combinedClickable(onClick = {}, onDoubleClick = onBack).padding(horizontal = 18.dp), contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 12.dp, bottom = 24.dp)) {
        item {
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
                Column {
                    Text("Scannerinstellingen", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.Bold)
                    Text("${conditions.size} actieve voorwaarden", color = ScannerMuted)
                }
                Text("Scannen", color = Color(0xFF75A0FF), modifier = Modifier.clickable(onClick = onBack).padding(10.dp))
            }
            Spacer(Modifier.height(20.dp))
            SettingsBlock("Basis", "Richting en combinatielogica") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    StrategyDirection.entries.forEach { value -> Choice(value.title, value == direction) { onDirection(value) } }
                }
                Spacer(Modifier.height(7.dp))
                FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    Choice("ALLE (AND)", requireAll) { onRequireAll(true) }
                    Choice("ÉÉN OF MEER (OR)", !requireAll) { onRequireAll(false) }
                }
            }
            SettingsBlock("Actieve filters", "Verwijder regels die je niet meer wilt gebruiken") {
                conditions.forEach { condition -> ActiveConditionRow(condition) { onRemoveCondition(condition.id) } }
                if (conditions.isEmpty()) Text("Nog geen filters gekozen.", color = ScannerMuted)
            }
            SettingsBlock("Bollinger Bands", "Kies direct waar de prijs zich ten opzichte van de banden bevindt") {
                Column {
                    PresetRow(
                        1,
                        ScanCondition(
                            id = 0,
                            metric = ScanMetric.BollingerLowerDistance,
                            operator = ScanOperator.LessThan,
                            threshold = 0.0,
                            label = "Prijs lager dan onderste Bollinger Band",
                            interval = interval
                        )
                    ) {
                        onAddCondition(
                            ScanCondition(
                                id = 0,
                                metric = ScanMetric.BollingerLowerDistance,
                                operator = ScanOperator.LessThan,
                                threshold = 0.0,
                                label = "Prijs lager dan onderste Bollinger Band",
                                interval = interval
                            )
                        )
                    }
                    PresetRow(
                        2,
                        ScanCondition(
                            id = 0,
                            metric = ScanMetric.BollingerUpperDistance,
                            operator = ScanOperator.GreaterThan,
                            threshold = 0.0,
                            label = "Prijs hoger dan bovenste Bollinger Band",
                            interval = interval
                        )
                    ) {
                        onAddCondition(
                            ScanCondition(
                                id = 0,
                                metric = ScanMetric.BollingerUpperDistance,
                                operator = ScanOperator.GreaterThan,
                                threshold = 0.0,
                                label = "Prijs hoger dan bovenste Bollinger Band",
                                interval = interval
                            )
                        )
                    }
                }
            }
            SettingsBlock("Eigen filter maken", "Kies eerst een indicator en daarna de gewenste voorwaarde") {
                ExposedDropdownMenuBox(expanded = metricExpanded, onExpandedChange = { metricExpanded = !metricExpanded }) {
                    OutlinedTextField(value = if (isBollingerMetric) "Bollinger Bands" else selectedMetric.title, onValueChange = {}, readOnly = true, label = { Text("Indicator") }, modifier = Modifier.menuAnchor().fillMaxWidth(), trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(metricExpanded) }, colors = scannerTextFieldColors())
                    DropdownMenu(expanded = metricExpanded, onDismissRequest = { metricExpanded = false }, modifier = Modifier.background(ScannerPanel)) {
                        ScanMetric.entries.filter { it != ScanMetric.BollingerLowerDistance }.forEach { metric ->
                            DropdownMenuItem(
                                text = { Text(if (metric == ScanMetric.BollingerUpperDistance) "Bollinger Bands" else metric.title, color = Color.White) },
                                onClick = {
                                    selectedMetric = metric
                                    if (metric == ScanMetric.BollingerUpperDistance) {
                                        selectedOperator = ScanOperator.GreaterThan
                                        thresholdText = "0"
                                    }
                                    metricExpanded = false
                                }
                            )
                        }
                    }
                }
                Spacer(Modifier.height(8.dp))
                if (isBollingerMetric) {
                    ExposedDropdownMenuBox(expanded = bollingerConditionExpanded, onExpandedChange = { bollingerConditionExpanded = !bollingerConditionExpanded }) {
                        OutlinedTextField(
                            value = bollingerConditionLabel(selectedMetric, thresholdText.replace(',', '.').toDoubleOrNull() ?: 0.0),
                            onValueChange = {},
                            readOnly = true,
                            label = { Text("Bollinger-voorwaarde") },
                            modifier = Modifier.menuAnchor().fillMaxWidth(),
                            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(bollingerConditionExpanded) },
                            colors = scannerTextFieldColors()
                        )
                        DropdownMenu(expanded = bollingerConditionExpanded, onDismissRequest = { bollingerConditionExpanded = false }, modifier = Modifier.background(ScannerPanel)) {
                            listOf(
                                Triple(ScanMetric.BollingerLowerDistance, -1.0, "Prijs meer dan 1% onder onderste Bollinger Band"),
                                Triple(ScanMetric.BollingerLowerDistance, 0.0, "Prijs lager dan onderste Bollinger Band"),
                                Triple(ScanMetric.BollingerUpperDistance, 0.0, "Prijs hoger dan bovenste Bollinger Band"),
                                Triple(ScanMetric.BollingerUpperDistance, 1.0, "Prijs meer dan 1% boven bovenste Bollinger Band")
                            ).forEach { (metric, threshold, label) ->
                                DropdownMenuItem(
                                    text = { Text(label, color = Color.White) },
                                    onClick = {
                                        selectedMetric = metric
                                        selectedOperator = if (metric == ScanMetric.BollingerLowerDistance) ScanOperator.LessThan else ScanOperator.GreaterThan
                                        thresholdText = threshold.toString()
                                        bollingerConditionExpanded = false
                                    }
                                )
                            }
                        }
                    }
                } else {
                    ExposedDropdownMenuBox(expanded = operatorExpanded, onExpandedChange = { operatorExpanded = !operatorExpanded }) {
                        OutlinedTextField(value = selectedOperator.words, onValueChange = {}, readOnly = true, label = { Text("Vergelijking") }, modifier = Modifier.menuAnchor().fillMaxWidth(), trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(operatorExpanded) }, colors = scannerTextFieldColors())
                        DropdownMenu(expanded = operatorExpanded, onDismissRequest = { operatorExpanded = false }, modifier = Modifier.background(ScannerPanel)) {
                            ScanOperator.entries.forEach { operator -> DropdownMenuItem(text = { Text(operator.words, color = Color.White) }, onClick = { selectedOperator = operator; operatorExpanded = false }) }
                        }
                    }
                    Spacer(Modifier.height(8.dp))
                    OutlinedTextField(value = thresholdText, onValueChange = { thresholdText = it }, label = { Text("Waarde ${selectedMetric.unit}") }, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.fillMaxWidth(), colors = scannerTextFieldColors())
                }
                Spacer(Modifier.height(9.dp))
                Button(
                    onClick = {
                        thresholdText.replace(',', '.').toDoubleOrNull()?.let { value ->
                            val label = if (isBollingerMetric) bollingerConditionLabel(selectedMetric, value) else customLabel(selectedMetric, selectedOperator, value)
                            onAddCondition(ScanCondition(0, selectedMetric, selectedOperator, value, label))
                        }
                    },
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (isBollingerMetric) "Bollinger-filter toevoegen" else "Eigen filter toevoegen") }
            }
            SettingsBlock("50 populaire presets", "Tik op een instelling om haar aan je strategie toe te voegen") {
                presetConditions().forEachIndexed { index, preset -> PresetRow(index + 1, preset) { onAddCondition(preset) } }
            }
            SettingsBlock("Strategie opslaan", "Bewaar alle huidige instellingen lokaal op dit toestel") {
                OutlinedTextField(value = strategyName, onValueChange = { strategyName = it }, label = { Text("Naam strategie") }, modifier = Modifier.fillMaxWidth(), colors = scannerTextFieldColors())
                Spacer(Modifier.height(8.dp))
                Button(onClick = { if (strategyName.isNotBlank() && conditions.isNotEmpty()) { onSaveStrategy(strategyName.trim()); strategyName = "" } }, modifier = Modifier.fillMaxWidth()) { Text("Strategie opslaan") }
                if (savedStrategies.isNotEmpty()) {
                    Spacer(Modifier.height(12.dp))
                    savedStrategies.forEach { saved -> SavedStrategyRow(saved, { onLoadStrategy(saved) }, { onDeleteStrategy(saved) }) }
                }
            }
            SettingsBlock("Achtergrondscan en notificaties", "Scan ook wanneer TradeMentor niet op het scherm staat") {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    Choice("Achtergrondscan aan", backgroundEnabled) { backgroundEnabled = true }
                    Choice("Uit", !backgroundEnabled) { backgroundEnabled = false }
                }
                Spacer(Modifier.height(9.dp))
                Text("Frequentie", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    listOf(15L, 30L, 60L, 240L).forEach { minutes ->
                        Choice(if (minutes < 60) "$minutes min" else "${minutes / 60} uur", backgroundInterval == minutes) { backgroundInterval = minutes }
                    }
                }
                Spacer(Modifier.height(9.dp))
                Text("Wanneer melden", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                Column {
                    NotificationMode.entries.forEach { mode -> Choice(mode.title, notificationMode == mode) { notificationMode = mode } }
                }
                Spacer(Modifier.height(9.dp))
                Text("Meldingsstijl", color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.SemiBold)
                FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                    NotificationStyle.entries.forEach { style -> Choice(style.title, notificationStyle == style) { notificationStyle = style } }
                }
                Spacer(Modifier.height(9.dp))
                OutlinedTextField(value = backgroundName, onValueChange = { backgroundName = it }, label = { Text("Naam in notificatie") }, modifier = Modifier.fillMaxWidth(), colors = scannerTextFieldColors())
                Spacer(Modifier.height(8.dp))
                Button(
                    onClick = {
                        BackgroundScannerScheduler.update(
                            context,
                            BackgroundScanConfig(
                                enabled = backgroundEnabled,
                                strategyName = backgroundName.ifBlank { "TradeMentor scanner" },
                                requireAll = requireAll,
                                conditions = conditions,
                                intervalMinutes = backgroundInterval,
                                notificationMode = notificationMode,
                                notificationStyle = notificationStyle
                            )
                        )
                    },
                    modifier = Modifier.fillMaxWidth()
                ) { Text(if (backgroundEnabled) "Achtergrondscanner activeren" else "Achtergrondscanner uitschakelen") }
                Spacer(Modifier.height(7.dp))
                Text("Android voert periodieke scans vanaf 15 minuten uit. Batterijbesparing kan het exacte moment iets vertragen.", color = ScannerMuted, fontSize = 11.sp, lineHeight = 16.sp)
            }
            Text("Dubbeltik om terug te flippen en de strategie te scannen.", color = ScannerMuted, fontSize = 12.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        }
    }
}

@Composable
private fun SettingsBlock(title: String, subtitle: String, content: @Composable () -> Unit) {
    Column(modifier = Modifier.fillMaxWidth().padding(bottom = 22.dp)) {
        Text(title, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.SemiBold)
        Text(subtitle, color = ScannerMuted, fontSize = 12.sp)
        Spacer(Modifier.height(9.dp))
        content()
    }
}

@Composable
private fun ActiveConditionRow(condition: ScanCondition, onRemove: () -> Unit) {
    Surface(color = ScannerBlue.copy(alpha = 0.16f), shape = RoundedCornerShape(11.dp), modifier = Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Row(modifier = Modifier.padding(12.dp), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.CenterVertically) {
            Text("${condition.interval} · ${condition.label}", color = Color.White, modifier = Modifier.weight(1f), fontSize = 13.sp)
            Text("Verwijder", color = ScannerRed, fontSize = 11.sp, modifier = Modifier.clickable(onClick = onRemove).padding(5.dp))
        }
    }
}

@Composable
private fun PresetRow(number: Int, condition: ScanCondition, onAdd: () -> Unit) {
    Row(modifier = Modifier.fillMaxWidth().clickable(onClick = onAdd).padding(vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(number.toString().padStart(2, '0'), color = ScannerBlue, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(end = 10.dp))
        Column(modifier = Modifier.weight(1f)) {
            Text(condition.label, color = Color.White, fontSize = 13.sp)
            Text(condition.metric.title, color = ScannerMuted, fontSize = 10.sp)
        }
        Text("+", color = ScannerGreen, fontSize = 20.sp)
    }
    HorizontalDivider(color = ScannerDivider)
}

@Composable
private fun SavedStrategyRow(saved: SavedStrategy, onLoad: () -> Unit, onDelete: () -> Unit) {
    Surface(color = ScannerPanel, shape = RoundedCornerShape(11.dp), modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Row(modifier = Modifier.padding(11.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(modifier = Modifier.weight(1f).clickable(onClick = onLoad)) {
                Text(saved.name, color = Color.White, fontWeight = FontWeight.SemiBold)
                Text("${saved.direction.title} · ${saved.interval} · ${saved.conditions.size} filters", color = ScannerMuted, fontSize = 11.sp)
            }
            Text("Laden", color = ScannerBlue, fontSize = 11.sp, modifier = Modifier.clickable(onClick = onLoad).padding(6.dp))
            Text("Wis", color = ScannerRed, fontSize = 11.sp, modifier = Modifier.clickable(onClick = onDelete).padding(6.dp))
        }
    }
}

@Composable
private fun Choice(label: String, selected: Boolean, onClick: () -> Unit) {
    FilterChip(selected = selected, onClick = onClick, label = { Text(label) }, colors = FilterChipDefaults.filterChipColors(containerColor = ScannerPanel, labelColor = ScannerMuted, selectedContainerColor = ScannerBlue, selectedLabelColor = Color.White))
}

@Composable
private fun scannerTextFieldColors() = OutlinedTextFieldDefaults.colors(
    focusedContainerColor = ScannerPanel,
    unfocusedContainerColor = ScannerPanel,
    focusedTextColor = Color.White,
    unfocusedTextColor = Color.White,
    focusedBorderColor = ScannerBlue,
    unfocusedBorderColor = ScannerDivider
)

private fun customLabel(metric: ScanMetric, operator: ScanOperator, value: Double) =
    "${metric.title} ${operator.words} ${formatThreshold(value)}${if (metric.unit.isBlank()) "" else " ${metric.unit}"}"

private fun bollingerConditionLabel(metric: ScanMetric, threshold: Double): String = when {
    metric == ScanMetric.BollingerLowerDistance && threshold < 0.0 -> "Prijs meer dan ${formatThreshold(-threshold)}% onder onderste Bollinger Band"
    metric == ScanMetric.BollingerLowerDistance -> "Prijs lager dan onderste Bollinger Band"
    metric == ScanMetric.BollingerUpperDistance && threshold > 0.0 -> "Prijs meer dan ${formatThreshold(threshold)}% boven bovenste Bollinger Band"
    else -> "Prijs hoger dan bovenste Bollinger Band"
}

private fun compactCondition(condition: ScanCondition) = "${condition.interval} ${condition.metric.title} ${condition.operator.words} ${formatThreshold(condition.threshold)}"

private fun formatThreshold(value: Double): String = DecimalFormat("#,##0.####").format(value)

private fun scannerPrice(value: Double): String = DecimalFormat(if (value >= 1_000) "#,##0.00" else if (value >= 1) "0.0000" else "0.########").format(value)

private fun winChanceTimeframes() = listOf(
    "1 min", "3 min", "5 min", "10 min", "15 min", "30 min",
    "1 uur", "2 uur", "4 uur", "6 uur", "8 uur", "12 uur",
    "18 uur", "24 uur", "2 dagen", "3 dagen", "7 dagen"
)

private fun signalIntervalToWinTimeframe(interval: String): String = when (interval) {
    "1m" -> "1 min"
    "3m" -> "3 min"
    "5m" -> "5 min"
    "15m" -> "15 min"
    "30m" -> "30 min"
    "1h" -> "1 uur"
    "2h" -> "2 uur"
    "4h" -> "4 uur"
    "8h" -> "8 uur"
    "12h" -> "12 uur"
    "1d" -> "24 uur"
    "3d" -> "3 dagen"
    "1w" -> "7 dagen"
    else -> "24 uur"
}

private fun compactWinTimeframe(timeframe: String): String = when (timeframe) {
    "1 min" -> "1M"
    "3 min" -> "3M"
    "5 min" -> "5M"
    "10 min" -> "10M"
    "15 min" -> "15M"
    "30 min" -> "30M"
    "1 uur" -> "1H"
    "2 uur" -> "2H"
    "4 uur" -> "4H"
    "6 uur" -> "6H"
    "8 uur" -> "8H"
    "12 uur" -> "12H"
    "18 uur" -> "18H"
    "24 uur" -> "24H"
    "2 dagen" -> "2D"
    "3 dagen" -> "3D"
    "7 dagen" -> "7D"
    else -> timeframe
}

private fun winTimeframeMinutes(timeframe: String): Int = when (timeframe) {
    "1 min" -> 1
    "3 min" -> 3
    "5 min" -> 5
    "10 min" -> 10
    "15 min" -> 15
    "30 min" -> 30
    "1 uur" -> 60
    "2 uur" -> 120
    "4 uur" -> 240
    "6 uur" -> 360
    "8 uur" -> 480
    "12 uur" -> 720
    "18 uur" -> 1_080
    "24 uur" -> 1_440
    "2 dagen" -> 2_880
    "3 dagen" -> 4_320
    "7 dagen" -> 10_080
    else -> 1_440
}

private fun winRateColor(rate: Double?): Color = when {
    rate == null -> ScannerMuted
    rate >= 70.0 -> ScannerGreen
    rate < 40.0 -> ScannerRed
    else -> Color(0xFFFFC857)
}

private fun strategyMatches(
    saved: SavedStrategy,
    direction: StrategyDirection,
    interval: String,
    requireAll: Boolean,
    conditions: List<ScanCondition>
): Boolean {
    if (saved.direction != direction || saved.interval != interval || saved.requireAll != requireAll) return false
    fun signature(condition: ScanCondition) = listOf(
        condition.metric.name,
        condition.operator.name,
        condition.threshold.toString(),
        condition.interval
    ).joinToString("|")
    return saved.conditions.map(::signature).sorted() == conditions.map(::signature).sorted()
}

private fun suggestedStrategyName(
    direction: StrategyDirection,
    interval: String,
    conditions: List<ScanCondition>
): String {
    val indicators = conditions.map { condition ->
        when (condition.metric) {
            ScanMetric.BollingerUpperDistance, ScanMetric.BollingerLowerDistance -> "BB"
            ScanMetric.Ema20Distance -> "EMA20"
            ScanMetric.Ema50Distance -> "EMA50"
            ScanMetric.Sma20Distance -> "SMA20"
            ScanMetric.Sma50Distance -> "SMA50"
            ScanMetric.PriceChange24h -> "24u beweging"
            ScanMetric.DayVolumeUsd, ScanMetric.CandleVolume, ScanMetric.VolumeRatio -> "Volume"
            else -> condition.metric.title.substringBefore(" ")
        }
    }.distinct().take(3)
    val indicatorPart = indicators.ifEmpty { listOf("Strategie") }.joinToString(" + ")
    return "${direction.title} $indicatorPart $interval"
}

private fun presetConditions(): List<ScanCondition> {
    var id = 1L
    fun preset(metric: ScanMetric, operator: ScanOperator, value: Double, label: String) = ScanCondition(id++, metric, operator, value, label)
    return listOf(
        preset(ScanMetric.Rsi, ScanOperator.LessThan, 20.0, "RSI lager dan 20"), preset(ScanMetric.Rsi, ScanOperator.LessThan, 25.0, "RSI lager dan 25"), preset(ScanMetric.Rsi, ScanOperator.LessThan, 30.0, "RSI oversold onder 30"),
        preset(ScanMetric.Rsi, ScanOperator.GreaterThan, 70.0, "RSI overbought boven 70"), preset(ScanMetric.Rsi, ScanOperator.GreaterThan, 75.0, "RSI boven 75"), preset(ScanMetric.Rsi, ScanOperator.GreaterThan, 80.0, "RSI boven 80"),
        preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 1_000_000.0, "24u-volume boven \$1 miljoen"), preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 5_000_000.0, "24u-volume boven \$5 miljoen"), preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 10_000_000.0, "24u-volume boven \$10 miljoen"),
        preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 25_000_000.0, "24u-volume boven \$25 miljoen"), preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 50_000_000.0, "24u-volume boven \$50 miljoen"), preset(ScanMetric.DayVolumeUsd, ScanOperator.GreaterThan, 100_000_000.0, "24u-volume boven \$100 miljoen"),
        preset(ScanMetric.PriceChange24h, ScanOperator.GreaterThan, 1.0, "24u-stijging boven 1%"), preset(ScanMetric.PriceChange24h, ScanOperator.GreaterThan, 3.0, "24u-stijging boven 3%"), preset(ScanMetric.PriceChange24h, ScanOperator.GreaterThan, 5.0, "24u-stijging boven 5%"), preset(ScanMetric.PriceChange24h, ScanOperator.GreaterThan, 10.0, "24u-stijging boven 10%"),
        preset(ScanMetric.PriceChange24h, ScanOperator.LessThan, -1.0, "24u-daling groter dan 1%"), preset(ScanMetric.PriceChange24h, ScanOperator.LessThan, -3.0, "24u-daling groter dan 3%"), preset(ScanMetric.PriceChange24h, ScanOperator.LessThan, -5.0, "24u-daling groter dan 5%"), preset(ScanMetric.PriceChange24h, ScanOperator.LessThan, -10.0, "24u-daling groter dan 10%"),
        preset(ScanMetric.FundingRate, ScanOperator.GreaterThan, 0.01, "Funding boven 0,01%"), preset(ScanMetric.FundingRate, ScanOperator.GreaterThan, 0.03, "Funding boven 0,03%"), preset(ScanMetric.FundingRate, ScanOperator.LessThan, 0.0, "Negatieve funding"), preset(ScanMetric.FundingRate, ScanOperator.LessThan, -0.01, "Funding onder -0,01%"), preset(ScanMetric.FundingRate, ScanOperator.LessThan, -0.03, "Funding onder -0,03%"),
        preset(ScanMetric.OpenInterest, ScanOperator.GreaterThan, 1_000_000.0, "Open interest boven 1 miljoen"), preset(ScanMetric.OpenInterest, ScanOperator.GreaterThan, 10_000_000.0, "Open interest boven 10 miljoen"), preset(ScanMetric.OpenInterest, ScanOperator.GreaterThan, 50_000_000.0, "Open interest boven 50 miljoen"), preset(ScanMetric.OpenInterest, ScanOperator.GreaterThan, 100_000_000.0, "Open interest boven 100 miljoen"),
        preset(ScanMetric.BollingerUpperDistance, ScanOperator.GreaterThan, 0.0, "Prijs hoger dan bovenste Bollinger Band"), preset(ScanMetric.BollingerUpperDistance, ScanOperator.GreaterThan, 1.0, "Prijs meer dan 1% boven de bovenste Bollinger Band"), preset(ScanMetric.BollingerLowerDistance, ScanOperator.LessThan, 0.0, "Prijs lager dan onderste Bollinger Band"), preset(ScanMetric.BollingerLowerDistance, ScanOperator.LessThan, -1.0, "Prijs meer dan 1% onder de onderste Bollinger Band"),
        preset(ScanMetric.Ema20Distance, ScanOperator.GreaterThan, 0.0, "Prijs boven EMA 20"), preset(ScanMetric.Ema20Distance, ScanOperator.LessThan, 0.0, "Prijs onder EMA 20"), preset(ScanMetric.Ema50Distance, ScanOperator.GreaterThan, 0.0, "Prijs boven EMA 50"), preset(ScanMetric.Ema50Distance, ScanOperator.LessThan, 0.0, "Prijs onder EMA 50"),
        preset(ScanMetric.Sma20Distance, ScanOperator.GreaterThan, 0.0, "Prijs boven SMA 20"), preset(ScanMetric.Sma20Distance, ScanOperator.LessThan, 0.0, "Prijs onder SMA 20"), preset(ScanMetric.Sma50Distance, ScanOperator.GreaterThan, 0.0, "Prijs boven SMA 50"), preset(ScanMetric.Sma50Distance, ScanOperator.LessThan, 0.0, "Prijs onder SMA 50"),
        preset(ScanMetric.MacdPercent, ScanOperator.GreaterThan, 0.0, "MACD bullish boven nul"), preset(ScanMetric.MacdPercent, ScanOperator.LessThan, 0.0, "MACD bearish onder nul"),
        preset(ScanMetric.VolumeRatio, ScanOperator.GreaterThan, 1.5, "Candlevolume boven 1,5× gemiddeld"), preset(ScanMetric.VolumeRatio, ScanOperator.GreaterThan, 2.0, "Volume spike boven 2× gemiddeld"), preset(ScanMetric.VolumeRatio, ScanOperator.GreaterThan, 3.0, "Volume spike boven 3× gemiddeld"),
        preset(ScanMetric.Roc14, ScanOperator.GreaterThan, 5.0, "ROC 14 boven 5%"), preset(ScanMetric.Roc14, ScanOperator.LessThan, -5.0, "ROC 14 onder -5%"),
        preset(ScanMetric.Stochastic14, ScanOperator.GreaterThan, 80.0, "Stochastic overbought boven 80"), preset(ScanMetric.Stochastic14, ScanOperator.LessThan, 20.0, "Stochastic oversold onder 20")
    )
}

private fun loadStrategies(context: Context): List<SavedStrategy> = try {
    val json = context.getSharedPreferences("scanner_strategies", Context.MODE_PRIVATE).getString("saved", null) ?: return emptyList()
    Gson().fromJson(json, object : TypeToken<List<SavedStrategy>>() {}.type)
} catch (_: Exception) { emptyList() }

private fun saveStrategies(context: Context, strategies: List<SavedStrategy>) {
    context.getSharedPreferences("scanner_strategies", Context.MODE_PRIVATE).edit().putString("saved", Gson().toJson(strategies)).apply()
}
