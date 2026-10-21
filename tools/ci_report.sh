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
tail -n 40 "$out"
exit "$code"
