package com.tradementor.app.ui.theme

import android.app.Activity
import android.os.Build
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.darkColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.platform.LocalContext

val LocalTradeMentorColors = staticCompositionLocalOf { TradeMentor2027Colors }

private fun colorScheme(colors: TradeMentorBrandColors) = darkColorScheme(
    primary = colors.electricBlue,
    onPrimary = Color.White,
    secondary = colors.marketGreen,
    onSecondary = colors.background,
    tertiary = colors.riskRed,
    background = colors.background,
    onBackground = colors.primaryText,
    surface = colors.surface,
    onSurface = colors.primaryText,
    surfaceVariant = colors.surfaceRaised,
    onSurfaceVariant = colors.secondaryText,
    outline = colors.divider,
    error = colors.riskRed
)

@Composable
fun TradeMentorTheme(
    style: TradeMentorThemeStyle = TradeMentorThemeStyle.TradeMentor2027,
    content: @Composable () -> Unit
) {
    val colors = when (style) {
        TradeMentorThemeStyle.TradeMentor2027 -> TradeMentor2027Colors
    }
    val context = LocalContext.current
    val activity = context as? Activity

    activity?.window?.apply {
        statusBarColor = colors.background.toArgb()
        navigationBarColor = colors.background.toArgb()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            isStatusBarContrastEnforced = false
            isNavigationBarContrastEnforced = false
        }
    }

    CompositionLocalProvider(LocalTradeMentorColors provides colors) {
        MaterialTheme(
            colorScheme = colorScheme(colors),
            typography = Typography,
            content = content
        )
    }
}
