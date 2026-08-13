package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.cloud.CloudAccountRepository
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorTextButton

@Composable
fun CloudAccountScreen() {
    var registering by remember { mutableStateOf(false) }
    var displayName by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var confirmPassword by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var message by remember { mutableStateOf("") }
    var messageIsError by remember { mutableStateOf(false) }

    fun showResult(result: Result<*>, successMessage: String = "") {
        busy = false
        messageIsError = result.isFailure
        message = result.exceptionOrNull()?.localizedMessage
            ?: successMessage
    }

    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.verticalGradient(
                    listOf(Color(0xFF101C38), Color(0xFF07101E), Color(0xFF05070B))
                )
            )
            .padding(horizontal = 24.dp),
        verticalArrangement = Arrangement.Center
    ) {
        Text("TRADEMENTOR", color = Color.White, fontSize = 29.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 2.sp)
        Spacer(Modifier.height(6.dp))
        Text(
            if (registering) "Maak je persoonlijke cloudaccount" else "Veilig aanmelden",
            color = Color(0xFF9DB4FF), fontSize = 15.sp, fontWeight = FontWeight.SemiBold
        )
        Spacer(Modifier.height(20.dp))
        Surface(color = Color(0xEE101722), shape = RoundedCornerShape(22.dp), modifier = Modifier.fillMaxWidth()) {
            Column(modifier = Modifier.padding(18.dp)) {
                if (registering) {
                    OutlinedTextField(
                        value = displayName,
                        onValueChange = { displayName = it.take(60); message = "" },
                        label = { Text("Naam") },
                        singleLine = true,
                        modifier = Modifier.fillMaxWidth()
                    )
                    Spacer(Modifier.height(10.dp))
                }
                OutlinedTextField(
                    value = email,
                    onValueChange = { email = it.trim().take(160); message = "" },
                    label = { Text("E-mailadres") },
                    singleLine = true,
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Email),
                    modifier = Modifier.fillMaxWidth()
                )
                Spacer(Modifier.height(10.dp))
                OutlinedTextField(
                    value = password,
                    onValueChange = { password = it.take(128); message = "" },
                    label = { Text("Wachtwoord") },
                    singleLine = true,
                    visualTransformation = PasswordVisualTransformation(),
                    keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                    modifier = Modifier.fillMaxWidth()
                )
                if (registering) {
                    Spacer(Modifier.height(10.dp))
                    OutlinedTextField(
                        value = confirmPassword,
                        onValueChange = { confirmPassword = it.take(128); message = "" },
                        label = { Text("Herhaal wachtwoord") },
                        singleLine = true,
                        visualTransformation = PasswordVisualTransformation(),
                        keyboardOptions = KeyboardOptions(keyboardType = KeyboardType.Password),
                        modifier = Modifier.fillMaxWidth()
                    )
                }
                if (message.isNotBlank()) {
                    Spacer(Modifier.height(10.dp))
                    Text(message, color = if (messageIsError) Color(0xFFFF7373) else Color(0xFF63D6A4), fontSize = 12.sp)
                }
                Spacer(Modifier.height(16.dp))
                TradeMentorPrimaryButton(
                    label = if (registering) "Account maken" else "Aanmelden",
                    onClick = {
                        when {
                            email.isBlank() || !email.contains('@') -> {
                                messageIsError = true; message = "Vul een geldig e-mailadres in."
                            }
                            password.length < 8 -> {
                                messageIsError = true; message = "Gebruik minimaal 8 tekens voor je wachtwoord."
                            }
                            registering && displayName.isBlank() -> {
                                messageIsError = true; message = "Vul je naam in."
                            }
                            registering && password != confirmPassword -> {
                                messageIsError = true; message = "De wachtwoorden zijn niet gelijk."
                            }
                            else -> {
                                busy = true; message = ""
                                if (registering) {
                                    CloudAccountRepository.register(email, password, displayName) {
                                        showResult(it, "Account gemaakt. Controleer ook je verificatiemail.")
                                    }
                                } else {
                                    CloudAccountRepository.signIn(email, password) { showResult(it) }
                                }
                            }
                        }
                    },
                    enabled = !busy,
                    modifier = Modifier.fillMaxWidth()
                )
                if (busy) {
                    CircularProgressIndicator(color = Color.White, strokeWidth = 2.dp)
                }
                if (!registering) {
                    TradeMentorTextButton(
                        label = "Wachtwoord vergeten?",
                        onClick = {
                            if (!email.contains('@')) {
                                messageIsError = true; message = "Vul eerst je e-mailadres in."
                            } else {
                                busy = true
                                CloudAccountRepository.sendPasswordReset(email) {
                                    showResult(it, "Herstellink verzonden. Controleer je e-mail.")
                                }
                            }
                        },
                        modifier = Modifier.align(Alignment.End),
                        enabled = !busy
                    )
                }
            }
        }
        Spacer(Modifier.height(12.dp))
        Row(modifier = Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
            Text(if (registering) "Heb je al een account?" else "Nog geen TradeMentor-account?", color = Color(0xFF8C92A3), fontSize = 12.sp)
            TradeMentorTextButton(onClick = {
                registering = !registering
                password = ""
                confirmPassword = ""
                message = ""
            }, label = if (registering) "Aanmelden" else "Registreren")
        }
        Text(
            "Gebruik een uniek wachtwoord. TradeMentor vraagt nooit om je seed phrase of hoofdwallet-private key.",
            color = Color(0xFF71809A), fontSize = 10.sp, lineHeight = 15.sp
        )
    }
}
