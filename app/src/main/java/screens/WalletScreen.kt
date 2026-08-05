package com.tradementor.app.screens

import androidx.compose.foundation.background
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
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Button
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ButtonDefaults
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedButton
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalClipboardManager
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.reown.appkit.client.AppKit
import com.tradementor.app.cloud.CloudAccountRepository
import com.tradementor.app.repository.WalletOverview
import com.tradementor.app.repository.WalletOverviewCache
import com.tradementor.app.repository.WalletRepository
import com.tradementor.app.security.ApiWalletVault
import com.tradementor.app.security.MetaMaskAgentApproval
import com.tradementor.app.scanner.LocalTradingGatewayStore
import com.tradementor.app.scanner.TradingGatewayClient
import com.tradementor.app.scanner.TradingGatewayHealthCache
import com.tradementor.app.scanner.TradingGatewayHealth
import com.tradementor.app.scanner.AutoTradingStore
import org.web3j.crypto.ECKeyPair
import org.web3j.crypto.Keys
import java.math.BigInteger
import kotlinx.coroutines.delay
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import kotlinx.coroutines.withContext
import java.text.NumberFormat
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

private val WalletBackground = Color(0xFF05070B)
private val WalletCard = Color(0xFF101723)
private val WalletBlue = Color(0xFF2F68FF)
private val WalletGreen = Color(0xFF08C887)
private val WalletMuted = Color(0xFF8C92A3)

@Composable
private fun WalletConnectionFlipCard(
    title: String,
    connected: Boolean,
    summary: String,
    flipped: Boolean,
    onFlip: () -> Unit,
    details: @Composable () -> Unit
) {
    val rotation by animateFloatAsState(if (flipped) 180f else 0f, tween(420), label = "connectionFlip")
    Surface(
        color = if (connected) Color(0xFF0B2C27) else Color(0xFF261F0D),
        shape = RoundedCornerShape(16.dp),
        modifier = Modifier.fillMaxWidth().graphicsLayer {
            rotationY = rotation
            cameraDistance = 14f * density
        }
    ) {
        if (rotation <= 90f) {
            Row(
                Modifier.fillMaxWidth().clickable(onClick = onFlip).padding(horizontal = 14.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically
            ) {
                Text(if (connected) "●" else "○", color = if (connected) WalletGreen else Color(0xFFFFC857), fontSize = 15.sp)
                Column(Modifier.weight(1f).padding(start = 10.dp)) {
                    Text(title, color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold)
                    Text(summary, color = WalletMuted, fontSize = 10.sp, maxLines = 1)
                }
                Text(if (connected) "✓" else "!", color = if (connected) WalletGreen else Color(0xFFFFC857), fontSize = 18.sp, fontWeight = FontWeight.Black)
                Text("  ›", color = WalletMuted, fontSize = 18.sp)
            }
        } else {
            Column(Modifier.fillMaxWidth().graphicsLayer { rotationY = 180f }.padding(15.dp)) {
                Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                    Text(title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f))
                    Text(if (connected) "● VERBONDEN" else "○ ACTIE NODIG", color = if (connected) WalletGreen else Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.Black)
                }
                Spacer(Modifier.height(10.dp))
                details()
                OutlinedButton(onClick = onFlip, modifier = Modifier.fillMaxWidth().padding(top = 12.dp)) { Text("Terug naar overzicht") }
            }
        }
    }
}

@Composable
fun WalletScreen(onOpenWallet: () -> Unit, onOpenSettings: () -> Unit = {}) {
    val context = LocalContext.current
    val clipboard = LocalClipboardManager.current
    val repository = remember { WalletRepository() }
    var address by remember { mutableStateOf(AppKit.getAccount()?.address.orEmpty()) }
    var overview by remember(address) { mutableStateOf(WalletOverviewCache.get(address)) }
    var loading by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var apiWalletConfigured by remember { mutableStateOf(ApiWalletVault.isApproved(context)) }
    var approvalRunning by remember { mutableStateOf(false) }
    var flippedConnection by remember { mutableStateOf<String?>(null) }
    var approvalMessage by remember { mutableStateOf<String?>(null) }
    var manualMode by remember { mutableStateOf(false) }
    var apiKeyInput by remember { mutableStateOf("") }
    var gatewayHealth by remember { mutableStateOf(TradingGatewayHealthCache.get()) }
    var gatewayError by remember { mutableStateOf<String?>(null) }
    var accountWalletMismatch by remember { mutableStateOf<String?>(null) }
    val gatewayClient = remember { TradingGatewayClient() }
    val scope = rememberCoroutineScope()

    LaunchedEffect(Unit) {
        while (true) {
            address = AppKit.getAccount()?.address.orEmpty()
            delay(1_000)
        }
    }
    LaunchedEffect(address) {
        if (address.isBlank()) {
            overview = null
            return@LaunchedEffect
        }
        CloudAccountRepository.linkWallet(address) { result ->
            result.exceptionOrNull()?.message?.let { message ->
                if (message.contains("andere Hyperliquid-wallet", ignoreCase = true)) {
                    accountWalletMismatch = message
                }
            }
        }
        while (true) {
            loading = overview == null
            error = null
            runCatching { repository.load(address) }
                .onSuccess { overview = it; WalletOverviewCache.put(address, it) }
                .onFailure { error = it.message ?: "Accountgegevens konden niet worden geladen." }
            loading = false
            delay(10_000)
        }
    }
    LaunchedEffect(Unit) {
        while (true) {
            runCatching { gatewayClient.health(LocalTradingGatewayStore.url(context)) }
                .onSuccess {
                    gatewayHealth = it
                    TradingGatewayHealthCache.put(it)
                    if (it.agentWalletConfigured) apiWalletConfigured = true
                    gatewayError = null
                    if (it.agentWalletReason == "wallet_mismatch") {
                        accountWalletMismatch = "De cloud-handelswallet hoort bij een andere hoofdwallet."
                    }
                }
                .onFailure {
                    // Keep showing the last confirmed state during a short network hiccup.
                    if (gatewayHealth == null) {
                        gatewayError = "TradeMentor Cloud is tijdelijk niet bereikbaar"
                    }
                }
            delay(10_000)
        }
    }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(WalletBackground).padding(horizontal = 16.dp),
        contentPadding = androidx.compose.foundation.layout.PaddingValues(top = 18.dp, bottom = 28.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Wallet", color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.ExtraBold, textAlign = androidx.compose.ui.text.style.TextAlign.Center, modifier = Modifier.fillMaxWidth())
                    Text("Hyperliquid · wallet en beveiligde handelslaag", color = WalletMuted, fontSize = 12.sp)
                }
                OutlinedButton(onClick = onOpenSettings) { Text("Appinstellingen") }
            }
        }

        if (address.isNotBlank()) {
            if (loading) item { LoadingWalletCard() }
            error?.let { message -> item { ErrorWalletCard(message) } }
            overview?.let { data -> item { BalanceCard(data) } }
        }

        item {
            Text("VERBINDINGEN", color = WalletMuted, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(top = 2.dp))
        }

        if (address.isBlank()) {
            item { ConnectWalletCard(onOpenWallet) }
        } else {
            item {
                WalletConnectionFlipCard(
                    title = "MetaMask-wallet", connected = true,
                    summary = shortAddress(address), flipped = flippedConnection == "wallet",
                    onFlip = { flippedConnection = if (flippedConnection == "wallet") null else "wallet" }
                ) {
                    Text(address, color = Color.White, fontSize = 12.sp)
                    Text("Dit openbare handelsadres is aan jouw persoonlijke cloudaccount gekoppeld.", color = WalletMuted, fontSize = 11.sp, modifier = Modifier.padding(top = 5.dp))
                    Spacer(Modifier.height(10.dp))
                    Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        Button(onClick = { clipboard.setText(AnnotatedString(address)) }, colors = ButtonDefaults.buttonColors(containerColor = WalletBlue)) { Text("Adres kopiëren") }
                        OutlinedButton(onClick = onOpenWallet) { Text("Wallet beheren") }
                    }
                }
            }
            item {
                WalletConnectionFlipCard(
                    title = "API-wallet", connected = apiWalletConfigured,
                    summary = if (apiWalletConfigured) ApiWalletVault.address(context).takeIf { value -> value.isNotBlank() }?.let(::shortAddress) ?: "Veilig in persoonlijke cloud" else "Koppeling vereist",
                    flipped = flippedConnection == "api",
                    onFlip = { flippedConnection = if (flippedConnection == "api") null else "api" }
                ) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Text("AUTOMATISCH HANDELEN · VERSIE 1.65", color = if (apiWalletConfigured) WalletGreen else Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                        Text(if (apiWalletConfigured) "API-wallet veilig opgeslagen" else "API-wallet vereist voor echte orders", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp))
                        Text(if (apiWalletConfigured) ApiWalletVault.address(context).takeIf { value -> value.isNotBlank() }?.let(::shortAddress) ?: "Veilig gekoppeld aan jouw persoonlijke cloudaccount" else "Maak en autoriseer eerst een aparte API-wallet via de officiële Hyperliquid API-pagina.", color = WalletMuted, fontSize = 11.sp, modifier = Modifier.padding(top = 4.dp))
                        Text(if (gatewayHealth?.agentWalletConfigured == true) "Op een tweede toestel hoef je geen secret key opnieuw in te voeren." else "De sleutel wordt versleuteld met Android Keystore en nooit getoond of gelogd.", color = WalletMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 7.dp))
                        Spacer(Modifier.height(11.dp))
                        Button(
                            onClick = {
                                approvalRunning = true
                                approvalMessage = "MetaMask openen voor Mainnet-machtigingâ€¦"
                                MetaMaskAgentApproval.start(context) { result ->
                                    approvalRunning = false
                                    result.onSuccess {
                                        apiWalletConfigured = true
                                        approvalMessage = "Mainnet-handelswallet is goedgekeurd en veilig in de cloud opgeslagen."
                                    }.onFailure {
                                        apiWalletConfigured = false
                                        approvalMessage = it.message ?: "Mainnet-machtiging is niet voltooid."
                                    }
                                }
                            },
                            enabled = !approvalRunning && address.isNotBlank() && gatewayHealth?.agentWalletConfigured != true,
                            colors = ButtonDefaults.buttonColors(containerColor = WalletGreen),
                            modifier = Modifier.fillMaxWidth()
                        ) {
                            if (approvalRunning) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp)
                            else Text(if (gatewayHealth?.agentWalletConfigured == true) "Cloudkoppeling actief" else if (apiWalletConfigured) "Mainnet-koppeling vernieuwen" else "Veilig met MetaMask koppelen")
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Button(onClick = { manualMode = !manualMode }, enabled = gatewayHealth?.agentWalletConfigured != true, colors = ButtonDefaults.buttonColors(containerColor = WalletBlue)) {
                                Text(if (manualMode) "Annuleren" else "Handmatig koppelen")
                            }
                            if (apiWalletConfigured && gatewayHealth?.agentWalletConfigured != true) OutlinedButton(onClick = { ApiWalletVault.clear(context); apiWalletConfigured = false }) { Text("Verwijderen") }
                        }
                        if (manualMode) {
                            Spacer(Modifier.height(12.dp))
                            OutlinedTextField(value = apiKeyInput, onValueChange = { apiKeyInput = it.trim() }, label = { Text("Private API-sleutel") }, singleLine = true, visualTransformation = PasswordVisualTransformation(), modifier = Modifier.fillMaxWidth())
                            Text("Het API-walletadres wordt veilig uit de sleutel berekend.", color = WalletMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 6.dp))
                            Spacer(Modifier.height(10.dp))
                            Button(onClick = {
                                approvalRunning = true
                                approvalMessage = "API-wallet op Mainnet en in jouw persoonlijke cloud controlerenâ€¦"
                                scope.launch {
                                    runCatching {
                                        val cleanKey = apiKeyInput.removePrefix("0x")
                                        require(cleanKey.length == 64) { "De private API-sleutel heeft niet de juiste lengte." }
                                        val derivedAddress = "0x${Keys.getAddress(ECKeyPair.create(BigInteger(cleanKey, 16)))}"
                                        withContext(Dispatchers.IO) {
                                            CloudAccountRepository.provisionAgentBlocking(cleanKey, derivedAddress)
                                        }
                                        ApiWalletVault.save(context, derivedAddress, cleanKey)
                                        ApiWalletVault.setApproved(context, true)
                                    }.onSuccess {
                                        apiWalletConfigured = true; manualMode = false; apiKeyInput = ""
                                        accountWalletMismatch = null
                                        approvalMessage = "Mainnet-API-wallet gecontroleerd en veilig in jouw persoonlijke cloud opgeslagen."
                                    }.onFailure {
                                        ApiWalletVault.setApproved(context, false)
                                        apiWalletConfigured = false
                                        approvalMessage = it.message ?: "Controleer of deze API-wallet op Hyperliquid Mainnet is geautoriseerd."
                                    }
                                    approvalRunning = false
                                }
                            }, enabled = !approvalRunning && apiKeyInput.isNotBlank(), modifier = Modifier.fillMaxWidth(), colors = ButtonDefaults.buttonColors(containerColor = WalletGreen)) {
                                if (approvalRunning) CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp)
                                else Text("Veilig opslaan in cloud")
                            }
                        }
                        approvalMessage?.let { Text(it, color = if (apiWalletConfigured) WalletGreen else Color(0xFFFFC857), fontSize = 10.sp, modifier = Modifier.padding(top = 8.dp)) }
                    }
                }
            }
            item {
                val connected = gatewayHealth?.status == "ready"
                WalletConnectionFlipCard(
                    title = "TradeMentor Cloud", connected = connected,
                    summary = if (connected) "Veilig verbonden" else "Verbinding controleren",
                    flipped = flippedConnection == "cloud",
                    onFlip = { flippedConnection = if (flippedConnection == "cloud") null else "cloud" }
                ) {
                    Column(Modifier.fillMaxWidth().padding(16.dp)) {
                        Text("TRADEMENTOR CLOUD", color = if (connected) WalletGreen else Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                        Text(if (connected) "Veilig verbonden" else "Verbinding controleren", color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp))
                        Text(LocalTradingGatewayStore.url(context), color = WalletMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 4.dp))
                        gatewayHealth?.let { status ->
                            Text("${status.activePositions} echte posities · ${status.remainingSlots} vrije plaatsen · orders ${if (status.tradingEnabled) "actief" else "vergrendeld"}", color = WalletMuted, fontSize = 11.sp, modifier = Modifier.padding(top = 7.dp))
                        }
                        gatewayError?.let { Text(it, color = Color(0xFFFF8A9D), fontSize = 10.sp, modifier = Modifier.padding(top = 7.dp)) }
                        Text("Iedere aanvraag gebruikt jouw Firebase-sessie; een lokaal IP-adres of servercode is niet meer nodig.", color = WalletMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 8.dp))
                    }
                }
            }
            overview?.let { data ->
                if (data.spotBalances.isNotEmpty()) {
                    item { SectionCounter("Unified balances", data.spotBalances.size) }
                    items(data.spotBalances, key = { "${it.token}-${it.coin}" }) { balance ->
                        Surface(color = WalletCard, shape = RoundedCornerShape(15.dp)) {
                            Row(Modifier.fillMaxWidth().padding(13.dp), verticalAlignment = Alignment.CenterVertically) {
                                Text(balance.coin, color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                                Column(horizontalAlignment = Alignment.End) {
                                    Text(price(balance.total), color = Color.White, fontWeight = FontWeight.Bold)
                                    if ((balance.hold.toDoubleOrNull() ?: 0.0) > 0.0) Text("Vast: ${price(balance.hold)}", color = WalletMuted, fontSize = 10.sp)
                                }
                            }
                        }
                    }
                }
                item {
                    Text("Open posities · ${data.account.assetPositions.size}", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                }
                if (data.account.assetPositions.isEmpty()) {
                    item { EmptyWalletCard("Geen open Hyperliquid-posities") }
                } else {
                    items(data.account.assetPositions, key = { it.position.coin }) { asset ->
                        val position = asset.position
                        val short = (position.signedSize.toDoubleOrNull() ?: 0.0) < 0
                        Surface(color = WalletCard, shape = RoundedCornerShape(17.dp)) {
                            Column(Modifier.padding(14.dp)) {
                                Row(Modifier.fillMaxWidth()) {
                                    Text(position.coin, color = Color.White, fontSize = 18.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                                    Text(if (short) "SHORT" else "LONG", color = if (short) Color(0xFFFF496A) else WalletGreen, fontWeight = FontWeight.Bold)
                                }
                                Spacer(Modifier.height(8.dp))
                                WalletValueRow("Positiewaarde", usd(position.positionValue))
                                WalletValueRow("Instapprijs", price(position.entryPrice))
                                WalletValueRow("Ongerealiseerd resultaat", signedUsd(position.unrealizedPnl), valueColor = pnlColor(position.unrealizedPnl))
                                WalletValueRow("Rendement", percentRatio(position.returnOnEquity), valueColor = pnlColor(position.returnOnEquity))
                                WalletValueRow("Liquidatieprijs", price(position.liquidationPrice))
                                WalletValueRow("Hefboom", "${position.leverage.value}× · ${position.leverage.type}")
                            }
                        }
                    }
                }
                item { SectionCounter("Openstaande orders", data.openOrders.size) }
                if (data.openOrders.isEmpty()) item { EmptyWalletCard("Geen openstaande orders") }
                else items(data.openOrders.take(10), key = { it.orderId }) { order ->
                    Surface(color = WalletCard, shape = RoundedCornerShape(15.dp)) {
                        Row(Modifier.fillMaxWidth().padding(13.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("${order.coin} · ${if (order.side == "B") "KOPEN" else "VERKOPEN"}", color = Color.White, fontWeight = FontWeight.Bold)
                                Text("${order.size} @ ${price(order.limitPrice)}", color = WalletMuted, fontSize = 12.sp)
                            }
                            Text(time(order.timestamp), color = WalletMuted, fontSize = 11.sp)
                        }
                    }
                }
                item { SectionCounter("Recente transacties", data.recentFills.size) }
                if (data.recentFills.isEmpty()) item { EmptyWalletCard("Nog geen recente transacties gevonden") }
                else items(data.recentFills, key = { "${it.tradeId}-${it.time}" }) { fill ->
                    Surface(color = WalletCard, shape = RoundedCornerShape(15.dp)) {
                        Row(Modifier.fillMaxWidth().padding(13.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text("${fill.coin} · ${if (fill.side == "B") "KOOP" else "VERKOOP"}", color = Color.White, fontWeight = FontWeight.Bold)
                                Text("${fill.size} @ ${price(fill.price)}", color = WalletMuted, fontSize = 12.sp)
                            }
                            Column(horizontalAlignment = Alignment.End) {
                                Text(signedUsd(fill.closedPnl), color = pnlColor(fill.closedPnl), fontWeight = FontWeight.Bold)
                                Text(time(fill.time), color = WalletMuted, fontSize = 10.sp)
                            }
                        }
                    }
                }
            }
        }
    }

    accountWalletMismatch?.let {
        AlertDialog(
            onDismissRequest = { accountWalletMismatch = null },
            title = { Text("Andere wallet of gebruiker gevonden") },
            text = {
                Text(
                    "Deze telefoon bevat een wallet die niet bij het ingelogde TradeMentor-account hoort. " +
                        "Om vermenging te voorkomen worden alleen de lokale sessie en toestelgebonden " +
                        "handelskoppeling opnieuw ingesteld. Je echte wallet, saldo, posities, " +
                        "cloudhistorie en leerresultaten worden niet verwijderd. Daarna kun je opnieuw aanmelden."
                )
            },
            confirmButton = {
                Button(onClick = {
                    AutoTradingStore.setEnabled(context, false)
                    ApiWalletVault.clear(context)
                    CloudAccountRepository.signOut()
                    accountWalletMismatch = null
                }) { Text("Opnieuw instellen en aanmelden") }
            },
            dismissButton = {
                TextButton(onClick = { accountWalletMismatch = null }) { Text("Annuleren") }
            }
        )
    }
}

@Composable private fun ConnectWalletCard(onOpenWallet: () -> Unit) {
    Surface(color = WalletCard, shape = RoundedCornerShape(24.dp)) {
        Column(Modifier.fillMaxWidth().padding(22.dp), horizontalAlignment = Alignment.CenterHorizontally) {
            Box(Modifier.width(62.dp).height(62.dp).background(Color(0xFF162B55), RoundedCornerShape(20.dp)), contentAlignment = Alignment.Center) {
                Text("W", color = Color.White, fontSize = 25.sp, fontWeight = FontWeight.ExtraBold)
            }
            Spacer(Modifier.height(15.dp))
            Text("Koppel je Hyperliquid-wallet", color = Color.White, fontSize = 21.sp, fontWeight = FontWeight.Bold)
            Text("MetaMask blijft de baas. Wij lezen alleen je openbare accountgegevens.", color = WalletMuted, fontSize = 13.sp, modifier = Modifier.padding(top = 7.dp))
            Spacer(Modifier.height(18.dp))
            Button(onClick = onOpenWallet, colors = ButtonDefaults.buttonColors(containerColor = WalletBlue), modifier = Modifier.fillMaxWidth().height(52.dp)) {
                Text("Wallet koppelen", fontWeight = FontWeight.Bold)
            }
            Text("Handelen gebruikt een afzonderlijk beveiligde API-wallet", color = WalletGreen, fontSize = 11.sp, modifier = Modifier.padding(top = 10.dp))
        }
    }
}

@Composable private fun BalanceCard(data: WalletOverview) {
    val summary = data.account.marginSummary
    val unrealizedPnl = data.account.assetPositions.sumOf { it.position.unrealizedPnl.toDoubleOrNull() ?: 0.0 }
    val modeLabel = when (data.accountMode) {
        "unifiedAccount" -> "UNIFIED ACCOUNT"
        "portfolioMargin" -> "PORTFOLIO MARGIN"
        else -> "CLASSIC ACCOUNT"
    }
    Surface(color = Color(0xFF0D2140), shape = RoundedCornerShape(22.dp)) {
        Column(Modifier.padding(18.dp)) {
            Text(modeLabel, color = WalletGreen, fontSize = 10.sp, fontWeight = FontWeight.Bold)
            Text("PORTFOLIO VALUE", color = Color(0xFF8EB2FF), fontSize = 11.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 4.dp))
            Text(usd(data.portfolioValue.toString()), color = Color.White, fontSize = 32.sp, fontWeight = FontWeight.ExtraBold)
            Surface(
                color = Color(0xFF0B332B),
                shape = RoundedCornerShape(16.dp),
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
            ) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("AVAILABLE TO TRADE", color = WalletGreen, fontSize = 10.sp, fontWeight = FontWeight.ExtraBold)
                        Text("Beschikbaar om nieuwe trades te openen", color = WalletMuted, fontSize = 9.sp)
                    }
                    Text("${amount2(data.availableToTrade)} USDC", color = WalletGreen, fontSize = 20.sp, fontWeight = FontWeight.ExtraBold)
                }
            }
            Spacer(Modifier.height(14.dp))
            Row(Modifier.fillMaxWidth()) {
                WalletMetric("Ongerealiseerde PNL", signedUsd(unrealizedPnl.toString()), Modifier.weight(1f))
                WalletMetric("Maintenance margin", usd(data.account.crossMaintenanceMarginUsed), Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
            Row(Modifier.fillMaxWidth()) {
                WalletMetric("Marge gebruikt", usd(summary.totalMarginUsed), Modifier.weight(1f))
                WalletMetric("Positiewaarde", usd(summary.totalNotionalPosition), Modifier.weight(1f))
            }
            if (data.accountMode == "unifiedAccount" || data.accountMode == "portfolioMargin") {
                Text("Vrij beschikbaar is je opneembare USDC/USDT-collateral (totaal min vastgehouden saldo).", color = WalletMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 10.dp))
            }
        }
    }
}

@Composable private fun WalletMetric(label: String, value: String, modifier: Modifier) {
    Column(modifier) { Text(label, color = WalletMuted, fontSize = 11.sp); Text(value, color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.Bold) }
}

@Composable private fun WalletValueRow(label: String, value: String, valueColor: Color = Color.White) {
    Row(Modifier.fillMaxWidth().padding(vertical = 3.dp)) {
        Text(label, color = WalletMuted, fontSize = 12.sp, modifier = Modifier.weight(1f))
        Text(value, color = valueColor, fontSize = 12.sp, fontWeight = FontWeight.SemiBold)
    }
}

@Composable private fun SectionCounter(title: String, count: Int) {
    Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
        Text(title, color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
        Surface(color = Color(0xFF162135), shape = RoundedCornerShape(16.dp)) { Text(count.toString(), color = WalletBlue, fontWeight = FontWeight.Bold, modifier = Modifier.padding(horizontal = 11.dp, vertical = 5.dp)) }
    }
}

@Composable private fun LoadingWalletCard() = Surface(color = WalletCard, shape = RoundedCornerShape(18.dp)) {
    Row(Modifier.fillMaxWidth().padding(18.dp), verticalAlignment = Alignment.CenterVertically) {
        CircularProgressIndicator(color = WalletBlue, modifier = Modifier.width(22.dp).height(22.dp), strokeWidth = 2.dp)
        Spacer(Modifier.width(12.dp)); Text("Hyperliquid-account wordt geladen…", color = Color.White)
    }
}

@Composable private fun ErrorWalletCard(message: String) = Surface(color = Color(0xFF35151D), shape = RoundedCornerShape(18.dp)) {
    Text(message, color = Color(0xFFFF8A9D), modifier = Modifier.padding(16.dp))
}

@Composable private fun EmptyWalletCard(message: String) = Surface(color = WalletCard, shape = RoundedCornerShape(16.dp)) {
    Text(message, color = WalletMuted, modifier = Modifier.fillMaxWidth().padding(16.dp))
}

private fun shortAddress(address: String) = if (address.length > 12) "${address.take(7)}…${address.takeLast(5)}" else address
private fun value(number: String?): Double = number?.toDoubleOrNull() ?: 0.0
private fun usd(number: String?) = NumberFormat.getCurrencyInstance(Locale.US).format(value(number))
private fun signedUsd(number: String?): String = (if (value(number) >= 0) "+" else "") + usd(number)
private fun price(number: String?): String = number?.toDoubleOrNull()?.let { NumberFormat.getNumberInstance(Locale.US).apply { maximumFractionDigits = 8 }.format(it) } ?: "—"
private fun amount2(number: Double): String = NumberFormat.getNumberInstance(Locale.US).apply {
    minimumFractionDigits = 2
    maximumFractionDigits = 2
}.format(number)
private fun percentRatio(number: String?): String = String.format(Locale.US, "%+.2f%%", value(number) * 100.0)
private fun pnlColor(number: String?) = if (value(number) >= 0) WalletGreen else Color(0xFFFF496A)
private fun time(timestamp: Long) = SimpleDateFormat("dd MMM HH:mm", Locale("nl", "NL")).format(Date(timestamp))
