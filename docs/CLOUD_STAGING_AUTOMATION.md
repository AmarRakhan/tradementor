# TradeMentor cloud staging automation

The staging backend is deployed from GitHub Actions. A laptop is not part of
the runtime or deployment path.

## Fixed isolation boundary

- Data and Cloud Run project: `tradementor-amar-20260813`
- Firebase Authentication issuer: `tradementor-production`
- Cloud Run service: `tradementor-staging-api`
- Region: `europe-west4`
- Live-order flags: always `false` in the staging workflow
- Schedulers: not created or enabled by this workflow

The default Firebase app and Firestore client remain attached to the staging
project. A separately named Firebase app validates existing identity tokens.
This does not give staging a Firestore connection to production.

## One-time cloud setup

Create a Google Workload Identity Federation provider that trusts only this
repository and the `amar-crypto-bot-2026-cloud` branch. Grant its deployment
service account only the staging roles needed for Artifact Registry and this
Cloud Run service. Use a separate staging runtime service account. Neither
service account receives any IAM role in `tradementor-production`; the named
Firebase app uses only the issuer project ID to validate existing signed ID
tokens. Do not create or download a JSON service account key.

Add these non-secret GitHub environment variables to the `staging`
environment:

- `GCP_WORKLOAD_IDENTITY_PROVIDER`
- `GCP_DEPLOY_SERVICE_ACCOUNT`
- `GCP_RUNTIME_SERVICE_ACCOUNT`

Require approval on the GitHub `staging` environment until the pipeline has
completed its first successful deployment. Thereafter, a push that changes
`cloud_api/**` runs all backend tests and deploys only the staging service.

## Runtime verification

The workflow checks `/health` after deployment and fails unless:

- the environment is `staging`;
- order execution is disabled;
- the data project is the isolated migration project;
- the identity project is the established production Firebase Auth project.

Cloud Run remains publicly reachable because the browser must reach the API,
but every personal route continues to require a valid Firebase bearer token.
