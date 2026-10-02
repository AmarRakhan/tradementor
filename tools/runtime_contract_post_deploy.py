from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


MAX_ACCOUNT_TICK_AGE_MS = 240_000
MAX_SCANNER_AGE_MS = 240_000


def _i(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _b(value: Any) -> bool:
    return value is True


def _row_map(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {
        str(row.get("accountRef") or ""): row
        for row in rows
        if isinstance(row, dict) and str(row.get("accountRef") or "")
    }


@dataclass(frozen=True)
class RuntimeGateResult:
    ok: bool
    failures: tuple[str, ...]
    warnings: tuple[str, ...]

    def public_dict(self) -> dict[str, Any]:
        return {
            "ok": self.ok,
            "failures": list(self.failures),
            "warnings": list(self.warnings),
        }


def evaluate_runtime_contract(
    before: dict[str, Any],
    after: dict[str, Any],
    *,
    now_ms: int,
) -> RuntimeGateResult:
    failures: list[str] = []
    warnings: list[str] = []

    if not _b(after.get("serviceReady")):
        failures.append("SERVICE_NOT_READY")
    if not _b(after.get("backgroundCpuEnabled")):
        failures.append("BACKGROUND_CPU_DISABLED")
    if _i(after.get("minInstances")) < 1:
        failures.append("NO_WARM_INSTANCE")
    if not _b(after.get("periodicWorkerRecent")):
        failures.append("PERIODIC_WORKER_HEARTBEAT_MISSING")
    if _i(after.get("periodicWorkerErrors")) > _i(before.get("periodicWorkerErrors")):
        failures.append("PERIODIC_WORKER_ERRORS_REGRESSED")

    before_rows = _row_map(before.get("accounts") if isinstance(before.get("accounts"), list) else [])
    after_rows = _row_map(after.get("accounts") if isinstance(after.get("accounts"), list) else [])

    for account_ref, previous in sorted(before_rows.items()):
        current = after_rows.get(account_ref)
        if current is None:
            failures.append(f"{account_ref}:MONITORED_ACCOUNT_MISSING")
            continue
        if not _b(current.get("monitor")):
            # A deploy must never silently stop monitoring an account that was monitored before.
            if _b(previous.get("monitor")):
                failures.append(f"{account_ref}:MONITOR_DISABLED_AFTER_DEPLOY")
            continue

        tick_after = _i(current.get("lastTickAtMs"))
        tick_before = _i(previous.get("lastTickAtMs"))
        tick_age = max(0, now_ms - tick_after) if tick_after > 0 else 10**18
        if tick_age > MAX_ACCOUNT_TICK_AGE_MS:
            failures.append(f"{account_ref}:ACCOUNT_TICK_STALE")
        if tick_before > 0 and tick_after <= tick_before:
            failures.append(f"{account_ref}:ACCOUNT_TICK_DID_NOT_ADVANCE")

        if _b(current.get("enabled")):
            scanner_after = _i(current.get("scannerUpdatedAtMs"))
            scanner_before = _i(previous.get("scannerUpdatedAtMs"))
            scanner_blocked = _b(current.get("scannerBlocked"))
            if scanner_after > 0:
                scanner_age = max(0, now_ms - scanner_after)
                if scanner_age > MAX_SCANNER_AGE_MS and not scanner_blocked:
                    failures.append(f"{account_ref}:SCANNER_HEARTBEAT_STALE")
                if scanner_before > 0 and scanner_after <= scanner_before and not scanner_blocked:
                    failures.append(f"{account_ref}:SCANNER_DID_NOT_ADVANCE")
            elif not scanner_blocked:
                warnings.append(f"{account_ref}:SCANNER_HEARTBEAT_UNAVAILABLE")

        bad_phases = {"DATA_HOLD", "CONFIG_ERROR"}
        previous_phase = str(previous.get("phase") or "").upper()
        current_phase = str(current.get("phase") or "").upper()
        if current_phase in bad_phases and previous_phase not in bad_phases:
            failures.append(f"{account_ref}:RUNTIME_PHASE_REGRESSED_TO_{current_phase}")

        if _b(previous.get("zoneEnabled")):
            previous_zone = previous.get("activeZone")
            current_zone = current.get("activeZone")
            if previous_zone is not None and current_zone is None:
                failures.append(f"{account_ref}:ACTIVE_ZONE_REGRESSED_TO_NULL")

        if _b(previous.get("zoneSafeForNewEntries")) and not _b(current.get("zoneSafeForNewEntries")):
            # Zone safety can legitimately change with market/history data, so this is
            # a warning only. A null-zone regression above remains a hard failure.
            warnings.append(f"{account_ref}:ZONE_ENTRY_SAFETY_CHANGED")

    for account_ref, current in sorted(after_rows.items()):
        if account_ref in before_rows or not _b(current.get("monitor")):
            continue
        tick_after = _i(current.get("lastTickAtMs"))
        tick_age = max(0, now_ms - tick_after) if tick_after > 0 else 10**18
        if tick_age > MAX_ACCOUNT_TICK_AGE_MS:
            failures.append(f"{account_ref}:NEW_MONITORED_ACCOUNT_TICK_STALE")

    return RuntimeGateResult(not failures, tuple(failures), tuple(warnings))


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only post-deploy runtime contract evaluator.")
    parser.add_argument("--before", required=True)
    parser.add_argument("--after", required=True)
    parser.add_argument("--now-ms", required=True, type=int)
    parser.add_argument("--output")
    args = parser.parse_args()

    before = json.loads(Path(args.before).read_text(encoding="utf-8"))
    after = json.loads(Path(args.after).read_text(encoding="utf-8"))
    result = evaluate_runtime_contract(before, after, now_ms=args.now_ms)
    payload = json.dumps(result.public_dict(), sort_keys=True)
    print(payload)
    if args.output:
        Path(args.output).write_text(payload + "\n", encoding="utf-8")
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
