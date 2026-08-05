package com.tradementor.app.ui.theme

import androidx.compose.ui.graphics.Color

enum class TradeMentorThemeStyle {
    TradeMentor2027
}

data class TradeMentorBrandColors(
    val background: Color,
    val surface: Color,
    val surfaceRaised: Color,
    val electricBlue: Color,
    val marketGreen: Color,
    val riskRed: Color,
    val primaryText: Color,
    val secondaryText: Color,
    val divider: Color
)

val TradeMentor2027Colors = TradeMentorBrandColors(
    background = Color(0xFF05070B),
    surface = Color(0xFF0B1220),
    surfaceRaised = Color(0xFF121A2A),
    electricBlue = Color(0xFF2F68FF),
    marketGreen = Color(0xFF08C887),
    riskRed = Color(0xFFFF4964),
    primaryText = Color(0xFFF5F7FB),
    secondaryText = Color(0xFF8C92A3),
    divider = Color(0xFF232A38)
)
