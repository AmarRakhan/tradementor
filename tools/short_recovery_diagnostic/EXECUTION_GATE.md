# Build 601 read-only rollback diagnostic — execution gate

Scope: repository `AmarRakhan/tradementor`, project `tradementor-production`, region `europe-west4`.

## Current proof
- Historical web revision: `amar-bot-v44-direct-install-v46-89ab74a0-1`.
- Historical backend revision: `tradementor-api-src-f87d6b20-124369`.
- Local probe tests: five unit cases plus four workflow contract cases, all passing on 2026-10-16.
- A successful local probe test does NOT establish current Cloud Run readiness or rollback compatibility.

## Execution limitation
`short-recovery-601-readonly.yml` is staged under `tools/short_recovery_diagnostic/` and is NOT registered as a GitHub Actions workflow. Moving it to `.github/workflows` on this diagnostic branch would not make the production observer usable: the existing Workload Identity Federation trust requires `refs/heads/amar-crypto-bot-2026-cloud`, and the staged workflow itself asserts that exact ref. Do not widen WIF, use deploy credentials, or reroute execution through a privileged identity.

## Safe future execution
Separate authorization is required before any change to the trusted branch or any workflow dispatch. If authorized later, use the existing production observer service account and an exact-source, read-only diagnostic workflow to describe ONLY the two specified revisions. Publish sanitized existence/readiness/image-present results. No traffic changes, deployment, IAM changes, Firestore writes, orders, or sensitive output.

## Limits of outcome
Even if both revisions exist, are Ready and have images, this is NOT proof of full rollback compatibility. Verify frontend/backend API/schema compatibility independently and retain build-601 rollback instructions. Treat actual rollback readiness as NO-GO until all necessary checks are complete.
