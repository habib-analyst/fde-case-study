# Launch note — fde-case-study (20-point pre-launch checklist)

Worked item by item on 2026-11-05. Every item PASS or N/A with a
reason; no FAIL items. This project is documentation plus a read-only
verification harness; it ships no service.

1. **Functionality complete** — PASS: README case study, RUNBOOK.md,
   docs/architecture.md, claims.json, verify_case_study.py and its
   test suite are all written and cross-linked.
2. **Test suite green** — PASS: `python3 -m pytest tests/ -q` → 5
   passed (coverage, full verification, two corrupted-claim negative
   tests, missing-sibling negative test).
3. **Verification harness green** — PASS: `python3 verify_case_study.py`
   → all eleven projects [PASS], 467 total claimed tests, exit 0.
4. **Every quoted number sourced** — PASS: each figure in the README
   metrics table exists in claims.json and was machine-checked against
   its sibling README (verbatim) and test suite (pytest
   --collect-only count) in this build session; nothing was invented.
5. **Negative path proven** — PASS: tests corrupt a headline value and
   a test count on temp copies of claims.json and assert the harness
   fails with the specific mismatch; the real claims.json and sibling
   builds are never modified by the tests.
6. **No real secrets** — PASS: the only credential-shaped strings are
   the siblings' own documented synthetic fixtures (`fixture-*`,
   `sk_test_fixture_...` in prose describing P10's scope); no realistic
   credential literal exists in the tree.
7. **No private/personal data** — PASS: the customer ("Meridian
   Logistics Group") is invented and labelled fictional in the README;
   all tenants, users and datasets referenced are the siblings'
   invented fixtures.
8. **No payment integration** — PASS: no payment code exists; the case
   study documents P10's fixture-only export and states plainly that
   no real Stripe API is ever called.
9. **Free tier only / $0 cost** — PASS: pure Python standard library
   plus pytest; no paid service, account or card anywhere.
10. **No network calls** — PASS: the harness reads local files and runs
    local pytest collectors only; grep confirms no HTTP/socket code in
    verify_case_study.py.
11. **Sibling projects untouched** — PASS: the harness and tests only
    read sibling READMEs/results and run their collectors; no sibling
    file was created, edited or deleted (collect runs may refresh the
    siblings' own `__pycache__`, which their `.gitignore` files cover).
12. **Honest limits carried, not smoothed over** — PASS: the README's
    Failures and lessons section includes the three mandated limits
    verbatim in substance — P1's Postgres RLS live run could not be
    executed on the build VM (migration + skip-clean integration test
    instead), P2's SAML signature is an HMAC stand-in for XML-DSig,
    P10 talks to a fixture Stripe-shaped server, never the real API —
    plus the fixture nature of connectors, receivers, deploy sandbox,
    IdP, headers, the no-LLM RAG and the pattern-based PII limits.
13. **No live-state claims about sibling repos** — PASS: the README
    links the eleven GitHub repos and states that each linked
    repository holds that system's source and tests, claiming nothing
    about their live state beyond that.
14. **README free of internal process language** — PASS: public copy
    describes the rollout, the systems and the verification method
    only; no staging/pipeline/chat references.
15. **Runbook commands are the siblings' own** — PASS: every command
    block in RUNBOOK.md is copied from the owning repository's README
    (demo/test/serve commands and the P6 signed-webhook snippet
    included), with the owning repo named at each step.
16. **Deterministic verification** — PASS: collect-only counts and
    verbatim string checks are deterministic; the harness was run
    twice in this session with identical results.
17. **Architecture doc matches the code estate** — PASS:
    docs/architecture.md maps only the eleven real systems, their
    documented flows and their documented trust boundaries; no
    aspirational components.
18. **License/attribution** — PASS: MIT declared in README and
    pyproject.toml; no third-party code or assets copied in.
19. **File hygiene** — PASS: project tree holds source, tests and docs
    only; `.gitignore` excludes `__pycache__` and `.pytest_cache`.
20. **Rollback** — N/A: local documentation project with no deployed
    service, no production data and no external side effects; rollback
    is deleting the directory.
