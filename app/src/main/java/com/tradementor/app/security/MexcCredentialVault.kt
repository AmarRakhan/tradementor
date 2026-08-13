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

object MexcCredentialVault {
    private const val ALIAS="tradementor_mexc_credentials"
    private const val PREFS="secure_mexc_credentials"
    fun configured(context:Context)=context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).contains("secret")
    fun keySuffix(context:Context)=context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).getString("suffix","").orEmpty()
    fun save(context:Context,apiKey:String,secret:String){require(apiKey.length>=8&&secret.length>=8){"API Key en Secret Key zijn ongeldig"}; val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.ENCRYPT_MODE,key());val encrypted=cipher.doFinal("$apiKey\n$secret".toByteArray());context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().putString("secret",Base64.encodeToString(encrypted,Base64.NO_WRAP)).putString("iv",Base64.encodeToString(cipher.iv,Base64.NO_WRAP)).putString("suffix",apiKey.takeLast(4)).apply()}
    fun read(context:Context):Pair<String,String>{val p=context.getSharedPreferences(PREFS,Context.MODE_PRIVATE);val cipher=Cipher.getInstance("AES/GCM/NoPadding");cipher.init(Cipher.DECRYPT_MODE,key(),GCMParameterSpec(128,Base64.decode(p.getString("iv",""),Base64.NO_WRAP)));val value=String(cipher.doFinal(Base64.decode(p.getString("secret",""),Base64.NO_WRAP))).split('\n',limit=2);return value[0] to value[1]}
    fun clear(context:Context)=context.getSharedPreferences(PREFS,Context.MODE_PRIVATE).edit().clear().apply()
    private fun key():SecretKey{val store=KeyStore.getInstance("AndroidKeyStore").apply{load(null)};(store.getKey(ALIAS,null)as?SecretKey)?.let{return it};return KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES,"AndroidKeyStore").apply{init(KeyGenParameterSpec.Builder(ALIAS,KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT).setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())}.generateKey()}
}
