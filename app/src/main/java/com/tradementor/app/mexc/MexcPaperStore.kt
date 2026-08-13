package com.tradementor.app.mexc

import android.content.Context
import com.google.gson.Gson

object MexcPaperStore {
    private const val PREFS = "mexc_auto_trade"
    private const val SETTINGS = "settings_v3_test3"
    private const val SESSION = "session"
    private val gson = Gson()

    fun settings(context: Context): MexcSettings = MexcAdaptiveEngine.fixedProfile(runCatching {
        gson.fromJson(context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(SETTINGS,null),MexcSettings::class.java)
    }.getOrNull() ?: MexcSettings(strategyVersion = "hedge_dca_v3"))

    fun saveSettings(context: Context, value: MexcSettings) = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString(SETTINGS,gson.toJson(MexcAdaptiveEngine.fixedProfile(value))).apply()
    fun session(context: Context): MexcSession? = runCatching { gson.fromJson(context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString(SESSION,null),MexcSession::class.java) }.getOrNull()
    fun saveSession(context: Context, value: MexcSession) = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString(SESSION,gson.toJson(value)).apply()
    fun clearSession(context: Context) = context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().remove(SESSION).apply()
}
