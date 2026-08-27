from functools import lru_cache
from typing import Any, Literal

from pydantic import Field, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

from app.core.agent_config_generated import AGENT_DEFAULTS


def _agent_default(name: str) -> Any:
    return AGENT_DEFAULTS[name]


class Settings(BaseSettings):
    app_name: str = _agent_default("app_name")
    app_slug: str = _agent_default("app_slug")
    app_env: str = "development"
    app_version: str = "0.1.0"
    database_url: str | None = None
    langgraph_checkpoint_schema: str | None = None
    langgraph_checkpoint_pool_min_size: int = Field(default=1, ge=1)
    langgraph_checkpoint_pool_max_size: int = Field(default=10, ge=1)
    langgraph_checkpoint_pool_timeout_seconds: float = Field(default=10.0, gt=0)
    cloudflare_tunnel_token: str | None = None
    cloudflare_tunnel_hostname: str | None = None
    cloudflare_tunnel_url: str | None = None
    cloudflare_tunnel_metrics: str | None = None
    cloudflare_tunnel_loglevel: str | None = None
    # Pipefacil still exposes its public API through this legacy infrastructure hostname.
    pipefacil_base_url: str = "https://pipefacil-server.matchsales.com.br"
    pipefacil_api_key: str | None = None
    pipefacil_conversation_history_path: str = _agent_default("pipefacil_conversation_history_path")
    pipefacil_timeout_seconds: float = Field(
        default=_agent_default("pipefacil_timeout_seconds"), gt=0
    )
    pipefacil_media_max_bytes: int = Field(
        default=_agent_default("pipefacil_media_max_bytes"), ge=1
    )
    pipefacil_webhook_idempotency_ttl_seconds: int = Field(
        default=_agent_default("pipefacil_webhook_idempotency_ttl_seconds"), ge=0
    )
    pipefacil_ai_attendance_field_slug: str = _agent_default("pipefacil_ai_attendance_field_slug")
    pipefacil_max_tokens_per_lead: int = Field(
        default=_agent_default("pipefacil_max_tokens_per_lead"), ge=0
    )
    pipefacil_webhook_signature_enabled: bool = True
    pipefacil_webhook_signature_secret: str | None = None
    pipefacil_webhook_signature_header: str = _agent_default("pipefacil_webhook_signature_header")
    outbound_media_catalog_path: str | None = None
    generated_audio_enabled: bool = _agent_default("generated_audio_enabled")
    generated_audio_auto_enabled: bool = _agent_default("generated_audio_auto_enabled")
    generated_audio_auto_min_chars: int = Field(
        default=_agent_default("generated_audio_auto_min_chars"), ge=1
    )
    generated_audio_max_chars: int = Field(
        default=_agent_default("generated_audio_max_chars"), ge=1
    )
    generated_audio_public_base_url: str | None = None
    generated_audio_storage_dir: str = _agent_default("generated_audio_storage_dir")
    generated_audio_ttl_seconds: int = Field(
        default=_agent_default("generated_audio_ttl_seconds"), ge=60
    )
    generated_audio_auto_text: str = _agent_default("generated_audio_auto_text")
    generated_audio_convert_to_ogg_opus: bool = _agent_default(
        "generated_audio_convert_to_ogg_opus"
    )
    elevenlabs_base_url: str = _agent_default("elevenlabs_base_url")
    elevenlabs_api_key: str | None = None
    elevenlabs_voice_id: str | None = _agent_default("elevenlabs_voice_id")
    elevenlabs_model_id: str = _agent_default("elevenlabs_model_id")
    elevenlabs_output_format: str = _agent_default("elevenlabs_output_format")
    elevenlabs_tts_cost_per_1k_chars_usd: float | None = Field(
        default=_agent_default("elevenlabs_tts_cost_per_1k_chars_usd"), ge=0
    )
    elevenlabs_timeout_seconds: float = Field(
        default=_agent_default("elevenlabs_timeout_seconds"), gt=0
    )
    elevenlabs_max_attempts: int = Field(
        default=_agent_default("elevenlabs_max_attempts"), ge=1, le=2
    )
    elevenlabs_retry_backoff_seconds: float = Field(
        default=_agent_default("elevenlabs_retry_backoff_seconds"), ge=0, le=5
    )
    elevenlabs_voice_stability: float | None = Field(
        default=_agent_default("elevenlabs_voice_stability"), ge=0, le=1
    )
    elevenlabs_voice_similarity_boost: float | None = Field(
        default=_agent_default("elevenlabs_voice_similarity_boost"), ge=0, le=1
    )
    elevenlabs_voice_style: float | None = Field(
        default=_agent_default("elevenlabs_voice_style"), ge=0, le=1
    )
    elevenlabs_voice_use_speaker_boost: bool | None = _agent_default(
        "elevenlabs_voice_use_speaker_boost"
    )
    elevenlabs_voice_speed: float | None = Field(
        default=_agent_default("elevenlabs_voice_speed"), gt=0, le=2
    )
    langfuse_enabled: bool = True
    langfuse_public_key: str | None = None
    langfuse_secret_key: str | None = None
    langfuse_base_url: str | None = None
    langfuse_tracing_environment: str | None = None
    langfuse_prompt_label: str | None = None
    langfuse_debug: bool = False
    langfuse_pipefacil_user_id_mode: Literal["contact_id", "contact_name_phone"] = _agent_default(
        "langfuse_pipefacil_user_id_mode"
    )
    log_level: str = "INFO"
    log_format: str | None = None
    log_inbound_payloads: bool = False
    openai_model: str = _agent_default("openai_model")
    openai_transcription_model: str = _agent_default("openai_transcription_model")
    openai_specialists_enabled: bool = _agent_default("openai_specialists_enabled")
    openai_specialist_model: str | None = _agent_default("openai_specialist_model")
    openai_specialist_max_turns: int = Field(
        default=_agent_default("openai_specialist_max_turns"), ge=1
    )
    openai_api_key: str | None = None

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
    )

    @model_validator(mode="after")
    def validate_langgraph_checkpoint_pool(self) -> "Settings":
        if self.langgraph_checkpoint_pool_max_size < self.langgraph_checkpoint_pool_min_size:
            raise ValueError(
                "LANGGRAPH_CHECKPOINT_POOL_MAX_SIZE must be greater than or equal to "
                "LANGGRAPH_CHECKPOINT_POOL_MIN_SIZE."
            )

        if (
            self.generated_audio_auto_enabled
            and self.generated_audio_auto_min_chars > self.generated_audio_max_chars
        ):
            raise ValueError(
                "GENERATED_AUDIO_AUTO_MIN_CHARS cannot exceed GENERATED_AUDIO_MAX_CHARS."
            )

        return self


@lru_cache
def get_settings() -> Settings:
    return Settings()
