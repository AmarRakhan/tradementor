package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reown.appkit.client.AppKit
import com.tradementor.app.BuildConfig
import com.tradementor.app.cloud.CloudAccountRepository
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.repository.WalletOverview
import com.tradementor.app.repository.WalletOverviewCache
import com.tradementor.app.repository.WalletRepository
import com.tradementor.app.scanner.*
import kotlinx.coroutines.delay
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.*

private val RiskBg = Color(0xFF05070B)
private val RiskCard = Color(0xFF101723)
private val RiskBlue = Color(0xFF2F68FF)
private val RiskGreen = Color(0xFF08C887)
private val RiskRed = Color(0xFFFF496A)
private val RiskMuted = Color(0xFF8C92A3)

@Composable
fun RiskManagementScreen(onOpenLaunchpad: () -> Unit = {}) {
    val context = LocalContext.current
    val repository = remember { WalletRepository() }
    val initialAddress = AppKit.getAccount()?.address.orEmpty()
    var address by remember { mutableStateOf(initialAddress) }
    var overview by remember(initialAddress) { mutableStateOf(WalletOverviewCache.get(initialAddress)) }
    var message by remember { mutableStateOf<String?>(null) }
    var settings by remember { mutableStateOf(SignalExecutionSettingsStore.load(context)) }
    var amount by remember { mutableStateOf(String.format(Locale.US, "%.2f", settings.positionSizeUsd)) }
    var maximum by remember { mutableStateOf(settings.maxActiveTrades.toString()) }
    val profile = remember { ConsensusProfileStore.load(context) }
    val activeStrategy = remember { StrategyProfileStore.activeDefinition(context) }
    val dcaSettings = remember { DcaBotSettingsStore.load(context) }

    LaunchedEffect(Unit) {
        if (address.isBlank()) {
            runCatching { CloudAccountRepository.linkedWallet() }
                .onSuccess { cloudAddress ->
                    if (cloudAddress.isNotBlank()) address = cloudAddress
                }
        }
        while (true) {
            AppKit.getAccount()?.address?.takeIf { it.isNotBlank() }?.let { address = it }
            if (address.isBlank()) {
                runCatching { CloudAccountRepository.linkedWallet() }
                    .onSuccess { cloudAddress ->
                        if (cloudAddress.isNotBlank()) address = cloudAddress
                    }
            }
            address.takeIf { it.isNotBlank() }?.let { walletAddress ->
                runCatching { repository.load(walletAddress) }.onSuccess {
                    overview = it
                    WalletOverviewCache.put(walletAddress, it)
                    message = null
                }.onFailure { message = it.message }
            }
            delay(15_000)
        }
    }

    val active = overview?.account?.assetPositions.orEmpty()
    val fills = overview?.recentFills.orEmpty()
    val startToday = remember {
        Calendar.getInstance().apply { set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0) }.timeInMillis
    }
    val cycleStartedAt = TradingCycleStore.startedAt(context)
    val visibleStart = maxOf(startToday, cycleStartedAt)
    val profitToday = fills.filter { it.time >= visibleStart }.sumOf {
        (it.closedPnl.toDoubleOrNull() ?: 0.0) - (it.fee.toDoubleOrNull() ?: 0.0)
    }
    val history = (TradeHistoryStore.load(context) + LiveOutcomeLedger.loadCompleted(context))
        .filter { it.startedAt >= cycleStartedAt }
    val completed = history.filter { it.outcome != TradeOutcome.Pending }.distinctBy { it.id }
    // Financial performance comes from actual Hyperliquid fills, independent
    // from the model outcome. Manual profit-taking therefore counts financially
    // without being mislabeled as a successful profit-target prediction.
    val totalProfit = fills.filter { it.time >= cycleStartedAt }.sumOf {
        (it.closedPnl.toDoubleOrNull() ?: 0.0) - (it.fee.toDoubleOrNull() ?: 0.0)
    }
    val startWeek = remember {
        Calendar.getInstance().apply {
            firstDayOfWeek = Calendar.MONDAY
            set(Calendar.DAY_OF_WEEK, Calendar.MONDAY)
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }.timeInMillis
    }
    val startMonth = remember {
        Calendar.getInstance().apply {
            set(Calendar.DAY_OF_MONTH, 1)
            set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
        }.timeInMillis
    }
    fun netFill(from: Long) = fills.filter { it.time >= maxOf(from, cycleStartedAt) }.sumOf {
        (it.closedPnl.toDoubleOrNull() ?: 0.0) - (it.fee.toDoubleOrNull() ?: 0.0)
    }
    val profitWeek = netFill(startWeek)
    val profitMonth = netFill(startMonth)
    val financialFills = fills.filter { it.time >= cycleStartedAt }.map { fill ->
        Triple(fill, fill.closedPnl.toDoubleOrNull() ?: 0.0, fill.fee.toDoubleOrNull() ?: 0.0)
    }
    val grossRealized = financialFills.sumOf { it.second }
    val totalFees = financialFills.sumOf { it.third }
    val closingResults = financialFills.map { it.first to (it.second - it.third) }.filter { kotlin.math.abs(it.second) > 0.000001 }
    val positiveResults = closingResults.filter { it.second > 0.0 }
    val negativeResults = closingResults.filter { it.second < 0.0 }
    val financialWinRate = if (closingResults.isEmpty()) 0.0 else positiveResults.size * 100.0 / closingResults.size
    val averageWin = positiveResults.map { it.second }.average().takeUnless { it.isNaN() } ?: 0.0
    val averageLoss = negativeResults.map { it.second }.average().takeUnless { it.isNaN() } ?: 0.0
    val profitFactor = positiveResults.sumOf { it.second }.let { grossWin ->
        val grossLoss = kotlin.math.abs(negativeResults.sumOf { it.second })
        if (grossLoss > 0.0) grossWin / grossLoss else if (grossWin > 0.0) Double.POSITIVE_INFINITY else 0.0
    }
    val bestResult = closingResults.maxByOrNull { it.second }
    val worstResult = closingResults.minByOrNull { it.second }
    val cycleStartValue = TradingCycleStore.startPortfolioValue(context)
    val realizedGrowth = if (cycleStartValue > 0.0) totalProfit / cycleStartValue * 100.0 else 0.0
    val dailyProfit = remember(fills, cycleStartedAt) {
        val formatter = SimpleDateFormat("EEE", Locale("nl", "NL"))
        (6 downTo 0).map { daysAgo ->
            val calendar = Calendar.getInstance().apply {
                add(Calendar.DAY_OF_YEAR, -daysAgo)
                set(Calendar.HOUR_OF_DAY, 0); set(Calendar.MINUTE, 0); set(Calendar.SECOND, 0); set(Calendar.MILLISECOND, 0)
            }
            val from = calendar.timeInMillis
            val until = from + 24L * 60 * 60 * 1000
            formatter.format(Date(from)) to fills.filter { it.time in maxOf(from, cycleStartedAt) until until }.sumOf {
                (it.closedPnl.toDoubleOrNull() ?: 0.0) - (it.fee.toDoubleOrNull() ?: 0.0)
            }
        }
    }
    val wins = completed.count { it.outcome == TradeOutcome.Succeeded || it.lateTargetReachedAt != null }
    val losses = completed.count { it.outcome == TradeOutcome.Failed && it.lateTargetReachedAt == null }
    val winRate = if (wins + losses == 0) 0.0 else wins * 100.0 / (wins + losses)
    val successfulDurations = completed.filter {
        it.closedAt != null && (it.outcome == TradeOutcome.Succeeded || it.lateTargetReachedAt != null) && (it.realizedPnl ?: 0.0) > 0.0
    }.map { it.closedAt!! - it.startedAt }.filter { it >= 0L }
    val averageSuccessfulDuration = successfulDurations.takeIf { it.isNotEmpty() }?.average()?.toLong()
    val crossAccountValue = overview?.account?.crossMarginSummary?.accountValue?.toDoubleOrNull() ?: 0.0
    val accountValue = overview?.let {
        if (it.accountMode == "unifiedAccount" || it.accountMode == "portfolioMargin") it.portfolioValue
        else crossAccountValue
    } ?: 0.0
    val maintenance = overview?.account?.crossMaintenanceMarginUsed?.toDoubleOrNull() ?: 0.0
    val liquidationRisk = if (accountValue > 0) (maintenance / accountValue * 100).coerceIn(0.0, 100.0) else 0.0
    val liquidationColor = when {
        liquidationRisk < 30 -> RiskGreen
        liquidationRisk < 50 -> Color(0xFFFFD166)
        liquidationRisk < 70 -> Color(0xFFFF9F43)
        else -> RiskRed
    }
    val liquidationStatus = when {
        liquidationRisk < 30 -> "Gezonde buffer"
        liquidationRisk < 50 -> "Verhoogd · blijven volgen"
        liquidationRisk < 70 -> "Geen extra risico toevoegen"
        liquidationRisk < 85 -> "Hoog · posities verkleinen"
        liquidationRisk < 95 -> "Kritiek · direct handelen"
        else -> "Liquidatiegevaar"
    }
    val exposure = active.sumOf { kotlin.math.abs(it.position.positionValue.toDoubleOrNull() ?: 0.0) }
    val riskPerTrade = if (accountValue > 0.0) (settings.positionSizeUsd / accountValue * 100.0) else 0.0
    val riskPerTradeColor = when {
        riskPerTrade <= 2.0 -> RiskGreen
        riskPerTrade <= 5.0 -> Color(0xFFFFD166)
        else -> RiskRed
    }

    LazyColumn(Modifier.fillMaxSize().background(RiskBg).padding(horizontal = 16.dp), contentPadding = PaddingValues(top = 18.dp, bottom = 28.dp), verticalArrangement = Arrangement.spacedBy(11.dp)) {
        item {
            Text("Risk Management", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Black, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.fillMaxWidth())
            Text("Strategy & management · jouw centrale handelscontrole", color = RiskMuted, fontSize = 11.sp)
        }
        if (BuildConfig.ADMIN_FEATURES) {
            item {
                TradeMentorPrimaryButton(
                    label = "Mijn takenlijst & projectlogboek",
                    onClick = onOpenLaunchpad,
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                RiskMetric("NETTO PNL VANDAAG", money(profitToday), if (profitToday >= 0) RiskGreen else RiskRed, Modifier.weight(1f))
                RiskMetric("PROFIT TOTAAL", money(totalProfit), if (totalProfit >= 0) RiskGreen else RiskRed, Modifier.weight(1f))
            }
        }
        item {
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(9.dp)) {
                RiskMetric("DEZE WEEK", money(profitWeek), if (profitWeek >= 0) RiskGreen else RiskRed, Modifier.weight(1f))
                RiskMetric("DEZE MAAND", money(profitMonth), if (profitMonth >= 0) RiskGreen else RiskRed, Modifier.weight(1f))
            }
        }
        item {
            RiskPanel("PROFIT PERFORMANCE") {
                Text("GEREALISEERDE NETTO PNL · LAATSTE 7 DAGEN", color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                ProfitWeekChart(dailyProfit)
                HorizontalDivider(color = Color(0xFF263142), modifier = Modifier.padding(vertical = 10.dp))
                RiskLine("Bruto gerealiseerde PNL", money(grossRealized), if (grossRealized >= 0) RiskGreen else RiskRed)
                RiskLine("Hyperliquid-fees", "−${money(totalFees)}", RiskRed)
                RiskLine("Netto gerealiseerd", money(totalProfit), if (totalProfit >= 0) RiskGreen else RiskRed)
                RiskLine("Groei sinds cyclusstart", String.format(Locale.US, "%+.2f%%", realizedGrowth), if (realizedGrowth >= 0) RiskGreen else RiskRed)
                HorizontalDivider(color = Color(0xFF263142), modifier = Modifier.padding(vertical = 10.dp))
                RiskLine("Financiële winratio", String.format(Locale.US, "%.1f%%", financialWinRate), if (financialWinRate >= 55) RiskGreen else Color(0xFFFFB84D))
                RiskLine("Profit factor", if (profitFactor.isInfinite()) "∞" else String.format(Locale.US, "%.2f", profitFactor), if (profitFactor >= 1.5) RiskGreen else Color(0xFFFFB84D))
                RiskLine("Gemiddelde winst", money(averageWin), RiskGreen)
                RiskLine("Gemiddeld verlies", money(averageLoss), RiskRed)
                RiskLine("Beste trade", bestResult?.let { "${it.first.coin} · ${money(it.second)}" } ?: "Nog geen data", RiskGreen)
                RiskLine("Slechtste trade", worstResult?.let { "${it.first.coin} · ${money(it.second)}" } ?: "Nog geen data", RiskRed)
                RiskLine("Winstgevende / verliesgevende sluitingen", "${positiveResults.size} / ${negativeResults.size}")
                Text("Alle bedragen zijn gerealiseerd en na fees. Open PNL staat bewust niet in dit profitoverzicht.", color = RiskMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 9.dp))
            }
        }
        item {
            RiskPanel("ACCOUNT & RISICO") {
                RiskProgress("Naar liquidatie", liquidationRisk, liquidationColor)
                RiskLine("Status", liquidationStatus, liquidationColor)
                RiskLine("Portfolio", money(overview?.portfolioValue ?: 0.0))
                RiskLine("Available to trade", money(overview?.availableToTrade ?: 0.0), RiskGreen)
                RiskLine("Totale open exposure", money(exposure))
                RiskLine("Nieuwe trade / portfolio", String.format(Locale.US, "%.2f%%", riskPerTrade), riskPerTradeColor)
                RiskLine("Instapbedrag", money(settings.positionSizeUsd))
                RiskLine("Actieve posities", "${active.size} / ${settings.maxActiveTrades}")
                RiskLine("LONG / SHORT", "${active.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) > 0 }} / ${active.count { (it.position.signedSize.toDoubleOrNull() ?: 0.0) < 0 }}")
            }
        }
        item {
            RiskPanel("RESULTATEN") {
                RiskProgress("Historische winrate", winRate, if (winRate >= 60) RiskGreen else Color(0xFFFFB84D))
                RiskLine("Gewonnen", wins.toString(), RiskGreen)
                RiskLine("Doel niet op tijd (LATE)", losses.toString(), RiskRed)
                RiskLine("Afgeronde trades", (wins + losses).toString())
                RiskLine("Gem. tijd actief (wins)", averageSuccessfulDuration?.let(::riskDuration) ?: "Nog geen data")
                Text("Risico per nieuwe trade vergelijkt het ingestelde instapbedrag met de actuele portfolio value. Dit beÃ¯nvloedt de risicobeoordeling, niet de historische resultaatkans.", color = RiskMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 8.dp))
                Text("Netto PNL vandaag is gerealiseerde closedPnl sinds 00:00 min Hyperliquid-fees. Open posities tellen niet mee. Profit totaal gebruikt de in TradeMentor opgeslagen afgeronde trades.", color = RiskMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 8.dp))
            }
        }
        item {
            RiskPanel("HANDELSINSTELLINGEN") {
                Text("Het instapbedrag is automatisch ook het eenmalige bijkoopbedrag.", color = RiskMuted, fontSize = 10.sp)
                Row(Modifier.fillMaxWidth().padding(top = 9.dp), horizontalArrangement = Arrangement.spacedBy(9.dp), verticalAlignment = Alignment.CenterVertically) {
                    OutlinedTextField(amount, { amount = it.filter { c -> c.isDigit() || c == '.' }.take(8) }, label = { Text("Instap & bijkoop ($)") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal), modifier = Modifier.weight(1f))
                    OutlinedTextField(maximum, { maximum = it.filter(Char::isDigit).take(3) }, label = { Text("Max actief") }, singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Number), modifier = Modifier.weight(0.75f))
                }
                TradeMentorPrimaryButton(
                    label = "Instellingen opslaan",
                    onClick = {
                        val value = amount.toDoubleOrNull()
                        val max = maximum.toIntOrNull()
                        if (value == null || value < 10 || max == null || max !in 1..400) message = "Gebruik minimaal $10 en 1-400 actieve trades."
                        else {
                            settings = SignalExecutionSettings(value, max)
                            SignalExecutionSettingsStore.save(context, settings)
                            message = "Handelsinstellingen opgeslagen."
                        }
                    },
                    modifier = Modifier.fillMaxWidth().padding(top = 10.dp)
                )
                message?.let { Text(it, color = Color(0xFFB7CAFF), fontSize = 10.sp, modifier = Modifier.padding(top = 7.dp)) }
            }
        }
        item {
            RiskPanel("ACTIEVE SCANNERSTRATEGIE") {
                RiskLine("Profitdoel", String.format(Locale.US, "%.2f%%", profile.profitTarget), Color(0xFFFFC857))
                when (activeStrategy.id) {
                    "strategy_3" -> {
                        if (dcaSettings.stopLossEnabled) {
                            RiskLine("Maximale tegenbeweging", String.format(Locale.US, "%.2f%%", dcaSettings.stopLossPercentage))
                        } else {
                            RiskLine("Stop-loss", "Uitgeschakeld (handmatig beheer)")
                        }
                    }
                    "strategy_2" -> RiskLine("Maximale tegenbeweging", String.format(Locale.US, "%.2f%%", kotlin.math.min(profile.stopLoss, 1.5)), Color(0xFFFF7A00))
                    else -> RiskLine("Maximale tegenbeweging", String.format(Locale.US, "%.2f%%", profile.stopLoss))
                }
                RiskLine("Minimale winrate", String.format(Locale.US, "%.0f%%", profile.minimumWinRate))
                RiskLine("Minimale TM-score", String.format(Locale.US, "%.0f", profile.minimumScore))
                RiskLine("Toegestane richting", when { profile.allowLong && profile.allowShort -> "LONG + SHORT"; profile.allowLong -> "Alleen LONG"; else -> "Alleen SHORT" })
                RiskLine("Onderzoeksruns", profile.sourceRuns.toString())
                RiskLine("Historische situaties", profile.historicalSituations.toString())
                RiskLine("Validatietrades", profile.validationTrades.toString())
            }
        }
        item {
            RiskPanel("BIJKOOPBEVEILIGING") {
                RiskLine("Maximum per pair", "1×")
                RiskLine("Hercontrole", "5m + 15m")
                RiskLine("Minimale winrate", "80%")
                RiskLine("Minimale kwaliteit", "70")
                Text("Alleen zichtbaar wanneer beide tijdframes opnieuw dezelfde richting bevestigen en de tegenbeweging binnen de veilige zone blijft.", color = RiskMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 8.dp))
            }
        }
    }
}

@Composable private fun RiskPanel(title: String, content: @Composable ColumnScope.() -> Unit) = Surface(color = RiskCard, shape = RoundedCornerShape(18.dp)) { Column(Modifier.fillMaxWidth().padding(15.dp)) { Text(title, color = Color(0xFF8EB2FF), fontSize = 10.sp, fontWeight = FontWeight.Black); Spacer(Modifier.height(9.dp)); content() } }
@Composable private fun RiskMetric(label: String, value: String, color: Color, modifier: Modifier) = Surface(color = Color(0xFF0D2140), shape = RoundedCornerShape(17.dp), modifier = modifier) { Column(Modifier.padding(14.dp)) { Text(label, color = Color(0xFF8EB2FF), fontSize = 9.sp, fontWeight = FontWeight.Black); Text(value, color = color, fontSize = 22.sp, fontWeight = FontWeight.Black) } }
@Composable private fun RiskLine(label: String, value: String, color: Color = Color.White) = Row(Modifier.fillMaxWidth().padding(vertical = 4.dp)) { Text(label, color = RiskMuted, fontSize = 11.sp, modifier = Modifier.weight(1f)); Text(value, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold) }
@Composable private fun RiskProgress(label: String, value: Double, color: Color) { Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) { Text(label, color = Color.White, fontWeight = FontWeight.Bold); Text(String.format(Locale.US, "%.1f%%", value), color = color, fontWeight = FontWeight.Black) }; LinearProgressIndicator(progress = { (value / 100).toFloat() }, color = color, trackColor = Color(0xFF202A39), modifier = Modifier.fillMaxWidth().height(8.dp).padding(top = 3.dp)); Spacer(Modifier.height(7.dp)) }
@Composable private fun ProfitWeekChart(values: List<Pair<String, Double>>) {
    val maximum = values.maxOfOrNull { kotlin.math.abs(it.second) }?.coerceAtLeast(0.01) ?: 0.01
    Row(
        Modifier.fillMaxWidth().height(105.dp).padding(top = 10.dp),
        horizontalArrangement = Arrangement.spacedBy(5.dp),
        verticalAlignment = Alignment.Bottom
    ) {
        values.forEach { (day, value) ->
            val barHeight = (12.0 + kotlin.math.abs(value) / maximum * 48.0).dp
            Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally, verticalArrangement = Arrangement.Bottom) {
                Text(
                    if (kotlin.math.abs(value) < 0.005) "–" else String.format(Locale.US, "%+.2f", value),
                    color = if (value >= 0) RiskGreen else RiskRed,
                    fontSize = 7.sp,
                    maxLines = 1
                )
                Box(
                    Modifier.fillMaxWidth(0.62f).height(barHeight)
                        .background(if (value >= 0) RiskGreen.copy(alpha = 0.82f) else RiskRed.copy(alpha = 0.82f), RoundedCornerShape(topStart = 5.dp, topEnd = 5.dp))
                )
                Text(day, color = RiskMuted, fontSize = 8.sp, modifier = Modifier.padding(top = 4.dp))
            }
        }
    }
}
private fun money(value: Double): String = NumberFormat.getCurrencyInstance(Locale.US).format(value)
private fun riskDuration(milliseconds: Long): String {
    val minutes = milliseconds / 60_000L
    val days = minutes / 1_440L
    val hours = (minutes % 1_440L) / 60L
    val mins = minutes % 60L
    return when { days > 0 -> "${days}d ${hours}u"; hours > 0 -> "${hours}u ${mins}m"; else -> "${mins}m" }
}
