package com.tradementor.app.cloud

import com.tradementor.app.BuildConfig
import com.google.firebase.auth.FirebaseAuth
import com.google.firebase.firestore.FieldValue
import com.google.firebase.firestore.FirebaseFirestore
import com.google.android.gms.tasks.Tasks
import okhttp3.Call
import okhttp3.Callback
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.RequestBody.Companion.toRequestBody
import okhttp3.Response
import com.google.gson.Gson
import java.io.IOException

object CloudAccountRepository {
    private val auth: FirebaseAuth get() = FirebaseAuth.getInstance()
    private val firestore: FirebaseFirestore get() = FirebaseFirestore.getInstance()
    private val httpClient = OkHttpClient()
    private val emptyJson = "{}".toRequestBody("application/json".toMediaType())

    fun currentSession(): CloudUserSession? = auth.currentUser?.let {
        CloudUserSession(uid = it.uid, email = it.email)
    }

    fun register(
        email: String,
        password: String,
        displayName: String,
        onResult: (Result<CloudUserSession>) -> Unit
    ) {
        auth.createUserWithEmailAndPassword(email.trim(), password)
            .addOnSuccessListener { result ->
                val user = result.user ?: return@addOnSuccessListener onResult(
                    Result.failure(IllegalStateException("Firebase heeft geen gebruiker teruggegeven."))
                )
                val profile = mapOf(
                    "createdAt" to FieldValue.serverTimestamp(),
                    "updatedAt" to FieldValue.serverTimestamp(),
                    "displayName" to displayName.trim(),
                    "schemaVersion" to 1
                )
                firestore.collection("users").document(user.uid).set(profile)
                    .addOnSuccessListener {
                        user.sendEmailVerification()
                        bootstrapCloudSession()
                        onResult(Result.success(CloudUserSession(user.uid, user.email)))
                    }
                    .addOnFailureListener { error ->
                        user.delete()
                        onResult(Result.failure(error))
                    }
            }
            .addOnFailureListener { onResult(Result.failure(it)) }
    }

    fun signIn(email: String, password: String, onResult: (Result<CloudUserSession>) -> Unit) {
        auth.signInWithEmailAndPassword(email.trim(), password)
            .addOnSuccessListener { result ->
                val user = result.user
                if (user == null) onResult(Result.failure(IllegalStateException("Aanmelden is niet voltooid.")))
                else {
                    bootstrapCloudSession()
                    onResult(Result.success(CloudUserSession(user.uid, user.email)))
                }
            }
            .addOnFailureListener { onResult(Result.failure(it)) }
    }

    fun sendPasswordReset(email: String, onResult: (Result<Unit>) -> Unit) {
        auth.sendPasswordResetEmail(email.trim())
            .addOnSuccessListener { onResult(Result.success(Unit)) }
            .addOnFailureListener { onResult(Result.failure(it)) }
    }

    fun signOut() = auth.signOut()

    /**
     * Meldt de ingelogde gebruiker veilig aan bij de cloud-API. Dit is bewust
     * best-effort: een tijdelijke cold start mag de gebruiker niet uitloggen.
     */
    fun bootstrapCloudSession() {
        val user = auth.currentUser ?: return
        val baseUrl = BuildConfig.CLOUD_API_URL.trimEnd('/')
        if (baseUrl.isBlank()) return
        user.getIdToken(false).addOnSuccessListener { result ->
            val token = result.token ?: return@addOnSuccessListener
            val request = Request.Builder()
                .url("$baseUrl/v1/me/bootstrap")
                .header("Authorization", "Bearer $token")
                .post(emptyJson)
                .build()
            httpClient.newCall(request).enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) = Unit
                override fun onResponse(call: Call, response: Response) = response.close()
            })
        }
    }

    fun linkWallet(address: String, onResult: (Result<Unit>) -> Unit = {}) {
        val user = auth.currentUser ?: return onResult(Result.failure(IllegalStateException("Log eerst in.")))
        val normalized = address.trim().lowercase()
        val baseUrl = BuildConfig.CLOUD_API_URL.trimEnd('/')
        if (baseUrl.isBlank()) return onResult(Result.failure(IllegalStateException("Cloudserver ontbreekt.")))
        user.getIdToken(false)
            .addOnFailureListener { onResult(Result.failure(it)) }
            .addOnSuccessListener { result ->
                val token = result.token ?: return@addOnSuccessListener onResult(Result.failure(IllegalStateException("Cloudsessie ontbreekt.")))
                val json = "{\"address\":\"$normalized\"}".toRequestBody("application/json".toMediaType())
                val request = Request.Builder()
                    .url("$baseUrl/v1/me/wallet")
                    .header("Authorization", "Bearer $token")
                    .put(json)
                    .build()
                httpClient.newCall(request).enqueue(object : Callback {
                    override fun onFailure(call: Call, e: IOException) = onResult(Result.failure(e))
                    override fun onResponse(call: Call, response: Response) {
                        response.use {
                            if (it.isSuccessful) onResult(Result.success(Unit))
                            else {
                                val body = it.body?.string().orEmpty()
                                val detail = runCatching {
                                    Gson().fromJson(body, Map::class.java)["detail"]?.toString()
                                }.getOrNull()
                                onResult(Result.failure(IllegalStateException(
                                    detail ?: "Walletkoppeling antwoordde met ${it.code}."
                                )))
                            }
                        }
                    }
                })
        }
    }

    /** Called only from the background thread after MetaMask approved Mainnet. */
    fun provisionAgentBlocking(privateKey: String, agentAddress: String) {
        val user = auth.currentUser ?: error("Log eerst in bij TradeMentor.")
        val token = Tasks.await(user.getIdToken(false)).token ?: error("Cloudsessie ontbreekt.")
        val payload = Gson().toJson(mapOf(
            "private_key" to privateKey.removePrefix("0x"),
            "agent_address" to agentAddress.lowercase()
        )).toRequestBody("application/json".toMediaType())
        val request = Request.Builder()
            .url("${BuildConfig.CLOUD_API_URL.trimEnd('/')}/v1/me/agent/provision")
            .header("Authorization", "Bearer $token")
            .post(payload)
            .build()
        httpClient.newCall(request).execute().use { response ->
            val body = response.body?.string().orEmpty()
            check(response.isSuccessful) {
                runCatching { Gson().fromJson(body, Map::class.java)["detail"]?.toString() }
                    .getOrNull() ?: "Cloud-handelswallet kon niet worden opgeslagen (${response.code})."
            }
        }
    }

}
