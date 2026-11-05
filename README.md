# fde-case-study

A public deployment case study and operator runbook for rolling out a
multi-tenant SaaS platform to a new enterprise customer, built entirely
from the eleven working systems in this portfolio (P1–P11). Every number
quoted here is checked by code: `claims.json` holds each figure in
machine-readable form and `verify_case_study.py` re-derives it from the
source project it came from — test counts by running pytest's collector
in the sibling repository, headline figures by finding them verbatim in
the sibling README. If a quoted number ever stops matching its source,
the verification fails loudly. This is a checked document, not
marketing copy.

## The scenario

**The customer is fictional.** "Meridian Logistics Group" is an invented
enterprise customer used to give the rollout a concrete shape; no real
company, user, or dataset appears anywhere in this programme. Meridian
has ~400 staff, an identity provider their people already sign in
through, data living in Salesforce, HubSpot, Google Workspace and
Slack, a compliance requirement that personal data be masked before it
reaches downstream tooling, and a contract priced on metered usage.
Their rollout is the thread that ties the eleven systems together:

| Need | System that covers it |
| --- | --- |
| A tenant of their own, isolated in the database | [fde-multitenant-saas](https://github.com/habib-analyst/fde-multitenant-saas) (P1) |
| Sign-in through their IdP, directory provisioning, roles | [fde-enterprise-sso](https://github.com/habib-analyst/fde-enterprise-sso) (P2) |
| Their existing data synced in, resiliently | [fde-connector-pack](https://github.com/habib-analyst/fde-connector-pack) (P3) |
| Staff asking questions over internal documents, safely | [fde-secure-rag](https://github.com/habib-analyst/fde-secure-rag) (P4) |
| Usage, adoption and SLA health visible from day one | [fde-health-dashboard](https://github.com/habib-analyst/fde-health-dashboard) (P5) |
| Events delivered to their systems, with retries | [fde-webhook-engine](https://github.com/habib-analyst/fde-webhook-engine) (P6) |
| A repeatable, reversible deployment of the stack | [fde-oneclick-deploy](https://github.com/habib-analyst/fde-oneclick-deploy) (P7) |
| Personal data masked before downstream processing | [fde-pii-redaction](https://github.com/habib-analyst/fde-pii-redaction) (P8) |
| A rehearsed answer when something breaks | [fde-incident-response](https://github.com/habib-analyst/fde-incident-response) (P9) |
| A correct first invoice for metered usage | [fde-usage-billing](https://github.com/habib-analyst/fde-usage-billing) (P10) |
| Their admins self-serving setup instead of filing tickets | [fde-onboarding](https://github.com/habib-analyst/fde-onboarding) (P11) |

Each linked repository holds that system's source and tests. This case
study claims nothing about those repositories beyond that.

## How the eleven systems compose

The platform is assembled in dependency order. The tenant platform and
identity layer come first, because everything else needs to know whose
data it is touching and who is asking. Onboarding turns that plumbing
into a journey the customer's admins can walk themselves. Connectors
bring the data in and the deploy toolkit puts the stack up; webhooks
push events back out and the RAG service lets staff query what was
ingested. Health monitoring watches all of it, the incident system is
the rehearsed response when health degrades, billing prices the usage
the platform metered, and PII redaction sits in front of every
downstream consumer of customer data.

```
tenant platform (P1) + SSO (P2)
        │
        ▼
   onboarding (P11) ──────────────► admins self-serve the setup
        │
        ▼
 connectors (P3) ──► PII redaction (P8) ──► secure RAG (P4)
        │                                        ▲
        ▼                                        │ ingested,
   one-click deploy (P7)                         │ ACL-scoped docs
        │
        ▼
 webhook engine (P6) ──► events out to customer systems
        │
        ▼
 health dashboard (P5) ──► alerts ──► incident response (P9)
        │
        ▼
 usage billing (P10) ──► metered invoice for the period
```

The full component map, data flows and trust boundaries are in
[docs/architecture.md](docs/architecture.md).

## The runbook, stage by stage

The complete numbered operator runbook, with the exact commands each
repository documents for its own demo and tests, is in
[RUNBOOK.md](RUNBOOK.md). The stages:

### Stage 0 — Pre-flight

- **fde-oneclick-deploy (P7)** validates the deployment spec before
  anything is built: required fields, sizing tier, region label, semver
  version, feature-flag allowlist. Secrets are references only
  (`vault://` / `env://`); a literal secret value in the spec is a
  validation error, pinned by tests that reject 7 literal-secret shapes.
- **This case study's harness** runs over the whole estate:
  `python3 verify_case_study.py` confirms all eleven systems still
  match the numbers this document quotes (467 tests in total).
- Preflight checks on the target (writable directory, free disk, port
  free) run inside P7's deploy flow and abort before the live release
  is touched if any of them fail.

### Stage 1 — Provisioning

- **fde-multitenant-saas (P1)** creates Meridian's tenant. Every
  tenant-owned table carries `tenant_id`, Postgres row-level security
  compares each row's tenant against the per-connection
  `app.tenant_id`, and the application connects as a non-superuser role
  without `BYPASSRLS`, so a forgotten `WHERE` clause in application
  code still cannot leak another tenant's rows. Cross-tenant reads by
  direct id answer 404, never 403, so existence does not leak either.
- **fde-oneclick-deploy (P7)** renders the stack's artifacts
  (docker-compose, `.env` template naming secret references, never
  values, nginx config, systemd unit) deterministically — the same
  spec produces byte-identical artifacts — writes them to a versioned
  release directory, flips the `current` symlink atomically, and gates
  going live on health checks, with automatic rollback on failure.

### Stage 2 — Identity

- **fde-enterprise-sso (P2)** wires Meridian's sign-in: OAuth2/OIDC
  authorization-code flow with PKCE S256 enforced, single-use codes
  with a 60-second expiry, and ID-token validation on signature,
  issuer, audience, expiry and nonce before any local session exists.
- SAML 2.0 responses are validated on the same decision points
  (signature presence and correctness, issuer, audience, validity
  window) — see *Failures and lessons* for what the signature is in
  this build.
- **SCIM 2.0 provisioning** creates, patches, deactivates and deletes
  users and groups per tenant; deactivation in SCIM refuses SSO
  sign-in immediately. The **RBAC** matrix (14 permissions, four roles)
  is resolved per tenant on every request, so the same person can be
  owner of one tenant and viewer of another.

### Stage 3 — Data

- **fde-connector-pack (P3)** syncs Meridian's Salesforce, HubSpot,
  Google Workspace and Slack data through one connector framework:
  exact payload mapping, pagination drained to completion,
  retry/backoff with error classification, checkpointed crash-resume
  and a dead-letter queue. In the measured demo the Salesforce sync
  fetches 12 contacts in 3 pages, creates 11 and dead-letters exactly
  1 invalid record — and a crash after page 1 resumes with
  0 duplicates.
- **fde-pii-redaction (P8)** sits in front of every downstream
  consumer: text and JSON payloads are scanned, validated PII (Luhn
  for cards, mod-97 for IBANs, SSA rules for SSNs) is replaced with
  consistent typed placeholders, a per-tenant token vault can reverse
  the mask for the owning tenant only, and every redaction writes a
  hash-only compliance audit record. On the fixture corpora it catches
  13 / 13 planted PII items and passes 8 / 8 clean strings unchanged.
- **fde-secure-rag (P4)** ingests Meridian's documents with
  per-document ACLs (tenant, group or named-user) and retrieves with
  filter-before-rank: the retriever is built only from chunks the
  caller may see, so a foreign document cannot influence a score even
  indirectly. A caller issuing another tenant's document word for word
  as the query receives 0 beta chunks — only their own tenant's
  permitted documents. Answers cite their chunks, citations are
  independently verified, and every ingest, query and denial is
  audit-logged.

### Stage 4 — Go-live

- **fde-webhook-engine (P6)** delivers platform events to Meridian's
  own systems: inbound webhooks are HMAC-verified with a ±300s
  timestamp tolerance and replay protection, subscriptions are
  per-tenant, and outbound delivery is signed, retried on a pinned
  backoff schedule (10.463s / 20.777s / 40.924s for the pinned
  delivery), and dead-lettered after 4 attempts with the full attempt
  history preserved. A flaky receiver in the measured run is delivered
  on attempt 3 of 4 with exactly 1 effect applied.
- **fde-onboarding (P11)** hands the remaining setup to Meridian's
  admins as a resumable, self-serve flow: workspace, invites,
  data-source connection, SSO configuration, import, first value.
  Progress survives closing and reopening the store. On the seeded
  8-tenant cohort the median time-to-first-value is 10,800s (3h) and
  p90 is 36,000s (10h).

### Stage 5 — Hypercare

- **fde-health-dashboard (P5)** computes usage and adoption metrics,
  evaluates SLA monitors with deduped, auto-resolving alerts, and
  rolls adoption, trend, error rate and latency into one weighted
  health score. In the seeded demo tenant `acme` scores 78.48, and a
  synthetic incident breaches only the affected tenant's monitors.
- **fde-incident-response (P9)** is the rehearsed response when an
  alert fires: structured logs and traces correlate across services,
  the severity matrix maps impact × urgency to SEV1–SEV4, the incident
  lifecycle is state-checked, and the post-mortem is assembled from
  the recorded facts (in the golden sample: time to acknowledge 600s,
  time to resolve 3600s, 8 timeline entries, 2 action items with
  owners), with 16 status-update templates covering every stage ×
  severity combination.
- **fde-usage-billing (P10)** closes the first billing period:
  idempotent meter ingestion (1,000 events with 100 duplicate keys
  store 900 and aggregate exactly 1,800 units), a versioned price book
  pinned at period start, Decimal-exact invoicing (worked example
  $71.00 / $7.10 / $78.10), mid-period plan-change proration (pinned
  example $23.25 / $2.33 / $25.58), and export through a test-mode
  adapter — see *Failures and lessons* for exactly what that adapter
  talks to.

## Measured results

All figures below are the verified claims in `claims.json`. Test
counts are the counts pytest collects in each source repository today;
P1's count includes its one skipped test (41 passed + 1 skipped).

| # | Project | Tests | Headline measured results |
| --- | --- | --- | --- |
| P1 | [fde-multitenant-saas](https://github.com/habib-analyst/fde-multitenant-saas) | 42 | Seeded-fixture invoices total exactly $28.00 (tenant A) and $1.50 (tenant B); analytics summary sustains ~372 requests/second in-process (correctness harness, not a load test) |
| P2 | [fde-enterprise-sso](https://github.com/habib-analyst/fde-enterprise-sso) | 60 | 60 passed: 18 OIDC tests, 14 SCIM, 11 RBAC, 10 SAML, 7 JWT; RBAC matrix covers 14 permissions across 4 roles |
| P3 | [fde-connector-pack](https://github.com/habib-analyst/fde-connector-pack) | 42 | Salesforce fixture drains 12 contacts in 3 pages (HubSpot 11, Google Workspace 10, Slack 9, each in 3 pages); crash-resume sync produces 0 duplicates; 429 retries honour delays of exactly [2.0, 2.0] seconds |
| P4 | [fde-secure-rag](https://github.com/habib-analyst/fde-secure-rag) | 40 | Word-for-word cross-tenant query returns 0 beta chunks; top refund chunk scores 0.5943 on the seeded corpus; denied document ids appear in the audit log and nowhere in responses |
| P5 | [fde-health-dashboard](https://github.com/habib-analyst/fde-health-dashboard) | 31 | Seeded demo health score 78.48 for tenant acme; hand-computed fixture scores pinned exactly at 57.38 and 66.25 |
| P6 | [fde-webhook-engine](https://github.com/habib-analyst/fde-webhook-engine) | 25 | 25/25 tests pass; pinned retry schedule 10.463s / 20.777s / 40.924s; flaky receiver delivered on attempt 3 of 4; down receiver dead-lettered after 4 attempts |
| P7 | [fde-oneclick-deploy](https://github.com/habib-analyst/fde-oneclick-deploy) | 62 | 62 tests, all passing; validation rejects 7 literal-secret shapes and accepts 4 `vault://` / `env://` reference shapes; deploy v1 → v2 → rollback returns `current` to v1 |
| P8 | [fde-pii-redaction](https://github.com/habib-analyst/fde-pii-redaction) | 74 | Recall 13 / 13 planted PII items; precision 8 / 8 clean strings unchanged; audit log verified to contain no raw PII values |
| P9 | [fde-incident-response](https://github.com/habib-analyst/fde-incident-response) | 42 | Golden SEV1 post-mortem: time to acknowledge 600s, to mitigate 1800s, to resolve 3600s; 16 status-update templates (4 stages × 4 severities) |
| P10 | [fde-usage-billing](https://github.com/habib-analyst/fde-usage-billing) | 38 | 1,000 events with 100 duplicate keys aggregate exactly 1,800 units; worked invoice $71.00 / $7.10 / $78.10; proration example $23.25 / $2.33 / $25.58 |
| P11 | [fde-onboarding](https://github.com/habib-analyst/fde-onboarding) | 11 | Seeded 8-tenant cohort: median time-to-first-value 10,800s (3h), p90 36,000s (10h); 5 of 8 tenants complete the flow |

**467 tests in total** across the eleven systems, all collected and
counted by the verification harness.

## Failures and lessons

A case study that only lists successes would not be worth checking.
These are the honest limits of the rollout, each stated in the source
repository's own scope section and carried here unchanged:

- **The Postgres RLS live run was never executed on the build VM
  (P1).** The Postgres server binaries exist on the machine but cannot
  be started by the available unprivileged user, so the row-level
  security policies were not proven against a live database in this
  build. What exists instead: the real migration
  (`migrations/001_rls.sql`, including the non-superuser app role) and
  an integration test that runs when `FDE_TEST_PG_DSN` points at a
  migrated database and skips cleanly otherwise — hence 41 passed,
  1 skipped. The isolation contract itself is fully tested on the
  SQLite backend. Lesson: a skip-clean test plus a real migration is
  an honest substitute; claiming a live Postgres verification would
  not have been.
- **SAML signatures are an HMAC stand-in for XML-DSig (P2).** Fixture
  assertions are signed with HMAC-SHA256 over a canonical rendering of
  the signed fields. Real SAML requires enveloped XML-DSig
  verification, canonicalization and certificate trust with a
  dedicated library. The module validates the same decision points —
  signature presence and correctness, issuer, audience, validity
  window — without claiming to be that library. Lesson: name the
  substitution plainly, and test every rejection path the real
  verifier would have.
- **Billing talks to a fixture server, never the real Stripe API
  (P10).** The export adapter targets a local server that mimics the
  Stripe API surface in test mode (`livemode: false`, `*_test_*` ids).
  No real API is called, no real key exists (the only key string is
  the clearly synthetic fixture key), no payment is processed and no
  card data of any kind is handled. What is proven is the metering,
  the Decimal-exact invoice math and the idempotent export behaviour.
  P1's billing likewise stops at computing the invoice.
- **Every external system in this programme is a fixture.** The
  connector pack's vendor servers mimic API shapes with invented
  datasets — there is no real OAuth flow and no live vendor endpoint
  is contacted (P3). Webhook receivers are in-process stand-ins; there
  is no real HTTP egress (P6). The deploy toolkit's sandbox directory
  stands in for a customer host — no cloud API, no SSH, no Docker
  daemon (P7). Onboarding's data-source test connection is simulated
  in-process (P11). The engineering under test in each case is the
  framework logic — mapping, resilience, isolation, delivery,
  deployment — exercised end to end without external dependencies.
- **Identity and auth are fixture-shaped throughout.** The SSO IdP is
  a local stand-in with users seeded in code (P2); the RAG service and
  the dashboards take fixture headers instead of a real identity
  provider (P4, P5). The permission predicates behind those headers
  are the real, tested controls; identity resolution is deliberately a
  thin, replaceable layer.
- **The RAG system contains no LLM (P4).** Answers are extractive
  chunk listings with verified citations over a local TF-IDF baseline.
  The security properties — filter-before-rank, citation verification,
  audit boundary — are the point of the project; generated prose would
  be a different project.
- **PII detection is pattern-based, not a compliance product (P8).**
  Names come from a small fixture dictionary plus title/context
  patterns, and free-form addresses outside the street pattern will be
  missed. It is a working reference implementation; using it does not
  by itself make a pipeline GDPR-, HIPAA- or PCI-compliant.
- **Demo numbers are demo numbers.** The health-score weights are a
  documented, deliberate choice, not a validated customer-success
  model (P5); the incident system's three "services" are one
  in-process simulation (P9); the tenant platform's ~372 requests/second
  figure is an in-process correctness harness, not a production load
  test (P1). Each figure is labelled as such where it is quoted.

## Verify it yourself

```bash
# Check every number in this document against its source project
python3 verify_case_study.py

# Run this project's own test suite (coverage, full verification,
# and negative tests proving a corrupted claim fails)
python3 -m pytest tests/ -q
```

The harness expects the eleven sibling builds next to this project
(`~/workspace/build/fde-*/`); pass `--build-root` and `--claims` to
point it elsewhere.

## Operator checklist

- [ ] `python3 verify_case_study.py` passes for all eleven projects
      before the rollout starts and after any source repo changes.
- [ ] Deployment spec validates (P7) and contains only `vault://` /
      `env://` secret references — no literal secrets, ever.
- [ ] Preflight passes (writable target, free disk, port free) before
      the live release is touched.
- [ ] Tenant created in P1; a cross-tenant probe (read another
      tenant's id) returns 404 before any customer data lands.
- [ ] Postgres migration applied as DBA and the app connected as the
      non-superuser role without `BYPASSRLS` (P1); where a live
      Postgres check is impossible, the skip-clean integration test is
      on record as skipped, not passed.
- [ ] OIDC flow completed end to end with PKCE S256; replayed and
      expired codes rejected (P2).
- [ ] SAML validation rejects unsigned, wrong-key, tampered, expired
      and wrong-audience fixtures before go-live (P2).
- [ ] SCIM provisioning round-trip done: create → patch → deactivate
      (sign-in refused) → reactivate (P2).
- [ ] RBAC spot-check: a viewer cannot write; a tenant-A session is
      refused by tenant-B routes (P2).
- [ ] Each connector sync drained to completion; dead-letter count
      reviewed and explained; a re-run creates 0 duplicates (P3).
- [ ] PII redaction in front of every downstream consumer; audit log
      spot-checked to contain hashes and counts only (P8).
- [ ] RAG ingest ACLs reviewed per document; a cross-tenant probe
      query returns 0 foreign chunks; a deny entry exists in the audit
      log for the probe (P4).
- [ ] Webhook subscriptions created before events flow; a test event
      is delivered signed; the dead-letter queue is empty or explained
      (P6).
- [ ] Onboarding flow walked by a customer admin unaided; stalls show
      up in the drop-off stats (P11).
- [ ] Health monitors evaluated once; the alert list shows only the
      new tenant's alerts; health score recorded as the hypercare
      baseline (P5).
- [ ] Incident drill run: one declared incident walked through the
      lifecycle to a rendered post-mortem (P9).
- [ ] First invoice recomputed by hand from metered usage and matched
      to the cent before it is exported (P10).
- [ ] Rollback rehearsed: deploy v2, roll back, confirm `current` is
      v1 and the previous release was untouched by the drill (P7).

## Layout

```
README.md               this case study
RUNBOOK.md              numbered operator runbook with exact commands
docs/architecture.md    component map, data flows, trust boundaries
claims.json             every quoted number, machine-readable
verify_case_study.py    the verification harness
tests/                  harness tests: coverage, full verification,
                        corrupted-claim negative tests
LAUNCH_NOTE.md          20-point pre-launch checklist
```

## License

MIT
