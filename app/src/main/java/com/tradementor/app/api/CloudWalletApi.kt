package com.tradementor.app.api

import com.google.gson.JsonArray
import retrofit2.Response
import retrofit2.http.Body
import retrofit2.http.POST

interface CloudWalletApi {
    @POST("v1/me/info")
    suspend fun getClearinghouseState(@Body request: ClearinghouseStateRequest): Response<HyperliquidAccountState>

    @POST("v1/me/info")
    suspend fun getOpenOrders(@Body request: UserInfoRequest): Response<List<HyperliquidOpenOrder>>

    @POST("v1/me/info")
    suspend fun getUserFills(@Body request: UserInfoRequest): Response<List<HyperliquidFill>>

    @POST("v1/me/info")
    suspend fun getUserAbstraction(@Body request: UserInfoRequest): Response<String>

    @POST("v1/me/info")
    suspend fun getSpotClearinghouseState(@Body request: UserInfoRequest): Response<HyperliquidSpotState>

    @POST("v1/me/info")
    suspend fun getSpotMetaAndAssetContexts(@Body request: InfoTypeRequest): Response<JsonArray>

    @POST("v1/me/info")
    suspend fun getPerpDexs(@Body request: InfoTypeRequest): Response<JsonArray>
}
