package com.tradementor.app.repository

import com.tradementor.app.api.CatalogExchange
import com.tradementor.app.api.CatalogMarket
import com.tradementor.app.api.ExchangeCatalogApi
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

class ExchangeCatalogRepository {
    private val api: ExchangeCatalogApi by lazy {
        Retrofit.Builder()
            .baseUrl("https://api.coinpaprika.com/v1/")
            .client(OkHttpClient.Builder().build())
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(ExchangeCatalogApi::class.java)
    }

    suspend fun getTopExchanges(limit: Int = 25): List<CatalogExchange> {
        val response = api.getExchanges()
        if (!response.isSuccessful) error("Exchangelijst kon niet worden opgehaald.")
        return response.body().orEmpty()
            .filter { it.active && it.apiStatus && it.marketsDataFetched && it.adjustedRank != null }
            .sortedBy { it.adjustedRank }
            .take(limit)
    }

    suspend fun getMarkets(exchangeId: String): List<CatalogMarket> {
        val response = api.getExchangeMarkets(exchangeId)
        if (!response.isSuccessful) error("Markten voor deze exchange konden niet worden opgehaald.")
        return response.body().orEmpty()
            .filter { !it.outlier && it.pair.contains('/') && it.usdPrice > 0.0 }
            .sortedByDescending { it.usdVolume24h }
    }
}

object MarketUniverseSelection {
    var exchangeId: String = "hyperliquid"
    var exchangeName: String = "Hyperliquid"
    var marketType: String = "Perpetuals"
    var quoteCurrency: String = "USD"
}
