package com.tradementor.app.cloud

import android.os.Build
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
import java.util.concurrent.TimeUnit

data class FeedbackReport(
    val id: String = "",
    val userEmail: String = "",
    val category: String = "bug",
    val title: String = "",
    val description: String = "",
    val screen: String = "",
    val appVersion: String = "",
    val buildNumber: Int = 0,
    val deviceModel: String = "",
    val androidVersion: String = "",
    val status: String = "new",
    val adminNote: String = "",
    val createdAt: String = ""
)

private data class FeedbackListResponse(val reports: List<FeedbackReport> = emptyList())

class FeedbackRepository {
    private val gson = Gson()
    private val http = OkHttpClient.Builder()
        .connectTimeout(5, TimeUnit.SECONDS)
        .readTimeout(20, TimeUnit.SECONDS)
        .build()
    private val base = BuildConfig.CLOUD_API_URL.trimEnd('/')

    private fun authenticated(builder: Request.Builder): Request {
        val user = FirebaseAuth.getInstance().currentUser ?: error("Log eerst in bij TradeMentor.")
        val token = Tasks.await(user.getIdToken(false)).token ?: error("Cloudsessie ontbreekt.")
        return builder.header("Authorization", "Bearer $token").build()
    }

    private fun detail(body: String, fallback: String): String = runCatching {
        (gson.fromJson(body, Map::class.java)["detail"] as? String).orEmpty()
    }.getOrDefault("").ifBlank { fallback }

    suspend fun submit(category: String, title: String, description: String, screen: String) = withContext(Dispatchers.IO) {
        val payload = gson.toJson(mapOf(
            "category" to category,
            "title" to title.trim(),
            "description" to description.trim(),
            "screen" to screen.trim(),
            "app_version" to BuildConfig.VERSION_NAME,
            "build_number" to BuildConfig.VERSION_CODE,
            "device_model" to "${Build.MANUFACTURER} ${Build.MODEL}".trim(),
            "android_version" to "Android ${Build.VERSION.RELEASE} (SDK ${Build.VERSION.SDK_INT})"
        ))
        val request = authenticated(Request.Builder().url("$base/v1/me/feedback")
            .post(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { detail(body, "Melding kon niet worden verzonden (${response.code}).") }
        }
    }

    suspend fun listMine(): List<FeedbackReport> = list("$base/v1/me/feedback")

    suspend fun listAdmin(): List<FeedbackReport> = list("$base/v1/admin/feedback")

    private suspend fun list(url: String): List<FeedbackReport> = withContext(Dispatchers.IO) {
        val request = authenticated(Request.Builder().url(url).get())
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { detail(body, "Feedback kon niet worden geladen (${response.code}).") }
            gson.fromJson(body, FeedbackListResponse::class.java).reports
        }
    }

    suspend fun updateStatus(id: String, status: String, note: String = "") = withContext(Dispatchers.IO) {
        val payload = gson.toJson(mapOf("status" to status, "admin_note" to note.trim()))
        val request = authenticated(Request.Builder().url("$base/v1/admin/feedback/$id")
            .put(payload.toRequestBody("application/json".toMediaType())))
        http.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) { detail(body, "Status kon niet worden bijgewerkt (${response.code}).") }
        }
    }
}
