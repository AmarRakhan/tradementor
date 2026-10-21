#!/usr/bin/env bash
# Run a command, keep its exit status, and publish the last lines of its output as a GitHub annotation so results
# are readable through the check-runs API (job logs are not downloadable from every environment).
# usage: tools/ci_report.sh "<title>" <tail-lines> <command...>
set -uo pipefail
title="$1"; lines="$2"; shift 2
out="$(mktemp)"
"$@" >"$out" 2>&1; code=$?
text="exit=${code}"$'\n'"$(tail -n "$lines" "$out")"
text="${text//'%'/'%25'}"; text="${text//$'\r'/'%0D'}"; text="${text//$'\n'/'%0A'}"
if [ "$code" -eq 0 ]; then echo "::notice title=${title}::${text:0:60000}"; else echo "::error title=${title}::${text:0:60000}"; fi
# compact verdict annotation (always short, never truncated): summary-looking lines + last 6 lines
sumtext="exit=${code}"$'\n'"$(grep -E '^(Ran |OK|FAILED|[0-9]+ (passed|failed)|=+ .*(passed|failed)|ℹ (tests|pass|fail|skipped|cancelled))|[0-9]+ passed|[0-9]+ failed' "$out" | tail -n 12)"
sumtext="${sumtext//'%'/'%25'}"; sumtext="${sumtext//$'\r'/'%0D'}"; sumtext="${sumtext//$'\n'/'%0A'}"
echo "::notice title=SUMMARY ${title}::${sumtext:0:3000}"
if [ "$code" -ne 0 ]; then
  ftext="$(grep -E '^(FAIL|ERROR): |^[A-Za-z_.]*(Error|Exception)[:(]|^AssertionError|^E  |line [0-9]+, in test_|^- |^\+ ' "$out" | cut -c1-230 | head -n 45)"
  ftext="${ftext//'%'/'%25'}"; ftext="${ftext//$'\r'/'%0D'}"; ftext="${ftext//$'\n'/'%0A'}"
  echo "::error title=FAILURES ${title}::${ftext:0:3500}"
fi
tail -n 40 "$out"
exit "$code"
