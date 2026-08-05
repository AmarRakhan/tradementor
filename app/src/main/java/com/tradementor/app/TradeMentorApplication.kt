package com.tradementor.app

import android.app.Application
import com.reown.android.Core
import com.reown.android.CoreClient
import com.reown.android.relay.ConnectionType
import com.reown.appkit.client.AppKit
import com.reown.appkit.client.Modal
import com.reown.appkit.presets.AppKitChainsPresets
import com.tradementor.app.security.MetaMaskAgentApproval
import com.tradementor.app.scanner.AutoTradingStore
import com.tradementor.app.scanner.BackgroundScannerScheduler
import com.tradementor.app.scanner.ScannerProgressStore
import com.tradementor.app.scanner.TradeHistoryStore

class TradeMentorApplication : Application() {
    override fun onCreate() {
        super.onCreate()

        val cleanupPrefs = getSharedPreferences("data_repairs", MODE_PRIVATE)
        if (!cleanupPrefs.getBoolean("public_scanner_upgrade_202", false)) {
            // Clear only a stale scanner terminal state from older public builds.
            // Account, wallet, history and learning data remain untouched.
            AutoTradingStore.setEnabled(this, false)
            ScannerProgressStore.update(
                this, "idle", summary = "Update voltooid · Scan & Buy kan veilig worden gestart"
            )
            cleanupPrefs.edit().putBoolean("public_scanner_upgrade_202", true).apply()
        }
        if (!cleanupPrefs.getBoolean("unconfirmed_scanner_records_208", false)) {
            TradeHistoryStore.removeUnconfirmedScannerRecordsBefore(this, 1785833700000L)
            cleanupPrefs.edit().putBoolean("unconfirmed_scanner_records_208", true).apply()
        }
        if (!cleanupPrefs.getBoolean("phantom_wins_209", false)) {
            TradeHistoryStore.removeByIds(
                this,
                setOf(
                    1785827130752L, 1785827063402L, 1785826560569L, 1785826330403L,
                    1785826317013L, 1785825274815L, 1785824104407L, 1785824005078L
                )
            )
            cleanupPrefs.edit().putBoolean("phantom_wins_209", true).apply()
        }

        // App updates can replace WorkManager's scheduled job while preserving
        // the user's Scan & Buy preference. Always restore the periodic worker
        // when automatic trading is still enabled.
        if (AutoTradingStore.isEnabled(this)) {
            BackgroundScannerScheduler.refresh(this)
        }

        val metadata = Core.Model.AppMetaData(
            name = "TradeMentor",
            description = "Market intelligence en beveiligd Hyperliquid-handelen",
            url = "https://hyperedge.app",
            icons = listOf("https://reown.com/favicon.ico"),
            redirect = BuildConfig.WALLET_REDIRECT
        )

        CoreClient.initialize(
            application = this,
            projectId = BuildConfig.REOWN_PROJECT_ID,
            metaData = metadata,
            connectionType = ConnectionType.AUTOMATIC,
            onError = { }
        )
        AppKit.initialize(
            init = Modal.Params.Init(core = CoreClient),
            onSuccess = {
                AppKit.setChains(AppKitChainsPresets.ethChains.values.toList())
                AppKit.setDelegate(object : AppKit.ModalDelegate {
                    override fun onSessionApproved(approvedSession: Modal.Model.ApprovedSession) = Unit
                    override fun onSessionRejected(rejectedSession: Modal.Model.RejectedSession) = MetaMaskAgentApproval.fail("MetaMask-koppeling geweigerd.")
                    override fun onSessionUpdate(updatedSession: Modal.Model.UpdatedSession) = Unit
                    override fun onSessionEvent(sessionEvent: Modal.Model.SessionEvent) = Unit
                    override fun onSessionExtend(session: Modal.Model.Session) = Unit
                    override fun onSessionDelete(deletedSession: Modal.Model.DeletedSession) = MetaMaskAgentApproval.fail("Walletverbinding verbroken.")
                    override fun onSessionRequestResponse(response: Modal.Model.SessionRequestResponse) = MetaMaskAgentApproval.handleResponse(response)
                    override fun onProposalExpired(expiredProposal: Modal.Model.ExpiredProposal) = MetaMaskAgentApproval.fail("MetaMask-verzoek verlopen.")
                    override fun onRequestExpired(expiredRequest: Modal.Model.ExpiredRequest) = MetaMaskAgentApproval.fail("MetaMask-verzoek verlopen.")
                    override fun onConnectionStateChange(state: Modal.Model.ConnectionState) = Unit
                    override fun onError(error: Modal.Model.Error) = MetaMaskAgentApproval.fail(error.throwable.message ?: "Walletfout")
                })
            },
            onError = { }
        )
    }
}
