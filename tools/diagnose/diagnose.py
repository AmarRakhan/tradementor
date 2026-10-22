#!/usr/bin/env python3
"""Alleen-lezen diagnose voor Tradementor (draait in .github/workflows/diagnose.yml met het read-only SA).

Taken:
  overview                     Cloud Run-services/revisies/verkeer, scheduler-jobs, VM's, schijven, Artifact Registry
  autohedge-pairs [STATUS]     Auto Hedge-pairs per account (asterPositionLossAutoHedge/{uid}/pairs), optioneel op status
  firestore-collection PATH    Documenten van één collectie (max 200), bijv. users/UID/asterProfitCloseRounds
  firestore-doc PATH           Eén document
  logs FILTER [FRESHNESS]      Cloud Logging (max 300 regels), freshness bijv. 2h (max 7d)

Schrijft JSON naar stdout. Wijzigt nooit iets: Firestore alleen get/stream, gcloud alleen list/describe/read.
Velden waarvan de naam op een geheim lijkt, worden vervangen door "<REDACTED>" (extra laag; de uitvoer is ook versleuteld).
"""
from __future__ import annotations

import datetime as dt
import json
import re
import subprocess
import sys

PROJECT = "tradementor-production"
REGION = "europe-west4"
SECRET_KEY_RE = re.compile(r"(secret|private|apikey|api_key|password|passphrase|mnemonic|seed|token|signer|wallet_key)", re.I)
PATH_RE = re.compile(r"^[A-Za-z0-9_\-.]+(/[A-Za-z0-9_\-.]+)*$")
FRESH_RE = re.compile(r"^([1-9][0-9]{0,2})([mhd])$")
READ_ONLY_GCLOUD = ("list", "describe", "read", "get-iam-policy")


class DiagError(Exception):
    pass


def redact(value, depth=0):
    if depth > 30:
        return "<TOO_DEEP>"
    if isinstance(value, dict):
        return {k: ("<REDACTED>" if SECRET_KEY_RE.search(str(k)) else redact(v, depth + 1)) for k, v in value.items()}
    if isinstance(value, list):
        return [redact(v, depth + 1) for v in value]
    if isinstance(value, (dt.datetime, dt.date)):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def gcloud(*args: str):
    verbs = [a for a in args if not a.startswith("-")]
    if not any(v in READ_ONLY_GCLOUD for v in verbs):
        raise DiagError(f"weigering: geen alleen-lezen gcloud-opdracht: {args}")
    for forbidden in ("create", "delete", "update", "deploy", "set-iam-policy", "add-iam-policy-binding",
                      "remove-iam-policy-binding", "update-traffic", "pause", "resume", "run", "start", "stop"):
        if forbidden in verbs[1:] and forbidden not in ("run",):
            raise DiagError(f"weigering: '{forbidden}' in {args}")
    cmd = ["gcloud", *args, f"--project={PROJECT}", "--format=json", "--quiet"]
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
    if p.returncode != 0:
        return {"error": p.stderr.strip()[-800:]}
    try:
        return json.loads(p.stdout or "null")
    except json.JSONDecodeError:
        return {"error": "geen JSON", "raw": p.stdout[:2000]}


def service_summary(svc: dict) -> dict:
    st = svc.get("status", {}) if isinstance(svc, dict) else {}
    meta = svc.get("metadata", {}) if isinstance(svc, dict) else {}
    tmpl = (svc.get("spec", {}) or {}).get("template", {}) if isinstance(svc, dict) else {}
    ann = (tmpl.get("metadata", {}) or {}).get("annotations", {}) or {}
    return {"name": meta.get("name"), "url": st.get("url"),
            "traffic": [{k: r.get(k) for k in ("revisionName", "percent", "tag")} for r in st.get("traffic") or []],
            "latestReady": st.get("latestReadyRevisionName"), "latestCreated": st.get("latestCreatedRevisionName"),
            "minScale": ann.get("autoscaling.knative.dev/minScale"), "maxScale": ann.get("autoscaling.knative.dev/maxScale"),
            "cpuThrottling": ann.get("run.googleapis.com/cpu-throttling")}


def task_overview() -> dict:
    services = gcloud("run", "services", "list", f"--region={REGION}")
    out = {"services": [service_summary(s) for s in services] if isinstance(services, list) else services}
    revs = {}
    for name in ("tradementor-api", "amar-bot-v44-direct-install"):
        r = gcloud("run", "revisions", "list", f"--service={name}", f"--region={REGION}", "--limit=12")
        revs[name] = [{"name": x.get("metadata", {}).get("name"),
                       "created": x.get("metadata", {}).get("creationTimestamp"),
                       "creator": (x.get("metadata", {}).get("annotations", {}) or {}).get("serving.knative.dev/creator"),
                       "image": ((x.get("spec", {}).get("containers") or [{}])[0]).get("image")}
                      for x in r] if isinstance(r, list) else r
    out["revisions"] = revs
    jobs = gcloud("scheduler", "jobs", "list", f"--location={REGION}")
    out["schedulerJobs"] = [{"name": (j.get("name") or "").split("/")[-1], "state": j.get("state"),
                             "schedule": j.get("schedule"), "target": (j.get("httpTarget") or {}).get("uri")}
                            for j in jobs] if isinstance(jobs, list) else jobs
    vms = gcloud("compute", "instances", "list")
    out["vms"] = [{"name": v.get("name"), "zone": (v.get("zone") or "").split("/")[-1], "status": v.get("status"),
                   "machineType": (v.get("machineType") or "").split("/")[-1],
                   "created": v.get("creationTimestamp"), "lastStart": v.get("lastStartTimestamp"),
                   "labels": v.get("labels"), "tags": (v.get("tags") or {}).get("items")}
                  for v in vms] if isinstance(vms, list) else vms
    disks = gcloud("compute", "disks", "list")
    out["disks"] = [{"name": d.get("name"), "sizeGb": d.get("sizeGb"), "users": d.get("users"),
                     "region": (d.get("region") or d.get("zone") or "").split("/")[-1]}
                    for d in disks] if isinstance(disks, list) else disks
    snaps = gcloud("compute", "snapshots", "list")
    out["snapshots"] = [{"name": s.get("name"), "status": s.get("status"), "diskSizeGb": s.get("diskSizeGb"),
                         "storageBytes": s.get("storageBytes")} for s in snaps] if isinstance(snaps, list) else snaps
    repos = gcloud("artifacts", "repositories", "list", f"--location={REGION}")
    out["artifactRepositories"] = [{"name": (r.get("name") or "").split("/")[-1], "sizeBytes": r.get("sizeBytes"),
                                    "format": r.get("format")} for r in repos] if isinstance(repos, list) else repos
    return out


def firestore():
    from google.cloud import firestore as fs  # pip install google-cloud-firestore in de workflow
    return fs.Client(project=PROJECT)


def task_autohedge_pairs(status: str = "") -> dict:
    if status and not re.fullmatch(r"[A-Z_]{2,40}", status):
        raise DiagError("ongeldige status")
    db = firestore()
    accounts = []
    for acc in db.collection("asterPositionLossAutoHedge").stream():
        pairs = []
        for p in acc.reference.collection("pairs").stream():
            d = p.to_dict() or {}
            if status and d.get("status") != status:
                continue
            pairs.append({"symbol": p.id, **redact(d)})
        accounts.append({"uid": acc.id, "pairCount": len(pairs), "pairs": pairs})
    return {"filterStatus": status or None, "accounts": accounts}


def check_path(path: str, want_even: bool) -> list[str]:
    if not PATH_RE.match(path or "") or ".." in path:
        raise DiagError("ongeldig Firestore-pad")
    parts = path.split("/")
    if (len(parts) % 2 == 0) != want_even:
        raise DiagError("pad is geen " + ("document" if want_even else "collectie"))
    return parts


def task_firestore_collection(path: str) -> dict:
    check_path(path, want_even=False)
    docs = firestore().collection(path).limit(200).stream()
    return {"path": path, "documents": [{"id": d.id, **redact(d.to_dict() or {})} for d in docs]}


def task_firestore_doc(path: str) -> dict:
    check_path(path, want_even=True)
    snap = firestore().document(path).get()
    return {"path": path, "exists": snap.exists, "data": redact(snap.to_dict() or {}) if snap.exists else None}


def task_logs(flt: str, freshness: str = "2h") -> dict:
    if not flt or len(flt) > 2000:
        raise DiagError("filter ontbreekt of is te lang")
    m = FRESH_RE.match(freshness or "")
    if not m:
        raise DiagError("freshness moet bijv. 30m, 2h of 3d zijn")
    n, unit = int(m.group(1)), m.group(2)
    if unit == "d" and n > 7:
        raise DiagError("maximaal 7 dagen")
    rows = gcloud("logging", "read", flt, f"--freshness={freshness}", "--limit=300")
    if not isinstance(rows, list):
        return {"filter": flt, "result": rows}
    keep = []
    for r in rows:
        keep.append(redact({k: r.get(k) for k in ("timestamp", "severity", "textPayload", "jsonPayload",
                                                   "httpRequest", "resource", "labels", "protoPayload")
                            if r.get(k) is not None}))
    return {"filter": flt, "freshness": freshness, "count": len(keep), "entries": keep}


TASKS = {
    "overview": (task_overview, 0, 0),
    "autohedge-pairs": (task_autohedge_pairs, 0, 1),
    "firestore-collection": (task_firestore_collection, 1, 1),
    "firestore-doc": (task_firestore_doc, 1, 1),
    "logs": (task_logs, 1, 2),
}


def main(argv: list[str]) -> int:
    if len(argv) < 2 or argv[1] not in TASKS:
        print(json.dumps({"error": f"onbekende taak; kies uit {sorted(TASKS)}"}))
        return 2
    fn, lo, hi = TASKS[argv[1]]
    args = [a for a in argv[2:] if a != ""]
    if not lo <= len(args) <= hi:
        print(json.dumps({"error": f"{argv[1]} verwacht {lo}-{hi} argumenten"}))
        return 2
    started = dt.datetime.now(dt.timezone.utc).isoformat()
    try:
        result = fn(*args)
        ok = True
    except DiagError as exc:
        result, ok = {"error": str(exc)}, False
    print(json.dumps({"task": argv[1], "args": args, "startedUtc": started, "ok": ok, "result": result},
                     ensure_ascii=False, indent=1, default=str))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv))
