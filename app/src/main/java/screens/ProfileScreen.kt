package com.tradementor.app.screens

import android.content.Intent
import android.net.Uri
import android.provider.Settings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Switch
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.BuildConfig
import com.tradementor.app.scanner.ProfitableTradeClosureNotifier
import com.tradementor.app.security.AppLockManager
import com.tradementor.app.localization.AppLanguage
import com.tradementor.app.localization.AppLanguageStore
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorTextButton
import com.tradementor.app.localization.tr
import com.tradementor.app.localization.languageFlag
import com.tradementor.app.localization.orderedLanguages
import kotlinx.coroutines.delay

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun AppSettingsScreen(
    onBack: (() -> Unit)? = null,
    onOpenFeedback: () -> Unit = {},
    purchasePreviewEnabled: Boolean = false,
    onPurchasePreviewEnabledChange: (Boolean) -> Unit = {}
) {
    val context = LocalContext.current
    var refreshVersion by remember { mutableIntStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }
    var lockEnabled by remember { mutableStateOf(AppLockManager.isEnabled(context)) }
    var biometricEnabled by remember { mutableStateOf(AppLockManager.isBiometricEnabled(context)) }
    var newPin by remember { mutableStateOf("") }
    var confirmPin by remember { mutableStateOf("") }
    var currentPin by remember { mutableStateOf("") }
    var securityMessage by remember { mutableStateOf("") }
    var showDisableDialog by remember { mutableStateOf(false) }
    var language by remember { mutableStateOf(AppLanguageStore.load(context)) }
    var languageExpanded by remember { mutableStateOf(false) }
    var selectedProfitSound by remember { mutableStateOf(ProfitableTradeClosureNotifier.selectedSoundId(context)) }
    var moneySoundsExpanded by remember { mutableStateOf(false) }
    var movieCriesExpanded by remember { mutableStateOf(false) }

    LaunchedEffect(refreshVersion) {
        if (refreshVersion == 0) return@LaunchedEffect
        delay(350)
        refreshing = false
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { refreshing = true; refreshVersion++ },
        modifier = Modifier.fillMaxSize().background(Color(0xFF05070B)).statusBarsPadding().navigationBarsPadding()
    ) {
        Column(modifier = Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(18.dp)) {
            if (onBack != null) {
                TradeMentorPrimaryButton(
                    label = "← Terug naar Wallet",
                    onClick = onBack,
                    modifier = Modifier.fillMaxWidth().padding(bottom = 12.dp)
                )
            }
            Text(tr(language, "settings"), color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.Bold)
            Text(tr(language, "settings_subtitle"), color = Color(0xFF8C92A3), fontSize = 13.sp)
            Spacer(Modifier.height(20.dp))

            SettingsCard(tr(language, "language")) {
                Row(Modifier.fillMaxWidth().clickable { languageExpanded = !languageExpanded }.padding(15.dp)) {
                    Text(language.nativeName, color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                    Text("${languageFlag(language)}   ${if (languageExpanded) "▲" else "▼"}", color = Color(0xFF63D6A4), fontWeight = FontWeight.Black)
                }
                if (languageExpanded) {
                    Text(tr(language, "language_help"), color = Color(0xFF8C92A3), fontSize = 11.sp, modifier = Modifier.padding(horizontal = 15.dp, vertical = 8.dp))
                    orderedLanguages().forEach { option ->
                        HorizontalDivider(color = Color(0xFF232A38))
                        Row(modifier = Modifier.fillMaxWidth().clickable {
                            language = option
                            languageExpanded = false
                            AppLanguageStore.save(context, option)
                            (context as? android.app.Activity)?.recreate()
                        }.padding(15.dp)) {
                            Text(option.nativeName, color = Color.White, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                            Text("${languageFlag(option)}${if (language == option) "   ✓" else ""}", color = Color(0xFF63D6A4), fontWeight = FontWeight.Black)
                        }
                    }
                }
            }
            Spacer(Modifier.height(12.dp))

            SettingsCard(tr(language, "app")) {
                SettingsLine(tr(language, "version"), BuildConfig.VERSION_NAME)
                HorizontalDivider(color = Color(0xFF232A38))
                SettingsLine(tr(language, "build"), BuildConfig.VERSION_CODE.toString())
                HorizontalDivider(color = Color(0xFF232A38))
                SettingsLine(tr(language, "package"), BuildConfig.APPLICATION_ID)
            }
            Spacer(Modifier.height(12.dp))
            SettingsCard("In-app aankopen · voorbeeld") {
                Row(modifier = Modifier.fillMaxWidth().padding(15.dp)) {
                    Column(modifier = Modifier.weight(1f)) {
                        Text("Toon toekomstige winkelweergave", color = Color.White, fontWeight = FontWeight.SemiBold)
                        Text("Alleen een visueel voorbeeld. Er wordt niets gekocht of afgeschreven.", color = Color(0xFF8C92A3), fontSize = 11.sp)
                    }
                    Switch(checked = purchasePreviewEnabled, onCheckedChange = onPurchasePreviewEnabledChange)
                }
                if (purchasePreviewEnabled) {
                    HorizontalDivider(color = Color(0xFF232A38))
                    Column(Modifier.padding(15.dp)) {
                        Text("TRADEMENTOR MEMBERSHIP", color = Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.Black)
                        Text("Kies later het niveau dat bij jouw handelsstijl past", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp, bottom = 12.dp))
                        PurchasePreviewPlan("CORE", "Gratis", "TradeMentor Core · Live Positions · Wallet", true)
                        PurchasePreviewPlan("PRO", "€ 9,99 / maand", "Quantum Shield · uitgebreid Risk · strategie-inzichten", false)
                        PurchasePreviewPlan("ELITE", "€ 19,99 / maand", "Alle strategieën · vergelijking · geavanceerd leren", false)
                        Text("DEMO · knoppen en betalingen zijn bewust uitgeschakeld", color = Color(0xFF8C92A3), fontSize = 9.sp, modifier = Modifier.padding(top = 10.dp))
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            SettingsCard(tr(language, "main_tabs")) {
                Column(modifier = Modifier.fillMaxWidth().padding(15.dp)) {
                    Text("MEXC · HYPERLIQUID · ASTER · WALLET", color = Color.White, fontWeight = FontWeight.SemiBold)
                    Text(
                        "De vier hoofdbestemmingen staan vast. Strategy is bereikbaar vanuit Hyperliquid; overige analysefuncties blijven achterliggend beschikbaar.",
                        color = Color(0xFF8C92A3),
                        fontSize = 11.sp,
                        lineHeight = 16.sp,
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            SettingsCard(tr(language, "security")) {
                Column(modifier = Modifier.padding(15.dp)) {
                    Text(
                        if (lockEnabled) "Appvergrendeling is actief" else "Bescherm TradeMentor met een persoonlijke code.",
                        color = if (lockEnabled) Color(0xFF63D6A4) else Color(0xFFB8BFCC),
                        fontWeight = FontWeight.SemiBold,
                        fontSize = 14.sp
                    )
                    Spacer(Modifier.height(10.dp))
                    if (!lockEnabled) {
                        SecurityPinField("Nieuwe code (4–8 cijfers)", newPin) { newPin = it; securityMessage = "" }
                        Spacer(Modifier.height(8.dp))
                        SecurityPinField("Herhaal code", confirmPin) { confirmPin = it; securityMessage = "" }
                        Spacer(Modifier.height(10.dp))
                        TradeMentorPrimaryButton(
                            label = "Appvergrendeling instellen",
                            onClick = {
                                when {
                                    newPin.length !in 4..8 -> securityMessage = "Kies een code van 4 tot en met 8 cijfers."
                                    newPin != confirmPin -> securityMessage = "De twee codes zijn niet gelijk."
                                    else -> {
                                        AppLockManager.setPin(context, newPin)
                                        lockEnabled = true
                                        newPin = ""
                                        confirmPin = ""
                                        securityMessage = "Appvergrendeling is ingesteld."
                                    }
                                }
                            },
                            modifier = Modifier.fillMaxWidth()
                        )
                    } else {
                        Row(modifier = Modifier.fillMaxWidth()) {
                            Column(modifier = Modifier.weight(1f)) {
                                Text("Vingerafdruk of gezicht", color = Color.White, fontWeight = FontWeight.SemiBold)
                                Text("Gebruikt de biometrie die in Android is ingesteld.", color = Color(0xFF8C92A3), fontSize = 11.sp)
                            }
                            Switch(
                                checked = biometricEnabled,
                                onCheckedChange = {
                                    biometricEnabled = it
                                    AppLockManager.setBiometricEnabled(context, it)
                                    securityMessage = if (it) "Biometrisch ontgrendelen staat aan." else "Biometrisch ontgrendelen staat uit."
                                }
                            )
                        }
                        Spacer(Modifier.height(12.dp))
                        TradeMentorPrimaryButton(
                            label = "Appvergrendeling uitschakelen",
                            onClick = { showDisableDialog = true },
                            modifier = Modifier.fillMaxWidth()
                        )
                    }
                    if (securityMessage.isNotBlank()) {
                        Spacer(Modifier.height(8.dp))
                        Text(securityMessage, color = Color(0xFF9DB4FF), fontSize = 12.sp)
                    }
                }
            }
            Spacer(Modifier.height(12.dp))
            SettingsCard(tr(language, "scanner_notifications")) {
                Text(
                    "Scannerfilters, achtergrondscan en meldingsstijl beheer je via het tandwiel op de Scanner-pagina.",
                    color = Color(0xFFB8BFCC), fontSize = 13.sp, lineHeight = 19.sp,
                    modifier = Modifier.padding(15.dp)
                )
                if (BuildConfig.APPLICATION_ID.endsWith(".test")) {
                    HorizontalDivider(color = Color(0xFF232A38))
                    Text(
                        "Kies een geldgeluid of gesproken winstkreet",
                        color = Color.White,
                        fontWeight = FontWeight.Bold,
                        modifier = Modifier.padding(horizontal = 15.dp, vertical = 12.dp)
                    )
                    listOf(
                        Triple("effects", "Geldgeluiden · 10", moneySoundsExpanded),
                        Triple("movies", "Victory sounds · echte stemmen & publiek · 10", movieCriesExpanded)
                    ).forEach { (category, title, expanded) ->
                        Row(
                            modifier = Modifier.fillMaxWidth().clickable {
                                if (category == "effects") moneySoundsExpanded = !moneySoundsExpanded
                                else movieCriesExpanded = !movieCriesExpanded
                            }.padding(horizontal = 15.dp, vertical = 13.dp)
                        ) {
                            Text(title, color = Color.White, fontWeight = FontWeight.Bold, modifier = Modifier.weight(1f))
                            Text(if (expanded) "▲" else "▼", color = Color(0xFF63D6A4))
                        }
                        if (expanded) {
                            ProfitableTradeClosureNotifier.soundOptions.filter { it.category == category }.forEach { option ->
                                val selected = selectedProfitSound == option.id
                                Row(
                                    modifier = Modifier.fillMaxWidth().clickable {
                                        selectedProfitSound = option.id
                                        ProfitableTradeClosureNotifier.selectSound(context, option.id)
                                        ProfitableTradeClosureNotifier.previewSound(context, option.id)
                                    }.padding(start = 26.dp, end = 15.dp, top = 9.dp, bottom = 9.dp)
                                ) {
                                    Text(if (selected) "●" else "○", color = if (selected) Color(0xFF63D6A4) else Color(0xFF8C92A3), fontSize = 18.sp)
                                    Text(option.title, color = Color.White, fontWeight = if (selected) FontWeight.Bold else FontWeight.Normal, modifier = Modifier.weight(1f).padding(start = 10.dp))
                                    Text("▶", color = Color(0xFF63D6A4))
                                }
                            }
                        }
                        HorizontalDivider(color = Color(0xFF232A38))
                    }
                    TradeMentorPrimaryButton(
                        label = "Test gekozen winstgeluid",
                        onClick = { ProfitableTradeClosureNotifier.test(context) },
                        modifier = Modifier.fillMaxWidth().padding(15.dp)
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Surface(
                color = Color(0xFF0B2C27),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().clickable(onClick = onOpenFeedback)
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Feedback & problemen melden", color = Color.White, fontWeight = FontWeight.Bold)
                    Text(
                        if (BuildConfig.ADMIN_FEATURES) "Stuur een melding of open de centrale admin-inbox."
                        else "Meld een bug, wens of verbetering en volg de voortgang.",
                        color = Color(0xFF9DE4CB), fontSize = 12.sp
                    )
                }
            }
            Spacer(Modifier.height(12.dp))
            Surface(
                color = Color(0xFF2F68FF),
                shape = RoundedCornerShape(14.dp),
                modifier = Modifier.fillMaxWidth().clickable {
                    context.startActivity(Intent(Settings.ACTION_APPLICATION_DETAILS_SETTINGS).apply {
                        data = Uri.parse("package:${context.packageName}")
                    })
                }
            ) {
                Column(modifier = Modifier.padding(16.dp)) {
                    Text("Android-instellingen openen", color = Color.White, fontWeight = FontWeight.Bold)
                    Text("Beheer notificaties, batterijgebruik en toestemmingen.", color = Color(0xFFD7E1FF), fontSize = 12.sp)
                }
            }
            Spacer(Modifier.height(14.dp))
            Text(
                "Scannerstrategieën, Trade History en beveiligingsinstellingen worden lokaal op dit toestel bewaard.",
                color = Color(0xFF8C92A3), fontSize = 11.sp, lineHeight = 16.sp
            )
        }
    }

    if (showDisableDialog) {
        AlertDialog(
            onDismissRequest = { showDisableDialog = false; currentPin = "" },
            title = { Text("Vergrendeling uitschakelen") },
            text = {
                Column {
                    Text("Voer ter controle je huidige code in.")
                    Spacer(Modifier.height(10.dp))
                    SecurityPinField("Huidige code", currentPin) { currentPin = it }
                }
            },
            confirmButton = {
                TradeMentorTextButton(
                    label = "Uitschakelen",
                    color = Color(0xFFFF4964),
                    onClick = {
                    if (AppLockManager.verifyPin(context, currentPin)) {
                        AppLockManager.clear(context)
                        lockEnabled = false
                        biometricEnabled = false
                        currentPin = ""
                        showDisableDialog = false
                        securityMessage = "Appvergrendeling is uitgeschakeld."
                    } else securityMessage = "De huidige code klopt niet."
                    }
                )
            },
            dismissButton = {
                TradeMentorTextButton(label = "Annuleren", onClick = { showDisableDialog = false; currentPin = "" })
            }
        )
    }
}

@Composable
private fun PurchasePreviewPlan(name: String, price: String, features: String, current: Boolean) {
    Surface(
        color = if (current) Color(0xFF0B2C27) else Color(0xFF121A2A),
        shape = RoundedCornerShape(13.dp),
        modifier = Modifier.fillMaxWidth().padding(bottom = 8.dp)
    ) {
        Row(Modifier.fillMaxWidth().padding(12.dp)) {
            Column(Modifier.weight(1f)) {
                Text(name, color = if (current) Color(0xFF63D6A4) else Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.Black)
                Text(features, color = Color(0xFFC5CBD7), fontSize = 10.sp, modifier = Modifier.padding(top = 3.dp))
            }
            Text(if (current) "HUIDIG" else price, color = Color.White, fontSize = 11.sp, fontWeight = FontWeight.Bold)
        }
    }
}

@Composable
private fun SecurityPinField(label: String, value: String, onValueChange: (String) -> Unit) {
    OutlinedTextField(
        value = value,
        onValueChange = { onValueChange(it.filter(Char::isDigit).take(8)) },
        label = { Text(label) },
        singleLine = true,
        visualTransformation = PasswordVisualTransformation(),
        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
        modifier = Modifier.fillMaxWidth()
    )
}

@Composable
private fun SettingsCard(title: String, content: @Composable () -> Unit) {
    Column {
        Text(title, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.SemiBold)
        Spacer(Modifier.height(8.dp))
        Surface(color = Color(0xFF101722), shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
            Column { content() }
        }
    }
}

@Composable
private fun SettingsLine(label: String, value: String) {
    Row(modifier = Modifier.fillMaxWidth().padding(15.dp)) {
        Text(label, color = Color(0xFF8C92A3), modifier = Modifier.weight(1f))
        Text(value, color = Color.White, fontWeight = FontWeight.SemiBold)
    }
}
