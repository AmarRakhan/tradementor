package com.tradementor.app.security

import android.content.Context
import android.content.ComponentName
import android.content.Intent
import com.google.gson.Gson
import com.google.gson.JsonObject
import com.reown.appkit.client.AppKit
import com.reown.appkit.client.Modal
import com.reown.appkit.client.models.request.Request
import com.reown.appkit.client.models.request.SentRequestResult
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import okhttp3.MediaType.Companion.toMediaType
import okhttp3.OkHttpClient
import okhttp3.RequestBody.Companion.toRequestBody
import org.web3j.crypto.Keys
import com.tradementor.app.cloud.CloudAccountRepository

object MetaMaskAgentApproval {
    private const val SIGN_METHOD = "eth_signTypedData"
    private var pending: ((Result<String>) -> Unit)? = null
    private var pendingContext: Context? = null
    private var nonce: Long = 0L
    private const val AGENT_NAME = "TradeMentor Cloud"

    fun start(context: Context, callback: (Result<String>) -> Unit) {
        val activeAccount = AppKit.getAccount()
        val account = activeAccount?.address.orEmpty()
        if (!account.matches(Regex("^0x[0-9a-fA-F]{40}$"))) {
            callback(Result.failure(IllegalStateException("Koppel eerst MetaMask.")))
            return
        }
        val pair = Keys.createEcKeyPair()
        val privateKey = pair.privateKey.toString(16).padStart(64, '0')
        val agentAddress = "0x${Keys.getAddress(pair)}"
        ApiWalletVault.save(context, agentAddress, privateKey)
        ApiWalletVault.setApproved(context, false)
        nonce = System.currentTimeMillis()
        pending = callback
        pendingContext = context.applicationContext
        val typedData = typedData(agentAddress, nonce)
        val params = Gson().toJson(listOf(account.lowercase(), typedData))
        val sessionChainId = activeAccount?.chain?.let { "${it.chainNamespace}:${it.chainReference}" }
            ?: "eip155:1"
        AppKit.request(
            Request(method = SIGN_METHOD, params = params, chainId = sessionChainId, expiry = null),
            onSuccess = { _: SentRequestResult ->
                val launchIntent = context.packageManager.getLaunchIntentForPackage("io.metamask")
                    ?: return@request finish(Result.failure(IllegalStateException("MetaMask is niet geïnstalleerd.")))
                launchIntent.component = ComponentName("io.metamask", "io.metamask.MainActivity")
                launchIntent.addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP)
                context.startActivity(launchIntent)
            },
            onError = { error: Throwable -> finish(Result.failure(error)) }
        )
    }

    fun handleResponse(response: Modal.Model.SessionRequestResponse) {
        if (response.method != SIGN_METHOD || pending == null) return
        when (val result = response.result) {
            is Modal.Model.JsonRpcResponse.JsonRpcResult -> {
                val signature = result.result?.toString().orEmpty()
                val context = pendingContext ?: return finish(Result.failure(IllegalStateException("Appcontext ontbreekt")))
                CoroutineScope(Dispatchers.IO).launch {
                    finish(runCatching { registerAgent(context, signature) })
                }
            }
            is Modal.Model.JsonRpcResponse.JsonRpcError -> finish(Result.failure(IllegalStateException(result.message)))
        }
    }

    fun fail(message: String) { if (pending != null) finish(Result.failure(IllegalStateException(message))) }

    private fun registerAgent(context: Context, signature: String): String {
        val clean = signature.removePrefix("0x")
        require(clean.length == 130) { "MetaMask gaf geen geldige ondertekening terug." }
        val vRaw = clean.substring(128, 130).toInt(16)
        val body = mapOf(
            "action" to mapOf("type" to "approveAgent", "agentAddress" to ApiWalletVault.address(context), "agentName" to AGENT_NAME, "nonce" to nonce),
            "nonce" to nonce,
            "signature" to mapOf("r" to "0x${clean.substring(0, 64)}", "s" to "0x${clean.substring(64, 128)}", "v" to if (vRaw < 27) vRaw + 27 else vRaw),
            "vaultAddress" to null
        )
        val request = okhttp3.Request.Builder().url("https://api.hyperliquid.xyz/exchange")
            .post(Gson().toJson(body).toRequestBody("application/json".toMediaType())).build()
        OkHttpClient().newCall(request).execute().use { response ->
            val text = response.body?.string().orEmpty()
            check(response.isSuccessful && text.contains("\"status\":\"ok\"")) { "Hyperliquid weigerde de API-wallet: $text" }
        }
        CloudAccountRepository.provisionAgentBlocking(
            ApiWalletVault.privateKey(context),
            ApiWalletVault.address(context)
        )
        ApiWalletVault.setApproved(context, true)
        return ApiWalletVault.address(context)
    }

    private fun typedData(agentAddress: String, time: Long): JsonObject = Gson().toJsonTree(mapOf(
        "domain" to mapOf("name" to "HyperliquidSignTransaction", "version" to "1", "chainId" to 42161, "verifyingContract" to "0x0000000000000000000000000000000000000000"),
        "types" to mapOf(
            "HyperliquidTransaction:ApproveAgent" to listOf(
                mapOf("name" to "hyperliquidChain", "type" to "string"), mapOf("name" to "agentAddress", "type" to "address"),
                mapOf("name" to "agentName", "type" to "string"), mapOf("name" to "nonce", "type" to "uint64")
            ),
            "EIP712Domain" to listOf(
                mapOf("name" to "name", "type" to "string"), mapOf("name" to "version", "type" to "string"),
                mapOf("name" to "chainId", "type" to "uint256"), mapOf("name" to "verifyingContract", "type" to "address")
            )
        ),
        "primaryType" to "HyperliquidTransaction:ApproveAgent",
        "message" to mapOf("hyperliquidChain" to "Mainnet", "signatureChainId" to "0xa4b1", "agentAddress" to agentAddress, "agentName" to AGENT_NAME, "nonce" to time)
    )).asJsonObject

    @Synchronized private fun finish(result: Result<String>) {
        val callback = pending
        pending = null
        pendingContext = null
        callback?.invoke(result)
    }
}
