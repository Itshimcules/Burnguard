# Launch notes

Burnguard should be introduced as a local open-source gateway for metering coding-agent API usage, not as a production billing platform.

## GitHub setup

Recommended topics:

```text
ai-agents
openai-compatible
api-gateway
token-usage
cost-control
developer-tools
fastapi
sqlite
llm
```

Use `docs/assets/brand/burnguard-social-card.svg` as the source for the GitHub social preview. Export it to PNG if GitHub does not accept the SVG upload.

Before launch:

- Confirm CI is passing.
- Create a `v0.1.0` release tag.
- Verify the README 5-minute demo works from a clean clone.
- Keep the repo description specific: `Local gateway for metering shared LLM API usage before coding agents run up costs.`

## Show HN draft

Title:

```text
Show HN: Burnguard - local gateway for metering coding-agent LLM usage
```

Post:

```text
Hi HN, I built Burnguard, a small local-first gateway that sits between coding agents and OpenAI-compatible or Anthropic-style APIs.

The immediate problem is shared API keys. When a coding agent loops, sends huge context, or keeps retrying failed tests, the provider bill often does not explain which tool, project, session, or prompt pattern caused the spend.

Burnguard issues local virtual keys, estimates request cost before forwarding, blocks requests that cross simple daily/monthly/max-request budgets, and logs usage to SQLite. The dashboard shows spend by owner/project/session/model plus warning flags for repeated prompts, large context, expensive models, and possible loops.

It is intentionally an MVP: local FastAPI app, SQLite, mock mode by default, no hosted service, no production security claims, and no streaming yet. The repo includes a 5-minute demo and copy-paste prompts for configuring Hermes Agent and OpenClaw through its OpenAI-compatible endpoint.

I am looking for feedback from people using coding agents with shared API keys: what controls or session views would have helped you catch runaway usage earlier?
```

## Community post draft

```text
I am testing Burnguard, a local open-source gateway for tracking and limiting LLM API usage from coding agents.

It runs locally, uses virtual API keys, logs request/session cost to SQLite, and flags repeated prompts, large context, expensive models, and possible loops. Mock mode is enabled by default so the demo does not call a paid provider.

The current focus is developers using shared OpenAI-compatible, OpenRouter, or Anthropic-style keys with tools like coding agents and local automation.

Repo: https://github.com/Itshimcules/Burnguard

I would appreciate feedback on the local setup, dashboard, and which budget/session controls would be useful in real agent workflows.
```

## Product Hunt prep

Wait until Burnguard has:

- a tagged release
- passing CI badge
- a short demo GIF or video
- a GitHub social preview
- at least one documented real provider setup
- a crisp one-line tagline without production claims
