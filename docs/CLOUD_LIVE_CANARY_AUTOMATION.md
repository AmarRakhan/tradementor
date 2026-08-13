# Amar Crypto Bot 2026 cloud live-canary

The live-canary service is a separate Cloud Run service in the isolated
`tradementor-amar-20260813` project. It exists only to prove one explicitly
confirmed Strategy 3 Aster open/fill/close/flat round trip.

## Fixed boundary

- Service: `tradementor-live-canary-api`
- Environment: `live-canary`
- Firebase identity issuer: `tradementor-production`
- Data and Secret Manager project: `tradementor-amar-20260813`
- Strategy 3 canary endpoint: enabled
- Continuous Aster execution: disabled
- Strategy 2 live execution: disabled
- Strategy 3 live runtime: disabled
- MEXC live execution and automation: disabled
- Schedulers: absent

Deployment cannot itself place an order. The canary still requires a recent
account-specific readiness report, an authenticated and verified user, an
existing encrypted Aster secret, Hedge Mode, safe margin state, no open orders,
a flat eligible contract, and a separate request body with `confirm: true`.
Unknown or incomplete exchange state blocks retry.
