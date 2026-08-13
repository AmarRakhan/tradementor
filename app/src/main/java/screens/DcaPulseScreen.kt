package com.tradementor.app.screens

import androidx.activity.compose.BackHandler
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ColumnScope
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorTextButton
import com.tradementor.app.scanner.ActiveHyperliquidPositionStore
import com.tradementor.app.scanner.AutoTradingStore
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.StrategyProfileStore
import com.tradementor.app.scanner.DcaBotSettings
import com.tradementor.app.scanner.DcaBotSettingsInput
import com.tradementor.app.scanner.DcaBotSettingsStore
import com.tradementor.app.scanner.TradingCycleStore
import kotlinx.coroutines.delay
import java.util.Locale

private val DcaBg = Color(0xFF05070B)
private val DcaCard = Color(0xFF101A2A)
private val DcaGreen = Color(0xFF08C887)
private val DcaBlue = Color(0xFF6EA8FF)
private val DcaMuted = Color(0xFF8C92A3)
private enum class DcaTimeUnit(val label: String) { Minutes("MINUTEN"), Hours("UREN") }

@Composable
fun DcaPulseScreen(enabled: Boolean, onBack: () -> Unit, onEnabled: (Boolean) -> Unit) {
    val context = LocalContext.current
    var stored by remember { mutableStateOf(DcaBotSettingsStore.load(context)) }
    var revealed by remember { mutableStateOf(false) }
    val rotation by animateFloatAsState(if (revealed) 0f else 88f, tween(420), label = "dcaCardFlip")
    var baseOrder by remember { mutableStateOf(number(stored.baseOrderUsd)) }
    var maxSafetyOrders by remember { mutableStateOf(stored.maxSafetyOrders.toString()) }
    var deviation by remember { mutableStateOf(number(stored.priceDeviationPercentage)) }
    var shortDeviation by remember { mutableStateOf(number(stored.shortPriceDeviationPercentage)) }
    var maxActiveDeals by remember { mutableStateOf(stored.maxActiveDeals.toString()) }
    var cooldownUnit by remember { mutableStateOf(if (stored.cooldownMinutes >= 60 && stored.cooldownMinutes % 60 == 0) DcaTimeUnit.Hours else DcaTimeUnit.Minutes) }
    var cooldown by remember { mutableStateOf(if (cooldownUnit == DcaTimeUnit.Hours) (stored.cooldownMinutes / 60).toString() else stored.cooldownMinutes.toString()) }
    var portfolioTarget by remember { mutableStateOf(number(stored.portfolioTargetPercentage)) }
    var stopLossEnabled by remember { mutableStateOf(stored.stopLossEnabled) }
    var topUniverseSize by remember { mutableStateOf(stored.topUniverseSize.toString()) }
    var entryMode by remember { mutableStateOf(stored.entryMode) }
    var savedMessage by remember { mutableStateOf<String?>(null) }

    fun draft() = DcaBotSettingsInput(
        baseOrderUsd = baseOrder,
        maxSafetyOrders = maxSafetyOrders,
        longDeviationPercentage = deviation,
        shortDeviationPercentage = shortDeviation,
        maxActiveDeals = maxActiveDeals,
        cooldownValue = cooldown,
        cooldownInHours = cooldownUnit == DcaTimeUnit.Hours,
        portfolioTargetPercentage = portfolioTarget,
        topUniverseSize = topUniverseSize,
        entryMode = entryMode,
        stopLossEnabled = stopLossEnabled
    ).applyTo(stored)

    fun save(): DcaBotSettings = draft().also {
        DcaBotSettingsStore.save(context, it)
        stored = it
        if (TradingCycleStore.startedAt(context) > 0L && !TradingCycleStore.isLocked(context)) {
            TradingCycleStore.updateTarget(context, it.portfolioTargetPercentage)
        }
        if (AutoTradingStore.isEnabled(context) &&
            StrategyProfileStore.activeDefinition(context).id == "strategy_3" &&
            it.maxActiveDeals > ActiveHyperliquidPositionStore.count(context)
        ) {
            BackgroundScannerScheduler.runNow(context)
        }
        savedMessage = "Instellingen opgeslagen · maximale dealwaarde ${usd(it.maximumDealValueUsd())}"
    }

    fun saveAndClose() {
        save()
        onBack()
    }

    BackHandler(onBack = ::saveAndClose)

    LaunchedEffect(Unit) { delay(40); revealed = true }
    Column(
        Modifier.fillMaxSize().background(DcaBg).graphicsLayer {
            rotationY = rotation; cameraDistance = 18f * density
        }.verticalScroll(rememberScrollState()).padding(16.dp)
    ) {
        TradeMentorTextButton(label = "← Opslaan en terug naar strategy", onClick = ::saveAndClose, modifier = Modifier.fillMaxWidth())
        Text("DCA Pulse", color = Color.White, fontSize = 31.sp, fontWeight = FontWeight.ExtraBold)
        val configuredTopUniverse = topUniverseSize.toIntOrNull() ?: stored.topUniverseSize
        Text("MULTI-PAIR DCA · TOP $configuredTopUniverse BIJ EERSTE AANKOOP", color = DcaGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
        Text(
            "DCA Pulse gebruikt uitsluitend zijn eigen regels. Nieuwe deals starten vanuit de CoinMarketCap top $configuredTopUniverse; daarna blijft de pair meedoen aan zijn vaste DCA-ladder.",
            color = DcaMuted, fontSize = 11.sp, lineHeight = 16.sp, modifier = Modifier.padding(top = 8.dp)
        )
        Spacer(Modifier.height(14.dp))

        DcaSection("Botstatus", "Precies één strategie kan actief zijn.") {
            SettingToggle("DCA Pulse actief", enabled) { requested ->
                if (!requested) onEnabled(false) else {
                    val settings = save()
                    settings.executionBlockReason()?.let { savedMessage = "Kan niet starten: $it" } ?: onEnabled(true)
                }
            }
            DcaNumberField(
                "Top universumgrootte",
                topUniverseSize,
                { topUniverseSize = it.filter { ch -> ch.isDigit() } },
                "1 – 500 (bijv. 50)"
            )
            FixedRule(
                "Top universum",
                "ALLEEN BASISORDER",
                "Bij bijkopen wordt de top-${configuredTopUniverse}-status niet opnieuw gecontroleerd."
            )
        }

        DcaSection("Richting en capaciteit", "Long en short zijn altijd samen actief; de balans wordt uitsluitend op aantallen bewaakt.") {
            FixedRule("Richting", "LONG + SHORT", "24u stijgers worden long; 24u dalers short. Maximaal verschil: drie actieve pairs.")
            DcaNumberField("Max actieve deals", maxActiveDeals, { maxActiveDeals = it }, "1–500 unieke, op Hyperliquid verhandelbare pairs")
            FixedRule("Hefboom", "MAXIMUM PER PAIR", "Het orderbedrag blijft notional gelijk; iedere pair gebruikt zijn actuele Hyperliquid-maximum.")
            Text("TIJD TUSSEN BIJKOPEN", color = DcaMuted, fontSize = 9.sp, fontWeight = FontWeight.Black)
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                DcaTimeUnit.entries.forEach { unit ->
                    Surface(
                        color = if (cooldownUnit == unit) Color(0xFF113A32) else Color(0xFF162033),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.weight(1f).clickable { cooldownUnit = unit }
                    ) {
                        Text(unit.label, color = if (cooldownUnit == unit) DcaGreen else Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(11.dp))
                    }
                }
            }
            DcaNumberField("Tijdswaarde", cooldown, { cooldown = it }, if (cooldownUnit == DcaTimeUnit.Hours) "1–168 uur" else "1–10.080 minuten")
        }

        DcaSection("Eerste aankoop", "Kandidaten worden eerst volledig op absolute 24u-beweging gerangschikt.") {
            Text("INSTAPMETHODE", color = DcaMuted, fontSize = 9.sp, fontWeight = FontWeight.Black)
            Row(Modifier.fillMaxWidth().padding(vertical = 7.dp), horizontalArrangement = Arrangement.spacedBy(7.dp)) {
                listOf("bollinger" to "BOLLINGER", "direct" to "DIRECT VULLEN").forEach { (mode, label) ->
                    Surface(
                        color = if (entryMode == mode) Color(0xFF113A32) else Color(0xFF162033),
                        shape = RoundedCornerShape(12.dp),
                        modifier = Modifier.weight(1f).clickable { entryMode = mode }
                    ) {
                        Text(label, color = if (entryMode == mode) DcaGreen else Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(11.dp))
                    }
                }
            }
            DcaNumberField("Basisorder", baseOrder, { baseOrder = it }, "USD · minimaal $10")
            if (entryMode == "direct") {
                FixedRule("Direct vullen", "SNELSTE 24U-BEWEGERS", "Geen uitstapprijs of BB-instapvoorwaarde. Unieke Top-N-pairs, vrije capaciteit en balans blijven verplicht.")
                FixedRule("Richting", "STIJGER LONG · DALER SHORT", "Posities worden handmatig gesloten; bijkopen volgen afzonderlijk de DCA-ladder.")
            } else {
                FixedRule("Long", "STIJGER + ONDER LOWER BB", "BB(20,2), gesloten 1m-candles.")
                FixedRule("Short", "DALER + BOVEN UPPER BB", "BB(20,2), gesloten 1m-candles.")
            }
        }

        DcaSection("DCA-ladder", "Iedere bijkoop is gelijk aan de basisorder en blijft in de oorspronkelijke richting.") {
            val preview = draft()
            FixedRule("Bedrag per bijkoop", usd(preview.baseOrderUsd), "Geen volume- of martingalevermenigvuldiging.")
            DcaNumberField("Maximaal aantal bijkopen", maxSafetyOrders, { maxSafetyOrders = it }, "0–20 · geldt direct voor lopende deals")
            DcaNumberField("Long-afstand per niveau", deviation, { deviation = it }, "% onder de oorspronkelijke long-instap")
            DcaNumberField("Short-afstand per niveau", shortDeviation, { shortDeviation = it }, "% boven de oorspronkelijke short-instap")
            FixedRule("Maximale geplande dealwaarde", usd(preview.maximumDealValueUsd()), "Basisorder plus alle ingestelde bijkopen.")
        }

        DcaSection("Portfoliocyclus", "Normale posities sluit je handmatig; dit doel is de enige automatische Close All.") {
            DcaNumberField("Close All-doel", portfolioTarget, { portfolioTarget = it }, "% groei vanaf de vaste cyclusstart · standaard 10%")
            FixedRule("Startwaarde", "VAST PER START", "Wijzigt niet wanneer je het doel tijdens de cyclus verhoogt.")
            FixedRule("Normale exits", "HANDMATIG", "Take-profit en trailing blijven uit.")
            SettingToggle("Stop-loss activeren", stopLossEnabled) { stopLossEnabled = it }
            FixedRule(
                "Stop-loss",
                if (stopLossEnabled) "INGESCHAKELD" else "UIT",
                if (stopLossEnabled) "Automatische stop-loss sluiting is actief." else "Stop-loss staat uit; sluiting gebeurt handmatig."
            )
        }

        TradeMentorPrimaryButton(label = "Instellingen opslaan", onClick = { save() }, modifier = Modifier.fillMaxWidth().height(50.dp))
        savedMessage?.let { Text(it, color = DcaGreen, fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp)) }
        Text("Dit is een experimentele teststrategie; historische prestaties zijn geen winstgarantie.", color = DcaMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 14.dp, bottom = 30.dp))
    }
}

@Composable
private fun DcaSection(title: String, subtitle: String, content: @Composable ColumnScope.() -> Unit) {
    Surface(color = DcaCard, shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 11.dp)) {
        Column(Modifier.padding(15.dp)) {
            Text(title.uppercase(), color = DcaGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
            Text(subtitle, color = DcaMuted, fontSize = 10.sp, lineHeight = 14.sp, modifier = Modifier.padding(top = 4.dp, bottom = 11.dp))
            content()
        }
    }
}

@Composable
private fun DcaNumberField(label: String, value: String, onValue: (String) -> Unit, hint: String) {
    OutlinedTextField(
        value = value,
        onValueChange = { onValue(it.filter { char -> char.isDigit() || char == '.' || char == ',' }.replace(',', '.')) },
        label = { Text(label) }, supportingText = { Text(hint, color = DcaMuted, fontSize = 9.sp) },
        singleLine = true, keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Decimal),
        modifier = Modifier.fillMaxWidth().padding(bottom = 4.dp)
    )
}

@Composable
private fun SettingToggle(label: String, checked: Boolean, onChecked: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().padding(vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(label, color = Color.White, fontSize = 12.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
        Switch(checked = checked, onCheckedChange = onChecked)
    }
}

@Composable
private fun FixedRule(label: String, value: String, explanation: String) {
    Surface(color = Color(0xFF152238), shape = RoundedCornerShape(12.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 7.dp)) {
        Column(Modifier.padding(11.dp)) {
            Row(Modifier.fillMaxWidth()) {
                Text(label, color = Color.White, fontSize = 10.sp, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                Text(value, color = DcaBlue, fontSize = 10.sp, fontWeight = FontWeight.Black)
            }
            Text(explanation, color = DcaMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 3.dp))
        }
    }
}

private fun number(value: Double): String = if (value % 1.0 == 0.0) value.toInt().toString() else String.format(Locale.US, "%.2f", value)
private fun usd(value: Double): String = String.format(Locale.US, "$%.2f", value)
