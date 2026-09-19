# AGENT HANDOFF — Amar Crypto Bot 2026 Cloud

Last updated: 2026-09-19
Status: GITHUB-FIRST DAILY CONTROL PLANE PROVEN END-TO-END

## Required operating model
Normal development is GitHub-first:

ChatGPT / agent → GitHub → tests/build → GitHub Actions → Workload Identity Federation → Google Cloud → candidate checks → production verification.

For normal UI work, backend debugging, fixes, deployment, diagnostics and rollback, the user must NOT need to connect a Cloud Workstation.

Direct Google Cloud / Workstation access is break-glass only for:
- billing/payment account incidents;
- IAM/bootstrap changes;
- highly sensitive secrets;
- failure of the GitHub → Google control path itself.

A new chat must read this file and `CURRENT_TASK.json` before modifying code or assuming production state.

## Production now
- GCP project: `tradementor-production`
- Region: `europe-west4`
- Backend service: `tradementor-api`
- Live revision: `tradementor-api-src-ef3a5ecd-341284`
- Live source commit: `ef3a5ecdad21fc44dd2e4945c12c16d6c45a8853`
- Health: `ready`
- Firestore metadata: reachable
- Aster scheduler: ENABLED
- Latest verified Aster automation tick: HTTP 200
- Backend 5xx in final 30-minute verification window: 0
- Aster public market API: reachable

Final GitHub-only post-deploy proof: issue #155.
Successful no-op deployment proof: issue #154.

## What is proven
### UI / web
`.github/workflows/deploy-shared-v44-testapp.yml` already provides the normal V46 web path:
- push under `web/**`
- tests/build
- WIF authentication
- no-traffic candidate on `amar-bot-v44-direct-install`
- candidate verification
- promotion
- post-promotion verification
- rollback on failure

Therefore normal requests such as adding tabs, buttons, layout/styling, mobile fixes, settings fields or charts do not require Workstation access.

### Backend deployment
The production backend path now:
- accepts an explicit 40-character `source_commit`;
- requires that commit to belong to the trusted `amar-crypto-bot-2026-cloud` history;
- tests the exact requested source;
- never implicitly ships the current cloud-branch head;
- uses GitHub Actions + keyless WIF;
- captures the existing production rollback point;
- reuses the current live image for a safe no-op proof when source commit equals the live source;
- otherwise builds an exact-source image;
- deploys a no-traffic candidate;
- verifies exact source/image identity and `/health`;
- promotes only after candidate verification;
- verifies production after promotion;
- automatically restores the previous revision after failed post-promotion verification;
- reports success/failure and rollback context back to the agent request issue.

Owner-only GitHub issue dispatcher:
`[AGENT-CONTROL] deploy backend`

### Production diagnostics
Owner-only diagnostic issue:
`[AGENT-CONTROL] diagnose production`

The main branch acts only as a GitHub dispatcher. Google authentication remains restricted to the trusted `amar-crypto-bot-2026-cloud` branch.

The diagnostic worker can read, without Workstation:
- Cloud Run health/revision/source commit;
- Firestore database metadata only;
- Cloud Scheduler state;
- recent Aster automation tick;
- backend 5xx count;
- Aster public connectivity.

Diagnostic identity:
`github-tradementor-observer@tradementor-production.iam.gserviceaccount.com`

It has least-privilege read-only access only:
- Cloud Run Viewer
- Logging Viewer
- Cloud Scheduler Viewer
- Billing Viewer on billing account
- custom Firestore metadata role containing only `datastore.databases.get` and `datastore.databases.getMetadata`

It has no deploy, Secret Manager, exchange-order, wallet-key or Firestore-document permissions.

## WIF trust boundary
The WIF provider remains restricted to:
- repository: `AmarRakhan/tradementor`
- ref: `refs/heads/amar-crypto-bot-2026-cloud`

Do not broaden this merely for convenience.

## Rollback
Current retained rollback revision:
`tradementor-api-dca-e1f8132f-1`

The final proof promoted a new revision using the existing live image and the same live source commit. No later trading commit was shipped.

## Billing incident — confirmed
2026-09-19 incident:
- billing account suspension caused Cloud Run requests and Aster automation ticks to fail;
- last successful tick before interruption: 2026-09-18 23:28 UTC;
- first billing-disabled failure: 2026-09-18 23:29 UTC;
- billing reinstated around 2026-09-19 04:39 UTC;
- first fully successful Aster tick after recovery: 2026-09-19 05:09 UTC;
- full automation interruption: about 340 minutes;
- confirmed cause: billing account suspension after a failed payment.

Do not store payment instrument details in repository files.

## Billing monitoring
Direct Billing API reads from the observer currently return HTTP 403 / PERMISSION_DENIED. This does NOT affect runtime diagnosis or deployment.

Billing monitoring remains separated from runtime health:
- external Cloud Billing / Google Payments Gmail watch is active;
- monthly Google Cloud budget alert exists;
- runtime diagnostic explicitly reports billing as UNVERIFIED instead of falsely marking runtime unhealthy.

Do not weaken IAM merely to make the diagnostic show billing as green. Billing/payment remains a break-glass/account-control concern.

## Independent monitoring
- GitHub public uptime monitor: scheduled every 15 minutes.
- Hourly Cloud Billing Gmail watch: active.
- Hourly Bot Health Watch: active.
- GitHub-only production diagnostic path: proven.

## Safety boundaries
Do not change unless the task explicitly requires it:
- trading strategies/order logic;
- existing user settings;
- wallet/exchange connections;
- secrets / Secret Manager values;
- account data.

Never deploy the cloud-branch head merely because it is newer. Always identify and deploy the intended exact source commit.

## Incident-proof deployment history
- Issue #148: first GitHub-only proof safely failed before candidate creation.
- Issue #151: second proof safely failed at `capture-current-health`; root cause was same-step GitHub Actions environment handling.
- Fix: read `SERVICE_URL` locally in the same shell step instead of relying on `$GITHUB_ENV` before the next step.
- Issue #154: final no-op deployment proof SUCCESS.
- Issue #155: post-deploy read-only runtime verification HEALTHY.

## Current conclusion
The core migration goal is complete:
normal development, UI changes, backend fixes, tests, production diagnostics, deployment and rollback control can now operate from GitHub without requiring the user to connect Google Cloud for each task.

Cloud Workstation remains emergency/break-glass only.
