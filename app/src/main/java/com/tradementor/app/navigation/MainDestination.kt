package com.tradementor.app.navigation

enum class MainDestination(
    val storageKey: String,
    val label: String,
    val glyph: String,
) {
    Mexc("mexc", "MEXC", "MX"),
    Hyperliquid("hyperliquid", "HYPERLIQUID", "HL"),
    Aster("aster", "ASTER", "A"),
    Wallet("wallet", "WALLET", "W"),
}

fun mainDestinations(): List<MainDestination> = listOf(
    MainDestination.Mexc,
    MainDestination.Hyperliquid,
    MainDestination.Aster,
    MainDestination.Wallet,
)

fun restoreMainDestination(value: String?): MainDestination =
    mainDestinations().firstOrNull { it.storageKey == value } ?: MainDestination.Hyperliquid
