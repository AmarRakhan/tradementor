#!/usr/bin/env bash
set -euo pipefail
: "${RUNNER_TEMP:=/tmp}"
LIVE_B=f87d6b201790d612f970355f3b8c4c8766938941
LIVE_W=89ab74a0cc488979b1dc6231ffa27fc8e293a627
BASE=81f1d8006e3df0dce8bef5688493f16b61b8a13c
REL=$(git rev-parse origin/release/close-profits-2-0)
git checkout -q --detach "$REL"
bash tools/verify_close_profits_release.sh --source "$REL" --live "$LIVE_B" --baseline "$BASE"
bash tools/verify_close_profits_release.sh --source "$REL" --live "$LIVE_W" --paths web/
mustfail() { if bash tools/verify_close_profits_release.sh "$@" > "$RUNNER_TEMP/mf.txt" 2>&1; then echo "MUST HAVE FAILED: $*"; cat "$RUNNER_TEMP/mf.txt"; exit 1; fi; echo "INFO refused as required: $1 $2 -> $(head -1 "$RUNNER_TEMP/mf.txt")"; }
# the whole canonical development branch (SHORT Recovery, Spike, 602/603, ...) and the integration candidate
mustfail --source "$(git rev-parse origin/amar-crypto-bot-2026-cloud)" --live "$LIVE_B"
mustfail --source "$(git rev-parse origin/amar-crypto-bot-2026-cloud)" --live "$LIVE_W" --paths web/
if git rev-parse -q --verify origin/release/close-profits-2-0-integration > /dev/null; then
  mustfail --source "$(git rev-parse origin/release/close-profits-2-0-integration)" --live "$LIVE_B"
fi
# a commit that is not a descendant of the live commit
mustfail --source "$LIVE_W" --live "$LIVE_B"
# synthetic tampering on top of the release
git config user.email ci@example.invalid; git config user.name ci
git checkout -q --detach "$REL"; echo "x = 1" > cloud_api/short_recovery_executor_adapter.py
git add -A; git commit -qm foreign-file; mustfail --source "$(git rev-parse HEAD)" --live "$LIVE_B"
git checkout -q --detach "$REL"; git rm -q cloud_api/aster_gateway.py
git commit -qm deletion; mustfail --source "$(git rev-parse HEAD)" --live "$LIVE_B"
git checkout -q --detach "$REL"; echo "// SHORT recovery" >> web/components/aster-position-card.tsx 2>/dev/null || echo "// x" >> web/app/page.tsx
git add -A; git commit -qm foreign-web; mustfail --source "$(git rev-parse HEAD)" --live "$LIVE_W" --paths web/
git checkout -q --detach "$REL"; echo "// harmless note" >> web/lib/release-history.ts
git add -A; git commit -qm allowed-change; bash tools/verify_close_profits_release.sh --source "$(git rev-parse HEAD)" --live "$LIVE_W" --paths web/
echo "INFO release guards: all positive and negative cases behaved as required"
