package com.tradementor.app

import android.os.Bundle
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reown.appkit.client.AppKit
import com.tradementor.app.repository.WalletOverview
import com.tradementor.app.repository.WalletOverviewCache
import com.tradementor.app.repository.WalletRepository
import com.tradementor.app.scanner.AutoTradingStore
import com.tradementor.app.ui.theme.TradeMentorTheme
import kotlinx.coroutines.delay
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.abs

class CarDashboardActivity : FragmentActivity() {
    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        setContent {
            TradeMentorTheme {
                CarDashboardScreen()
            }
        }
    }
}

private val CarBg = Color(0xFF05070B)
private val CarCard = Color(0xFF10151C)
private val CarGreen = Color(0xFF20D34A)
private val CarRed = Color(0xFFFF4D4D)
private val CarMuted = Color(0xFF9BA3AF)

@Composable
private fun CarDashboardScreen() {
    val context = androidx.compose.ui.platform.LocalContext.current
    val repository = remember { WalletRepository() }
    var address by remember { mutableStateOf(AppKit.getAccount()?.address.orEmpty()) }
    var overview by remember(address) { mutableStateOf(WalletOverviewCache.get(address)) }
    var error by remember { mutableStateOf<String?>(null) }
    var lastUpdated by remember { mutableLongStateOf(0L) }

    LaunchedEffect(Unit) {
        while (true) {
            address = AppKit.getAccount()?.address.orEmpty()
            if (address.isNotBlank()) {
                runCatching { repository.load(address) }
                    .onSuccess {
                        overview = it
                        WalletOverviewCache.put(address, it)
                        lastUpdated = System.currentTimeMillis()
                        error = null
                    }
                    .onFailure { error = it.message ?: "Live data kon niet worden geladen" }
            }
            delay(10_000)
        }
    }

    val data = overview
    Box(Modifier.fillMaxSize().background(CarBg).padding(14.dp)) {
        when {
            address.isBlank() -> CarCenteredMessage("Open TradeMentor eerst op je telefoon en koppel je wallet.")
            data == null -> CarCenteredMessage(error ?: "Live dashboard laden…")
            else -> CarDashboardContent(data, AutoTradingStore.isEnabled(context), lastUpdated, error)
        }
    }
}

@Composable
private fun CarDashboardContent(data: WalletOverview, botActive: Boolean, lastUpdated: Long, error: String?) {
    val positions = data.account.assetPositions.map { it.position }.filter { (it.signedSize.toDoubleOrNull() ?: 0.0) != 0.0 }
    val activeTrades = positions.size
    val longs = positions.count { (it.signedSize.toDoubleOrNull() ?: 0.0) > 0.0 }
    val shorts = positions.count { (it.signedSize.toDoubleOrNull() ?: 0.0) < 0.0 }
    val marginUsed = positions.sumOf { abs(it.marginUsed.toDoubleOrNull() ?: 0.0) }
    val unrealized = positions.sumOf { it.unrealizedPnl.toDoubleOrNull() ?: 0.0 }
    val crossAccountValue = data.account.crossMarginSummary.accountValue.toDoubleOrNull() ?: 0.0
    val riskBase = if (data.accountMode == "unifiedAccount" || data.accountMode == "portfolioMargin") data.portfolioValue else crossAccountValue
    val maintenance = data.account.crossMaintenanceMarginUsed.toDoubleOrNull() ?: 0.0
    val risk = if (riskBase > 0.0) (maintenance / riskBase * 100.0).coerceIn(0.0, 100.0) else 0.0
    val top = positions.sortedByDescending { it.unrealizedPnl.toDoubleOrNull() ?: Double.NEGATIVE_INFINITY }.take(3)

    Column(Modifier.fillMaxSize()) {
        Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
            Text("●", color = CarGreen, fontSize = 16.sp)
            Text(" Amar Crypto Bot", color = Color.White, fontWeight = FontWeight.Bold, fontSize = 18.sp)
            Spacer(Modifier.weight(1f))
            Text(if (lastUpdated > 0) "Laatste update ${time(lastUpdated)}" else "Laden…", color = CarMuted, fontSize = 11.sp)
            Spacer(Modifier.width(16.dp))
            Text(if (botActive) "● Bot actief" else "● Bot uit", color = if (botActive) CarGreen else CarRed, fontWeight = FontWeight.Bold, fontSize = 12.sp)
        }

        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CarMetricCard("PORTFOLIO WAARDE", money(data.portfolioValue), signedMoney(unrealized), Modifier.weight(1.25f))
            CarMetricCard("BESCHIKBAAR", money(data.availableToTrade), "Vrije marge", Modifier.weight(1f))
            CarMetricCard("TRADES ACTIEF", activeTrades.toString(), "$longs long · $shorts short", Modifier.weight(0.95f))
            CarRiskCard(risk, Modifier.weight(1.1f))
        }
        Spacer(Modifier.height(10.dp))
        Row(Modifier.fillMaxWidth().weight(1f), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            CarMetricCard("LONG / SHORT", "$longs / $shorts", "Totaal $activeTrades", Modifier.weight(0.85f))
            CarMetricCard("OPEN P&L", signedMoney(unrealized), "Live ongerealiseerd", Modifier.weight(0.85f), valueColor = if (unrealized >= 0) CarGreen else CarRed)
            CarMetricCard("MARGIN GEBRUIKT", money(marginUsed), "Maintenance ${money(maintenance)}", Modifier.weight(1f))
            CarTopPositions(top, Modifier.weight(1.6f))
        }
        error?.let {
            Text("Updatewaarschuwing: $it", color = Color(0xFFFFC857), fontSize = 9.sp, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@Composable
private fun CarMetricCard(title: String, value: String, subtitle: String, modifier: Modifier = Modifier, valueColor: Color = Color.White) {
    Surface(modifier = modifier.fillMaxHeight(), color = CarCard, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.Center) {
            Text(title, color = CarMuted, fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
            Text(value, color = valueColor, fontSize = 25.sp, fontWeight = FontWeight.Black, modifier = Modifier.padding(top = 5.dp))
            Text(subtitle, color = if (subtitle.startsWith("+")) CarGreen else CarMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
        }
    }
}

@Composable
private fun CarRiskCard(risk: Double, modifier: Modifier = Modifier) {
    val color = when {
        risk < 30 -> CarGreen
        risk < 50 -> Color(0xFFFFD166)
        risk < 70 -> Color(0xFFFF9F43)
        else -> CarRed
    }
    val label = when {
        risk < 30 -> "Laag"
        risk < 50 -> "Volgen"
        risk < 70 -> "Verlagen"
        risk < 85 -> "Hoog"
        else -> "Kritiek"
    }
    Surface(modifier = modifier.fillMaxHeight(), color = CarCard, shape = RoundedCornerShape(14.dp)) {
        Row(Modifier.fillMaxSize().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("RISICO", color = CarMuted, fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
                Text(String.format(Locale.US, "%.1f%%", risk), color = color, fontSize = 30.sp, fontWeight = FontWeight.Black)
                Text(label, color = color, fontSize = 11.sp, fontWeight = FontWeight.Bold)
            }
            Box(Modifier.size(62.dp), contentAlignment = Alignment.Center) {
                Canvas(Modifier.fillMaxSize()) {
                    drawArc(Color(0xFF343A40), 135f, 270f, false, style = Stroke(8.dp.toPx()))
                    drawArc(color, 135f, 270f * (risk / 100.0).toFloat(), false, style = Stroke(8.dp.toPx()))
                }
            }
        }
    }
}

@Composable
private fun CarTopPositions(positions: List<com.tradementor.app.api.HyperliquidPosition>, modifier: Modifier = Modifier) {
    Surface(modifier = modifier.fillMaxHeight(), color = CarCard, shape = RoundedCornerShape(14.dp)) {
        Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.Center) {
            Text("TOP 3 POSITIES", color = CarMuted, fontSize = 10.sp, fontWeight = FontWeight.SemiBold)
            if (positions.isEmpty()) {
                Text("Geen open posities", color = CarMuted, fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
            } else positions.forEachIndexed { index, p ->
                val size = p.signedSize.toDoubleOrNull() ?: 0.0
                val pnl = p.unrealizedPnl.toDoubleOrNull() ?: 0.0
                Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("${index + 1}. ${p.coin}", color = Color.White, fontSize = 10.sp, modifier = Modifier.weight(1f))
                    Text(if (size >= 0) "LONG ${p.leverage.value}x" else "SHORT ${p.leverage.value}x", color = if (size >= 0) CarGreen else CarRed, fontSize = 9.sp, modifier = Modifier.weight(1f))
                    Text(signedMoney(pnl), color = if (pnl >= 0) CarGreen else CarRed, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                }
            }
        }
    }
}

@Composable
private fun CarCenteredMessage(message: String) {
    Box(Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        Text(message, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold)
    }
}

private fun money(value: Double): String = NumberFormat.getCurrencyInstance(Locale.US).format(value)
private fun signedMoney(value: Double): String = (if (value >= 0) "+" else "−") + money(abs(value))
private fun time(timestamp: Long): String = SimpleDateFormat("HH:mm:ss", Locale.getDefault()).format(Date(timestamp))
