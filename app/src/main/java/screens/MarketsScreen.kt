package com.tradementor.app.screens

import androidx.compose.animation.core.Animatable
import androidx.compose.animation.core.tween
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.ExposedDropdownMenuBox
import androidx.compose.material3.ExposedDropdownMenuDefaults
import androidx.compose.material3.FilterChip
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.api.PerpetualMarket
import com.tradementor.app.api.CatalogExchange
import com.tradementor.app.api.CatalogMarket
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.repository.ExchangeCatalogRepository
import com.tradementor.app.repository.MarketUniverseSelection
import com.tradementor.app.repository.MarketRepository
import java.text.DecimalFormat

private val MarketGreen = Color(0xFF08C887)
private val MarketRed = Color(0xFFFF4964)
private val MutedText = Color(0xFF8C92A3)
private val PanelColor = Color(0xFF121318)
private val DividerColor = Color(0xFF23252D)

enum class MarketDirection(val title: String) { All("Alle"), Rising("Stijgend"), Falling("Dalend") }
private enum class MarketSort(val title: String) {
    VolumeHigh("Volume: hoog naar laag"),
    VolumeLow("Volume: laag naar hoog"),
    ChangeHigh("24u: grootste stijging"),
    ChangeLow("24u: grootste daling"),
    PriceHigh("Prijs: hoog naar laag"),
    PriceLow("Prijs: laag naar hoog"),
    NameAscending("Naam: A–Z"),
    NameDescending("Naam: Z–A")
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class, ExperimentalFoundationApi::class)
@Composable
fun MarketsScreen(initialDirection: MarketDirection = MarketDirection.All) {
    val repository = remember { MarketRepository() }
    val catalogRepository = remember { ExchangeCatalogRepository() }
    var exchangeCatalog by remember { mutableStateOf<List<CatalogExchange>>(emptyList()) }
    var catalogMarkets by remember { mutableStateOf<List<CatalogMarket>>(emptyList()) }
    var selectedExchange by remember { mutableStateOf(MarketUniverseSelection.exchangeName) }
    var selectedMarketType by remember { mutableStateOf(MarketUniverseSelection.marketType) }
    var selectedQuote by remember { mutableStateOf(MarketUniverseSelection.quoteCurrency) }
    var exchangeExpanded by remember { mutableStateOf(false) }
    var marketExpanded by remember { mutableStateOf(false) }
    var quoteExpanded by remember { mutableStateOf(false) }
    var query by remember { mutableStateOf("") }
    var direction by remember(initialDirection) { mutableStateOf(initialDirection) }
    var sort by remember { mutableStateOf(MarketSort.VolumeHigh) }
    var sortExpanded by remember { mutableStateOf(false) }
    var markets by remember { mutableStateOf<List<PerpetualMarket>>(emptyList()) }
    var isLoading by remember { mutableStateOf(false) }
    var errorMessage by remember { mutableStateOf<String?>(null) }
    var refreshRequest by remember { mutableIntStateOf(0) }
    var requestedMarket by remember { mutableStateOf<PerpetualMarket?>(null) }
    var displayedMarket by remember { mutableStateOf<PerpetualMarket?>(null) }
    var requestedChartMarket by remember { mutableStateOf<PerpetualMarket?>(null) }
    var displayedChartMarket by remember { mutableStateOf<PerpetualMarket?>(null) }
    var catalogChartMarket by remember { mutableStateOf<CatalogMarket?>(null) }
    var catalogNotice by remember { mutableStateOf<String?>(null) }
    val pageRotation = remember { Animatable(0f) }

    val exchanges = listOf("Hyperliquid") + exchangeCatalog.map { it.name }.filterNot { it == "Hyperliquid" }
    val selectedCatalogExchange = exchangeCatalog.firstOrNull { it.name == selectedExchange }
    val marketTypes = if (selectedExchange == "Hyperliquid") {
        listOf("Perpetuals", "Spot")
    } else {
        catalogMarkets.map { it.category.ifBlank { "Overig" } }.distinct().sorted().ifEmpty {
            selectedCatalogExchange?.type?.map { it.replaceFirstChar(Char::uppercase) }.orEmpty().ifEmpty { listOf("Spot") }
        }
    }
    val quoteCurrencies = if (selectedExchange == "Hyperliquid") listOf("USD") else
        catalogMarkets.map { it.quoteSymbol }.filter { it.isNotBlank() }.distinct().sortedWith(compareBy<String> { it !in listOf("USDT", "USDC", "USD", "EUR", "BTC", "ETH") }.thenBy { it })
    val isLiveSelection = selectedExchange == "Hyperliquid" && selectedMarketType == "Perpetuals"
    val visibleCatalogMarkets = remember(catalogMarkets, selectedMarketType, selectedQuote, query) {
        catalogMarkets.filter {
            it.category.equals(selectedMarketType, true) && it.quoteSymbol == selectedQuote &&
                (it.pair.contains(query.trim(), true) || it.baseCurrencyName.contains(query.trim(), true))
        }
    }
    val visibleMarkets = remember(markets, query, direction, sort) {
        val filtered = markets.filter { market ->
            market.market.name.contains(query.trim(), ignoreCase = true) && when (direction) {
                MarketDirection.All -> true
                MarketDirection.Rising -> market.changePercentage >= 0
                MarketDirection.Falling -> market.changePercentage < 0
            }
        }
        when (sort) {
            MarketSort.VolumeHigh -> filtered.sortedByDescending { it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0 }
            MarketSort.VolumeLow -> filtered.sortedBy { it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0 }
            MarketSort.ChangeHigh -> filtered.sortedByDescending { it.changePercentage }
            MarketSort.ChangeLow -> filtered.sortedBy { it.changePercentage }
            MarketSort.PriceHigh -> filtered.sortedByDescending { it.context.markPrice.toDoubleOrNull() ?: 0.0 }
            MarketSort.PriceLow -> filtered.sortedBy { it.context.markPrice.toDoubleOrNull() ?: 0.0 }
            MarketSort.NameAscending -> filtered.sortedBy { it.market.name }
            MarketSort.NameDescending -> filtered.sortedByDescending { it.market.name }
        }
    }

    LaunchedEffect(Unit) {
        runCatching { catalogRepository.getTopExchanges(25) }.onSuccess { exchangeCatalog = it }
    }
    LaunchedEffect(selectedExchange) {
        if (selectedExchange == "Hyperliquid") {
            catalogMarkets = emptyList()
            selectedMarketType = "Perpetuals"
            selectedQuote = "USD"
        } else {
            isLoading = true
            errorMessage = null
            try {
                val exchange = exchangeCatalog.firstOrNull { it.name == selectedExchange }
                catalogMarkets = exchange?.let { catalogRepository.getMarkets(it.id) }.orEmpty()
                selectedMarketType = catalogMarkets.firstOrNull()?.category ?: "Spot"
                selectedQuote = catalogMarkets.map { it.quoteSymbol }.firstOrNull { it in listOf("USDT", "USDC", "USD", "EUR", "BTC") }
                    ?: catalogMarkets.firstOrNull()?.quoteSymbol.orEmpty()
            } catch (_: Exception) {
                errorMessage = "Markten voor $selectedExchange konden niet worden geladen."
                catalogMarkets = emptyList()
            } finally { isLoading = false }
        }
        MarketUniverseSelection.exchangeName = selectedExchange
        MarketUniverseSelection.exchangeId = exchangeCatalog.firstOrNull { it.name == selectedExchange }?.id ?: "hyperliquid"
        MarketUniverseSelection.marketType = selectedMarketType
        MarketUniverseSelection.quoteCurrency = selectedQuote
    }
    LaunchedEffect(selectedMarketType, selectedQuote) {
        MarketUniverseSelection.marketType = selectedMarketType
        MarketUniverseSelection.quoteCurrency = selectedQuote
    }
    LaunchedEffect(isLiveSelection, refreshRequest) {
        if (!isLiveSelection) {
            markets = emptyList()
            errorMessage = null
            return@LaunchedEffect
        }
        isLoading = true
        errorMessage = null
        try {
            markets = repository.getMarkets()?.sortedByDescending {
                it.context.dayNotionalVolume.toDoubleOrNull() ?: 0.0
            } ?: run {
                errorMessage = "Hyperliquid gaf geen geldige reactie."
                emptyList()
            }
        } catch (_: Exception) {
            errorMessage = "Kan Hyperliquid niet bereiken. Controleer je verbinding."
        } finally {
            isLoading = false
        }
    }

    LaunchedEffect(requestedMarket, requestedChartMarket) {
        if (requestedMarket == displayedMarket && requestedChartMarket == displayedChartMarket) return@LaunchedEffect
        pageRotation.animateTo(90f, tween(260))
        displayedChartMarket = requestedChartMarket
        displayedMarket = if (requestedChartMarket == null) requestedMarket else null
        pageRotation.snapTo(-90f)
        pageRotation.animateTo(0f, tween(320))
    }

    PullToRefreshBox(
        isRefreshing = isLoading,
        onRefresh = {
            if (displayedMarket == null && isLiveSelection) refreshRequest++
        },
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .graphicsLayer {
                rotationY = pageRotation.value
                cameraDistance = 18f * density
            }
    ) {
        if (catalogChartMarket != null) {
            BinanceChartScreen(market = catalogChartMarket!!, onBack = { catalogChartMarket = null })
        } else if (displayedChartMarket != null) {
            MarketChartScreen(
                market = displayedChartMarket!!,
                repository = repository,
                onBack = { requestedChartMarket = null }
            )
        } else if (displayedMarket != null) {
            MarketDetailScreen(
                item = displayedMarket!!,
                onBack = { requestedMarket = null }
            )
        } else {
            Column(
                modifier = Modifier
                    .fillMaxSize()
                    .padding(horizontal = 16.dp)
                    .padding(top = 16.dp)
            ) {
        catalogNotice?.let {
            Surface(color = Color(0xFF2A2110), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().clickable { catalogNotice = null }) {
                Text(it, color = Color(0xFFFFC857), fontSize = 11.sp, modifier = Modifier.padding(11.dp))
            }
            Spacer(Modifier.height(8.dp))
        }
        Text("Markets", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.Bold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(14.dp))

        OutlinedTextField(
            value = query,
            onValueChange = { query = it },
            modifier = Modifier.fillMaxWidth(),
            placeholder = { Text("Zoek een paar", color = MutedText) },
            leadingIcon = { Text("⌕", color = MutedText, fontSize = 26.sp) },
            singleLine = true,
            shape = RoundedCornerShape(22.dp),
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = PanelColor,
                unfocusedContainerColor = PanelColor,
                focusedBorderColor = Color(0xFF2F68FF),
                unfocusedBorderColor = Color.Transparent,
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White
            )
        )
        Spacer(Modifier.height(14.dp))

        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            Selector(
                value = selectedExchange,
                options = exchanges,
                expanded = exchangeExpanded,
                onExpandedChange = { exchangeExpanded = it },
                onSelected = { selectedExchange = it },
                width = 154,
                fullOptions = setOf("Hyperliquid"),
                partialOptions = setOf("Binance")
            )
            Selector(
                value = selectedMarketType,
                options = marketTypes,
                expanded = marketExpanded,
                onExpandedChange = { marketExpanded = it },
                onSelected = { selectedMarketType = it },
                width = 154
            )
            Selector(
                value = selectedQuote.ifBlank { "Quote" },
                options = quoteCurrencies,
                expanded = quoteExpanded,
                onExpandedChange = { quoteExpanded = it },
                onSelected = { selectedQuote = it },
                width = 154
            )
        }
        val integration = marketIntegrationStatus(selectedExchange, selectedMarketType, selectedQuote)
        Spacer(Modifier.height(8.dp))
        Surface(color = integration.color.copy(alpha = 0.14f), shape = RoundedCornerShape(11.dp), modifier = Modifier.fillMaxWidth()) {
            Row(modifier = Modifier.padding(horizontal = 11.dp, vertical = 9.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("●", color = integration.color, fontSize = 13.sp)
                Spacer(Modifier.width(7.dp))
                Column {
                    Text(integration.title, color = integration.color, fontSize = 11.sp, fontWeight = FontWeight.Bold)
                    Text(integration.detail, color = MutedText, fontSize = 10.sp)
                }
            }
        }
        Spacer(Modifier.height(11.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(7.dp), verticalArrangement = Arrangement.spacedBy(5.dp)) {
            MarketDirection.entries.forEach { option ->
                FilterChip(selected = direction == option, onClick = { direction = option }, label = { Text(option.title) })
            }
            Box {
                FilterChip(
                    selected = sortExpanded,
                    onClick = { sortExpanded = true },
                    label = { Text("Sorteer: ${sort.title}") }
                )
                DropdownMenu(
                    expanded = sortExpanded,
                    onDismissRequest = { sortExpanded = false },
                    modifier = Modifier.background(PanelColor)
                ) {
                    MarketSort.entries.forEach { option ->
                        DropdownMenuItem(
                            text = {
                                Text(
                                    if (sort == option) "✓  ${option.title}" else option.title,
                                    color = Color.White
                                )
                            },
                            onClick = {
                                sort = option
                                sortExpanded = false
                            }
                        )
                    }
                }
            }
        }
        Spacer(Modifier.height(12.dp))

        Row(
            modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp),
            verticalAlignment = Alignment.CenterVertically
        ) {
            Text(
                "Paar${sortArrow(sort, MarketSort.NameAscending, MarketSort.NameDescending)}",
                color = if (sort == MarketSort.NameAscending || sort == MarketSort.NameDescending) Color.White else MutedText,
                modifier = Modifier.weight(1.35f).clickable {
                    sort = if (sort == MarketSort.NameAscending) MarketSort.NameDescending else MarketSort.NameAscending
                }
            )
            Text(
                "Laatste prijs${sortArrow(sort, MarketSort.PriceHigh, MarketSort.PriceLow)}",
                color = if (sort == MarketSort.PriceHigh || sort == MarketSort.PriceLow) Color.White else MutedText,
                modifier = Modifier.weight(0.9f).clickable {
                    sort = if (sort == MarketSort.PriceHigh) MarketSort.PriceLow else MarketSort.PriceHigh
                },
                textAlign = TextAlign.End
            )
            Text(
                if (isLiveSelection) "24u${sortArrow(sort, MarketSort.ChangeHigh, MarketSort.ChangeLow)}" else "Volume",
                color = if (sort == MarketSort.ChangeHigh || sort == MarketSort.ChangeLow) Color.White else MutedText,
                modifier = Modifier.weight(0.65f).clickable {
                    sort = if (sort == MarketSort.ChangeHigh) MarketSort.ChangeLow else MarketSort.ChangeHigh
                },
                textAlign = TextAlign.End
            )
        }
        Spacer(Modifier.height(8.dp))
        HorizontalDivider(color = DividerColor)

        Box(modifier = Modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
            when {
                isLoading -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    CircularProgressIndicator(color = MarketGreen)
                    Spacer(Modifier.height(12.dp))
                    Text("Live markten laden…", color = MutedText)
                }
                errorMessage != null -> Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    Text(errorMessage!!, color = MarketRed, textAlign = TextAlign.Center)
                    Spacer(Modifier.height(12.dp))
                    TradeMentorPrimaryButton(label = "Opnieuw proberen", onClick = { refreshRequest++ })
                }
                isLiveSelection && visibleMarkets.isEmpty() -> Text("Geen paren gevonden", color = MutedText)
                isLiveSelection -> LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(visibleMarkets, key = { it.market.name }) { item ->
                        MarketRow(
                            item = item,
                            onClick = {
                                requestedChartMarket = null
                                requestedMarket = item
                            },
                            onDoubleClick = {
                                requestedMarket = null
                                requestedChartMarket = item
                            }
                        )
                        HorizontalDivider(color = DividerColor)
                    }
                }
                visibleCatalogMarkets.isEmpty() -> Text("Geen echte paren gevonden voor deze combinatie.", color = MutedText, textAlign = TextAlign.Center)
                else -> LazyColumn(modifier = Modifier.fillMaxSize()) {
                    items(visibleCatalogMarkets, key = { "${it.pair}-${it.category}" }) { item ->
                        CatalogMarketRow(
                            item = item,
                            onDoubleClick = {
                                if (selectedExchange.equals("Binance", true) && item.category.equals("Spot", true)) {
                                    catalogChartMarket = item
                                } else {
                                    catalogNotice = "De native candlechart voor $selectedExchange ${item.category} wordt nog aangesloten."
                                }
                            }
                        )
                        HorizontalDivider(color = DividerColor)
                    }
                }
            }
        }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun CatalogMarketRow(item: CatalogMarket, onDoubleClick: () -> Unit) {
    Row(
        modifier = Modifier.fillMaxWidth().combinedClickable(onClick = {}, onDoubleClick = onDoubleClick).padding(vertical = 13.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1.35f)) {
            Text(item.pair, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold, maxLines = 1)
            Text("${item.category} · ${item.baseCurrencyName}", color = MutedText, fontSize = 10.sp, maxLines = 1, overflow = TextOverflow.Ellipsis)
        }
        Text(
            formatCatalogPrice(item.usdPrice),
            color = Color.White,
            fontSize = 14.sp,
            modifier = Modifier.weight(0.9f),
            textAlign = TextAlign.End,
            maxLines = 1
        )
        Text(
            "$${formatCatalogVolume(item.usdVolume24h)}",
            color = Color(0xFF9DB4FF),
            fontSize = 11.sp,
            modifier = Modifier.weight(0.65f),
            textAlign = TextAlign.End,
            maxLines = 1
        )
    }
}

private fun formatCatalogPrice(value: Double): String = DecimalFormat(
    when { value >= 1_000 -> "#,##0.00"; value >= 1 -> "0.0000"; else -> "0.########" }
).format(value)

private fun formatCatalogVolume(value: Double): String = when {
    value >= 1_000_000_000 -> String.format("%.1fB", value / 1_000_000_000)
    value >= 1_000_000 -> String.format("%.1fM", value / 1_000_000)
    value >= 1_000 -> String.format("%.1fK", value / 1_000)
    else -> DecimalFormat("0").format(value)
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
private fun Selector(
    value: String,
    options: List<String>,
    expanded: Boolean,
    onExpandedChange: (Boolean) -> Unit,
    onSelected: (String) -> Unit,
    width: Int = 164,
    fullOptions: Set<String> = emptySet(),
    partialOptions: Set<String> = emptySet()
) {
    ExposedDropdownMenuBox(
        expanded = expanded,
        onExpandedChange = onExpandedChange,
        modifier = Modifier.width(width.dp)
    ) {
        OutlinedTextField(
            value = value,
            onValueChange = {},
            readOnly = true,
            singleLine = true,
            modifier = Modifier.menuAnchor().fillMaxWidth(),
            shape = RoundedCornerShape(12.dp),
            trailingIcon = { ExposedDropdownMenuDefaults.TrailingIcon(expanded) },
            colors = OutlinedTextFieldDefaults.colors(
                focusedContainerColor = PanelColor,
                unfocusedContainerColor = PanelColor,
                focusedBorderColor = Color(0xFF2F68FF),
                unfocusedBorderColor = DividerColor,
                focusedTextColor = Color.White,
                unfocusedTextColor = Color.White
            )
        )
        DropdownMenu(
            expanded = expanded,
            onDismissRequest = { onExpandedChange(false) },
            modifier = Modifier.background(PanelColor)
        ) {
            options.forEach { option ->
                val statusColor = when (option) {
                    in fullOptions -> MarketGreen
                    in partialOptions -> Color(0xFFFFC857)
                    else -> MutedText
                }
                DropdownMenuItem(
                    text = {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Text("●", color = statusColor)
                            Spacer(Modifier.width(7.dp))
                            Text(
                                "$option  ${when (option) { in fullOptions -> "VOLLEDIG"; in partialOptions -> "DEELS"; else -> "CATALOGUS" }}",
                                color = Color.White
                            )
                        }
                    },
                    onClick = {
                        onSelected(option)
                        onExpandedChange(false)
                    }
                )
            }
        }
    }
}

private data class MarketIntegrationStatus(val title: String, val detail: String, val color: Color)

private fun marketIntegrationStatus(exchange: String, type: String, quote: String): MarketIntegrationStatus = when {
    exchange == "Hyperliquid" && type == "Perpetuals" && quote == "USD" -> MarketIntegrationStatus(
        "VOLLEDIG ACTIEF",
        "Markten, chart, Signals, Custom, winkans en History zijn aangesloten.",
        MarketGreen
    )
    exchange.equals("Binance", true) && type.equals("Spot", true) -> MarketIntegrationStatus(
        "DEELS ACTIEF",
        "Markten, chart en zelfstandige Signals werken. Custom volgt nog.",
        Color(0xFFFFC857)
    )
    else -> MarketIntegrationStatus(
        "ALLEEN CATALOGUS",
        "Pairs en marktmetadata zijn zichtbaar; chart en Signals zijn nog niet aangesloten.",
        MutedText
    )
}

@Composable
@OptIn(ExperimentalFoundationApi::class)
private fun MarketRow(item: PerpetualMarket, onClick: () -> Unit, onDoubleClick: () -> Unit) {
    val change = item.changePercentage
    val changeColor = if (change >= 0.0) MarketGreen else MarketRed
    Row(
        modifier = Modifier
            .fillMaxWidth()
            .combinedClickable(onClick = onClick, onDoubleClick = onDoubleClick)
            .padding(vertical = 14.dp, horizontal = 4.dp),
        verticalAlignment = Alignment.CenterVertically
    ) {
        Column(modifier = Modifier.weight(1.35f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(
                    "${item.market.name}/USD",
                    color = Color.White,
                    fontSize = 16.sp,
                    fontWeight = FontWeight.SemiBold,
                    maxLines = 1,
                    overflow = TextOverflow.Ellipsis
                )
                Spacer(Modifier.width(5.dp))
                Text("Perp", color = MutedText, fontSize = 11.sp)
            }
            Spacer(Modifier.height(4.dp))
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(formatCompact(item.context.dayNotionalVolume), color = MutedText, fontSize = 13.sp)
                Spacer(Modifier.width(7.dp))
                Surface(color = Color(0xFF102A62), shape = RoundedCornerShape(5.dp)) {
                    Text(
                        "${item.market.maxLeverage}×",
                        color = Color(0xFF8DB6FF),
                        fontSize = 11.sp,
                        modifier = Modifier.padding(horizontal = 5.dp, vertical = 2.dp)
                    )
                }
            }
        }
        Text(
            formatPrice(item.context.markPrice),
            color = changeColor,
            fontSize = 16.sp,
            modifier = Modifier.weight(0.9f),
            textAlign = TextAlign.End,
            maxLines = 1
        )
        Box(modifier = Modifier.weight(0.65f), contentAlignment = Alignment.CenterEnd) {
            Surface(color = changeColor, shape = RoundedCornerShape(7.dp)) {
                Text(
                    String.format("%+.2f%%", change),
                    color = Color.White,
                    fontSize = 13.sp,
                    fontWeight = FontWeight.SemiBold,
                    modifier = Modifier.padding(horizontal = 8.dp, vertical = 7.dp)
                )
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MarketDetailScreen(item: PerpetualMarket, onBack: () -> Unit) {
    val change = item.changePercentage
    val changeColor = if (change >= 0.0) MarketGreen else MarketRed
    val currentPrice = item.context.markPrice.toDoubleOrNull() ?: 0.0
    val previousPrice = item.context.previousDayPrice.toDoubleOrNull() ?: 0.0
    val priceDifference = currentPrice - previousPrice
    val fundingPercentage = (item.context.funding.toDoubleOrNull() ?: 0.0) * 100.0

    LazyColumn(
        modifier = Modifier
            .fillMaxSize()
            .background(Color.Black)
            .combinedClickable(
                onClick = {},
                onDoubleClick = onBack
            )
            .padding(horizontal = 18.dp)
            .padding(top = 18.dp, bottom = 16.dp)
    ) {
        item {
            Row(
                modifier = Modifier.fillMaxWidth(),
                horizontalArrangement = Arrangement.SpaceBetween,
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(
                    "‹  Markets",
                    color = Color(0xFF75A0FF),
                    fontSize = 16.sp,
                    modifier = Modifier.clickable(onClick = onBack).padding(vertical = 10.dp)
                )
                Surface(color = Color(0xFF102A62), shape = RoundedCornerShape(7.dp)) {
                    Text(
                        "HYPERLIQUID · PERPETUAL",
                        color = Color(0xFF8DB6FF),
                        fontSize = 11.sp,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 9.dp, vertical = 6.dp)
                    )
                }
            }
            Spacer(Modifier.height(22.dp))
            Text(
                "${item.market.name}/USD",
                color = Color.White,
                fontSize = 30.sp,
                fontWeight = FontWeight.Bold
            )
            Text("Hyperliquid perpetual contract", color = MutedText, fontSize = 14.sp)
            Spacer(Modifier.height(26.dp))

            Surface(
                modifier = Modifier.fillMaxWidth(),
                color = PanelColor,
                shape = RoundedCornerShape(20.dp)
            ) {
                Column(modifier = Modifier.padding(20.dp)) {
                    Text("Mark price", color = MutedText, fontSize = 13.sp)
                    Spacer(Modifier.height(5.dp))
                    Text(
                        "$${formatPrice(item.context.markPrice)}",
                        color = Color.White,
                        fontSize = 35.sp,
                        fontWeight = FontWeight.Bold
                    )
                    Spacer(Modifier.height(10.dp))
                    Surface(color = changeColor, shape = RoundedCornerShape(8.dp)) {
                        Text(
                            "${String.format("%+.2f%%", change)}  (${formatSignedPrice(priceDifference)})",
                            color = Color.White,
                            fontWeight = FontWeight.SemiBold,
                            modifier = Modifier.padding(horizontal = 10.dp, vertical = 7.dp)
                        )
                    }
                    Spacer(Modifier.height(18.dp))
                    MiniPriceChart(positive = change >= 0.0)
                    Spacer(Modifier.height(8.dp))
                    Text("Indicatieve 24u-richting", color = MutedText, fontSize = 11.sp)
                }
            }
            Spacer(Modifier.height(18.dp))

            Text("Marktgegevens", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            DetailGrid(
                values = listOf(
                    "24u volume" to "$${formatCompact(item.context.dayNotionalVolume)}",
                    "Open interest" to formatCompact(item.context.openInterest),
                    "Funding" to String.format("%+.4f%%", fundingPercentage),
                    "Max. leverage" to "${item.market.maxLeverage}×",
                    "Vorige dagprijs" to "$${formatPrice(item.context.previousDayPrice)}",
                    "Prijsdecimalen" to item.market.sizeDecimals.toString()
                )
            )
            Spacer(Modifier.height(22.dp))

            Text("Over dit contract", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
            Spacer(Modifier.height(10.dp))
            Surface(color = PanelColor, shape = RoundedCornerShape(16.dp)) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text(assetBackground(item.market.name), color = Color(0xFFD5D7DE), lineHeight = 21.sp)
                    Spacer(Modifier.height(13.dp))
                    HorizontalDivider(color = DividerColor)
                    Spacer(Modifier.height(13.dp))
                    Text(
                        "Een perpetual heeft geen afloopdatum. De funding rate helpt de contractprijs rond de spotprijs te houden. Leverage vergroot zowel mogelijke winst als verlies.",
                        color = MutedText,
                        fontSize = 13.sp,
                        lineHeight = 19.sp
                    )
                }
            }
            Spacer(Modifier.height(18.dp))
            Text(
                "Dubbeltik ergens op deze pagina om terug te draaien naar Markets.",
                color = MutedText,
                fontSize = 12.sp,
                textAlign = TextAlign.Center,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

@Composable
private fun DetailGrid(values: List<Pair<String, String>>) {
    Column(verticalArrangement = Arrangement.spacedBy(10.dp)) {
        values.chunked(2).forEach { rowValues ->
            Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                rowValues.forEach { (label, value) ->
                    Surface(
                        modifier = Modifier.weight(1f),
                        color = PanelColor,
                        shape = RoundedCornerShape(14.dp)
                    ) {
                        Column(modifier = Modifier.padding(14.dp)) {
                            Text(label, color = MutedText, fontSize = 12.sp)
                            Spacer(Modifier.height(5.dp))
                            Text(value, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold)
                        }
                    }
                }
                if (rowValues.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

@Composable
private fun MiniPriceChart(positive: Boolean) {
    val chartColor = if (positive) MarketGreen else MarketRed
    Row(
        modifier = Modifier.fillMaxWidth().height(66.dp),
        horizontalArrangement = Arrangement.spacedBy(4.dp),
        verticalAlignment = Alignment.Bottom
    ) {
        val heights = if (positive) listOf(20, 26, 22, 35, 31, 44, 40, 55, 49, 63) else
            listOf(60, 51, 55, 44, 47, 36, 40, 28, 31, 20)
        heights.forEach { height ->
            Box(
                modifier = Modifier
                    .weight(1f)
                    .height(height.dp)
                    .background(chartColor.copy(alpha = 0.72f), RoundedCornerShape(3.dp))
            )
        }
    }
}

private fun formatSignedPrice(value: Double): String =
    if (value >= 0) "+$${formatPrice(value.toString())}" else "-$${formatPrice((-value).toString())}"

private fun assetBackground(symbol: String): String = when (symbol.uppercase()) {
    "BTC" -> "Bitcoin is het eerste gedecentraliseerde digitale activum en wordt vaak gezien als digitaal schaars bezit. Dit contract volgt de BTC-prijs op Hyperliquid."
    "ETH" -> "Ether is het native activum van Ethereum, het netwerk voor smart contracts en gedecentraliseerde applicaties. Dit contract volgt de ETH-prijs op Hyperliquid."
    "SOL" -> "SOL is het native activum van Solana, een blockchain gericht op snelle en goedkope transacties. Dit contract volgt de SOL-prijs op Hyperliquid."
    "HYPE" -> "HYPE is het native activum van het Hyperliquid-ecosysteem en wordt gebruikt binnen governance en netwerkmechanismen."
    else -> "$symbol is als perpetual contract beschikbaar op Hyperliquid. De getoonde koers, funding, open interest en het 24-uursvolume komen rechtstreeks uit de actuele Hyperliquid-marktdata."
}

private fun formatPrice(value: String): String {
    val number = value.toDoubleOrNull() ?: return value
    val pattern = when {
        number >= 1_000 -> "#,##0.00"
        number >= 1 -> "0.0000"
        else -> "0.########"
    }
    return DecimalFormat(pattern).format(number)
}

private fun formatCompact(value: String): String {
    val number = value.toDoubleOrNull() ?: return "-"
    return when {
        number >= 1_000_000_000 -> DecimalFormat("0.00B").format(number / 1_000_000_000)
        number >= 1_000_000 -> DecimalFormat("0.00M").format(number / 1_000_000)
        number >= 1_000 -> DecimalFormat("0.00K").format(number / 1_000)
        else -> DecimalFormat("0.00").format(number)
    }
}

private fun sortArrow(current: MarketSort, descending: MarketSort, ascending: MarketSort): String = when (current) {
    descending -> " ↓"
    ascending -> " ↑"
    else -> ""
}
