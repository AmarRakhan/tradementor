package com.tradementor.app.scanner

import com.tradementor.app.api.HyperliquidFill

/** Pure reconciliation used by UI/background refreshes and unit simulations. */
object TradeClosureReconciler {
    fun reconcileClosedTrade(trade: TrackedTrade, recentFills: List<HyperliquidFill>): TrackedTrade? {
        val closeFills = recentFills.filter {
            it.coin.equals(trade.symbol, ignoreCase = true) &&
                it.time >= trade.startedAt &&
                it.direction.contains("Close", ignoreCase = true)
        }
        if (closeFills.isEmpty()) return null

        val latest = closeFills.maxBy { it.time }
        val realized = closeFills.sumOf { it.closedPnl.toDoubleOrNull() ?: 0.0 }
        val fees = closeFills.sumOf { it.fee.toDoubleOrNull() ?: 0.0 }
        val wasOutsideTerm = trade.outcome == TradeOutcome.Failed
        val profitable = realized > 0.0
        return trade.copy(
            // A manually closed green trade is a realized win. "Manual" describes
            // the exit method, not whether the result belongs under Won.
            outcome = if (profitable) TradeOutcome.Succeeded else TradeOutcome.Failed,
            realizedPnl = realized,
            feesPaidUsd = fees,
            lastPrice = latest.price.toDoubleOrNull() ?: trade.lastPrice,
            closedAt = latest.time,
            lateTargetReachedAt = if (profitable && wasOutsideTerm) latest.time else trade.lateTargetReachedAt,
            adviceUpdatedAt = latest.time,
            exitAdvice = when {
                trade.exitAdvice == "Take All Profits" -> "Take All Profits"
                profitable && wasOutsideTerm -> "Doel later bereikt en positie gesloten"
                profitable -> "Handmatig met winst gesloten"
                else -> "Handmatig zonder winst gesloten"
            }
        )
    }
}
