# AGENT HANDOFF — Amar Crypto Bot 2026 Cloud

Last updated: 2026-09-19
Active task: 24/7 infrastructure, GitHub Actions deployment hardening, monitoring, billing protection, and chat handoff.

## Current status
- Audit complete; infrastructure hardening is being implemented on feature branch `agent/infra-24x7-20260919`. No trading logic changed.
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

## Workstation
- Cloud Workstation remains available as emergency access.
- Current config uses e2-standard-4 with 2h idle timeout and 6h running timeout.
- Do not disable Workstation until GitHub-only deploy, diagnostics, rollback, and production verification are proven.

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
- Feature branch: `agent/infra-24x7-20260919`.
- Production deploy workflow hardened with exact-commit verification, Firestore/Aster prechecks, saved rollback revision, post-promotion verification, and automatic rollback.
- New GitHub-hosted 15-minute read-only production monitor added for billing, Cloud Run health, Firestore, scheduler state, recent successful Aster ticks, backend 5xx rate, and Aster public connectivity.
- Safety-contract tests added for both workflows.
- Production has NOT been redeployed yet.

## Exact next step
1. Run/verify CI on the feature branch/PR.
2. Fix any CI failures without touching trading logic.
3. Merge the validated infra changes into `amar-crypto-bot-2026-cloud`.
4. Dispatch the hardened production workflow and verify candidate, promotion, and rollback path.
5. Configure GCP notification channel / alert policies and improve billing thresholds.
6. Re-audit Workstation costs and only then decide whether it can be stopped.
