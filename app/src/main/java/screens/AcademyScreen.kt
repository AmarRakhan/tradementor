package com.tradementor.app.screens

import android.app.DatePickerDialog
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectHorizontalDragGestures
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.scanner.TrackedTrade
import com.tradementor.app.scanner.TradeHistoryStore
import com.tradementor.app.scanner.TradeOutcome
import com.tradementor.app.scanner.AdvisorEngine
import com.tradementor.app.components.TradeMentorTextButton
import kotlinx.coroutines.delay
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.Calendar
import kotlin.math.roundToInt

private val HistoryBg = Color(0xFF05070B)
private val HistoryPanel = Color(0xFF101722)
private val HistoryMuted = Color(0xFF8C92A3)
private val HistoryGreen = Color(0xFF08C887)
private val HistoryRed = Color(0xFFFF4964)
private val HistoryBlue = Color(0xFF2F68FF)
private val HistoryDivider = Color(0xFF232A38)

private enum class HistoryPeriod(val title: String, val durationMillis: Long?) {
    Week("7 dagen", 7L * 24 * 60 * 60_000),
    Month("30 dagen", 30L * 24 * 60 * 60_000),
    Quarter("90 dagen", 90L * 24 * 60 * 60_000),
    Custom("Vanaf datum", null),
    All("Alles", null)
}

private enum class WatchlistStatus(val title: String) {
    All("Alle trades"),
    Active("Actief"),
    Succeeded("Doel behaald"),
    Failed("Mislukt")
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HistoryScreen(modifier: Modifier = Modifier) {
    val context = LocalContext.current
    val repository = remember { MarketRepository() }
    val advisorEngine = remember(repository) { AdvisorEngine(repository) }
    var trades by remember { mutableStateOf(TradeHistoryStore.load(context)) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var refreshVersion by remember { mutableIntStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }
    var selectedTrade by remember { mutableStateOf<TrackedTrade?>(null) }
    var flippedTradeId by remember { mutableStateOf<Long?>(null) }
    var tradeToDelete by remember { mutableStateOf<TrackedTrade?>(null) }
    var confirmClearAll by remember { mutableStateOf(false) }
    var selectedPeriod by remember { mutableStateOf(HistoryPeriod.Month) }
    var selectedStatus by remember { mutableStateOf(WatchlistStatus.All) }
    var showPeriodDialog by remember { mutableStateOf(false) }
    var customStart by remember { mutableLongStateOf(System.currentTimeMillis() - 30L * 24 * 60 * 60_000) }
    val lastAttempts = remember { mutableMapOf<Long, Long>() }
    val lastAdviceAttempts = remember { mutableMapOf<Long, Long>() }
    val periodTrades = trades.filter { trade ->
        when (selectedPeriod) {
            HistoryPeriod.Custom -> trade.startedAt >= customStart
            HistoryPeriod.All -> true
            else -> selectedPeriod.durationMillis?.let { trade.startedAt >= now - it } ?: true
        }
    }
    val filteredTrades = periodTrades.filter { trade ->
        when (selectedStatus) {
            WatchlistStatus.All -> true
            WatchlistStatus.Active -> trade.isPositionOpen()
            WatchlistStatus.Succeeded -> trade.outcome == TradeOutcome.Succeeded
            WatchlistStatus.Failed -> trade.outcome == TradeOutcome.Failed
        }
    }
    val succeeded = periodTrades.count { it.outcome == TradeOutcome.Succeeded }
    val failed = periodTrades.count { it.outcome == TradeOutcome.Failed }
    val activeCount = trades.count { it.isPositionOpen() }
    val completed = succeeded + failed
    val successRate = if (completed == 0) 0.0 else succeeded * 100.0 / completed
    val averageWinChance = periodTrades.mapNotNull { it.historicalWinRate }.average().takeUnless { it.isNaN() }
    val popularIndicator = periodTrades.flatMap { runCatching { it.indicators }.getOrNull().orEmpty() }.groupingBy { it }.eachCount().maxByOrNull { it.value }?.key
    val popularStrategy = periodTrades.map { runCatching { it.strategyName }.getOrNull().orEmpty() }.filter { it.isNotBlank() && it != "Niet vastgelegd" }
        .groupingBy { it }.eachCount().maxByOrNull { it.value }?.key

    if (selectedTrade != null) {
        TradeHistoryChartScreen(
            trade = selectedTrade!!,
            repository = repository,
            onBack = { selectedTrade = null }
        )
        return
    }

    LaunchedEffect(Unit) {
        while (true) {
            now = System.currentTimeMillis()
            val storedTrades = TradeHistoryStore.load(context)
            if (storedTrades != trades) trades = storedTrades
            delay(2_000)
        }
    }

    LaunchedEffect(refreshVersion) {
        if (refreshVersion == 0) return@LaunchedEffect
        trades = TradeHistoryStore.load(context)
        now = System.currentTimeMillis()
        delay(350)
        refreshing = false
    }

    LaunchedEffect(now) {
        val expired = trades.filter {
            it.outcome == TradeOutcome.Pending && it.expiresAt <= now &&
                now - (lastAttempts[it.id] ?: 0L) >= 30_000L
        }
        if (expired.isEmpty()) return@LaunchedEffect
        var updated = trades
        expired.forEach { trade ->
            lastAttempts[trade.id] = now
            try {
                val barrierOutcome = repository.getTradeBarrierOutcome(
                    trade.symbol,
                    trade.entryPrice,
                    trade.profitPercentage,
                    trade.maxAdversePercentage,
                    trade.shortDirection,
                    trade.startedAt,
                    trade.expiresAt
                )
                updated = updated.map {
                    if (it.id == trade.id) it.copy(
                        outcome = if (barrierOutcome == 1) TradeOutcome.Succeeded else TradeOutcome.Failed,
                        exitAdvice = if (barrierOutcome == -1) "Risicogrens geraakt" else it.exitAdvice
                    ) else it
                }
            } catch (_: Exception) {
                // Pending blijft staan; na 30 seconden volgt automatisch een nieuwe controle.
            }
        }
        if (updated != trades) {
            trades = updated
            TradeHistoryStore.save(context, updated)
        }
    }

    LaunchedEffect(Unit) {
        while (true) {
        val cycleNow = System.currentTimeMillis()
        val openTrades = trades.filter {
            it.isPositionOpen() &&
                cycleNow - (lastAdviceAttempts[it.id] ?: 0L) >= 10_000L
        }
        if (openTrades.isEmpty()) {
            delay(10_000)
            continue
        }
        var updated = trades
        openTrades.forEach { original ->
            lastAdviceAttempts[original.id] = cycleNow
            val trade = updated.firstOrNull { it.id == original.id } ?: return@forEach
            try {
                val barrierOutcome = repository.getTradeBarrierOutcome(
                    trade.symbol,
                    trade.entryPrice,
                    trade.profitPercentage,
                    Double.MAX_VALUE,
                    trade.shortDirection,
                    trade.startedAt,
                    cycleNow
                )
                if (barrierOutcome == 1) {
                    updated = updated.map {
                        if (it.id == trade.id) it.copy(
                            outcome = if (it.outcome == TradeOutcome.Pending) TradeOutcome.Succeeded else it.outcome,
                            closedAt = cycleNow,
                            lateTargetReachedAt = if (it.outcome == TradeOutcome.Failed) cycleNow else null,
                            exitAdvice = if (it.outcome == TradeOutcome.Failed) "Doel later bereikt" else "Doel bereikt",
                            remainingWinRate = 100.0,
                            adviceReason = if (it.outcome == TradeOutcome.Failed) "Het doel is na de modeltermijn alsnog geraakt; de modeluitslag blijft ongewijzigd." else "Het oorspronkelijke profitdoel is geraakt.",
                            adviceUpdatedAt = cycleNow,
                            lastPrice = if (trade.shortDirection) {
                                trade.entryPrice * (1.0 - trade.profitPercentage / 100.0)
                            } else {
                                trade.entryPrice * (1.0 + trade.profitPercentage / 100.0)
                            }
                        ) else it
                    }
                    return@forEach
                }
                val assessment = advisorEngine.assessOpenTrade(trade, cycleNow)
                if (assessment == null) {
                    updated = updated.map {
                        if (it.id == trade.id) it.copy(
                            remainingWinRate = it.remainingWinRate ?: it.historicalWinRate,
                            adviceUpdatedAt = cycleNow,
                            adviceReason = it.adviceReason ?: "Nieuwe marktbeoordeling volgt bij de volgende verversing."
                        ) else it
                    }
                    return@forEach
                }
                val lowChecks = if (assessment.advice == "Lage kans") trade.lowChanceChecks + 1 else 0
                val finalAdvice = if (assessment.advice == "Lage kans" && lowChecks >= 2) "Sluiten overwegen" else assessment.advice
                updated = updated.map {
                    if (it.id == trade.id) it.copy(
                        exitAdvice = finalAdvice,
                        remainingWinRate = assessment.winRate,
                        adviceReason = assessment.reason,
                        adviceUpdatedAt = cycleNow,
                        lowChanceChecks = lowChecks,
                        lastPrice = assessment.currentPrice
                    ) else it
                }
            } catch (_: Exception) {
                // De laatst bekende beoordeling blijft zichtbaar; later volgt een nieuwe poging.
            }
        }
        if (updated != trades) {
            trades = updated
            TradeHistoryStore.save(context, updated)
        }
        delay(10_000)
        }
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = {
            refreshing = true
            refreshVersion++
        },
        modifier = modifier.fillMaxSize().background(HistoryBg)
    ) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 16.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 18.dp, bottom = 20.dp)
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("Live Watchlist", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
                Surface(color = HistoryBlue.copy(alpha = 0.18f), shape = RoundedCornerShape(20.dp), modifier = Modifier.padding(start = 8.dp)) {
                    Text("$activeCount actief", color = Color(0xFF75A0FF), fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp))
                }
                Spacer(Modifier.weight(1f))
            }
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Text("Lopende trades, actuele winkans en gecontroleerde resultaten", color = HistoryMuted, fontSize = 11.sp, modifier = Modifier.weight(1f))
                TradeMentorTextButton(
                    label = "Periode · ${selectedPeriod.title}",
                    onClick = { showPeriodDialog = true },
                    color = Color(0xFF9DB4FF),
                    fontSize = 9.sp
                )
                TradeMentorTextButton(
                    label = "Alles verwijderen",
                    onClick = { confirmClearAll = true },
                    color = HistoryRed,
                    fontSize = 9.sp
                )
            }
            Spacer(Modifier.height(7.dp))
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()),
                horizontalArrangement = Arrangement.spacedBy(7.dp)
            ) {
                WatchlistStatus.entries.forEach { status ->
                    FilterChip(
                        selected = selectedStatus == status,
                        onClick = { selectedStatus = status },
                        label = { Text(if (status == WatchlistStatus.Active) "${status.title} ($activeCount)" else status.title) },
                        colors = FilterChipDefaults.filterChipColors(
                            selectedContainerColor = when (status) {
                                WatchlistStatus.Active -> HistoryBlue
                                WatchlistStatus.Succeeded -> HistoryGreen
                                WatchlistStatus.Failed -> HistoryRed
                                WatchlistStatus.All -> Color(0xFF39445A)
                            },
                            selectedLabelColor = Color.White
                        )
                    )
                }
            }
            Spacer(Modifier.height(10.dp))
            Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                HistoryMetricCard("Geslaagd", succeeded.toString(), HistoryGreen, Modifier.weight(1f))
                HistoryMetricCard("Mislukt", failed.toString(), HistoryRed, Modifier.weight(1f))
                HistoryMetricCard("Score", if (completed == 0) "—" else String.format("%.0f%%", successRate), HistoryBlue, Modifier.weight(1f))
            }
            Spacer(Modifier.height(8.dp))
            Surface(color = HistoryPanel, shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(12.dp)) {
                    Row {
                        Text("Afgerond $completed", color = HistoryMuted, fontSize = 12.sp, modifier = Modifier.weight(1f))
                        Text("Gem. winkans ${averageWinChance?.let { String.format("%.1f%%", it) } ?: "—"}", color = Color(0xFF9DB4FF), fontSize = 12.sp)
                    }
                    Spacer(Modifier.height(7.dp))
                    Text("Populaire indicator: ${popularIndicator ?: "Nog niet vastgelegd"}", color = Color.White, fontSize = 11.sp)
                    Text("Populaire strategie: ${popularStrategy ?: "Nog niet vastgelegd"}", color = Color.White, fontSize = 11.sp, maxLines = 1)
                }
            }
            Spacer(Modifier.height(16.dp))
            Text("Tik op een trade om de kaart om te draaien", color = HistoryMuted, fontSize = 11.sp)
        }

        if (filteredTrades.isEmpty()) {
            item {
                Box(modifier = Modifier.fillMaxWidth().padding(vertical = 70.dp), contentAlignment = Alignment.Center) {
                    Text("Geen ${selectedStatus.title.lowercase()} in de gekozen periode.", color = HistoryMuted, textAlign = TextAlign.Center)
                }
            }
        } else {
            items(filteredTrades, key = { it.id }) { trade ->
                HistoryRow(
                    trade = trade,
                    now = now,
                    flipped = flippedTradeId == trade.id,
                    onFlip = { flippedTradeId = if (flippedTradeId == trade.id) null else trade.id },
                    onOpenChart = { selectedTrade = trade },
                    onDeleteRequested = { tradeToDelete = trade }
                )
                Spacer(Modifier.height(9.dp))
            }
        }
    }
    }

    tradeToDelete?.let { trade ->
        AlertDialog(
            onDismissRequest = { tradeToDelete = null },
            title = { Text("Trade verwijderen?") },
            text = { Text("${trade.symbol}/USD wordt definitief uit Live Watchlist en History verwijderd.") },
            confirmButton = {
                TradeMentorTextButton(
                    label = "Verwijderen",
                    color = HistoryRed,
                    onClick = {
                        trades = trades.filterNot { it.id == trade.id }
                        TradeHistoryStore.save(context, trades)
                        tradeToDelete = null
                    }
                )
            },
            dismissButton = { TradeMentorTextButton(label = "Annuleren", onClick = { tradeToDelete = null }) }
        )
    }
    if (confirmClearAll) {
        AlertDialog(
            onDismissRequest = { confirmClearAll = false },
            title = { Text("Live Watchlist leegmaken?") },
            text = { Text("Dit verwijdert alleen de zichtbare actieve en afgeronde trades. Backtests, consensus en het onverwijderbare leerlogboek met positieve én negatieve uitkomsten blijven behouden.") },
            confirmButton = {
                TradeMentorTextButton(
                    label = "Alles verwijderen",
                    color = HistoryRed,
                    onClick = {
                        trades = emptyList()
                        TradeHistoryStore.save(context, emptyList())
                        confirmClearAll = false
                    }
                )
            },
            dismissButton = { TradeMentorTextButton(label = "Annuleren", onClick = { confirmClearAll = false }) }
        )
    }
    if (showPeriodDialog) {
        AlertDialog(
            onDismissRequest = { showPeriodDialog = false },
            title = { Text("Kies een periode") },
            text = {
                Column {
                    HistoryPeriod.entries.forEach { period ->
                        Surface(
                            color = if (selectedPeriod == period) HistoryBlue.copy(alpha = 0.18f) else Color.Transparent,
                            shape = RoundedCornerShape(10.dp),
                            modifier = Modifier.fillMaxWidth().clickable {
                                if (period == HistoryPeriod.Custom) {
                                    val calendar = Calendar.getInstance().apply { timeInMillis = customStart }
                                    DatePickerDialog(
                                        context,
                                        { _, year, month, day ->
                                            customStart = Calendar.getInstance().apply {
                                                set(year, month, day, 0, 0, 0)
                                                set(Calendar.MILLISECOND, 0)
                                            }.timeInMillis
                                            selectedPeriod = HistoryPeriod.Custom
                                        },
                                        calendar.get(Calendar.YEAR), calendar.get(Calendar.MONTH), calendar.get(Calendar.DAY_OF_MONTH)
                                    ).show()
                                } else selectedPeriod = period
                                showPeriodDialog = false
                            }
                        ) {
                            Row(modifier = Modifier.padding(horizontal = 12.dp, vertical = 11.dp)) {
                                Text(period.title, color = Color.White, modifier = Modifier.weight(1f))
                                if (selectedPeriod == period) Text("✓", color = HistoryBlue, fontWeight = FontWeight.Bold)
                            }
                        }
                    }
                    if (selectedPeriod == HistoryPeriod.Custom) {
                        Text("Vanaf ${SimpleDateFormat("dd-MM-yyyy", Locale.getDefault()).format(Date(customStart))}", color = HistoryMuted, fontSize = 10.sp, modifier = Modifier.padding(start = 12.dp, top = 6.dp))
                    }
                }
            },
            confirmButton = { TradeMentorTextButton(label = "Sluiten", onClick = { showPeriodDialog = false }) }
        )
    }
}

@Composable
private fun HistoryMetricCard(title: String, value: String, color: Color, modifier: Modifier = Modifier) {
    Surface(color = color.copy(alpha = 0.13f), shape = RoundedCornerShape(14.dp), modifier = modifier) {
        Column(modifier = Modifier.padding(horizontal = 10.dp, vertical = 12.dp)) {
            Text(value, color = color, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold)
            Text(title, color = HistoryMuted, fontSize = 10.sp)
        }
    }
}

@Composable
private fun HistoryRow(trade: TrackedTrade, now: Long, flipped: Boolean, onFlip: () -> Unit, onOpenChart: () -> Unit, onDeleteRequested: () -> Unit) {
    val resultColor = when (trade.outcome) {
        TradeOutcome.Pending -> HistoryBlue
        TradeOutcome.Succeeded -> HistoryGreen
        TradeOutcome.Failed -> HistoryRed
        TradeOutcome.ManuallyClosed -> Color(0xFFFFC857)
    }
    val targetPrice = if (trade.shortDirection) {
        trade.entryPrice * (1.0 - trade.profitPercentage / 100.0)
    } else {
        trade.entryPrice * (1.0 + trade.profitPercentage / 100.0)
    }
    val rotation by animateFloatAsState(if (flipped) 180f else 0f, tween(420), label = "history_flip")
    var dragOffset by remember(trade.id) { mutableFloatStateOf(0f) }
    Box(modifier = Modifier.fillMaxWidth().background(HistoryRed.copy(alpha = 0.18f), RoundedCornerShape(16.dp))) {
        Text("Verwijderen", color = HistoryRed, fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.align(Alignment.CenterEnd).padding(end = 18.dp))
    Surface(
        color = HistoryPanel, shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().offset { IntOffset(dragOffset.roundToInt(), 0) }.pointerInput(trade.id) {
            detectHorizontalDragGestures(
                onHorizontalDrag = { _, amount -> dragOffset = (dragOffset + amount).coerceIn(-220f, 0f) },
                onDragEnd = { if (dragOffset < -120f) onDeleteRequested(); dragOffset = 0f },
                onDragCancel = { dragOffset = 0f }
            )
        }.graphicsLayer {
            rotationY = rotation
            cameraDistance = 12f * density
        }.clickable(onClick = onFlip)
    ) {
        if (rotation <= 90f) {
            Row(modifier = Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(modifier = Modifier.weight(1f)) {
                    Text("${trade.symbol}/USD", color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold)
                    Text(if (trade.shortDirection) "SHORT" else "LONG", color = resultColor, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                    Text(
                        when (trade.outcome) {
                            TradeOutcome.Pending -> if (trade.expiresAt <= now) "Controleren" else "Actief"
                            TradeOutcome.Succeeded -> "Doel behaald"
                            TradeOutcome.ManuallyClosed -> "Winst handmatig genomen"
                            TradeOutcome.Failed -> if (trade.lateTargetReachedAt != null) "Doel later behaald" else if (trade.isPositionOpen()) "Niet op tijd · blijft open" else "Niet op tijd"
                        }, color = resultColor, fontSize = 9.sp, fontWeight = FontWeight.Bold
                    )
                }
                Column(horizontalAlignment = Alignment.End, modifier = Modifier.weight(0.72f)) {
                    Text("BIJ INSTAP", color = HistoryMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                    Text(
                        trade.historicalWinRate?.let { String.format("%.1f%%", it) } ?: "—",
                        color = Color(0xFF9DB4FF),
                        fontSize = 15.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                }
                Column(horizontalAlignment = Alignment.End, modifier = Modifier.weight(0.72f)) {
                    Text("HUIDIG", color = HistoryMuted, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                    Text(
                        trade.remainingWinRate?.let { String.format("%.1f%%", it) } ?: "Berekenen…",
                        color = trade.remainingWinRate?.let { if (it >= 50) HistoryGreen else if (it >= 25) Color(0xFFFFC857) else HistoryRed } ?: Color(0xFF9DB4FF),
                        fontSize = 15.sp,
                        fontWeight = FontWeight.ExtraBold
                    )
                    Text("elke 10 sec", color = HistoryMuted, fontSize = 7.sp)
                }
            }
        } else {
            Column(modifier = Modifier.graphicsLayer { rotationY = 180f }.padding(14.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("${trade.symbol}/USD · details", color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text("Tik om terug te draaien", color = HistoryMuted, fontSize = 9.sp)
                }
                Spacer(Modifier.height(9.dp))
                HistoryDetailLine("Toegevoegd", formatHistoryDate(trade.startedAt))
                HistoryDetailLine("Looptijd", "${trade.timeframe} · eindigt ${formatHistoryDate(trade.expiresAt)}")
                HistoryDetailLine("Profitdoel", "${formatHistoryNumber(trade.profitPercentage)}%")
                HistoryDetailLine("Max. tegenbeweging", "${formatHistoryNumber(trade.maxAdversePercentage)}%")
                HistoryDetailLine("Markt", "${trade.exchange} · ${trade.marketType} · ${trade.quoteCurrency}")
                HistoryDetailLine("Strategie", trade.strategyName)
                if (trade.indicators.isNotEmpty()) HistoryDetailLine("Indicatoren", trade.indicators.joinToString(", "))
                HistoryDetailLine(
                    "Winkans bij toevoegen",
                    trade.historicalWinRate?.let { String.format("%.1f%%", it) } ?: "Niet vastgelegd"
                )
                HistoryDetailLine(
                    "Huidige winkans",
                    trade.remainingWinRate?.let { String.format("%.1f%%", it) } ?: "Wordt berekend"
                )
                trade.exitAdvice?.let { HistoryDetailLine("Actueel advies", it) }
                trade.remainingWinRate?.let { HistoryDetailLine("Resterende winkans", String.format("%.1f%%", it)) }
                trade.adviceReason?.let { HistoryDetailLine("Reden", it) }
                HistoryDetailLine(
                    "Koers",
                    "Instap ${formatHistoryNumber(trade.entryPrice)}  →  doel ${formatHistoryNumber(targetPrice)}"
                )
                Spacer(Modifier.height(10.dp))
                Surface(color = HistoryBlue, shape = RoundedCornerShape(9.dp), modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenChart)) {
                    Text("Open koersgrafiek", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.padding(vertical = 9.dp))
                }
            }
        }
    }
    }
}

@Composable
private fun HistoryDetailLine(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(vertical = 2.dp)) {
        Text(label, color = HistoryMuted, fontSize = 10.sp, modifier = Modifier.weight(0.9f))
        Text(value, color = Color(0xFFD5D9E2), fontSize = 10.sp, modifier = Modifier.weight(1.4f), textAlign = TextAlign.End)
    }
}

private fun formatRemaining(millis: Long): String {
    val totalMinutes = (millis.coerceAtLeast(0L) + 59_999L) / 60_000L
    val days = totalMinutes / (24 * 60)
    val hours = (totalMinutes % (24 * 60)) / 60
    val minutes = totalMinutes % 60
    return when {
        days > 0 -> "${days}d ${hours}u"
        hours > 0 -> "${hours}u ${minutes}m"
        else -> "${minutes}m"
    }
}

private fun formatHistoryNumber(value: Double): String = DecimalFormat("#,##0.####").format(value)

private fun formatHistoryDate(timestamp: Long): String =
    SimpleDateFormat("dd-MM-yyyy HH:mm", Locale.getDefault()).format(Date(timestamp))
