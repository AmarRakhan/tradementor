package com.tradementor.app.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.localization.AppLanguage
import com.tradementor.app.localization.languageFlag
import com.tradementor.app.localization.orderedLanguages
import com.tradementor.app.components.TradeMentorPrimaryButton

@Composable
fun LanguageOnboardingScreen(onConfirmed: (AppLanguage) -> Unit) {
    var selected by remember { mutableStateOf(AppLanguage.English) }
    Column(Modifier.fillMaxSize().background(Color(0xFF05070B)).padding(horizontal = 20.dp, vertical = 28.dp)) {
        Text("TRADEMENTOR", color = Color(0xFF63D6A4), fontSize = 12.sp, fontWeight = FontWeight.Black, letterSpacing = 2.sp, modifier = Modifier.fillMaxWidth(), textAlign = TextAlign.Center)
        Text("Kies je taal", color = Color.White, fontSize = 30.sp, fontWeight = FontWeight.Black, modifier = Modifier.fillMaxWidth().padding(top = 12.dp), textAlign = TextAlign.Center)
        Text("Choose your language", color = Color(0xFF8C92A3), fontSize = 14.sp, modifier = Modifier.fillMaxWidth().padding(top = 4.dp), textAlign = TextAlign.Center)
        Spacer(Modifier.height(18.dp))
        LazyColumn(Modifier.weight(1f)) {
            items(orderedLanguages(), key = { it.code }) { language ->
                Surface(
                    color = if (selected == language) Color(0xFF123B34) else Color(0xFF101722),
                    shape = RoundedCornerShape(14.dp),
                    modifier = Modifier.fillMaxWidth().padding(vertical = 4.dp).clickable { selected = language }
                ) {
                    Row(Modifier.fillMaxWidth().padding(horizontal = 16.dp, vertical = 14.dp)) {
                        Text(language.nativeName, color = Color.White, fontSize = 16.sp, fontWeight = FontWeight.SemiBold, modifier = Modifier.weight(1f))
                        Text("${languageFlag(language)}${if (selected == language) "   ✓" else ""}", color = Color(0xFF63D6A4), fontWeight = FontWeight.Black)
                    }
                }
            }
        }
        TradeMentorPrimaryButton(
            label = if (selected == AppLanguage.Dutch) "Doorgaan" else "Continue",
            onClick = { onConfirmed(selected) },
            modifier = Modifier.fillMaxWidth().height(54.dp)
        )
    }
}
