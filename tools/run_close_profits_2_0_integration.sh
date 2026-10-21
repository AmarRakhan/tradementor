#!/usr/bin/env bash
# Reproducible validation for Close Profits 2.0 against the REAL Firestore emulator (Aster stays a mock; no credentials,
# no production project, no orders). Needs network (npm/PyPI) + Java 21: run in CI or on an authorised dev machine.
set -euo pipefail
cd "$(dirname "$0")/.."
export GCLOUD_PROJECT=close-profits-test-only
export FIRESTORE_EMULATOR_HOST=127.0.0.1:8080
python3 -m venv /tmp/cp20-venv && . /tmp/cp20-venv/bin/activate
python -m pip install -r cloud_api/requirements.txt pytest
npm install --no-save firebase-tools@14.21.0
printf '%s\n' '{"emulators":{"firestore":{"host":"127.0.0.1","port":8080}}}' > /tmp/cp20-firebase.json
# 1) model-based scenarios (real route source, in-memory Firestore MODEL)
( cd cloud_api && python -m unittest -v test_close_profits_2_0_integration )
# 2) the same scenarios on the REAL Firestore emulator
npx firebase emulators:exec --config /tmp/cp20-firebase.json --only firestore --project "$GCLOUD_PROJECT" \
  'cd cloud_api && python -m unittest -v test_close_profits_2_0_firestore_emulator'
# 3) frontend handlers -> real Next proxy code -> local backend wrapper (real httpx, model Firestore)
( cd web && node --test tests/aster-close-profits-integration.test.mjs tests/aster-close-profits-scope.test.mjs tests/aster-close-profits-short-handler.test.mjs )
# 4) full backend regression with real dependencies, like cloud-backend-ci.yml
( cd cloud_api && python -m pytest -q )
