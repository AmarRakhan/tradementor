"""Global order gate for the Aster Portfolio Noodhedge.

P0 safety kill switch (2026-09-16): Portfolio Noodhedge is disabled. Persisted
EXECUTING/LOCKED state must never block normal trading or a user-requested
CLOSE while the feature is disabled.
"""
from __future__ import annotations

from typing import Any

from aster_gateway import AsterOrderIntent, AsterValidationError, AsterV3Client

COLLECTION = "aster_portfolio_emergency_hedges"
EMERGENCY_PREFIX = "tm-eh-"
BLOCKED_STATUSES = {"EXECUTING", "LOCKED"}

# P0: entire Portfolio Noodhedge feature is disabled until explicitly restored
# in a reviewed change. Keep this server-side; the UI is not a safety boundary.
FEATURE_ENABLED = False


def emergency_blocks(state: dict[str, Any] | None, intent: AsterOrderIntent) -> bool:
    """Return whether one non-emergency order must be blocked by persisted state."""
    if not FEATURE_ENABLED:
        return False

    data = state if isinstance(state, dict) else {}
    status = str(data.get("status", "OFF")).upper().strip()
    if not bool(data.get("enabled", False)) or status not in BLOCKED_STATUSES:
        return False
    if str(intent.intent_id).startswith(EMERGENCY_PREFIX):
        return False
    # Risk-reducing manual exits must never be blocked by Portfolio Noodhedge.
    if intent.action == "CLOSE":
        return False
    return True


def install(main_module: Any) -> None:
    """Patch the established per-user Aster client guards exactly once."""
    if bool(getattr(main_module, "_portfolio_emergency_guard_installed", False)):
        return

    original_close_guard_factory = main_module._block_order_during_close_all

    def combined_guard_factory(uid: str):
        close_guard = original_close_guard_factory(uid)

        def guard(intent: AsterOrderIntent) -> None:
            close_guard(intent)
            # P0 kill switch: do not even consult stale emergency Firestore state.
            # This guarantees old EXECUTING/LOCKED documents cannot block CLOSE,
            # DCA, auto-restart or other established order routing.
            if not FEATURE_ENABLED:
                return

            # Closing exposure is always allowed if Firestore is temporarily
            # unavailable; risk-increasing OPENs fail closed in that situation.
            try:
                state = main_module.db.collection(COLLECTION).document(uid).get().to_dict() or {}
            except Exception as exc:
                if intent.action == "CLOSE":
                    return
                raise AsterValidationError(
                    "Portfolio Noodhedge-status is tijdelijk onbekend; nieuwe Aster-exposure is geblokkeerd"
                ) from exc
            if emergency_blocks(state, intent):
                status = str(state.get("status", "OFF")).upper().strip()
                if status == "EXECUTING":
                    raise AsterValidationError(
                        "Portfolio Noodhedge EXECUTING: alle niet-noodhedge orders zijn tijdelijk geblokkeerd"
                    )
                raise AsterValidationError(
                    "Portfolio LOCKED: nieuwe Aster-exposure, DCA en auto-restart zijn geblokkeerd"
                )

        return guard

    main_module._block_order_during_close_all = combined_guard_factory

    # This helper is used by explicit portfolio/profit close flows and did not
    # previously carry the close-all order hook. Rebuild it with the same
    # combined hook so a user-driven CLOSE remains available.
    def portfolio_growth_client(user: dict[str, Any], *, live: bool) -> AsterV3Client:
        secret = main_module.load_aster_secret(user)
        uid = str(user["uid"])
        return AsterV3Client(
            signer_address=secret.signer_address,
            sign_message=main_module.local_eip712_signer(secret),
            live_authorized=live,
            before_order_submit=combined_guard_factory(uid) if live else None,
        )

    main_module._portfolio_growth_client = portfolio_growth_client
    main_module._portfolio_emergency_guard_installed = True
