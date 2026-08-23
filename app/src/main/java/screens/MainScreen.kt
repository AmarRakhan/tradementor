package com.tradementor.app.screens

import android.content.Context

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
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.fragment.app.FragmentActivity
import com.reown.appkit.ui.AppKitSheet
import com.tradementor.app.navigation.MainDestination
import com.tradementor.app.navigation.mainDestinations
import com.tradementor.app.navigation.restoreMainDestination
import com.tradementor.app.ui.theme.LocalTradeMentorColors

@Composable
fun MainScreen() {
    val palette = LocalTradeMentorColors.current
    val mutedText = MaterialTheme.colorScheme.onSurfaceVariant
    val context = LocalContext.current
    val navigationPreferences = remember { context.getSharedPreferences("main_navigation", Context.MODE_PRIVATE) }
    var purchasePreviewEnabled by remember { mutableStateOf(navigationPreferences.getBoolean("purchase_preview_enabled", false)) }
    var selectedDestination by remember {
        mutableStateOf(restoreMainDestination(navigationPreferences.getString("selected_main_destination", null)))
    }
    var showSettings by remember { mutableStateOf(false) }
    var showFeedback by remember { mutableStateOf(false) }
    var showHyperliquidStrategy by remember { mutableStateOf(false) }
    val activity = context as? FragmentActivity
    val openWallet = {
        activity?.let {
            if (it.supportFragmentManager.findFragmentByTag("reown_appkit") == null) {
                AppKitSheet().show(it.supportFragmentManager, "reown_appkit")
            }
        }
        Unit
    }
    if (showFeedback) {
        FeedbackScreen(onBack = { showFeedback = false })
        return
    }
    if (showSettings) {
        AppSettingsScreen(
            onBack = { showSettings = false },
            onOpenFeedback = { showFeedback = true },
            purchasePreviewEnabled = purchasePreviewEnabled,
            onPurchasePreviewEnabledChange = { enabled ->
                purchasePreviewEnabled = enabled
                navigationPreferences.edit().putBoolean("purchase_preview_enabled", enabled).apply()
            }
        )
        return
    }
    if (showHyperliquidStrategy) {
        StrategyScreen(
            purchasePreviewEnabled = purchasePreviewEnabled,
            onBack = { showHyperliquidStrategy = false },
        )
        return
    }

    Scaffold(
        containerColor = MaterialTheme.colorScheme.background,
        bottomBar = {
            NavigationBar(containerColor = palette.surface, tonalElevation = 0.dp) {
                mainDestinations().forEach { destination ->
                    val selected = selectedDestination == destination
                    NavigationBarItem(
                        selected = selected,
                        onClick = {
                            selectedDestination = destination
                            navigationPreferences.edit()
                                .putString("selected_main_destination", destination.storageKey)
                                .apply()
                        },
                        icon = { NavGlyph(destination.glyph, selected) },
                        label = { Text(destination.label, fontSize = 10.sp, fontWeight = if (selected) FontWeight.Bold else FontWeight.Medium) },
                        colors = NavigationBarItemDefaults.colors(
                            selectedIconColor = Color.White, selectedTextColor = palette.marketGreen,
                            indicatorColor = Color.Transparent, unselectedIconColor = mutedText,
                            unselectedTextColor = mutedText
                        )
                    )
                }
            }
        }
    ) { innerPadding ->
        Box(modifier = Modifier.padding(innerPadding)) {
            when (selectedDestination) {
                MainDestination.Mexc -> MexcAutoTradeScreen()
                MainDestination.Hyperliquid -> LivePositionsScreen(
                    onOpenWallet = openWallet,
                    onOpenStrategySettings = { showHyperliquidStrategy = true },
                    modifier = Modifier.fillMaxSize(),
                )
                MainDestination.Aster -> AsterScreen()
                MainDestination.Wallet -> WalletScreen(onOpenWallet = openWallet, onOpenSettings = { showSettings = true })
            }
        }
    }
}

@Composable private fun NavGlyph(glyph: String, selected: Boolean) {
    val palette = LocalTradeMentorColors.current
    Surface(
        color = if (selected) palette.electricBlue.copy(alpha = 0.2f) else palette.surfaceRaised,
        shape = RoundedCornerShape(11.dp),
        modifier = Modifier.padding(bottom = 1.dp)
    ) {
        Box(modifier = Modifier.padding(horizontal = 13.dp, vertical = 7.dp), contentAlignment = Alignment.Center) {
            Text(
                glyph,
                color = if (selected) Color.White else MaterialTheme.colorScheme.onSurfaceVariant,
                fontSize = 14.sp,
                fontWeight = FontWeight.ExtraBold
            )
        }
    }
}
