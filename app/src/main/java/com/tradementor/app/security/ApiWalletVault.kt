package com.tradementor.app.security

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec

object ApiWalletVault {
    private const val ALIAS = "tradementor_hyperliquid_api_wallet"
    private const val PREFS = "secure_api_wallet"

    fun isConfigured(context: Context): Boolean =
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).contains("encrypted_key") &&
            address(context).matches(Regex("^0x[0-9a-fA-F]{40}$"))

    fun isApproved(context: Context): Boolean = isConfigured(context) &&
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getBoolean("mainnet_cloud_approved", false)

    fun setApproved(context: Context, approved: Boolean) {
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean("mainnet_cloud_approved", approved).apply()
    }

    fun address(context: Context): String = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        .getString("address", "").orEmpty()

    fun save(context: Context, address: String, privateKey: String) {
        require(address.matches(Regex("^0x[0-9a-fA-F]{40}$"))) { "Ongeldig API-walletadres" }
        val cleanKey = privateKey.removePrefix("0x")
        require(cleanKey.matches(Regex("^[0-9a-fA-F]{64}$"))) { "Ongeldige API-walletsleutel" }
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.ENCRYPT_MODE, secretKey())
        val encrypted = cipher.doFinal(cleanKey.toByteArray(Charsets.UTF_8))
        context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit()
            .putString("address", address.lowercase())
            .putString("encrypted_key", Base64.encodeToString(encrypted, Base64.NO_WRAP))
            .putString("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
            .apply()
    }

    fun clear(context: Context) = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().clear().apply()

    internal fun privateKey(context: Context): String {
        val prefs = context.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        val encrypted = Base64.decode(prefs.getString("encrypted_key", ""), Base64.NO_WRAP)
        val iv = Base64.decode(prefs.getString("iv", ""), Base64.NO_WRAP)
        val cipher = Cipher.getInstance("AES/GCM/NoPadding")
        cipher.init(Cipher.DECRYPT_MODE, secretKey(), GCMParameterSpec(128, iv))
        return cipher.doFinal(encrypted).toString(Charsets.UTF_8)
    }

    private fun secretKey(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        (store.getKey(ALIAS, null) as? SecretKey)?.let { return it }
        return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore").apply {
            init(KeyGenParameterSpec.Builder(ALIAS, KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
                .setBlockModes(KeyProperties.BLOCK_MODE_GCM)
                .setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE)
                .build())
        }.generateKey()
    }
}
