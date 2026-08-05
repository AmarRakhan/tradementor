package com.tradementor.app.screens

import android.content.Context
import android.content.ContentValues
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper
import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.scanner.BacktestEngine
import com.tradementor.app.scanner.BacktestReport
import com.tradementor.app.scanner.BacktestTrade
import com.tradementor.app.scanner.ConsensusProfileStore
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.launch

@Composable
fun BacktestScreen(
    repository: MarketRepository,
    profitPercentage: Double,
    maxAdversePercentage: Double,
    onBack: () -> Unit,
    showBackButton: Boolean = true
) {
    val engine = remember(repository) { BacktestEngine(repository) }
    val context = LocalContext.current
    var weeks by remember { mutableIntStateOf(4) }
    var count by remember { mutableIntStateOf(50) }
    var runId by remember { mutableIntStateOf(0) }
    var loading by remember { mutableStateOf(false) }
    var progress by remember { mutableIntStateOf(0) }
    var total by remember { mutableIntStateOf(0) }
    var report by remember { mutableStateOf<BacktestReport?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var adverseDescending by remember { mutableStateOf(false) }
    var amountText by remember { mutableStateOf("10") }
    var startingCapitalText by remember { mutableStateOf("100") }
    var stopLossText by remember { mutableStateOf("20.5") }
    var appliedStopLoss by remember { mutableStateOf(20.5) }
    var profitText by remember { mutableStateOf(String.format(java.util.Locale.US, "%.1f", profitPercentage)) }
    var appliedProfit by remember { mutableStateOf(profitPercentage) }
    var minimumWinRateText by remember { mutableStateOf("0") }
    var profitReports by remember { mutableStateOf<Map<Double, BacktestReport>>(emptyMap()) }
    var optimizationLabel by remember { mutableStateOf("") }
    var archiveVisible by remember { mutableStateOf(false) }
    var archivedRuns by remember { mutableStateOf(loadArchivedBacktests(context)) }

    if (archiveVisible) {
        BacktestArchiveScreen(onBack = { archiveVisible = false })
        return
    }

    LaunchedEffect(runId) {
        loading = true
        error = null
        progress = 0
        total = 0
        report = null
        profitReports = emptyMap()
        try {
            val selectedStopLoss = stopLossText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: maxAdversePercentage
            val selectedProfit = profitText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: profitPercentage
            appliedStopLoss = selectedStopLoss
            appliedProfit = selectedProfit
            val targets = (listOf(selectedProfit, 0.5, 1.0, 1.5, 2.0, 3.0, 5.0)).distinct().sorted()
            val collected = linkedMapOf<Double, BacktestReport>()
            val completedRunId = System.currentTimeMillis()
            targets.forEachIndexed { targetIndex, target ->
                optimizationLabel = "Profitdoel ${targetIndex + 1} van ${targets.size}: ${String.format("%.2f", target)}%"
                val targetReport = engine.run(weeks, count, target, selectedStopLoss) { done, all ->
                    progress = targetIndex * all + done
                    total = targets.size * all
                }
                collected[target] = targetReport
                profitReports = collected.toMap()
                if (kotlin.math.abs(target - selectedProfit) < 0.0001) report = targetReport
            }
            savePredictionLedger(context, completedRunId, selectedStopLoss, collected)
            val startCapital = startingCapitalText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 100.0
            val stake = amountText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 10.0
            val winRateFloor = minimumWinRateText.toDoubleOrNull()?.coerceIn(0.0, 100.0) ?: 0.0
            collected.map { (target, targetReport) ->
                target to optimizeSettings(targetReport, startCapital, stake, target, selectedStopLoss, winRateFloor)
            }.maxByOrNull { it.second.validationRoi }?.let { (bestProfit, bestSettings) ->
                saveArchivedBacktest(
                    context,
                    ArchivedBacktest(
                        id = completedRunId,
                        createdAt = completedRunId,
                        weeks = weeks,
                        requestedSignals = count,
                        profitTarget = bestProfit,
                        stopLoss = bestSettings.stopLoss,
                        minimumWinRate = bestSettings.minimumWinRate,
                        minimumScore = bestSettings.minimumScore,
                        direction = when (bestSettings.direction) { true -> "SHORT"; false -> "LONG"; null -> "LONG + SHORT" },
                        validationRoi = bestSettings.validationRoi,
                        validationTrades = bestSettings.validationTrades
                    )
                )
                archivedRuns = loadArchivedBacktests(context)
            }
            loading = false
        } catch (cancelled: CancellationException) {
            throw cancelled
        } catch (failure: Throwable) {
            error = failure.message ?: "Backtest kon niet worden uitgevoerd."
            loading = false
        }
    }

    Column(Modifier.fillMaxSize().background(Color(0xFF05070B)).padding(horizontal = 12.dp, vertical = 8.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            if (showBackButton) {
                Text("‹", color = Color.White, fontSize = 32.sp, modifier = Modifier.clickable(onClick = onBack).padding(end = 12.dp))
            }
            Column(Modifier.weight(1f)) {
                Text("Historische backtest", color = Color.White, fontSize = 21.sp, fontWeight = FontWeight.Bold, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.fillMaxWidth())
                Text("Zonder toekomstige informatie", color = Color(0xFF08C887), fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
            Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
                Surface(color = Color(0xFF151C29), shape = RoundedCornerShape(9.dp), modifier = Modifier.clickable { archiveVisible = true }) {
                    Text("Archief", color = Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 9.dp, vertical = 7.dp))
                }
                Surface(color = Color(0xFF2F68FF), shape = RoundedCornerShape(9.dp), modifier = Modifier.clickable { runId++ }) {
                    Text("Opnieuw", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp))
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        ArchiveConsensusCard(archivedRuns, onOpenArchive = { archiveVisible = true })
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf(4, 12, 26, 52, 104).forEach { option -> BacktestChoice(if (option == 104) "2 jaar" else "$option wk", weeks == option) { weeks = option; runId++ } }
        }
        Spacer(Modifier.height(5.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Aantal historische signals", color = Color(0xFF8C92A3), fontSize = 8.sp, modifier = Modifier.weight(1f))
            listOf(50, 100, 250).forEach { option -> BacktestChoice("$option", count == option) { count = option; runId++ } }
        }
        Spacer(Modifier.height(5.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            BacktestNumberField("Startkapitaal $", startingCapitalText, { startingCapitalText = it }, Modifier.weight(1f))
            BacktestNumberField("Inzet per trade $", amountText, { amountText = it }, Modifier.weight(1f))
        }
        Spacer(Modifier.height(5.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(7.dp)) {
            BacktestNumberField("Profitdoel %", profitText, { profitText = it }, Modifier.weight(1f))
            BacktestNumberField("Max. tegen / stoploss %", stopLossText, { stopLossText = it }, Modifier.weight(1f))
        }
        Spacer(Modifier.height(5.dp))
        BacktestNumberField("Min. voorspelde winrate %", minimumWinRateText, { minimumWinRateText = it }, Modifier.fillMaxWidth())
        Spacer(Modifier.height(8.dp))
        if (loading) {
            val fraction = if (total == 0) 0f else progress.toFloat() / total
            Surface(color = Color(0xFF101725), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
                Column(Modifier.padding(12.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        CircularProgressIndicator(color = Color(0xFF2F68FF), strokeWidth = 3.dp, modifier = Modifier.height(24.dp))
                        Spacer(Modifier.padding(horizontal = 6.dp))
                        Column(Modifier.weight(1f)) {
                            Text("Backtest wordt berekend", color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold)
                            Text("$weeks weken · $count signals · $optimizationLabel", color = Color(0xFF8C92A3), fontSize = 8.sp)
                        }
                        Text("${(fraction * 100).toInt()}%", color = Color(0xFF08C887), fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    }
                    Spacer(Modifier.height(9.dp))
                    LinearProgressIndicator(progress = { fraction }, modifier = Modifier.fillMaxWidth().height(7.dp), color = Color(0xFF2F68FF), trackColor = Color(0xFF232A38))
                    Text("Historisch meetmoment $progress van ${total.takeIf { it > 0 } ?: "…"} analyseren", color = Color(0xFF8C92A3), fontSize = 8.sp, modifier = Modifier.padding(top = 5.dp))
                }
            }
        }
        error?.let { Text(it, color = Color(0xFFFF4964), modifier = Modifier.padding(vertical = 10.dp)) }
        val currentReport = report
        if (currentReport != null) {
            val minimumWinRate = minimumWinRateText.toDoubleOrNull()?.coerceIn(0.0, 100.0) ?: 0.0
            val filteredReport = BacktestReport(currentReport.trades.filter { it.predictedWinRate >= minimumWinRate })
            val filteredProfitReports = profitReports.ifEmpty { mapOf(appliedProfit to currentReport) }
                .mapValues { (_, candidateReport) -> BacktestReport(candidateReport.trades.filter { it.predictedWinRate >= minimumWinRate }) }
            Spacer(Modifier.height(8.dp))
            BacktestSummary(filteredReport, appliedProfit)
            Spacer(Modifier.height(6.dp))
            BacktestMoneySummary(
                filteredReport,
                startingCapitalText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 100.0,
                amountText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 10.0,
                appliedProfit,
                appliedStopLoss
            )
            Spacer(Modifier.height(6.dp))
            OptimalSettingsCard(
                reports = profitReports.ifEmpty { mapOf(appliedProfit to currentReport) },
                startingCapital = startingCapitalText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 100.0,
                amount = amountText.toDoubleOrNull()?.takeIf { it > 0.0 } ?: 10.0,
                testedMaximum = appliedStopLoss,
                minimumWinRateFloor = minimumWinRate,
                weeks = weeks,
                requestedSignals = count,
                exportEnabled = !loading
            )
            Spacer(Modifier.height(7.dp))
            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Pair en reden", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text("Uitslag", color = Color(0xFF8C92A3), fontSize = 9.sp, modifier = Modifier.padding(end = 12.dp))
                Text(
                    "Max. tegen ${if (adverseDescending) "↓" else "↑"}",
                    color = Color(0xFFFFC857),
                    fontSize = 9.sp,
                    fontWeight = FontWeight.Bold,
                    modifier = Modifier.clickable { adverseDescending = !adverseDescending }.padding(vertical = 7.dp)
                )
            }
            val orderedTrades = if (adverseDescending) filteredReport.trades.sortedByDescending { it.worstAdverseMove }
                else filteredReport.trades.sortedBy { it.worstAdverseMove }
            LazyColumn(Modifier.fillMaxSize()) { items(orderedTrades) { BacktestTradeRow(it) } }
        }
    }
}

private data class ArchivedBacktest(
    val id: Long,
    val createdAt: Long,
    val weeks: Int,
    val requestedSignals: Int,
    val profitTarget: Double,
    val stopLoss: Double,
    val minimumWinRate: Int,
    val minimumScore: Int,
    val direction: String,
    val validationRoi: Double,
    val validationTrades: Int
)

private const val BACKTEST_ARCHIVE_PREFS = "backtest_archive"
private const val BACKTEST_ARCHIVE_KEY = "completed_runs"
private const val BACKTEST_MIGRATION_KEY = "sqlite_migrated_v1"

private class BacktestDatabase(context: Context) : SQLiteOpenHelper(context, "tradementor_research.db", null, 1) {
    override fun onCreate(db: SQLiteDatabase) {
        db.execSQL("""
            CREATE TABLE archived_backtests (
                id INTEGER PRIMARY KEY,
                created_at INTEGER NOT NULL,
                weeks INTEGER NOT NULL,
                requested_signals INTEGER NOT NULL,
                profit_target REAL NOT NULL,
                stop_loss REAL NOT NULL,
                minimum_win_rate INTEGER NOT NULL,
                minimum_score INTEGER NOT NULL,
                direction TEXT NOT NULL,
                validation_roi REAL NOT NULL,
                validation_trades INTEGER NOT NULL,
                synced INTEGER NOT NULL DEFAULT 0
            )
        """.trimIndent())
        db.execSQL("""
            CREATE TABLE prediction_ledger (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                run_id INTEGER NOT NULL,
                profit_target REAL NOT NULL,
                stop_loss REAL NOT NULL,
                symbol TEXT NOT NULL,
                signal_time INTEGER NOT NULL,
                short_direction INTEGER NOT NULL,
                entry_price REAL NOT NULL,
                target_price REAL NOT NULL,
                predicted_win_rate REAL NOT NULL,
                tm_score REAL NOT NULL,
                indicators TEXT NOT NULL,
                succeeded INTEGER NOT NULL,
                stopped INTEGER NOT NULL,
                resolved_hours INTEGER,
                timeframe TEXT NOT NULL,
                favourable_move REAL NOT NULL,
                adverse_move REAL NOT NULL,
                return_percentage REAL NOT NULL,
                synced INTEGER NOT NULL DEFAULT 0,
                UNIQUE(run_id, profit_target, symbol, signal_time)
            )
        """.trimIndent())
        db.execSQL("CREATE INDEX idx_predictions_run ON prediction_ledger(run_id)")
        db.execSQL("CREATE INDEX idx_predictions_signal_time ON prediction_ledger(signal_time)")
    }

    override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit

    fun insertArchive(item: ArchivedBacktest) {
        writableDatabase.insertWithOnConflict("archived_backtests", null, ContentValues().apply {
            put("id", item.id); put("created_at", item.createdAt); put("weeks", item.weeks)
            put("requested_signals", item.requestedSignals); put("profit_target", item.profitTarget)
            put("stop_loss", item.stopLoss); put("minimum_win_rate", item.minimumWinRate)
            put("minimum_score", item.minimumScore); put("direction", item.direction)
            put("validation_roi", item.validationRoi); put("validation_trades", item.validationTrades)
        }, SQLiteDatabase.CONFLICT_REPLACE)
    }

    fun loadArchives(): List<ArchivedBacktest> {
        val items = mutableListOf<ArchivedBacktest>()
        readableDatabase.query("archived_backtests", null, null, null, null, null, "created_at DESC").use { cursor ->
            while (cursor.moveToNext()) items += ArchivedBacktest(
                id = cursor.getLong(cursor.getColumnIndexOrThrow("id")),
                createdAt = cursor.getLong(cursor.getColumnIndexOrThrow("created_at")),
                weeks = cursor.getInt(cursor.getColumnIndexOrThrow("weeks")),
                requestedSignals = cursor.getInt(cursor.getColumnIndexOrThrow("requested_signals")),
                profitTarget = cursor.getDouble(cursor.getColumnIndexOrThrow("profit_target")),
                stopLoss = cursor.getDouble(cursor.getColumnIndexOrThrow("stop_loss")),
                minimumWinRate = cursor.getInt(cursor.getColumnIndexOrThrow("minimum_win_rate")),
                minimumScore = cursor.getInt(cursor.getColumnIndexOrThrow("minimum_score")),
                direction = cursor.getString(cursor.getColumnIndexOrThrow("direction")),
                validationRoi = cursor.getDouble(cursor.getColumnIndexOrThrow("validation_roi")),
                validationTrades = cursor.getInt(cursor.getColumnIndexOrThrow("validation_trades"))
            )
        }
        return items
    }

    fun insertPredictions(runId: Long, stopLoss: Double, reports: Map<Double, BacktestReport>) {
        val db = writableDatabase
        db.beginTransaction()
        try {
            reports.forEach { (profit, report) -> report.trades.forEach { trade ->
                db.insertWithOnConflict("prediction_ledger", null, ContentValues().apply {
                    put("run_id", runId); put("profit_target", profit); put("stop_loss", stopLoss)
                    put("symbol", trade.symbol); put("signal_time", trade.signalTime)
                    put("short_direction", if (trade.shortDirection) 1 else 0)
                    put("entry_price", trade.entryPrice); put("target_price", trade.targetPrice)
                    put("predicted_win_rate", trade.predictedWinRate); put("tm_score", trade.qualityScore)
                    put("indicators", trade.indicators.joinToString("|")); put("succeeded", if (trade.succeeded) 1 else 0)
                    put("stopped", if (trade.stopped) 1 else 0); trade.resolvedAfterHours?.let { put("resolved_hours", it) }
                    put("timeframe", trade.analysisTimeframe); put("favourable_move", trade.bestFavourableMove)
                    put("adverse_move", trade.worstAdverseMove); put("return_percentage", trade.returnPercentage)
                }, SQLiteDatabase.CONFLICT_IGNORE)
            } }
            db.setTransactionSuccessful()
        } finally { db.endTransaction() }
    }
}

private fun database(context: Context): BacktestDatabase {
    val db = BacktestDatabase(context.applicationContext)
    val prefs = context.getSharedPreferences(BACKTEST_ARCHIVE_PREFS, Context.MODE_PRIVATE)
    if (!prefs.getBoolean(BACKTEST_MIGRATION_KEY, false)) {
        val legacyJson = prefs.getString(BACKTEST_ARCHIVE_KEY, null)
        if (legacyJson != null) runCatching {
            Gson().fromJson<List<ArchivedBacktest>>(legacyJson, object : TypeToken<List<ArchivedBacktest>>() {}.type).orEmpty()
        }.getOrDefault(emptyList()).forEach(db::insertArchive)
        prefs.edit().putBoolean(BACKTEST_MIGRATION_KEY, true).apply()
    }
    return db
}

private fun loadArchivedBacktests(context: Context): List<ArchivedBacktest> {
    return database(context).use { it.loadArchives() }
}

private fun saveArchivedBacktest(context: Context, item: ArchivedBacktest) {
    database(context).use { it.insertArchive(item) }
}

private fun savePredictionLedger(context: Context, runId: Long, stopLoss: Double, reports: Map<Double, BacktestReport>) {
    database(context).use { it.insertPredictions(runId, stopLoss, reports) }
}

private enum class ArchiveSort(val label: String) { Date("Datum"), Roi("Rendement"), Profit("Profit"), Stop("Stoploss"), WinRate("Winrate") }

private fun median(values: List<Double>): Double {
    if (values.isEmpty()) return 0.0
    val ordered = values.sorted()
    val middle = ordered.size / 2
    return if (ordered.size % 2 == 0) (ordered[middle - 1] + ordered[middle]) / 2.0 else ordered[middle]
}

@Composable private fun ArchiveConsensusCard(items: List<ArchivedBacktest>, onOpenArchive: () -> Unit) {
    val context = LocalContext.current
    val evidence = remember(items.size) { ConsensusProfileStore.load(context) }
    Surface(color = Color(0xFF132237), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenArchive)) {
        if (items.isEmpty()) {
            Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("ACTIEF SCANNERPROFIEL", color = Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.Bold)
                    Text("Stuurt Signals en automatische Live Trades aan", color = Color(0xFF75A0FF), fontSize = 7.sp, fontWeight = FontWeight.Bold)
                    Text("Voltooi een backtest om het gemiddelde advies op te bouwen.", color = Color(0xFF8C92A3), fontSize = 9.sp)
                }
                Text("Archief →", color = Color(0xFF75A0FF), fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
        } else {
            val profit = median(items.map { it.profitTarget })
            val stop = median(items.map { it.stopLoss })
            val winRate = median(items.map { it.minimumWinRate.toDouble() }).toInt()
            val scores = items.filter { it.minimumScore > 0 }.map { it.minimumScore.toDouble() }
            val score = median(scores).toInt()
            val direction = items.groupingBy { it.direction }.eachCount().maxByOrNull { it.value }?.key ?: "LONG + SHORT"
            val totalTrades = items.sumOf { it.validationTrades }
            val weightedRoi = if (totalTrades > 0) items.sumOf { it.validationRoi * it.validationTrades } / totalTrades else 0.0
            val reliability = when {
                evidence.historicalSituations >= 2_000 && evidence.completedLiveTrades >= 100 -> "STERK"
                evidence.historicalSituations >= 500 && evidence.completedLiveTrades >= 25 -> "REDELIJK"
                else -> "IN OPBOUW"
            }
            Column(Modifier.padding(10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("ACTIEF SCANNERPROFIEL", color = Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.Bold)
                        Text("Stuurt Signals en automatische Live Trades aan", color = Color(0xFF75A0FF), fontSize = 7.sp, fontWeight = FontWeight.Bold)
                    }
                    Column(horizontalAlignment = Alignment.End) {
                        Text(reliability, color = if (reliability == "STERK") Color(0xFF08C887) else Color(0xFFFFC857), fontSize = 8.sp, fontWeight = FontWeight.Bold)
                        Text(String.format("%+.2f%%", weightedRoi), color = if (weightedRoi >= 0) Color(0xFF08C887) else Color(0xFFFF4964), fontSize = 15.sp, fontWeight = FontWeight.Bold)
                    }
                }
                Text("${evidence.sourceRuns} runs · ${evidence.historicalSituations} historische situaties · ${evidence.validationTrades} controletrades", color = Color(0xFF8C92A3), fontSize = 7.sp, modifier = Modifier.padding(top = 4.dp))
                Text("${evidence.completedLiveTrades} echte uitkomsten · ${evidence.liveWins} winst / ${evidence.liveLosses} verlies", color = Color(0xFF8C92A3), fontSize = 7.sp)
                Spacer(Modifier.height(7.dp))
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    SummaryValue("${String.format("%.2f", profit)}%", "Profitdoel", Color(0xFFFFC857))
                    SummaryValue("${String.format("%.2f", stop)}%", "Max. tegen", Color.White)
                    SummaryValue(if (winRate == 0) "Geen filter" else "$winRate+", "Min. winrate", Color.White)
                    SummaryValue(if (scores.isEmpty()) "Alle" else "$score+", "TM-score", Color.White)
                    SummaryValue(direction, "Richting", Color.White)
                }
                Text("Backtests bepalen dit profiel; echte afgeronde trades versterken later de keuze. Tik voor bewijsarchief.", color = Color(0xFF8C92A3), fontSize = 7.sp, modifier = Modifier.padding(top = 5.dp))
            }
        }
    }
}

@Composable private fun BacktestArchiveScreen(onBack: () -> Unit) {
    val context = LocalContext.current
    var sort by remember { mutableStateOf(ArchiveSort.Date) }
    var descending by remember { mutableStateOf(true) }
    val archive = remember { loadArchivedBacktests(context) }
    val ordered = remember(archive, sort, descending) {
        val sorted = when (sort) {
            ArchiveSort.Date -> archive.sortedBy { it.createdAt }
            ArchiveSort.Roi -> archive.sortedBy { it.validationRoi }
            ArchiveSort.Profit -> archive.sortedBy { it.profitTarget }
            ArchiveSort.Stop -> archive.sortedBy { it.stopLoss }
            ArchiveSort.WinRate -> archive.sortedBy { it.minimumWinRate }
        }
        if (descending) sorted.reversed() else sorted
    }
    Column(Modifier.fillMaxSize().background(Color(0xFF05070B)).padding(12.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("‹", color = Color.White, fontSize = 32.sp, modifier = Modifier.clickable(onClick = onBack).padding(end = 12.dp))
            Column(Modifier.weight(1f)) {
                Text("Backtestarchief", color = Color.White, fontSize = 21.sp, fontWeight = FontWeight.Bold)
                Text("${archive.size} volledig afgeronde backtests", color = Color(0xFF8C92A3), fontSize = 9.sp)
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(5.dp)) {
            ArchiveSort.entries.forEach { option ->
                Surface(color = if (sort == option) Color(0xFF2F68FF) else Color(0xFF151C29), shape = RoundedCornerShape(8.dp), modifier = Modifier.clickable {
                    if (sort == option) descending = !descending else { sort = option; descending = true }
                }) {
                    Text(option.label + if (sort == option) if (descending) " ↓" else " ↑" else "", color = if (sort == option) Color.White else Color(0xFF8C92A3), fontSize = 8.sp, modifier = Modifier.padding(horizontal = 7.dp, vertical = 6.dp))
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        if (ordered.isEmpty()) Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            Text("Nog geen volledig afgeronde backtest opgeslagen.", color = Color(0xFF8C92A3))
        } else LazyColumn(Modifier.fillMaxSize()) {
            items(ordered, key = { it.id }) { item -> ArchivedBacktestCard(item) }
        }
    }
}

@Composable private fun ArchivedBacktestCard(item: ArchivedBacktest) {
    Surface(color = Color(0xFF10291F), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp)) {
        Column(Modifier.padding(10.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(SimpleDateFormat("dd MMM yyyy · HH:mm", Locale("nl", "NL")).format(Date(item.createdAt)), color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    Text("${if (item.weeks == 104) "2 jaar" else "${item.weeks} weken"} · maximaal ${item.requestedSignals} signals · ${item.validationTrades} controletrades", color = Color(0xFF8C92A3), fontSize = 8.sp)
                }
                Text(String.format("%+.2f%%", item.validationRoi), color = if (item.validationRoi >= 0) Color(0xFF08C887) else Color(0xFFFF4964), fontSize = 16.sp, fontWeight = FontWeight.Bold)
            }
            Spacer(Modifier.height(7.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                SummaryValue("${String.format("%.2f", item.profitTarget)}%", "Profitdoel", Color(0xFFFFC857))
                SummaryValue("${String.format("%.2f", item.stopLoss)}%", "Max. tegen", Color.White)
                SummaryValue(if (item.minimumWinRate == 0) "Geen filter" else "${item.minimumWinRate}+", "Min. winrate", Color.White)
                SummaryValue(if (item.minimumScore == 0) "Alle" else "${item.minimumScore}+", "TM-score", Color.White)
                SummaryValue(item.direction, "Richting", Color.White)
            }
        }
    }
}

private data class StopLossSuggestion(val percentage: Double, val netResult: Double, val medianWinnerAdverse: Double)

private data class OptimizedSettings(
    val stopLoss: Double,
    val minimumScore: Int,
    val minimumWinRate: Int,
    val direction: Boolean?,
    val trainingRoi: Double,
    val validationRoi: Double,
    val validationTrades: Int,
    val validationInvested: Double,
    val validationEnding: Double
)

private data class PortfolioResult(
    val startingCapital: Double,
    val endingCapital: Double,
    val turnover: Double,
    val executedTrades: Int,
    val skippedTrades: Int,
    val maxDrawdown: Double
) { val roi: Double get() = (endingCapital - startingCapital) / startingCapital.coerceAtLeast(0.01) * 100.0 }

private data class StrategyEvaluation(val roi: Double, val invested: Double, val ending: Double, val count: Int)

private data class VirtualPosition(val closesAt: Long, val stake: Double, val payout: Double)

private fun simulatePortfolio(
    trades: List<BacktestTrade>,
    startingCapital: Double,
    amount: Double,
    profitPercentage: Double,
    stopLoss: Double,
    minimumScore: Int = 0,
    direction: Boolean? = null
): PortfolioResult {
    var cash = startingCapital
    var turnover = 0.0
    var executed = 0
    var skipped = 0
    var peak = startingCapital
    var maxDrawdown = 0.0
    val open = mutableListOf<VirtualPosition>()

    fun release(until: Long) {
        val closing = open.filter { it.closesAt <= until }
        closing.forEach { cash += it.payout }
        open.removeAll(closing.toSet())
        val equity = cash + open.sumOf { it.stake }
        peak = maxOf(peak, equity)
        if (peak > 0.0) maxDrawdown = maxOf(maxDrawdown, (peak - equity) / peak * 100.0)
    }

    trades.sortedBy { it.signalTime }
        .filter { it.qualityScore >= minimumScore && (direction == null || it.shortDirection == direction) }
        .forEach { trade ->
            release(trade.signalTime)
            if (cash + 1e-9 < amount) {
                skipped++
            } else {
                val resultPercentage = when {
                    trade.worstAdverseMove >= stopLoss -> -stopLoss
                    trade.succeeded -> profitPercentage
                    else -> trade.returnPercentage
                }
                cash -= amount
                turnover += amount
                executed++
                val duration = (trade.resolvedAfterHours ?: 7 * 24).toLong() * 60L * 60_000L
                open += VirtualPosition(trade.signalTime + duration, amount, amount * (1.0 + resultPercentage / 100.0))
            }
        }
    release(Long.MAX_VALUE)
    return PortfolioResult(startingCapital, cash, turnover, executed, skipped, maxDrawdown)
}

private fun evaluateSettings(
    trades: List<BacktestTrade>,
    startingCapital: Double,
    amount: Double,
    profitPercentage: Double,
    stopLoss: Double,
    minimumScore: Int,
    minimumWinRate: Int,
    direction: Boolean?
): StrategyEvaluation {
    val result = simulatePortfolio(trades.filter { it.predictedWinRate >= minimumWinRate }, startingCapital, amount, profitPercentage, stopLoss, minimumScore, direction)
    val roi = if (result.executedTrades > 0) result.roi else Double.NEGATIVE_INFINITY
    return StrategyEvaluation(roi, result.turnover, result.endingCapital, result.executedTrades)
}

private fun optimizeSettings(report: BacktestReport, startingCapital: Double, amount: Double, profitPercentage: Double, maximum: Double, minimumWinRateFloor: Double): OptimizedSettings {
    val chronological = report.trades.sortedBy { it.signalTime }
    val split = (chronological.size * 0.7).toInt().coerceIn(1, chronological.size.coerceAtLeast(1))
    val training = chronological.take(split)
    val validation = chronological.drop(split)
    val stops = buildList {
        var value = 0.5
        while (value <= maximum) { add(value); value += 0.5 }
        if (none { kotlin.math.abs(it - maximum) < 0.001 }) add(maximum)
    }
    val minimumRequired = maxOf(10, training.size / 10)
    var bestStop = maximum
    var bestScore = 0
    var bestWinRate = minimumWinRateFloor.toInt()
    var bestDirection: Boolean? = null
    var bestTraining = StrategyEvaluation(Double.NEGATIVE_INFINITY, 0.0, 0.0, 0)
    stops.forEach { stop ->
        listOf(0, 40, 50, 55, 60, 65, 70, 75, 80, 85, 90).forEach { score ->
            listOf(0, 50, 60, 70, 75, 80, 85, 90, 95).map { maxOf(it, minimumWinRateFloor.toInt()) }.distinct().forEach { winRate ->
                listOf<Boolean?>(null, false, true).forEach { direction ->
                    val evaluation = evaluateSettings(training, startingCapital, amount, profitPercentage, stop, score, winRate, direction)
                    val clearlyBetter = evaluation.roi > bestTraining.roi + 0.0001
                    val equivalentSameTrades = kotlin.math.abs(evaluation.roi - bestTraining.roi) <= 0.0001 &&
                        evaluation.count == bestTraining.count && winRate > bestWinRate
                    if (evaluation.count >= minimumRequired && (clearlyBetter || equivalentSameTrades)) {
                        bestStop = stop
                        bestScore = score
                        bestWinRate = winRate
                        bestDirection = direction
                        bestTraining = evaluation
                    }
                }
            }
        }
    }
    val checked = evaluateSettings(validation, startingCapital, amount, profitPercentage, bestStop, bestScore, bestWinRate, bestDirection)
    return OptimizedSettings(bestStop, bestScore, bestWinRate, bestDirection, bestTraining.roi, checked.roi.takeIf { it.isFinite() } ?: 0.0, checked.count, checked.invested, checked.ending)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable private fun OptimalSettingsCard(
    reports: Map<Double, BacktestReport>,
    startingCapital: Double,
    amount: Double,
    testedMaximum: Double,
    minimumWinRateFloor: Double,
    weeks: Int,
    requestedSignals: Int,
    exportEnabled: Boolean
) {
    val best = remember(reports, startingCapital, amount, testedMaximum, minimumWinRateFloor) {
        reports.map { (profit, report) -> profit to optimizeSettings(report, startingCapital, amount, profit, testedMaximum, minimumWinRateFloor) }
            .maxByOrNull { it.second.validationRoi }
    }
    val profitPercentage = best?.first ?: 1.0
    val settings = best?.second ?: return
    val direction = when (settings.direction) { true -> "Alleen SHORT"; false -> "Alleen LONG"; null -> "LONG + SHORT" }
    val rotation = remember { Animatable(0f) }
    val scope = rememberCoroutineScope()
    Surface(
        color = Color(0xFF10291F),
        shape = RoundedCornerShape(12.dp),
        modifier = Modifier.fillMaxWidth().height(270.dp)
            .graphicsLayer { rotationY = rotation.value; cameraDistance = 18f * density }
            .combinedClickable(
                onClick = {},
                onDoubleClick = {
                    scope.launch { rotation.animateTo(if (rotation.value > 90f) 0f else 180f, tween(550)) }
                }
            )
    ) {
      Box(Modifier.fillMaxSize().graphicsLayer { if (rotation.value > 90f) rotationY = 180f }) {
        if (rotation.value <= 90f) Column(Modifier.padding(10.dp)) {
            Text("BESTE INSTELLINGEN ACHTERAF", color = Color(0xFF08C887), fontSize = 8.sp, fontWeight = FontWeight.Bold)
            Text(if (exportEnabled) "Automatisch opgeslagen in Archief · dubbeltik voor uitleg" else "Wordt na voltooiing automatisch opgeslagen · dubbeltik voor uitleg", color = Color(0xFF8C92A3), fontSize = 7.sp)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                SummaryValue("${String.format("%.2f", profitPercentage)}%", "Profitdoel", Color(0xFFFFC857))
                SummaryValue("${String.format("%.2f", settings.stopLoss)}%", "Max. tegen", Color.White)
                SummaryValue(if (settings.minimumWinRate == 0) "Geen filter" else "${settings.minimumWinRate}+", "Min. winrate", Color.White)
            }
            Spacer(Modifier.height(5.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceEvenly) {
                SummaryValue(if (settings.minimumScore == 0) "Alle" else "${settings.minimumScore}+", "Min. TM-score", Color.White)
                SummaryValue(direction, "Richting", Color.White)
            }
            Spacer(Modifier.height(8.dp))
            androidx.compose.material3.HorizontalDivider(color = Color(0xFF275140))
            Spacer(Modifier.height(8.dp))
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                SummaryValue("$${String.format("%.2f", startingCapital)}", "Startkapitaal", Color.White)
                SummaryValue("$${String.format("%.2f", settings.validationInvested)}", "Totaal ingezet", Color(0xFF75A0FF))
                SummaryValue("${String.format("%+.2f%%", settings.validationRoi)}", "Rendement", if (settings.validationRoi >= 0) Color(0xFF08C887) else Color(0xFFFF4964))
                SummaryValue("$${String.format("%.2f", settings.validationEnding)}", "Eindwaarde", if (settings.validationRoi >= 0) Color(0xFF08C887) else Color(0xFFFF4964))
            }
            Spacer(Modifier.height(5.dp))
            Text("Controle op nieuwste 30% · ${settings.validationTrades} uitgevoerde trades", color = Color.White, fontSize = 8.sp, fontWeight = FontWeight.Bold)
            Text("Beste combinatie uit ${reports.size} volledig doorgerekende profitdoelen · gekozen op oudste 70% en gecontroleerd op nieuwste 30%", color = Color(0xFF8C92A3), fontSize = 7.sp)
        } else Column(Modifier.padding(12.dp)) {
            Text("WAAROM DIT DE BESTE INSTELLINGEN WAREN", color = Color(0xFF08C887), fontSize = 10.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(6.dp))
            Text("Profitdoel ${String.format("%.2f", profitPercentage)}%", color = Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.Bold)
            Text("Dit doel gaf samen met de overige instellingen de hoogste ROI op het aparte controlegedeelte. TradeMentor vergeleek ${reports.size} volledig doorgerekende profitdoelen.", color = Color.White, fontSize = 8.sp)
            Spacer(Modifier.height(5.dp))
            Text("Max. tegen ${String.format("%.2f", settings.stopLoss)}%", color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold)
            Text("Stoplossgrenzen van 0,5% tot ${String.format("%.2f", testedMaximum)}% zijn vergeleken. Deze grens hield binnen de test de beste balans tussen winnaars ruimte geven en verliezen beperken.", color = Color(0xFFB8C2D8), fontSize = 8.sp)
            Spacer(Modifier.height(5.dp))
            Text("Selectie: winrate ${if (settings.minimumWinRate == 0) "geen extra filter" else "${settings.minimumWinRate}+"} · TM-score ${if (settings.minimumScore == 0) "alle" else "${settings.minimumScore}+"} · $direction", color = Color.White, fontSize = 9.sp, fontWeight = FontWeight.Bold)
            Text("Alleen signals die aan deze drempels voldeden zijn in de geoptimaliseerde portefeuille opgenomen.", color = Color(0xFFB8C2D8), fontSize = 8.sp)
            Spacer(Modifier.height(5.dp))
            Text("EERLIJKHEIDSCONTROLE", color = Color(0xFF75A0FF), fontSize = 8.sp, fontWeight = FontWeight.Bold)
            Text("De oudste 70% koos de instellingen. De nieuwste 30% was vooraf apart gehouden en leverde ${settings.validationTrades} trades, ${String.format("%+.2f%%", settings.validationRoi)} ROI en $${String.format("%.2f", settings.validationEnding)} eindwaarde.", color = Color.White, fontSize = 8.sp)
            Spacer(Modifier.height(5.dp))
            Text("Startkapitaal $${String.format("%.2f", startingCapital)} · inzet $${String.format("%.2f", amount)} per trade · beperkt beschikbaar kapitaal. Handelskosten, funding, slippage en liquidatie zijn nog niet meegerekend.", color = Color(0xFFFFC857), fontSize = 8.sp)
            Spacer(Modifier.weight(1f))
            Text("Dubbeltik om terug te draaien", color = Color(0xFF8C92A3), fontSize = 7.sp, modifier = Modifier.align(Alignment.End))
        }
      }
    }
}

private fun calculateBestStopLoss(report: BacktestReport, amount: Double, profitPercentage: Double, maximum: Double): StopLossSuggestion {
    val candidates = buildList {
        var candidate = 0.5
        while (candidate <= maximum) { add(candidate); candidate += 0.5 }
        if (none { kotlin.math.abs(it - maximum) < 0.001 }) add(maximum)
    }
    val best = candidates.map { stop ->
        val net = report.trades.sumOf { trade ->
            val resultPercentage = when {
                trade.worstAdverseMove >= stop -> -stop
                trade.succeeded -> profitPercentage
                else -> trade.returnPercentage
            }
            amount * resultPercentage / 100.0
        }
        stop to net
    }.maxWithOrNull(compareBy<Pair<Double, Double>> { it.second }.thenBy { -it.first }) ?: (maximum to 0.0)
    val winnerMoves = report.trades.filter { it.succeeded }.map { it.worstAdverseMove }.sorted()
    val median = if (winnerMoves.isEmpty()) 0.0 else winnerMoves[winnerMoves.size / 2]
    return StopLossSuggestion(best.first, best.second, median)
}

@Composable private fun BestStopLossCard(
    report: BacktestReport,
    amount: Double,
    profitPercentage: Double,
    testedMaximum: Double,
    onUse: (Double) -> Unit
) {
    val suggestion = remember(report, amount, profitPercentage, testedMaximum) {
        calculateBestStopLoss(report, amount, profitPercentage, testedMaximum)
    }
    Surface(color = Color(0xFF132237), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(10.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("BESTE STOPLOSS ACHTERAF", color = Color(0xFFFFC857), fontSize = 8.sp, fontWeight = FontWeight.Bold)
                Text("${String.format("%.2f", suggestion.percentage)}%", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Text("Hoogste netto resultaat $${String.format("%.2f", suggestion.netResult)} · mediaan tegen bij winnaars ${String.format("%.2f", suggestion.medianWinnerAdverse)}%", color = Color(0xFF8C92A3), fontSize = 8.sp)
                Text("Getest van 0,5% t/m ${String.format("%.2f", testedMaximum)}% · historische optimalisatie, geen garantie", color = Color(0xFF8C92A3), fontSize = 7.sp)
            }
            Surface(color = Color(0xFF2F68FF), shape = RoundedCornerShape(8.dp), modifier = Modifier.clickable { onUse(suggestion.percentage) }) {
                Text("Gebruiken", color = Color.White, fontSize = 9.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 10.dp, vertical = 8.dp))
            }
        }
    }
}

@Composable private fun BacktestNumberField(label: String, value: String, onValue: (String) -> Unit, modifier: Modifier) {
    OutlinedTextField(
        value = value,
        onValueChange = { onValue(it.filter { char -> char.isDigit() || char == '.' }.take(8)) },
        label = { Text(label, fontSize = 8.sp) },
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        singleLine = true,
        textStyle = androidx.compose.ui.text.TextStyle(fontSize = 11.sp, color = Color.White),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = Color(0xFF2F68FF), unfocusedBorderColor = Color(0xFF232A38),
            focusedLabelColor = Color(0xFF75A0FF), unfocusedLabelColor = Color(0xFF8C92A3)
        ),
        modifier = modifier
    )
}

@Composable private fun BacktestMoneySummary(report: BacktestReport, startingCapital: Double, amount: Double, profitPercentage: Double, stopLoss: Double) {
    val result = remember(report, startingCapital, amount, profitPercentage, stopLoss) {
        simulatePortfolio(report.trades, startingCapital, amount, profitPercentage, stopLoss)
    }
    val net = result.endingCapital - startingCapital
    Surface(color = Color(0xFF101725), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(9.dp)) {
            Row(horizontalArrangement = Arrangement.SpaceBetween, modifier = Modifier.fillMaxWidth()) {
                SummaryValue("$${String.format("%.2f", startingCapital)}", "Startkapitaal", Color.White)
                SummaryValue("$${String.format("%.2f", result.turnover)}", "Totaal ingezet", Color(0xFF75A0FF))
                SummaryValue("${String.format("%+.2f%%", result.roi)}", "Rendement", if (net >= 0) Color(0xFF08C887) else Color(0xFFFF4964))
                SummaryValue("$${String.format("%.2f", result.endingCapital)}", "Eindwaarde", if (net >= 0) Color(0xFF08C887) else Color(0xFFFF4964))
            }
            Text("Netto ${if (net >= 0) "+" else "−"}$${String.format("%.2f", kotlin.math.abs(net))} · ${result.executedTrades} uitgevoerd · ${result.skippedTrades} overgeslagen · drawdown ${String.format("%.2f%%", result.maxDrawdown)}", color = Color(0xFFFFC857), fontSize = 8.sp, modifier = Modifier.padding(top = 5.dp))
            Text("Chronologisch met werkelijk beschikbaar kapitaal · zonder handelskosten en funding", color = Color(0xFF8C92A3), fontSize = 7.sp)
        }
    }
}

@Composable private fun BacktestChoice(text: String, selected: Boolean, onClick: () -> Unit) {
    Surface(color = if (selected) Color(0xFF2F68FF) else Color(0xFF151C29), shape = RoundedCornerShape(8.dp), modifier = Modifier.clickable(onClick = onClick)) {
        Text(text, color = if (selected) Color.White else Color(0xFF8C92A3), fontSize = 8.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp))
    }
}

@Composable private fun BacktestSummary(report: BacktestReport, profit: Double) {
    Surface(color = Color(0xFF101725), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth()) {
        Row(Modifier.padding(10.dp), horizontalArrangement = Arrangement.SpaceBetween) {
            SummaryValue("${report.trades.size}", "Signals", Color.White)
            SummaryValue("${report.succeeded}", "Doel +${String.format("%.1f", profit)}%", Color(0xFF08C887))
            SummaryValue("${report.failed}", "Niet behaald", Color(0xFFFF4964))
            SummaryValue(String.format("%.1f%%", report.successRate), "Werkelijk", Color(0xFFFFC857))
        }
    }
}

@Composable private fun SummaryValue(value: String, label: String, color: Color) {
    Column(horizontalAlignment = Alignment.CenterHorizontally) { Text(value, color = color, fontSize = 17.sp, fontWeight = FontWeight.Bold); Text(label, color = Color(0xFF8C92A3), fontSize = 7.sp) }
}

@Composable private fun BacktestTradeRow(trade: BacktestTrade) {
    val outcomeColor = if (trade.succeeded) Color(0xFF08C887) else Color(0xFFFF4964)
    var expanded by remember { mutableStateOf(false) }
    Column(Modifier.fillMaxWidth().clickable { expanded = !expanded }.padding(vertical = 7.dp)) {
      Row(verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text("${trade.symbol}/USD · ${if (trade.shortDirection) "SHORT" else "LONG"}", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
            Text("${SimpleDateFormat("dd MMM yyyy", Locale("nl", "NL")).format(Date(trade.signalTime))} · ${trade.analysisTimeframe} · voorspeld ${String.format("%.1f%%", trade.predictedWinRate)} · TM ${trade.qualityScore.toInt()}", color = Color(0xFF8C92A3), fontSize = 8.sp)
            Text("Waarom: ${trade.selectionReason}", color = Color(0xFFFFC857), fontSize = 7.sp, maxLines = if (expanded) 5 else 1)
        }
        Column(horizontalAlignment = Alignment.End, modifier = Modifier.padding(end = 10.dp)) {
            Text(if (trade.succeeded) "BEHAALD" else "NIET BEHAALD", color = outcomeColor, fontSize = 9.sp, fontWeight = FontWeight.Bold)
            Text(trade.resolvedAfterHours?.let { "na $it uur" } ?: "na 7 dagen", color = Color(0xFF8C92A3), fontSize = 7.sp)
        }
        Text("−${String.format("%.2f", trade.worstAdverseMove)}%", color = Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.Bold)
      }
      if (expanded) {
          Spacer(Modifier.height(5.dp))
          Surface(color = outcomeColor.copy(alpha = 0.10f), shape = RoundedCornerShape(8.dp), modifier = Modifier.fillMaxWidth()) {
              Column(Modifier.padding(8.dp)) {
                  Text("Waarom deze uitslag?", color = outcomeColor, fontSize = 8.sp, fontWeight = FontWeight.Bold)
                  Text(trade.outcomeReason, color = Color.White, fontSize = 8.sp)
                  Text("Tot aan de uitslag: beste beweging +${String.format("%.2f", trade.bestFavourableMove)}% · maximaal tegen −${String.format("%.2f", trade.worstAdverseMove)}%", color = Color(0xFF8C92A3), fontSize = 8.sp)
                  Text("Instap ${String.format("%.6f", trade.entryPrice)} · doel ${String.format("%.6f", trade.targetPrice)}", color = Color(0xFF8C92A3), fontSize = 8.sp)
              }
          }
      }
    }
}
