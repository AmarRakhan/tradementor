package com.tradementor.app.screens

import android.content.Context
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
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.google.gson.Gson
import com.google.gson.reflect.TypeToken
import com.tradementor.app.BuildConfig
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorGhostButton
import com.tradementor.app.components.TradeMentorTextButton

private val LearnBg = Color(0xFF05070B)
private val LearnPanel = Color(0xFF101722)
private val LearnBlue = Color(0xFF2F68FF)
private val LearnGreen = Color(0xFF08C887)
private val LearnMuted = Color(0xFF8C92A3)

private data class LaunchTask(
    val id: String,
    val phase: String,
    val title: String,
    val completed: Boolean = false,
    val note: String = "",
    val custom: Boolean = false
)

private val verifiedCompletedTaskIds = setOf(
    "admin_email",
    "cloud_project",
    "billing",
    "budget",
    "firebase",
    "android_app",
    "config"
)

private val initialLaunchTasks = listOf(
    LaunchTask("brand_name", "1 · Naam en eigenaarschap", "Overkoepelende studio- of bedrijfsnaam bedenken"),
    LaunchTask("brand_check", "1 · Naam en eigenaarschap", "Domein, handelsnaam, merken en bestaande apps controleren"),
    LaunchTask("domain", "1 · Naam en eigenaarschap", "Domeinnaam registreren"),
    LaunchTask("admin_email", "1 · Naam en eigenaarschap", "Neutraal beheeradres aanmaken en tweestapsverificatie inschakelen", completed = true),
    LaunchTask("cloud_project", "2 · Google Cloud", "Neutraal Google Cloud-project aanmaken", completed = true),
    LaunchTask("billing", "2 · Google Cloud", "Facturering zelf activeren", completed = true),
    LaunchTask("budget", "2 · Google Cloud", "Maandbudget €10 met waarschuwingen op 50%, 80% en 100% instellen", completed = true),
    LaunchTask("firebase", "3 · Firebase", "Firebase aan hetzelfde Cloud-project koppelen", completed = true),
    LaunchTask("android_app", "3 · Firebase", "Android-app registreren met pakketnaam com.tradementor.app", completed = true),
    LaunchTask("config", "3 · Firebase", "google-services.json downloaden en in de app-map plaatsen", completed = true),
    LaunchTask("server_scan", "4 · Server en signals", "Centrale scanner op Cloud Run activeren"),
    LaunchTask("hyperliquid", "4 · Server en signals", "Hyperliquid iedere vijf minuten laten analyseren"),
    LaunchTask("database", "4 · Server en signals", "Signals, instellingen en gevolgde trades centraal opslaan"),
    LaunchTask("push", "5 · Notificaties", "Firebase-pushmeldingen aan TradeMentor koppelen"),
    LaunchTask("test_push", "5 · Notificaties", "Testmelding op mijn telefoon ontvangen"),
    LaunchTask("dedupe", "5 · Notificaties", "Dubbele meldingen voor hetzelfde signal voorkomen"),
    LaunchTask("deep_link", "5 · Notificaties", "Melding rechtstreeks het juiste signal laten openen"),
    LaunchTask("notification_settings", "6 · Gebruikersinstellingen", "Kleur, richting, exchange, geluid en stilteperiode instelbaar maken"),
    LaunchTask("accounts", "7 · Accounts", "Accounts en synchronisatie veilig inrichten"),
    LaunchTask("practice", "8 · Praktijktest", "Signals en meldingen minimaal één tot twee weken testen"),
    LaunchTask("load_test", "9 · Opschalen", "Belastingtest voor 1.000 gebruikers uitvoeren"),
    LaunchTask("backups", "9 · Opschalen", "Monitoring, back-ups en noodschakelaar instellen"),
    LaunchTask("legal", "10 · Publicatie", "Privacybeleid, voorwaarden en financiële disclaimer maken"),
    LaunchTask("play", "10 · Publicatie", "Google Play Console en gesloten testgroep voorbereiden")
)

@Composable
fun LearningScreen(onBack: (() -> Unit)? = null) {
    val context = LocalContext.current
    var showProjectLog by remember { mutableStateOf(false) }
    if (showProjectLog) {
        ProjectLogScreen(onBack = { showProjectLog = false })
        return
    }
    var tasks by remember { mutableStateOf(loadLaunchTasks(context)) }
    var newTask by remember { mutableStateOf("") }
    val completed = tasks.count { it.completed }
    val progress = if (tasks.isEmpty()) 0f else completed.toFloat() / tasks.size

    Column(
        modifier = Modifier.fillMaxSize().background(LearnBg)
            .statusBarsPadding().navigationBarsPadding()
            .verticalScroll(rememberScrollState()).padding(18.dp)
    ) {
        onBack?.let {
            TradeMentorGhostButton(label = "← Terug naar Risk", onClick = it, modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp))
        }
        Text("Launchpad", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
        Text("Van eerste voorbereiding naar een schaalbare TradeMentor-server", color = LearnMuted, fontSize = 13.sp)
        Spacer(Modifier.height(14.dp))
        Surface(color = LearnPanel, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(15.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text("Voortgang", color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text("$completed / ${tasks.size}", color = LearnGreen, fontWeight = FontWeight.Bold)
                }
                Spacer(Modifier.height(9.dp))
                LinearProgressIndicator(progress = { progress }, modifier = Modifier.fillMaxWidth(), color = LearnGreen, trackColor = Color(0xFF252D3B))
                Spacer(Modifier.height(7.dp))
                Text("Tik op een taak om een notitie toe te voegen.", color = LearnMuted, fontSize = 11.sp)
                Spacer(Modifier.height(10.dp))
                TradeMentorPrimaryButton(
                    label = "Open projectlogboek",
                    onClick = { showProjectLog = true },
                    modifier = Modifier.fillMaxWidth()
                )
            }
        }
        Spacer(Modifier.height(16.dp))

        tasks.groupBy { it.phase }.forEach { (phase, phaseTasks) ->
            Text(phase, color = Color(0xFF9DB4FF), fontSize = 14.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(vertical = 7.dp))
            phaseTasks.forEach { task ->
                LaunchTaskRow(
                    task = task,
                    onChanged = { changed ->
                        tasks = tasks.map { if (it.id == changed.id) changed else it }
                        saveLaunchTasks(context, tasks)
                    },
                    onDelete = if (task.custom) {{
                        tasks = tasks.filterNot { it.id == task.id }
                        saveLaunchTasks(context, tasks)
                    }} else null
                )
                Spacer(Modifier.height(7.dp))
            }
        }

        Spacer(Modifier.height(12.dp))
        Text("Eigen taak toevoegen", color = Color.White, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(7.dp))
        Row(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalAlignment = Alignment.CenterVertically) {
            OutlinedTextField(
                value = newTask,
                onValueChange = { newTask = it },
                label = { Text("Nieuwe taak") },
                singleLine = true,
                modifier = Modifier.weight(1f)
            )
            TradeMentorPrimaryButton(
                label = "+",
                onClick = {
                val title = newTask.trim()
                if (title.isNotEmpty()) {
                    tasks = tasks + LaunchTask("custom_${System.currentTimeMillis()}", "Mijn eigen taken", title, custom = true)
                    saveLaunchTasks(context, tasks)
                    newTask = ""
                }
                },
                modifier = Modifier
            )
        }

        Spacer(Modifier.height(20.dp))
    }
}

private data class BuildLogEntry(
    val build: String,
    val version: String,
    val title: String,
    val details: String,
    val status: String = "Gebouwd en gecontroleerd",
    val date: String = "1–3 augustus 2026"
)

private val buildLog = listOf(
    BuildLogEntry("183", "2.15", "Feedback vanuit de app", "Iedere gebruiker kan vanuit Instellingen bugs, wensen, verbeteringen en verwijderverzoeken veilig melden en de voortgang volgen. De Amar Admin-versie bevat een beveiligde centrale feedbackinbox met toestel- en buildinformatie en beheerstatussen.", "Publieke en adminvariant gebouwd; cloudrechten per gebruiker gecontroleerd", "4 augustus 2026"),
    BuildLogEntry("156", "1.88", "Cryptografische cloudpreflight", "De persoonlijke sleutel blijft in Secret Manager, ondertekent daar lokaal een unieke controleboodschap en verifieert het afgeleide agentadres. De app accepteert de proef alleen met ready, dryRun en signatureVerified true én ordersEnabled false.", "Cloud Run-revisie 9 · geen order of handtekening uitgezonden", "3 augustus 2026"),
    BuildLogEntry("155", "1.87", "End-to-end dubbele-orderproef", "De app verstuurt eenmalig tweemaal dezelfde onuitvoerbare migratie-intentie. Alleen hetzelfde intent-ID plus duplicate=true bij de tweede aanvraag geldt als geslaagd; bovendien moet ordersEnabled bij beide antwoorden false blijven.", "Cloud Run-revisie 8 · geen echte pair of order gebruikt", "3 augustus 2026"),
    BuildLogEntry("154", "1.86", "Persoonlijke scanner- en tradecloudsync", "Scannerstatus, handelsinstellingen en maximaal 2.500 persoonlijke traderecords worden via Firebase-authenticatie met Cloud Run en Firestore gesynchroniseerd. Per trade-id worden toestel- en cloudversies samengevoegd; orderuitvoering blijft uit.", "Cloud Run-revisie 7 · onbevoegd lezen en schrijven geeft 401", "3 augustus 2026"),
    BuildLogEntry("153", "1.85", "Compacte 3D-verbindingskaarten", "MetaMask-wallet, API-wallet en TradeMentor Cloud staan op Wallet als drie rustige compacte statusregels met groen bolletje en vinkje zodra de koppeling actief is. Tikken draait één kaart 3D om en toont uitgebreide informatie en beheeracties.", "MetaMask krijgt nu dezelfde duidelijke groene verbondenstatus", "3 augustus 2026"),
    BuildLogEntry("152", "1.84", "Compact taalmenu met vlaggen", "De taalinstelling toont standaard alleen de actieve taal en klapt op verzoek open. Alle 21 talen hebben een herkenbare vlag; English staat bovenaan, gevolgd door Nederlands. Ook de eerste-startkeuze gebruikt deze strakke volgorde.", "Settings blijft compact tot de gebruiker op de taalkaart tikt", "3 augustus 2026"),
    BuildLogEntry("151", "1.83", "Taalkeuze vóór registratie", "Nieuwe installaties openen voortaan eerst met de keuze uit 21 talen en gaan pas daarna naar accountregistratie of inloggen. De keuze blijft lokaal bewaard; bestaande gebruikers worden automatisch als Nederlands gemigreerd en niet onderbroken.", "Eerste-startvolgorde zonder bestaande accounts uit te loggen", "3 augustus 2026"),
    BuildLogEntry("150", "1.82", "Eenentwintig app-talen", "De taalkeuze bevat nu Nederlands plus negentien brede wereldtalen en Sranan Tongo als bonustaal. Iedere keuze heeft de eigen taalnaam en vertaalde hoofdnavigatie- en instellingenkoppen.", "Technische onbekende termen vallen veilig terug op Engels", "3 augustus 2026"),
    BuildLogEntry("149", "1.81", "Gecentreerde tabbladkoppen", "De hoofdkoppen van Backtest, Markets, Signals, Live Positions, Risk Management en Wallet staan nu horizontaal gecentreerd voor een rustigere, consistente schermindeling.", "Beide appvarianten gelijkgetrokken", "3 augustus 2026"),
    BuildLogEntry("148", "1.80", "Taalkeuze met negen talen", "Wallet Settings bevat nu een opgeslagen taalkeuze voor Nederlands, Engels, vereenvoudigd Chinees, Hindi, Spaans, Frans, Arabisch, Bengaals en Portugees. De instellingenkoppen en volledige hoofdnavigatie reageren direct na de keuze.", "Taalbasis voorbereid voor verdere vertaling van alle inhoudelijke analyseteksten", "3 augustus 2026"),
    BuildLogEntry("147", "1.79", "Conservatieve liquidatieveiligheidszones", "Live Positions en Risk Management gebruiken nu duidelijke zones: gezond onder 30%, volgen vanaf 30%, geen extra risico vanaf 50%, hoog vanaf 70%, kritiek vanaf 85% en liquidatiegevaar vanaf 95%.", "Gebaseerd op de officiële 95%-liquidatiegrens; gewenste TradeMentor-grens blijft onder 30%", "3 augustus 2026"),
    BuildLogEntry("146", "1.78", "Unified Account-risico gelijk aan Hyperliquid", "De liquidatiemeter gebruikt bij Unified Account en Portfolio Margin voortaan maintenance margin gedeeld door de volledige portfolio value. Daardoor sluit het percentage aan op Hyperliquid; de meter toont dit met twee decimalen.", "Gecontroleerd met $100,98 / $424,87 = 23,77%", "3 augustus 2026"),
    BuildLogEntry("145", "1.77", "Cloudstatus en instellingen", "Handelsstatus en maximum actieve trades gebruiken persoonlijke Firebase-authenticatie en Cloud Run. Het lokale IP-adres en de lokale servercode zijn uit Wallet verwijderd en vervangen door één rustige TradeMentor Cloud-status. Orderroutes bestaan alleen als vergrendelde placeholders.", "Geen echte orderuitvoering mogelijk", "3 augustus 2026"),
    BuildLogEntry("144", "1.76", "Walletdata via persoonlijke cloudroute", "Wallet en Live Positions halen Hyperliquid-accountgegevens voortaan via een Firebase-beveiligde Cloud Run-route op. De server injecteert het aan de gebruiker gekoppelde walletadres en accepteert uitsluitend vooraf toegestane alleen-lezen informatietypen.", "Cloud Run-revisie 3 gepubliceerd; orders blijven uit", "3 augustus 2026"),
    BuildLogEntry("143", "1.75", "Persoonlijke cloudwalletkoppeling", "Cloud Run-revisie 2 voegt beveiligde walletstatus, live positievoorbereiding en handelsinstellingen per Firebase-gebruiker toe. De Android-app koppelt het bestaande openbare MetaMask-adres automatisch aan uitsluitend het ingelogde account.", "Onbevoegde cloudtoegang getest en geweigerd", "3 augustus 2026"),
    BuildLogEntry("142", "1.74", "Rustiger Wallet en schermcontrole", "Het portfolioblok staat bovenaan Wallet; technische koppelingen zijn gegroepeerd onder Verbindingen. Launchpad en projectlogboek respecteren de status- en navigatiebalk, opgeslagen systeemtaken krijgen bijgewerkte teksten en logregels tonen een compacte datum.", "Adminschermen visueel op toestel gecontroleerd", "3 augustus 2026"),
    BuildLogEntry("141", "1.73", "Admin- en distributieversie", "Iedere release bouwt voortaan twee APK's: TradeMentor - Amar Admin met takenlijst en projectlogboek, en een schone TradeMentor-distributieversie zonder deze beheeronderdelen. Veilige schermmarges en compacte logboekdatums toegevoegd.", "Beide varianten afzonderlijk gebouwd", "3 augustus 2026"),
    BuildLogEntry("140", "1.72", "Eerste Cloud Run-koppeling", "Veilige TradeMentor API in Nederland gepubliceerd, kostenbewaking ingesteld en Firebase-accountbootstrap vanuit de Android-app gekoppeld. Echte cloudorders blijven uit.", "Cloudstatus en afwijzing zonder login getest", "3 augustus 2026"),
    BuildLogEntry("139", "1.71", "Firebase-accountlaag en cloudvoorbereiding", "Firebase Authentication, afgeschermde gebruikersprofielen, wachtwoordherstel, e-mailverificatie en de basis voor persoonlijke cloudgegevens toegevoegd.", "Android-build succesvol geverifieerd", "3 augustus 2026"),
    BuildLogEntry("1–8", "Blueprint 1.0–1.8", "Fundament", "Appstructuur, eerste Markets- en scannerfuncties, documentatieafspraken en professionele ontwikkelstructuur.", "Historisch vastgelegd"),
    BuildLogEntry("9", "1.9", "Signals en Bollinger-filters", "Directe Bollinger-filterkeuzes, 3D-resultaatdetails, uitgebreide timeframes, sortering, tradehistorie, appsettings en versiebeheer."),
    BuildLogEntry("10–11", "1.9", "Beveiliging en professionele charts", "Pincode, biometrie, automatische vergrendeling en TradingView-achtige candlecharts met indicatoren, zoom en crosshair."),
    BuildLogEntry("12–13", "1.9", "Signals, management en chartflow", "Scanner werd Signals, History kreeg managementinformatie en de MEXC-referentie bepaalde de compactere chartwerkruimte."),
    BuildLogEntry("14–16", "1.9", "Exchanges en Binance", "Top-25 exchangecatalogus, marktcontext, Binance Spot-chart en zelfstandige Binance-signalanalyse."),
    BuildLogEntry("17", "1.9", "History-crashhotfix", "Oudere trades defensief gemigreerd en de History-crash op het toestel opgelost.", "Hotfix geïnstalleerd en getest"),
    BuildLogEntry("18", "1.9", "ANR-vastloper opgelost", "Zware Advisor-berekeningen verhuisden van de schermthread naar achtergrondverwerking.", "Hotfix geïnstalleerd en getest"),
    BuildLogEntry("19–27", "1.9", "Signals opnieuw verfijnd", "Compactere bediening, looptijd als resultaatvenster, filters op winkans, live batchresultaten, herstel van lege resultaten en gerichte Advisor-diagnostiek."),
    BuildLogEntry("28–40", "1.10–1.22", "Van screener naar sterke signals", "De oude timeframe- en minimumknoppen werden stapsgewijs verwijderd. Signals ging automatisch LONG en SHORT over meerdere analysetypen beoordelen, met technische redenen en een eenvoudiger kernscherm.", "Historische buildreeks; hoofdbesluiten vastgelegd"),
    BuildLogEntry("41–42", "1.23–1.24", "Multi-timeframe Advisor en Watchlist", "Snelle, korte, intraday- en swingplannen; Trade volgen; resterende winkans; live advies; doel- en risicocontrole; stabielere schermstatus."),
    BuildLogEntry("43", "1.25", "Risico en kleurbeoordeling", "Instelbare maximale tegenbeweging, groen/geel/rood, TradeMentor-score en correcte volgorde van profitdoel versus risicogrens."),
    BuildLogEntry("44", "1.26", "Launchpad", "Interactieve server- en publicatietaken met afvinken, doorstrepen, notities, voortgang en eigen taken."),
    BuildLogEntry("45", "1.27", "Tabblad hernoemd", "Leren werd Launchpad met een passende navigatiemarkering."),
    BuildLogEntry("46", "1.28", "History vereenvoudigd", "Compacte tradekaarten met 3D-flip, details op de achterkant en een aparte knop naar de koersgrafiek."),
    BuildLogEntry("47", "1.29", "Samengestelde TradeMentor-score", "Score verdeeld over kanskwaliteit, risico-opbrengst, betrouwbaarheid, indicatorbevestiging en meetbare marktkwaliteit. History werd Live Watchlist."),
    BuildLogEntry("48", "1.30", "Actuele winkans", "Bij instap en huidige winkans naast elkaar; tienseconden-verversing en behoud van de laatst geldige waarde."),
    BuildLogEntry("49", "1.31", "Verversingscyclus gerepareerd", "Zelfannulering gevonden via toesteldata. Alle actieve trades worden nu per volledige cyclus verwerkt. Trade volgen voegt direct toe zonder bevestigingsscherm.", "Gebouwd, geïnstalleerd en toestelprobleem onderzocht"),
    BuildLogEntry("50", "1.32", "Projectlogboek", "Professionele buildtijdlijn en besluitenoverzicht toegevoegd aan Launchpad."),
    BuildLogEntry("51", "1.33", "Eén actieve trade per pair", "Een pair kan ongeacht exchange of LONG/SHORT maar één keer actief in Live Watchlist staan. Na Succeeded of Failed komt de pair automatisch vrij."),
    BuildLogEntry("52", "1.34", "Watchlistbeheer en compactere Signals", "Swipe-verwijderen met bevestiging, tijdelijke Alles wissen-knop en een veel compactere bedieningszone boven Sterkste kansen."),
    BuildLogEntry("53", "1.35", "Signals grafisch hersteld", "Afgeknipte Material-velden vervangen door compacte selector-kaarten, echte richtingchips en correct leesbare profit- en risicovelden."),
    BuildLogEntry("54", "1.36", "Score centraal op signalkaart", "TradeMentor-score, oordeel, meter, verwachte duur en risico naar boven verplaatst. Instap en doel teruggebracht tot compacte uitvoeringsdetails."),
    BuildLogEntry("55", "1.37", "Actieve pairs uit Signals", "Pairs met een Pending-trade in Live Watchlist worden realtime uit alle Signals-resultaten gefilterd en komen na afsluiten of verwijderen automatisch terug."),
    BuildLogEntry("56", "1.38", "Statusfilters Live Watchlist", "Kaartenlijst filterbaar op Alle trades, Actief, Doel behaald en Mislukt, combineerbaar met de bestaande datumfilters."),
    BuildLogEntry("57", "1.39", "Compacte periodekeuze", "De vijf grote datumchips zijn vervangen door één zichtbare Periode-knop rechtsboven met een overzichtelijk keuzescherm."),
    BuildLogEntry("58", "1.40", "Vier Signals tegelijk", "De instellingen zijn inklapbaar en ieder signaal behoudt winrate, TradeMentor-score, looptijd, datakwaliteit, risico, indicatoren, instap en doel in een kleinere kaart."),
    BuildLogEntry("59", "1.41", "Historische Signals-backtest", "Vanaf Signals kan TradeMentor maximaal 50 historische signalen simuleren op 2, 4 of 8 weken geleden. Iedere voorspelling gebruikt alleen toen bekende candles en wordt daarna met de werkelijke zeven dagen vergeleken."),
    BuildLogEntry("60", "1.42", "Uitgebreide verklaarbare backtest", "Backtests uitgebreid tot twee jaar en 250 signals. Iedere regel verklaart waarom het signaal verscheen en waarom het doel wel of niet werd behaald, inclusief beste en grootste tegenbeweging."),
    BuildLogEntry("61", "1.43", "Zichtbare backtestvoortgang", "Een duidelijke laadkaart toont percentage, meetmoment, periode en aantal signals. Normale annulering bij een nieuwe keuze wordt niet meer als technische fout getoond."),
    BuildLogEntry("62", "1.44", "Sorteerbare maximale tegenbeweging", "Max. tegen staat als vaste kolom bij ieder historisch signaal en is met één tik oplopend of aflopend sorteerbaar."),
    BuildLogEntry("63", "1.45", "Financiële backtestsimulatie", "Vrije inzet per signal en stoploss toegevoegd. Rapport toont totaal ingezet, bruto winst, bruto verlies, netto resultaat en eindwaarde; verlopen trades sluiten tegen hun werkelijke zevendaagse slotprijs."),
    BuildLogEntry("64", "1.46", "Beste stoploss achteraf", "Backtest vergelijkt automatisch stoplossgrenzen vanaf 0,5% tot het geteste maximum, toont welke grens de hoogste eindwaarde gaf en laat die grens direct opnieuw testen."),
    BuildLogEntry("65", "1.47", "ROI-optimalisatie van instellingen", "TradeMentor zoekt tegelijk naar max. tegen, minimale TM-score en richting die het procentuele verschil tussen inzet en eindwaarde maximaliseren. Keuze gebeurt op de oudste 70% en wordt gecontroleerd op de nieuwste 30%."),
    BuildLogEntry("66", "1.48", "Vrij instelbaar profitdoel in backtest", "Naast inzet en max. tegen is ook het profitdoel vrij wijzigbaar. Een nieuwe run herberekent signalen, winrate, uitkomsten, financiële rapportage en optimale instellingen voor dat doel."),
    BuildLogEntry("67", "1.49", "Chronologische portefeuillesimulatie", "Startkapitaal en inzet per trade zijn gescheiden. Geld staat tijdens actieve trades vast, komt na afsluiting terug beschikbaar en signals worden overgeslagen als onvoldoende vrij kapitaal bestaat. Rapport toont eindwaarde, ROI, omzet en drawdown."),
    BuildLogEntry("68", "1.50", "Volledige profit- en stoplossoptimalisatie", "Backtest draait volledige vergelijkingen voor 0,5%, 1%, 1,5%, 2%, 3% en 5% profit. Eén hoofdkaart toont daarna profitdoel, stoploss, TM-score en richting van de combinatie met de beste gecontroleerde ROI."),
    BuildLogEntry("69", "1.51", "Financiële vergelijking beste instellingen", "De kaart Beste instellingen achteraf toont dezelfde hoofdregel als de gebruikersinstellingen: startkapitaal, totaal ingezet, rendement en eindwaarde."),
    BuildLogEntry("70", "1.52", "Minimale winrate in backtest", "Vrij instelbaar minimum voor de voorspelde winrate toegevoegd. Alleen historische signals vanaf deze kans tellen mee in portefeuille, financieel rapport en optimalisatie."),
    BuildLogEntry("71", "1.53", "Winrate in gezamenlijke optimizer", "Beste instellingen achteraf optimaliseert nu ook de minimale voorspelde winrate, samen met profitdoel, max. tegen, TM-score en richting."),
    BuildLogEntry("72", "1.54", "3D-uitleg beste instellingen", "De kaart Beste instellingen achteraf draait met een dubbeltik in 3D en verklaart uitgebreid profitdoel, stoploss, selectiedrempels, 70/30-controle, portefeuille-aannames en beperkingen."),
    BuildLogEntry("73", "1.55", "Export beste backtestinstellingen", "Voltooide beste instellingen zijn als duidelijke tekst deelbaar via Android. Export bevat rendement en richting, maar bewust geen startkapitaal of eindbedrag."),
    BuildLogEntry("74", "1.56", "Permanent sorteerbaar backtestarchief", "Iedere volledig afgeronde backtest slaat automatisch zijn beste instellingen op een apart archiefscherm op, sorteerbaar op datum, rendement, profit, stoploss en winrate."),
    BuildLogEntry("75", "1.57", "Consensus bovenaan Backtest", "Bovenaan Historische backtest staat een permanent consensusblok met robuuste medianen van opgeslagen beste instellingen, meest voorkomende richting en op controletrades gewogen rendement."),
    BuildLogEntry("76", "1.58", "Automatisch archief zonder exportknop", "De handmatige exportknop is verwijderd omdat iedere voltooide backtest automatisch permanent in het Backtestarchief wordt opgeslagen."),
    BuildLogEntry("77", "1.59", "Winratedrempel correct bij gelijke uitkomst", "Bij identieke trades en ROI kiest de optimizer nu de hoogste duidelijke winratedrempel. Wanneer geen filter voordeel gaf, wordt Geen filter getoond in plaats van het misleidende 0+."),
    BuildLogEntry("78", "1.60", "Actieve-tradeteller", "Live Watchlist toont permanent hoeveel trades nu actief zijn; dezelfde teller staat ook in het filter Actief."),
    BuildLogEntry("79", "1.61", "Onbeperkte onderzoeksdatabase", "Backtestarchief gemigreerd van begrensde JSON-opslag naar SQLite zonder inhoudelijke limiet. Iedere voorspelling, score, instelling en uitkomst wordt per run vastgelegd met server-synchronisatievelden."),
    BuildLogEntry("80", "1.62", "Backtest als hoofdtab en automatisch volgen", "Home is vervangen door een zelfstandig Backtest-tabblad. Volledig berekende sterke Signals worden automatisch aan Live Trades toegevoegd; verwijderen uit Live Trades raakt de onderzoeksdatabase niet."),
    BuildLogEntry("81", "1.63", "Consensusgestuurde kwartierscanner", "De achtergrondscanner gebruikt iedere circa 15 minuten profitdoel, stoploss, winrate, score en richting uit het Backtest-consensusprofiel. Afgeronde pairs worden vrijgegeven, sterke signals automatisch gevolgd en Live Trades ververst zijn teller vanuit dezelfde opslag."),
    BuildLogEntry("82", "1.64", "Direct volgen en veilig leerlogboek", "Actieve pairs worden vóór candle-analyse uitgesloten, ieder sterk resultaat direct gevolgd en opnieuw beschikbare pairs meteen toegevoegd. Afgeronde positieve en negatieve trades gaan naar een onverwijderbaar SQLite-leerlogboek; Alles verwijderen wist alleen de zichtbare watchlist."),
    BuildLogEntry("83", "1.64", "Actief Scannerprofiel en bewijsbasis", "Het belangrijkste consensusvak heet nu Actief Scannerprofiel en vermeldt expliciet dat het Signals en Live Trades aanstuurt. Runs, unieke historische situaties, controletrades, echte uitkomsten en betrouwbaarheidsniveau zijn zichtbaar."),
    BuildLogEntry("84", "1.64", "Roterend volledig Hyperliquid-universum", "Iedere niet-actieve Hyperliquid-pair wordt beoordeeld. De zware multi-timeframe-analyse roteert per kwartier door groepen van maximaal 30, zodat alle pairs aan bod komen zonder de lokale API-belasting te overschrijden."),
    BuildLogEntry("85", "1.64", "Wallet alleen-lezen", "Nieuw Wallet-tabblad met Reown/MetaMask-koppeling. Leest uitsluitend openbare Hyperliquid-accountwaarde, beschikbaar saldo, posities, orders en transacties; de app bevat geen order- of opname-endpoint."),
    BuildLogEntry("86", "1.64", "Unified Portfolio Value", "Wallet herkent automatisch Classic, Unified Account en Portfolio Margin. Unified totalen worden uit spot/collateral-balansen en actuele spotwaarderingen opgebouwd in plaats van de misleidende klassieke perp-accountwaarde."),
    BuildLogEntry("87", "1.64", "Echte Live Positions", "Tabblad 4 toont uitsluitend werkelijke open Hyperliquid-posities met live PNL, rendement, instap, marge, hefboom en liquidatieprijs. De oude zichtbare testwatchlist wordt eenmalig geleegd zonder leerlogboek of echte posities te wijzigen. Signals kreeg een duidelijke hoofdschakelaar waarmee voorgrond- en kwartierscans plus nieuwe lokale voorspellingen samen gestart of gestopt worden."),
    BuildLogEntry("90", "1.64", "Veilige Testnet-handelslaag", "Orderplanning gebruikt positiewaarde, maximale marktleverage, berekende marge, profitdoel, totaalplafond en dubbele-pairblokkering. Mainnet en daadwerkelijke verzending blijven geblokkeerd totdat een Hyperliquid API-wallet veilig is goedgekeurd."),
    BuildLogEntry("91", "1.64", "Opstartboodschap", "Het grafische beginscherm toont de professioneel gecorrigeerde boodschap ‘Love taught me one thing: having no money is not an option.’ en blijft een halve seconde langer zichtbaar."),
    BuildLogEntry("92", "1.65", "Veilige API-walletkluis", "Nieuw versienummer voor automatisch handelen. Een afzonderlijke Hyperliquid API-wallet kan lokaal met Android Keystore worden versleuteld; hoofdwalletsleutels en seed phrases worden nadrukkelijk geweigerd. Echte orders blijven geblokkeerd totdat ondertekening en Testnet-validatie compleet zijn."),
    BuildLogEntry("93", "1.65", "Eén tik MetaMask-koppeling", "Handmatige sleutelvelden zijn verwijderd. TradeMentor genereert lokaal een aparte Testnet API-wallet, bewaart de sleutel versleuteld en vraagt MetaMask eenmalig om de officiële Hyperliquid approveAgent EIP-712-toestemming."),
    BuildLogEntry("94", "1.65", "LONG/SHORT-richtingsbalans", "Voorgrond- en kwartierscanner tellen echte plus gereserveerde LONG- en SHORT-posities. Nieuwe trades worden uitsluitend in de ondervertegenwoordigde richting toegelaten totdat het aantal maximaal één verschilt, binnen het totale positieplafond."),
    BuildLogEntry("95", "1.65", "MetaMask automatisch openen", "Na verzending van het WalletConnect EIP-712-verzoek opent TradeMentor de geïnstalleerde MetaMask-app expliciet. Dit voorkomt dat de gebruiker op het zwarte startscherm achterblijft."),
    BuildLogEntry("88", "1.64", "Alle Hyperliquid perp-DEX-posities", "Live Positions vraagt naast de standaard DEX ook iedere actuele HIP-3/builder-DEX op en voegt echte open posities zonder dubbeltelling samen. Hierdoor ontbreken posities buiten de hoofd-DEX niet meer."),
    BuildLogEntry("110", "1.69", "Handelsstatus en Live Positions-dashboard", "Wallet toont de actuele Hyperliquid-handelsruimte prominent als Available to trade in USDC. De verouderde Alleen lezen-labels zijn vervangen. Live Positions toont opnieuw actieve, gewonnen en verloren trades, succesratio en filters voor Alles, Actief, Gewonnen en Verloren."),
    BuildLogEntry("111", "1.69", "Ongerealiseerde P&L op positiekaart", "De voorkant van iedere echte Live Positions-kaart toont permanent de actuele ongerealiseerde P&L in dollars, plus het procentuele koersresultaat en het ingestelde take-profitdoel."),
    BuildLogEntry("113", "1.70", "Echt vrij beschikbaar saldo", "Wallet en Live Positions tonen voor Unified Accounts nu het werkelijk vrij beschikbare USDC/USDT-collateral: totaal minus vastgehouden saldo. Classic Accounts blijven het officiële withdrawable-bedrag gebruiken."),
    BuildLogEntry("114", "1.70", "Vrij saldo op twee decimalen", "Het vrij beschikbare bedrag wordt op Wallet en Live Positions consequent als dollarbedrag met exact twee decimalen getoond."),
    BuildLogEntry("115", "1.70", "Optioneel Markets-tabblad", "Onder Settings kan het tweede hoofdtabblad Markets worden verborgen of opnieuw getoond. De marktdata voor Signals blijft onafhankelijk beschikbaar."),
    BuildLogEntry("116", "1.70", "Financieel overzicht Live Positions", "Portfolio value staat links en Available to trade rechts in één compacte kaart, beide als dollarbedrag met twee decimalen."),
    BuildLogEntry("117", "1.70", "Uniforme Live Positions-lijsten", "Actief gebruikt nu dezelfde compacte lijstindeling als Alles, Gewonnen en Verloren. De afwijkende extra overzichtskaart tussen tabs en posities is verwijderd; actuele PNL en details blijven beschikbaar."),
    BuildLogEntry("118", "1.70", "Identieke compacte positiekaarten", "Het losse PNL-kleurblok op Actief is verwijderd. PNL en take-profit staan nu in dezelfde compacte rechterkolom als de statusinformatie op Gewonnen en Verloren, waardoor alle tabbladen dezelfde kaarthoogte gebruiken."),
    BuildLogEntry("119", "1.70", "Live Positions zonder verspringen", "Alles is verwijderd en Live Positions opent standaard op Actief. Actief, Gewonnen en Verloren gebruiken compacte kaarten met exact dezelfde vaste hoogte, zodat wisselen tussen tabs niet meer verspringt."),
    BuildLogEntry("120", "1.70", "Instelbare hoofdnavigatie", "Wallet heeft een directe Appinstellingen-knop. Backtest en Markets kunnen daar onafhankelijk worden verborgen; met beide uit vullen Signals, Live Positions en Wallet automatisch de volledige navigatiebalk."),
    BuildLogEntry("121", "1.70", "Grafische risicometer", "De financiële kaart boven Live Positions toont nu Portfolio value links, een compacte halfronde risicometer in het midden en Available to trade rechts, zonder de bestaande kaarthoogte te wijzigen."),
    BuildLogEntry("122", "1.70", "Kassageluid bij behaald winstdoel", "Wanneer een echte actieve positie verdwijnt en Hyperliquid een positieve closedPnl-fill bevestigt, toont TradeMentor een eenmalige popupmelding en speelt een kort synthetisch rinkeld-geldgeluid."),
    BuildLogEntry("123", "1.70", "Authenticatie vóór startscherm", "Bij het openen vraagt TradeMentor eerst om pincode of biometrie. Pas na succesvolle authenticatie verschijnt het startscherm met slogan, gevolgd door de app."),
    BuildLogEntry("124", "1.70", "Echte liquidatieratio", "De meter volgt nu de beurslogica: cross maintenance margin gedeeld door cross account value. Available to trade telt niet meer als risico; 100% is uitsluitend de daadwerkelijke liquidatiegrens."),
    BuildLogEntry("125", "1.70", "Duidelijke terugknop in Settings", "De kleine tekstlink is vervangen door een brede knop Terug naar Wallet bovenaan de instellingenpagina."),
    BuildLogEntry("126", "1.70", "Blijvende trade-informatie", "Actieve trades bewaren voortaan hefboom, positiewaarde en liquidatieprijs. Bij sluiten worden echte closedPnl, slotkoers en looptijd vastgelegd; dezelfde kaartinformatie blijft zichtbaar op Gewonnen en Verloren."),
    BuildLogEntry("127", "1.70", "Sortering op duur en profit", "Actief, Gewonnen en Verloren kunnen met één tik worden gesorteerd op Langste duur of Meeste profit. De gekozen sortering blijft behouden bij wisselen tussen statustabs."),
    BuildLogEntry("128", "1.70", "Maximum trades via 3D-prestatiekaart", "Tik op de tegel Actief om de Prestatiekaart om te draaien. Achterop kan Maximum actieve trades direct worden aangepast; deze waarde blijft gesynchroniseerd met Signals."),
    BuildLogEntry("129", "1.70", "Duidelijke liquidatierisicozones", "De margin ratio is nadrukkelijk gelabeld als voortgang naar de liquidatiegrens. Onder 30% is veilig groen, 30–70% is oranje Let op en vanaf 70% is het risico rood en hoog.")
)

@Composable
private fun ProjectLogScreen(onBack: () -> Unit) {
    Column(modifier = Modifier.fillMaxSize().background(LearnBg).statusBarsPadding().navigationBarsPadding().verticalScroll(rememberScrollState()).padding(18.dp)) {
        TradeMentorTextButton(label = "‹ Launchpad", onClick = onBack)
        Text("Projectlogboek", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
        Text("Versie ${BuildConfig.VERSION_NAME} · build ${BuildConfig.VERSION_CODE}", color = LearnGreen, fontSize = 13.sp, fontWeight = FontWeight.Bold)
        Text("Wensen, besluiten, uitvoering en verificatie vanaf het begin", color = LearnMuted, fontSize = 12.sp)
        Spacer(Modifier.height(14.dp))
        Surface(color = LearnBlue.copy(alpha = 0.14f), shape = RoundedCornerShape(14.dp), modifier = Modifier.fillMaxWidth()) {
            Text(
                "Vaste afspraak: ieder nieuw buildnummer krijgt voortaan een eigen entry. Een buildnummer wordt nooit opnieuw gebruikt.",
                color = Color(0xFFB8C7FF), fontSize = 12.sp, modifier = Modifier.padding(14.dp)
            )
        }
        Spacer(Modifier.height(12.dp))
        buildLog.asReversed().forEach { entry ->
            Surface(color = LearnPanel, shape = RoundedCornerShape(15.dp), modifier = Modifier.fillMaxWidth()) {
                Column(modifier = Modifier.padding(14.dp)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text("BUILD ${entry.build}", color = LearnGreen, fontSize = 11.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.weight(1f))
                        Text("${entry.date}  ·  v${entry.version}", color = LearnMuted, fontSize = 10.sp)
                    }
                    Spacer(Modifier.height(5.dp))
                    Text(entry.title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
                    Spacer(Modifier.height(5.dp))
                    Text(entry.details, color = Color(0xFFB8BFCC), fontSize = 12.sp, lineHeight = 18.sp)
                    Spacer(Modifier.height(7.dp))
                    Text("● ${entry.status}", color = Color(0xFF9DB4FF), fontSize = 9.sp, fontWeight = FontWeight.Bold)
                }
            }
            Spacer(Modifier.height(9.dp))
        }
    }
}

@Composable
private fun LaunchTaskRow(task: LaunchTask, onChanged: (LaunchTask) -> Unit, onDelete: (() -> Unit)?) {
    var expanded by remember(task.id) { mutableStateOf(task.note.isNotBlank()) }
    var note by remember(task.id, task.note) { mutableStateOf(task.note) }
    Surface(color = LearnPanel, shape = RoundedCornerShape(13.dp), modifier = Modifier.fillMaxWidth()) {
        Column(modifier = Modifier.padding(horizontal = 9.dp, vertical = 7.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth()) {
                Checkbox(
                    checked = task.completed,
                    onCheckedChange = { onChanged(task.copy(completed = it)) },
                    colors = CheckboxDefaults.colors(checkedColor = LearnGreen)
                )
                Text(
                    task.title,
                    color = if (task.completed) LearnMuted else Color.White,
                    fontSize = 13.sp,
                    textDecoration = if (task.completed) TextDecoration.LineThrough else TextDecoration.None,
                    modifier = Modifier.weight(1f).clickable { expanded = !expanded }
                )
                Text(if (expanded) "−" else "+", color = LearnBlue, modifier = Modifier.padding(8.dp).clickable { expanded = !expanded })
            }
            if (expanded) {
                OutlinedTextField(
                    value = note,
                    onValueChange = { note = it },
                    label = { Text("Notitie of ingevulde waarde") },
                    minLines = 2,
                    modifier = Modifier.fillMaxWidth()
                )
                Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.End) {
                    onDelete?.let { TradeMentorTextButton(label = "Verwijderen", onClick = it, color = Color(0xFFFF4964)) }
                    TradeMentorTextButton(label = "Opslaan", onClick = { onChanged(task.copy(note = note.trim())); expanded = false })
                }
            }
        }
    }
}

private fun loadLaunchTasks(context: Context): List<LaunchTask> = runCatching {
    val json = context.getSharedPreferences("launchpad", Context.MODE_PRIVATE).getString("tasks", null)
        ?: return initialLaunchTasks
    val type = object : TypeToken<List<LaunchTask>>() {}.type
    val saved = Gson().fromJson<List<LaunchTask>>(json, type).orEmpty()
    val savedById = saved.associateBy { it.id }
    initialLaunchTasks.map { initial ->
        val merged = savedById[initial.id] ?: initial
        merged.copy(
            phase = initial.phase,
            title = initial.title,
            completed = merged.completed || initial.id in verifiedCompletedTaskIds
        )
    } + saved.filter { it.custom }
}.getOrElse { initialLaunchTasks }

private fun saveLaunchTasks(context: Context, tasks: List<LaunchTask>) {
    context.getSharedPreferences("launchpad", Context.MODE_PRIVATE).edit().putString("tasks", Gson().toJson(tasks)).apply()
}
