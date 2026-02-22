from __future__ import annotations


def normalize_generation_error(exc: Exception | str) -> str:
    msg = str(exc or "").lower()
    if ("template variable" in msg and "not found in inputs dictionary" in msg) or "missing required template variable" in msg:
        return "Input template mismatch was auto-fixed."

    quota_hints = (
        "insufficient_quota",
        "exceeded your current quota",
        "quota exceeded",
        "openai quota exceeded",
        "quota is exhausted",
        "billing details",
        "error code: 429",
    )
    if any(h in msg for h in quota_hints):
        return "OpenAI quota is exhausted. Add billing/credits or switch to a key with available quota."

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

    tool_hints = (
        "tool health",
        "critical health checks failed",
        "tavily_api_key",
        "x3p.ai probe failed",
        "trend sourcing failed",
    )
    if any(h in msg for h in tool_hints):
        return "System health checks failed. Verify tool credentials/connectivity, then retry."

    timeout_hints = (
        "timeout",
        "timed out",
        "read timed out",
        "connection reset",
        "connect timeout",
    )
    if any(h in msg for h in timeout_hints):
        return "Generation timed out during a required stage. Please retry."

    if "stage dependency" in msg or "no trend claims passed strict verification" in msg:
        return "Generation stopped because required verified evidence was unavailable."

    return "Generation stopped. Please retry."
