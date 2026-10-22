#!/usr/bin/env bash
# Eenmalige setup: alleen-lezen toegang voor Claude via GitHub (.github/workflows/diagnose.yml).
#
# Wat dit doet (en verder niets):
#   1. Nieuw service account claude-readonly@ met ALLEEN deze projectrollen:
#      run.viewer, logging.viewer, monitoring.viewer, datastore.viewer, cloudscheduler.viewer,
#      artifactregistry.reader, compute.viewer.   Geen secrets, geen schrijfrechten, geen IAM-wijzigrechten.
#   2. Provider github-main (pool gh-deploy) splitst per workflow:
#        release-backend.yml / release-backend-rollback.yml (environment release) -> attribute.workflow = release
#        diagnose.yml                                                           -> attribute.workflow = diagnose
#   3. Deploy-SA: binding verhuist van attribute.repository_id/... naar attribute.workflow/release
#      (diagnose kan het deploy-account dus NOOIT gebruiken). Read-SA: binding op attribute.workflow/diagnose.
# Volgorde is zo gekozen dat er op geen enkel moment meer rechten zijn dan bedoeld.
# Ongedaan maken:  bash setup-claude-readonly.sh undo
set -euo pipefail
umask 077

PROJECT_ID="tradementor-production"
PROJECT_NUMBER="604335232956"
POOL="gh-deploy"
PROVIDER="github-main"
OLD_POOL="github"
OLD_PROVIDER="tradementor-production"
DEPLOY_SA="github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com"
READ_SA_ID="claude-readonly"
READ_SA="${READ_SA_ID}@${PROJECT_ID}.iam.gserviceaccount.com"
READ_ROLES="roles/run.viewer roles/logging.viewer roles/monitoring.viewer roles/datastore.viewer roles/cloudscheduler.viewer roles/artifactregistry.reader roles/compute.viewer"
WIU="roles/iam.workloadIdentityUser"
REPO_ID="1324367697"
OWNER_ID="313542222"
WF="AmarRakhan/tradementor/.github/workflows"
PSET="principalSet://iam.googleapis.com/projects/${PROJECT_NUMBER}/locations/global/workloadIdentityPools/${POOL}"
OLD_MEMBER="${PSET}/attribute.repository_id/${REPO_ID}"
RELEASE_MEMBER="${PSET}/attribute.workflow/release"
DIAG_MEMBER="${PSET}/attribute.workflow/diagnose"
OLD_MAPPING="google.subject=assertion.sub,attribute.repository_id=assertion.repository_id"
NEW_MAPPING="google.subject=assertion.sub,attribute.workflow=assertion.workflow_ref.endsWith('/diagnose.yml@refs/heads/main') ? 'diagnose' : 'release'"
BASE="assertion.repository_id == '${REPO_ID}' && assertion.repository_owner_id == '${OWNER_ID}' && assertion.ref == 'refs/heads/main' && assertion.ref_type == 'branch' && assertion.event_name == 'workflow_dispatch'"
OLD_CONDITION="${BASE} && assertion.environment == 'release' && assertion.job_workflow_ref == assertion.workflow_ref && (assertion.workflow_ref == '${WF}/release-backend.yml@refs/heads/main' || assertion.workflow_ref == '${WF}/release-backend-rollback.yml@refs/heads/main')"
NEW_CONDITION="${BASE} && assertion.job_workflow_ref == assertion.workflow_ref && ((assertion.environment == 'release' && (assertion.workflow_ref == '${WF}/release-backend.yml@refs/heads/main' || assertion.workflow_ref == '${WF}/release-backend-rollback.yml@refs/heads/main')) || assertion.workflow_ref == '${WF}/diagnose.yml@refs/heads/main')"

MODE="${1:-setup}"
OUT="${OUT_DIR:-$HOME/claude-readonly-$(date +%Y%m%d-%H%M%S)}"
mkdir -p "$OUT"; chmod 700 "$OUT"
DONE=()

say()  { printf '%s\n' "$*"; }
report() { if [ "${#DONE[@]}" -gt 0 ]; then printf 'Al gedaan in deze run: %s\nOpnieuw draaien maakt het af; ongedaan maken: bash %s undo\n' "${DONE[*]}" "$0" >&2; else printf 'Er is niets gewijzigd.\n' >&2; fi; }
stop() { STOPPED=1; printf '\nSTOP: %s\n' "$*" >&2; report; exit 1; }
trap 'rc=$?; [ $rc -ne 0 ] && [ -z "${STOPPED:-}" ] && { printf "\nSTOP: onverwachte fout (exit %s), zie de melding hierboven\n" "$rc" >&2; report; }' EXIT
ask() { if [ -n "${CONFIRM_ANSWER:-}" ]; then ANSWER="$CONFIRM_ANSWER"; else read -r -p "$1" ANSWER < /dev/tty || ANSWER=""; fi; }
g() { gcloud --project="$PROJECT_ID" --quiet "$@"; }

provider_state() {  # $1 json -> OLD | NEW | OTHER
  python3 - "$1" "$OLD_CONDITION" "$NEW_CONDITION" <<'PY'
import json, sys
p = json.load(open(sys.argv[1]))
old_map = {"google.subject": "assertion.sub", "attribute.repository_id": "assertion.repository_id"}
new_map = {"google.subject": "assertion.sub",
           "attribute.workflow": "assertion.workflow_ref.endsWith('/diagnose.yml@refs/heads/main') ? 'diagnose' : 'release'"}
c, m = p.get("attributeCondition"), p.get("attributeMapping")
if p.get("state") != "ACTIVE": print("OTHER"); sys.exit()
if (p.get("oidc") or {}).get("issuerUri") != "https://token.actions.githubusercontent.com": print("OTHER"); sys.exit()
if c == sys.argv[2] and m == old_map: print("OLD")
elif c == sys.argv[3] and m == new_map: print("NEW")
else: print("OTHER")
PY
}

has() {  # $1 policy json, $2 role, $3 member
  python3 - "$1" "$2" "$3" <<'PY'
import json, sys
pol = json.load(open(sys.argv[1]))
print("yes" if any(b.get("role") == sys.argv[2] and sys.argv[3] in (b.get("members") or []) and not b.get("condition")
                   for b in pol.get("bindings") or []) else "no")
PY
}

delta_ok() {  # $1 before, $2 after, $3 added "role|member;...", $4 removed "role|member;..."
  python3 - "$@" <<'PY'
import json, sys
def flat(path):
    pol = json.load(open(path))
    s = set()
    for b in pol.get("bindings") or []:
        for m in b.get("members") or []:
            s.add((b.get("role"), m, json.dumps(b.get("condition"), sort_keys=True)))
    return s, {k: v for k, v in pol.items() if k not in ("bindings", "etag", "version")}
def parse(arg):
    return {(x.split("|")[0], x.split("|")[1], "null") for x in arg.split(";") if x}
b, bx = flat(sys.argv[1]); a, ax = flat(sys.argv[2])
want = (b | parse(sys.argv[3])) - parse(sys.argv[4])
if a != want or ax != bx:
    print("onverwacht: +%s -%s" % (sorted(a - want)[:5], sorted(want - a)[:5])); sys.exit(1)
print("ok")
PY
}

# ---------- vooraf: alleen lezen ----------
command -v gcloud >/dev/null || stop "gcloud ontbreekt (draai dit in Google Cloud Shell)"
command -v python3 >/dev/null || stop "python3 ontbreekt"
ACCOUNT="$(gcloud config get-value account 2>/dev/null || true)"
[ -n "$ACCOUNT" ] || stop "geen ingelogd Google-account"
NUM="$(gcloud projects describe "$PROJECT_ID" --format='value(projectNumber)' 2>/dev/null || true)"
[ "$NUM" = "$PROJECT_NUMBER" ] || stop "project $PROJECT_ID niet gevonden of verkeerd projectnummer (${NUM:-geen})"
g iam service-accounts describe "$DEPLOY_SA" --format=json > "$OUT/deploy-sa.json" 2>/dev/null || stop "deploy-SA niet gevonden"
g iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool="$POOL" --location=global \
  --format=json > "$OUT/provider-before.json" 2>/dev/null || stop "provider $POOL/$PROVIDER niet gevonden (eerst setup-github-deploy-identity.sh)"
PSTATE="$(provider_state "$OUT/provider-before.json")"
[ "$PSTATE" != "OTHER" ] || stop "provider $PROVIDER heeft onverwachte instellingen; niets aangeraakt"
g iam workload-identity-pools providers describe "$OLD_PROVIDER" --workload-identity-pool="$OLD_POOL" --location=global \
  --format=json > "$OUT/old-provider-before.json" || stop "bestaande provider niet leesbaar"
g projects get-iam-policy "$PROJECT_ID" --format=json > "$OUT/project-before.json" || stop "project-IAM niet leesbaar"
g iam service-accounts get-iam-policy "$DEPLOY_SA" --format=json > "$OUT/deploy-before.json" || stop "IAM van deploy-SA niet leesbaar"
SA_EXISTS=no
if g iam service-accounts describe "$READ_SA" --format=json > "$OUT/read-sa.json" 2>/dev/null; then
  SA_EXISTS=yes
  g iam service-accounts get-iam-policy "$READ_SA" --format=json > "$OUT/read-before.json"
else
  echo '{}' > "$OUT/read-before.json"
fi

say ""
say "=== Tradementor: alleen-lezen toegang voor Claude ==="
say "Account:   $ACCOUNT"
say "Project:   $PROJECT_ID ($PROJECT_NUMBER)"
say "Modus:     $MODE"
say "Read-SA:   $READ_SA ($( [ $SA_EXISTS = yes ] && echo bestaat || echo nog niet))"
say "Rollen:    $READ_ROLES"
say "Provider:  $POOL/$PROVIDER (stand: $PSTATE)"
say "Bestaande pool '$OLD_POOL' en alle andere rechten blijven ongewijzigd (wordt na afloop gecontroleerd)."
say ""

ADDED_PROJECT=""; for r in $READ_ROLES; do ADDED_PROJECT="${ADDED_PROJECT}${r}|serviceAccount:${READ_SA};"; done

if [ "$MODE" = "setup" ]; then
  ask "Typ JA om dit in te stellen: "
  [ "$ANSWER" = "JA" ] || { STOPPED=1; say "Afgebroken. Er is niets gewijzigd."; exit 1; }
  if [ "$SA_EXISTS" = no ]; then
    g iam service-accounts create "$READ_SA_ID" --display-name="Claude read-only diagnose" \
      --description="Alleen lezen via .github/workflows/diagnose.yml (WIF gh-deploy)" >/dev/null
    DONE+=("service account"); say "✓ service account aangemaakt"
    for i in 1 2 3 4 5 6; do g iam service-accounts describe "$READ_SA" >/dev/null 2>&1 && break; sleep 5; done
  fi
  for r in $READ_ROLES; do
    if [ "$(has "$OUT/project-before.json" "$r" "serviceAccount:$READ_SA")" != yes ]; then
      g projects add-iam-policy-binding "$PROJECT_ID" --role="$r" --member="serviceAccount:$READ_SA" --condition=None --format=none
    fi
  done
  DONE+=("projectrollen"); say "✓ 7 alleen-lezen rollen toegekend"
  if [ "$(has "$OUT/deploy-before.json" "$WIU" "$RELEASE_MEMBER")" != yes ]; then
    g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role="$WIU" --member="$RELEASE_MEMBER" --format=none
    DONE+=("deploy-binding release"); say "✓ deploy-account gekoppeld aan release-workflows"
  fi
  if [ "$PSTATE" = OLD ]; then
    g iam workload-identity-pools providers update-oidc "$PROVIDER" --workload-identity-pool="$POOL" --location=global \
      --attribute-mapping="$NEW_MAPPING" --attribute-condition="$NEW_CONDITION" >/dev/null
    DONE+=("provider"); say "✓ provider splitst nu release en diagnose"
  fi
  if [ "$(has "$OUT/deploy-before.json" "$WIU" "$OLD_MEMBER")" = yes ]; then
    g iam service-accounts remove-iam-policy-binding "$DEPLOY_SA" --role="$WIU" --member="$OLD_MEMBER" --format=none
    DONE+=("oude deploy-binding weg"); say "✓ oude brede deploy-binding verwijderd"
  fi
  if [ "$(has "$OUT/read-before.json" "$WIU" "$DIAG_MEMBER")" != yes ]; then
    g iam service-accounts add-iam-policy-binding "$READ_SA" --role="$WIU" --member="$DIAG_MEMBER" --format=none
    DONE+=("read-binding"); say "✓ alleen-lezen account gekoppeld aan diagnose.yml"
  fi
elif [ "$MODE" = "undo" ]; then
  ask "Typ VERWIJDER om de alleen-lezen toegang te verwijderen: "
  [ "$ANSWER" = "VERWIJDER" ] || { STOPPED=1; say "Afgebroken. Er is niets gewijzigd."; exit 1; }
  [ "$(has "$OUT/deploy-before.json" "$WIU" "$OLD_MEMBER")" = yes ] || \
    g iam service-accounts add-iam-policy-binding "$DEPLOY_SA" --role="$WIU" --member="$OLD_MEMBER" --format=none
  if [ "$PSTATE" = NEW ]; then
    g iam workload-identity-pools providers update-oidc "$PROVIDER" --workload-identity-pool="$POOL" --location=global \
      --attribute-mapping="$OLD_MAPPING" --attribute-condition="$OLD_CONDITION" >/dev/null
  fi
  [ "$(has "$OUT/deploy-before.json" "$WIU" "$RELEASE_MEMBER")" != yes ] || \
    g iam service-accounts remove-iam-policy-binding "$DEPLOY_SA" --role="$WIU" --member="$RELEASE_MEMBER" --format=none
  for r in $READ_ROLES; do
    [ "$(has "$OUT/project-before.json" "$r" "serviceAccount:$READ_SA")" != yes ] || \
      g projects remove-iam-policy-binding "$PROJECT_ID" --role="$r" --member="serviceAccount:$READ_SA" --condition=None --format=none
  done
  [ "$SA_EXISTS" = no ] || g iam service-accounts delete "$READ_SA" >/dev/null
  say "✓ teruggezet naar de stand van vanochtend"
else
  stop "onbekende modus '$MODE' (gebruik: setup of undo)"
fi

# ---------- achteraf: bewijzen dat alleen dit is veranderd ----------
g projects get-iam-policy "$PROJECT_ID" --format=json > "$OUT/project-after.json"
g iam service-accounts get-iam-policy "$DEPLOY_SA" --format=json > "$OUT/deploy-after.json"
g iam workload-identity-pools providers describe "$PROVIDER" --workload-identity-pool="$POOL" --location=global --format=json > "$OUT/provider-after.json"
g iam workload-identity-pools providers describe "$OLD_PROVIDER" --workload-identity-pool="$OLD_POOL" --location=global --format=json > "$OUT/old-provider-after.json"
cmp -s "$OUT/old-provider-before.json" "$OUT/old-provider-after.json" || stop "bestaande provider is veranderd"

if [ "$MODE" = "setup" ]; then
  [ "$(provider_state "$OUT/provider-after.json")" = NEW ] || stop "provider heeft niet de nieuwe instellingen"
  D="$(delta_ok "$OUT/project-before.json" "$OUT/project-after.json" "$ADDED_PROJECT" "")" || stop "project-IAM: $D"
  D="$(delta_ok "$OUT/deploy-before.json" "$OUT/deploy-after.json" "$WIU|$RELEASE_MEMBER;" "$WIU|$OLD_MEMBER;")" || stop "deploy-SA IAM: $D"
  g iam service-accounts get-iam-policy "$READ_SA" --format=json > "$OUT/read-after.json"
  [ "$(has "$OUT/read-after.json" "$WIU" "$DIAG_MEMBER")" = yes ] || stop "read-binding ontbreekt"
  [ "$(has "$OUT/deploy-after.json" "$WIU" "$DIAG_MEMBER")" = no ] || stop "diagnose mag het deploy-account NIET krijgen"
  HASH="$(printf '%s' "$NEW_CONDITION" | sha256sum | cut -c1-12)"
  say ""
  say "KLAAR. Alleen het read-SA, 7 leesrollen en de splitsing release/diagnose zijn nieuw; de rest is gelijk gebleven."
  say "Stuur deze regel naar Claude:"
  say ""
  say "  READONLY_OK sa=$READ_SA_ID rollen=7 conditie=$HASH deploy=release-only"
  say ""
  say "(Google heeft soms een paar minuten nodig voordat nieuwe rechten werken.)"
else
  [ "$(provider_state "$OUT/provider-after.json")" = OLD ] || stop "provider niet terug in de oude stand"
  say "  READONLY_UNDO_OK"
fi
STOPPED=1
