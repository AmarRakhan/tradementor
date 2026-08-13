package com.tradementor.app.scanner

import android.content.Context

object AddOnTradeStore {
    private const val PREFS = "add_on_trade_store"
    private const val KEY = "symbols"
    private fun canonicalSymbol(symbol: String) = DcaPulseGate.normalizedBaseSymbol(symbol)

    fun symbols(context: Context): Set<String> = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getStringSet(KEY, emptySet()).orEmpty().map { canonicalSymbol(it) }.toSet()

    fun hasAdded(context: Context, symbol: String): Boolean = canonicalSymbol(symbol) in symbols(context)

    fun markAdded(context: Context, symbol: String) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putStringSet(KEY, symbols(context) + canonicalSymbol(symbol)).apply()
    }

    fun retainOpen(context: Context, openSymbols: Set<String>) {
        val retained = symbols(context).intersect(openSymbols.map { it.uppercase() }.toSet())
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putStringSet(KEY, retained).apply()
    }
}
