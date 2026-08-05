package com.tradementor.app.scanner

import android.content.Context

data class ScannerProgress(val phase: String, val completed: Int, val total: Int, val updatedAt: Long, val summary: String = "") {
    val running: Boolean get() = phase != "idle" && phase != "error"
    val fraction: Float get() = if (total > 0) (completed.toFloat() / total).coerceIn(0f, 1f) else 0f
}

object ScannerProgressStore {
    private const val PREFS = "scanner_progress"

    fun load(context: Context): ScannerProgress {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return ScannerProgress(
            prefs.getString("phase", "idle") ?: "idle",
            prefs.getInt("completed", 0),
            prefs.getInt("total", 0),
            prefs.getLong("updated_at", 0L),
            prefs.getString("summary", "") ?: ""
        )
    }

    fun update(context: Context, phase: String, completed: Int = 0, total: Int = 0, summary: String? = null) {
        val edit = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("phase", phase)
            .putInt("completed", completed.coerceAtLeast(0))
            .putInt("total", total.coerceAtLeast(0))
            .putLong("updated_at", System.currentTimeMillis())
        if (summary != null) edit.putString("summary", summary)
        edit.apply()
    }
}
