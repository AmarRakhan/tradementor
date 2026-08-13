package com.tradementor.app.cloud

import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.tradementor.app.BuildConfig
import com.tradementor.app.mexc.MexcSettings
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

data class MexcCloudPosition(
    val positionId: String = "",
    val symbol: String = "",
    val side: String = "",
    val isolated: Boolean = true,
    val volume: Double = 0.0,
    val contractSize: Double = 0.0,
    val entryPrice: Double = 0.0,
    val markPrice: Double = 0.0,
    val notionalUsd: Double = 0.0,
    val marginUsd: Double = 0.0,
    val unrealizedPnl: Double = 0.0,
    val realizedPnl: Double = 0.0,
    val funding: Double = 0.0,
    val liquidationPrice: Double = 0.0,
    val leverage: Int = 1,
    val maintenanceMarginRate: Double = 0.0,
    val liquidationFeeRate: Double = 0.0,
    val maintenanceMarginUsd: Double = 0.0,
    val marginRatioPercent: Double = 0.0,
)

data class MexcCloudStatus(
    val configured: Boolean = false,
    val credentialsVerified: Boolean = false,
    val hedgeMode: Boolean = false,
    val positionMode: Int = 0,
    val equity: Double = 0.0,
    val availableBalance: Double = 0.0,
    val availableOpen: Double = 0.0,
    val positionMargin: Double = 0.0,
    val unrealizedPnl: Double = 0.0,
    val openBtcPositions: Int = 0,
    val openBtcOrders: Int = 0,
    val positions: List<MexcCloudPosition> = emptyList(),
    val makerFee: Double = 0.0,
    val takerFee: Double = 0.0,
    val maximumLeverage: Int = 0,
    val executionLeverage: Int = 0,
    val executionMarginMode: String = "",
    val automationExecutionEnabled: Boolean = false,
    val liveReady: Boolean = false,
    val liveEnabled: Boolean = false,
    val ordersEnabled: Boolean = false,
    val keySuffix: String = "",
    val automationEnabled: Boolean = false,
    val automationMonitoring: Boolean = false,
    val automationProtectiveOnly: Boolean = false,
    val automationPhase: String = "WAIT",
    val automationReason: String = "",
    val automationLastAction: String = "HOLD",
    val automationPaused: Boolean = false,
    val automationPauseReason: String = "",
    val automationSessionStartEquity: Double = 0.0,
    val automationDcaCount: Int = 0,
    val automationRiskScore: Int = 0,
    val automationRecoveryScore: Int = 0,
    val automationNetSessionPnl: Double = 0.0,
    val automationMarginRatioPercent: Double = 0.0,
    val automationLiquidationDistancePercent: Double = 0.0,
    val automationFees: Double = 0.0,
    val automationRealizedPnl: Double = 0.0,
    val automationStrategyVersion: String = "hedge_dca_v3",
    val automationLongDcaCount: Int = 0,
    val automationShortDcaCount: Int = 0,
    val automationFrozen: Boolean = false,
    val automationRescueState: String = "",
)

data class MexcAutomationResult(
    val started: Boolean = false,
    val stopped: Boolean = false,
    val automationEnabled: Boolean = false,
    val automationMonitoring: Boolean = false,
    val automationProtectiveOnly: Boolean = false,
    val automationPhase: String = "WAIT",
    val automationReason: String = "",
    val automationPaused: Boolean = false,
    val automationPauseReason: String = "",
)

data class MexcCanaryResult(
    val status: String = "",
    val orderId: String = "",
    val symbol: String = "",
    val side: String = "",
    val volume: Double = 0.0,
    val actualNotionalUsd: Double = 0.0,
    val maximumNotionalUsd: Double = 0.0,
    val leverage: Int = 0,
    val replayed: Boolean = false,
)

data class MexcSimulationResult(
    val status: String = "",
    val strategyVersion: String = "",
    val action: String = "HOLD",
    val side: String = "",
    val reason: String = "",
    val targetNotional: Double = 0.0,
    val targetQuantity: Double = 0.0,
)

object MexcCloudClient {
    private val gson = Gson()
    private val http = OkHttpClient()
    private val jsonType = "application/json".toMediaType()

    suspend fun status(): MexcCloudStatus = request("GET", "/v1/me/mexc/status")

    suspend fun connect(apiKey: String, secretKey: String): MexcCloudStatus = request(
        "PUT",
        "/v1/me/mexc/credentials",
        gson.toJson(mapOf("api_key" to apiKey, "secret_key" to secretKey)),
    )

    suspend fun setLive(enabled: Boolean, confirm: Boolean): MexcCloudStatus = request(
        "PUT",
        "/v1/me/mexc/live",
        gson.toJson(mapOf("enabled" to enabled, "confirm" to confirm)),
    )

    suspend fun placeCanary(idempotencyKey: String, leverage: Int): MexcCanaryResult = request(
        "POST",
        "/v1/me/mexc/canary",
        gson.toJson(mapOf(
            "confirm" to true,
            "idempotency_key" to idempotencyKey,
            "maximum_notional_usd" to 8.50,
            "leverage" to leverage.coerceIn(1, 200),
        )),
    )

    private fun v3Settings(settings: MexcSettings) = mapOf(
        "strategyVersion" to "hedge_dca_v3",
        "mode" to settings.mode.name.lowercase(),
        "tradingPair" to "BTC_USDT",
        "leverage" to 200,
        "marginMode" to "cross",
        "initialOrderNotional" to settings.initialOrderNotional,
        "takeProfit" to settings.takeProfit,
        "maximumDcaOrders" to settings.maximumDcaOrders,
        "dcaTimeframe" to settings.executionTimeframe,
        "dcaSpacing" to settings.dcaSpacing,
        "hedgeEnabled" to settings.hedgeEnabled,
        "emergencyHedgeEnabled" to settings.emergencyHedgeEnabled,
        "emergencyEquityTrigger" to settings.emergencyEquityTrigger,
        "emergencyHedgeRatio" to settings.emergencyHedgeRatio,
        "rescueEnabled" to settings.rescueEnabled,
        "rescueOrderNotional" to settings.rescueOrderNotional,
        "rescueTakeProfit" to settings.rescueTakeProfit,
        "maxFrozenCycles" to settings.maxFrozenCycles,
        "classicStopLoss" to false,
        "minimumAvailableBuffer" to settings.minimumAvailableBuffer,
        "maximumMarginRatio" to settings.maximumMarginRatio,
        "minimumLiquidationDistance" to settings.minimumLiquidationDistance,
        "assumedTakerFee" to settings.takerFee,
        "rescueRequiresIndependentAccount" to true,
    )

    suspend fun startAutomation(settings: MexcSettings): MexcAutomationResult = request(
        "POST", "/v1/me/mexc/automation/start",
        gson.toJson(mapOf("confirm" to true, "settings" to v3Settings(settings))),
    )

    suspend fun simulateAutomation(settings: MexcSettings): MexcSimulationResult = request(
        "POST", "/v1/me/mexc/automation/simulate",
        gson.toJson(mapOf("settings" to v3Settings(settings.copy(mode = com.tradementor.app.mexc.MexcMode.PAPER)))),
    )

    suspend fun stopAutomation(): MexcAutomationResult = request(
        "POST", "/v1/me/mexc/automation/stop", gson.toJson(mapOf("confirm" to true)),
    )

    private suspend inline fun <reified T> request(method: String, path: String, json: String? = null): T =
        withContext(Dispatchers.IO) {
            val user = FirebaseAuth.getInstance().currentUser ?: error("Log eerst in bij TradeMentor.")
            val token = Tasks.await(user.getIdToken(false)).token ?: error("Cloudsessie ontbreekt.")
            val builder = Request.Builder()
                .url("${BuildConfig.CLOUD_API_URL.trimEnd('/')}$path")
                .header("Authorization", "Bearer $token")
            when (method) {
                "GET" -> builder.get()
                "PUT" -> builder.put((json ?: "{}").toRequestBody(jsonType))
                "POST" -> builder.post((json ?: "{}").toRequestBody(jsonType))
                else -> error("Niet-ondersteunde cloudmethode")
            }
            http.newCall(builder.build()).execute().use { response ->
                val body = response.body?.string().orEmpty()
                if (!response.isSuccessful) {
                    val detail = runCatching { gson.fromJson(body, JsonObject::class.java)["detail"]?.asString }.getOrNull()
                    error(detail ?: "MEXC-cloudcontrole antwoordde met ${response.code}.")
                }
                gson.fromJson(body, T::class.java)
            }
        }
}
