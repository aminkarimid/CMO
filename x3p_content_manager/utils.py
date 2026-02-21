import json
import os
from datetime import datetime
from typing import Any, Dict, Optional

_API_KEY_RULES = {
    "OPENAI_API_KEY": (
        "error",
        "OPENAI_API_KEY is not set. Please set it in your terminal or ~/.zshrc.",
    ),
    "TAVILY_API_KEY": (
        "error",
        "TAVILY_API_KEY is not set. Please set it in your terminal or ~/.zshrc.",
    ),
    "SEMANTIC_SCHOLAR_KEY": (
        "warning",
        "SEMANTIC_SCHOLAR_KEY is not set. Some advanced features may require it.",
    ),
}

_ENV_ALIASES = {
    "SEMANTIC_SCHOLAR_KEY": ["SEMANTIC_SCHOLAR_API_KEY"],
}

_ALLOWED_TOKEN_KEYS = {
    "prompt_tokens",
    "completion_tokens",
    "total_tokens",
    "cache_read_tokens",
    "cache_write_tokens",
}


def get_api_key_messages() -> Dict[str, list[str]]:
    for primary, aliases in _ENV_ALIASES.items():
        if os.getenv(primary):
            continue
        for alias in aliases:
            val = os.getenv(alias)
            if val:
                os.environ.setdefault(primary, val)
                break

    messages = {"errors": [], "warnings": []}
    for key, (level, text) in _API_KEY_RULES.items():
        if not os.getenv(key):
            messages[f"{level}s"].append(text)
    return messages


def print_api_key_messages(messages: Dict[str, list[str]]) -> None:
    for msg in messages.get("errors", []):
        print(f"[ERROR] {msg}")
    for msg in messages.get("warnings", []):
        print(f"[WARN] {msg}")


def log_telemetry(
    pipeline: str,
    success: bool,
    *,
    tokens: Optional[Dict[str, int]] = None,
    message: Optional[str] = None,
) -> None:
    os.makedirs("runs", exist_ok=True)
    entry = {
        "timestamp": datetime.now().isoformat(),
        "pipeline": pipeline,
        "success": success,
        "tokens": tokens or {},
        "message": message or "",
    }
    path = os.path.join("runs", "telemetry.log")
    with open(path, "a", encoding="utf-8") as fh:
        fh.write(json.dumps(entry, ensure_ascii=False) + "\n")


def extract_token_usage(result: Any) -> Optional[Dict[str, int]]:
    """Best-effort extraction of token usage from CrewAI result objects."""

    def _coerce(candidate: Any) -> Optional[Dict[str, int]]:
        if isinstance(candidate, dict):
            tokens: Dict[str, int] = {}
            for key in _ALLOWED_TOKEN_KEYS:
                value = candidate.get(key)
                if isinstance(value, (int, float)):
                    tokens[key] = int(value)
            return tokens or None
        if hasattr(candidate, "__dict__"):
            return _coerce(vars(candidate))
        return None

    candidates = [result]
    if hasattr(result, "to_dict"):
        try:
            candidates.append(result.to_dict())
        except Exception:
            pass
    for attr in (
        "token_usage",
        "usage",
        "usage_metadata",
        "llm_usage",
        "metrics",
    ):
        if hasattr(result, attr):
            candidates.append(getattr(result, attr))
    for candidate in candidates:
        tokens = _coerce(candidate)
        if tokens:
            return tokens
    return None


__all__ = [
    "get_api_key_messages",
    "print_api_key_messages",
    "log_telemetry",
    "extract_token_usage",
]
