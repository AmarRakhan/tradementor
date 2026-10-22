#!/usr/bin/env python3
"""READ-ONLY Artifact Registry inventory + cleanup manifest for tradementor-production (Kostenreductie 4.1, COST-005).

Runs only gcloud *list* / *describe* commands. It never deletes, tags, untags or changes anything.
Output (in --out, default ./ar-inventory):
  images.csv            every image version: repo, package, digest, tags, created, size, class, reason
  keep-manifest.txt     package@digest that MUST stay (live, rollback, referenced by an existing revision/job, recent)
  delete-candidates.txt package@digest that no Cloud Run revision or job references and that are older than --keep-days
  summary.md            totals per class and the estimated saving

Classes (first match wins):
  KEEP_LIVE        digest of a revision that serves traffic now
  KEEP_ROLLBACK    digest of one of the newest --rollback-revisions revisions of a protected service
  KEEP_REFERENCED  digest of ANY other existing Cloud Run revision or job (deleting it would make that revision unstartable)
  KEEP_RECENT      created less than --keep-days ago
  CANDIDATE        none of the above

Saving estimate: CANDIDATE bytes x EUR 0.0925 per GB-month. Layers shared between images are stored once, so the real
saving is AT MOST this number; check the repository sizeBytes before and after.

Usage (owner / ChatGPT, with an account that has roles/artifactregistry.reader + roles/run.viewer):
  python3 tools/cost/ar_inventory.py --project tradementor-production --region europe-west4 --out ./ar-inventory
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import subprocess
import sys
from typing import Any, Callable

PROTECTED_SERVICES = ("tradementor-api", "amar-bot-v44-direct-install")
EUR_PER_GB_MONTH = 0.0925
ALLOWED_VERBS = ("list", "describe")


def gcloud_json(args: list[str], runner: Callable[[list[str]], str] | None = None) -> Any:
    if not any(verb in args for verb in ALLOWED_VERBS) or any(bad in args for bad in ("delete", "update", "add-tag", "untag", "set-cleanup-policies")):
        raise SystemExit("refusing non-read-only gcloud command: " + " ".join(args))
    cmd = ["gcloud", *args, "--format=json"]
    out = runner(cmd) if runner else subprocess.run(cmd, check=True, capture_output=True, text=True).stdout
    return json.loads(out or "[]")


def digest_of(image: str) -> str:
    return image.split("@", 1)[1] if "@" in image else ""


def parse_time(value: str) -> dt.datetime:
    value = (value or "1970-01-01T00:00:00Z").replace("Z", "+00:00")
    if "." in value:                                   # gcloud prints nanoseconds; Python accepts up to micro
        head, rest = value.split(".", 1)
        frac, _, tz = rest.partition("+")
        value = head + "." + frac[:6] + ("+" + tz if tz else "")
    return dt.datetime.fromisoformat(value)


def revision_rows(revisions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    rows = []
    for rev in revisions:
        meta, status = rev.get("metadata", {}), rev.get("status", {})
        labels = meta.get("labels", {}) or {}
        service = labels.get("serving.knative.dev/service") or labels.get("run.googleapis.com/service") or ""
        containers = (rev.get("spec", {}) or {}).get("containers", []) or []
        images = [c.get("image", "") for c in containers]
        digests = {digest_of(i) for i in images} | {status.get("imageDigest", "") and digest_of(status.get("imageDigest", ""))}
        rows.append({"service": service, "name": meta.get("name", ""), "created": meta.get("creationTimestamp", ""),
                     "digests": {d for d in digests if d}, "images": images})
    return rows


def classify(images: list[dict[str, Any]], revisions: list[dict[str, Any]], services: list[dict[str, Any]],
             jobs: list[dict[str, Any]], *, now: dt.datetime, keep_days: int, rollback_revisions: int) -> list[dict[str, Any]]:
    revs = revision_rows(revisions)
    by_name = {r["name"]: r for r in revs}
    live: set[str] = set()
    for svc in services:
        for t in (svc.get("status", {}) or {}).get("traffic", []) or []:
            if int(t.get("percent", 0) or 0) > 0 and t.get("revisionName") in by_name:
                live |= by_name[t["revisionName"]]["digests"]
    rollback: set[str] = set()
    for service in PROTECTED_SERVICES:
        newest = sorted((r for r in revs if r["service"] == service), key=lambda r: r["created"], reverse=True)
        for r in newest[:rollback_revisions]:
            rollback |= r["digests"]
    referenced: set[str] = set().union(*(r["digests"] for r in revs)) if revs else set()
    for job in jobs:
        tmpl = ((job.get("spec", {}) or {}).get("template", {}) or {}).get("spec", {}).get("template", {}).get("spec", {})
        for c in (tmpl or {}).get("containers", []) or []:
            if digest_of(c.get("image", "")):
                referenced.add(digest_of(c["image"]))
    # Revisions that reference an image by TAG (no digest) are resolved via the tag on the image row.
    tag_refs = {i.split("/")[-1] for r in revs for i in r["images"] if "@" not in i}
    out = []
    for img in images:
        digest = img.get("version", "")
        package = img.get("package", "")
        tags = img.get("tags", "")
        tags = tags if isinstance(tags, list) else [t for t in str(tags).split(",") if t]
        created = parse_time(img.get("createTime", ""))
        size = int(img.get("metadata", {}).get("imageSizeBytes", 0) or 0)
        name_tags = {package.split("/")[-1] + ":" + t for t in tags}
        if digest in live:
            cls, why = "KEEP_LIVE", "serves traffic"
        elif digest in rollback:
            cls, why = "KEEP_ROLLBACK", f"newest {rollback_revisions} revisions of a protected service"
        elif digest in referenced or name_tags & tag_refs:
            cls, why = "KEEP_REFERENCED", "used by an existing revision or job"
        elif (now - created).days < keep_days:
            cls, why = "KEEP_RECENT", f"younger than {keep_days} days"
        else:
            cls, why = "CANDIDATE", "no revision/job reference and old"
        out.append({"package": package, "digest": digest, "tags": ";".join(tags), "created": created.isoformat(),
                    "sizeBytes": size, "class": cls, "reason": why})
    return out


def main(argv: list[str] | None = None, runner: Callable[[list[str]], str] | None = None) -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--project", default="tradementor-production")
    ap.add_argument("--region", default="europe-west4")
    ap.add_argument("--keep-days", type=int, default=30)
    ap.add_argument("--rollback-revisions", type=int, default=5)
    ap.add_argument("--out", default="ar-inventory")
    a = ap.parse_args(argv)
    p, r = a.project, a.region
    repos = gcloud_json(["artifacts", "repositories", "list", f"--project={p}", "--location=all"], runner)
    images: list[dict[str, Any]] = []
    repo_sizes = []
    for repo in repos:
        name = repo.get("name", "")                       # projects/P/locations/L/repositories/R
        parts = name.split("/")
        repo_sizes.append((name, int(repo.get("sizeBytes", 0) or 0), repo.get("format", "")))
        if repo.get("format") != "DOCKER" or len(parts) < 6:
            continue
        host = f"{parts[3]}-docker.pkg.dev/{parts[1]}/{parts[5]}"
        images += gcloud_json(["artifacts", "docker", "images", "list", host, "--include-tags", f"--project={p}"], runner)
    revisions = gcloud_json(["run", "revisions", "list", f"--project={p}", f"--region={r}"], runner)
    services = gcloud_json(["run", "services", "list", f"--project={p}", f"--region={r}"], runner)
    jobs = gcloud_json(["run", "jobs", "list", f"--project={p}", f"--region={r}"], runner)
    rows = classify(images, revisions, services, jobs, now=dt.datetime.now(dt.timezone.utc),
                    keep_days=a.keep_days, rollback_revisions=a.rollback_revisions)
    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "images.csv"), "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0].keys()) if rows else ["package"])
        w.writeheader()
        w.writerows(rows)
    with open(os.path.join(a.out, "keep-manifest.txt"), "w") as fh:
        fh.writelines(f"{x['package']}@{x['digest']}  {x['class']}\n" for x in rows if x["class"] != "CANDIDATE")
    with open(os.path.join(a.out, "delete-candidates.txt"), "w") as fh:
        fh.writelines(f"{x['package']}@{x['digest']}\n" for x in rows if x["class"] == "CANDIDATE")
    totals: dict[str, list[int]] = {}
    for x in rows:
        t = totals.setdefault(x["class"], [0, 0])
        t[0] += 1
        t[1] += x["sizeBytes"]
    gb = lambda b: b / 1e9
    lines = ["# Artifact Registry inventory (read-only)", "", f"Project {p}; generated {dt.datetime.now(dt.timezone.utc).isoformat()}", "",
             "| Repository | Format | sizeBytes (billed basis) |", "|---|---|---:|"]
    lines += [f"| {n} | {f} | {s:,} ({gb(s):.1f} GB) |" for n, s, f in repo_sizes]
    lines += ["", "| Class | Images | Sum of image sizes |", "|---|---:|---:|"]
    lines += [f"| {c} | {n} | {gb(b):.1f} GB |" for c, (n, b) in sorted(totals.items())]
    cand = totals.get("CANDIDATE", [0, 0])[1]
    lines += ["", f"Upper bound saving if all CANDIDATE images are removed: EUR {gb(cand) * EUR_PER_GB_MONTH:.2f}/month "
              "(shared layers are stored once: real saving <= this; compare repository sizeBytes before/after)."]
    with open(os.path.join(a.out, "summary.md"), "w") as fh:
        fh.write("\n".join(lines) + "\n")
    print("\n".join(lines))
    return 0


if __name__ == "__main__":
    sys.exit(main())
