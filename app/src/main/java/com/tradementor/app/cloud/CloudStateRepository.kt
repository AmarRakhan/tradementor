package com.tradementor.app.cloud

import android.content.Context
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.google.gson.reflect.TypeToken
import com.tradementor.app.BuildConfig
import com.tradementor.app.scanner.BackgroundScanConfig
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.SignalExecutionSettings
import com.tradementor.app.scanner.SignalExecutionSettingsStore
import com.tradementor.app.scanner.TrackedTrade
import com.tradementor.app.scanner.TradeHistoryStore
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

object CloudStateRepository {
    private val gson = Gson()
    private val http = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(30, TimeUnit.SECONDS).build()
    private val tradeListType = object : TypeToken<List<TrackedTrade>>() {}.type

    suspend fun synchronize(context: Context) = withContext(Dispatchers.IO) {
        val user = FirebaseAuth.getInstance().currentUser ?: return@withContext
        val token = Tasks.await(user.getIdToken(false)).token ?: return@withContext
        val base = BuildConfig.CLOUD_API_URL.trimEnd('/')

        val cloud = runCatching {
            val request = Request.Builder().url("$base/v1/me/state").header("Authorization", "Bearer $token").get().build()
            http.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "Cloudstatus kon niet worden gelezen (${response.code})" }
                gson.fromJson(response.body?.string().orEmpty(), JsonObject::class.java)
            }
        }.getOrNull()

        val localTrades = TradeHistoryStore.load(context)
        val cloudTrades = cloud?.getAsJsonArray("trades")?.let { array ->
            runCatching { gson.fromJson<List<TrackedTrade>>(array, tradeListType) }.getOrNull()
        }.orEmpty()
        val mergedTrades = (localTrades + cloudTrades).groupBy { it.id }.map { (_, versions) ->
            versions.maxBy { it.closedAt ?: it.adviceUpdatedAt ?: it.startedAt }
        }.sortedByDescending { it.startedAt }
        if (mergedTrades != localTrades) TradeHistoryStore.save(context, mergedTrades)

        cloud?.getAsJsonObject("scanner")?.takeIf { it.size() > 0 }?.let { scannerJson ->
            runCatching { gson.fromJson(scannerJson, BackgroundScanConfig::class.java) }.getOrNull()?.let {
                BackgroundScannerScheduler.update(context, it)
            }
        }
        cloud?.getAsJsonObject("tradingSettings")?.let { settingsJson ->
            val current = SignalExecutionSettingsStore.load(context)
            val size = settingsJson.get("positionSizeUsd")?.asDouble ?: current.positionSizeUsd
            val maximum = settingsJson.get("maxActiveTrades")?.asInt
                ?: settingsJson.get("maxActivePositions")?.asInt ?: current.maxActiveTrades
            SignalExecutionSettingsStore.save(context, SignalExecutionSettings(size, maximum.coerceIn(1, 400)))
        }

        val scanner = BackgroundScannerScheduler.load(context)
        val trading = SignalExecutionSettingsStore.load(context)
        val payload = mapOf(
            "scanner" to (scanner ?: emptyMap<String, Any>()),
            "trading_settings" to mapOf(
                "positionSizeUsd" to trading.positionSizeUsd,
                "maxActiveTrades" to trading.maxActiveTrades,
                "maxActivePositions" to trading.maxActiveTrades
            ),
            "trades" to mergedTrades
        )
        val request = Request.Builder().url("$base/v1/me/state").header("Authorization", "Bearer $token")
            .put(gson.toJson(payload).toRequestBody("application/json".toMediaType())).build()
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Cloudstatus kon niet worden opgeslagen (${response.code})" }
        }
    }
}
