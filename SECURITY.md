# Security Policy

Burnguard is a local-first working prototype for metering LLM API usage. It is useful for demos, feedback, and trusted development environments, but it is not hardened production infrastructure.

## Supported versions

Burnguard currently supports the `v0.1.x` release line. Security fixes are handled on the default branch first and may be backported to a patch release when they affect the latest `v0.1.x` tag.

## Prototype security model

Burnguard is designed to run in a trusted local or team-controlled environment. Do not expose it directly to the public internet without adding your own production controls.

Important limitations:

- Virtual API keys are stored in SQLite as text in the current MVP.
- Usage records include virtual-key identifiers, owner/project metadata, model names, session ids, token estimates, costs, request status, routes, latency, user agents, risk flags, and optional correlation headers.
- By default, Burnguard stores prompt and response hashes plus short redacted previews. It does not store full raw prompts or responses unless `STORE_RAW_MESSAGES=true` is set.
- Redaction is best-effort and heuristic-based. Treat previews and exports as operational metadata that may still contain sensitive context.
- The dashboard supports a single optional shared admin password (`ADMIN_TOKEN`, HTTP Basic). There is no multi-user login, enterprise RBAC, or tenant isolation. With `ADMIN_TOKEN` unset, anyone who can reach the port can read keys and usage data.
- Budget checks are guardrails, not financial guarantees. Token accounting and pricing defaults must be verified before real billing decisions. Budget checks reserve estimated spend in a single immediate SQLite transaction before forwarding, so concurrent requests serialize against the budget — but reservations are based on token estimates, so totals can still drift from provider invoices.
- Streaming is supported. Streamed usage is metered from provider usage events when present, with character-based estimates as a fallback.

## Handling provider keys

- Keep real upstream provider keys only in your local `.env` or secret manager.
- Give agents Burnguard virtual keys instead of real provider keys.
- Do not commit `.env`, SQLite databases, exports, logs, or screenshots that include real keys, prompts, response content, or customer data.
- Rotate upstream provider keys if you suspect a real key was exposed to an agent, repository, log, or dashboard screenshot.

## Recommended hardening before production use

Before using Burnguard with untrusted users or sensitive workloads, add controls such as:

- hashed virtual keys at rest
- per-user authentication and authorization beyond the shared `ADMIN_TOKEN`
- TLS termination and network allowlists
- secret-manager integration for provider credentials
- stricter audit-log retention and export controls
- configurable prompt/response preview retention
- verified provider pricing configuration
- deployment-specific threat modeling and monitoring

## Reporting a vulnerability

Please report suspected vulnerabilities privately by opening a GitHub security advisory for this repository, or by contacting the maintainer through the contact path listed on the GitHub profile.

When reporting, include:

- affected commit or version
- steps to reproduce
- expected and actual behavior
- impact assessment
- any relevant logs or screenshots with secrets redacted

Please do not publish exploit details until the issue has been reviewed and a fix or mitigation is available.
