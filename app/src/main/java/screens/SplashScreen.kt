package com.tradementor.app.screens

import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Image
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.alpha
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.res.painterResource
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import com.tradementor.app.R
import com.tradementor.app.BuildConfig

@Composable
fun SplashScreen() {
    var appeared by remember { mutableFloatStateOf(0f) }
    var progress by remember { mutableFloatStateOf(0f) }
    val intro by animateFloatAsState(appeared, tween(700, easing = FastOutSlowInEasing), label = "intro")
    val animatedProgress by animateFloatAsState(progress, tween(2700, easing = FastOutSlowInEasing), label = "load")
    val pulse by rememberInfiniteTransition(label = "logoPulse").animateFloat(
        initialValue = 0.96f,
        targetValue = 1.035f,
        animationSpec = infiniteRepeatable(tween(1100), RepeatMode.Reverse),
        label = "pulse"
    )

    LaunchedEffect(Unit) {
        appeared = 1f
        progress = 1f
    }

    Box(
        modifier = Modifier
            .fillMaxSize()
            .background(
                Brush.radialGradient(
                    colors = listOf(Color(0xFF101C38), Color(0xFF07101E), Color(0xFF05070B)),
                    radius = 1050f
                )
            )
            .padding(horizontal = 34.dp),
        contentAlignment = Alignment.Center
    ) {
        Box(
            modifier = Modifier
                .size(250.dp)
                .scale(pulse)
                .alpha(0.15f)
                .background(Color(0xFF2F68FF), RoundedCornerShape(80.dp))
        )

        Column(horizontalAlignment = Alignment.CenterHorizontally) {
            Image(
                painter = painterResource(R.drawable.tradementor_launcher_2027_tm),
                contentDescription = "TradeMentor-logo",
                modifier = Modifier
                    .size(188.dp)
                    .graphicsLayer {
                        scaleX = 0.78f + (intro * 0.22f)
                        scaleY = 0.78f + (intro * 0.22f)
                        rotationY = (1f - intro) * 36f
                        alpha = intro
                        cameraDistance = 16f * density
                    }
                    .clip(RoundedCornerShape(44.dp))
            )
            Spacer(Modifier.height(28.dp))
            Text(
                "TRADEMENTOR",
                color = Color.White,
                fontSize = 28.sp,
                fontWeight = FontWeight.ExtraBold,
                letterSpacing = 2.5.sp,
                modifier = Modifier.alpha(intro)
            )
            Spacer(Modifier.height(8.dp))
            Text(
                "SEE THE MARKET. MASTER THE MOVE.",
                color = Color(0xFF8C92A3),
                fontSize = 11.sp,
                fontWeight = FontWeight.SemiBold,
                letterSpacing = 1.2.sp,
                modifier = Modifier.alpha(intro)
            )
            Spacer(Modifier.height(24.dp))
            Surface(
                color = Color(0xCC0F192A),
                shape = RoundedCornerShape(20.dp),
                modifier = Modifier.fillMaxWidth().alpha(intro)
            ) {
                Column(
                    modifier = Modifier.padding(horizontal = 20.dp, vertical = 16.dp),
                    horizontalAlignment = Alignment.CenterHorizontally
                ) {
                    Text("LOVE TAUGHT ME ONE THING", color = Color(0xFFFFC857), fontSize = 9.sp, fontWeight = FontWeight.ExtraBold, letterSpacing = 1.4.sp)
                    Spacer(Modifier.height(7.dp))
                    Text("“Having no money is not an option.”", color = Color.White, fontSize = 15.sp, fontWeight = FontWeight.SemiBold)
                }
            }
            Spacer(Modifier.height(24.dp))
            LinearProgressIndicator(
                progress = { animatedProgress },
                modifier = Modifier.fillMaxWidth(0.62f).height(3.dp).clip(RoundedCornerShape(4.dp)),
                color = Color(0xFF08C887),
                trackColor = Color(0xFF1A2435)
            )
            Spacer(Modifier.height(12.dp))
            Text("MARKET INTELLIGENCE 2027", color = Color(0xFF55719E), fontSize = 10.sp, letterSpacing = 1.sp)
            Spacer(Modifier.height(8.dp))
            Text(
                "VERSIE ${BuildConfig.VERSION_NAME}  ·  BUILD ${BuildConfig.VERSION_CODE}",
                color = Color(0xFF71809A),
                fontSize = 9.sp,
                fontWeight = FontWeight.Medium,
                letterSpacing = 0.8.sp,
                modifier = Modifier.alpha(intro)
            )
        }
    }
}
