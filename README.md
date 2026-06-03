# Burnguard

**Guardrails for shared LLM API usage.**

Burnguard is a small open-source prototype for metering shared AI API usage before coding agents turn curiosity into invoices.

It sits between AI tools and model providers, issuing local virtual keys, enforcing simple budgets, logging session-level usage, and flagging patterns like repeated prompts, large context, expensive model use, and possible agent loops.

Hopefully this category of tool is short-lived.

In a better tooling world, providers and coding agents would make per-user budgets, session-level cost visibility, and runaway-loop protection native. Until then, teams need a practical way to see who spent what, why it was spent, and when a session should have stopped.

> **Design phase / working prototype:** Burnguard is intentionally small and local-first. Treat the current implementation as an MVP for exploration, demos, and feedback rather than production infrastructure.

## Dashboard preview

![Burnguard seeded dashboard preview](docs/dashboard-preview.svg)

Run `python -m token_governor seed-demo` and start the app to populate a dashboard with normal usage, a fake runaway session, warning flags, and blocked requests.

## Why this exists

Coding agents are useful, but they can burn tokens in loops. Shared API accounts make the problem harder because a single provider key often hides which person, project, tool, or session caused the spend.

Burnguard sits between clients and an OpenAI-compatible provider:

```text
Client / Script / Coding Agent
        ↓
Burnguard Gateway
        ↓
Provider API
```

It gives teams a local MVP for visibility, simple budgets, and session-level inspection without building an enterprise platform.

## What the MVP does

- Accepts OpenAI-compatible `POST /v1/chat/completions` requests.
- Validates local virtual API keys such as `tg_sk_demo`.
- Enforces daily, monthly, and max-single-request budgets before a request is forwarded.
- Rejects unsupported streaming requests explicitly.
- Runs in **mock mode** by default so demos do not spend real API money.
- Can forward to one OpenAI-compatible provider when configured.
- Logs usage metadata to SQLite: owner, project, key, model, session, tokens, cost, status, route, latency, user-agent, category, and warning flags.
- Tracks sessions using `X-Token-Governor-Session` or generates a session id automatically.
- Classifies requests with local heuristics only. No extra LLM is used.
- Detects basic risk flags: repeated prompts, possible loops, large context, expensive models, budget-near-limit, high-cost requests, and test failure loops.
- Shows a plain FastAPI/Jinja dashboard at `/`, `/keys`, `/sessions`, `/sessions/{session_id}`, and `/requests`.
- Provides `python -m token_governor seed-demo` for fake data that makes the dashboard useful immediately.

## What it does not do

This is an MVP/prototype. It does **not** provide:

- multi-user login
- SaaS billing
- Kubernetes deployment
- full enterprise RBAC
- complex frontend
- LLM-powered classification
- raw prompt storage by default
- production-grade security claims
- perfect token accounting
- perfect support for every provider
- streaming support

## Quick start

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .[dev]
cp .env.example .env
python -m token_governor seed-demo
uvicorn token_governor.main:app --reload
```

Open the dashboard:

```text
http://localhost:8000/
```

## Demo API request

Mock mode is enabled by default in `.env.example`, so this does not call a paid provider:

```bash
curl http://localhost:8000/v1/chat/completions \
  -H "Authorization: Bearer tg_sk_demo" \
  -H "Content-Type: application/json" \
  -H "X-Token-Governor-Session: demo-session-1" \
  -d '{
    "model": "gpt-4o-mini",
    "messages": [
      {"role": "user", "content": "Write a Python function that adds two numbers."}
    ]
  }'
```

The gateway returns an OpenAI-compatible response and records the request.

## Create a virtual key

```bash
python -m token_governor create-key \
  --owner "Stephan" \
  --project "demo" \
  --daily-budget 5 \
  --monthly-budget 100 \
  --max-request 1
```

You can also provide `--key tg_sk_my_key` and `--allowed-models gpt-4o-mini,gpt-4.1`.

## Budget behavior

Burnguard uses HTTP **402 Payment Required** when a request is blocked by policy.

Example response:

```json
{
  "error": {
    "message": "Request blocked by Burnguard budget policy.",
    "type": "budget_exceeded",
    "details": {
      "daily_budget_usd": 5.0,
      "daily_spend_usd": 4.99,
      "projected_daily_spend_usd": 7.99,
      "estimated_request_cost_usd": 3.0
    }
  }
}
```

Budgets are intentionally simple:

- `daily_budget_usd`
- `monthly_budget_usd`
- `max_single_request_usd`

Before forwarding a request, Burnguard estimates input and expected output cost and blocks requests that would push the key over its daily or monthly budget. After a provider response, it records final estimated cost from returned usage when available.

## Pricing notes

Model pricing lives in `token_governor/pricing.py`. Defaults are placeholders for demo purposes and must be verified before real use.

Included sample entries:

```json
{
  "gpt-4o-mini": {"input_per_1m": 0.15, "output_per_1m": 0.60},
  "gpt-4.1": {"input_per_1m": 2.00, "output_per_1m": 8.00},
  "claude-sonnet": {"input_per_1m": 3.00, "output_per_1m": 15.00}
}
```

## Privacy notes

By default, Burnguard does **not** store full prompts or full responses.

It stores:

- prompt hash
- response hash
- short redacted previews capped at 200 characters
- category labels
- usage metadata

Raw message storage is controlled by:

```env
STORE_RAW_MESSAGES=false
```

If this is false, raw prompt and response bodies are not persisted. Previews are still only lightweight heuristics: common API keys, bearer tokens, passwords, secrets, and email addresses are redacted, but teams should treat previews as operational metadata rather than a security boundary.

## Configuration

Copy `.env.example` to `.env` and edit as needed:

```env
TOKEN_GOVERNOR_MODE=mock
DATABASE_URL=sqlite:///./token_governor.db
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
OPENAI_COMPATIBLE_API_KEY=replace_me
STORE_RAW_MESSAGES=false
DEFAULT_DAILY_BUDGET_USD=5
DEFAULT_MONTHLY_BUDGET_USD=100
DEFAULT_MAX_SINGLE_REQUEST_USD=1
LARGE_CONTEXT_TOKEN_THRESHOLD=50000
LOOP_REQUEST_COUNT=10
LOOP_WINDOW_MINUTES=15
```

To call a real OpenAI-compatible provider, set:

```env
TOKEN_GOVERNOR_MODE=proxy
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
OPENAI_COMPATIBLE_API_KEY=your_real_provider_key
```

## Dashboard pages

- `/` — overview: spend, requests, top users/projects/sessions/models, categories, flags, blocked requests
- `/keys` — virtual keys and budgets
- `/sessions` — session list with spend totals
- `/sessions/{session_id}` — session detail, repeated prompts, category breakdown, flags, timeline
- `/requests` — recent request log

## Development

```bash
pytest
python -m token_governor seed-demo
uvicorn token_governor.main:app --reload
```

## Roadmap

- OpenAI Responses API support
- Anthropic Messages API support
- LiteLLM integration
- streaming support
- Slack/Discord alerts
- GitHub PR/session correlation
- MCP/tool-call cost attribution
- repeated file/context detection
- cost-per-merged-PR reports
- per-team approval workflows
- Docker Compose deployment
- hosted dashboard mode
- export to CSV/JSON
- Prometheus/OpenTelemetry support

## License

MIT
