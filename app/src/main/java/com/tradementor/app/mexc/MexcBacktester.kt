package com.tradementor.app.mexc

data class MexcBacktestResult(val sessions:Int,val wins:Int,val losses:Int,val startEquity:Double,val endEquity:Double,val maxDrawdownPercent:Double,val totalFees:Double,val maxDca:Int,val maxExposure:Double,val peakMarginUsagePercent:Double=0.0,val estimatedLiquidationDistancePercent:Double=0.0)

object MexcBacktester {
    fun run(settings:MexcSettings,candles:List<MexcCandle>,riskCandles:List<MexcCandle> = candles,maintenanceMarginRate:Double=.001,liquidationFeeRate:Double=.0004):MexcBacktestResult {
        if(settings.strategyVersion=="hedge_dca_v3") return runV3(settings,candles,maintenanceMarginRate,liquidationFeeRate)
        val fixedSettings=MexcAdaptiveEngine.fixedProfile(settings)
        val emptySession=MexcSession(fixedSettings.paperEquity,fixedSettings.paperEquity,fixedSettings.paperEquity)
        val initialNotional=MexcAdaptiveEngine.initialNotional(fixedSettings,fixedSettings.paperEquity)
        val initialLiquidationDistance=MexcAdaptiveEngine.estimatedCrossLiquidationDistance(emptySession,maintenanceMarginRate,liquidationFeeRate,projectedLongNotional=initialNotional)
        if(candles.size<60) return MexcBacktestResult(0,0,0,fixedSettings.paperEquity,fixedSettings.paperEquity,0.0,0.0,0,0.0,0.0,initialLiquidationDistance*100)
        var equity=fixedSettings.paperEquity; var session=MexcSession(equity,equity,equity); var sessions=0; var wins=0; var losses=0; var low=equity; var fees=0.0; var maxDca=0; var maxExposure=0.0; var peakMarginUsage=0.0; var minimumLiquidationDistance=initialLiquidationDistance
        candles.forEachIndexed { index,c ->
            val riskIndex=riskCandles.indexOfLast{it.time<=c.time}.coerceAtLeast(0); val riskRecent=riskCandles.subList(maxOf(0,riskIndex-49),riskIndex+1)
            if(index==0 || riskRecent.size<14) return@forEachIndexed
            val point=MexcSignalCalculator.point(candles.subList(maxOf(0,index-14),index+1),riskRecent); val marginUsage=MexcAdaptiveEngine.estimatedMarginUsage(fixedSettings,session); val liquidationDistance=MexcAdaptiveEngine.estimatedCrossLiquidationDistance(session,maintenanceMarginRate,liquidationFeeRate,projectedLongNotional=if(session.longNotional==0.0)initialNotional else session.longNotional); peakMarginUsage=maxOf(peakMarginUsage,marginUsage); minimumLiquidationDistance=minOf(minimumLiquidationDistance,liquidationDistance); session=MexcAdaptiveEngine.executePaper(fixedSettings,session,point,MexcAdaptiveEngine.decide(fixedSettings,session,point,liquidationDistance,marginUsage)); low=minOf(low,session.currentEquity); maxDca=maxOf(maxDca,session.dcaCount); maxExposure=maxOf(maxExposure,session.longNotional)
            if(session.closed){sessions++; if(session.currentEquity>equity)wins++ else losses++; fees+=session.fees; equity=session.currentEquity; session=MexcSession(equity,equity,equity)}
        }
        val end=session.currentEquity; val dd=if(settings.paperEquity>0)(settings.paperEquity-low)/settings.paperEquity*100 else 0.0
        return MexcBacktestResult(sessions,wins,losses,fixedSettings.paperEquity,end,dd.coerceAtLeast(0.0),fees,maxDca,maxExposure,peakMarginUsage*100,minimumLiquidationDistance*100)
    }

    private fun runV3(s:MexcSettings,candles:List<MexcCandle>,mmr:Double,liquidationFee:Double):MexcBacktestResult{
        if(candles.size<2)return MexcBacktestResult(0,0,0,s.paperEquity,s.paperEquity,0.0,0.0,0,0.0)
        val start=s.paperEquity;var realized=0.0;var fees=0.0;var longQty=0.0;var shortQty=0.0;var longAvg=0.0;var shortAvg=0.0;var longDca=0;var shortDca=0;var longNext=0.0;var shortNext=0.0;var wins=0;var sessions=0;var low=start;var maxExposure=0.0;var peakMargin=0.0;var minLiq=1.0;var frozen=false
        fun openLong(price:Double,notional:Double){val q=notional/price;longAvg=if(longQty>0)(longAvg*longQty+price*q)/(longQty+q)else price;longQty+=q;fees+=notional*s.takerFee;longNext=price*(1-s.dcaSpacing)}
        fun openShort(price:Double,notional:Double){val q=notional/price;shortAvg=if(shortQty>0)(shortAvg*shortQty+price*q)/(shortQty+q)else price;shortQty+=q;fees+=notional*s.takerFee;shortNext=price*(1+s.dcaSpacing)}
        openLong(candles.first().close,s.initialOrderNotional);openShort(candles.first().close,s.initialOrderNotional)
        candles.drop(1).forEach{c->
            val price=c.close;var longPnl=longQty*(price-longAvg);var shortPnl=shortQty*(shortAvg-price);var equity=start+realized+longPnl+shortPnl-fees
            if(!frozen&&s.emergencyHedgeEnabled&&equity<=s.emergencyEquityTrigger){val diff=longQty-shortQty;if(diff>0)openShort(price,diff*price)else if(diff<0)openLong(price,-diff*price);frozen=true}
            if(!frozen){
                if(longQty>0&&c.high>=longAvg*(1+s.takeProfit)){val exit=longAvg*(1+s.takeProfit);val n=longQty*exit;realized+=longQty*(exit-longAvg);fees+=n*s.takerFee;longQty=0.0;longAvg=0.0;longDca=0;wins++;sessions++;openLong(exit,s.initialOrderNotional)}
                if(shortQty>0&&c.low<=shortAvg*(1-s.takeProfit)){val exit=shortAvg*(1-s.takeProfit);val n=shortQty*exit;realized+=shortQty*(shortAvg-exit);fees+=n*s.takerFee;shortQty=0.0;shortAvg=0.0;shortDca=0;wins++;sessions++;openShort(exit,s.initialOrderNotional)}
                if(longDca<s.maximumDcaOrders&&c.low<=longNext){openLong(longNext,s.initialOrderNotional);longDca++}
                if(shortDca<s.maximumDcaOrders&&c.high>=shortNext){openShort(shortNext,s.initialOrderNotional);shortDca++}
            }
            longPnl=longQty*(price-longAvg);shortPnl=shortQty*(shortAvg-price);equity=start+realized+longPnl+shortPnl-fees;low=minOf(low,equity)
            val longN=longQty*price;val shortN=shortQty*price;val gross=longN+shortN;val net=kotlin.math.abs(longN-shortN);maxExposure=maxOf(maxExposure,gross);peakMargin=maxOf(peakMargin,(gross/200.0)/maxOf(equity,.01));minLiq=minOf(minLiq,if(net<=0)1.0 else ((equity-gross*(mmr+liquidationFee))/net).coerceIn(0.0,1.0))
        }
        val last=candles.last().close;val end=start+realized+longQty*(last-longAvg)+shortQty*(shortAvg-last)-fees;val dd=((start-low)/start*100).coerceAtLeast(0.0)
        return MexcBacktestResult(sessions,wins,0,start,end,dd,fees,maxOf(longDca,shortDca),maxExposure,peakMargin*100,minLiq*100)
    }
}
