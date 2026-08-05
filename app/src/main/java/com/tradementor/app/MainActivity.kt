package com.tradementor.app

import android.os.Bundle
import android.os.Build
import android.Manifest
import android.content.pm.PackageManager
import androidx.activity.compose.setContent
import androidx.fragment.app.FragmentActivity
import com.tradementor.app.navigation.AppNavigation
import com.tradementor.app.ui.theme.TradeMentorTheme
import com.tradementor.app.scanner.BackgroundScanConfig
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.NotificationMode
import com.tradementor.app.scanner.NotificationStyle

class MainActivity : FragmentActivity() {

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)

        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.TIRAMISU &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            requestPermissions(arrayOf(Manifest.permission.POST_NOTIFICATIONS), 2027)
        }

        val existingScanner = BackgroundScannerScheduler.load(this)
        BackgroundScannerScheduler.update(
            this,
            existingScanner ?: BackgroundScanConfig(
                enabled = true,
                strategyName = "TradeMentor consensus",
                requireAll = true,
                conditions = emptyList(),
                intervalMinutes = 15,
                notificationMode = NotificationMode.NewMatches,
                notificationStyle = NotificationStyle.Silent
            )
        )

        setContent {
            TradeMentorTheme {
                AppNavigation()
            }
        }
    }
}
