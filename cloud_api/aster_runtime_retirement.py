"""Machine-readable retirement contract for Aster runtime modernization.

Nothing in this module changes trading behavior. It exists so a replacement is
not considered complete while its legacy path remains indefinitely active.
"""

RETIREMENT_ITEMS = (
    {
        "id": "SOFTWARE_TP_TRIGGER",
        "legacy": "Multi-BB mark-price TP trigger + software close submission",
        "replacement": "exchange-native reduce-only TP lifecycle",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "shadow price/quantity parity",
            "Auto Hedge lock parity",
            "live canary success",
            "restart/reconciliation proof",
        ),
        "removeWhen": "native TP is production-proven and rollback window has expired",
    },
    {
        "id": "SOFTWARE_DCA_TRIGGER",
        "legacy": "Multi-BB mark-price next-DCA trigger + software OPEN submission",
        "replacement": "one exchange-native next-DCA order with fill-driven rearm",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "shadow trigger parity",
            "margin/leverage guard parity",
            "config-change cancel/replace proof",
            "live canary success",
        ),
        "removeWhen": "native next-DCA lifecycle is production-proven and rollback window has expired",
    },
    {
        "id": "DUPLICATE_ASTER_STATUS_POLLING",
        "legacy": "multiple UI bridges independently polling the same Aster account/status truth",
        "replacement": "one shared realtime Aster client state with bounded reconciliation",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "shared-state parity",
            "no stale UI regression",
            "reconnect/focus recovery proof",
        ),
        "removeWhen": "all consumers read the shared state and direct duplicate pollers have zero callers",
    },
    {
        "id": "PER_INSTANCE_REALTIME_WORKER",
        "legacy": "each autoscaled API instance starts its own realtime Aster worker",
        "replacement": "singleton/dedicated realtime worker",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "worker ownership proof",
            "failover proof",
            "order-safety lock parity",
        ),
        "removeWhen": "dedicated worker is production-proven and API instances no longer own realtime work",
    },
    {
        "id": "PER_INSTANCE_PERIODIC_WORKER",
        "legacy": "each API instance runs the periodic scheduler loop and competes for a distributed minute claim",
        "replacement": "single scheduler/reconciliation owner",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "single-owner scheduler proof",
            "missed-tick recovery proof",
            "lease/idempotency parity",
        ),
        "removeWhen": "single-owner scheduler is production-proven and duplicate loops are disabled",
    },
    {
        "id": "UNBOUNDED_RELEASE_RETENTION",
        "legacy": "candidate tags/revisions/images accumulate across releases",
        "replacement": "bounded rollback retention policy",
        "status": "ACTIVE_LEGACY",
        "removalGate": (
            "protected revision list",
            "rollback drill",
            "artifact age/usage audit",
        ),
        "removeWhen": "retention policy is approved and protected rollback artifacts are explicitly excluded",
    },
)


def retirement_contract() -> dict:
    items = [dict(item) for item in RETIREMENT_ITEMS]
    return {
        "version": 1,
        "policy": "REPLACEMENT_IS_NOT_DONE_UNTIL_LEGACY_IS_REMOVED",
        "items": items,
        "activeLegacyCount": sum(1 for item in items if item["status"] == "ACTIVE_LEGACY"),
        "retiredCount": sum(1 for item in items if item["status"] == "RETIRED"),
    }
