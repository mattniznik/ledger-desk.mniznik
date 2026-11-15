# Deploying ledger-desk

**Status: deployed 2026-11-15**, live at [ledger-desk.mniznik.com](https://ledger-desk.mniznik.com). This describes
the shape at the service level. The Terraform lives in a private repository, so no account, subscription or resource
ids appear here.

## The pieces

| Piece | Azure service | Notes |
|---|---|---|
| The page | Static Web Apps | The built `web/` bundle. Talks only to the app API, from its own hostname. |
| The app API | Container Apps, external ingress | `ledger-desk api-serve`. Scales to zero, one replica at most. CORS allows only the page's origin (`LEDGER_DESK_WEB_ORIGIN`). |
| The mock ERP | Container Apps, internal ingress | Reachable only from the API inside the same environment. Verifies every approval's signature. |
| The database | Azure Database for PostgreSQL, Flexible Server, burstable B1ms | The app's tables, the ERP schema, the LangGraph checkpoints and the audit log; migrations in `migrations/`. B1ms allows 35 user connections ("Maximum user connections", Azure's limits page, read 2026-11-14); each container keeps connection pools of 10 (`db.pool`): two in the API and one in the ERP, 30 in all at one replica each. |
| Secrets | Key Vault, one per container app | The vaults hold the secrets. The Container Apps environment refuses Key Vault references ("ExpressKeyVaultSecretsNotSupported"), so the Terraform reads each secret from its vault at apply time and gives the app its value; the values also sit in the local, private Terraform state. |

Both images come from one `Dockerfile` with two targets, `api` and `erp`; `tests/test_containers.py` checks what
must hold in any image (a pinned base, a non-root user, no secrets or local clutter in the build context).

## Settings

Read from the environment (`src/ledger_desk/settings.py`); the secret ones come from Key Vault as the Secrets row above
describes:

| Container | Setting | What it is |
|---|---|---|
| API | `LEDGER_DESK_ERP_URL` | the ERP's internal address; unset means the ERP runs in-process (local only) |
| API | `LEDGER_DESK_ERP_KEY` | the key the ERP expects on every call |
| API | `LEDGER_DESK_APPROVAL_PRIVATE_KEY` | the Ed25519 key that signs approvals, base64 |
| API | `LEDGER_DESK_WEB_ORIGIN` | the page's origin, the only one CORS allows |
| API, ERP | `LEDGER_DESK_DB_URL` | the database address with its password, from Key Vault |
| ERP | `LEDGER_DESK_ERP_KEY` | its own key |
| ERP | `LEDGER_DESK_APPROVAL_PUBLIC_KEY` | the public half: it verifies, it cannot sign |

A live model would add `LEDGER_DESK_ANTHROPIC_KEY` to the API's vault; the QuickBooks sandbox copy would add its
keys and refresh token. Neither is part of the deploy: the demo replays recorded runs and costs nothing per
visitor.

## Steps, as done on 2026-11-15

1. Build both images (`docker build --target api` and `--target erp`) and push them to GitHub's container registry as
   public packages.
2. Apply the Terraform in two passes: first everything except the two container apps (resource group, environment,
   identities and vaults, the database, the static site); then put the secrets in the vaults (`db-url`, `erp-key` and
   the approval key pair); then apply again to create the two apps.
3. The API migrates the database and seeds the demo company on its first start (`ledger-desk api-serve`); migration
   `005` lets the server's admin, which is not a superuser on a managed server, switch to the app's roles.
4. Build the page with `VITE_API_BASE` set to the API's address (the page and the API are on two hostnames; the API's
   CORS allows only the page's origin, `LEDGER_DESK_WEB_ORIGIN`), and upload `web/dist` with the Static Web Apps CLI.
5. The custom domain, last: add it to the static site, prove ownership with the TXT record Azure gives, check the
   certificate and the page with `curl --resolve` before any visitor can reach it, then add the CNAME (DNS only, not
   proxied) and set the API's allowed origin (`LEDGER_DESK_WEB_ORIGIN`) to the new address.

**Regions.** The subscription's policy allows only a few regions, and Postgres Flexible Server is refused in some of
those ("Subscriptions are restricted from provisioning in this region"), so the database and the container apps run
in one allowed region and the vaults and the static site in another.

Each step needs the owner's go; none runs from CI.
