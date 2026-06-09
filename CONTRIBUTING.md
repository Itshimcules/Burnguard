# Contributing

Burnguard is a small local-first prototype. Keep changes focused, easy to review, and honest about the current MVP limits.

## Local setup

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env
```

On Windows PowerShell:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -e ".[dev]"
Copy-Item .env.example .env
```

## Run tests

```bash
pytest
```

or on Windows PowerShell:

```powershell
.\.venv\Scripts\python.exe -m pytest
```

## Run the demo app

```bash
python -m token_governor seed-demo
uvicorn token_governor.main:app --reload
```

Open `http://localhost:8000/`.

## Pull requests

- Keep PRs scoped to one behavior or documentation improvement.
- Add or update tests for gateway behavior, budget decisions, and dashboard rendering.
- Do not commit local databases, virtual environments, screenshots, or package metadata.
- Keep README and launch copy concrete. Avoid production claims, vague AI language, or inflated benchmarks.
