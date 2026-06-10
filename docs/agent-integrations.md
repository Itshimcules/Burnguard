# Agent integrations

Burnguard can sit in front of agents that support an OpenAI-compatible API base URL. For Hermes Agent and OpenClaw, point the agent at Burnguard's local `/v1` endpoint and use a Burnguard virtual key as the API key.

This integration covers OpenAI-compatible traffic, streaming and non-streaming:

- `POST /v1/chat/completions`
- `POST /v1/responses`

Streaming responses are relayed as SSE and metered from the stream's usage events.

## Burnguard setup

Start in mock mode while wiring up an agent. Mock mode records metering data without calling a paid provider.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
python -m token_governor seed-demo
uvicorn token_governor.main:app --reload
```

Use these values in the agent:

```text
API base URL: http://localhost:8000/v1
API key: tg_sk_demo
Model: gpt-4o-mini
```

For a real upstream provider, run Burnguard in proxy mode and keep the real provider key in Burnguard's `.env`, not in the agent config:

```env
TOKEN_GOVERNOR_MODE=proxy
OPENAI_COMPATIBLE_BASE_URL=https://api.openai.com/v1
OPENAI_COMPATIBLE_API_KEY=your_real_openai_compatible_key
```

## Hermes Agent

Hermes Agent supports custom OpenAI-compatible endpoints. Configure the model provider with:

```yaml
model:
  default: "gpt-4o-mini"
  provider: "custom"
  base_url: "http://localhost:8000/v1"
  api_key: "tg_sk_demo"
```

You can also use Hermes' interactive model setup and choose the custom endpoint option. Enter `http://localhost:8000/v1` as the API base URL, `tg_sk_demo` as the API key, and `gpt-4o-mini` as the model name.

## OpenClaw

Use OpenClaw's custom or OpenAI-compatible provider configuration and set:

```text
Base URL: http://localhost:8000/v1
API key: tg_sk_demo
Model: gpt-4o-mini
```

For OpenClaw configurations that use a JSON-style provider entry, the intent should be equivalent to:

```json
{
  "provider": "openai-compatible",
  "base_url": "http://localhost:8000/v1",
  "api_key": "tg_sk_demo",
  "model": "gpt-4o-mini"
}
```

OpenClaw also has Codex/OAuth runtime paths. This Burnguard integration is for direct OpenAI-compatible API routing where OpenClaw sends model requests to a custom base URL.

## Session tracking

Burnguard records a session id for every request. If the agent supports custom headers, add a stable header per agent run:

```text
X-Token-Governor-Session: hermes-project-a
```

or:

```text
X-Token-Governor-Session: openclaw-project-a
```

If the agent cannot send custom headers, Burnguard generates a session id automatically.

## Copy-paste prompt for an agent

Paste this into Hermes, OpenClaw, or another coding agent when you want it to configure itself or a local project to use Burnguard.

```text
Configure this agent or project to route OpenAI-compatible model requests through Burnguard.

Use these Burnguard settings:
- API base URL: http://localhost:8000/v1
- API key: tg_sk_demo
- Default model: gpt-4o-mini

Requirements:
1. Inspect the existing agent/model/provider configuration before changing anything.
2. Preserve the current model name if one is already configured and it is allowed by the Burnguard virtual key; otherwise use gpt-4o-mini.
3. Set the provider to a custom OpenAI-compatible endpoint when the tool offers that option.
4. Do not put the real upstream OpenAI, Anthropic, OpenRouter, or other provider key into the agent config. Burnguard proxy mode should own real upstream provider keys.
5. If custom headers are supported, add X-Token-Governor-Session with a stable value that identifies this agent run or project.
6. Keep streaming disabled unless Burnguard has explicit streaming support.
7. After configuration, run one small non-streaming chat or responses request and confirm Burnguard records it on http://localhost:8000/requests.

Report the files or settings changed, the final base URL, the model, whether a session header was configured, and the result of the smoke test.
```

Before using a real paid provider, open `http://localhost:8000/keys` and confirm the virtual key has appropriate daily, monthly, and max-request budgets.
