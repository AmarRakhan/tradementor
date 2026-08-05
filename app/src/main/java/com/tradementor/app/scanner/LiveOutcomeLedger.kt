package com.tradementor.app.scanner

import android.content.ContentValues
import android.content.Context
import android.database.sqlite.SQLiteDatabase
import android.database.sqlite.SQLiteOpenHelper

object LiveOutcomeLedger {
    private class Database(context: Context) : SQLiteOpenHelper(context, "tradementor_live_learning.db", null, 1) {
        override fun onCreate(db: SQLiteDatabase) {
            db.execSQL(
                """
                CREATE TABLE completed_live_trades (
                    trade_id INTEGER PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    short_direction INTEGER NOT NULL,
                    entry_price REAL NOT NULL,
                    profit_target REAL NOT NULL,
                    max_adverse REAL NOT NULL,
                    predicted_win_rate REAL,
                    started_at INTEGER NOT NULL,
                    resolved_at INTEGER NOT NULL,
                    outcome TEXT NOT NULL,
                    final_price REAL,
                    strategy TEXT NOT NULL,
                    indicators TEXT NOT NULL,
                    synced INTEGER NOT NULL DEFAULT 0
                )
                """.trimIndent()
            )
        }

        override fun onUpgrade(db: SQLiteDatabase, oldVersion: Int, newVersion: Int) = Unit
    }

    fun archiveCompleted(context: Context, trades: List<TrackedTrade>) {
        val completed = trades.filter { it.outcome != TradeOutcome.Pending }
        if (completed.isEmpty()) return
        Database(context.applicationContext).use { helper ->
            val db = helper.writableDatabase
            db.beginTransaction()
            try {
                completed.forEach { trade ->
                    db.insertWithOnConflict("completed_live_trades", null, ContentValues().apply {
                        put("trade_id", trade.id)
                        put("symbol", trade.symbol)
                        put("short_direction", if (trade.shortDirection) 1 else 0)
                        put("entry_price", trade.entryPrice)
                        put("profit_target", trade.profitPercentage)
                        put("max_adverse", trade.maxAdversePercentage)
                        trade.historicalWinRate?.let { put("predicted_win_rate", it) }
                        put("started_at", trade.startedAt)
                        put("resolved_at", trade.adviceUpdatedAt ?: System.currentTimeMillis())
                        put("outcome", trade.outcome.name)
                        trade.lastPrice?.let { put("final_price", it) }
                        put("strategy", trade.strategyName)
                        put("indicators", trade.indicators.joinToString("|"))
                    }, SQLiteDatabase.CONFLICT_IGNORE)
                }
                db.setTransactionSuccessful()
            } finally {
                db.endTransaction()
            }
        }
    }

    fun loadCompleted(context: Context): List<TrackedTrade> = runCatching {
        Database(context.applicationContext).use { helper ->
            helper.readableDatabase.query(
                "completed_live_trades", null, null, null, null, null, "resolved_at DESC"
            ).use { cursor ->
                buildList {
                    while (cursor.moveToNext()) {
                        val outcome = runCatching {
                            TradeOutcome.valueOf(cursor.getString(cursor.getColumnIndexOrThrow("outcome")))
                        }.getOrDefault(TradeOutcome.Failed)
                        val storedStrategy = cursor.getString(cursor.getColumnIndexOrThrow("strategy"))
                        val storedStrategyId = when {
                            storedStrategy.equals("Strategy 1", true) || storedStrategy.startsWith("Backtest-consensus") || storedStrategy.startsWith("TradeMentor") -> "strategy_1"
                            storedStrategy.equals("Strategy 2", true) -> "strategy_2"
                            storedStrategy.startsWith("Extern") -> "external_hyperliquid"
                            else -> "unattributed"
                        }
                        add(
                            TrackedTrade(
                                id = cursor.getLong(cursor.getColumnIndexOrThrow("trade_id")),
                                symbol = cursor.getString(cursor.getColumnIndexOrThrow("symbol")),
                                shortDirection = cursor.getInt(cursor.getColumnIndexOrThrow("short_direction")) == 1,
                                entryPrice = cursor.getDouble(cursor.getColumnIndexOrThrow("entry_price")),
                                profitPercentage = cursor.getDouble(cursor.getColumnIndexOrThrow("profit_target")),
                                timeframe = "Afgerond",
                                startedAt = cursor.getLong(cursor.getColumnIndexOrThrow("started_at")),
                                expiresAt = cursor.getLong(cursor.getColumnIndexOrThrow("resolved_at")),
                                historicalWinRate = cursor.getColumnIndex("predicted_win_rate").takeIf { it >= 0 && !cursor.isNull(it) }?.let(cursor::getDouble),
                                outcome = outcome,
                                strategyId = storedStrategyId,
                                strategyName = storedStrategy,
                                indicators = cursor.getString(cursor.getColumnIndexOrThrow("indicators")).orEmpty().split('|').filter(String::isNotBlank),
                                lastPrice = cursor.getColumnIndex("final_price").takeIf { it >= 0 && !cursor.isNull(it) }?.let(cursor::getDouble),
                                maxAdversePercentage = cursor.getDouble(cursor.getColumnIndexOrThrow("max_adverse")),
                                closedAt = cursor.getLong(cursor.getColumnIndexOrThrow("resolved_at"))
                            )
                        )
                    }
                }
            }
        }
    }.getOrDefault(emptyList())

    fun removeTradeIds(context: Context, tradeIds: Collection<Long>) {
        if (tradeIds.isEmpty()) return
        Database(context.applicationContext).use { helper ->
            val db = helper.writableDatabase
            tradeIds.chunked(400).forEach { ids ->
                db.delete(
                    "completed_live_trades",
                    "trade_id IN (${ids.joinToString(",") { "?" }})",
                    ids.map(Long::toString).toTypedArray()
                )
            }
        }
    }
}
