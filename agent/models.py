from config import LLM_PROVIDER, OPENAI_API_KEY, GOOGLE_API_KEY, ANTHROPIC_API_KEY


def get_model() -> str:
    """根據 .env 中的 LLM_PROVIDER 回傳 pydantic-ai 的 model 字串"""
    provider = LLM_PROVIDER.lower()

    if provider == "openai":
        if not OPENAI_API_KEY:
            raise ValueError("OPENAI_API_KEY is not set in .env")
        return "openai:gpt-5-mini"

    elif provider == "google":
        if not GOOGLE_API_KEY:
            raise ValueError("GOOGLE_API_KEY is not set in .env")
        return "google-gla:gemini-3.1-flash-preview"

    elif provider == "claude" or provider == "anthropic":
        if not ANTHROPIC_API_KEY:
            raise ValueError("ANTHROPIC_API_KEY is not set in .env")
        return "anthropic:claude-sonnet-4-5-20250514"

    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}. Use 'openai', 'google', or 'claude'.")
