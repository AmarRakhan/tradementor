#!/usr/bin/env bash
# Simulatietests voor setup-claude-readonly.sh (bovenop de stand na setup-github-deploy-identity.sh).
set -uo pipefail
HERE="$(cd "$(dirname "$0")" && pwd)"
FIRST="$HERE/../setup-github-deploy-identity.sh"
SCRIPT="$HERE/../setup-claude-readonly.sh"
WORK="$(mktemp -d)"
trap 'rm -rf "$WORK"' EXIT
mkdir -p "$WORK/bin"
printf '#!/usr/bin/env bash\nexec python3 %q "$@"\n' "$HERE/fake_gcloud.py" > "$WORK/bin/gcloud"
chmod +x "$WORK/bin/gcloud"
export PATH="$WORK/bin:$PATH"
PASS=0; FAIL=0
DSA="github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com"
RSA="claude-readonly@tradementor-production.iam.gserviceaccount.com"
PSET="principalSet://iam.googleapis.com/projects/604335232956/locations/global/workloadIdentityPools/gh-deploy"

base() {  # stand na de eerste setup (pool gh-deploy + provider + brede binding)
  cat > "$WORK/state.json" <<JSON
{"account":"tradementor.admin@gmail.com","project_id":"tradementor-production","project_number":"604335232956",
 "project_policy":{"bindings":[{"role":"roles/owner","members":["user:tradementor.admin@gmail.com"]}],"version":1},
 "service_accounts":{"$DSA":{"policy":{"bindings":[],"etag":"a"}}},
 "pools":{"github":{"name":"github","displayName":"GitHub","state":"ACTIVE",
   "providers":{"tradementor-production":{"name":"tradementor-production","state":"ACTIVE","attributeCondition":"old","attributeMapping":{"google.subject":"assertion.sub"},"oidc":{"issuerUri":"https://token.actions.githubusercontent.com"}}}}}}
JSON
  env FAKE_STATE="$WORK/state.json" OUT_DIR="$WORK/o1" CONFIRM_ANSWER=JA bash "$FIRST" setup > /dev/null 2>&1 || { echo "basis-setup mislukt"; exit 1; }
  rm -rf "$WORK/o1"; cp "$WORK/state.json" "$WORK/base.json"; cp "$WORK/state.json" "$WORK/state0.json"
}
run() { local mode="$1"; shift; rm -rf "$WORK/out"
  env FAKE_STATE="$WORK/state.json" OUT_DIR="$WORK/out" "$@" bash "$SCRIPT" "$mode" > "$WORK/stdout" 2> "$WORK/stderr"; echo $?; }
q() { python3 -c "import json,sys; s=json.load(open('$WORK/state.json')); print(eval(sys.argv[1]))" "$1"; }
check() { local name="$1"; shift
  if "$@"; then PASS=$((PASS+1)); echo "PASS  $name"; else FAIL=$((FAIL+1)); echo "FAIL  $name"; sed 's/^/      /' "$WORK/stdout" "$WORK/stderr" | tail -12; fi; }
same_as() { python3 - "$1" "$WORK/state.json" <<'PY'
import json,sys
a,b=(json.load(open(p)) for p in sys.argv[1:])
def norm(s):
    for acc in s.get("service_accounts",{}).values(): acc.get("policy",{}).pop("etag",None)
    s.get("project_policy",{}).pop("etag",None)
    for k in ("service_accounts",):
        for acc in s[k].values():
            pol=acc.get("policy",{})
            pol["bindings"]=sorted([{"role":b["role"],"members":sorted(b["members"])} for b in pol.get("bindings",[]) if b.get("members")], key=lambda x:x["role"])
    pp=s.get("project_policy",{}); pp["bindings"]=sorted([{"role":b["role"],"members":sorted(b["members"])} for b in pp.get("bindings",[]) if b.get("members")], key=lambda x:x["role"])
    return s
sys.exit(0 if norm(a)==norm(b) else 1)
PY
}
members() { q "sorted(m for b in s['service_accounts'].get('$1',{}).get('policy',{}).get('bindings',[]) for m in b['members'])"; }
prov() { q "s['pools']['gh-deploy']['providers']['github-main']['$1']"; }

# 1. Setup
base; rc=$(run setup CONFIRM_ANSWER=JA)
check "setup slaagt" test "$rc" = 0
check "meldt READONLY_OK" grep -q "READONLY_OK sa=claude-readonly rollen=7" "$WORK/stdout"
check "read-SA bestaat" test "$(q "'$RSA' in s['service_accounts']")" = True
check "precies 7 rollen voor read-SA" test "$(q "sum('serviceAccount:$RSA' in b['members'] for b in s['project_policy']['bindings'])")" = 7
check "geen schrijfrol voor read-SA" test "$(q "[b['role'] for b in s['project_policy']['bindings'] if 'serviceAccount:$RSA' in b['members'] and not (b['role'].endswith('.viewer') or b['role'].endswith('.reader'))]")" = "[]"
check "owner ongewijzigd" test "$(q "[b for b in s['project_policy']['bindings'] if b['role']=='roles/owner'][0]['members']")" = "['user:tradementor.admin@gmail.com']"
check "deploy-SA alleen release" test "$(members "$DSA")" = "['$PSET/attribute.workflow/release']"
check "read-SA alleen diagnose" test "$(members "$RSA")" = "['$PSET/attribute.workflow/diagnose']"
check "mapping nieuw" grep -q "diagnose.yml@refs/heads/main') ? 'diagnose' : 'release'" <(prov attributeMapping)
check "conditie bevat diagnose.yml" grep -q "diagnose.yml@refs/heads/main'" <(prov attributeCondition)
check "oude provider ongewijzigd" test "$(q "s['pools']['github']['providers']['tradementor-production']['attributeCondition']")" = old

# 2. Herhalen
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "herhalen slaagt" test "$rc" = 0
check "herhalen wijzigt niets" same_as "$WORK/state0.json"

# 3. Undo
rc=$(run undo CONFIRM_ANSWER=VERWIJDER)
check "undo slaagt" test "$rc" = 0
check "undo: terug naar stand na eerste setup" same_as "$WORK/base.json"

# 4. Geen JA
base; rc=$(run setup CONFIRM_ANSWER=ja)
check "geen JA: stopt" test "$rc" = 1
check "geen JA: niets gewijzigd" same_as "$WORK/base.json"

# 5. Provider met onbekende instellingen
base; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["pools"]["gh-deploy"]["providers"]["github-main"]["attributeCondition"]="true"; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "vreemde provider: stopt" test "$rc" = 1
check "vreemde provider: niets gewijzigd" same_as "$WORK/state0.json"

# 6. Provider-update faalt: release blijft werken via oude binding, herhalen maakt af
base; rc=$(run setup CONFIRM_ANSWER=JA FAKE_FAIL=update-oidc)
check "update faalt: stopt" test "$rc" = 1
check "update faalt: deploy heeft oud én release" test "$(members "$DSA")" = "['$PSET/attribute.repository_id/1324367697', '$PSET/attribute.workflow/release']"
check "update faalt: oude mapping nog actief" grep -q "repository_id" <(prov attributeMapping)
check "update faalt: read-SA nog niet gekoppeld" test "$(members "$RSA")" = "[]"
rc=$(run setup CONFIRM_ANSWER=JA)
check "update faalt: herhalen maakt af" test "$rc" = 0
check "update faalt: daarna deploy alleen release" test "$(members "$DSA")" = "['$PSET/attribute.workflow/release']"

# 7. Verwijderen oude binding faalt
base; rc=$(run setup CONFIRM_ANSWER=JA FAKE_FAIL="remove-iam-policy-binding $DSA")
check "remove faalt: stopt" test "$rc" = 1
check "remove faalt: diagnose nog niet gekoppeld" test "$(members "$RSA")" = "[]"
rc=$(run setup CONFIRM_ANSWER=JA)
check "remove faalt: herhalen maakt af" test "$rc" = 0

# 8. Verkeerd projectnummer
base; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); s["project_number"]="1"; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "verkeerd project: stopt" test "$rc" = 1
check "verkeerd project: niets gewijzigd" same_as "$WORK/state0.json"

# 9. Eerste setup ontbreekt
base; python3 - "$WORK/state.json" <<'PY'
import json,sys; s=json.load(open(sys.argv[1])); del s["pools"]["gh-deploy"]; json.dump(s,open(sys.argv[1],"w"))
PY
cp "$WORK/state.json" "$WORK/state0.json"; rc=$(run setup CONFIRM_ANSWER=JA)
check "geen gh-deploy: stopt" test "$rc" = 1
check "geen gh-deploy: niets gewijzigd" same_as "$WORK/state0.json"

echo
echo "RESULTAAT: $PASS PASS / $FAIL FAIL"
[ "$FAIL" = 0 ]
