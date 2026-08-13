package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.BuildConfig
import com.tradementor.app.cloud.FeedbackReport
import com.tradementor.app.cloud.FeedbackRepository
import com.tradementor.app.components.TradeMentorPrimaryButton
import com.tradementor.app.components.TradeMentorGhostButton
import kotlinx.coroutines.launch

private val FeedbackBg = Color(0xFF05070B)
private val FeedbackCard = Color(0xFF101722)
private val FeedbackGreen = Color(0xFF08C887)
private val FeedbackMuted = Color(0xFF8C92A3)

@Composable
fun FeedbackScreen(onBack: () -> Unit) {
    val repository = remember { FeedbackRepository() }
    val scope = rememberCoroutineScope()
    var reports by remember { mutableStateOf<List<FeedbackReport>>(emptyList()) }
    var loading by remember { mutableStateOf(true) }
    var message by remember { mutableStateOf("") }
    var adminInbox by remember { mutableStateOf(BuildConfig.ADMIN_FEATURES) }
    var category by remember { mutableStateOf("bug") }
    var title by remember { mutableStateOf("") }
    var description by remember { mutableStateOf("") }
    var screen by remember { mutableStateOf("") }

    fun reload() {
        scope.launch {
            loading = true
            runCatching { if (adminInbox) repository.listAdmin() else repository.listMine() }
                .onSuccess { reports = it; message = "" }
                .onFailure { message = it.message ?: "Feedback kon niet worden geladen." }
            loading = false
        }
    }
    LaunchedEffect(adminInbox) { reload() }

    LazyColumn(
        modifier = Modifier.fillMaxSize().background(FeedbackBg).statusBarsPadding().padding(horizontal = 18.dp),
        verticalArrangement = Arrangement.spacedBy(12.dp)
    ) {
        item {
            TradeMentorPrimaryButton(
                label = "← Terug naar instellingen",
                onClick = onBack,
                modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
            )
            Text("Feedback & problemen", color = Color.White, fontSize = 28.sp, fontWeight = FontWeight.ExtraBold, modifier = Modifier.padding(top = 16.dp))
            Text("Meld een bug, wens of verbetering. Geheime sleutels en wachtwoorden worden nooit meegestuurd.", color = FeedbackMuted, fontSize = 12.sp)
        }

        if (BuildConfig.ADMIN_FEATURES) item {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                FeedbackModeButton("Admin-inbox", adminInbox) { adminInbox = true }
                FeedbackModeButton("Mijn meldingen", !adminInbox) { adminInbox = false }
            }
        }

        if (!adminInbox) item {
            Surface(color = FeedbackCard, shape = RoundedCornerShape(18.dp)) {
                Column(Modifier.padding(16.dp)) {
                    Text("NIEUWE MELDING", color = FeedbackGreen, fontSize = 11.sp, fontWeight = FontWeight.Black)
                    Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                        listOf("bug" to "Bug", "wish" to "Wens", "improvement" to "Verbetering", "removal" to "Verwijderen").forEach { (value, label) ->
                            Surface(
                                color = if (category == value) Color(0xFF2F68FF) else Color(0xFF192131),
                                shape = RoundedCornerShape(10.dp),
                                modifier = Modifier.clickable { category = value }
                            ) { Text(label, color = Color.White, fontSize = 11.sp, modifier = Modifier.padding(horizontal = 9.dp, vertical = 8.dp)) }
                        }
                    }
                    OutlinedTextField(title, { title = it.take(120) }, label = { Text("Korte titel") }, modifier = Modifier.fillMaxWidth().padding(top = 10.dp))
                    OutlinedTextField(description, { description = it.take(4000) }, label = { Text("Wat gebeurde er of wat wil je veranderen?") }, minLines = 4, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                    OutlinedTextField(screen, { screen = it.take(80) }, label = { Text("Op welk scherm? (optioneel)") }, modifier = Modifier.fillMaxWidth().padding(top = 8.dp))
                    TradeMentorPrimaryButton(
                        enabled = title.trim().length >= 4 && description.trim().length >= 10,
                        label = "Melding verzenden",
                        onClick = {
                            scope.launch {
                                message = "Melding veilig verzenden…"
                                runCatching { repository.submit(category, title, description, screen) }
                                    .onSuccess {
                                        title = ""; description = ""; screen = ""
                                        message = "Bedankt! Je melding is veilig ontvangen."
                                        reports = repository.listMine()
                                    }
                                    .onFailure { message = it.message ?: "Melding kon niet worden verzonden." }
                            }
                        },
                        modifier = Modifier.fillMaxWidth().padding(top = 12.dp)
                    )
                }
            }
        }

        if (message.isNotBlank()) item { Text(message, color = Color(0xFF9DB4FF), fontSize = 12.sp) }
        item {
            Text(if (adminInbox) "ALLE MELDINGEN" else "MIJN MELDINGEN", color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold)
            if (loading) Text("Laden…", color = FeedbackMuted, fontSize = 12.sp)
            else if (reports.isEmpty()) Text("Nog geen meldingen.", color = FeedbackMuted, fontSize = 12.sp)
        }
        items(reports, key = { it.id }) { report ->
            FeedbackReportCard(report, adminInbox) { status ->
                scope.launch {
                    runCatching { repository.updateStatus(report.id, status) }
                        .onSuccess { reload() }
                        .onFailure { message = it.message ?: "Status kon niet worden bijgewerkt." }
                }
            }
        }
        item { Spacer(Modifier.height(30.dp)) }
    }
}

@Composable
private fun FeedbackModeButton(label: String, selected: Boolean, onClick: () -> Unit) {
    if (selected) {
        TradeMentorPrimaryButton(label = label, onClick = onClick, modifier = Modifier.fillMaxWidth())
    } else {
        TradeMentorGhostButton(label = label, onClick = onClick, modifier = Modifier.fillMaxWidth())
    }
}

@Composable
private fun FeedbackReportCard(report: FeedbackReport, admin: Boolean, onStatus: (String) -> Unit) {
    Surface(color = FeedbackCard, shape = RoundedCornerShape(16.dp), modifier = Modifier.fillMaxWidth()) {
        Column(Modifier.padding(15.dp)) {
            Row(Modifier.fillMaxWidth()) {
                Text(categoryLabel(report.category), color = FeedbackGreen, fontSize = 10.sp, fontWeight = FontWeight.Black, modifier = Modifier.weight(1f))
                Text(statusLabel(report.status), color = statusColor(report.status), fontSize = 10.sp, fontWeight = FontWeight.Black)
            }
            Text(report.title, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.Bold, modifier = Modifier.padding(top = 5.dp))
            Text(report.description, color = Color(0xFFD4D8E2), fontSize = 12.sp, modifier = Modifier.padding(top = 6.dp))
            val technical = listOf(report.screen, "v${report.appVersion} · build ${report.buildNumber}", report.deviceModel, report.androidVersion).filter { it.isNotBlank() }
            Text(technical.joinToString(" · "), color = FeedbackMuted, fontSize = 9.sp, modifier = Modifier.padding(top = 9.dp))
            if (admin && report.userEmail.isNotBlank()) Text(report.userEmail, color = Color(0xFF9DB4FF), fontSize = 9.sp, modifier = Modifier.padding(top = 4.dp))
            if (report.adminNote.isNotBlank()) Text("Reactie: ${report.adminNote}", color = Color(0xFFFFC857), fontSize = 11.sp, modifier = Modifier.padding(top = 8.dp))
            if (admin) Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                listOf("reviewed" to "Bekeken", "planned" to "Gepland", "in_progress" to "Bezig", "resolved" to "Opgelost").forEach { (value, label) ->
                    Surface(color = if (report.status == value) Color(0xFF2F68FF) else Color(0xFF20293A), shape = RoundedCornerShape(8.dp), modifier = Modifier.clickable { onStatus(value) }) {
                        Text(label, color = Color.White, fontSize = 9.sp, modifier = Modifier.padding(horizontal = 7.dp, vertical = 7.dp))
                    }
                }
            }
        }
    }
}

private fun categoryLabel(value: String) = when (value) { "bug" -> "BUG"; "wish" -> "WENS"; "improvement" -> "VERBETERING"; else -> "VERWIJDEREN" }
private fun statusLabel(value: String) = when (value) { "new" -> "NIEUW"; "reviewed" -> "BEKEKEN"; "planned" -> "GEPLAND"; "in_progress" -> "BEZIG"; "resolved" -> "OPGELOST"; else -> "AFGEWEZEN" }
private fun statusColor(value: String) = when (value) { "resolved" -> FeedbackGreen; "in_progress", "planned" -> Color(0xFFFFC857); "new" -> Color(0xFFFF657D); else -> FeedbackMuted }
