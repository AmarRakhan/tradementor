from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from google.cloud import firestore


def _ms(value: Any) -> int:
    if isinstance(value, datetime):
        current = value if value.tzinfo else value.replace(tzinfo=timezone.utc)
        return int(current.astimezone(timezone.utc).timestamp() * 1000)
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return 0


def _num(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _hash_uid(uid: str) -> str:
    return hashlib.sha256(uid.encode()).hexdigest()[:10]


def _service_runtime(service: dict[str, Any]) -> tuple[bool, int]:
    annotations: dict[str, Any] = {}
    annotations.update(service.get("metadata", {}).get("annotations") or {})
    template = service.get("spec", {}).get("template", {})
    annotations.update(template.get("metadata", {}).get("annotations") or {})
    cpu = str(annotations.get("run.googleapis.com/cpu-throttling", "")).lower() == "false"
    minimum = (
        annotations.get("autoscaling.knative.dev/minScale")
        or annotations.get("run.googleapis.com/minScale")
        or 0
    )
    return cpu, _num(minimum)


def _periodic_logs(rows: list[dict[str, Any]], *, now_ms: int) -> bool:
    for row in rows if isinstance(rows, list) else []:
        text = str(row.get("textPayload") or "")
        if "ASTER_PERIODIC_TICK_COMPLETE" not in text:
            continue
        timestamp = row.get("timestamp")
        try:
            seen = datetime.fromisoformat(str(timestamp).replace("Z", "+00:00"))
        except ValueError:
            continue
        age = now_ms - int(seen.timestamp() * 1000)
        if 0 <= age <= 240_000:
            return True
    return False


def _dynamic_blocking(raw: dict[str, Any]) -> bool:
    report = raw.get("dynamicHedgeReport") if isinstance(raw.get("dynamicHedgeReport"), dict) else {}
    status = str(report.get("status") or "").lower()
    ownership = str(report.get("ownershipState") or "").upper()
    safety = str(report.get("safetyStatus") or "").upper()
    if status in {"uncertain", "data-hold", "paused"}:
        return True
    if ownership and ownership != "DYNAMIC_HEDGE_ACTIVE":
        return True
    if safety and safety != "VEILIG":
        return True
    return False


def _account_row(uid: str, raw: dict[str, Any]) -> dict[str, Any]:
    settings = raw.get("settings") if isinstance(raw.get("settings"), dict) else {}
    report = raw.get("multiBbReport") if isinstance(raw.get("multiBbReport"), dict) else {}
    scanner = report.get("scannerDiagnostics") if isinstance(report.get("scannerDiagnostics"), dict) else {}
    zone = raw.get("zoneSoldierReport") if isinstance(raw.get("zoneSoldierReport"), dict) else {}
    zone_enabled = bool(settings.get("zoneSoldiersEnabled")) and _num(settings.get("zoneSoldiersOptInVersion")) >= 1
    return {
        "accountRef": _hash_uid(uid),
        "monitor": bool(raw.get("monitor")),
        "enabled": bool(raw.get("enabled")),
        "phase": str(raw.get("phase") or ""),
        "lastTickAtMs": _ms(raw.get("lastTickAt")),
        "scannerUpdatedAtMs": _num(scanner.get("updatedAtMs")),
        "scannerBlocked": _dynamic_blocking(raw) or str(raw.get("phase") or "").upper() in {"PORTFOLIO_TP_EXECUTING", "FLAT_CONFIRMING", "RESTARTING"},
        "zoneEnabled": zone_enabled,
        "activeZone": zone.get("activeZone") if zone_enabled else None,
        "zoneSafeForNewEntries": bool(zone.get("safeForNewEntries")) if zone_enabled else False,
    }


def collect_accounts(project: str) -> list[dict[str, Any]]:
    client = firestore.Client(project=project)
    accounts = [
        _account_row(snapshot.id, snapshot.to_dict() or {})
        for snapshot in client.collection("asterStrategy2").where("monitor", "==", True).stream()
    ]
    accounts.sort(key=lambda row: row["accountRef"])
    return accounts


def build_snapshot(
    *,
    project: str,
    service: dict[str, Any],
    health: dict[str, Any],
    ticks: list[dict[str, Any]],
    errors: list[dict[str, Any]],
    now_ms: int,
    accounts_override: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    accounts = list(accounts_override) if accounts_override is not None else collect_accounts(project)
    accounts.sort(key=lambda row: row["accountRef"])
    background_cpu, min_instances = _service_runtime(service)
    return {
        "generatedAtMs": now_ms,
        "sourceCommit": str(health.get("sourceCommit") or health.get("imageSourceCommit") or ""),
        "serviceReady": health.get("status") == "ready" and health.get("multiUser") is True,
        "backgroundCpuEnabled": background_cpu,
        "minInstances": min_instances,
        "periodicWorkerRecent": _periodic_logs(ticks, now_ms=now_ms),
        "periodicWorkerErrors": len(errors) if isinstance(errors, list) else 0,
        "accounts": accounts,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Collect a sanitized read-only production runtime snapshot.")
    parser.add_argument("--project", required=True)
    parser.add_argument("--service-json")
    parser.add_argument("--health-json")
    parser.add_argument("--ticks-json")
    parser.add_argument("--errors-json")
    parser.add_argument("--output")
    parser.add_argument("--accounts-json")
    parser.add_argument("--accounts-only", action="store_true")
    parser.add_argument("--now-ms", type=int)
    args = parser.parse_args()

    if args.accounts_only:
        accounts = collect_accounts(args.project)
        print("RUNTIME_CONTRACT_ACCOUNTS " + json.dumps(accounts, sort_keys=True, separators=(",", ":")))
        return 0

    required = {
        "--service-json": args.service_json,
        "--health-json": args.health_json,
        "--ticks-json": args.ticks_json,
        "--errors-json": args.errors_json,
        "--output": args.output,
    }
    missing = [name for name, value in required.items() if not value]
    if missing:
        parser.error("missing required arguments outside --accounts-only: " + ", ".join(missing))

    now_ms = args.now_ms or int(datetime.now(timezone.utc).timestamp() * 1000)
    service = json.loads(Path(args.service_json).read_text(encoding="utf-8"))
    health = json.loads(Path(args.health_json).read_text(encoding="utf-8"))
    ticks = json.loads(Path(args.ticks_json).read_text(encoding="utf-8"))
    errors = json.loads(Path(args.errors_json).read_text(encoding="utf-8"))
    accounts_override = None
    if args.accounts_json:
        accounts_override = json.loads(Path(args.accounts_json).read_text(encoding="utf-8"))
        if not isinstance(accounts_override, list):
            raise SystemExit("--accounts-json must contain a JSON array")
    payload = build_snapshot(
        project=args.project,
        service=service,
        health=health,
        ticks=ticks,
        errors=errors,
        now_ms=now_ms,
        accounts_override=accounts_override,
    )
    Path(args.output).write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({
        "serviceReady": payload["serviceReady"],
        "backgroundCpuEnabled": payload["backgroundCpuEnabled"],
        "minInstances": payload["minInstances"],
        "periodicWorkerRecent": payload["periodicWorkerRecent"],
        "periodicWorkerErrors": payload["periodicWorkerErrors"],
        "monitoredAccountCount": len(payload["accounts"]),
    }, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
