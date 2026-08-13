package com.tradementor.app.screens

import android.app.Activity
import android.content.Context
import android.content.ContextWrapper
import android.hardware.biometrics.BiometricManager
import android.hardware.biometrics.BiometricPrompt
import android.os.Build
import android.os.CancellationSignal
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.security.AppLockManager

@Composable
fun AppLockScreen(onUnlocked: () -> Unit) {
    val context = LocalContext.current
    var pin by remember { mutableStateOf("") }
    var message by remember { mutableStateOf("") }
    val biometricEnabled = remember { AppLockManager.isBiometricEnabled(context) }

    fun useBiometrics() {
        showBiometricPrompt(
            context = context,
            onSuccess = onUnlocked,
            onError = { message = it }
        )
    }

    LaunchedEffect(biometricEnabled) {
        if (biometricEnabled) useBiometrics()
    }

    Column(
        modifier = Modifier.fillMaxSize().background(Color(0xFF05070B)).padding(28.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
        verticalArrangement = Arrangement.Center
    ) {
        Text("TradeMentor vergrendeld", color = Color.White, fontSize = 27.sp, fontWeight = FontWeight.Bold)
        Spacer(Modifier.height(8.dp))
        Text("Ontgrendel met je persoonlijke code${if (biometricEnabled) " of biometrie" else ""}.", color = Color(0xFF9AA3B5))
        Spacer(Modifier.height(24.dp))
        OutlinedTextField(
            value = pin,
            onValueChange = { value -> pin = value.filter(Char::isDigit).take(8); message = "" },
            label = { Text("Code") },
            singleLine = true,
            visualTransformation = PasswordVisualTransformation(),
            keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.NumberPassword),
            modifier = Modifier.fillMaxWidth()
        )
        if (message.isNotBlank()) {
            Spacer(Modifier.height(8.dp))
            Text(message, color = Color(0xFFFF6B6B), fontSize = 13.sp)
        }
        Spacer(Modifier.height(16.dp))
        TradeMentorPrimaryButton(
            label = "Ontgrendelen",
            enabled = pin.length >= 4,
            onClick = {
                if (AppLockManager.verifyPin(context, pin)) onUnlocked()
                else message = "De ingevoerde code klopt niet."
            },
            modifier = Modifier.fillMaxWidth()
        )
        if (biometricEnabled) {
            Spacer(Modifier.height(10.dp))
            TradeMentorPrimaryButton(
                label = "Vingerafdruk of gezicht gebruiken",
                onClick = ::useBiometrics,
                modifier = Modifier.fillMaxWidth()
            )
        }
    }
}

private fun showBiometricPrompt(context: Context, onSuccess: () -> Unit, onError: (String) -> Unit) {
    if (Build.VERSION.SDK_INT < Build.VERSION_CODES.P) {
        onError("Biometrisch ontgrendelen wordt op dit Android-toestel niet ondersteund.")
        return
    }
    val activity = context.findActivity() ?: return onError("Biometrisch venster kon niet worden geopend.")
    val builder = BiometricPrompt.Builder(activity)
        .setTitle("TradeMentor ontgrendelen")
        .setSubtitle("Gebruik je vingerafdruk of gezicht")
        .setNegativeButton("Gebruik code", activity.mainExecutor) { _, _ -> }
    if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.R) {
        builder.setAllowedAuthenticators(BiometricManager.Authenticators.BIOMETRIC_WEAK)
    }
    builder.build().authenticate(
        CancellationSignal(),
        activity.mainExecutor,
        object : BiometricPrompt.AuthenticationCallback() {
            override fun onAuthenticationSucceeded(result: BiometricPrompt.AuthenticationResult?) = onSuccess()
            override fun onAuthenticationError(errorCode: Int, errString: CharSequence?) {
                if (errorCode != BiometricPrompt.BIOMETRIC_ERROR_USER_CANCELED) {
                    onError(errString?.toString() ?: "Biometrische controle is mislukt.")
                }
            }
            override fun onAuthenticationFailed() = onError("Niet herkend. Probeer opnieuw of gebruik je code.")
        }
    )
}

private tailrec fun Context.findActivity(): Activity? = when (this) {
    is Activity -> this
    is ContextWrapper -> baseContext.findActivity()
    else -> null
}
