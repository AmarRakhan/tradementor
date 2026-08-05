package com.tradementor.app.screens

import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.compose.ui.zIndex
import androidx.fragment.app.FragmentActivity
import com.reown.appkit.ui.AppKitSheet
import com.tradementor.app.repository.MarketRepository
import com.tradementor.app.localization.AppLanguageStore
import com.tradementor.app.localization.tr

private data class BottomDestination(val label: String, val glyph: String)

@Composable
fun MainScreen() {
    val context = LocalContext.current
    val language = remember { AppLanguageStore.load(context) }
    val tabPreferences = remember { context.getSharedPreferences("main_navigation", android.content.Context.MODE_PRIVATE) }
    var backtestVisible by remember { mutableStateOf(tabPreferences.getBoolean("backtest_visible", true)) }
    var marketsVisible by remember { mutableStateOf(tabPreferences.getBoolean("markets_visible", true)) }
    var signalsVisible by remember { mutableStateOf(tabPreferences.getBoolean("signals_visible", true)) }
    var purchasePreviewEnabled by remember { mutableStateOf(tabPreferences.getBoolean("purchase_preview_enabled", false)) }
    var selectedTab by remember { mutableIntStateOf(if (backtestVisible) 0 else if (marketsVisible) 1 else if (signalsVisible) 2 else 4) }
    var showSettings by remember { mutableStateOf(false) }
    var showFeedback by remember { mutableStateOf(false) }
    var showLaunchpad by remember { mutableStateOf(false) }
    var requestedMarketDirection by remember { mutableStateOf(MarketDirection.All) }
    var scannerWasOpened by remember { mutableStateOf(false) }
    val backtestRepository = remember { MarketRepository() }
    val activity = context as? FragmentActivity
    val openWallet = {
        activity?.let {
            if (it.supportFragmentManager.findFragmentByTag("reown_appkit") == null) {
                AppKitSheet().show(it.supportFragmentManager, "reown_appkit")
            }
        }
        Unit
    }
    val fullDestinations = listOf(
        BottomDestination(tr(language, "backtest"), "B"), BottomDestination(tr(language, "markets"), "M"),
        BottomDestination(tr(language, "signals"), "S"), BottomDestination(if (purchasePreviewEnabled) "Strategy PRO" else "Strategy", "ST"),
        BottomDestination(tr(language, "live_positions"), "●"),
        BottomDestination(tr(language, "risk"), "R"), BottomDestination(tr(language, "wallet"), "W")
    )
    val destinations = fullDestinations.filterIndexed { index, _ ->
        (index != 0 || backtestVisible) && (index != 1 || marketsVisible) && (index != 2 || signalsVisible)
    }

    if (showFeedback) {
        FeedbackScreen(onBack = { showFeedback = false })
        return
    }
    if (showSettings) {
        AppSettingsScreen(
            onBack = { showSettings = false },
            onOpenFeedback = { showFeedback = true },
            backtestVisible = backtestVisible,
            onBacktestVisibleChange = { visible ->
                backtestVisible = visible
                tabPreferences.edit().putBoolean("backtest_visible", visible).apply()
                if (!visible && selectedTab == 0) {
                    selectedTab = 2
                    scannerWasOpened = true
                }
            },
            marketsVisible = marketsVisible,
            onMarketsVisibleChange = { visible ->
                marketsVisible = visible
                tabPreferences.edit().putBoolean("markets_visible", visible).apply()
                if (!visible && selectedTab == 1) {
                    selectedTab = 2
                    scannerWasOpened = true
                }
            },
            signalsVisible = signalsVisible,
            onSignalsVisibleChange = { visible ->
                signalsVisible = visible
                tabPreferences.edit().putBoolean("signals_visible", visible).apply()
                if (!visible && selectedTab == 2) selectedTab = 4
            },
            purchasePreviewEnabled = purchasePreviewEnabled,
            onPurchasePreviewEnabledChange = { enabled ->
                purchasePreviewEnabled = enabled
                tabPreferences.edit().putBoolean("purchase_preview_enabled", enabled).apply()
            }
        )
        return
    }
    if (showLaunchpad) {
        LearningScreen(onBack = { showLaunchpad = false })
        return
    }

    Scaffold(
        containerColor = Color(0xFF05070B),
        bottomBar = {
            NavigationBar(containerColor = Color(0xFF0B101A), tonalElevation = 0.dp) {
                destinations.forEach { destination ->
                    val index = fullDestinations.indexOf(destination)
                    val selected = selectedTab == index
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            if (index == 1) requestedMarketDirection = MarketDirection.All
                            if (index == 2) scannerWasOpened = true
                            selectedTab = index
                        },
                        icon = { NavGlyph(destination.glyph, selected) },
                        label = { Text(destination.label, fontSize = 10.sp, fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Color.White, selectedTextColor = Color(0xFF08C887),
                            indicatorColor = Color.Transparent, unselectedIconColor = Color(0xFF737B8C),
                            unselectedTextColor = Color(0xFF737B8C)
                        )
                    )
                }
            }
        }
    ) { innerPadding ->
        Box(modifier = Modifier.padding(innerPadding)) {
            when (selectedTab) {
                0 -> BacktestScreen(backtestRepository, 1.0, 20.0, {}, false)
                1 -> MarketsScreen(initialDirection = requestedMarketDirection)
                2 -> Unit
                3 -> StrategyScreen(purchasePreviewEnabled = purchasePreviewEnabled)
                4 -> Unit
                5 -> RiskManagementScreen(onOpenLaunchpad = { showLaunchpad = true })
                6 -> WalletScreen(onOpenWallet = openWallet, onOpenSettings = { showSettings = true })
            }
            LivePositionsScreen(
                onOpenWallet = openWallet,
                modifier = Modifier.fillMaxSize().alpha(if (selectedTab == 4) 1f else 0f).zIndex(if (selectedTab == 4) 1f else -1f)
            )
            if (scannerWasOpened) ScannerScreen(Modifier.fillMaxSize().alpha(if (selectedTab == 2) 1f else 0f).zIndex(if (selectedTab == 2) 1f else -1f))
        }
    }
}

@Composable private fun NavGlyph(glyph: String, selected: Boolean) {
    Surface(color = if (selected) Color(0xFF2F68FF) else Color(0xFF151C29), shape = RoundedCornerShape(11.dp), modifier = Modifier.padding(bottom = 1.dp)) {
        Box(modifier = Modifier.padding(horizontal = 13.dp, vertical = 7.dp), contentAlignment = Alignment.Center) {
            Text(glyph, color = if (selected) Color.White else Color(0xFF8C92A3), fontSize = 14.sp, fontWeight = FontWeight.ExtraBold)
        }
    }
}
