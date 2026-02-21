from x3p_content_manager.app.errors import normalize_generation_error


def test_normalize_generation_error_for_backend_unavailable():
    msg = normalize_generation_error("APIConnectionError: OllamaException - [Errno 1] Operation not permitted")
    assert msg == "Backend is unavailable. Configure OPENAI_API_KEY or start Ollama, then retry."


def test_normalize_generation_error_for_openai_connection_error():
    msg = normalize_generation_error("litellm.InternalServerError: InternalServerError: OpenAIException - Connection error.")
    assert msg == "Backend is unavailable. Configure OPENAI_API_KEY or start Ollama, then retry."


def test_normalize_generation_error_for_runtime_configuration_issue():
    msg = normalize_generation_error("ValidationError: 1 validation error for Crew\\nmemory\\n  Input should be a valid boolean")
    assert msg == "Runtime configuration was refreshed. Please retry generation."
