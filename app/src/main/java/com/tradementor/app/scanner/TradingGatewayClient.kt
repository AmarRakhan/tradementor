package com.tradementor.app.scanner

import android.content.Context
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.google.gson.Gson
import com.tradementor.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import java.util.concurrent.TimeUnit

data class TradingGatewayHealth(
    val status: String = "unknown",
    val environment: String = "mainnet",
    val tradingEnabled: Boolean = false,
    val oneTestOrderArmed: Boolean = false,
    val activePositions: Int = 0,
    val remainingSlots: Int = 0,
    val agentWalletConfigured: Boolean = false,
    val agentWalletReason: String = "unknown",
    val agentAddressSuffix: String = ""
)

/** Keeps the last confirmed cloud status while Compose screens are recreated. */
object TradingGatewayHealthCache {
    @Volatile
    private var lastSuccessfulHealth: TradingGatewayHealth? = null

    fun get(): TradingGatewayHealth? = lastSuccessfulHealth

    fun put(health: TradingGatewayHealth) {
        lastSuccessfulHealth = health
    }
}

data class TradingGatewayExecution(
    val accepted: Boolean = false,
    val symbol: String = "",
    val short: Boolean = false,
    val filledSize: Double = 0.0,
    val fillPrice: Double = 0.0,
    val targetPrice: Double = 0.0,
    val stopPrice: Double = 0.0,
    val strategyId: String = ""
)

data class TradingGatewayCloseResult(val closed: Boolean = false, val symbol: String = "", val cancelledOrders: Int = 0)

data class TakeProfitCandidate(
    val symbol: String = "",
    val unrealizedPnl: Double = 0.0,
    val positionValueUsd: Double = 0.0,
    val safetyBufferUsd: Double = 0.0,
    val estimatedNetProfitUsd: Double = 0.0
)

data class TakeAllProfitsPreview(
    val eligible: List<TakeProfitCandidate> = emptyList(),
    val eligibleCount: Int = 0,
    val estimatedGrossProfitUsd: Double = 0.0,
    val estimatedNetProfitUsd: Double = 0.0
)

data class TakeAllProfitsResult(
    val closed: List<TakeProfitCandidate> = emptyList(),
    val failed: List<Map<String, String>> = emptyList(),
    val closedCount: Int = 0,
    val estimatedRealizedProfitUsd: Double = 0.0,
    val scannerEnabled: Boolean = false
)

data class TpProtectionResult(
    val positionsChecked: Int = 0,
    val alreadyProtected: List<String> = emptyList(),
    val repaired: List<String> = emptyList(),
    val closedAtTarget: List<String> = emptyList(),
    val failed: List<Map<String, String>> = emptyList(),
    val scanAndBuyEnabled: Boolean = false
)

object LocalTradingGatewayStore {
    private const val PREFS = "local_trading_gateway"
    private const val URL = "url"
    private const val TEST_TOKEN = "one_test_token"
    const val DEFAULT_URL = "https://tradementor-api-604335232956.europe-west4.run.app"

    fun url(context: Context): String = BuildConfig.CLOUD_API_URL.ifBlank {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(URL, DEFAULT_URL).orEmpty()
    }.trimEnd('/')
    fun saveUrl(context: Context, value: String) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit().putString(URL, value.trim().trimEnd('/')).apply()
    fun testToken(context: Context): String = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString(TEST_TOKEN, "").orEmpty().trim()
    fun saveTestToken(context: Context, value: String) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit().putString(TEST_TOKEN, value.trim()).apply()
    fun clearTestToken(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .edit().remove(TEST_TOKEN).apply()
}

class TradingGatewayClient {
    private val http = OkHttpClient.Builder()
        .connectTimeout(3, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()

    private fun authenticated(request: Request.Builder): Request {
        val user = FirebaseAuth.getInstance().currentUser ?: error("Log eerst in bij TradeMentor")
        val token = Tasks.await(user.getIdToken(false)).token ?: error("Cloudsessie ontbreekt")
        return request.header("Authorization", "Bearer $token").build()
    }

    suspend fun health(baseUrl: String): TradingGatewayHealth = withContext(Dispatchers.IO) {
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/trading/health").get())
        http.newCall(request).execute().use { response ->
            check(response.isSuccessful) { "Lokale handelsserver antwoordde met ${response.code}" }
            Gson().fromJson(response.body?.string().orEmpty(), TradingGatewayHealth::class.java)
        }
    }

    suspend fun executeOneTest(
        baseUrl: String,
        token: String,
        intent: HyperliquidOrderIntent,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        strategyId: String
    ): TradingGatewayExecution = withContext(Dispatchers.IO) {
        val payload = mapOf(
            "idempotency_key" to "entry-${intent.id}-${intent.symbol.uppercase()}",
            "symbol" to intent.symbol,
            "short" to intent.shortDirection,
            "position_value_usd" to intent.positionValueUsd,
            "leverage" to intent.leverage,
            "signal_price" to intent.entryPrice,
            "profit_percentage" to profitPercentage,
            "max_adverse_percentage" to maxAdversePercentage,
            "strategy_id" to strategyId
        )
        val request = Request.Builder()
            .url("$baseUrl/v1/me/orders/entry")
            .post(Gson().toJson(payload).toRequestBody("application/json".toMediaType()))
        val authenticatedRequest = authenticated(request)
        http.newCall(authenticatedRequest).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }.getOrDefault("Handelsserver antwoordde met ${response.code}") }
            Gson().fromJson(body, TradingGatewayExecution::class.java)
        }
    }

    suspend fun executeAddOn(
        baseUrl: String,
        token: String,
        intent: HyperliquidOrderIntent,
        profitPercentage: Double
    ): TradingGatewayExecution = withContext(Dispatchers.IO) {
        val payload = mapOf(
            "symbol" to intent.symbol,
            "short" to intent.shortDirection,
            "position_value_usd" to intent.positionValueUsd,
            "leverage" to intent.leverage,
            "signal_price" to intent.entryPrice,
            "profit_percentage" to profitPercentage
        )
        val request = Request.Builder()
            .url("$baseUrl/v1/me/positions/add-on")
            .post(Gson().toJson(payload).toRequestBody("application/json".toMediaType()))
        val authenticatedRequest = authenticated(request)
        http.newCall(authenticatedRequest).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }.getOrDefault("Bijkoop kon niet worden uitgevoerd") }
            Gson().fromJson(body, TradingGatewayExecution::class.java)
        }
    }

    suspend fun syncMaximum(baseUrl: String, token: String, maximum: Int) = withContext(Dispatchers.IO) {
        val payload = Gson().toJson(mapOf("max_active_positions" to maximum.coerceIn(1, 400)))
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/settings")
            .post(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }.getOrDefault("Limiet kon niet worden opgeslagen") }
        }
    }

    suspend fun setLiveTrading(baseUrl: String, enabled: Boolean) = withContext(Dispatchers.IO) {
        val payload = Gson().toJson(mapOf("enabled" to enabled))
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/execution/live")
            .put(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) {
                runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }
                    .getOrDefault("Scan & Buy kon niet worden bijgewerkt")
            }
        }
    }

    suspend fun previewTakeAllProfits(baseUrl: String): TakeAllProfitsPreview = withContext(Dispatchers.IO) {
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/positions/take-all-profits/preview").get())
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) {
                runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }
                    .getOrDefault("Winstposities konden niet veilig worden gecontroleerd")
            }
            Gson().fromJson(body, TakeAllProfitsPreview::class.java)
        }
    }

    suspend fun executeTakeAllProfits(baseUrl: String, operationId: String): TakeAllProfitsResult = withContext(Dispatchers.IO) {
        val payload = Gson().toJson(mapOf(
            "confirm" to true,
            "operation_id" to operationId,
            "minimum_net_profit_usd" to 0.05
        ))
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/positions/take-all-profits")
            .post(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) {
                runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }
                    .getOrDefault("Take All Profits kon niet veilig worden uitgevoerd")
            }
            Gson().fromJson(body, TakeAllProfitsResult::class.java)
        }
    }

    suspend fun protectOpenPositions(
        baseUrl: String,
        profitPercentage: Double,
        maxAdversePercentage: Double,
        strategyId: String
    ): TpProtectionResult = withContext(Dispatchers.IO) {
        val payload = Gson().toJson(mapOf(
            "profit_percentage" to profitPercentage,
            "max_adverse_percentage" to maxAdversePercentage,
            "strategy_id" to strategyId
        ))
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/positions/protect")
            .post(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) {
                runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }
                    .getOrDefault("Positiebescherming kon niet worden gecontroleerd")
            }
            Gson().fromJson(body, TpProtectionResult::class.java)
        }
    }

    suspend fun closePosition(baseUrl: String, token: String, symbol: String): TradingGatewayCloseResult = withContext(Dispatchers.IO) {
        val encoded = java.net.URLEncoder.encode(symbol, "UTF-8")
        val request = authenticated(Request.Builder().url("$baseUrl/v1/me/positions/$encoded/close")
            .post("{\"confirm\":true}".toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { runCatching { Gson().fromJson(body, Map::class.java)["detail"].toString() }.getOrDefault("Positie kon niet worden gesloten") }
            Gson().fromJson(body, TradingGatewayCloseResult::class.java)
        }
    }
}
