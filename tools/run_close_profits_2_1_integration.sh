#!/usr/bin/env bash
# Reproducible FULL validation for Close Profits 2.1. Needs network (npm/PyPI) + Java 21 -> run in CI or on an
# authorised dev machine, NOT in the offline review sandbox. Uses ONLY the Firestore emulator and mocked Aster
# (no credentials, no production project, no orders). Mirrors .github/workflows/extreme-spike-firestore-emulator.yml.
set -euo pipefail
cd "$(dirname "$0")/.."
export GCLOUD_PROJECT=close-profits-test-only
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
python3 -m venv /tmp/cp21-venv && . /tmp/cp21-venv/bin/activate
python -m pip install -r cloud_api/requirements.txt pytest
npm install --no-save firebase-tools@14.21.0
printf '%s\n' '{"emulators":{"firestore":{"host":"127.0.0.1","port":8080}}}' > /tmp/cp21-firebase.json
# 1) pure + route tests (no emulator needed; real httpx so the 2 ContractRules tests run too)
( cd cloud_api && python -m unittest -v test_close_profits_2_1_guard )
# 2) real Firestore transactions (lease) + ownership reads against the emulator
npx firebase emulators:exec --config /tmp/cp21-firebase.json --only firestore --project "$GCLOUD_PROJECT" \
  'PYTHONPATH=cloud_api python -m unittest -v cloud_api.test_close_profits_2_1_firestore_emulator'
# 3) existing Recovery/Spike emulator suites (must stay green: proves Recovery fences/claims untouched)
npx firebase emulators:exec --config /tmp/cp21-firebase.json --only firestore --project "$GCLOUD_PROJECT" \
  'PYTHONPATH=cloud_api python -m unittest -v cloud_api.test_short_recovery_fence_emulator cloud_api.test_short_recovery_firestore_emulator_integration cloud_api.test_aster_spike_firestore_emulator'
# 4) whole backend suite with real dependencies (pytest like cloud-backend-ci.yml)
( cd cloud_api && python -m pytest -q )
# 5) web
( cd web && node --test tests/aster-close-profits-2-1-safety.test.mjs tests/aster-close-profits-short-handler.test.mjs )
