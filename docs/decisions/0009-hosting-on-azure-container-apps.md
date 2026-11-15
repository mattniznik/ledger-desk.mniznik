# 0009. Hosting on Azure: Container Apps, PostgreSQL Flexible Server, Static Web Apps

**Status:** accepted, deployed 2026-11-15 (see Evidence for what the deploy changed)

## Decision

The API and the mock ERP as two Azure Container Apps (the ERP reachable only inside the environment), Azure Database
for PostgreSQL Flexible Server on the burstable B1ms tier, one Key Vault per app holding its secrets, and the page on
Static Web Apps ([docs/DEPLOY.md](../DEPLOY.md)). The Terraform is kept privately.

## Sources

- Azure Container Apps pricing (read 2026-11-14): "The first 180,000 vCPU-seconds, 360,000 GiB-seconds, and 2
  million requests per subscription per month are free." "No usage charges apply when an application is scaled to
  zero."
- Azure free services (read 2026-11-14): "Get free monthly amounts of these services for 12 months from the date
  you create your Azure account." The page lists the per-service amounts in the browser only, so the database
  tier's free amount was not confirmed there.

## Evidence (this repository)

- `tests/test_containers.py`: both images from one Dockerfile, a pinned base, a non-root user, no secrets in the
  build context, servers that listen beyond localhost.
- `tests/test_deploy_settings.py`: the API calls the ERP over HTTP with its key and refuses to start half
  configured; `tests/test_cors.py`: only the page's origin.
- Cost, derived and not measured: the two container apps, one replica at most and scaling to zero, inside the
  free grant for a demo's traffic. The database's cost is not confirmed (see Sources).

**What the first deploy found (2026-11-15), each fixed before it went live:**
- The environment refused Key Vault references for app secrets (`ExpressKeyVaultSecretsNotSupported`; express
  environments support only secrets added to the app, learn.microsoft.com/azure/container-apps/express-overview, read
  2026-11-15), so secrets are read from the vaults at apply time and given to the apps as values.
- On Postgres 17 a non-superuser admin cannot `SET ROLE` to roles it created (measured in a fresh Postgres 17:
  "permission denied to set role"); migration 005 grants it.
- The API committed a request after its response, so an approval sent at once could find "no such run" (3 of 12 in
  the API image on Linux); every route now commits first (FastAPI dependency scope "function").
- Smoke test on Azure: 12 of 12 sequences read, rendered and approved a bill through the separate ERP; the page read
  all 13 bills with no page errors at 1280 and 390 px (n=1 each).

## Rejected

- **One container running everything.** The ERP verifying approvals is the point; in the same process it would
  share the API's keys.
- **Serverless functions.** The LangGraph checkpointer and the database connection suit a long-lived process.

## Trade-off

Scaling to zero means a cold start on the first visit after a quiet spell (not measured).

## What would change it

The owner's hosting decision; another cloud with a container service, a managed Postgres and a secret store would
take the same shape.
