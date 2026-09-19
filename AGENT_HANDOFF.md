# AGENT HANDOFF — Amar Crypto Bot 2026 Cloud

Last updated: 2026-09-19
Active task: 24/7 infrastructure, GitHub Actions deployment hardening, monitoring, billing protection, and chat handoff.

## Current status
- Audit complete; infrastructure hardening PR #106 passed Cloud Backend CI and was merged into the active cloud branch. No trading logic changed.
- Production project: `tradementor-production`, region `europe-west4`.
- Active deployment source branch: `amar-crypto-bot-2026-cloud`.
- Branch head at audit checkpoint: `c47ecdf8ee7bdb69df7155800f3ebae416afd489`.
- Default branch head at audit checkpoint: `b02013861d5d1047b3e10f51f5ccf2f6fd4f0785`.
- Current production backend revision: `tradementor-api-dca-e1f8132f-1`.
- Current production source commit reported by `/health`: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`.
- Production health currently returns HTTP 200 / status ready.
- Aster scheduler is enabled every minute and is currently returning HTTP 200.

## Incident confirmed
- Billing suspension caused Cloud Run requests to fail.
- Last successful Aster automation tick before outage: 2026-09-18 23:28 UTC.
- First billing-disabled failure: 2026-09-18 23:29 UTC.
- Billing was reinstated around 2026-09-19 04:39 UTC.
- Cloud Run returned temporary 429 no-instance responses during recovery.
- First successful Aster automation tick after recovery: 2026-09-19 05:09 UTC.
- Full trading automation interruption: approximately 5h40m.
- Root cause is confirmed from Google billing notifications as a payment failure followed by billing-account suspension. Do not add payment instrument details to this repository.

## Existing deployment controls
- `.github/workflows/deploy-cloud-production.yml` already uses GitHub Actions + Workload Identity Federation.
- It already runs backend tests, builds/pushes an image, deploys a no-traffic candidate, checks `/health`, then promotes.
- Permanent service-account keys are not required by this workflow.
- Missing/weak areas: automatic rollback after failed post-promotion verification, dependency-level production probes, centralized handoff checkpoints, Cloud Monitoring alerts, and independent billing-suspension warning.

## Monitoring audit
- No Cloud Monitoring alert policies found at audit time.
- No notification channels found at audit time.
- Cloud Billing Budget API is currently disabled for the project, although a console-created monthly budget alert exists.
- Existing monthly budget alert observed: EUR 100, with an 80% threshold notification.

## Daily operating model — REQUIRED
- Normal development MUST be GitHub-first: ChatGPT/agent → GitHub → tests/build → GitHub Actions → Workload Identity Federation → Google Cloud.
- Normal UI work (tabs, buttons, copy, layout, mobile fixes, settings fields, charts) must NOT require a Workstation connection.
- Normal backend debugging/fixes/deployments must NOT require a Workstation connection once the GitHub control-plane PRs below are validated.
- Direct Google Cloud / Workstation access is break-glass only for billing/payment, IAM/bootstrap, highly sensitive secrets, or failure of the GitHub→Google control path itself.
- A new chat must read AGENT_HANDOFF.md and CURRENT_TASK.json before modifying code or assuming deployment state.
- The Workstation remains an emergency option only; do not make it part of the normal workflow.

## Workstation
- Cloud Workstation remains available as emergency/break-glass access.
- Current config uses e2-standard-4 with 2h idle timeout and 6h running timeout.
- Do not disable it until GitHub-only diagnosis, backend deploy, rollback, and production verification are proven end-to-end.

## Must not change
- Trading strategies or order logic.
- Existing user settings.
- Wallet/exchange connections.
- Secrets / Secret Manager values.
- Account data.
- Production traffic until candidate tests pass.

## Rollback point
- Backend revision: `tradementor-api-dca-e1f8132f-1`.
- Source commit reported by production: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`.

## Implementation checkpoint
- PR #106 merged into `amar-crypto-bot-2026-cloud`.
- Infrastructure merge commit: `397fe7144325aefca6c8d08155ec69c27a835e64`.
- Latest handoff-only cloud-branch commit at this checkpoint: `1d18655febe951b041bfe0912dc2f808159fad64`.
- Cloud Backend CI run 378: SUCCESS (all backend tests passed after preserving existing safety contracts).
- Existing Botsettings reference check: SUCCESS.
- Production deploy workflow has exact-commit verification, Firestore/Aster prechecks, saved rollback revision, post-promotion verification, and automatic rollback.
- Attempted GitHub push-trigger design was rejected by existing manual-only deployment tests; PR #107 was CLOSED and NOT merged. Manual-only production safety remains intact.
- Independent public GitHub uptime workflow was merged to default branch `main` in commit `990f17120cfb193d3b5e25ce3b044b637749a3ff`; it is scheduled every 15 minutes and checks public backend health plus Aster public connectivity.
- Independent hourly ChatGPT/Gmail Cloud Billing Watch is active.
- Independent hourly ChatGPT Bot Health Watch is active.
- Production has NOT yet been redeployed with the infrastructure hardening.
- Canonical V46 web deployment is already GitHub-native: changes under `web/**` trigger tests, no-traffic candidate deployment to `amar-bot-v44-direct-install`, candidate verification, promotion, post-promotion verification, and rollback on failure via WIF.
- PR #109 (target `main`): GitHub-native issue-triggered read-only production diagnostics; CI permission fix included for existing Android workflow.
- PR #110 (target active cloud branch): backend deployment can report success/failure/rollback details back to an agent GitHub issue.
- PR #111 (target `main`): owner-only backend deploy dispatcher; only exact active-branch head with successful Cloud Backend CI can trigger the hardened deploy.
- Workstation is NOT a normal blocker anymore. GitHub control-plane completion is the current path.

## Exact next step
1. Finish CI for PRs #109, #110 and #111; merge only green changes.
2. Trigger a real `[AGENT-CONTROL] diagnose production` issue and verify the result returns to GitHub without Workstation access.
3. Trigger a safe backend deploy request through GitHub and verify candidate → promotion → production health → issue feedback; verify rollback capability without Workstation.
4. Keep the existing automatic V46 web path as the standard for UI changes.
5. After GitHub control-plane proof, handle Cloud Monitoring / budget IAM as a one-time infrastructure task, not part of normal development.
6. Re-audit costs and keep Workstation emergency-only.