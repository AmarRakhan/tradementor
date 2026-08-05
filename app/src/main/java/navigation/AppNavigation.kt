package com.tradementor.app.navigation

import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.platform.LocalContext
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleEventObserver
import androidx.lifecycle.LifecycleOwner
import com.tradementor.app.security.AppLockManager
import com.tradementor.app.BuildConfig
import com.google.firebase.auth.FirebaseAuth
import com.tradementor.app.cloud.CloudAccountRepository
import com.tradementor.app.cloud.CloudStateRepository
import com.tradementor.app.cloud.CloudOrderSafetyRepository
import com.tradementor.app.screens.AppLockScreen
import com.tradementor.app.screens.CloudAccountScreen
import com.tradementor.app.screens.MainScreen
import com.tradementor.app.screens.SplashScreen
import com.tradementor.app.screens.LanguageOnboardingScreen
import com.tradementor.app.localization.AppLanguage
import com.tradementor.app.localization.AppLanguageStore
import kotlinx.coroutines.delay
import com.tradementor.app.scanner.ScannerSession

@Composable
fun AppNavigation() {
    val context = LocalContext.current
    val firebaseAuth = remember { FirebaseAuth.getInstance() }
    var cloudUserId by remember { mutableStateOf(firebaseAuth.currentUser?.uid) }
    val legacyInstallation = remember {
        firebaseAuth.currentUser != null || AppLockManager.isEnabled(context) ||
            context.getSharedPreferences("main_navigation", android.content.Context.MODE_PRIVATE).all.isNotEmpty()
    }
    var languageChosen by remember { mutableStateOf(AppLanguageStore.isChosen(context) || legacyInstallation) }
    if (legacyInstallation && !AppLanguageStore.isChosen(context)) {
        AppLanguageStore.save(context, AppLanguage.Dutch)
    }

    val lockEnabledAtStart = remember { AppLockManager.isEnabled(context) }
    var locked by remember { mutableStateOf(lockEnabledAtStart) }
    var showSplash by remember { mutableStateOf(!lockEnabledAtStart) }

    DisposableEffect(context) {
        val owner = context as? LifecycleOwner
        val observer = LifecycleEventObserver { _, event ->
            if (event == Lifecycle.Event.ON_STOP && AppLockManager.isEnabled(context)) {
                locked = true
                showSplash = false
            }
        }
        owner?.lifecycle?.addObserver(observer)
        onDispose { owner?.lifecycle?.removeObserver(observer) }
    }

    DisposableEffect(firebaseAuth) {
        val listener = FirebaseAuth.AuthStateListener { cloudUserId = it.currentUser?.uid }
        firebaseAuth.addAuthStateListener(listener)
        onDispose { firebaseAuth.removeAuthStateListener(listener) }
    }

    LaunchedEffect(showSplash) {
        if (showSplash) {
            delay(3100)
            showSplash = false
        }
    }

    LaunchedEffect("scanner-preload") {
        ScannerSession.preload()
    }

    LaunchedEffect(cloudUserId) {
        if (cloudUserId != null) {
            CloudAccountRepository.bootstrapCloudSession()
            runCatching { CloudOrderSafetyRepository.verifyIdempotency(context) }
            while (true) {
                runCatching { CloudStateRepository.synchronize(context) }
                delay(5 * 60_000L)
            }
        }
    }

    if (!languageChosen) {
        LanguageOnboardingScreen { language ->
            AppLanguageStore.save(context, language)
            languageChosen = true
        }
    } else if (BuildConfig.CLOUD_ACCOUNTS_ENABLED && cloudUserId == null) {
        CloudAccountScreen()
    } else if (locked && AppLockManager.isEnabled(context)) {
        AppLockScreen(onUnlocked = {
            locked = false
            showSplash = true
        })
    } else if (showSplash) {
        SplashScreen()
    } else {
        MainScreen()
    }
}
