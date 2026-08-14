package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.components.TradeMentorTextButton
import com.tradementor.app.scanner.ConsensusProfileStore
import com.tradementor.app.scanner.StrategyDefinition
import com.tradementor.app.scanner.StrategyProfileStore
import com.tradementor.app.scanner.TradeHistoryStore

private val StrategyBg = Color(0xFF05070B)
private val StrategyCard = Color(0xFF101A2A)
private val StrategyGreen = Color(0xFF08C887)
private val StrategyMuted = Color(0xFF8C92A3)

@Composable
fun StrategyScreen(
    purchasePreviewEnabled: Boolean = false,
    onBack: (() -> Unit)? = null,
) {
    val context = LocalContext.current
    val profile = remember { ConsensusProfileStore.load(context) }
    val closedTrades = remember { TradeHistoryStore.load(context).filter { it.closedAt != null && it.realizedPnl != null } }
    var selectedStrategy by remember { mutableStateOf<StrategyDefinition?>(null) }
    val enabled = remember {
        mutableStateMapOf<String, Boolean>().apply {
            StrategyProfileStore.definitions.forEach { put(it.id, StrategyProfileStore.isEnabled(context, it.id)) }
        }
    }

    selectedStrategy?.let { definition ->
        if (definition.id == "strategy_3") {
            DcaPulseScreen(
                enabled = enabled[definition.id] == true,
                onBack = { selectedStrategy = null },
                onEnabled = { value ->
                    StrategyProfileStore.setEnabled(context, definition.id, value)
                    StrategyProfileStore.definitions.forEach { candidate ->
                        enabled[candidate.id] = StrategyProfileStore.isEnabled(context, candidate.id)
                    }
                }
            )
            return
        }
        StrategyDetailPage(
            definition = definition,
            enabled = enabled[definition.id] == true,
            minimumWinRate = profile.minimumWinRate,
            profitTarget = profile.profitTarget,
            maxAdverse = profile.stopLoss,
            onBack = { selectedStrategy = null },
            onEnabled = { value ->
                StrategyProfileStore.setEnabled(context, definition.id, value)
                StrategyProfileStore.definitions.forEach { candidate ->
                    enabled[candidate.id] = StrategyProfileStore.isEnabled(context, candidate.id)
                }
            }
        )
        return
    }

    Column(Modifier.fillMaxSize().background(StrategyBg).verticalScroll(rememberScrollState()).padding(horizontal = 14.dp, vertical = 14.dp)) {
        if (onBack != null) {
            TradeMentorTextButton(
                label = "← Terug naar Hyperliquid",
                onClick = onBack,
                modifier = Modifier.fillMaxWidth(),
            )
            Spacer(Modifier.height(8.dp))
        }
        Text("Strategy", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.ExtraBold, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Text("Tik op een kaart voor een volledige, scrollbare uitleg", color = StrategyMuted, fontSize = 11.sp, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(13.dp))

        StrategyProfileStore.definitions.chunked(2).forEach { rowDefinitions ->
            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                rowDefinitions.forEach { definition ->
                    StrategyOverviewCard(
                        definition = definition,
                        enabled = enabled[definition.id] == true,
                        onOpen = { selectedStrategy = definition },
                        onEnabled = { value ->
                            StrategyProfileStore.setEnabled(context, definition.id, value)
                            StrategyProfileStore.definitions.forEach { candidate ->
                                enabled[candidate.id] = StrategyProfileStore.isEnabled(context, candidate.id)
                            }
                        },
                        purchasePreviewEnabled = purchasePreviewEnabled,
                        modifier = Modifier.weight(1f)
                    )
                }
                if (rowDefinitions.size == 1) Spacer(Modifier.weight(1f))
            }
            Spacer(Modifier.height(10.dp))
        }

        Surface(color = Color(0xFF0B1320), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("HISTORISCHE STRATEGIEVERGELIJKING", color = StrategyGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
                Text("Alleen gerealiseerde resultaten; historische prestaties zijn geen winstgarantie.", color = StrategyMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 5.dp, bottom = 8.dp))
                StrategyProfileStore.definitions.filter { it.specificationReady }.forEach { definition ->
                    val trades = closedTrades.filter { it.strategyId == definition.id || (it.strategyId == "unattributed" && it.strategyName == definition.name) }
                    val gross = trades.sumOf { it.realizedPnl ?: 0.0 }
                    val costs = trades.sumOf { it.feesPaidUsd + it.fundingPaidUsd }
                    val net = gross - costs
                    val wins = trades.count { (it.realizedPnl ?: 0.0) - it.feesPaidUsd - it.fundingPaidUsd > 0.0 }
                    val winRate = if (trades.isEmpty()) 0.0 else wins * 100.0 / trades.size
                    val averageRisk = if (trades.isEmpty()) 0.0 else trades.map { it.maxAdversePercentage }.average()
                    Text(definition.name, color = Color.White, fontWeight = FontWeight.Bold, fontSize = 12.sp, modifier = Modifier.padding(top = 7.dp))
                    Text(
                        if (trades.isEmpty()) "Nog geen toegeschreven gesloten trades"
                        else "Netto $${String.format("%.2f", net)} · kosten $${String.format("%.2f", costs)} · winratio ${String.format("%.1f", winRate)}% · gem. risicogrens ${String.format("%.2f", averageRisk)}% · ${trades.size} trades",
                        color = StrategyMuted, fontSize = 10.sp, lineHeight = 14.sp
                    )
                }
            }
        }
        Spacer(Modifier.height(10.dp))

        Surface(color = Color(0xFF111827), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Text("EERLIJKE VERGELIJKING", color = StrategyGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
                Text("We vergelijken rendement, tijd tot resultaat, winratio, maximale terugloop en invloed op de portfoliowaarde over dezelfde marktperiode.", color = Color(0xFFC5CBD7), fontSize = 11.sp, modifier = Modifier.padding(top = 6.dp))
                Text("De vijf lege strategieën kunnen pas aan nadat hun regels volledig zijn vastgelegd.", color = StrategyMuted, fontSize = 10.sp, modifier = Modifier.padding(top = 8.dp))
            }
        }
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun StrategyOverviewCard(
    definition: StrategyDefinition,
    enabled: Boolean,
    onOpen: () -> Unit,
    onEnabled: (Boolean) -> Unit,
    purchasePreviewEnabled: Boolean,
    modifier: Modifier
) {
    Surface(
        color = if (enabled) Color(0xFF0B2C27) else StrategyCard,
        shape = RoundedCornerShape(18.dp),
        modifier = modifier.height(172.dp).clickable(onClick = onOpen)
    ) {
        Column(Modifier.fillMaxSize().padding(14.dp), verticalArrangement = Arrangement.SpaceBetween) {
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(definition.name.uppercase(), color = if (enabled) StrategyGreen else StrategyMuted, fontSize = 10.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
                if (purchasePreviewEnabled) {
                    Text(if (definition.id == "strategy_1") "CORE" else "PRO", color = if (definition.id == "strategy_1") StrategyGreen else Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.Black, modifier = Modifier.padding(end = 6.dp))
                }
                Text(if (enabled) "●" else "○", color = if (enabled) StrategyGreen else StrategyMuted, fontSize = 12.sp)
            }
            Column {
                Text(
                    when {
                        definition.summary.isNotBlank() -> definition.summary
                        definition.defined -> "Historische technische selectie"
                        else -> "Nog niet gedefinieerd"
                    },
                    color = Color.White, fontSize = 14.sp, fontWeight = FontWeight.Bold
                )
                Text(
                    when {
                        definition.id == "strategy_2" -> "Autonoom · beschermd · maximaal 3×"
                        definition.id == "strategy_3" -> "Multi-pair · DCA-ladder · Aster Top-N"
                        definition.defined -> "Doel: gecontroleerde portfoliogroei"
                        else -> "Regels worden later samen bepaald"
                    },
                    color = StrategyMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 4.dp)
                )
            }
            Row(Modifier.fillMaxWidth(), verticalAlignment = Alignment.CenterVertically) {
                Text(if (definition.defined || definition.specificationReady) "Open uitleg  ↗" else "Open status  ↗", color = Color(0xFF9DB4FF), fontSize = 9.sp, modifier = Modifier.weight(1f))
                Switch(
                    checked = enabled,
                    onCheckedChange = onEnabled,
                    enabled = definition.specificationReady
                )
            }
        }
    }
}

@Composable
private fun StrategyDetailPage(
    definition: StrategyDefinition,
    enabled: Boolean,
    minimumWinRate: Double,
    profitTarget: Double,
    maxAdverse: Double,
    onBack: () -> Unit,
    onEnabled: (Boolean) -> Unit
) {
    Column(Modifier.fillMaxSize().background(StrategyBg).verticalScroll(rememberScrollState()).padding(16.dp)) {
        TradeMentorTextButton(label = "← Terug naar strategy", onClick = onBack, modifier = Modifier.fillMaxWidth())
        Spacer(Modifier.height(16.dp))
        Text(definition.name, color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.ExtraBold)
        Text(
            when {
                definition.id == "strategy_1" -> "HUIDIGE WINNENDE AANPAK"
                definition.id == "strategy_2" -> "ACTIEF · AUTONOOM · BESCHERMD"
                definition.id == "strategy_3" -> "MULTI-PAIR · DCA · ASTER TOP-N"
                else -> "NOG NIET BESCHIKBAAR"
            },
            color = if (definition.specificationReady) StrategyGreen else StrategyMuted,
            fontSize = 11.sp, fontWeight = FontWeight.Black, modifier = Modifier.padding(top = 4.dp)
        )
        Spacer(Modifier.height(16.dp))

        if (definition.id == "strategy_1") {
            StrategyDetailBlock("Doel", "De portfoliowaarde gecontroleerd laten groeien door alleen selectieve LONG- en SHORT-kansen te nemen waarvan vergelijkbare historische situaties vaak genoeg het winstdoel bereikten.")
            StrategyDetailBlock("Technische selectie", "De scanner combineert RSI, EMA20 en EMA50, Bollinger Bands, momentum, volume en volatiliteit. Eén losse indicator is nooit voldoende: signalen moeten elkaar ondersteunen.")
            StrategyDetailBlock("Historisch bewijs", "De actuele situatie wordt vergeleken met eerdere koerspatronen. Een kandidaat moet minimaal ${formatStrategy(minimumWinRate)}% berekende winkans halen voordat instappen mogelijk wordt.")
            StrategyDetailBlock("Laatste controle voor aankoop", "Vlak voor de order worden actuele koers, richting, winstdoel, datakwaliteit en marktconditie opnieuw gecontroleerd. Een verouderd of verslechterd signaal wordt afgewezen.")
            StrategyDetailBlock("Winst en risico", "Het doel is ${formatStrategy(profitTarget)}% koersbeweging vóór maximaal ${formatStrategy(maxAdverse)}% ongunstige beweging. Liquidatierisico, beschikbare ruimte en positiegrootte blijven onderdeel van de veiligheidscontrole.")
            StrategyDetailBlock("Portfoliobescherming", "Dubbele pairs, een volle positielimiet en een te scheve LONG/SHORT-verdeling worden geblokkeerd. Daardoor kan één munt of marktrichting niet ongemerkt de hele portefeuille domineren.")
            StrategyDetailBlock("Waarom deze aanpak kansrijk is", "De kracht zit in de combinatie van historische bevestiging, meerdere onafhankelijke indicatoren en een tweede controle direct vóór uitvoering. Dat maakt de strategie selectief; winst blijft nooit gegarandeerd.")
            StrategyDetailBlock("Metingen", "We meten gerealiseerd rendement, winratio, gemiddelde looptijd, maximale terugloop, liquidatiedruk en werkelijke groei van de portfoliowaarde.")
        } else if (definition.id == "strategy_2") {
            StrategyDetailBlock("Mandaat", "Strategie 2 mag zelfstandig het instrument, LONG of SHORT, instapmoment, uitstapmoment, positieomvang, eventuele hedge en hefboom kiezen. Het doel is portefeuillegroei, maar kapitaalbehoud is altijd belangrijker dan een extra kans op rendement.")
            StrategyDetailBlock("Volledig autonoom", "De gebruiker kiest uitsluitend welke ene strategie actief is. Na selectie accepteert Strategie 2 geen handmatige inhoudelijke input voor instrument, richting, timing, omvang, hedge, hefboom of exit. Alle beslissingen volgen uitsluitend haar vaste regels en beschermrails.")
            StrategyDetailBlock("Harde liquidatiegrens", "Een trade wordt afgewezen wanneer geen ruime veiligheidsafstand tot liquidatie kan worden aangetoond. De geplande stop moet ver vóór de liquidatiezone liggen; ontbreekt een betrouwbare stop of marktliquiditeit, dan is de enige toegestane keuze: niet instappen.")
            StrategyDetailBlock("Hefboomlimiet", "Geen onbeperkte hefboom. Ontwerpstandaard: 1×, alleen risicogestuurd verhogen en nooit boven 3×. Hogere volatiliteit, slechtere liquiditeit, sterke correlatie of oplopende accountdruk verlaagt de toegestane hefboom automatisch.")
            StrategyDetailBlock("Risico per positie", "Het vooraf berekende verlies bij de harde stop is maximaal 0,5% van de actuele portfoliowaarde. Eén positie gebruikt maximaal 10% notionele blootstelling. Positieomvang wordt verlaagd als de stop verder weg moet liggen.")
            StrategyDetailBlock("Totale blootstelling", "Maximaal 50% bruto blootstelling en 25% netto richtingsblootstelling als ontwerpstandaard. Vrij beschikbare marge blijft gereserveerd; beschikbare dollars zijn geen toestemming om alles te gebruiken.")
            StrategyDetailBlock("Exitvoorwaarden", "Iedere positie heeft vóór uitvoering een harde stop, winst-/afbouwplan en thesis-invalidatie. Uitstappen gebeurt bij stop, ongeldig signaal, verslechterde liquiditeit, tijdslimiet, bereikte winst of wanneer portefeuillerisico daarom vraagt. Een verliespositie mag niet onbeperkt blijven doorlopen.")
            StrategyDetailBlock("Dagelijkse circuit-breaker", "Bij 2% dagelijkse drawdown op gerealiseerd plus ongerealiseerd resultaat stopt Strategie 2 met nieuwe risico-opbouw en reduceert zij veilig waar nodig. Hervatten vereist een nieuwe risicocontrole; geen automatisch najagen van verlies.")
            StrategyDetailBlock("Gecorreleerd risico", "Sterk gecorreleerde munten tellen als één risicocluster. Ontwerpgrens: maximaal drie posities per cluster en samen maximaal 20% bruto blootstelling. Meerdere altcoin-longs worden dus niet behandeld alsof het onafhankelijke kansen zijn.")
            StrategyDetailBlock("Hedgebeleid", "Een hedge is optioneel, nooit verplicht. Hij is alleen toegestaan als hij aantoonbaar netto risico verlaagt. Een hedge mag geen verborgen extra hefboom, dubbele kosten of schijnveiligheid creëren. Gelijktijdige LONG/SHORT-balans is slechts één mogelijke techniek.")
            StrategyDetailBlock("Fail-safe", "Ontbrekende data, afwijkende prijzen, cloudproblemen, orderonzekerheid of een mislukte beschermingsorder betekent: geen nieuwe trade. Na iedere uitvoering moet stopbescherming bevestigd zijn; anders wordt de positie veilig afgebouwd en de strategie gepauzeerd.")
            StrategyDetailBlock("Eerlijke beoordeling", "Resultaten worden na kosten en funding gemeten op rendement, maximale drawdown, liquidatiedruk, volatiliteit van het resultaat en groei per tijdseenheid. Rendement telt alleen als de beschermrails gedurende de hele trade intact bleven.")
            StrategyDetailBlock("Meet- en leerkring", "Vooraf staan netto rendement, kosten, drawdown, stopafstand, liquidatiedruk, looptijd en risico-gecorrigeerde groei vast. Iedere gesloten trade en iedere periode wordt geëvalueerd. Parameters veranderen alleen gecontroleerd wanneer voldoende onafhankelijk bewijs uit backtests én paper trading dit ondersteunt; nooit op basis van één winst- of verliesreeks.")
            StrategyDetailBlock("Resultaatgericht, niet gegarandeerd", "Strategie 2 mikt op betekenisvolle risico-gecorrigeerde groei en niet op een kunstmatig minimaal dagdoel. Zij forceert geen trades om een target te halen. Historische prestaties zijn bewijs voor evaluatie, geen garantie voor toekomstige winst.")
            StrategyDetailBlock("Technische vrijgave", "Een instap wordt alleen geaccepteerd wanneer de cloud take-profit én harde stop-loss als reduce-only triggerorders bevestigt. Mislukt één bescherming, dan wordt een noodsluiting gestart en Scan & Buy direct uitgeschakeld.")
        } else {
            StrategyDetailBlock("Status", "Deze strategie is nog leeg. Instapregels, uitstapregels, winstdoel, risicogrens en meetmethode moeten eerst volledig worden vastgelegd.")
            StrategyDetailBlock("Eerlijke vergelijking", "Na activering krijgt iedere trade een strategielabel. De resultaten worden over dezelfde marktperiode vergeleken met Strategy 1.")
        }

        Surface(color = if (enabled) Color(0xFF0B2C27) else StrategyCard, shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Row(Modifier.fillMaxWidth().padding(16.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text(if (enabled) "Enige geselecteerde strategie" else "Strategie niet geselecteerd", color = if (enabled) StrategyGreen else Color.White, fontWeight = FontWeight.Bold)
                    Text(
                        if (definition.executionReady) "Alleen deze strategie mag signalen en acties leveren."
                        else if (enabled) "Geselecteerd, maar uitvoering veilig vergrendeld tot validatie gereed is."
                        else "Selecteren is toegestaan; signalen en orders blijven vergrendeld.",
                        color = StrategyMuted, fontSize = 11.sp
                    )
                }
                Switch(checked = enabled, onCheckedChange = if (definition.specificationReady) onEnabled else null, enabled = definition.specificationReady)
            }
        }
        Spacer(Modifier.height(32.dp))
    }
}

@Composable
private fun StrategyDetailBlock(title: String, body: String) {
    Surface(color = StrategyCard, shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth().padding(bottom = 10.dp)) {
        Column(Modifier.padding(16.dp)) {
            Text(title.uppercase(), color = StrategyGreen, fontSize = 10.sp, fontWeight = FontWeight.Black)
            Text(body, color = Color(0xFFD5DAE4), fontSize = 13.sp, lineHeight = 19.sp, modifier = Modifier.padding(top = 7.dp))
        }
    }
}

private fun formatStrategy(value: Double): String = if (value % 1.0 == 0.0) "%.0f".format(value) else "%.1f".format(value)
