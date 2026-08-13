package com.tradementor.app.security

import android.content.Context
import android.util.Base64
import java.security.MessageDigest
import java.security.SecureRandom

object AppLockManager {
    private const val PREFS = "trade_mentor_app_lock"
    private const val KEY_ENABLED = "enabled"
    private const val KEY_SALT = "pin_salt"
    private const val KEY_HASH = "pin_hash"
    private const val KEY_BIOMETRIC = "biometric_enabled"

    fun isEnabled(context: Context): Boolean = prefs(context).getBoolean(KEY_ENABLED, false)

    fun setPin(context: Context, pin: String) {
        require(pin.length in 4..8 && pin.all(Char::isDigit))
        val salt = ByteArray(24).also { SecureRandom().nextBytes(it) }
        prefs(context).edit()
            .putString(KEY_SALT, encode(salt))
            .putString(KEY_HASH, encode(hash(pin, salt)))
            .putBoolean(KEY_ENABLED, true)
            .apply()
    }

    fun verifyPin(context: Context, pin: String): Boolean {
        val storedSalt = prefs(context).getString(KEY_SALT, null) ?: return false
        val storedHash = prefs(context).getString(KEY_HASH, null) ?: return false
        return runCatching {
            MessageDigest.isEqual(decode(storedHash), hash(pin, decode(storedSalt)))
        }.getOrDefault(false)
    }

    fun isBiometricEnabled(context: Context): Boolean =
        isEnabled(context) && prefs(context).getBoolean(KEY_BIOMETRIC, false)

    fun setBiometricEnabled(context: Context, enabled: Boolean) {
        prefs(context).edit().putBoolean(KEY_BIOMETRIC, enabled && isEnabled(context)).apply()
    }

    fun clear(context: Context) = prefs(context).edit().clear().apply()

    private fun prefs(context: Context) =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)

    private fun hash(pin: String, salt: ByteArray): ByteArray =
        MessageDigest.getInstance("SHA-256").digest(salt + pin.toByteArray(Charsets.UTF_8))

    private fun encode(value: ByteArray): String = Base64.encodeToString(value, Base64.NO_WRAP)
    private fun decode(value: String): ByteArray = Base64.decode(value, Base64.NO_WRAP)
}
