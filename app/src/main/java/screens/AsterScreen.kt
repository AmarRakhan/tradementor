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
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp

private val AsterBackground = Color(0xFF05070B)
private val AsterCard = Color(0xFF101A2A)
private val AsterAccent = Color(0xFFB78BFF)
private val AsterMuted = Color(0xFF8C92A3)

@Composable
fun AsterScreen() {
    Column(
        modifier = Modifier
            .fillMaxSize()
            .background(AsterBackground)
            .verticalScroll(rememberScrollState())
            .padding(horizontal = 16.dp, vertical = 18.dp)
    ) {
        Text(
            text = "ASTER",
            color = Color.White,
            fontSize = 29.sp,
            fontWeight = FontWeight.ExtraBold,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
        Text(
            text = "Futures · Hedge Mode · multi-pair",
            color = AsterMuted,
            fontSize = 11.sp,
            textAlign = TextAlign.Center,
            modifier = Modifier.fillMaxWidth(),
        )
        Spacer(Modifier.height(16.dp))

        Surface(color = Color(0xFF231B35), shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
            Column(Modifier.padding(16.dp)) {
                Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.SpaceBetween) {
                    Text("BOTSTATUS", color = AsterAccent, fontSize = 10.sp, fontWeight = FontWeight.Black)
                    Text("UIT", color = Color(0xFFFFC857), fontSize = 10.sp, fontWeight = FontWeight.Black)
                }
                Text(
                    "Aster trading is nog niet geconfigureerd. Alleen het openen van deze pagina kan nooit een order starten.",
                    color = Color.White,
                    fontSize = 13.sp,
                    lineHeight = 19.sp,
                    modifier = Modifier.padding(top = 8.dp),
                )
            }
        }
        Spacer(Modifier.height(12.dp))

        AsterStatusCard("VERBINDING", "Niet gekoppeld", "API-authenticatie en actuele account-synchronisatie zijn vereist.")
        Spacer(Modifier.height(10.dp))
        AsterStatusCard("HEDGE MODE", "Niet bevestigd", "Nieuwe exposure blijft geblokkeerd totdat Dual Side/Hedge Mode door Aster is bevestigd.")
        Spacer(Modifier.height(10.dp))
        AsterStatusCard("PORTFOLIO RISK", "Niet gereed", "Orderuitvoering blijft uit totdat risk budget, emergency reserve en reconciliation slagen.")
        Spacer(Modifier.height(24.dp))
    }
}

@Composable
private fun AsterStatusCard(title: String, status: String, explanation: String) {
    Surface(color = AsterCard, shape = RoundedCornerShape(18.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(16.dp)) {
            Text(title, color = AsterAccent, fontSize = 10.sp, fontWeight = FontWeight.Black)
            Text(status, color = Color.White, fontSize = 17.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp))
            Text(explanation, color = AsterMuted, fontSize = 11.sp, lineHeight = 16.sp, modifier = Modifier.padding(top = 5.dp))
        }
    }
}
