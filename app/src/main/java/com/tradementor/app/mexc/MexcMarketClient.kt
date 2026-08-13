package com.tradementor.app.mexc

import com.google.gson.JsonObject
import com.google.gson.JsonParser
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.withContext
import okhttp3.OkHttpClient
import okhttp3.Request
import java.util.concurrent.TimeUnit

data class MexcCandle(val time:Long,val open:Double,val high:Double,val low:Double,val close:Double,val volume:Double)
data class MexcMarketSnapshot(val price:Double=0.0,val fundingRate:Double=0.0,val holdVolume:Double=0.0,val timestamp:Long=0,val minimumNotional:Double=0.0,val maximumLeverage:Int=0,val maintenanceMarginRate:Double=0.0,val liquidationFeeRate:Double=0.0,val connected:Boolean=false)

class MexcMarketClient {
    private val http=OkHttpClient.Builder().connectTimeout(5,TimeUnit.SECONDS).readTimeout(20,TimeUnit.SECONDS).build()
    private val base="https://api.mexc.com"
    suspend fun snapshot():MexcMarketSnapshot=withContext(Dispatchers.IO){
        val root=get("/api/v1/contract/ticker?symbol=BTC_USDT"); val data=root.getAsJsonObject("data"); val details=get("/api/v1/contract/detail?symbol=BTC_USDT").getAsJsonObject("data"); val price=data.double("lastPrice")
        MexcMarketSnapshot(price,data.double("fundingRate"),data.double("holdVol"),data.long("timestamp"),details.double("contractSize")*details.double("minVol")*price,details.double("maxLeverage").toInt(),details.double("maintenanceMarginRate"),details.double("liquidationFeeRate"),true)
    }
    suspend fun candles(interval:String="3m",count:Int=600):List<MexcCandle> = withContext(Dispatchers.IO){
        val apiInterval=when(interval){"1m","3m"->"Min1";"5m"->"Min5";"15m"->"Min15";"30m"->"Min30";"1h"->"Min60";"4h"->"Hour4";else->error("Niet-ondersteund timeframe: $interval")}
        val seconds=when(apiInterval){"Min5"->300;"Min15"->900;"Min30"->1800;"Min60"->3600;"Hour4"->14400;else->60}
        val requested=if(interval=="3m")minOf(count*3,1900) else minOf(count,1900); val end=System.currentTimeMillis()/1000; val start=end-seconds*requested
        val data=get("/api/v1/contract/kline/BTC_USDT?interval=$apiInterval&start=$start&end=$end").getAsJsonObject("data")
        val times=data.getAsJsonArray("time"); val opens=data.getAsJsonArray("open"); val highs=data.getAsJsonArray("high"); val lows=data.getAsJsonArray("low"); val closes=data.getAsJsonArray("close"); val vols=data.getAsJsonArray("vol")
        val raw=(0 until times.size()).map{MexcCandle(times[it].asLong,opens[it].asDouble,highs[it].asDouble,lows[it].asDouble,closes[it].asDouble,vols[it].asDouble)}
        if(interval!="3m") raw.takeLast(count) else raw.chunked(3).filter{it.size==3}.map{group->MexcCandle(group.first().time,group.first().open,group.maxOf{it.high},group.minOf{it.low},group.last().close,group.sumOf{it.volume})}.takeLast(count)
    }
    private fun get(path:String):JsonObject { val response=http.newCall(Request.Builder().url(base+path).get().build()).execute(); response.use { val body=it.body?.string().orEmpty(); check(it.isSuccessful){"MEXC marktfeed antwoordde met ${it.code}"}; val root=JsonParser.parseString(body).asJsonObject; check(root.get("success")?.asBoolean==true){root.get("message")?.asString ?: "MEXC gaf geen geldige marktdata"}; return root } }
    private fun JsonObject.double(name:String)=get(name)?.asDouble ?: 0.0
    private fun JsonObject.long(name:String)=get(name)?.asLong ?: 0L
}
