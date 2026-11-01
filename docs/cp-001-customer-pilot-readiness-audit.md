# CP-001 — Customer Pilot Readiness Audit

Status: AUDIT ONLY. No product code changed, no tests modified.
Suite: 660 tests OK, 1 pre-existing socket skip. No provider calls made.

## 1. Executive assessment

FDE Command Center is a well-instrumented synthetic demonstration with
genuinely good local boundaries (loopback bind, Origin/Host gates,
server-side keys, sanitized diagnostics, fail-closed persistence).
It is **not pilot-ready for real customer data**: there is no
authentication, no tenant isolation, no encryption, no upload pipeline,
no logging/monitoring, and no operational controls. Verdict: **NO-GO
for real customer data**. A synthetic-data, operator-assisted pilot
(on the operator's machine, customer observing) needs no code changes
and is the only deployment model supportable today.

## 2. Verified architecture inventory

- Entry: `ThreadingHTTPServer` on `127.0.0.1` (`backend/server.py`);
  static files limited to `frontend/`; 12 pre-existing POST routes;
  no GET/POST for snapshot/pointer/receipt/link admin.
- Trust: browser ↔ loopback HTTP (plaintext); backend ↔ filesystem
  (0600/0700); backend → Meta API (Bearer [REDACTED] env key, 30s timeout,
  zero retries, output cap) only on explicit user action.
- Storage: `mission-snapshots/`, `evaluator-private/` (receipts,
  links, adjudications), fixtures; no encryption, no backup, no
  deletion API, no retention policy.
- Op posture: `log_message` suppressed; stdout boot lines only; no
  health endpoint, no graceful shutdown beyond KeyboardInterrupt, no
  rate limiting, unbounded threads, no security headers
  (only Content-Type/Length).

## 3. Threat model (single-org pilot → multi-org service)

Untrusted inputs today: browser requests (same-user only), fixture
files, provider responses. New attacker-reachable surfaces the moment
it leaves loopback: all 12 POST routes (no auth), static serving,
mission store/pointer files, receipt registry. Sensitive content at
stake: investigation records, human rationales, concealed outcomes,
receipts, API key in process env. Multi-org adds cross-tenant
read/write, which the architecture cannot express (no tenant id
anywhere) — that gap is structural, not incremental.

## 4. Gap analysis (implemented / partial / missing / unverified)

- B Identity/tenancy: everything missing — no authN/Z, sessions,
  RBAC, tenant ids, object-level checks, audit logging, revocation.
  Partial: loopback + Origin/Host gates (single-user only).
- C Ingestion: entirely missing — no upload route, validation,
  quarantine, parser isolation, prompt-injection defenses for
  customer content. (Nothing to exploit yet; everything to build.)
- D Data protection: only file permissions (partial). Missing: TLS,
  at-rest encryption, key management, redaction, retention/deletion,
  backups, export, disclosure audit, consent handling.
- E AI safety: implemented — explicit-action calls, evidence-grounded
  prompts, validated structured output, sanitized errors, no auto
  retry; human approval recorded, never executes. Missing (previously
  accepted gate): idempotency/durable external-call ledger against
  manual-retry double billing. Unverified: provider data-retention
  behavior (vendor policy, not code).
- F Persistence/provenance: implemented and tested (CAS, digests,
  quarantine, fail-closed recovery). Missing: tamper-evidence against
  privileged local writers, retention/deletion, cross-org isolation.
  Integrity hashes explicitly not truth-proofs (preserved).
- G Reliability: implemented — crash-consistent commits, abort-on-
  corruption startup. Missing: health checks, structured logs,
  metrics, concurrency/rate limits, backups/RPO/RTO, updates,
  incident runbooks, rollback (N/A: no deployment).

## 5. Pilot scope (H)

Smallest testable pilot: one organization, one pre-defined synthetic
or operator-anonymized incident, ≤3 authorized users (1 operator, 1–2
observers), read-only customer evidence review, success = correct
evidence-grounded diagnosis with uncertainty preserved, stop = any
unsupported conclusion, data-boundary breach, or bypass of human
approval. Real customer data enters only after identity, encryption,
and ingestion controls exist; until then use synthetic or
irreversibly anonymized fixtures prepared by the operator.

## 6. Risk register (abridged; full table §6.1–§6.14 in text)

- R-01 No authentication (server.py: no auth code) — critical, blocks
  customer data AND any networked synthetic pilot. Fix: session authN/Z.
- R-02 No tenant isolation (no tenant id in any schema) — critical,
  blocks customer data; structural for multi-org.
- R-03 Plaintext HTTP, no TLS (only Content-Type/Length headers) —
  critical off-loopback. Fix: TLS termination + security headers.
- R-04 No upload pipeline (no route) — high; blocks customer data.
  Design per OWASP File Upload Cheat Sheet when built.
- R-05 Secrets in process env only, no rotation/audit — medium.
- R-06 Manual-retry double billing (no idempotency ledger) — medium;
  accepted gate before live-provider use.
- R-07 Prompt injection via future customer content — high; no
  ingestion defenses exist yet.
- R-08 No audit/security logging (log_message suppressed) — high for
  pilot accountability. Fix: append-only audit log.
- R-09 No retention/deletion/backup (no APIs) — high for privacy.
- R-10 Unbounded concurrency, no rate limits — medium.
- R-11 No health checks / readiness gates — medium.
- R-12 Receipt/persistence files readable by any local user — low
  (single-user model; document, don't oversell perms).
- R-13 Physical restart/Safari acceptance still owner-pending — low
  for safety, required for demo confidence.
- R-14 Provider data-handling opacity — medium; needs vendor review
  before customer content is sent.

## 7. Pilot model comparison

1. Local operator-assisted (customer observes operator's machine):
   near-zero security burden, validates value now. RANKED FIRST.
2. Single-org hosted: needs R-01, R-03, R-08, R-09, R-10, R-11 —
   moderate build, real ops burden.
3. Multi-tenant SaaS: needs all above plus tenancy redesign —
   disproportionate for a first pilot; not recommended.

## 8. References (K)

OWASP ASVS 5.0 used as a checklist reference (2.1 credential handling
→ R-05; 3.x session/auth → R-01; 4.x access control → R-01/R-02;
7.x logging → R-08; 8.x data protection → R-03/R-09; 10.x malicious
input → R-04/R-07; 14.x config → R-03/R-10). File Upload Cheat Sheet
reserved for the future ingestion design. No certification or
compliance is claimed.

## 9. CP-002 proposed scope

Operator-assisted synthetic pilot support only: append-only audit log
(R-08), backup/restore procedure for mission stores (R-09 partial),
documented anonymization checklist for customer-derived fixtures,
plus the owner-executed Safari/restart acceptance (R-13). No auth,
no hosting, no ingestion — those belong to a later hosted-pilot
milestone with its own threat sign-off.

## 10. Decisions needed

Accept NO-GO for customer data; choose pilot model (recommend #1);
approve CP-002 scope; assign vendor-privacy review (R-14); schedule
physical acceptance.

## 11. Stop criteria

Any customer-data request before R-01–R-04 close; any multi-org
proposal before tenancy redesign; any claim of compliance from this
document.
