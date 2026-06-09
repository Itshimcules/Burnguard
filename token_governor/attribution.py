from __future__ import annotations

import json
import re
from typing import Any

from .privacy import stable_hash

_FILE_PATTERN = re.compile(r"\b[\w./\\-]+\.(?:py|js|ts|tsx|jsx|go|rs|java|rb|php|cs|css|html|md|json|yaml|yml|toml|sql)\b")


def _walk(value: Any):
    if isinstance(value, dict):
        yield value
        for item in value.values():
            yield from _walk(item)
    elif isinstance(value, list):
        for item in value:
            yield from _walk(item)


def _text(value: Any) -> str:
    if isinstance(value, str):
        return value
    return json.dumps(value, default=str)


def extract_tool_names(*values: Any) -> list[str]:
    names: set[str] = set()
    for value in values:
        for item in _walk(value):
            if not isinstance(item, dict):
                continue
            if isinstance(item.get("tools"), list):
                for tool in item["tools"]:
                    if isinstance(tool, dict):
                        name = tool.get("name") or tool.get("function", {}).get("name")
                        if name:
                            names.add(str(name))
            if isinstance(item.get("tool_calls"), list):
                for tool_call in item["tool_calls"]:
                    if isinstance(tool_call, dict):
                        name = tool_call.get("name") or tool_call.get("function", {}).get("name")
                        if name:
                            names.add(str(name))
            tool_type = item.get("type")
            if tool_type in {"function_call", "tool_call", "tool_use"}:
                name = item.get("name") or item.get("function", {}).get("name")
                if name:
                    names.add(str(name))
    return sorted(names)


def count_tool_calls(*values: Any) -> int:
    count = 0
    for value in values:
        for item in _walk(value):
            if isinstance(item, dict):
                if item.get("type") in {"function_call", "tool_call", "tool_use"}:
                    count += 1
                if isinstance(item.get("tool_calls"), list):
                    count += len(item["tool_calls"])
    return count


def file_context_hash(value: Any) -> str | None:
    paths = sorted(set(_FILE_PATTERN.findall(_text(value))))
    if not paths:
        return None
    return stable_hash(paths)
