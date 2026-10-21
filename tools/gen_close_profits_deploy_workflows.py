#!/usr/bin/env python3
"""Close Profits 2.0: derive the two exact-commit deploy workflows from the PROVEN production workflows.

The originals are pinned by git blob id (byte-identical at the live commits f87d6b20 / 89ab74a0 that deployed the code now
in production). `--check` regenerates both workflows in memory and fails when a committed file differs in any way from
"original + the documented guard changes", so no unreviewed edit can hide in them. `--write` rewrites them.
"""
import subprocess
import sys

ORIG_BACKEND_BLOB = "7f626ae5c5ff34bc3020c84aa4a95233a3e08190"   # .github/workflows/deploy-cloud-production.yml
ORIG_WEB_BLOB = "d27328ef12d7beb67a6c930ccbd8d1a8d28c0350"       # .github/workflows/deploy-shared-v44-testapp.yml
OUT = {"backend": ".github/workflows/deploy-close-profits-2-0-backend.yml",
       "web": ".github/workflows/deploy-close-profits-2-0-web.yml"}


def blob(oid):
    return subprocess.check_output(["git", "cat-file", "-p", oid], text=True)


orig_b, orig_w = blob(ORIG_BACKEND_BLOB), blob(ORIG_WEB_BLOB)
REL = "release/close-profits-2-0"
LIVE_B = "f87d6b201790d612f970355f3b8c4c8766938941"
LIVE_W = "89ab74a0cc488979b1dc6231ffa27fc8e293a627"
def sub(text, old, new, count=1):
    assert text.count(old) == count, (text.count(old), old[:80])
    return text.replace(old, new)


# ------------------------------------------------------------------ backend
b = orig_b
b = sub(b, "name: Deploy Cloud Production Backend\n",
        "name: Deploy Close Profits 2.0 Backend (exact release commit)\n"
        "# Generated from deploy-cloud-production.yml (proven) with ONLY these changes: dispatch from the release branch on\n"
        "# one exact commit that must be live+Close Profits 2.0 files only (tools/verify_close_profits_release.sh), no push\n"
        "# trigger, live source must still be the commit this release was built on. Everything else is unchanged.\n")
b = sub(b, '''  push:
    branches:
      - amar-crypto-bot-2026-cloud
    paths:
      - ".github/deploy-requests/production-backend.json"
''', "")
b = sub(b, 'description: "Type DEPLOY_PRODUCTION_BACKEND"', 'description: "Type DEPLOY_CLOSE_PROFITS_2_0_BACKEND"')
b = sub(b, 'description: "Exact 40-character repository commit to build, test and deploy"',
        f'description: "Exact 40-character commit = tip of {REL} (must equal the dispatched commit)"')
b = sub(b, '''  PROTECTED_BACKEND_BASELINE: 81f1d8006e3df0dce8bef5688493f16b61b8a13c
''', f'''  PROTECTED_BACKEND_BASELINE: 81f1d8006e3df0dce8bef5688493f16b61b8a13c
  # The backend source this release was built on and tested against. Production must still run exactly this.
  LIVE_BACKEND_SOURCE_COMMIT: {LIVE_B}
  RELEASE_BRANCH: {REL}
''')
b = sub(b, '''    if: >-
      github.event_name == 'workflow_dispatch' ||
      (github.event_name == 'push' && github.actor == 'AmarRakhan')
''', "    if: github.event_name == 'workflow_dispatch'\n")
b = sub(b, 'test "$MANUAL_CONFIRMATION" = "DEPLOY_PRODUCTION_BACKEND"', 'test "$MANUAL_CONFIRMATION" = "DEPLOY_CLOSE_PROFITS_2_0_BACKEND"')
b = sub(b, '''          case "$GITHUB_EVENT_NAME" in
            workflow_dispatch)
              test "$GITHUB_REF" = "refs/heads/amar-crypto-bot-2026-cloud"
              ;;''', '''          case "$GITHUB_EVENT_NAME" in
            workflow_dispatch)
              test "$GITHUB_REF" = "refs/heads/release/close-profits-2-0"
              ;;''')
start = b.index('          git fetch origin amar-crypto-bot-2026-cloud --quiet\n')
end_marker = '            git merge-base --is-ancestor "$SOURCE_COMMIT" "origin/amar-crypto-bot-2026-cloud"\n          fi\n'
end = b.index(end_marker) + len(end_marker)
b = b[:start] + '''          git fetch origin "$RELEASE_BRANCH" --quiet
          # Immutable release: the commit that holds this workflow, the requested source and the tip of the release
          # branch are ONE commit, and it differs from the live commit by Close Profits 2.0 files only.
          test "$SOURCE_COMMIT" = "$GITHUB_SHA"
          test "$SOURCE_COMMIT" = "$(git rev-parse "origin/$RELEASE_BRANCH")"
          bash tools/verify_close_profits_release.sh --source "$SOURCE_COMMIT" --live "$LIVE_BACKEND_SOURCE_COMMIT" --baseline "$PROTECTED_BACKEND_BASELINE"
''' + b[end:]
b = sub(b, '          print(f"PREVIOUS_SOURCE_COMMIT={previous}")\n',
        '          assert previous == __import__("os").environ["LIVE_BACKEND_SOURCE_COMMIT"], f"production runs {previous}, not the commit this release was built and tested on"\n'
        '          print(f"PREVIOUS_SOURCE_COMMIT={previous}")\n')

# ------------------------------------------------------------------ web
w = orig_w
w = sub(w, "name: Deploy Shared V46 Testapp\n",
        "name: Deploy Close Profits 2.0 Web (exact release commit)\n"
        "# Generated from deploy-shared-v44-testapp.yml (proven) with ONLY these changes: dispatch from the release branch on\n"
        "# one exact commit whose web/ is the live web + Close Profits 2.0 files only, no push trigger, the backend must\n"
        "# already serve exactly this commit, build number must always advance. Everything else is unchanged.\n")
w = sub(w, '''on:
  workflow_dispatch:
  push:
    branches:
      - amar-crypto-bot-2026-cloud
    paths:
      - "web/**"
      - ".github/workflows/deploy-shared-v44-testapp.yml"
''', f'''on:
  workflow_dispatch:
    inputs:
      confirmation:
        description: "Type DEPLOY_CLOSE_PROFITS_2_0_WEB"
        required: true
        type: string
      source_commit:
        description: "Exact 40-character commit = tip of {REL} (must equal the dispatched commit)"
        required: true
        type: string
''')
w = sub(w, '''  DEPLOY_SERVICE_ACCOUNT: github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com
''', f'''  DEPLOY_SERVICE_ACCOUNT: github-tradementor-deploy@tradementor-production.iam.gserviceaccount.com
  # The web commit this release was built on (live build 601) and the backend that must already serve the release.
  LIVE_WEB_SOURCE_COMMIT: {LIVE_W}
  BACKEND_URL: https://tradementor-api-604335232956.europe-west4.run.app
  RELEASE_BRANCH: {REL}
''')
w = sub(w, '''      - name: Check out canonical branch
        uses: actions/checkout@v4
        with:
          fetch-depth: 0

      - name: Verify canonical repository scope
        shell: bash
        run: |
          test "$GITHUB_REPOSITORY" = "AmarRakhan/tradementor"
          test "$GITHUB_REF" = "refs/heads/amar-crypto-bot-2026-cloud"
          test "$CLOUD_RUN_SERVICE" = "amar-bot-v44-direct-install"
          test "$GCP_PROJECT_ID" = "tradementor-production"
''', '''      - name: Check out the exact release commit
        uses: actions/checkout@v4
        with:
          ref: ${{ inputs.source_commit }}
          fetch-depth: 0

      - name: Verify release scope (exact commit, web = live web + Close Profits 2.0 only)
        shell: bash
        env:
          SOURCE_COMMIT: ${{ inputs.source_commit }}
          CONFIRMATION: ${{ inputs.confirmation }}
        run: |
          set -euo pipefail
          test "$GITHUB_REPOSITORY" = "AmarRakhan/tradementor"
          test "$GITHUB_REF" = "refs/heads/release/close-profits-2-0"
          test "$CLOUD_RUN_SERVICE" = "amar-bot-v44-direct-install"
          test "$GCP_PROJECT_ID" = "tradementor-production"
          test "$CONFIRMATION" = "DEPLOY_CLOSE_PROFITS_2_0_WEB"
          [[ "$SOURCE_COMMIT" =~ ^[0-9a-f]{40}$ ]]
          test "$(git rev-parse HEAD)" = "$SOURCE_COMMIT"
          test "$SOURCE_COMMIT" = "$GITHUB_SHA"
          git fetch origin "$RELEASE_BRANCH" --quiet
          test "$SOURCE_COMMIT" = "$(git rev-parse "origin/$RELEASE_BRANCH")"
          bash tools/verify_close_profits_release.sh --source "$SOURCE_COMMIT" --live "$LIVE_WEB_SOURCE_COMMIT" --paths web/

      - name: Backend must already serve exactly this release (backend first, then web)
        shell: bash
        env:
          SOURCE_COMMIT: ${{ inputs.source_commit }}
        run: |
          set -euo pipefail
          curl --fail --silent --show-error --retry 5 --retry-delay 3 "$BACKEND_URL/health" > "$RUNNER_TEMP/backend-health.json"
          curl --fail --silent --show-error --retry 5 --retry-delay 3 "$BACKEND_URL/openapi.json" > "$RUNNER_TEMP/backend-openapi.json"
          python - "$RUNNER_TEMP/backend-health.json" "$RUNNER_TEMP/backend-openapi.json" "$SOURCE_COMMIT" <<'PY'
          import json, sys
          health = json.load(open(sys.argv[1], encoding="utf-8"))
          paths = json.load(open(sys.argv[2], encoding="utf-8")).get("paths", {})
          assert health.get("status") == "ready", health
          assert health.get("sourceCommit") == sys.argv[3], f"backend runs {health.get('sourceCommit')}, deploy the backend first"
          assert "/v1/me/aster/positions/manual-profit-close-plan" in paths, "backend lacks the Close Profits 2.0 preview route"
          PY
''')
w = sub(w, '''          if [ "$GITHUB_EVENT_NAME" = "push" ]; then
            python - "$CURRENT_BUILD" "$WEBAPP_BUILD_NUMBER" <<'PY\'''', '''          if true; then
            python - "$CURRENT_BUILD" "$WEBAPP_BUILD_NUMBER" <<'PY\'''')

generated = {"backend": b, "web": w}


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "--check"
    bad = 0
    for key, path in OUT.items():
        if mode == "--write":
            open(path, "w", encoding="utf-8").write(generated[key])
            print("wrote", path)
            continue
        current = open(path, encoding="utf-8").read()
        if current != generated[key]:
            print("MISMATCH:", path, "differs from the documented transformation of the proven workflow")
            bad = 1
        else:
            print("OK:", path, "== proven original + documented guard changes")
    sys.exit(bad)


if __name__ == "__main__":
    main()
