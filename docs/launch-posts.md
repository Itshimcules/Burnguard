# Burnguard launch post drafts

These drafts are written for a soft launch after the `v0.1.0` tag is published. Replace bracketed placeholders before posting.

## r/LocalLLaMA

**Title:** I built Burnguard: a tiny local gateway that meters coding-agent LLM usage before it becomes a surprise bill

I built Burnguard after running into a practical problem with coding agents: shared provider keys make it hard to answer "which key, project, model, or session caused this spend?" when an agent loops or sends huge contexts.

Burnguard is a small open-source FastAPI + SQLite gateway that sits between OpenAI-compatible/Anthropic-compatible clients and the upstream provider. It issues local virtual keys, enforces simple budgets, records usage by key/project/session, and shows risky patterns in a plain local dashboard.

What is in the first MVP:

- OpenAI-compatible Chat Completions and Responses routes
- Anthropic Messages route
- streaming/SSE support in mock and proxy mode
- per-key daily/monthly/max-request budgets
- atomic budget reservations before proxying, so parallel agent bursts cannot all slip past the budget check
- optional per-key RPM limits
- dashboard kill switch for virtual keys
- redacted previews by default instead of storing full prompts/responses
- mock mode, so the demo works without spending real API money

It is intentionally local-first and not production-hardened yet. Plaintext virtual keys at rest are still on the hardening list, and the dashboard auth is a single optional shared admin token.

The demo story is: seed local data, open the dashboard, see a runaway coding-agent session, disable its virtual key, and the agent stops spending.

Repo: [link]
Release: [link]
Demo GIF: [link]

I would especially appreciate feedback from people routing local tools, LiteLLM, or coding agents through OpenAI-compatible endpoints. Which client integrations should I test next?

## r/selfhosted

**Title:** Burnguard v0.1.0: self-hosted LLM usage metering and budget guardrails for shared API keys

I released the first MVP of Burnguard, a small self-hosted gateway for teams using shared LLM provider accounts or coding agents.

It runs locally with FastAPI, SQLite, and a simple Jinja dashboard. Put it in front of an OpenAI-compatible or Anthropic Messages endpoint, give agents Burnguard virtual keys instead of real provider keys, and it records usage by key, owner, project, model, session, route, and risk flags.

Why I built it:

- provider dashboards often show a bill but not the local project/session that caused it
- coding agents can loop or attach huge context repeatedly
- teams want a quick brake before building a full internal platform

Features in v0.1.0:

- mock mode by default for no-cost demos
- OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages routes
- streaming support
- per-key budgets and request-per-minute limits
- dashboard kill switch for a virtual key
- optional shared admin token for dashboard/export access
- CSV/JSON-style operational data exports
- `/healthz` for basic deployment checks

Security caveat: this is a local-first prototype. Do not expose it directly to the public internet without adding your own production controls. Virtual keys are plaintext in SQLite in this MVP.

Repo: [link]
Release notes: [link]
Security policy: [link]

I would love feedback on the self-hosting path: Docker defaults, reverse-proxy examples, and what hardening should come before a v0.2.0.

## r/ChatGPTCoding

**Title:** I built a local spending brake for coding agents using OpenAI-compatible APIs

Coding agents are powerful, but when one gets stuck in a loop it can be hard to see the spend until after the fact. Burnguard is a small open-source gateway that gives each agent/project a virtual key, meters requests, and lets you disable a runaway key from a local dashboard.

The practical workflow:

1. Start Burnguard locally.
2. Give the coding agent Burnguard's base URL and a virtual key.
3. Keep streaming enabled.
4. Watch requests and sessions show up in the dashboard.
5. If a session starts looping, click disable on that virtual key.

v0.1.0 includes streaming for OpenAI Chat Completions, OpenAI Responses, and Anthropic Messages routes, plus simple budgets, RPM caps, redacted previews, and a demo seed command.

It is not meant to replace provider billing controls. It is a local visibility and guardrail layer for development workflows.

Repo: [link]
Release: [link]
Agent integration docs: [link]

If you use coding agents with custom OpenAI-compatible endpoints, I would appreciate smoke-test reports and integration notes.

## Show HN

**Title:** Show HN: Burnguard – local budget guardrails for coding-agent API usage

Hi HN, I built Burnguard, a small open-source gateway for metering LLM API usage before coding agents turn curiosity into invoices.

The problem it targets is simple: when an agent loops against a shared provider key, the provider bill may not tell you which local key, project, model, or session caused the spend.

Burnguard sits between OpenAI-compatible/Anthropic-compatible clients and the provider. It gives agents virtual keys, checks simple budgets before forwarding requests, records usage in SQLite, and shows sessions in a local dashboard. The demo includes a runaway coding-agent session and a dashboard kill switch for disabling its key.

What is in v0.1.0:

- Chat Completions, Responses, and Anthropic Messages routes
- streaming/SSE support
- mock mode by default, so the demo does not call a paid provider
- per-key daily/monthly/max-request budgets and optional RPM caps
- atomic budget reservations before proxying requests
- redacted prompt/response previews by default
- optional shared admin token for dashboard/export access

It is intentionally an MVP: local-first, SQLite-backed, and not production-hardened. Plaintext virtual keys at rest and multi-user auth are still future hardening work.

Repo: [link]
Demo/release notes: [link]

I would love feedback on whether this fits real coding-agent workflows and what would make it safer before broader use.
