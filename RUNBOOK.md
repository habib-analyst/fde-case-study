# Operator runbook — enterprise customer rollout

Numbered steps for deploying the platform to a new enterprise customer
(the fictional "Meridian Logistics Group" scenario in
[README.md](README.md)), using the eleven FDE portfolio systems. Every
command below is the command the owning repository documents for its
own demo or tests — each stage names its repository, and the stage is
not complete until that repository's own test suite passes and the
stage's check reads as expected.

Conventions: run each block from the root of the named repository.
Fixture credentials (`fixture-*`) appear exactly as the source
repositories document them; they are synthetic values that protect
nothing.

---

## Stage 0 — Pre-flight

### 0.1 Verify the whole estate against this case study

Repository: **fde-case-study** (this project)

```bash
python3 verify_case_study.py
python3 -m pytest tests/ -q
```

Expected: all eleven projects `[PASS]`, 467 total claimed tests, exit
code 0. Do not start a rollout on a red verification — a failed line
means a quoted number no longer matches its source.

### 0.2 Validate the deployment spec

Repository: [fde-oneclick-deploy](https://github.com/habib-analyst/fde-oneclick-deploy) (P7)

```bash
python3 -m fde_deploy validate --spec examples/acme.yaml
# spec OK: acme-corp 1.0.0 (production, us-east-1, tier medium)
```

Check: every entry in the spec's `secrets` map is a `vault://` or
`env://` reference. A literal secret value is a validation error by
design; fix the spec, never the validator.

### 0.3 Run the deploy toolkit's own suite

```bash
python3 -m pytest tests/ -q   # 62 tests, all passing
```

---

## Stage 1 — Provisioning

### 1.1 Tenant platform test suite

Repository: [fde-multitenant-saas](https://github.com/habib-analyst/fde-multitenant-saas) (P1)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q
```

Expected: **41 passed, 1 skipped**. The skip is the optional Postgres
integration test — it runs only when `FDE_TEST_PG_DSN` points at a
migrated database. Record the skip as a skip; on the build VM the live
Postgres run could not be executed (server binaries cannot be started
by the unprivileged user), and the rollout record must say so.

### 1.2 Apply the Postgres migration (production path)

As a DBA, apply `migrations/001_rls.sql` from the P1 repository. It
creates the tables, indexes and row-level-security policies keyed on
`current_setting('app.tenant_id')` and documents how to create the
non-superuser `fde_app` role. The application must connect as that
role, without `BYPASSRLS`. Then point `PostgresStore` at the DSN in
place of `SQLiteStore`, set `FDE_TEST_PG_DSN`, and re-run step 1.1 —
the integration test must now run and pass, not skip.

### 1.3 Start the platform API and create the tenant

```bash
# API (SQLite backend, seeded with two fixture tenants)
PYTHONPATH=src uvicorn fde_multitenant.app:app --port 8000

curl -H "X-Tenant-Id: tenant-a" -H "X-Api-Key: fixture-key-tenant-a" \
  http://127.0.0.1:8000/analytics/summary
curl -H "X-Tenant-Id: tenant-a" -H "X-Api-Key: fixture-key-tenant-a" \
  http://127.0.0.1:8000/billing/invoice
```

Check on the seeded fixtures: tenant A analytics total exactly
`api_calls=1000, storage_gb=80, compute_seconds=1800`; tenant A's
invoice totals exactly $28.00 and tenant B's $1.50. Then probe
isolation: list, read, update, delete and reference the other tenant's
projects and events, including by direct id — every probe must return
nothing (404, never 403).

### 1.4 Deploy the stack

Repository: [fde-oneclick-deploy](https://github.com/habib-analyst/fde-oneclick-deploy) (P7)

```bash
python3 -m fde_deploy deploy --root ./sandbox --spec examples/acme.yaml
python3 -m fde_deploy status --root ./sandbox
python3 -m fde_deploy history --root ./sandbox
```

Preflight (writable dir, free disk, port free) runs before the release
is touched; a failed preflight leaves the previous release live and
records `preflight_failed`. A failed health gate rolls back
automatically and records `health_failed`. Exit codes: `0` success,
`2` spec or preflight problem, `1` deploy/rollback failure.

---

## Stage 2 — Identity

### 2.1 SSO test suite

Repository: [fde-enterprise-sso](https://github.com/habib-analyst/fde-enterprise-sso) (P2)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q     # 60 tests, all local, no network
```

Expected: **60 passed, 0 failed** (18 OIDC, 14 SCIM, 11 RBAC, 10 SAML,
7 JWT).

### 2.2 Walk the OIDC login by hand

```bash
python3 -m fde_sso.serve        # demo on http://127.0.0.1:8000
```

Start a login with `GET /auth/login?tenant_id=tenant-acme`, follow the
returned authorization URL against `/idp/authorize` (add
`&fixture_user=ada@acme.example` — the fixture IdP's stand-in for a
login form), then pass the returned `code` and `state` to
`/auth/callback`. Confirm the session is RBAC-checked. Then confirm
the failure modes: replayed code rejected, expired code rejected,
`plain` PKCE rejected, wrong verifier rejected, `state` mismatch
rejected. (Production replaces the fixture IdP with the customer's
real one; nothing in this programme integrates with a production IdP.)

### 2.3 SAML validation check

Using the fixture response builder in P2, confirm a valid fixture is
accepted and each of these is rejected before any attribute is
trusted: unsigned, empty-signature, wrong-key, tampered, expired,
wrong-audience, wrong-issuer. Note for the rollout record: in this
build the SAML signature is an HMAC-SHA256 stand-in over the signed
fields, not XML-DSig — the decision points are validated, the
signature mechanism is the documented substitution.

### 2.4 SCIM provisioning round-trip

With the tenant's SCIM bearer token (`fixture-scim-token-acme` /
`fixture-scim-token-globex` in the demo): create a user, patch it, add
and remove group membership, deactivate it (`active=false`) and
confirm SSO sign-in is then refused, reactivate and confirm sign-in
works again, delete and confirm 404. Confirm another tenant's SCIM
resources return the SCIM 404 error, not data.

### 2.5 RBAC spot-check

Confirm the pinned matrix through the API: owner has all 14
permissions; admin has all except `billing.write`; member and viewer
are read-only (member also has `data.write`). Confirm a session scoped
to tenant A is refused by tenant B's routes, and that a role change
takes effect immediately.

---

## Stage 3 — Data

### 3.1 Connector test suite and demo sync

Repository: [fde-connector-pack](https://github.com/habib-analyst/fde-connector-pack) (P3)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q
# Test suite (42 tests, fully in-process, no network, no sockets)

# Demo: Salesforce -> HubSpot-validated store sync with a page that
# fails twice, a simulated crash after page 1, and a resume
PYTHONPATH=src python3 -m fde_connector_pack.demo
```

Expected demo numbers: Salesforce 12 contacts in 3 pages (HubSpot 11,
Google Workspace 10, Slack 9 messages, each in 3 pages); clean sync
12 fetched, 11 created, exactly 1 dead-lettered (invalid email,
`permanent` / `VALIDATION_ERROR`); fault-injected sync completes with
exactly 3 retries; crash after page 1 leaves 5 records durable,
resume fetches the remaining 7 and produces 0 duplicates; a full
re-run creates 0 and absorbs 11 duplicates. Review every dead letter
with the customer before go-live — a dead letter is data that did not
arrive.

### 3.2 Put PII redaction in front of downstream consumers

Repository: [fde-pii-redaction](https://github.com/habib-analyst/fde-pii-redaction) (P8)

```bash
python3 -m pytest tests/ -q     # 74 passing
pip install fastapi pydantic uvicorn
uvicorn fde_pii_redaction.api:app --port 8000

curl -X POST localhost:8000/redact -H 'Content-Type: application/json' -d '{
  "tenant_id": "tenant-a", "doc_id": "doc-1",
  "text": "mail fixture@example.com", "mode": "mask"}'
# {"text": "mail [EMAIL_1]", "counts": {"EMAIL": 1}, "doc_hash": "…"}

curl -X POST localhost:8000/restore -H 'Content-Type: application/json' -d '{
  "tenant_id": "tenant-a", "doc_id": "doc-1",
  "tenant_key": "fixture-key-a", "text": "mail [EMAIL_1]"}'
# {"text": "mail fixture@example.com"}
```

Checks: recall corpus catches 13 / 13 planted items, clean corpus
passes 8 / 8 unchanged; a restore under a different tenant is denied;
`POST /audit/verify` reports no raw PII in the audit table. Route all
synced and ingested content through `/redact` before it reaches any
analytics job, LLM call or support tool.

### 3.3 Ingest documents into the secure RAG

Repository: [fde-secure-rag](https://github.com/habib-analyst/fde-secure-rag) (P4)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q     # 40 tests, all passing

# API with the seeded corpus (http://127.0.0.1:8000)
PYTHONPATH=src python3 -m fde_secure_rag.serve

curl -s -X POST localhost:8000/query \
  -H 'X-Tenant-Id: fixture-tenant-alpha' \
  -H 'X-User-Id: fixture-user-alice' \
  -H 'X-Groups: fixture-group-support,fixture-group-billing' \
  -H 'Content-Type: application/json' \
  -d '{"query": "full refund within 30 days annual plans", "top_k": 3}'
```

Ingest with `POST /documents` (same headers; each document carries its
tenant, group or user ACL and sensitivity label — invalid ACL metadata
is rejected and nothing is stored). Checks: the seeded query ranks
alpha's refund chunk first (score 0.5943); a cross-tenant probe issuing
the other tenant's document word for word returns 0 foreign chunks;
read the audit trail with `GET /audit` (optionally
`?event_type=deny`) and confirm the probe wrote a deny entry whose
document ids appear nowhere in the probe's response.

---

## Stage 4 — Go-live

### 4.1 Webhook engine: subscribe first, then send

Repository: [fde-webhook-engine](https://github.com/habib-analyst/fde-webhook-engine) (P6)

```bash
pip install -e ".[dev]"
python3 -m pytest tests/ -q     # 25 passed
python3 -m uvicorn fde_webhook_engine.app:app --port 8000

# First create a subscription, or the event fans out to zero deliveries:
curl -X POST localhost:8000/tenants/acme/subscriptions \
  -H 'Content-Type: application/json' \
  -d '{"event_types": ["invoice.paid"], "target": "flaky", "signing_secret": "fixture-subscription-secret"}'
```

Then send a signed webhook (fixture secret for the `billing` source):

```bash
python3 - <<'PY'
import hashlib, hmac, json, time, urllib.request

body = json.dumps({"id": "evt_1", "type": "invoice.paid",
                   "tenant": "acme", "payload": {"amount": 4200}}).encode()
sig = hmac.new(b"fixture-billing-secret", body, hashlib.sha256).hexdigest()
req = urllib.request.Request(
    "http://localhost:8000/inbound/billing", data=body, method="POST",
    headers={"X-Signature": sig, "X-Timestamp": str(int(time.time())),
             "Content-Type": "application/json"})
print(urllib.request.urlopen(req).read().decode())
PY
```

Checks: a replayed event is rejected with 409 and fans out exactly
once; a stale or future timestamp is rejected; the flaky receiver is
delivered on attempt 3 of 4 with exactly 1 effect; a down receiver is
dead-lettered after 4 attempts with all 4 attempt records intact —
inspect the dead-letter queue before declaring go-live.

### 4.2 Hand setup to the customer's admins

Repository: [fde-onboarding](https://github.com/habib-analyst/fde-onboarding) (P11)

```bash
pip install fastapi pydantic pytest httpx
python3 -m pytest tests/ -q          # 11 tests
python3 -m fde_onboarding.demo       # seed the fixture cohort, print stats
uvicorn fde_onboarding.app:app       # serve the API locally
```

Walk one admin through the flow unaided: create workspace → invite
team → connect a data source → configure SSO → import data → first
value. Confirm a half-finished journey resumes exactly where it
stopped after the store is closed and reopened. Cohort reference
numbers from the seeded fixture: median time-to-first-value 10,800s
(3h), p90 36,000s (10h), completion counts workspace 8, invite 7,
connect 6, SSO 5, import 5, value 5 out of 8 tenants.

### 4.3 Go / no-go

All stage checks green, dead-letter queues (P3 sync, P6 delivery)
empty or individually explained, isolation probes (1.3, 3.3) on
record. If any check is red, roll back with step 5.4's procedure
before opening traffic.

---

## Stage 5 — Hypercare

### 5.1 Health baseline and monitors

Repository: [fde-health-dashboard](https://github.com/habib-analyst/fde-health-dashboard) (P5)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q        # 31 tests
python3 -m fde_health.serve        # demo API on http://127.0.0.1:8000
```

The demo server seeds the synthetic dataset, pins the clock and
evaluates the default monitors once, so
`GET /alerts?tenant=initech` (header `X-Tenant-Id: initech`) already
shows the seeded incident, while tenant `acme`'s health score reads
78.48. For the real tenant: record the first health score as the
hypercare baseline, confirm a breach opens exactly one alert (dedupe
on re-evaluation), recovery auto-resolves open alerts but not
acknowledged ones, and cross-tenant alert reads/actions are refused
(403; missing header 401).

### 5.2 Incident drill

Repository: [fde-incident-response](https://github.com/habib-analyst/fde-incident-response) (P9)

```bash
python3 -m pytest tests/ -q     # 42 tests, all passing
python3 -m fde_incident_response.demo
```

The demo runs the api → worker → db pipeline, prints the trace tree
(3 spans across 3 services, durations 8s / 6s / 2s, 5 correlated log
lines), then declares a sample SEV1 incident and walks it through the
full lifecycle to a rendered post-mortem. Golden reference: time to
acknowledge 600s, to mitigate 1800s, to resolve 3600s, 8 timeline
entries, 2 action items with owners. Run the same drill with the
customer's on-call before hypercare ends, and agree which of the 16
status-update templates (4 stages × 4 severities) goes out at each
stage. The post-mortem's root-cause section is a placeholder by
design — the incident owner writes the cause.

### 5.3 First billing cycle

Repository: [fde-usage-billing](https://github.com/habib-analyst/fde-usage-billing) (P10)

```bash
pip install -r requirements.txt
python3 -m pytest tests/ -q     # Full test suite (38 tests)

# Fixture "Stripe" server (local test mode only)
PYTHONPATH=src uvicorn fde_usage_billing.fixture_stripe:app --port 8002

# Billing API (SQLite, fixture-key tenant auth: fixture-key-<tenant>)
PYTHONPATH=src uvicorn fde_usage_billing.app:app --port 8001

curl -X POST http://127.0.0.1:8001/usage-events \
  -H "X-Tenant-Id: tenant-a" -H "X-Api-Key: fixture-key-tenant-a" \
  -H "Content-Type: application/json" \
  -d '{"meter":"api_calls","units":"12000","ts":"2026-01-10T00:00:00Z","idempotency_key":"api-1"}'
curl -X POST http://127.0.0.1:8001/invoices \
  -H "X-Tenant-Id: tenant-a" -H "X-Api-Key: fixture-key-tenant-a" \
  -H "Content-Type: application/json" \
  -d '{"period_start":"2026-01-01T00:00:00Z","period_end":"2026-02-01T00:00:00Z","plan":"starter"}'
```

Checks before the first invoice leaves: ingestion is idempotent
(1,000 events with 100 duplicate keys store 900 and aggregate exactly
1,800 units); rating boundaries are exact (1,000 units bills $0, 1,001
bills $0.002; 11,000 bills exactly $20.00); the worked example totals
$71.00 / $7.10 / $78.10; a finalized invoice does not change when late
usage arrives (corrections are separate adjustment invoices); the
export is idempotent (a 2-line invoice creates 4 fixture objects;
re-export creates 0). The export target is the local fixture server in
test mode only — this system makes no calls to the real Stripe API,
processes no payments and handles no card data.

### 5.4 Rollback (any stage, any time)

Repository: [fde-oneclick-deploy](https://github.com/habib-analyst/fde-oneclick-deploy) (P7)

```bash
python3 -m fde_deploy rollback --root ./sandbox
python3 -m fde_deploy status --root ./sandbox   # current is the previous release
```

Confirm the previously live release is serving again and the rollback
is recorded in `history`. A health-gate failure during a deploy rolls
back automatically; a manual rollback is the operator's call when a
later stage's checks go red.

### 5.5 Close-out

Re-run step 0.1. File the rollout record with: per-stage check
results, the dead-letter explanations, the isolation probes, the P1
Postgres skip (or its live pass, if a DSN was available), the P2 SAML
stand-in note, the P10 fixture-export note, and the hypercare health
baseline from step 5.1.
