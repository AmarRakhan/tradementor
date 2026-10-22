#!/usr/bin/env bash
# Eenmalige setup van de GitHub-releaseroute voor Tradementor (Workload Identity Federation).
#
# Maakt precies drie dingen aan, verder niets:
#   1. WIF-pool      gh-deploy                 (nieuw, los van de bestaande pool 'github')
#   2. OIDC-provider github-main in die pool   (accepteert ALLEEN tokens van
#        .github/workflows/release-backend.yml en release-backend-rollback.yml op main,
#        handmatig gestart, in environment 'release' = na goedkeuring door Amar)
#   3. Eén binding   roles/iam.workloadIdentityUser op het bestaande deploy-service-account
#
# Geen sleutels, geen nieuwe rollen, geen wijziging aan bestaande pools, providers, rollen of bindings.
# Ongedaan maken:  bash setup-github-deploy-identity.sh undo
#
# Draai in Google Cloud Shell als eigenaar van project tradementor-production.
set -euo pipefail
umask 077

PROJECT_ID="tradementor-production"
PROJECT_NUMBER="604335232956"
POOL="gh-deploy"
POOL_DISPLAY="GitHub release main + goedkeuring"
PROVIDER="github-main"
DEPLOY_SA="github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com"
OLD_POOL="github"
OLD_PROVIDER="tradementor-production"
ISSUER="https://token.actions.githubusercontent.com"
ROLE="roles/iam.workloadIdentityUser"
REPO_ID="1324367697"
OWNER_ID="313542222"
MAPPING="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id"
MEMBER="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}/attribute.repository_id/${REPO_ID}"
WF="AmarRakhan/tradementor/.github/workflows"
CONDITION="assertion.repository_id == '${REPO_ID}' && assertion.repository_owner_id == '${OWNER_ID}' && assertion.ref == 'refs/heads/main' && assertion.ref_type == 'branch' && assertion.event_name == 'workflow_dispatch' && assertion.environment == 'release' && assertion.job_workflow_ref == assertion.workflow_ref && (assertion.workflow_ref == '${WF}/release-backend.yml@refs/heads/main' || assertion.workflow_ref == '${WF}/release-backend-rollback.yml@refs/heads/main')"

MODE="${1:-setup}"
OUT="${OUT_DIR:-$HOME/github-deploy-identity-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"; chmod 700 "$OUT"
CREATED=()

say()  { printf '%s\n' "$*"; }
stop() { STOPPED=1; printf '\nSTOP: %s\n' "$*" >&2; report_partial; exit 1; }
report_partial() {
  if [ "${#CREATED[@]}" -gt 0 ]; then
    printf 'Al aangemaakt in deze run: %s\n' "${CREATED[*]}" >&2
    printf 'Dit verleent niets zolang de binding ontbreekt. Opruimen: bash %s undo\n' "$0" >&2
  else
    printf 'Er is niets gewijzigd.\n' >&2
  fi
}
trap 'rc=$?; [ $rc -ne 0 ] && [ -z "${STOPPED:-}" ] && { printf "\nSTOP: onverwachte fout (exit %s), zie de melding hierboven\n" "$rc" >&2; report_partial; }' EXIT
ask() { if [ -n "${CONFIRM_ANSWER:-}" ]; then ANSWER="$CONFIRM_ANSWER"; else read -r -p "$1" ANSWER < /dev/tty || ANSWER=""; fi; }
g() { gcloud --project="$PROJECT_ID" --quiet "$@"; }

json_get() { python3 -c 'import json,sys
d=json.load(open(sys.argv[1]))
for k in sys.argv[2].split("."):
    d = d.get(k) if isinstance(d, dict) else None
print("" if d is None else (json.dumps(d, sort_keys=True) if isinstance(d,(dict,list)) else d))' "$1" "$2"; }

check_provider() {  # $1 = json van de provider; controleert dat het exact onze provider is
  python3 - "$1" "$CONDITION" "$ISSUER" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
want_map = {"google.subject": "assertion.sub", "attribute.repository_id": "assertion.repository_id"}
problems = []
if p.get("attributeCondition") != sys.argv[2]: problems.append("conditie")
if p.get("attributeMapping") != want_map: problems.append("mapping")
if (p.get("oidc") or {}).get("issuerUri") != sys.argv[3]: problems.append("issuer")
if (p.get("oidc") or {}).get("allowedAudiences"): problems.append("audiences")
if problems:
    print("afwijkend: " + ", ".join(problems)); sys.exit(1)
print(p.get("state", ""))
PY
}

has_member() {  # $1 = policy-json
  python3 - "$1" "$ROLE" "$MEMBER" <<'PY'
import json, sys
pol = json.load(open(sys.argv[1]))
hit = any(b.get("role") == sys.argv[2] and sys.argv[3] in (b.get("members") or []) and not b.get("condition")
          for b in pol.get("bindings") or [])
print("yes" if hit else "no")
PY
}

policy_delta_ok() {  # $1 before, $2 after, $3 = add|remove : after == before ± alleen onze binding
  python3 - "$1" "$2" "$3" "$ROLE" "$MEMBER" <<'PY'
import json, sys
def flat(path):
    pol = json.load(open(path))
    out = set()
    for b in pol.get("bindings") or []:
        cond = json.dumps(b.get("condition"), sort_keys=True)
        for m in b.get("members") or []:
            out.add((b.get("role"), m, cond))
    extra = {k: v for k, v in pol.items() if k not in ("bindings", "etag", "version")}
    return out, extra
b, bx = flat(sys.argv[1]); a, ax = flat(sys.argv[2])
ours = {(sys.argv[4], sys.argv[5], "null")}
want = (b | ours) if sys.argv[3] == "add" else (b - ours)
if a != want or ax != bx:
    print("onverwachte wijziging: +%s -%s" % (sorted(a - want), sorted(want - a))); sys.exit(1)
print("ok")
PY
}

# ---------- 1. Vooraf: alleen lezen ----------
command -v gcloud >/dev/null || stop "gcloud ontbreekt (draai dit in Google Cloud Shell)"
command -v python3 >/dev/null || stop "python3 ontbreekt"
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "$ACCOUNT" ] || stop "geen ingelogd Google-account (gcloud auth login)"
NUM="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || true)"
[ "$NUM" = "$PROJECT_NUMBER" ] || stop "project $PROJECT_ID niet gevonden of verkeerd projectnummer (${NUM:-geen})"
g iam service-accounts describe "$DEPLOY_SA" --format=json > "$OUT/sa.json" 2>/dev/null || stop "deploy-service-account $DEPLOY_SA niet gevonden"
[ "$(json_get "$OUT/sa.json" disabled)" != "True" ] || stop "deploy-service-account is uitgeschakeld"

g iam workload-identity-pools describe "$OLD_POOL" --location=global --format=json > "$OUT/old-pool-before.json" \
  || stop "bestaande pool '$OLD_POOL' niet leesbaar"
g iam workload-identity-pools providers describe "$OLD_PROVIDER" --workload-identity-pool="$OLD_POOL" --location=global \
  --format=json > "$OUT/old-provider-before.json" || stop "bestaande provider niet leesbaar"
g iam service-accounts get-iam-policy "$DEPLOY_SA" --format=json > "$OUT/sa-policy-before.json" || stop "IAM-policy van deploy-SA niet leesbaar"

POOL_STATE=""
if g iam workload-identity-pools describe "$POOL" --location=global --format=json > "$OUT/pool-before.json" 2>/dev/null; then
  POOL_STATE="$(json_get "$OUT/pool-before.json" state)"
  [ "$(json_get "$OUT/pool-before.json" displayName)" = "$POOL_DISPLAY" ] || stop "er bestaat al een andere pool '$POOL'; niets aangeraakt"
fi
PROV_STATE=""
if [ -n "$POOL_STATE" ] && g iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool="$POOL" \
     --location=global --format=json > "$OUT/provider-before.json" 2>/dev/null; then
  PROV_STATE="$(check_provider "$OUT/provider-before.json")" || stop "provider '$PROVIDER' bestaat al met andere instellingen ($PROV_STATE)"
fi
BOUND="$(has_member "$OUT/sa-policy-before.json")"

say ""
say "=== Tradementor: eenmalige setup GitHub-releaseroute ==="
say "Account:   $ACCOUNT"
say "Project:   $PROJECT_ID ($PROJECT_NUMBER)"
say "Modus:     $MODE"
say "Pool:      $POOL           (${POOL_STATE:-bestaat nog niet})"
say "Provider:  $PROVIDER        (${PROV_STATE:-bestaat nog niet})"
say "Binding:   $ROLE op $DEPLOY_SA ($( [ "$BOUND" = yes ] && echo aanwezig || echo nog niet))"
say "Bestaande pool '$OLD_POOL' en alle andere rechten: blijven ongewijzigd (wordt na afloop gecontroleerd)."
say ""

if [ "$MODE" = "setup" ]; then
  [ "$POOL_STATE" != "DELETED" ] || stop "pool '$POOL' staat in de prullenbak; herstel met: gcloud iam workload-identity-pools undelete $POOL --location=global --project=$PROJECT_ID"
  [ -z "$PROV_STATE" ] || [ "$PROV_STATE" = "ACTIVE" ] || stop "provider '$PROVIDER' is niet actief ($PROV_STATE)"
  if [ "$POOL_STATE" = "ACTIVE" ] && [ "$PROV_STATE" = "ACTIVE" ] && [ "$BOUND" = yes ]; then
    say "Alles staat er al. Niets te doen."
  else
    ask "Typ JA om dit aan te maken: "
    [ "$ANSWER" = "JA" ] || { STOPPED=1; say "Afgebroken. Er is niets gewijzigd."; exit 1; }
    if [ -z "$POOL_STATE" ]; then
      g iam workload-identity-pools create "$POOL" --location=global --display-name="$POOL_DISPLAY" \
        --description="Alleen release-backend(-rollback).yml op main, environment release" >/dev/null
      CREATED+=("pool $POOL"); say "✓ pool aangemaakt"
    fi
    if [ -z "$PROV_STATE" ]; then
      g iam workload-identity-pools providers create-oidc "$PROVIDER" --location=global --workload-identity-pool="$POOL" \
        --display-name="GitHub main release" --issuer-uri="$ISSUER" --attribute-mapping="$MAPPING" \
        --attribute-condition="$CONDITION" >/dev/null
      CREATED+=("provider $PROVIDER"); say "✓ provider aangemaakt"
    fi
    if [ "$BOUND" != yes ]; then
      g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role="$ROLE" --member="$MEMBER" --format=none
      CREATED+=("binding"); say "✓ binding toegevoegd"
    fi
  fi
elif [ "$MODE" = "undo" ]; then
  [ -n "$POOL_STATE" ] || [ "$BOUND" = yes ] || { STOPPED=1; say "Niets te verwijderen."; exit 0; }
  ask "Typ VERWIJDER om de releaseroute te verwijderen: "
  [ "$ANSWER" = "VERWIJDER" ] || { STOPPED=1; say "Afgebroken. Er is niets gewijzigd."; exit 1; }
  if [ "$BOUND" = yes ]; then
    g iam service-accounts remove-iam-policy-binding "$DEPLOY_SA" --role="$ROLE" --member="$MEMBER" --format=none
    say "✓ binding verwijderd"
  fi
  if [ -n "$PROV_STATE" ] && [ "$PROV_STATE" != "DELETED" ]; then
    g iam workload-identity-pools providers delete "$PROVIDER" --location=global --workload-identity-pool="$POOL" >/dev/null
    say "✓ provider verwijderd"
  fi
  if [ -n "$POOL_STATE" ] && [ "$POOL_STATE" != "DELETED" ]; then
    g iam workload-identity-pools delete "$POOL" --location=global >/dev/null
    say "✓ pool verwijderd (naam 30 dagen gereserveerd)"
  fi
else
  stop "onbekende modus '$MODE' (gebruik: setup of undo)"
fi

# ---------- 3. Achteraf: bewijzen dat alleen dit is veranderd ----------
g iam service-accounts get-iam-policy "$DEPLOY_SA" --format=json > "$OUT/sa-policy-after.json"
g iam workload-identity-pools describe "$OLD_POOL" --location=global --format=json > "$OUT/old-pool-after.json"
g iam workload-identity-pools providers describe "$OLD_PROVIDER" --workload-identity-pool="$OLD_POOL" --location=global \
  --format=json > "$OUT/old-provider-after.json"
cmp -s "$OUT/old-pool-before.json" "$OUT/old-pool-after.json" || stop "bestaande pool '$OLD_POOL' is veranderd"
cmp -s "$OUT/old-provider-before.json" "$OUT/old-provider-after.json" || stop "bestaande provider is veranderd"

if [ "$MODE" = "setup" ]; then
  DELTA="$(policy_delta_ok "$OUT/sa-policy-before.json" "$OUT/sa-policy-after.json" add)" || stop "IAM-policy: $DELTA"
  [ "$(has_member "$OUT/sa-policy-after.json")" = yes ] || stop "binding niet gevonden na toevoegen"
  g iam workload-identity-pools describe "$POOL" --location=global --format=json > "$OUT/pool-after.json"
  [ "$(json_get "$OUT/pool-after.json" state)" = "ACTIVE" ] || stop "pool is niet ACTIVE"
  g iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool="$POOL" --location=global \
    --format=json > "$OUT/provider-after.json"
  ST="$(check_provider "$OUT/provider-after.json")" || stop "provider na aanmaken: $ST"
  [ "$ST" = "ACTIVE" ] || stop "provider is niet ACTIVE ($ST)"
  HASH="$(printf '%s' "$CONDITION" | sha256sum | cut -c1-12)"
  say ""
  say "KLAAR. Controle: alleen pool, provider en één binding zijn nieuw; de rest is gelijk gebleven."
  say "Stuur deze regel naar Claude:"
  say ""
  say "  SETUP_OK $POOL/$PROVIDER conditie=$HASH binding=1 oude-pool=ongewijzigd"
  say ""
  say "(Google heeft soms een paar minuten nodig voordat een nieuwe binding werkt.)"
else
  DELTA="$(policy_delta_ok "$OUT/sa-policy-before.json" "$OUT/sa-policy-after.json" remove)" || stop "IAM-policy: $DELTA"
  say ""
  say "KLAAR. De releaseroute is verwijderd; de rest is gelijk gebleven."
  say "  UNDO_OK $POOL/$PROVIDER"
fi
STOPPED=1
