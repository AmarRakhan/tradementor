package com.tradementor.app.repository

import com.tradementor.app.api.ClearinghouseStateRequest
import com.tradementor.app.api.HyperliquidAccountState
import com.tradementor.app.api.CloudWalletApi
import com.tradementor.app.BuildConfig
import com.google.android.gms.tasks.Tasks
import com.google.firebase.auth.FirebaseAuth
import com.tradementor.app.api.HyperliquidFill
import com.tradementor.app.api.HyperliquidOpenOrder
import com.tradementor.app.api.HyperliquidSpotBalance
import com.tradementor.app.api.InfoTypeRequest
import com.tradementor.app.api.UserInfoRequest
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.awaitAll
import kotlinx.coroutines.delay
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

data class WalletOverview(
    val account: HyperliquidAccountState,
    val openOrders: List<HyperliquidOpenOrder>,
    val recentFills: List<HyperliquidFill>,
    val accountMode: String,
    val portfolioValue: Double,
    val availableToTrade: Double,
    val spotBalances: List<HyperliquidSpotBalance>
)

object WalletOverviewCache {
    @Volatile private var address: String = ""
    @Volatile private var overview: WalletOverview? = null

    fun get(walletAddress: String): WalletOverview? =
        overview?.takeIf { address.equals(walletAddress, ignoreCase = true) }

    fun put(walletAddress: String, value: WalletOverview) {
        address = walletAddress
        overview = value
    }

    fun clear() {
        address = ""
        overview = null
    }
}

class WalletRepository {
    private var lastOverview: WalletOverview? = null
    private var lastSpotTokenPrices: Map<Int, Double> = emptyMap()
    private val api = Retrofit.Builder()
        .baseUrl("${BuildConfig.CLOUD_API_URL.trimEnd('/')}/")
        .client(OkHttpClient.Builder().addInterceptor { chain ->
            val user = FirebaseAuth.getInstance().currentUser
                ?: throw IllegalStateException("Log eerst in bij TradeMentor.")
            val token = Tasks.await(user.getIdToken(false)).token
                ?: throw IllegalStateException("Cloudsessie ontbreekt.")
            chain.proceed(chain.request().newBuilder().header("Authorization", "Bearer $token").build())
        }.build())
        .addConverterFactory(GsonConverterFactory.create())
        .build()
        .create(CloudWalletApi::class.java)

    suspend fun load(address: String): WalletOverview = coroutineScope {
        val normalized = address.lowercase()
        val account = async { api.getClearinghouseState(ClearinghouseStateRequest(normalized)) }
        val orders = async { api.getOpenOrders(UserInfoRequest("openOrders", normalized)) }
        val fills = async { api.getUserFills(UserInfoRequest("userFills", normalized)) }
        val abstraction = async { api.getUserAbstraction(UserInfoRequest("userAbstraction", normalized)) }
        val spotState = async { api.getSpotClearinghouseState(UserInfoRequest("spotClearinghouseState", normalized)) }
        val spotMeta = async { api.getSpotMetaAndAssetContexts(InfoTypeRequest("spotMetaAndAssetCtxs")) }
        val perpDexs = async { api.getPerpDexs(InfoTypeRequest("perpDexs")) }

        val accountResponse = account.await()
        if (!accountResponse.isSuccessful) error("Hyperliquid-account kon niet worden gelezen (${accountResponse.code()}).")
        val dexNames = perpDexs.await().takeIf { it.isSuccessful }?.body()?.mapNotNull { element ->
            when {
                element.isJsonObject -> element.asJsonObject.get("name")?.asString
                element.isJsonPrimitive && element.asJsonPrimitive.isString -> element.asString
                else -> null
            }
        }.orEmpty().filter { it.isNotBlank() }.distinct()
        // Avoid sending every HIP-3 DEX request as one burst; Hyperliquid rate-limits that.
        val additionalStates = buildList {
            dexNames.forEach { dex ->
                delay(175)
                runCatching { api.getClearinghouseState(ClearinghouseStateRequest(normalized, dex = dex)) }
                    .getOrNull()?.takeIf { it.isSuccessful }?.body()?.let(::add)
            }
        }
        val defaultAccount = accountResponse.body() ?: HyperliquidAccountState()
        val allPositions = (defaultAccount.assetPositions + additionalStates.flatMap { it.assetPositions })
            .filter { (it.position.signedSize.toDoubleOrNull() ?: 0.0) != 0.0 }
            .distinctBy { "${it.position.coin}|${it.position.signedSize}|${it.position.entryPrice}" }
        val combinedAccount = defaultAccount.copy(assetPositions = allPositions)
        val modeResponse = abstraction.await()
        val spotStateResponse = spotState.await()
        val balances = spotStateResponse.takeIf { it.isSuccessful }?.body()?.balances
            ?: lastOverview?.spotBalances.orEmpty()
        val freshTokenPrices = spotTokenPrices(spotMeta.await().takeIf { it.isSuccessful }?.body())
        if (freshTokenPrices.isNotEmpty()) lastSpotTokenPrices = freshTokenPrices
        val tokenPrices = freshTokenPrices.ifEmpty { lastSpotTokenPrices }
        val spotPortfolioValue = balances.sumOf { balance ->
            (balance.total.toDoubleOrNull() ?: 0.0) * (tokenPrices[balance.token] ?: if (balance.coin in setOf("USDC", "USDT")) 1.0 else 0.0)
        }
        val mode = modeResponse.takeIf { it.isSuccessful }?.body().orEmpty().ifBlank {
            // A temporary abstraction-endpoint failure must not make a unified
            // account jump back to its smaller perp-only value.
            lastOverview?.accountMode ?: if (balances.isNotEmpty()) "unifiedAccount" else "default"
        }
        val classicValue = defaultAccount.marginSummary.accountValue.toDoubleOrNull() ?: 0.0
        val unifiedAvailable = balances
            .filter { it.coin.equals("USDC", ignoreCase = true) || it.coin.equals("USDT", ignoreCase = true) }
            .sumOf { balance ->
                ((balance.total.toDoubleOrNull() ?: 0.0) - (balance.hold.toDoubleOrNull() ?: 0.0))
                    .coerceAtLeast(0.0)
            }
        val unifiedMode = mode == "unifiedAccount" || mode == "portfolioMargin"
        WalletOverview(
            account = combinedAccount,
            openOrders = orders.await().takeIf { it.isSuccessful }?.body().orEmpty(),
            recentFills = fills.await().takeIf { it.isSuccessful }?.body().orEmpty().take(2_000),
            accountMode = mode,
            portfolioValue = if (unifiedMode) spotPortfolioValue else classicValue,
            availableToTrade = if (unifiedMode) unifiedAvailable else (defaultAccount.withdrawable.toDoubleOrNull() ?: 0.0),
            spotBalances = balances
        ).also { lastOverview = it }
    }

    private fun spotTokenPrices(payload: com.google.gson.JsonArray?): Map<Int, Double> {
        if (payload == null || payload.size() < 2) return emptyMap()
        val meta = payload[0].asJsonObject
        val contexts = payload[1].asJsonArray
        val universe = meta.getAsJsonArray("universe") ?: return emptyMap()
        val tokens = meta.getAsJsonArray("tokens") ?: return emptyMap()
        val names = tokens.associate { token ->
            val item = token.asJsonObject
            item["index"].asInt to item["name"].asString
        }
        val prices = mutableMapOf<Int, Double>()
        names.forEach { (index, name) -> if (name == "USDC" || name == "USDT") prices[index] = 1.0 }
        repeat(4) {
            universe.forEachIndexed { index, element ->
                val pair = element.asJsonObject.getAsJsonArray("tokens") ?: return@forEachIndexed
                if (pair.size() < 2 || index >= contexts.size()) return@forEachIndexed
                val base = pair[0].asInt
                val quote = pair[1].asInt
                val context = contexts[index].asJsonObject
                val mark = context.get("markPx")?.asString?.toDoubleOrNull()
                    ?: context.get("midPx")?.asString?.toDoubleOrNull()
                    ?: return@forEachIndexed
                prices[quote]?.let { quotePrice -> prices[base] = mark * quotePrice }
            }
        }
        return prices
    }
}
