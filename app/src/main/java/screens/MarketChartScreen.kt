package com.tradementor.app.screens

import android.graphics.Paint
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.gestures.detectTransformGestures
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Button
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.FilterChipDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.graphics.PathEffect
import androidx.compose.ui.graphics.drawscope.Stroke
import androidx.compose.ui.graphics.nativeCanvas
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.api.Candle
import com.tradementor.app.api.CustomScanSignal
import com.tradementor.app.api.CatalogMarket
import com.tradementor.app.api.PerpetualMarket
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.repository.BinanceMarketRepository
import com.tradementor.app.scanner.TrackedTrade
import com.tradementor.app.scanner.TradeOutcome
import java.text.DecimalFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import kotlin.math.pow
import kotlin.math.sqrt

private enum class ChartIndicator(val title: String) {
    Sma20("SMA 20"), Ema20("EMA 20"), Bollinger("Bollinger"), Volume("Volume")
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun MarketChartScreen(
    market: PerpetualMarket,
    repository: MarketRepository,
    onBack: () -> Unit
) {
    var interval by remember(market.market.name) { mutableStateOf("1h") }
    var candles by remember(market.market.name) { mutableStateOf<List<Candle>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshVersion by remember { mutableIntStateOf(0) }
    var zoom by remember { mutableFloatStateOf(1f) }
    var panCandles by remember { mutableFloatStateOf(0f) }
    var indicators by remember { mutableStateOf(setOf(ChartIndicator.Volume)) }
    var inspectedCandle by remember { mutableStateOf<Candle?>(null) }
    var moreTimeframes by remember { mutableStateOf(false) }
    var winChanceDirection by remember { mutableStateOf<Boolean?>(null) }

    if (winChanceDirection != null) {
        WinChanceScreen(
            result = CustomScanSignal(
                symbol = market.market.name,
                price = market.context.markPrice.toDoubleOrNull() ?: 0.0,
                matchedConditionIds = emptyList(),
                candleCloseTime = System.currentTimeMillis()
            ),
            shortDirection = winChanceDirection == true,
            repository = repository,
            onBack = { winChanceDirection = null }
        )
        return
    }

    LaunchedEffect(market.market.name, interval, refreshVersion) {
        loading = true
        error = null
        try {
            candles = repository.getChartCandles(market.market.name, interval)
            zoom = 1f
            panCandles = 0f
            inspectedCandle = null
        } catch (_: Exception) {
            error = "De koersgrafiek kon niet worden geladen."
        } finally {
            loading = false
        }
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF05070B))
            .combinedClickable(onClick = {}, onDoubleClick = onBack)
            .padding(top = 12.dp, bottom = 10.dp)
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Markets", color = Color(0xFF75A0FF), modifier = Modifier.clickable(onClick = onBack).padding(vertical = 10.dp))
            Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                Text("${market.market.name}/USD", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text(chartPrice(market.context.markPrice.toDoubleOrNull() ?: 0.0), color = Color.White, fontSize = 13.sp, fontWeight = FontWeight.Bold)
                    Text(
                        "${if (market.changePercentage >= 0) "+" else ""}${DecimalFormat("0.00").format(market.changePercentage)}%",
                        color = if (market.changePercentage >= 0) Color(0xFF08C887) else Color(0xFFFF4964),
                        fontSize = 13.sp,
                        fontWeight = FontWeight.Bold
                    )
                }
                Text("HYPERLIQUID · LIVE CANDLES", color = Color(0xFF08C887), fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            listOf("1m", "15m", "1h", "4h", "1d", "1w").forEach { value ->
                FilterChip(
                    selected = interval == value,
                    onClick = { interval = value },
                    label = { Text(value) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Color(0xFF2F68FF), selectedLabelColor = Color.White)
                )
            }
            FilterChip(selected = moreTimeframes, onClick = { moreTimeframes = !moreTimeframes }, label = { Text("Meer ···") })
        }
        if (moreTimeframes) {
            Row(
                modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
                horizontalArrangement = Arrangement.spacedBy(6.dp)
            ) {
                listOf("3m", "5m", "30m", "2h", "8h", "12h", "3d").forEach { value ->
                    FilterChip(
                        selected = interval == value,
                        onClick = { interval = value; moreTimeframes = false },
                        label = { Text(value) },
                        colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Color(0xFF2F68FF), selectedLabelColor = Color.White)
                    )
                }
            }
        }
        inspectedCandle?.let { CandleInspector(it) }
        if (ChartIndicator.Bollinger in indicators && candles.size >= 20) {
            val last20 = candles.takeLast(20).mapNotNull { it.close.toDoubleOrNull() }
            if (last20.size == 20) {
                val middle = last20.average()
                val deviation = sqrt(last20.sumOf { (it - middle).pow(2) } / 20)
                Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 4.dp), horizontalArrangement = Arrangement.spacedBy(12.dp)) {
                    Text("BOLL ${chartPrice(middle)}", color = Color(0xFF5DA9FF), fontSize = 10.sp)
                    Text("UB ${chartPrice(middle + 2 * deviation)}", color = Color(0xFFFF5F78), fontSize = 10.sp)
                    Text("LB ${chartPrice(middle - 2 * deviation)}", color = Color(0xFFFFC857), fontSize = 10.sp)
                }
            }
        }
        Text(
            "Tik voor crosshair · knijp om te zoomen · sleep horizontaal · dubbeltik terug",
            color = Color(0xFF8C92A3),
            fontSize = 10.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp)
        )
        Box(modifier = Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
            when {
                loading -> CircularProgressIndicator(color = Color(0xFF2F68FF))
                error != null -> Text(error!!, color = Color(0xFFFF4964), modifier = Modifier.clickable { refreshVersion++ })
                candles.isEmpty() -> Text("Geen candles beschikbaar", color = Color(0xFF8C92A3))
                else -> CandleChart(
                    candles = candles,
                    zoom = zoom,
                    panCandles = panCandles,
                    indicators = indicators,
                    inspectedCandle = inspectedCandle,
                    onInspect = { inspectedCandle = it },
                    onTransform = { zoomChange, panChange ->
                        zoom = (zoom * zoomChange).coerceIn(1f, 8f)
                        panCandles = (panCandles - panChange / 9f).coerceIn(0f, (candles.size - 20).coerceAtLeast(0).toFloat())
                    }
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            ChartIndicator.entries.forEach { indicator ->
                FilterChip(
                    selected = indicator in indicators,
                    onClick = { indicators = if (indicator in indicators) indicators - indicator else indicators + indicator },
                    label = { Text(indicator.title) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Color(0xFF202B41), selectedLabelColor = Color.White)
                )
            }
        }
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
            Button(
                onClick = { winChanceDirection = false },
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFF08C887)),
                modifier = Modifier.weight(1f)
            ) { Text("LONG-winkans", fontWeight = FontWeight.Bold) }
            Button(
                onClick = { winChanceDirection = true },
                colors = ButtonDefaults.buttonColors(containerColor = Color(0xFFFF4964)),
                modifier = Modifier.weight(1f)
            ) { Text("SHORT-winkans", fontWeight = FontWeight.Bold) }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BinanceChartScreen(market: CatalogMarket, onBack: () -> Unit) {
    val repository = remember { BinanceMarketRepository() }
    var interval by remember(market.pair) { mutableStateOf("1h") }
    var candles by remember(market.pair) { mutableStateOf<List<Candle>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var error by remember { mutableStateOf<String?>(null) }
    var zoom by remember { mutableFloatStateOf(1f) }
    var panCandles by remember { mutableFloatStateOf(0f) }
    var indicators by remember { mutableStateOf(setOf(ChartIndicator.Volume, ChartIndicator.Bollinger)) }
    var inspectedCandle by remember { mutableStateOf<Candle?>(null) }

    LaunchedEffect(market.pair, interval) {
        loading = true
        error = null
        try {
            candles = repository.getCandles(market.pair, interval, 500)
            zoom = 1f
            panCandles = 0f
            inspectedCandle = null
        } catch (_: Exception) {
            error = "Binance-candles konden niet worden geladen."
        } finally { loading = false }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF05070B))
            .combinedClickable(onClick = {}, onDoubleClick = onBack).padding(top = 12.dp, bottom = 8.dp)
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Markets", color = Color(0xFF75A0FF), modifier = Modifier.clickable(onClick = onBack).padding(vertical = 10.dp))
            Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                Text(market.pair, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Text("BINANCE · SPOT · LIVE CANDLES", color = Color(0xFFF3BA2F), fontSize = 9.sp, fontWeight = FontWeight.Bold)
            }
        }
        Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            listOf("1m", "5m", "15m", "30m", "1h", "4h", "1d", "1w").forEach { value ->
                FilterChip(
                    selected = interval == value,
                    onClick = { interval = value },
                    label = { Text(value) },
                    colors = FilterChipDefaults.filterChipColors(selectedContainerColor = Color(0xFFF3BA2F), selectedLabelColor = Color.Black)
                )
            }
        }
        inspectedCandle?.let { CandleInspector(it) }
        Box(modifier = Modifier.fillMaxWidth().weight(1f), contentAlignment = Alignment.Center) {
            when {
                loading -> CircularProgressIndicator(color = Color(0xFFF3BA2F))
                error != null -> Text(error!!, color = Color(0xFFFF4964))
                candles.isEmpty() -> Text("Geen candles beschikbaar", color = Color(0xFF8C92A3))
                else -> CandleChart(
                    candles = candles,
                    zoom = zoom,
                    panCandles = panCandles,
                    indicators = indicators,
                    inspectedCandle = inspectedCandle,
                    onInspect = { inspectedCandle = it },
                    onTransform = { zoomChange, panChange ->
                        zoom = (zoom * zoomChange).coerceIn(1f, 8f)
                        panCandles = (panCandles - panChange / 9f).coerceIn(0f, (candles.size - 20).coerceAtLeast(0).toFloat())
                    }
                )
            }
        }
        Row(modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            ChartIndicator.entries.forEach { indicator ->
                FilterChip(
                    selected = indicator in indicators,
                    onClick = { indicators = if (indicator in indicators) indicators - indicator else indicators + indicator },
                    label = { Text(indicator.title) }
                )
            }
        }
        Text("Binance Spot-chart · tik candle voor OHLC · knijp om te zoomen", color = Color(0xFF8C92A3), fontSize = 10.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun CandleInspector(candle: Candle) {
    val open = candle.open.toDoubleOrNull() ?: 0.0
    val close = candle.close.toDoubleOrNull() ?: 0.0
    val color = if (close >= open) Color(0xFF08C887) else Color(0xFFFF4964)
    Row(
        modifier = Modifier.fillMaxWidth().background(Color(0xFF0D131D)).padding(horizontal = 12.dp, vertical = 7.dp),
        horizontalArrangement = Arrangement.spacedBy(11.dp)
    ) {
        Text(SimpleDateFormat("dd MMM HH:mm", Locale.getDefault()).format(Date(candle.openTime)), color = Color(0xFF9AA3B5), fontSize = 10.sp)
        Text("O ${chartPrice(open)}", color = Color.White, fontSize = 10.sp)
        Text("H ${chartPrice(candle.high.toDoubleOrNull() ?: 0.0)}", color = Color.White, fontSize = 10.sp)
        Text("L ${chartPrice(candle.low.toDoubleOrNull() ?: 0.0)}", color = Color.White, fontSize = 10.sp)
        Text("C ${chartPrice(close)}", color = color, fontSize = 10.sp, fontWeight = FontWeight.Bold)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun TradeHistoryChartScreen(
    trade: TrackedTrade,
    repository: MarketRepository,
    onBack: () -> Unit
) {
    val duration = trade.expiresAt - trade.startedAt
    val interval = when {
        duration <= 60 * 60_000L -> "1m"
        duration <= 24 * 60 * 60_000L -> "15m"
        duration <= 3 * 24 * 60 * 60_000L -> "1h"
        else -> "4h"
    }
    var candles by remember(trade.id) { mutableStateOf<List<Candle>>(emptyList()) }
    var loading by remember(trade.id) { mutableStateOf(true) }
    var error by remember(trade.id) { mutableStateOf<String?>(null) }
    var zoom by remember(trade.id) { mutableFloatStateOf(1f) }
    var panCandles by remember(trade.id) { mutableFloatStateOf(0f) }
    var indicators by remember(trade.id) { mutableStateOf(setOf(ChartIndicator.Volume)) }
    val targetPrice = if (trade.shortDirection) {
        trade.entryPrice * (1.0 - trade.profitPercentage / 100.0)
    } else {
        trade.entryPrice * (1.0 + trade.profitPercentage / 100.0)
    }

    LaunchedEffect(trade.id) {
        loading = true
        try {
            candles = repository.getTradeChartCandles(trade.symbol, interval, trade.startedAt, trade.expiresAt)
        } catch (_: Exception) {
            error = "De historische tradegrafiek kon niet worden geladen."
        } finally {
            loading = false
        }
    }

    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF05070B))
            .combinedClickable(onClick = {}, onDoubleClick = onBack).padding(top = 12.dp, bottom = 10.dp)
    ) {
        Row(modifier = Modifier.fillMaxWidth().padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("‹ Live Watchlist", color = Color(0xFF75A0FF), modifier = Modifier.clickable(onClick = onBack).padding(vertical = 10.dp))
            Column(modifier = Modifier.weight(1f), horizontalAlignment = Alignment.End) {
                Text("${trade.symbol}/USD", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                Text(
                    "${if (trade.shortDirection) "SHORT" else "LONG"} · ${trade.timeframe} · ${trade.outcome.name.uppercase()}",
                    color = when (trade.outcome) {
                        TradeOutcome.Succeeded -> Color(0xFF08C887)
                        TradeOutcome.Failed -> Color(0xFFFF4964)
                        TradeOutcome.Pending -> Color(0xFF2F68FF)
                        TradeOutcome.ManuallyClosed -> Color(0xFFFFC857)
                    },
                    fontSize = 10.sp,
                    fontWeight = FontWeight.Bold
                )
            }
        }
        Row(
            modifier = Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp),
            horizontalArrangement = Arrangement.spacedBy(6.dp)
        ) {
            ChartIndicator.entries.forEach { indicator ->
                FilterChip(
                    selected = indicator in indicators,
                    onClick = { indicators = if (indicator in indicators) indicators - indicator else indicators + indicator },
                    label = { Text(indicator.title) }
                )
            }
        }
        Text(
            "Oranje = instap · blauw = doel · vlak = looptijd · dubbeltik terug",
            color = Color(0xFF8C92A3), fontSize = 10.sp, textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth().padding(bottom = 6.dp)
        )
        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            when {
                loading -> CircularProgressIndicator(color = Color(0xFF2F68FF))
                error != null -> Text(error!!, color = Color(0xFFFF4964))
                candles.isEmpty() -> Text("Geen historische candles beschikbaar", color = Color(0xFF8C92A3))
                else -> CandleChart(
                    candles = candles,
                    zoom = zoom,
                    panCandles = panCandles,
                    indicators = indicators,
                    entryPrice = trade.entryPrice,
                    targetPrice = targetPrice,
                    windowStart = trade.startedAt,
                    windowEnd = trade.expiresAt,
                    onTransform = { zoomChange, panChange ->
                        zoom = (zoom * zoomChange).coerceIn(1f, 8f)
                        panCandles = (panCandles - panChange / 9f).coerceIn(0f, (candles.size - 20).coerceAtLeast(0).toFloat())
                    }
                )
            }
        }
    }
}

@Composable
private fun CandleChart(
    candles: List<Candle>,
    zoom: Float,
    panCandles: Float,
    indicators: Set<ChartIndicator>,
    entryPrice: Double? = null,
    targetPrice: Double? = null,
    windowStart: Long? = null,
    windowEnd: Long? = null,
    inspectedCandle: Candle? = null,
    onInspect: (Candle?) -> Unit = {},
    onTransform: (Float, Float) -> Unit
) {
    Canvas(
        modifier = Modifier
            .fillMaxSize()
            .background(Color(0xFF070A10))
            .pointerInput(candles) {
                detectTransformGestures { _, pan, gestureZoom, _ -> onTransform(gestureZoom, pan.x) }
            }
            .pointerInput(candles, zoom, panCandles) {
                detectTapGestures { tap ->
                    val visibleCount = (120 / zoom).toInt().coerceIn(20, candles.size)
                    val end = (candles.size - panCandles.toInt()).coerceIn(visibleCount, candles.size)
                    val start = (end - visibleCount).coerceAtLeast(0)
                    val plotWidth = (size.width - 92f).coerceAtLeast(1f)
                    val index = (start + (tap.x.coerceIn(0f, plotWidth - 1f) / plotWidth * visibleCount).toInt())
                        .coerceIn(start, end - 1)
                    onInspect(candles[index])
                }
            }
    ) {
        val baseVisible = 120
        val visibleCount = (baseVisible / zoom).toInt().coerceIn(20, candles.size)
        val end = (candles.size - panCandles.toInt()).coerceIn(visibleCount, candles.size)
        val start = (end - visibleCount).coerceAtLeast(0)
        val visible = candles.subList(start, end)
        val opens = visible.mapNotNull { it.open.toDoubleOrNull() }
        val closes = visible.mapNotNull { it.close.toDoubleOrNull() }
        val highs = visible.mapNotNull { it.high.toDoubleOrNull() }
        val lows = visible.mapNotNull { it.low.toDoubleOrNull() }
        if (opens.size != visible.size || closes.size != visible.size || highs.size != visible.size || lows.size != visible.size) return@Canvas

        val plotRight = (size.width - 92f).coerceAtLeast(size.width * 0.72f)
        val timeAxisTop = size.height - 30f
        val chartBottom = if (ChartIndicator.Volume in indicators) size.height * 0.73f else timeAxisTop
        val chartTop = 22f
        val priceMin = (lows + listOfNotNull(entryPrice, targetPrice)).minOrNull() ?: return@Canvas
        val priceMax = (highs + listOfNotNull(entryPrice, targetPrice)).maxOrNull() ?: return@Canvas
        val range = (priceMax - priceMin).takeIf { it > 0.0 } ?: 1.0
        fun y(price: Double) = chartBottom - (((price - priceMin) / range).toFloat() * (chartBottom - chartTop))

        repeat(5) { index ->
            val lineY = chartTop + (chartBottom - chartTop) * index / 4f
            drawLine(Color(0xFF1B2230), Offset(0f, lineY), Offset(plotRight, lineY), 1f)
            val price = priceMax - range * index / 4.0
            drawContext.canvas.nativeCanvas.drawText(
                chartPrice(price), size.width - 6f, lineY - 4f,
                Paint().apply { color = android.graphics.Color.rgb(150, 158, 174); textSize = 21f; textAlign = Paint.Align.RIGHT; isAntiAlias = true }
            )
        }

        repeat(5) { index ->
            val lineX = plotRight * index / 4f
            drawLine(Color(0xFF151C28), Offset(lineX, chartTop), Offset(lineX, timeAxisTop), 1f)
            val candleIndex = (index * (visible.lastIndex) / 4f).toInt().coerceIn(0, visible.lastIndex)
            val label = SimpleDateFormat("dd MMM HH:mm", Locale.getDefault()).format(Date(visible[candleIndex].openTime))
            drawContext.canvas.nativeCanvas.drawText(
                label, lineX.coerceIn(52f, plotRight - 52f), size.height - 6f,
                Paint().apply { color = android.graphics.Color.rgb(130, 140, 158); textSize = 19f; textAlign = Paint.Align.CENTER; isAntiAlias = true }
            )
        }

        if (windowStart != null && windowEnd != null) {
            fun timeX(timestamp: Long): Float {
                val first = visible.first().openTime
                val last = visible.last().closeTime
                val fraction = ((timestamp - first).toDouble() / (last - first).coerceAtLeast(1L)).toFloat()
                return (fraction * plotRight).coerceIn(0f, plotRight)
            }
            val left = timeX(windowStart)
            val right = timeX(windowEnd)
            if (right > left) drawRect(Color(0x142F68FF), Offset(left, chartTop), androidx.compose.ui.geometry.Size(right - left, chartBottom - chartTop))
        }

        fun drawTradeLine(price: Double?, color: Color, label: String) {
            if (price == null) return
            val lineY = y(price)
            drawLine(color, Offset(0f, lineY), Offset(plotRight, lineY), 2f)
            drawContext.canvas.nativeCanvas.drawText(
                "$label ${chartPrice(price)}", 8f, lineY - 5f,
                Paint().apply { this.color = color.toArgb(); textSize = 22f; isAntiAlias = true }
            )
        }
        drawTradeLine(entryPrice, Color(0xFFFFA726), "ENTRY")
        drawTradeLine(targetPrice, Color(0xFF2F68FF), "TARGET")

        val step = plotRight / visible.size
        val bodyWidth = (step * 0.62f).coerceAtLeast(2f)
        visible.indices.forEach { index ->
            val x = step * index + step / 2f
            val rising = closes[index] >= opens[index]
            val color = if (rising) Color(0xFF08C887) else Color(0xFFFF4964)
            drawLine(color, Offset(x, y(highs[index])), Offset(x, y(lows[index])), 1.5f)
            val top = y(maxOf(opens[index], closes[index]))
            val bottom = y(minOf(opens[index], closes[index]))
            drawRect(color, Offset(x - bodyWidth / 2f, top), androidx.compose.ui.geometry.Size(bodyWidth, (bottom - top).coerceAtLeast(2f)))
        }

        val allCloses = candles.mapNotNull { it.close.toDoubleOrNull() }
        fun drawSeries(values: List<Double?>, color: Color) {
            val path = Path()
            var started = false
            values.subList(start, end).forEachIndexed { index, value ->
                if (value != null) {
                    val point = Offset(step * index + step / 2f, y(value))
                    if (!started) { path.moveTo(point.x, point.y); started = true } else path.lineTo(point.x, point.y)
                }
            }
            if (started) drawPath(path, color, style = Stroke(width = 2.2f))
        }
        if (ChartIndicator.Sma20 in indicators) drawSeries(movingAverage(allCloses, 20), Color(0xFFFFC857))
        if (ChartIndicator.Ema20 in indicators) drawSeries(exponentialAverage(allCloses, 20), Color(0xFF5DA9FF))
        if (ChartIndicator.Bollinger in indicators) {
            val bands = bollingerBands(allCloses, 20)
            drawSeries(bands.first, Color(0xFFB178FF))
            drawSeries(bands.second, Color(0xFFB178FF))
        }
        if (ChartIndicator.Volume in indicators) {
            val volumes = visible.map { it.volume.toDoubleOrNull() ?: 0.0 }
            val maxVolume = volumes.maxOrNull()?.takeIf { it > 0.0 } ?: 1.0
            volumes.forEachIndexed { index, volume ->
                val height = ((volume / maxVolume).toFloat() * size.height * 0.15f)
                val color = if (closes[index] >= opens[index]) Color(0x6608C887) else Color(0x66FF4964)
                drawRect(color, Offset(step * index + step * 0.2f, timeAxisTop - height), androidx.compose.ui.geometry.Size(step * 0.6f, height))
            }
        }
        val lastPrice = closes.last()
        drawLine(Color(0xFF2F68FF), Offset(0f, y(lastPrice)), Offset(plotRight, y(lastPrice)), 1.2f)
        drawRect(Color(0xFF2F68FF), Offset(plotRight, y(lastPrice) - 13f), androidx.compose.ui.geometry.Size(size.width - plotRight, 26f))
        drawContext.canvas.nativeCanvas.drawText(
            chartPrice(lastPrice), size.width - 6f, y(lastPrice) + 7f,
            Paint().apply { color = android.graphics.Color.WHITE; textSize = 20f; textAlign = Paint.Align.RIGHT; isAntiAlias = true }
        )

        inspectedCandle?.let { selected ->
            val selectedIndex = visible.indexOfFirst { it.openTime == selected.openTime }
            if (selectedIndex >= 0) {
                val x = step * selectedIndex + step / 2f
                val selectedClose = selected.close.toDoubleOrNull() ?: return@let
                val crosshair = Color(0xFF7E8BA3)
                drawLine(crosshair, Offset(x, chartTop), Offset(x, timeAxisTop), 1.2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(7f, 7f)))
                drawLine(crosshair, Offset(0f, y(selectedClose)), Offset(plotRight, y(selectedClose)), 1.2f, pathEffect = PathEffect.dashPathEffect(floatArrayOf(7f, 7f)))
                drawCircle(Color.White, radius = 4f, center = Offset(x, y(selectedClose)))
            }
        }
    }
}

private fun movingAverage(values: List<Double>, period: Int): List<Double?> = values.indices.map { index ->
    if (index + 1 < period) null else values.subList(index + 1 - period, index + 1).average()
}

private fun exponentialAverage(values: List<Double>, period: Int): List<Double?> {
    if (values.isEmpty()) return emptyList()
    val multiplier = 2.0 / (period + 1.0)
    var ema = values.first()
    return values.mapIndexed { index, value ->
        ema = if (index == 0) value else (value - ema) * multiplier + ema
        if (index + 1 < period) null else ema
    }
}

private fun bollingerBands(values: List<Double>, period: Int): Pair<List<Double?>, List<Double?>> {
    val upper = mutableListOf<Double?>()
    val lower = mutableListOf<Double?>()
    values.indices.forEach { index ->
        if (index + 1 < period) {
            upper += null; lower += null
        } else {
            val window = values.subList(index + 1 - period, index + 1)
            val mean = window.average()
            val deviation = sqrt(window.sumOf { (it - mean).pow(2) } / period)
            upper += mean + 2 * deviation
            lower += mean - 2 * deviation
        }
    }
    return upper to lower
}

private fun chartPrice(value: Double): String = DecimalFormat(
    when { value >= 1_000 -> "#,##0.00"; value >= 1 -> "0.0000"; else -> "0.########" }
).format(value)
