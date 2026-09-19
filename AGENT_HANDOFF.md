# AGENT HANDOFF — Amar Crypto Bot 2026 Cloud

Last updated: 2026-09-19
Status: GITHUB-FIRST CONTROL PLANE PROVEN AND COMPLETE

## Daily operating model
Normal development is now:
User → ChatGPT/agent → GitHub → tests/build → GitHub Actions → Workload Identity Federation → Google Cloud → candidate → verification → production.

For normal UI work, backend work, diagnostics, deployment and rollback, do NOT ask the user to connect Cloud Workstation first.

Direct Google Cloud / Workstation access is break-glass only for billing/payment, IAM/bootstrap, highly sensitive secrets, or failure of the GitHub→Google control path itself.

A new chat must read AGENT_HANDOFF.md and CURRENT_TASK.json before changing code or assuming production state.

## Final production proof
- GitHub-only backend deployment proof: issue #154 — SUCCESS.
- Post-deploy production diagnosis: issue #155 — HEALTHY.
- Current live revision: `tradementor-api-src-ef3a5ecd-341284`
- Current live source commit: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`
- Image mode used for proof: `existing-live-image`
- Previous rollback revision retained: `tradementor-api-dca-e1f8132f-1`

## Verified post-deploy runtime state
- Cloud Run health: ready
- Firestore metadata: reachable
- Aster scheduler: ENABLED
- Recent Aster automation tick: HTTP 200
- Backend HTTP 5xx in final 30-minute proof window: 0
- Aster public market API: reachable
- Overall runtime health: HEALTHY

## Web/UI deployment
The canonical V46 web app is already GitHub-first:
- changes under `web/**` trigger tests/build/deploy;
- WIF authenticates keylessly to Google Cloud;
- candidate gets no production traffic until verified;
- post-promotion verification and rollback are in place.

Normal requests such as new tabs, buttons, styling, mobile fixes, settings fields and charts therefore do not require Workstation access.

## Security boundaries
- WIF remains restricted to repository `AmarRakhan/tradementor` and trusted ref `refs/heads/amar-crypto-bot-2026-cloud`.
- Main-branch agent dispatchers have no Google identity.
- Production diagnostics use dedicated observer service account `github-tradementor-observer@tradementor-production.iam.gserviceaccount.com`.
- Observer has read-only Cloud Run, Logging, Cloud Scheduler, billing viewer and Firestore database-metadata permissions only.
- Observer has no deploy, Secret Manager, wallet, order or Firestore document-data permissions.
- No permanent Google service-account key is required in GitHub.

## Billing
Direct Cloud Billing project API remains unavailable to the observer (HTTP 403 PERMISSION_DENIED).
Billing health is therefore reported separately from runtime health.
Independent Gmail Cloud Billing Watch remains the billing-suspension warning channel.

## Monitoring
Active:
- GitHub-only production diagnostics
- GitHub public uptime monitor
- Bot Health Watch
- Gmail Cloud Billing Watch

Cloud Monitoring native alerts remain optional infrastructure enhancement, not a requirement for normal development.

## Workstation
Cloud Workstation is now emergency/break-glass access only and is not required for normal development, diagnostics, deployment or rollback.

## Incident recap
- Billing suspension caused the 2026-09-19 outage.
- Last healthy Aster tick before outage: 2026-09-18 23:28 UTC.
- First billing-disabled failure: 2026-09-18 23:29 UTC.
- Billing reinstated around 2026-09-19 04:39 UTC.
- First recovered Aster tick: 2026-09-19 05:09 UTC.
- Approximate trading automation interruption: 5h40m.

## Must not change without explicit task scope
- trading strategies/order logic
- existing user settings
- wallet/exchange connections
- secrets / Secret Manager values
- account data

## Next normal task
Start directly in GitHub. Do not request a Workstation connection unless the task is specifically billing, IAM/bootstrap, sensitive secrets, or the GitHub→Google control path is broken.


## Web release history contract
- Vanaf V46 build 373 krijgt iedere echte live webapp-update een nieuw hoger buildnummer.
- Iedere live webwijziging moet dezelfde release vastleggen in `web/lib/release-history.ts`.
- `WEBAPP_VERSION` en `WEBAPP_BUILD_NUMBER` in `web/lib/app-version.ts` zijn de centrale productiebron voor versie/build.
- De deploymentworkflow blokkeert een push-release als buildnummer of release-history niet is aangepast, of als de kandidaat-build niet hoger is dan de live build.
- Pre-GitHub historie mag alleen als `reconstructed` worden opgenomen; geen verzonnen buildnummers.
- Deze regel geldt voor toekomstige agents en normale GitHub-first ontwikkeling.
