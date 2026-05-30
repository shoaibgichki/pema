"""Application configuration via environment variables."""

from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """Central configuration loaded from environment variables / .env file."""

    # Database
    database_url: str = "postgresql+asyncpg://localhost:5432/pema"

    # LLM Provider (OpenAI-compatible: OpenAI, OpenRouter, etc.)
    openai_api_key: str = ""
    openai_base_url: str = ""  # Leave empty for OpenAI; set for OpenRouter
    openai_model: str = "gpt-5.4-mini"

    # Engine tuning
    engine_version: str = "2.0.0"

    # Logging
    log_level: str = "INFO"

    # Prompt version (tracked in audit logs)
    conversation_prompt_version: str = "v1"
    # Symptom normalization (safety pre-pass) prompt version
    symptom_norm_prompt_version: str = "v1"

    model_config = {"env_file": ".env", "env_file_encoding": "utf-8"}


settings = Settings()
