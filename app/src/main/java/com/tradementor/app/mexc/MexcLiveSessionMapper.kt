package com.tradementor.app.mexc

import com.tradementor.app.cloud.MexcCloudPosition
import com.tradementor.app.cloud.MexcCloudStatus

data class MexcLiveDashboardState(
    val session: MexcSession,
    val marginRatioPercent: Double,
    val liquidationPrice: Double,
    val isolated: Boolean,
    val unrealizedPnl: Double,
)

object MexcLiveSessionMapper {
    fun from(status: MexcCloudStatus): MexcLiveDashboardState? {
        val positions = status.positions.filter { it.notionalUsd > 0.0 }
        if (positions.isEmpty()) return null
        val longs = positions.filter { it.side.equals("long", true) }
        val shorts = positions.filter { it.side.equals("short", true) }
        val longNotional = longs.sumOf { it.notionalUsd }
        val shortNotional = shorts.sumOf { it.notionalUsd }
        fun weightedEntry(rows: List<MexcCloudPosition>): Double {
            val weight = rows.sumOf { it.notionalUsd }
            return if (weight > 0.0) rows.sumOf { it.entryPrice * it.notionalUsd } / weight else 0.0
        }
        val unrealized = positions.sumOf { it.unrealizedPnl }
        val beforeOpenPnl = status.equity - unrealized
        return MexcLiveDashboardState(
            session = MexcSession(
                startEquity = beforeOpenPnl,
                currentEquity = status.equity,
                lowestEquity = minOf(beforeOpenPnl, status.equity),
                phase = if (shortNotional > 0.0) MexcPhase.HEDGE else MexcPhase.LONG,
                longNotional = longNotional,
                shortNotional = shortNotional,
                hedgeEntry = weightedEntry(shorts),
                weightedEntry = weightedEntry(longs),
                fees = 0.0,
                realizedPnl = positions.sumOf { it.realizedPnl },
                reason = "Echte MEXC-positie live gesynchroniseerd",
            ),
            marginRatioPercent = positions.maxOf { it.marginRatioPercent }.coerceIn(0.0, 100.0),
            liquidationPrice = positions.map { it.liquidationPrice }.filter { it > 0.0 }.minOrNull() ?: 0.0,
            isolated = positions.all { it.isolated },
            unrealizedPnl = unrealized,
        )
    }
}
