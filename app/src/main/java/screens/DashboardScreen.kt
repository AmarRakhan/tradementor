package com.tradementor.app.screens

import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.R
import com.tradementor.app.api.PerpetualMarket
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.scanner.TradeHistoryStore
import com.tradementor.app.scanner.TradeOutcome
import java.text.DecimalFormat
import kotlin.math.abs

private val HomeBg = Color(0xFF05070B)
private val HomePanel = Color(0xFF101722)
private val HomeRaised = Color(0xFF162033)
private val HomeBlue = Color(0xFF2F68FF)
private val HomeGreen = Color(0xFF08C887)
private val HomeRed = Color(0xFFFF4964)
private val HomeMuted = Color(0xFF8C92A3)
private val HomeDivider = Color(0xFF232A38)

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun DashboardScreen(
    onOpenScanner: () -> Unit = {},
    onOpenMarkets: () -> Unit = {},
    onOpenAppSettings: () -> Unit = {},
    onOpenHistory: () -> Unit = {},
    onOpenRisingMarkets: () -> Unit = {},
    onOpenFallingMarkets: () -> Unit = {}
) {
    val context = LocalContext.current
    val repository = remember { MarketRepository() }
    var markets by remember { mutableStateOf<List<PerpetualMarket>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var refreshVersion by remember { mutableStateOf(0) }
    var recentTrades by remember { mutableStateOf(TradeHistoryStore.load(context).filter { it.outcome != TradeOutcome.Pending }.take(3)) }

    LaunchedEffect(refreshVersion) {
        loading = true
        try {
            markets = repository.getMarkets().orEmpty()
            recentTrades = TradeHistoryStore.load(context).filter { it.outcome != TradeOutcome.Pending }.take(3)
        } catch (_: Exception) {
            markets = emptyList()
        } finally {
            loading = false
        }
    }

    val positive = markets.count { it.changePercentage >= 0 }
    val negative = markets.size - positive
    val totalVolume = markets.sumOf { it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0 }
    val movers = markets.sortedByDescending { abs(it.changePercentage) }.take(5)

    PullToRefreshBox(
        isRefreshing = loading,
        onRefresh = { refreshVersion++ },
        modifier = Modifier.fillMaxSize().background(HomeBg)
    ) {
    LazyColumn(
        modifier = Modifier.fillMaxSize().padding(horizontal = 18.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 18.dp, bottom = 18.dp)
    ) {
        item {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Image(
                    painter = painterResource(R.drawable.tradementor_launcher_2027_tm),
                    contentDescription = "TradeMentor",
                    modifier = Modifier.size(66.dp).clip(RoundedCornerShape(17.dp))
                )
                Spacer(Modifier.width(14.dp))
                Column {
                    Text("TRADEMENTOR", color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 1.5.sp)
                    Text("MARKET INTELLIGENCE 2027", color = Color(0xFF55719E), fontSize = 10.sp, letterSpacing = 1.sp)
                }
                Spacer(Modifier.weight(1f))
                Surface(
                    color = HomeRaised,
                    shape = RoundedCornerShape(12.dp),
                    modifier = Modifier.size(40.dp).clickable(onClick = onOpenAppSettings)
                ) {
                    Box(contentAlignment = Alignment.Center) {
                        Text("⚙", color = Color.White, fontSize = 20.sp)
                    }
                }
            }
            Spacer(Modifier.height(16.dp))
            Surface(color = HomeRaised, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenScanner)) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Jouw signals", color = Color.White, fontWeight = FontWeight.SemiBold)
                    Spacer(Modifier.height(5.dp))
                    Text("Open direct je actuele LONG-, SHORT- en Custom-signalen.", color = HomeMuted, fontSize = 12.sp)
                    Spacer(Modifier.height(8.dp))
                    Text("Signals openen  →", color = Color(0xFF75A0FF), fontSize = 12.sp, fontWeight = FontWeight.Bold)
                }
            }
            Spacer(Modifier.height(16.dp))
            if (recentTrades.isNotEmpty()) {
                Surface(color = HomePanel, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenHistory)) {
                    Column(modifier = Modifier.padding(14.dp)) {
                        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                            Text("Laatste resultaten", color = Color.White, fontWeight = FontWeight.Bold)
                            Text("Live Watchlist →", color = Color(0xFF75A0FF), fontSize = 11.sp)
                        }
                        Spacer(Modifier.height(8.dp))
                        recentTrades.forEachIndexed { index, trade ->
                            Row(modifier = Modifier.fillMaxWidth().padding(vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text("${trade.symbol}/USD · ${if (trade.shortDirection) "SHORT" else "LONG"}", color = Color.White, fontSize = 12.sp, modifier = Modifier.weight(1f))
                                Text(
                                    if (trade.outcome == TradeOutcome.Succeeded) "SUCCEEDED" else "FAILED",
                                    color = if (trade.outcome == TradeOutcome.Succeeded) HomeGreen else HomeRed,
                                    fontSize = 11.sp,
                                    fontWeight = FontWeight.Bold
                                )
                            }
                            if (index < recentTrades.lastIndex) HorizontalDivider(color = HomeDivider)
                        }
                    }
                }
                Spacer(Modifier.height(16.dp))
            }

            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = Color.Transparent,
                shape = RoundedCornerShape(22.dp)
            ) {
                Box(
                    modifier = Modifier
                        .background(
                            Brush.linearGradient(listOf(Color(0xFF142952), Color(0xFF0C2033), Color(0xFF0B1F1E)))
                        )
                        .padding(20.dp)
                ) {
                    Column {
                        Surface(color = HomeGreen.copy(alpha = 0.16f), shape = RoundedCornerShape(20.dp)) {
                            Text("●  LIVE", color = HomeGreen, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 9.dp, vertical = 5.dp))
                        }
                        Spacer(Modifier.height(14.dp))
                        Text("Zie de markt.\nBeheers de move.", color = Color.White, fontSize = 29.sp, lineHeight = 34.sp, fontWeight = FontWeight.Bold)
                        Spacer(Modifier.height(9.dp))
                        Text("Scan echte marktdata met jouw indicatoren en timeframes.", color = Color(0xFFB0B8C7), fontSize = 13.sp)
                        Spacer(Modifier.height(18.dp))
                        Surface(
                            color = HomeBlue,
                            shape = RoundedCornerShape(12.dp),
                            modifier = Modifier.clickable(onClick = onOpenScanner)
                        ) {
                            Text("Open Scanner  →", color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 17.dp, vertical = 11.dp))
                        }
                    }
                }
            }
            Spacer(Modifier.height(24.dp))
            Text("Market pulse", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Text("Hyperliquid perpetuals · live 24u-context", color = HomeMuted, fontSize = 12.sp)
            Spacer(Modifier.height(12.dp))
        }

        if (loading) {
            item {
                Box(modifier = Modifier.fillMaxWidth().height(130.dp), contentAlignment = Alignment.Center) {
                    CircularProgressIndicator(color = HomeBlue)
                }
            }
        } else {
            item {
                Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                    PulseCard("Markten", markets.size.toString(), HomeBlue, Modifier.weight(1f), onOpenMarkets)
                    PulseCard("Stijgend", positive.toString(), HomeGreen, Modifier.weight(1f), onOpenRisingMarkets)
                    PulseCard("Dalend", negative.toString(), HomeRed, Modifier.weight(1f), onOpenFallingMarkets)
                }
                Spacer(Modifier.height(10.dp))
                Surface(color = HomePanel, shape = RoundedCornerShape(15.dp), modifier = Modifier.fillMaxWidth()) {
                    Row(modifier = Modifier.padding(15.dp), horizontalArrangement = Arrangement.SpaceBetween) {
                        Text("24u handelsvolume", color = HomeMuted)
                        Text("$${compactHomeNumber(totalVolume)}", color = Color.White, fontWeight = FontWeight.SemiBold)
                    }
                }
                Spacer(Modifier.height(24.dp))
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween, verticalAlignment = Alignment.Bottom) {
                    Column {
                        Text("Sterkste bewegingen", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        Text("Gesorteerd op absolute 24u-verandering", color = HomeMuted, fontSize = 12.sp)
                    }
                    Text("LIVE", color = HomeGreen, fontSize = 10.sp, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.height(10.dp))
                Surface(color = HomePanel, shape = RoundedCornerShape(17.dp), modifier = Modifier.fillMaxWidth()) {
                    Column {
                        movers.forEachIndexed { index, market ->
                            HomeMoverRow(market)
                            if (index < movers.lastIndex) HorizontalDivider(color = HomeDivider)
                        }
                    }
                }
            }
        }
    }
    }
}

@Composable
private fun PulseCard(label: String, value: String, accent: Color, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    Surface(modifier = modifier.then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier), color = HomePanel, shape = RoundedCornerShape(15.dp)) {
        Column(modifier = Modifier.padding(horizontal = 12.dp, vertical = 14.dp)) {
            Box(Modifier.size(7.dp).background(accent, RoundedCornerShape(10.dp)))
            Spacer(Modifier.height(10.dp))
            Text(value, color = Color.White, fontSize = 22.sp, fontWeight = FontWeight.Bold)
            Text(label, color = HomeMuted, fontSize = 11.sp)
        }
    }
}

@Composable
private fun HomeMoverRow(market: PerpetualMarket) {
    val color = if (market.changePercentage >= 0) HomeGreen else HomeRed
    Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 15.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(modifier = Modifier.weight(1f)) {
            Text("${market.market.name}/USD", color = Color.White, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text("Vol. ${compactHomeNumber(market.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0)}", color = HomeMuted, fontSize = 11.sp)
        }
        Text(homePrice(market.context.markPrice), color = Color.White, modifier = Modifier.weight(0.8f), textAlign = TextAlign.End)
        Surface(color = color, shape = RoundedCornerShape(7.dp), modifier = Modifier.padding(start = 10.dp)) {
            Text(String.format("%+.2f%%", market.changePercentage), color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 8.dp, vertical = 6.dp))
        }
    }
}

private fun compactHomeNumber(number: Double): String = when {
    number >= 1_000_000_000 -> DecimalFormat("0.00B").format(number / 1_000_000_000)
    number >= 1_000_000 -> DecimalFormat("0.00M").format(number / 1_000_000)
    number >= 1_000 -> DecimalFormat("0.00K").format(number / 1_000)
    else -> DecimalFormat("0.00").format(number)
}

private fun homePrice(value: String): String {
    val number = value.toDoubleOrNull() ?: return value
    return DecimalFormat(if (number >= 1_000) "#,##0.00" else if (number >= 1) "0.0000" else "0.########").format(number)
}
