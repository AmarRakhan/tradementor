package com.tradementor.app.api

import com.google.gson.annotations.SerializedName
import retrofit2.Response
import retrofit2.http.GET
import retrofit2.http.Path
import retrofit2.http.Query

interface ExchangeCatalogApi {
    @GET("exchanges")
    suspend fun getExchanges(@Query("quotes") quotes: String = "USD"): Response<List<CatalogExchange>>

    @GET("exchanges/{exchangeId}/markets")
    suspend fun getExchangeMarkets(
        @Path("exchangeId") exchangeId: String,
        @Query("quotes") quotes: String = "USD"
    ): Response<List<CatalogMarket>>
}

data class CatalogExchange(
    val id: String,
    val name: String,
    val type: List<String> = emptyList(),
    val active: Boolean = false,
    @SerializedName("api_status") val apiStatus: Boolean = false,
    @SerializedName("markets_data_fetched") val marketsDataFetched: Boolean = false,
    @SerializedName("adjusted_rank") val adjustedRank: Int? = null,
    val markets: Int = 0,
    val quotes: Map<String, CatalogExchangeQuote> = emptyMap()
)

data class CatalogExchangeQuote(
    @SerializedName("adjusted_volume_24h") val adjustedVolume24h: Double? = null,
    @SerializedName("reported_volume_24h") val reportedVolume24h: Double? = null
)

data class CatalogMarket(
    val pair: String,
    @SerializedName("base_currency_id") val baseCurrencyId: String,
    @SerializedName("base_currency_name") val baseCurrencyName: String,
    @SerializedName("quote_currency_id") val quoteCurrencyId: String,
    @SerializedName("quote_currency_name") val quoteCurrencyName: String,
    val category: String,
    val outlier: Boolean = false,
    @SerializedName("reported_volume_24h_share") val volumeShare: Double? = null,
    val quotes: Map<String, CatalogMarketQuote> = emptyMap(),
    @SerializedName("last_updated") val lastUpdated: String? = null
) {
    val baseSymbol: String get() = pair.substringBefore('/').uppercase()
    val quoteSymbol: String get() = pair.substringAfter('/', "").uppercase()
    val usdPrice: Double get() = quotes["USD"]?.price ?: 0.0
    val usdVolume24h: Double get() = quotes["USD"]?.volume24h ?: 0.0
}

data class CatalogMarketQuote(
    val price: Double? = null,
    @SerializedName("volume_24h") val volume24h: Double? = null
)
