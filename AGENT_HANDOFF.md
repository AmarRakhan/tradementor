# AGENT HANDOFF — Amar Crypto Bot 2026 Cloud

Last updated: 2026-09-19
Status: GITHUB-FIRST CONTROL PLANE PROVEN

## Daily operating model — REQUIRED
Normal development is now:

User → ChatGPT/agent → GitHub → tests/build → GitHub Actions → Workload Identity Federation → Google Cloud → candidate → verification → production.

For normal development, UI work, backend fixes, diagnostics, deployment and rollback, the user should NOT be asked to connect the Cloud Workstation first.

Direct Google Cloud / Workstation access is break-glass only for billing/payment, IAM/bootstrap, highly sensitive secrets, or failure of the GitHub→Google control path itself.

A new chat must read AGENT_HANDOFF.md and CURRENT_TASK.json before changing code or assuming production state.

## Production
- Project: `tradementor-production`
- Region: `europe-west4`
- Backend service: `tradementor-api`
- Current live revision: `tradementor-api-src-ef3a5ecd-341284`
- Current live source commit: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`
- Previous rollback revision retained: `tradementor-api-dca-e1f8132f-1`
- Runtime health after final proof: HEALTHY
- Firestore metadata: reachable
- Aster scheduler: ENABLED
- Recent Aster automation tick: HTTP 200
- Backend 5xx in final 30-minute proof window: 0
- Aster public market API: reachable

## GitHub-first proof completed
Issue #154 proved the complete backend deployment path without Workstation:
1. Owner-only GitHub control issue.
2. Exact requested source SHA validated against trusted cloud-branch history.
3. Full backend tests run on that exact SHA.
4. Existing live image reused because requested source matched live source.
5. No-traffic Cloud Run candidate created.
6. Candidate health and exact source identity verified.
7. Candidate promoted to 100% traffic.
8. Production health verified.
9. Previous revision retained as rollback point.
10. Final result posted back to GitHub automatically.

Issue #155 proved post-deployment read-only production diagnostics through GitHub/WIF without Workstation.

## Web/UI deployment
The canonical V46 web app already deploys GitHub-first:
- Changes under `web/**` trigger the V46 workflow.
- Tests/build run in GitHub Actions.
- WIF authenticates keylessly to Google Cloud.
- A no-traffic candidate is created and verified.
- Traffic is promoted only after verification.
- Automatic rollback exists after failed post-promotion verification.

Therefore normal requests such as new tabs, buttons, styling, mobile fixes, settings fields and charts must not require Cloud Workstation access.

## Security boundaries
- WIF provider remains restricted to repository `AmarRakhan/tradementor` and ref `refs/heads/amar-crypto-bot-2026-cloud`.
- No permanent Google service-account key is required in GitHub.
- Main-branch agent dispatchers have no Google identity.
- Production diagnostics use dedicated observer service account `github-tradementor-observer@tradementor-production.iam.gserviceaccount.com`.
- Observer roles are read-only: Cloud Run viewer, Logging viewer, Cloud Scheduler viewer, billing viewer, plus Firestore database metadata-only custom permissions.
- Observer has no deploy, Secret Manager, order, wallet, or Firestore document-data permissions.

## Billing incident
Confirmed incident:
- Billing account was suspended after a failed payment.
- Last successful Aster tick before outage: 2026-09-18 23:28 UTC.
- First billing-disabled failure: 2026-09-18 23:29 UTC.
- Billing reinstated around 2026-09-19 04:39 UTC.
- First successful Aster tick after recovery: 2026-09-19 05:09 UTC.
- Full trading automation interruption: approximately 5h40m.

Direct Cloud Billing project API remains unavailable to the observer (HTTP 403 PERMISSION_DENIED). This does NOT make runtime health unknown; billing control is reported separately as UNVERIFIED. The independent Gmail Cloud Billing Watch remains the billing-suspension warning channel.

## Monitoring
Active layers:
- GitHub-only read-only production diagnosis via control issues.
- Independent public GitHub uptime monitor.
- Hourly Bot Health Watch.
- Hourly Gmail Cloud Billing Watch.

Cloud Monitoring native alert policies can still be added later as an infrastructure enhancement, but they are not required for normal agent development/deployment.

## Workstation
Cloud Workstation is now emergency/break-glass access only. It is no longer required for normal UI/backend development, diagnostics or deployments.

## Must not change without explicit task scope
- Trading strategies/order logic.
- Existing user settings.
- Wallet/exchange connections.
- Secrets/Secret Manager values.
- Account data.

## Historical rollback point
- Pre-migration backend revision: `tradementor-api-dca-e1f8132f-1`
- Source commit: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`

## Final proof references
- GitHub-only safe no-op backend deployment: issue #154 — SUCCESS.
- Post-deployment production diagnosis: issue #155 — HEALTHY.
- Final live revision: `tradementor-api-src-ef3a5ecd-341284`.

## Next normal task
For the next requested bot change, start directly in GitHub. Do not ask the user to connect Google Cloud/Workstation unless the task is specifically billing, IAM/bootstrap, sensitive secrets, or the GitHub→Google control path itself is broken.
