# Architecture — how the eleven systems compose

Component map, data flows and trust boundaries for the platform
assembled in the [fde-case-study](../README.md). Every component below
is one of the eleven portfolio repositories; nothing in this diagram is
aspirational — each box is a system with its own test suite, and the
case study's harness verifies the quoted totals (467 tests) against
those suites.

## Component map

```
                         CUSTOMER SIDE (fictional "Meridian")
   staff browsers        IdP (customer's)      Salesforce / HubSpot /
        │                     │                Google Workspace / Slack
        │                     │                          │
════════╪═════════════════════╪══════════════════════════╪═══════════
        │              TRUST BOUNDARY A: identity        │ sync
        ▼                     ▼                          ▼
┌───────────────┐   ┌──────────────────┐      ┌────────────────────┐
│  onboarding   │   │ enterprise SSO   │      │  connector pack    │
│  (P11)        │──►│ (P2)             │      │  (P3)              │
│  self-serve   │   │ OIDC+PKCE, SAML  │      │  mapping, paging,  │
│  setup flow,  │   │ validation, SCIM │      │  retry, checkpoint │
│  resumable    │   │ provisioning,    │      │  dead letters      │
└───────┬───────┘   │ per-tenant RBAC  │      └─────────┬──────────┘
        │           └────────┬─────────┘                │ raw records
        │  tenant +          │ session,                 ▼
        │  membership        │ membership     ┌────────────────────┐
        ▼                    ▼                │  PII redaction     │
┌──────────────────────────────────────┐    │  (P8)              │
│        multi-tenant SaaS core (P1)   │    │  validated         │
│  tenant context per request          │    │  detectors, typed  │
│  Postgres RLS / SQLite filter        │    │  placeholders,     │
│  projects · usage events · analytics │    │  token vault,      │
└───────┬──────────────────┬───────────┘    │  hash-only audit   │
        │ metered usage    │ tenant data    └─────────┬──────────┘
        ▼                  ▼                          │ redacted text
┌───────────────┐  ┌──────────────────┐               ▼
│ usage billing │  │  secure RAG (P4) │    downstream consumers
│ (P10)         │  │  per-doc ACLs,   │    (analytics, LLM calls,
│ idempotent    │  │  filter-before-  │     support tools) never
│ ingestion,    │  │  rank, verified  │     see raw PII
│ Decimal-exact │  │  citations, audit│
│ invoices      │  └──────────────────┘
└───────┬───────┘
        │ invoice.paid etc.
        ▼
┌───────────────┐        events out        ┌────────────────────┐
│ webhook       │ ───────────────────────► │ customer systems   │
│ engine (P6)   │  signed, retried, DLQ    │ (receivers)        │
└───────────────┘                          └────────────────────┘

   CROSS-CUTTING (under everything above)

┌──────────────────┐   ┌──────────────────┐   ┌────────────────────┐
│ one-click deploy │   │ health dashboard │   │ incident response  │
│ (P7)             │   │ (P5)             │   │ (P9)               │
│ validate, render,│   │ metrics, SLA     │   │ structured logs,   │
│ preflight,       │   │ monitors, deduped│   │ traces, severity   │
│ health-gated     │   │ alerts, health   │   │ matrix, lifecycle, │
│ release, rollback│   │ score            │   │ post-mortems       │
└──────────────────┘   └──────────────────┘   └────────────────────┘
        the stack itself      watches it        answers when it breaks
```

## Composition order and why

1. **P1 + P2 first.** Every later system needs two facts per request —
   whose tenant this is, and who is asking with what role. P1 supplies
   the tenant context and the database-enforced isolation; P2 supplies
   authenticated identity, provisioning and per-tenant roles. Nothing
   else can be trusted before these two exist.
2. **P11 next.** Onboarding is the customer's own path through the
   plumbing: workspace, invites, data-source connection, SSO
   configuration, import, first value. It depends on P1 (tenant) and
   P2 (SSO step) and gives the rollout a resumable, measurable journey
   instead of a ticket queue.
3. **P3 + P7 in parallel.** Connectors move the customer's existing
   data; the deploy toolkit puts the stack up. Neither depends on the
   other, and both are rehearsed against fixtures before real data or
   real hosts are involved.
4. **P8 before anything downstream.** Synced and ingested content
   passes through PII redaction before it reaches analytics, RAG
   indexing or any other consumer, so raw personal data has exactly
   one controlled entry point.
5. **P6 + P4 at go-live.** Webhooks publish platform events outward;
   the RAG service opens the ingested corpus to staff questions. Both
   are outward-facing surfaces, so they come after isolation, identity
   and redaction are proven.
6. **P5 + P9 for hypercare.** Health metrics and SLA alerts watch the
   running platform; the incident system is the rehearsed response
   when an alert fires.
7. **P10 closes the loop.** Billing prices the usage P1 metered, and
   its `invoice.paid` event is itself a webhook P6 delivers.

## Data flows

### Sign-in and a scoped request

```
staff ──► P2 /auth/login ──► customer IdP (authorize, PKCE S256)
      ◄── code ── P2 /auth/callback: code exchanged, ID token
          validated (sig, iss, aud, exp, nonce), local session
staff ──► P1 API with session ──► TenantContext bound per request
      ──► Postgres: set_config('app.tenant_id', …) arms RLS
          (SQLite backend: repository injects the tenant filter)
      ◄── only that tenant's rows; foreign ids answer 404
```

### Data in: sync, redact, index

```
vendor APIs (fixtures in this build) ──► P3 connectors
   mapping → pagination → retry/backoff → checkpointed sync
   invalid records ──► P3 dead-letter queue (reviewed by an operator)
synced records ──► P8 /redact ──► typed placeholders downstream
   placeholder map ──► P8 token vault (per tenant+document, TTL)
   counts + doc hash only ──► P8 compliance audit log
documents ──► P4 ingest (ACL validated; invalid ACL stores nothing)
   ──► chunks with stable ids ──► query: ACL predicate first,
       retriever built from permitted chunks only (filter-before-rank)
       ──► answer with [chunk_id] citations ──► citation verifier
       ──► audit: ingest / query / deny entries
```

### Events out

```
platform event ──► P6 POST /inbound/{source}
   HMAC-SHA256 verified, ±300s window, replay cache (409 on replay)
   ──► fan-out over the tenant's active subscriptions
   ──► signed delivery attempts on the pinned backoff schedule
   ──► receiver effect applied at most once (idempotency key)
   failures ──► retry ──► dead-letter queue after 4 attempts,
   full attempt history preserved
```

### Usage to invoice

```
P1 usage events ──► P10 ingestion (UNIQUE tenant+idempotency key;
   duplicates absorbed with the original payload)
   ──► rating under the price-book version effective at period start
   ──► Decimal-exact invoice (allowance, tiers, tax, proration)
   ──► finalized invoice is immutable; corrections are adjustment
       invoices referencing the original
   ──► export via test-mode adapter ──► fixture billing server
       (never the real Stripe API; no payments, no card data)
```

### Health to incident

```
usage/adoption events ──► P5 metrics ──► SLA monitors evaluate
   breach ──► exactly one deduped alert ──► ack / auto-resolve rules
   health score (adoption, trend, error, latency) per tenant
alert fires ──► P9 incident created (severity = impact × urgency)
   structured logs + trace context correlate the failing path
   lifecycle: declared → acknowledged → mitigated → resolved
   ──► post-mortem assembled from recorded facts + comms updates
       from the 16 stage × severity templates
```

## Trust boundaries

**Boundary A — identity (P2).** Nothing crosses from "anonymous" to
"a member of a tenant" except through the SSO layer: OIDC code + PKCE
exchange with full ID-token validation, SAML response validation, and
SCIM as the provisioning source of truth — a user deactivated in SCIM
cannot sign in. Roles are per-tenant memberships resolved on every
request; holding a role in tenant A grants nothing in tenant B.
*Honest limit:* the IdP in this build is a local fixture, SAML
signatures are an HMAC stand-in for XML-DSig, and JWT signing uses
shared fixture secrets — the validation decision points are real and
tested, the production IdP integration is not part of this build.

**Boundary B — tenant isolation (P1).** The database is the boundary,
not application discipline: RLS policies compare each row's
`tenant_id` with the per-connection `app.tenant_id`, and the app role
has no `BYPASSRLS`. A foreign row is indistinguishable from a
nonexistent one (404, never 403). The same contract is enforced on the
SQLite backend by the repository's injected filter, which is how the
suite tests it everywhere. *Honest limit:* the live Postgres run could
not be executed on the build VM; coverage is the real migration plus a
skip-clean integration test (see the case study's failures section).

**Boundary C — the PII vault (P8).** Raw personal data exists in
exactly two places: the source payload, transiently, and the token
vault, keyed per (tenant, document) with TTL expiry. Everything
downstream of `/redact` sees placeholders. Restoration requires the
owning tenant's key — another tenant's valid key is denied, and `hash`
/ `partial` modes store nothing and cannot be reversed at all. The
compliance audit log is on the safe side of the boundary by
construction: tenant, document id, detector counts, timestamp and a
salted document hash — and a `verify_no_pii` scan proves no planted
value appears in it.

**Boundary D — document access (P4).** Retrieval never crosses the
ACL: the permitted set is resolved first and the retriever (including
its corpus statistics) is built from that set alone, so an unseen
document cannot influence a score. Citations are re-verified against
the caller's retrieved set before an answer is returned. Denied
document ids are written to the audit log only — the audit log is
inside the boundary, responses are outside it.

**Boundary E — signed events (P6).** Inbound webhooks cross only with
a valid HMAC over the raw body inside a ±300s window, once (replay
cache). Outbound deliveries are signed per subscription, and receivers
dedupe by idempotency key so retries cannot double-apply an effect.
All secrets here are fixture values in this build.

**Boundary F — money (P10, with P1).** Invoice math is Decimal-exact
and deterministic; ingestion dedupe is a database UNIQUE constraint,
not a read-then-write check; finalized invoices are immutable. The
boundary stops before real money: the export adapter talks to a local
fixture server shaped like the Stripe test-mode API. No real API, no
real keys, no payments, no card data — in this build, by design.

**Cross-cutting.** Deployment (P7) treats secrets as references only
(`vault://` / `env://`) — a literal secret in a spec cannot cross into
a rendered artifact because validation rejects it. Audit logs exist at
every boundary: P4 (ingest/query/deny), P8 (hash-only redaction log),
P6 (delivery attempts and DLQ), P7 (deploy history), P9 (incident
timeline). If it crossed a boundary, there is a record of it.
