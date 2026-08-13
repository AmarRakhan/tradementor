package com.tradementor.app.ui.theme

import androidx.compose.ui.graphics.Color

enum class TradeMentorThemeStyle {
    TradeMentor2027
}

data class TradeMentorBrandColors(
    val background: Color,
    val surface: Color,
    val surfaceRaised: Color,
    val surfaceGradientStart: Color,
    val surfaceGradientEnd: Color,
    val panel: Color,
    val panelOutline: Color,
    val electricBlue: Color,
    val marketGreen: Color,
    val riskRed: Color,
    val warning: Color,
    val primaryText: Color,
    val secondaryText: Color,
    val divider: Color
)

val TradeMentor2027Colors = TradeMentorBrandColors(
    background = Color(0xFF070A12),
    surface = Color(0xFF111B2F),
    surfaceRaised = Color(0xFF17243D),
    surfaceGradientStart = Color(0xFF0D1320),
    surfaceGradientEnd = Color(0xFF111B2F),
    panel = Color(0xFF0F1A2E),
    panelOutline = Color(0xFF23324E),
    electricBlue = Color(0xFF597DFF),
    marketGreen = Color(0xFF2AE29B),
    riskRed = Color(0xFFFF5778),
    warning = Color(0xFFF3B14A),
    primaryText = Color(0xFFF7F9FF),
    secondaryText = Color(0xFFA2B0C6),
    divider = Color(0xFF26324A)
)
