# Changelog

All notable changes to Burnguard are documented here.

## v0.1.0 - 2026-06-10

Burnguard's first public MVP release focuses on giving local and team-controlled LLM workflows a small OpenAI/Anthropic-compatible gateway for usage visibility, guardrails, and demos.

### Added

- OpenAI-compatible `POST /v1/chat/completions` and `POST /v1/responses` routes, plus Anthropic-compatible `POST /v1/messages` routing.
- Server-sent event streaming support for all three API routes in mock and proxy mode, with streamed usage metered from provider usage events when available and local estimates as a fallback.
- Virtual API keys with owner/project metadata, allowed models, provider routing, daily/monthly/max-request budgets, optional per-key requests-per-minute limits, and dashboard disable/enable controls.
- Atomic estimated-spend reservations in SQLite before proxying requests so concurrent agent bursts serialize against budget checks.
- Local FastAPI/Jinja dashboard for keys, sessions, session details, request history, exports, reports, metrics, and health checks.
- Demo seeding command with representative keys, normal usage, a runaway agent session, warning flags, and a blocked request.
- Mock mode by default, proxy mode for OpenAI-compatible and Anthropic Messages providers, and upstream error passthrough in proxy mode.
- Configurable model pricing through `MODEL_PRICING_FILE`, refreshed default pricing entries, and warning flags for unknown model pricing.
- Optional shared `ADMIN_TOKEN` HTTP Basic protection for the dashboard and exports.
- Privacy defaults that store hashes and redacted previews instead of full prompts/responses unless `STORE_RAW_MESSAGES=true` is set.
- Integration documentation for routing coding agents and OpenAI-compatible clients through Burnguard without disabling streaming.

### Security notes

- This release is still a local-first prototype, not hardened public internet infrastructure.
- Virtual API keys are stored as plaintext in SQLite in v0.1.0.
- `ADMIN_TOKEN` is a single shared dashboard/export password, not a multi-user authorization system.
- Budget checks are guardrails based on token estimates and provider usage events; they are not provider-billing guarantees.

See [SECURITY.md](SECURITY.md) for the supported release line, key-handling guidance, and recommended production hardening work.
