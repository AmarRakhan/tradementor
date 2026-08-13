package com.tradementor.app.screens

import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.*
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.*
import androidx.compose.runtime.*
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.shadow
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.scanner.*
import com.tradementor.app.R
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.Instant
import java.util.Locale
import kotlin.math.abs

private data class ArenaDuration(val label: String, val seconds: Int)
private val arenaDurations = listOf(ArenaDuration("1m",60), ArenaDuration("5m",300), ArenaDuration("15m",900), ArenaDuration("1h",3600), ArenaDuration("4h",14400), ArenaDuration("1d",86400))
private val cockpitBg = Color(0xFF030711)
private val cyan = Color(0xFF21D8FF)
private val gold = Color(0xFFFFC34A)
private val longGreen = Color(0xFF18D796)
private val shortRed = Color(0xFFFF496D)

@Composable
fun BitcoinCasinoScreen() {
    val client = remember { BitcoinCasinoClient() }
    val baseUrl = LocalTradingGatewayStore.url(androidx.compose.ui.platform.LocalContext.current)
    val scope = rememberCoroutineScope()
    var duration by remember { mutableStateOf(arenaDurations[1]) }
    var state by remember { mutableStateOf(BitcoinCasinoState()) }
    var signal by remember { mutableStateOf<BitcoinSignal?>(null) }
    var stake by remember { mutableStateOf("25") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var confirmation by remember { mutableStateOf<Boolean?>(null) }
    var sound by remember { mutableStateOf(true) }
    var now by remember { mutableLongStateOf(System.currentTimeMillis()) }

    suspend fun refresh(includeSignal: Boolean = false) {
        runCatching {
            if (includeSignal) signal = client.signal(baseUrl, duration.seconds)
            state = client.state(baseUrl, duration.seconds)
        }.onFailure { error = it.message }
    }
    LaunchedEffect(duration) { refresh(true) }
    LaunchedEffect(duration.seconds) {
        while (true) {
            delay(duration.seconds * 1_000L)
            runCatching { signal = client.signal(baseUrl, duration.seconds) }.onFailure { error = it.message }
        }
    }
    LaunchedEffect(Unit) { while (true) { now = System.currentTimeMillis(); refresh(false); delay(2_000) } }

    Box(Modifier.fillMaxSize().background(cockpitBg)) {
        CockpitSpace()
        LazyColumn(Modifier.fillMaxSize(), contentPadding = PaddingValues(bottom = 28.dp)) {
            item {
                Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text("BITCOIN TRADE CASINO", color = Color.White, fontSize = 20.sp, fontWeight = FontWeight.Bold)
                        Text("2028 COCKPIT · BTC/USDC", color = cyan, fontSize = 11.sp)
                    }
                    Text(if (sound) "🔊" else "🔇", fontSize = 20.sp, modifier = Modifier.clickable { sound = !sound }.padding(8.dp))
                }
                DurationRail(duration) { duration = it }
                Spacer(Modifier.height(165.dp))
                AiConsole(signal)
                state.activeTrade?.let { LiveCockpit(it, state.currentPrice, now) } ?: EntryCockpit(
                    stake = stake, onStake = { stake = it.filter { c -> c.isDigit() || c == '.' } },
                    onLong = { confirmation = false }, onShort = { confirmation = true }, busy = busy
                    , averageWinningPercentage = state.averageWinningPercentage
                )
                error?.let { Text(it, color = shortRed, modifier = Modifier.padding(horizontal = 18.dp, vertical = 8.dp), fontSize = 12.sp) }
                state.activeTrade?.let { trade ->
                    OutlinedButton(onClick = {
                        scope.launch { busy = true; runCatching { client.close(baseUrl, trade.id) }.onSuccess { refresh() }.onFailure { error = it.message }; busy = false }
                    }, modifier = Modifier.fillMaxWidth().padding(horizontal = 18.dp), enabled = !busy) { Text("POSITIE NU HANDMATIG SLUITEN") }
                }
                PerformanceDeck(state, duration)
            }
            items(state.predictions.take(1000)) { PredictionRow(it) }
            item { Text("Historische prestaties zijn informatie en geen winstgarantie.", color = Color(0xFF8B96AA), fontSize = 11.sp, modifier = Modifier.padding(18.dp), textAlign = TextAlign.Center) }
        }
    }
    confirmation?.let { short ->
        val amount = stake.toDoubleOrNull() ?: 0.0
        AlertDialog(onDismissRequest = { confirmation = null }, title = { Text("Echte BTC-positie bevestigen") },
            text = { Text("${if (short) "Short" else "Long"} · ${duration.label} · ${money(amount)} USDC\n\nDe order opent direct tegen marktprijs en de server sluit hem automatisch na ${duration.label}. Geschatte instapkosten worden na uitvoering getoond.") },
            confirmButton = { Button(onClick = { confirmation = null; scope.launch { busy = true; error = null; runCatching { client.open(baseUrl, duration.seconds, amount, short) }.onSuccess { refresh() }.onFailure { error = it.message }; busy = false } }) { Text("BEVESTIG EN OPEN") } },
            dismissButton = { TextButton(onClick = { confirmation = null }) { Text("Annuleren") } })
    }
}

@Composable private fun CockpitSpace() = Box(Modifier.fillMaxSize()) {
    Image(
        painter = painterResource(R.drawable.bitcoin_cockpit_2028),
        contentDescription = null,
        modifier = Modifier.fillMaxSize(),
        contentScale = ContentScale.Crop
    )
    Box(Modifier.fillMaxSize().background(Brush.verticalGradient(listOf(Color.Transparent, Color.Transparent, cockpitBg.copy(.35f), cockpitBg), startY = 0f)))
}

@Composable private fun DurationRail(selected: ArenaDuration, onSelect: (ArenaDuration)->Unit) = Row(Modifier.fillMaxWidth().padding(horizontal=14.dp).shadow(10.dp,RoundedCornerShape(13.dp)).background(Color(0xDD070B12),RoundedCornerShape(13.dp)).border(1.dp,Color(0xFF58677D),RoundedCornerShape(13.dp)).padding(5.dp), horizontalArrangement = Arrangement.spacedBy(5.dp)) {
    arenaDurations.forEach { d -> Box(Modifier.weight(1f).shadow(if(d==selected)8.dp else 1.dp,RoundedCornerShape(8.dp)).background(if(d==selected)Brush.verticalGradient(listOf(Color(0xFFFFE096),gold,Color(0xFF9B5D00))) else Brush.verticalGradient(listOf(Color(0xFF303B4C),Color(0xFF111722))),RoundedCornerShape(8.dp)).border(1.dp,if(d==selected)Color(0xFFFFF0BD) else Color(0xFF4B596D),RoundedCornerShape(8.dp)).clickable { onSelect(d) }.padding(vertical=9.dp),contentAlignment=Alignment.Center) { Text(d.label, color=if(d==selected) Color.Black else Color.White, textAlign=TextAlign.Center, fontSize=11.sp, fontWeight=FontWeight.Bold) } }
}

@Composable private fun AiConsole(signal: BitcoinSignal?) {
    val isLong = signal?.direction == "long"; val color = if(isLong) longGreen else shortRed
    Column(Modifier.fillMaxWidth().padding(horizontal=42.dp, vertical=10.dp).background(Brush.linearGradient(listOf(Color(0xB8111A2B),Color(0xD9060A12))), RoundedCornerShape(22.dp)).border(1.dp,color.copy(.75f),RoundedCornerShape(22.dp)).padding(13.dp), horizontalAlignment=Alignment.CenterHorizontally) {
        Text("AI NAVIGATIEKERN", color=cyan, fontSize=11.sp)
        Text(signal?.direction?.uppercase() ?: "ANALYSEREN…", color=color, fontSize=34.sp, fontWeight=FontWeight.Bold)
        Text("${signal?.confidence?.let { String.format(Locale.US,"%.1f%% zekerheid",it) } ?: "Live data wordt samengevoegd"}", color=Color.White)
        Text(signal?.reason ?: "Techniek · marktstructuur · volatiliteit · sentiment · backtests", color=Color(0xFFAAB6C9), fontSize=11.sp, textAlign=TextAlign.Center)
    }
}

@Composable private fun EntryCockpit(stake:String,onStake:(String)->Unit,onLong:()->Unit,onShort:()->Unit,busy:Boolean,averageWinningPercentage:Double) {
    Column(Modifier.fillMaxWidth().padding(horizontal=18.dp), horizontalAlignment=Alignment.CenterHorizontally) {
        Text("INZET",color=gold,fontSize=11.sp)
        OutlinedTextField(stake,onStake,suffix={Text("USDC")},keyboardOptions=KeyboardOptions(keyboardType=KeyboardType.Decimal),singleLine=true,textStyle=LocalTextStyle.current.copy(textAlign=TextAlign.Center,fontSize=25.sp,color=Color.White),modifier=Modifier.width(210.dp))
        Row(Modifier.fillMaxWidth().padding(top=14.dp),horizontalArrangement=Arrangement.spacedBy(16.dp)) { PhysicalTradeControl("LONG ↗",longGreen,onLong,!busy,Modifier.weight(1f)); PhysicalTradeControl("SHORT ↘",shortRed,onShort,!busy,Modifier.weight(1f)) }
        val amount=stake.toDoubleOrNull() ?: 0.0; val netScenario=(amount*(averageWinningPercentage-.09)/100.0).coerceAtLeast(0.0)
        Text("Historisch winstscenario: +${money(netScenario)} USDC · gemiddelde winnende beweging ${money(averageWinningPercentage)}% · na 0,09% geschatte retourkosten",color=gold,fontSize=10.sp,textAlign=TextAlign.Center,modifier=Modifier.padding(top=10.dp))
        Text("Minimaal 10 · maximaal 500 USDC · één BTC-positie tegelijk",color=Color(0xFF8E9AAF),fontSize=10.sp,modifier=Modifier.padding(8.dp))
    }
}

@Composable private fun PhysicalTradeControl(label:String,color:Color,onClick:()->Unit,enabled:Boolean,modifier:Modifier=Modifier) {
    val shape=RoundedCornerShape(18.dp)
    Box(modifier.height(78.dp).shadow(15.dp,shape).background(Brush.verticalGradient(listOf(color.copy(.95f),color.copy(.72f),Color(0xFF080C12))),shape).border(2.dp,Brush.verticalGradient(listOf(Color.White.copy(.7f),color,Color.Black)),shape).clickable(enabled=enabled,onClick=onClick).padding(5.dp),contentAlignment=Alignment.Center) {
        Box(Modifier.fillMaxSize().border(1.dp,Color.White.copy(.24f),RoundedCornerShape(13.dp)),contentAlignment=Alignment.Center){Text(label,color=Color.White,fontSize=20.sp,fontWeight=FontWeight.Bold,style=LocalTextStyle.current.copy(shadow=androidx.compose.ui.graphics.Shadow(Color.Black,Offset(0f,3f),5f)))}
    }
}

@Composable private fun LiveCockpit(trade:BitcoinTrade, price:Double, now:Long) {
    val end=runCatching{Instant.parse(trade.scheduledCloseAt).toEpochMilli()}.getOrDefault(now); val left=((end-now)/1000).coerceAtLeast(0)
    val move=if(trade.entryPrice>0) (price/trade.entryPrice-1)*100 else 0.0; val pct=if(trade.short)-move else move; val pnl=trade.stakeUsd*pct/100; val value=trade.stakeUsd+pnl; val color=if(pnl>=0)longGreen else shortRed
    Column(Modifier.fillMaxWidth().padding(18.dp).background(Color(0xDD0B1220),RoundedCornerShape(28.dp)).border(2.dp,color.copy(.7f),RoundedCornerShape(28.dp)).padding(18.dp),horizontalAlignment=Alignment.CenterHorizontally) {
        Text("LIVE ${if(trade.short)"SHORT" else "LONG"}",color=color,fontWeight=FontWeight.Bold)
        Text("%02d:%02d:%02d".format(left/3600,(left%3600)/60,left%60),color=Color.White,fontSize=38.sp,fontWeight=FontWeight.Bold)
        Text("Waarde ${money(value)} USDC",color=Color.White,fontSize=19.sp)
        Text("${if(pnl>=0)"+" else ""}${money(pnl)} · ${if(pct>=0)"+" else ""}${money(pct)}%",color=color,fontSize=22.sp,fontWeight=FontWeight.Bold)
        Row(Modifier.fillMaxWidth().padding(top=12.dp),horizontalArrangement=Arrangement.SpaceBetween){Tiny("INZET",money(trade.stakeUsd));Tiny("INSTAP",money(trade.entryPrice));Tiny("BTC NU",money(price));Tiny("KOSTEN*",money(trade.estimatedEntryFeeUsd))}
    }
}

@Composable private fun Tiny(label:String,value:String)=Column(horizontalAlignment=Alignment.CenterHorizontally){Text(label,color=Color(0xFF8794A9),fontSize=9.sp);Text(value,color=Color.White,fontSize=11.sp)}

@Composable private fun PerformanceDeck(state:BitcoinCasinoState,duration:ArenaDuration) {
    val total=state.wonPredictions+state.lostPredictions; val winPart=if(total>0)state.wonPredictions.toFloat()/total else 0f; val animated by animateFloatAsState(winPart,label="wins")
    Column(Modifier.fillMaxWidth().padding(18.dp).background(Color(0xCC0C1320),RoundedCornerShape(22.dp)).padding(16.dp)) {
        Text("LAATSTE ${total.coerceAtMost(1000)} VOORSPELLINGEN · ${duration.label}",color=Color.White,fontWeight=FontWeight.Bold)
        Row(Modifier.fillMaxWidth().padding(vertical=10.dp),horizontalArrangement=Arrangement.SpaceBetween){Text("${state.wonPredictions} GEWONNEN",color=longGreen,fontSize=18.sp);Text("${state.lostPredictions} VERLOREN",color=shortRed,fontSize=18.sp)}
        Row(Modifier.fillMaxWidth().height(13.dp).clip(RoundedCornerShape(8.dp))){Box(Modifier.weight(animated.coerceAtLeast(.001f)).fillMaxHeight().background(longGreen));Box(Modifier.weight((1-animated).coerceAtLeast(.001f)).fillMaxHeight().background(shortRed))}
        Text("Succespercentage ${money(state.successPercentage)}% · resultaten per tijdvak gescheiden",color=Color(0xFFAAB6C9),fontSize=11.sp,modifier=Modifier.padding(top=8.dp))
    }
}

@Composable private fun PredictionRow(p:BitcoinPrediction) {
    val won=p.outcome=="win"; Row(Modifier.fillMaxWidth().padding(horizontal=18.dp,vertical=4.dp).background(Color(0xAA101827),RoundedCornerShape(13.dp)).padding(11.dp),verticalAlignment=Alignment.CenterVertically){
        Text(p.direction.uppercase(),color=if(p.direction=="long")longGreen else shortRed,fontWeight=FontWeight.Bold,modifier=Modifier.width(62.dp)); Column(Modifier.weight(1f)){Text("${money(p.predictionPrice)} → ${money(p.expiryPrice)}",color=Color.White,fontSize=12.sp);Text("${java.text.SimpleDateFormat("dd-MM HH:mm",Locale.getDefault()).format(java.util.Date(p.predictedAtEpochMs))} · ${if(p.resultPercentage>=0)"+" else ""}${money(p.resultPercentage)}%",color=Color(0xFF8995A8),fontSize=10.sp)}; Text(if(won)"WIN" else "LOSS",color=if(won)longGreen else shortRed,fontWeight=FontWeight.Bold)
    }
}

private fun money(value:Double)=String.format(Locale.US,"%,.2f",value)
