#!/usr/bin/env bash
# Close Profits 2.0: mechanical proof that a commit is "the live commit + only the Close Profits 2.0 files".
#   verify_close_profits_release.sh --source <40-hex> --live <40-hex> [--paths <dir>] [--baseline <40-hex>]
# Fails (exit 1) when
#   * <source> is not a descendant of the live commit (a release must move production forward from what is live),
#   * <source> lacks the protected backend baseline,
#   * ANY file differs from the live commit outside the allow-list below (this is what keeps the unfinished SHORT
#     Recovery, Extreme Spike, Auto Hedge-slider (602/603) work and every other development out of the release),
#   * a file was deleted or renamed.
# Run with the repository checked out (full history). Read-only; never touches GitHub, Google Cloud or the network.
set -euo pipefail
SOURCE=""; LIVE=""; PATHS=""; BASELINE=""
while [ $# -gt 0 ]; do
  case "$1" in
    --source) SOURCE="$2"; shift 2;;
    --live) LIVE="$2"; shift 2;;
    --paths) PATHS="$2"; shift 2;;
    --baseline) BASELINE="$2"; shift 2;;
    *) echo "unknown argument $1" >&2; exit 2;;
  esac
done
[[ "$SOURCE" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid --source" >&2; exit 2; }
[[ "$LIVE" =~ ^[0-9a-f]{40}$ ]] || { echo "invalid --live" >&2; exit 2; }
git cat-file -e "$SOURCE^{commit}"
git cat-file -e "$LIVE^{commit}"
git merge-base --is-ancestor "$LIVE" "$SOURCE" || { echo "FAIL: source is not a descendant of the live commit $LIVE" >&2; exit 1; }
if [ -n "$BASELINE" ]; then
  git merge-base --is-ancestor "$BASELINE" "$SOURCE" || { echo "FAIL: protected baseline $BASELINE is not an ancestor" >&2; exit 1; }
fi
ALLOW='^(cloud_api/(main\.py|aster_position_loss_auto_hedge_extension\.py|manual_profit_close_(planner|snapshot)\.py|offline_[a-z_]+\.py|e2e_stack_server\.py|test_close_profits_2_0_[a-z0-9_]+\.py|test_manual_profit_close_[a-z_]+\.py)|tools/(ci_report\.sh|run_close_profits_2_0_integration\.sh|verify_close_profits_release\.sh|gen_close_profits_deploy_workflows\.py|ci_release_guards\.sh)|web/app/api/exchanges/aster/positions/manual-profit-close-plan/route\.ts|web/components/aster-recent-trades\.tsx|web/lib/(app-version|release-history)\.ts|web/tests/(aster-close-profit[a-z0-9-]*\.test\.mjs|visual/close-profits-ui[a-z.-]*)|\.github/workflows/(deploy|rollback)-close-profits-2-0(-backend|-web)?\.yml)$'
if [ -n "$PATHS" ]; then
  ROWS="$(git diff --name-status --no-renames "$LIVE" "$SOURCE" -- "$PATHS")"
else
  ROWS="$(git diff --name-status --no-renames "$LIVE" "$SOURCE")"
fi
BAD=0; COUNT=0
while IFS=$'\t' read -r STATUS FILE; do
  [ -z "${FILE:-}" ] && continue
  COUNT=$((COUNT+1))
  case "$STATUS" in A|M) ;; *) echo "FAIL: $STATUS $FILE (only added/modified files are allowed)" >&2; BAD=1; continue;; esac
  if ! printf '%s\n' "$FILE" | grep -Eq "$ALLOW"; then echo "FAIL: not part of Close Profits 2.0: $FILE" >&2; BAD=1; fi
done <<< "$ROWS"
[ "$COUNT" -gt 0 ] || { echo "FAIL: source adds nothing to the live commit" >&2; exit 1; }
[ "$BAD" -eq 0 ] || exit 1
echo "OK: $COUNT files differ from live $LIVE${PATHS:+ under $PATHS}; every one is on the Close Profits 2.0 allow-list"
