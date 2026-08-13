package com.tradementor.app.api

import com.google.gson.JsonArray
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST

interface HyperliquidApi {

    @POST("info")
    suspend fun getAllMids(
        @Body request: AllMidsRequest
    ): Response<Map<String, String>>

    @POST("info")
    suspend fun getMeta(
        @Body request: MetaRequest
    ): Response<JsonArray>

    @POST("info")
    suspend fun getCandles(
        @Body request: CandleSnapshotRequest
    ): Response<List<Candle>>

    @POST("info")
    suspend fun getClearinghouseState(
        @Body request: ClearinghouseStateRequest
    ): Response<HyperliquidAccountState>

    @POST("info")
    suspend fun getOpenOrders(
        @Body request: UserInfoRequest
    ): Response<List<HyperliquidOpenOrder>>

    @POST("info")
    suspend fun getUserFills(
        @Body request: UserInfoRequest
    ): Response<List<HyperliquidFill>>

    @POST("info")
    suspend fun getUserAbstraction(
        @Body request: UserInfoRequest
    ): Response<String>

    @POST("info")
    suspend fun getSpotClearinghouseState(
        @Body request: UserInfoRequest
    ): Response<HyperliquidSpotState>

    @POST("info")
    suspend fun getSpotMetaAndAssetContexts(
        @Body request: InfoTypeRequest
    ): Response<JsonArray>

    @POST("info")
    suspend fun getPerpDexs(
        @Body request: InfoTypeRequest
    ): Response<JsonArray>

}
