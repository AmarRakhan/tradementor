package com.tradementor.app.cloud

import android.content.Context
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.google.gson.Gson
import com.tradementor.app.BuildConfig
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody

object CloudOrderSafetyRepository {
    private val http = OkHttpClient()
    private val gson = Gson()

    suspend fun verifyIdempotency(context: Context) = withContext(Dispatchers.IO) {
        val prefs = context.getSharedPreferences("cloud_migration_checks", Context.MODE_PRIVATE)
        val user = FirebaseAuth.getInstance().currentUser ?: return@withContext
        val token = Tasks.await(user.getIdToken(false)).token ?: return@withContext
        if (!prefs.getBoolean("signature_preflight_v1_passed", false)) {
            val preflightRequest = Request.Builder().url("${BuildConfig.CLOUD_API_URL.trimEnd('/')}/v1/me/execution/preflight")
                .header("Authorization", "Bearer $token").get().build()
            val preflight = http.newCall(preflightRequest).execute().use { response ->
                check(response.isSuccessful) { "Ondertekenpreflight antwoordde met ${response.code}" }
                gson.fromJson(response.body?.string().orEmpty(), Map::class.java)
            }
            val passed = preflight["ready"] == true && preflight["dryRun"] == true &&
                preflight["signatureVerified"] == true && preflight["ordersEnabled"] == false
            prefs.edit().putBoolean("signature_preflight_v1_passed", passed).apply()
            check(passed) { "Agentwallet-preflight is niet veilig geslaagd" }
        }
        if (prefs.getBoolean("idempotency_v1_passed", false)) return@withContext
        val payload = gson.toJson(mapOf(
            "idempotency_key" to "migration-idempotency-probe-v1",
            "symbol" to "TM-MIGRATION-PROBE",
            "kind" to "close",
            "short" to false,
            "position_value_usd" to 0,
            "leverage" to 1,
            "signal_price" to 0,
            "profit_percentage" to 0
        ))
        fun send(): Map<*, *> {
            val request = Request.Builder().url("${BuildConfig.CLOUD_API_URL.trimEnd('/')}/v1/me/order-intents")
                .header("Authorization", "Bearer $token")
                .post(payload.toRequestBody("application/json".toMediaType())).build()
            return http.newCall(request).execute().use { response ->
                check(response.isSuccessful) { "Idempotentietest antwoordde met ${response.code}" }
                gson.fromJson(response.body?.string().orEmpty(), Map::class.java)
            }
        }
        val first = send()
        val second = send()
        val sameId = first["intentId"] == second["intentId"]
        val duplicateConfirmed = second["duplicate"] == true
        prefs.edit()
            .putBoolean("idempotency_v1_passed", sameId && duplicateConfirmed)
            .putBoolean("orders_remained_disabled", first["ordersEnabled"] == false && second["ordersEnabled"] == false)
            .apply()
        check(sameId && duplicateConfirmed) { "Dubbele-orderbeveiliging gaf geen stabiel resultaat" }
    }
}
