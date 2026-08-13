package com.tradementor.app.scanner

import android.content.Context
import android.database.sqlite.SQLiteDatabase

data class ConsensusProfile(
    val profitTarget: Double = 1.0,
    val stopLoss: Double = 20.0,
    val minimumWinRate: Double = 65.0,
    val minimumScore: Double = 0.0,
    val allowLong: Boolean = true,
    val allowShort: Boolean = true,
    val sourceRuns: Int = 0,
    val historicalSituations: Int = 0,
    val validationTrades: Int = 0,
    val completedLiveTrades: Int = 0,
    val liveWins: Int = 0,
    val liveLosses: Int = 0
)

object ConsensusProfileStore {
    fun load(context: Context): ConsensusProfile {
        val path = context.getDatabasePath("tradementor_research.db")
        if (!path.exists()) return ConsensusProfile()
        return runCatching {
            SQLiteDatabase.openDatabase(path.absolutePath, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                val profits = mutableListOf<Double>()
                val stops = mutableListOf<Double>()
                val winRates = mutableListOf<Double>()
                val scores = mutableListOf<Double>()
                val directions = mutableListOf<String>()
                var validationTrades = 0
                db.query("archived_backtests", null, null, null, null, null, "created_at DESC").use { cursor ->
                    while (cursor.moveToNext()) {
                        profits += cursor.getDouble(cursor.getColumnIndexOrThrow("profit_target"))
                        stops += cursor.getDouble(cursor.getColumnIndexOrThrow("stop_loss"))
                        winRates += cursor.getDouble(cursor.getColumnIndexOrThrow("minimum_win_rate"))
                        scores += cursor.getDouble(cursor.getColumnIndexOrThrow("minimum_score"))
                        directions += cursor.getString(cursor.getColumnIndexOrThrow("direction"))
                        validationTrades += cursor.getInt(cursor.getColumnIndexOrThrow("validation_trades"))
                    }
                }
                val historicalSituations = db.rawQuery(
                    "SELECT COUNT(*) FROM (SELECT DISTINCT symbol, signal_time FROM prediction_ledger)", null
                ).use { cursor -> if (cursor.moveToFirst()) cursor.getInt(0) else 0 }
                val live = loadLiveEvidence(context)
                if (profits.isEmpty()) ConsensusProfile() else {
                    val direction = directions.groupingBy { it }.eachCount().maxByOrNull { it.value }?.key.orEmpty()
                    ConsensusProfile(
                        profitTarget = median(profits).coerceAtLeast(0.1),
                        stopLoss = median(stops).coerceAtLeast(0.1),
                        minimumWinRate = median(winRates).coerceIn(0.0, 99.0),
                        minimumScore = median(scores).coerceAtLeast(0.0),
                        allowLong = direction != "SHORT",
                        allowShort = direction != "LONG",
                        sourceRuns = profits.size,
                        historicalSituations = historicalSituations,
                        validationTrades = validationTrades,
                        completedLiveTrades = live.first + live.second,
                        liveWins = live.first,
                        liveLosses = live.second
                    )
                }
            }
        }.getOrDefault(ConsensusProfile())
    }

    private fun loadLiveEvidence(context: Context): Pair<Int, Int> {
        val path = context.getDatabasePath("tradementor_live_learning.db")
        if (!path.exists()) return 0 to 0
        return runCatching {
            SQLiteDatabase.openDatabase(path.absolutePath, null, SQLiteDatabase.OPEN_READONLY).use { db ->
                db.rawQuery("SELECT outcome, COUNT(*) FROM completed_live_trades GROUP BY outcome", null).use { cursor ->
                    var wins = 0
                    var losses = 0
                    while (cursor.moveToNext()) {
                        when (cursor.getString(0)) {
                            "Succeeded" -> wins = cursor.getInt(1)
                            "Failed" -> losses = cursor.getInt(1)
                        }
                    }
                    wins to losses
                }
            }
        }.getOrDefault(0 to 0)
    }

    private fun median(values: List<Double>): Double {
        val ordered = values.sorted()
        val middle = ordered.size / 2
        return if (ordered.size % 2 == 0) (ordered[middle - 1] + ordered[middle]) / 2.0 else ordered[middle]
    }
}
