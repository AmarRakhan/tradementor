package com.tradementor.app.scanner

import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.google.gson.Gson
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.UUID
import java.util.concurrent.TimeUnit

data class BitcoinSignal(val direction: String = "none", val confidence: Double = 0.0, val reason: String = "", val price: Double = 0.0, val durationSeconds: Int = 300)
data class BitcoinPrediction(val id: String = "", val direction: String = "none", val predictionPrice: Double = 0.0, val expiryPrice: Double = 0.0, val resultPercentage: Double = 0.0, val outcome: String? = null, val predictedAt: String? = null, val predictedAtEpochMs: Long = 0L)
data class BitcoinTrade(val id: String = "", val status: String = "", val short: Boolean = false, val stakeUsd: Double = 0.0, val entryPrice: Double = 0.0, val exitPrice: Double = 0.0, val resultPercentage: Double = 0.0, val realizedPnlUsdEstimate: Double = 0.0, val durationSeconds: Int = 0, val scheduledCloseAt: String? = null, val openedAt: String? = null, val closedAt: String? = null, val estimatedEntryFeeUsd: Double = 0.0)
data class BitcoinCasinoState(val currentPrice: Double = 0.0, val activeTrade: BitcoinTrade? = null, val trades: List<BitcoinTrade> = emptyList(), val predictions: List<BitcoinPrediction> = emptyList(), val resolvedPredictions: Int = 0, val wonPredictions: Int = 0, val lostPredictions: Int = 0, val successPercentage: Double = 0.0, val averageWinningPercentage: Double = 0.0, val minimumStakeUsd: Double = 10.0, val maximumStakeUsd: Double = 500.0)

class BitcoinCasinoClient {
    private val gson = Gson()
    private val http = OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(25, TimeUnit.SECONDS).build()
    private fun authenticated(builder: Request.Builder): Request {
        val user = FirebaseAuth.getInstance().currentUser ?: error("Log eerst in bij TradeMentor")
        val token = Tasks.await(user.getIdToken(false)).token ?: error("Cloudsessie ontbreekt")
        return builder.header("Authorization", "Bearer $token").build()
    }
    private fun message(body: String, fallback: String) = runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }.getOrDefault(fallback)
    suspend fun signal(baseUrl: String, seconds: Int): BitcoinSignal = post(baseUrl, "/v1/me/bitcoin/signal", mapOf("duration_seconds" to seconds))
    suspend fun state(baseUrl: String, seconds: Int): BitcoinCasinoState = withContext(Dispatchers.IO) {
        http.newCall(authenticated(Request.Builder().url("$baseUrl/v1/me/bitcoin/state?duration_seconds=$seconds").get())).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { message(body, "Bitcoin-status kon niet worden geladen") }
            gson.fromJson(body, BitcoinCasinoState::class.java)
        }
    }
    suspend fun open(baseUrl: String, seconds: Int, stake: Double, short: Boolean): BitcoinTrade = post(baseUrl, "/v1/me/bitcoin/trades", mapOf("duration_seconds" to seconds, "stake_usd" to stake, "short" to short, "confirm" to true, "idempotency_key" to "btc-${UUID.randomUUID()}"))
    suspend fun close(baseUrl: String, id: String): BitcoinTrade = post(baseUrl, "/v1/me/bitcoin/trades/$id/close", mapOf("confirm" to true))
    private suspend inline fun <reified T> post(baseUrl: String, path: String, payload: Any): T = withContext(Dispatchers.IO) {
        val request = authenticated(Request.Builder().url(baseUrl + path).post(gson.toJson(payload).toRequestBody(JSON)))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { message(body, "Bitcoin-server antwoordde met ${response.code}") }
            gson.fromJson(body, T::class.java)
        }
    }
    private companion object { val JSON = "application/json".toMediaType() }
}
