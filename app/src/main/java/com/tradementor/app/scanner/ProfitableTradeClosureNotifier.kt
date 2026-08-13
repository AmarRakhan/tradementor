package com.tradementor.app.scanner

import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.media.AudioAttributes
import android.media.AudioFocusRequest
import android.media.AudioManager
import android.media.MediaPlayer
import android.os.Build
import androidx.core.app.NotificationCompat
import com.tradementor.app.MainActivity
import com.tradementor.app.R
import com.tradementor.app.api.HyperliquidFill
import java.text.NumberFormat
import java.util.Locale

object ProfitableTradeClosureNotifier {
    private const val PREFS = "profitable_trade_closure_notifications"
    private const val CHANNEL_ID = "profit_target_reached_v4"
    private const val SOUND_KEY = "selected_profit_sound"

    data class SoundOption(val id: String, val title: String, val resourceId: Int, val category: String)

    val soundOptions = listOf(
        SoundOption("classic", "Kassa klassiek", R.raw.cash_register, "effects"),
        SoundOption("coins", "Gouden munten", R.raw.golden_coins, "effects"),
        SoundOption("jackpot", "Jackpot winst", R.raw.jackpot_win, "effects"),
        SoundOption("luxury", "Luxe geldbel", R.raw.luxury_bell, "effects"),
        SoundOption("cascade", "Muntenregen", R.raw.coin_cascade, "effects"),
        SoundOption("success", "Succes-ping", R.raw.success_ping, "effects"),
        SoundOption("vault", "Kluis geopend", R.raw.vault_open, "effects"),
        SoundOption("sparkle", "Cash sparkle", R.raw.cash_sparkle, "effects"),
        SoundOption("trading", "Trading win", R.raw.trading_win, "effects"),
        SoundOption("bigwin", "Grote winst", R.raw.big_win, "effects"),
        SoundOption("voice_cash", "Yes! Victory", R.raw.mixkit_yes_victory, "movies"),
        SoundOption("voice_profit", "Power cheer", R.raw.mixkit_male_cheer, "movies"),
        SoundOption("voice_won", "Victory shout", R.raw.mixkit_cheer_victory, "movies"),
        SoundOption("voice_money", "Team celebration", R.raw.mixkit_group_applause, "movies"),
        SoundOption("voice_target", "Massive victory crowd", R.raw.mixkit_huge_victory, "movies"),
        SoundOption("voice_winner", "Crowd & victory whistle", R.raw.mixkit_cheer_whistle, "movies"),
        SoundOption("voice_trade", "Casino payout", R.raw.mixkit_payout_award, "movies"),
        SoundOption("voice_earned", "Big slot payout", R.raw.mixkit_slot_payout, "movies"),
        SoundOption("voice_result", "Slot-machine celebration", R.raw.mixkit_slot_win, "movies"),
        SoundOption("voice_kaching", "Champion fanfare", R.raw.mixkit_fanfare, "movies")
    )

    fun selectedSoundId(context: Context): String = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString(SOUND_KEY, soundOptions.first().id).orEmpty()

    fun selectSound(context: Context, id: String) {
        if (soundOptions.none { it.id == id }) return
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(SOUND_KEY, id).apply()
    }

    fun previewSound(context: Context, id: String) {
        soundOptions.firstOrNull { it.id == id }?.let { playOption(context, it) }
    }

    fun test(context: Context) = show(context, "TEST", 1.23, isTest = true)

    fun reconcile(context: Context, currentSymbols: Set<String>, recentFills: List<HyperliquidFill>) {
        val previousSymbols = ActiveHyperliquidPositionStore.symbols(context)
        val closedSymbols = previousSymbols - currentSymbols.map { it.uppercase() }.toSet()
        if (closedSymbols.isEmpty()) return

        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val notified = prefs.getStringSet("notified_events", emptySet()).orEmpty().toMutableSet()
        closedSymbols.forEach { symbol ->
            val fill = recentFills
                .filter { it.coin.equals(symbol, ignoreCase = true) }
                .maxByOrNull { it.time }
                ?: return@forEach
            val realizedProfit = fill.closedPnl.toDoubleOrNull() ?: 0.0
            if (realizedProfit <= 0.0) return@forEach
            val eventKey = "${symbol.uppercase()}:${fill.tradeId}:${fill.time}"
            if (!notified.add(eventKey)) return@forEach
            show(context, symbol.uppercase(), realizedProfit)
        }
        prefs.edit().putStringSet("notified_events", notified.toList().takeLast(200).toSet()).apply()
    }

    private fun show(context: Context, symbol: String, realizedProfit: Double, isTest: Boolean = false) {
        val manager = context.getSystemService(Context.NOTIFICATION_SERVICE) as NotificationManager
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.O) {
            manager.createNotificationChannel(
                NotificationChannel(CHANNEL_ID, "Winstdoel behaald", NotificationManager.IMPORTANCE_HIGH).apply {
                    description = "Melding wanneer een echte trade met winst wordt gesloten"
                    enableVibration(true)
                    setSound(null, null)
                }
            )
        }
        val intent = Intent(context, MainActivity::class.java)
        val pendingIntent = PendingIntent.getActivity(
            context,
            symbol.hashCode(),
            intent,
            PendingIntent.FLAG_UPDATE_CURRENT or PendingIntent.FLAG_IMMUTABLE
        )
        val profit = NumberFormat.getCurrencyInstance(Locale.US).format(realizedProfit)
        val notification = NotificationCompat.Builder(context, CHANNEL_ID)
            .setSmallIcon(R.mipmap.ic_launcher)
            .setContentTitle(if (isTest) "Kassa! Test winstgeluid" else "Kassa! $symbol heeft het doel behaald")
            .setContentText(if (isTest) "Als je dit hoort, werkt het winstgeluid goed." else "De trade is gesloten met $profit gerealiseerde winst.")
            .setStyle(NotificationCompat.BigTextStyle().bigText(if (isTest) "Dit is alleen een geluidstest; er is geen trade uitgevoerd of gesloten." else "$symbol is automatisch gesloten nadat het winstdoel werd bereikt. Gerealiseerde winst: $profit."))
            .setContentIntent(pendingIntent)
            .setPriority(NotificationCompat.PRIORITY_HIGH)
            .setCategory(NotificationCompat.CATEGORY_STATUS)
            .setAutoCancel(true)
            .build()
        manager.notify(31_000 + (symbol.hashCode() and 0x0FFF), notification)
        val selected = soundOptions.firstOrNull { it.id == selectedSoundId(context) } ?: soundOptions.first()
        playOption(context, selected)
    }

    private fun playOption(context: Context, option: SoundOption) {
        CashSoundPlayer.play(context, option.resourceId)
    }
}

private object CashSoundPlayer {
    @Volatile private var activePlayer: MediaPlayer? = null

    fun play(context: Context, soundResource: Int) {
        runCatching {
            activePlayer?.release()
            val audioManager = context.getSystemService(Context.AUDIO_SERVICE) as AudioManager
            val attributes = AudioAttributes.Builder()
                .setUsage(AudioAttributes.USAGE_MEDIA)
                .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                .build()
            val focusRequest = AudioFocusRequest.Builder(AudioManager.AUDIOFOCUS_GAIN_TRANSIENT_MAY_DUCK)
                .setAudioAttributes(attributes)
                .build()
            audioManager.requestAudioFocus(focusRequest)

            val descriptor = context.resources.openRawResourceFd(soundResource)
            val player = MediaPlayer().apply {
                setAudioAttributes(attributes)
                setDataSource(descriptor.fileDescriptor, descriptor.startOffset, descriptor.length)
                descriptor.close()
                setOnCompletionListener {
                    audioManager.abandonAudioFocusRequest(focusRequest)
                    it.release()
                    if (activePlayer === it) activePlayer = null
                }
                setOnErrorListener { mediaPlayer, _, _ ->
                    audioManager.abandonAudioFocusRequest(focusRequest)
                    mediaPlayer.release()
                    if (activePlayer === mediaPlayer) activePlayer = null
                    true
                }
                prepare()
            }
            activePlayer = player
            player.start()
        }
    }
}
