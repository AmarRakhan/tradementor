#!/usr/bin/env bash
# Simulatietests voor setup-github-deploy-identity.sh met een strikte nep-gcloud.
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
SCRIPT="$HERE/../setup-github-deploy-identity.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
printf '#!/usr/bin/env bash\nexec python3 %q "$@"\n' "$HERE/fake_gcloud.py" > "$WORK/bin/gcloud"
chmod +x "$WORK/bin/gcloud"
export PATH="$WORK/bin:$PATH"
PASS=0; FAIL=0
SA="github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com"
MEMBER="principalSet://iam.googleapis.com/projects/604335232956/locations/global/workloadIdentityPools/gh-deploy/attribute.repository_id/1324367697"

fresh() {
  cat > "$WORK/state.json" <<JSON
{"account":"amar.rakhan@gmail.com","project_id":"tradementor-production","project_number":"604335232956",
 "service_accounts":{"$SA":{"policy":{"bindings":[{"role":"roles/iam.workloadIdentityUser","members":["principalSet://iam.googleapis.com/projects/604335232956/locations/global/workloadIdentityPools/github/attribute.repository/AmarRakhan/tradementor"]}],"etag":"abc","version":1}}},
 "pools":{"github":{"name":"github","displayName":"GitHub","state":"ACTIVE",
   "providers":{"tradementor-production":{"name":"tradementor-production","state":"ACTIVE","attributeCondition":"assertion.ref == 'refs/heads/amar-crypto-bot-2026-cloud'","attributeMapping":{"google.subject":"assertion.sub"},"oidc":{"issuerUri":"https://token.actions.githubusercontent.com"}}}}}}
JSON
  cp "$WORK/state.json" "$WORK/state0.json"
}
run() {  # run <mode> [env...]
  local mode="$1"; shift
  rm -rf "$WORK/out"
  env FAKE_STATE="$WORK/state.json" OUT_DIR="$WORK/out" "$@" bash "$SCRIPT" "$mode" > "$WORK/stdout" 2> "$WORK/stderr"
  echo $?
}
q() { python3 -c "import json,sys; s=json.load(open('$WORK/state.json')); print(eval(sys.argv[1]))" "$1"; }
check() {  # check <naam> <conditie-commando...>
  local name="$1"; shift
  if "$@"; then PASS=$((PASS+1)); echo "PASS  $name"; else FAIL=$((FAIL+1)); echo "FAIL  $name"; sed 's/^/      /' "$WORK/stdout" "$WORK/stderr" | tail -15; fi
}
unchanged() { python3 - "$WORK/state0.json" "$WORK/state.json" <<'PY'
import json,sys
a,b=(json.load(open(p)) for p in sys.argv[1:])
for s in (a,b):
    for acc in s["service_accounts"].values(): acc["policy"].pop("etag",None)
sys.exit(0 if a==b else 1)
PY
}
bound() { [ "$(q "'$MEMBER' in [m for b in s['service_accounts']['$SA']['policy']['bindings'] for m in b['members']]")" = True ]; }
not_bound() { ! bound; }
old_intact() { [ "$(q "s['pools']['github']==$(python3 -c "import json;print(repr(json.load(open('$WORK/state0.json'))['pools']['github']))")")" = True ]; }

# 1. Verse setup
fresh; rc=$(run setup CONFIRM_ANSWER=JA)
check "setup slaagt" test "$rc" = 0
check "setup meldt SETUP_OK" grep -q "SETUP_OK gh-deploy/github-main" "$WORK/stdout"
check "pool ACTIVE" test "$(q "s['pools']['gh-deploy']['state']")" = ACTIVE
check "provider-conditie bevat environment release" grep -q "environment == 'release'" <(q "s['pools']['gh-deploy']['providers']['github-main']['attributeCondition']")
check "provider-conditie pint workflowbestanden" grep -q "release-backend.yml@refs/heads/main" <(q "s['pools']['gh-deploy']['providers']['github-main']['attributeCondition']")
check "mapping exact" test "$(q "s['pools']['gh-deploy']['providers']['github-main']['attributeMapping']=={'google.subject':'assertion.sub','attribute.repository_id':'assertion.repository_id'}")" = True
check "binding aanwezig" bound
check "oude pool/provider ongewijzigd" old_intact
check "oude binding behouden" test "$(q "len(s['service_accounts']['$SA']['policy']['bindings'][0]['members'])")" = 2

# 2. Opnieuw draaien = niets doen
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup)
check "tweede run: niets te doen" grep -q "Alles staat er al" "$WORK/stdout"
check "tweede run: geen wijziging" unchanged
check "tweede run: exit 0" test "$rc" = 0

# 3. Ongedaan maken
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run undo CONFIRM_ANSWER=VERWIJDER)
check "undo slaagt" test "$rc" = 0
check "undo: binding weg" not_bound
check "undo: pool DELETED" test "$(q "s['pools']['gh-deploy']['state']")" = DELETED
check "undo: oude pool ongewijzigd" old_intact
check "undo: oude binding behouden" test "$(q "s['service_accounts']['$SA']['policy']['bindings'][0]['members']")" = "['principalSet://iam.googleapis.com/projects/604335232956/locations/global/workloadIdentityPools/github/attribute.repository/AmarRakhan/tradementor']"

# 4. Pool in prullenbak -> setup stopt
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "pool DELETED: stopt" test "$rc" = 1
check "pool DELETED: undelete-instructie" grep -q "undelete" "$WORK/stderr"
check "pool DELETED: niets gewijzigd" unchanged

# 5. Geen bevestiging
fresh; rc=$(run setup CONFIRM_ANSWER=nee)
check "geen JA: stopt" test "$rc" = 1
check "geen JA: niets gewijzigd" unchanged

# 6. Verkeerd projectnummer
fresh; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["project_number"]="111"; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "verkeerd projectnummer: stopt" test "$rc" = 1
check "verkeerd projectnummer: niets gewijzigd" unchanged

# 7. Geen account
fresh; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["account"]=""; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "geen account: stopt" test "$rc" = 1
check "geen account: niets gewijzigd" unchanged

# 8. Vreemde pool met dezelfde naam
fresh; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["pools"]["gh-deploy"]={"name":"gh-deploy","displayName":"iets anders","state":"ACTIVE","providers":{}}; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "vreemde pool: stopt" test "$rc" = 1
check "vreemde pool: niets gewijzigd" unchanged
rc=$(run undo CONFIRM_ANSWER=VERWIJDER)
check "vreemde pool: undo weigert" test "$rc" = 1
check "vreemde pool: undo wijzigt niets" unchanged

# 9. Onze pool, maar provider met andere conditie
fresh; CONFIRM_ANSWER=JA FAKE_FAIL="add-iam-policy-binding" run setup >/dev/null
python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["pools"]["gh-deploy"]["providers"]["github-main"]["attributeCondition"]="true"; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "afwijkende provider: stopt" test "$rc" = 1
check "afwijkende provider: niets gewijzigd" unchanged
rc=$(run undo CONFIRM_ANSWER=VERWIJDER)
check "afwijkende provider: undo weigert" test "$rc" = 1

# 10. Provider aanmaken faalt -> pool blijft, geen binding, melding met opruiminstructie
fresh; rc=$(run setup CONFIRM_ANSWER=JA FAKE_FAIL="create-oidc")
check "provider faalt: stopt" test "$rc" = 1
check "provider faalt: meldt pool + undo" grep -q "pool gh-deploy" "$WORK/stderr"
check "provider faalt: geen binding" not_bound
rc=$(run setup CONFIRM_ANSWER=JA)
check "provider faalt: hervatten slaagt" test "$rc" = 0
check "provider faalt: na hervatten binding" bound

# 11. Binding faalt -> geen binding
fresh; rc=$(run setup CONFIRM_ANSWER=JA FAKE_FAIL="add-iam-policy-binding")
check "binding faalt: stopt" test "$rc" = 1
check "binding faalt: geen binding" not_bound

# 12. Gelijktijdige wijziging aan de oude provider wordt gemeld
fresh; rc=$(run setup CONFIRM_ANSWER=JA FAKE_MUTATE_OLD=1)
check "oude provider gewijzigd: stopt" test "$rc" = 1
check "oude provider gewijzigd: gemeld" grep -q "bestaande provider is veranderd" "$WORK/stderr"

# 13. Onbekende modus
fresh; rc=$(run foo)
check "onbekende modus: stopt" test "$rc" = 1
check "onbekende modus: niets gewijzigd" unchanged

# 14. Service account ontbreekt
fresh; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["service_accounts"]={"x@y":{"policy":{}}}; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "SA ontbreekt: stopt" test "$rc" = 1
check "SA ontbreekt: niets gewijzigd" unchanged

echo
echo "RESULTAAT: $PASS PASS / $FAIL FAIL"
[ "$FAIL" = 0 ]
