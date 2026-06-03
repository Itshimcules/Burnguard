from __future__ import annotations

import re

CATEGORIES = {
    "code_generation",
    "code_review",
    "repo_context",
    "test_output",
    "debugging",
    "planning",
    "documentation",
    "general_chat",
    "unknown",
}


def _stringify_messages(messages: list[dict] | str | None) -> str:
    if messages is None:
        return ""
    if isinstance(messages, str):
        return messages
    parts: list[str] = []
    for message in messages:
        content = message.get("content", "") if isinstance(message, dict) else str(message)
        if isinstance(content, list):
            parts.extend(str(item.get("text", item)) if isinstance(item, dict) else str(item) for item in content)
        else:
            parts.append(str(content))
    return "\n".join(parts)


def classify_request(messages: list[dict] | str | None) -> str:
    text = _stringify_messages(messages)
    lower = text.lower()
    file_paths = len(re.findall(r"(?:^|\s)[\w./-]+\.(?:py|js|ts|tsx|md|rs|go|java|json|yaml|yml|toml)", text))
    code_fences = lower.count("```")

    if any(term in lower for term in ["pytest", "failed test", "test failed", "assertionerror", "npm test", "cargo test"]):
        return "test_output"
    if any(term in lower for term in ["traceback", "exception", "stack trace", "error:", "segmentation fault", "debug"]):
        return "debugging"
    if any(term in lower for term in ["review this diff", "pull request", " pr ", "code review", "review the patch"]):
        return "code_review"
    if file_paths >= 4 or code_fences >= 4 or any(term in lower for term in ["repository", "codebase", "repo context"]):
        return "repo_context"
    if any(term in lower for term in ["write", "implement", "modify", "patch", "create a function", "add a feature", "refactor"]):
        return "code_generation"
    if any(term in lower for term in ["plan", "roadmap", "architecture", "break down", "steps"]):
        return "planning"
    if any(term in lower for term in ["readme", "documentation", "docs", "markdown", "changelog"]):
        return "documentation"
    if text.strip():
        return "general_chat"
    return "unknown"
