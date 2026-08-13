package com.tradementor.app.mexc

import kotlin.math.abs

object MexcSignalCalculator {
    fun point(execution: List<MexcCandle>, risk: List<MexcCandle>): MexcMarketPoint {
        require(execution.size >= 2) { "Minimaal twee execution candles nodig" }
        require(risk.size >= 14) { "Minimaal veertien risk candles nodig" }
        val current = execution.last()
        val recentExecution = execution.takeLast(15)
        val trueRanges = recentExecution.zipWithNext().map { (previous, candle) ->
            maxOf(candle.high - candle.low, abs(candle.high - previous.close), abs(candle.low - previous.close))
        }
        val atrPercent = (trueRanges.average().takeIf { it.isFinite() } ?: 0.0) / current.close
        val riskWindow = risk.filter { it.time <= current.time }.takeLast(50).ifEmpty { risk.takeLast(50) }
        val closes=riskWindow.map{it.close}; val last=riskWindow.last(); val previous=riskWindow[riskWindow.lastIndex-1]
        val ema9=ema(closes,9); val ema21=ema(closes,21); val ema50=ema(closes,50); val rsi=rsi(closes,14)
        val avgVolume=riskWindow.dropLast(1).takeLast(20).map{it.volume}.average().takeIf{it.isFinite()&&it>0}?:last.volume
        val momentum=if(closes.size>=4)last.close/closes[closes.lastIndex-3]-1 else 0.0
        var riskScore=0
        riskScore += when { ema9<ema21 && ema21<ema50 -> 30; ema9<ema21 -> 18; else -> 0 }
        riskScore += when { rsi<35 -> 22; rsi<45 -> 12; else -> 0 }
        if(momentum<0)riskScore+=14
        if(last.low<previous.low)riskScore+=8
        if(last.high<previous.high)riskScore+=6
        if(last.close<last.open)riskScore+=8
        if(last.volume>avgVolume*1.25 && last.close<last.open)riskScore+=12
        riskScore=riskScore.coerceIn(0,100)
        var recoveryScore=0
        recoveryScore += when { ema9>ema21 && ema21>ema50 -> 30; ema9>ema21 -> 18; else -> 0 }
        recoveryScore += when { rsi>60 -> 20; rsi>50 -> 12; else -> 0 }
        if(momentum>0)recoveryScore+=16
        if(last.low>previous.low)recoveryScore+=10
        if(last.high>previous.high)recoveryScore+=8
        if(last.close>last.open)recoveryScore+=8
        if(last.volume>avgVolume*1.25 && last.close>last.open)recoveryScore+=8
        return MexcMarketPoint(
            timeSeconds = current.time,
            price = current.close,
            atrPercent = atrPercent,
            lowerLow = current.low < execution[execution.lastIndex - 1].low,
            riskScore = riskScore,
            recoveryScore = recoveryScore.coerceIn(0, 100)
        )
    }

    private fun ema(values:List<Double>,period:Int):Double{if(values.isEmpty())return 0.0;val k=2.0/(period+1);return values.fold(values.first()){acc,value->value*k+acc*(1-k)}}
    private fun rsi(values:List<Double>,period:Int):Double{val changes=values.zipWithNext().takeLast(period);if(changes.isEmpty())return 50.0;val gain=changes.sumOf{(a,b)->(b-a).coerceAtLeast(0.0)}/changes.size;val loss=changes.sumOf{(a,b)->(a-b).coerceAtLeast(0.0)}/changes.size;if(loss==0.0)return 100.0;return 100.0-(100.0/(1.0+gain/loss))}
}
