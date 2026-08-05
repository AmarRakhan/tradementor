package com.tradementor.app.cloud

enum class AccountTier { Free, Pro, Admin }

enum class CloudFeature {
    LiveWallet, RiskDashboard, BackgroundScanner, AutomaticOrders, AddOnOrders, CloudSync
}

data class CloudEntitlements(
    val tier: AccountTier = AccountTier.Free,
    val active: Boolean = true,
    val features: Set<CloudFeature> = setOf(CloudFeature.LiveWallet, CloudFeature.RiskDashboard),
    val verifiedAt: Long? = null
) {
    fun permits(feature: CloudFeature): Boolean = active && feature in features
}

data class CloudUserSession(
    val uid: String,
    val email: String? = null,
    val entitlements: CloudEntitlements = CloudEntitlements()
)

/**
 * Billing is intentionally not trusted on-device. Later, Google Play purchase
 * tokens are sent to the server and only verified server entitlements unlock
 * paid functionality.
 */
object CloudReadiness {
    const val BILLING_ENABLED = false
    const val CLOUD_ORDERS_ENABLED = false
}
