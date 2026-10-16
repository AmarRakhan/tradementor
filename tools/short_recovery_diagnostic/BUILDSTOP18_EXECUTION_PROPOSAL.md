# Bouwstop 18 — exact build-601 read-only execution proposal (2026-10-16)

## Verified
- The trusted workflow is `.github/workflows/agent-production-diagnostic-worker.yml` on `amar-crypto-bot-2026-cloud`.
- Its existing observer WIF identity is `github-tradementor-observer@tradementor-production.iam.gserviceaccount.com`.
- It currently describes latest/live revisions; it does not describe both exact retained build-601 revisions.
- Isolated diagnostic probe `tools/short_recovery_diagnostic/rollback_probe.py` and its tests are on `diag-short-recovery-601-20261016`. They are NOT present on the trusted branch.
- 9 tests passed locally, not a Cloud Run readback.

## Minimal authorized trusted-branch patch (NOT APPLIED)
Add a bounded, read-only shell block to the existing worker's `Collect sanitized production diagnostics` step, **after WIF auth and gcloud setup**. Do not add a new workflow, change IAM, or modify any production resource.

```bash
for item in \
  "web:amar-bot-v44-direct-install-v46-89ab74a0-1" \
  "backend:tradementor-api-src-f87d6b20-124369"; do
  label="${item%%:*}"; rev="${item#*:}"
  if gcloud run revisions describe "$rev" --project tradementor-production --region europe-west4 --format=json > "$RUNNER_TEMP/revision-$label.json" 2>/dev/null; then
    python - "$RUNNER_TEMP/revision-$label.json" "$label" "$rev" <<'PY'
import json,sys
row=json.load(open(sys.argv[1],encoding="utf-8"))
label,revision=sys.argv[2:]
name=(row.get("metadata") or {}).get("name")
conditions=(row.get("status") or {}).get("conditions") or []
ready=any(c.get("type")=="Ready" and c.get("status") in ("True",True) for c in conditions)
image=bool(((row.get("spec") or {}).get("containers") or [{}])[0].get("image"))
print(f"BUILD601_{label.upper()}_REVISION="+("PASS" if name==revision and ready and image else "NO_GO"))
PY
  else
    echo "BUILD601_${label^^}_REVISION=READ_UNAVAILABLE"
  fi
  rm -f "$RUNNER_TEMP/revision-$label.json"
done
```

Capture these lines within the existing sanitized report. Do not print raw revision JSON or cloud credentials. The control makes only two `gcloud run revisions describe` calls.

## Required evidence before trading code
1. Real, authorized observer execution reports exact build-601 web and backend revision identities.
2. Both revisions exist, are Ready, and have image pointers; a HEAD/latestReady reference is not enough.
3. Examine retained image availability and rollback compatibility separately (API contracts, Firestore schema, environment, secrets references), without mutation.
4. Any inconclusive or unavailable check => NO-GO; revision checks alone do not prove full rollback.
5. User authorization is required before **any** modification to the trusted branch or **any** workflow dispatch. The user explicitly prohibited those actions in bouwstop 18.

## Current result
Prepared only. No Cloud Run readback, no trusted-branch change, no workflow dispatch, no live orders, no Cloud Build or deployment.
