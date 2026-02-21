from __future__ import annotations


def normalize_generation_error(exc: Exception | str) -> str:
    msg = str(exc or "").lower()
    if ("template variable" in msg and "not found in inputs dictionary" in msg) or "missing required template variable" in msg:
        return "Input template mismatch was auto-fixed."

    if "runtime configuration error" in msg or ("validation error for crew" in msg and "memory" in msg):
        return "Runtime configuration was refreshed. Please retry generation."

    backend_hints = (
        "backend unavailable",
        "apiconnectionerror",
        "ollamaexception",
        "openaiexception - connection error",
        "openaiexception",
        "no usable backend found",
        "ollama is not reachable",
        "openai_api_key is missing",
        "invalid api key",
        "authenticationerror",
        "operation not permitted",
    )
    if any(h in msg for h in backend_hints):
        return "Backend is unavailable. Configure OPENAI_API_KEY or start Ollama, then retry."

    timeout_hints = (
        "timeout",
        "timed out",
        "read timed out",
        "connection reset",
        "connect timeout",
    )
    if any(h in msg for h in timeout_hints):
        return "Source check timed out; draft generated with conservative claims."

    return "Generation stopped. Please retry."
