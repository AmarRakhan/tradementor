package com.tradementor.app.repository

import com.tradementor.app.api.BinanceMarketApi
import com.tradementor.app.api.Candle
import okhttp3.OkHttpClient
import retrofit2.Retrofit
import retrofit2.converter.gson.GsonConverterFactory

class BinanceMarketRepository {
    private val api: BinanceMarketApi by lazy {
        Retrofit.Builder()
            .baseUrl("https://data-api.binance.vision/")
            .client(OkHttpClient.Builder().build())
            .addConverterFactory(GsonConverterFactory.create())
            .build()
            .create(BinanceMarketApi::class.java)
    }

    suspend fun getCandles(pair: String, interval: String, limit: Int = 500): List<Candle> {
        val symbol = pair.replace("/", "").replace("-", "").uppercase()
        val response = api.getKlines(symbol, interval, limit.coerceIn(50, 1_000))
        if (!response.isSuccessful) error("Binance-candles konden niet worden opgehaald.")
        return response.body().orEmpty().mapNotNull { row ->
            if (row.size() < 7) return@mapNotNull null
            runCatching {
                Candle(
                    openTime = row[0].asLong,
                    closeTime = row[6].asLong,
                    open = row[1].asString,
                    high = row[2].asString,
                    low = row[3].asString,
                    close = row[4].asString,
                    volume = row[5].asString
                )
            }.getOrNull()
        }.sortedBy { it.openTime }
    }
}
