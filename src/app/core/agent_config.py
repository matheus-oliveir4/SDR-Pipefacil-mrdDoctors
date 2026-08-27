from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

ENVIRONMENT_OVERRIDE_DEFAULT_FIELDS = frozenset(
    {
        "generated_audio_enabled",
        "generated_audio_auto_enabled",
        "pipefacil_webhook_signature_header",
        "openai_model",
        "openai_specialists_enabled",
        "openai_specialist_model",
    }
)


class _StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class PipefacilAgentConfig(_StrictModel):
    timeout_seconds: float = Field(default=20.0, gt=0)
    media_max_bytes: int = Field(default=25_000_000, ge=1)
    webhook_idempotency_ttl_seconds: int = Field(default=86_400, ge=0)
    ai_attendance_field_slug: str = "atendimento_por_ia"
    max_tokens_per_lead: int = Field(default=0, ge=0)
    conversation_history_path: str = "/api/v1/messages"
    webhook_signature_header: str = "X-Pipefacil-Signature-256"


class AudioAgentConfig(_StrictModel):
    enabled: bool = False
    auto_enabled: bool = False
    auto_min_chars: int = Field(default=650, ge=1)
    max_chars: int = Field(default=1_200, ge=1)
    ttl_seconds: int = Field(default=86_400, ge=60)
    storage_dir: str = ".runtime/generated-audio"
    auto_text: str = "Te mandei um audio para explicar melhor."
    convert_to_ogg_opus: bool = False


class ElevenLabsAgentConfig(_StrictModel):
    base_url: str = "https://api.elevenlabs.io"
    voice_id: str | None = None
    model_id: str = "eleven_v3"
    output_format: str = "opus_48000_96"
    tts_cost_per_1k_chars_usd: float | None = Field(default=None, ge=0)
    timeout_seconds: float = Field(default=30.0, gt=0)
    max_attempts: int = Field(default=2, ge=1, le=2)
    retry_backoff_seconds: float = Field(default=0.5, ge=0, le=5)
    voice_stability: float | None = Field(default=0.45, ge=0, le=1)
    voice_similarity_boost: float | None = Field(default=0.85, ge=0, le=1)
    voice_style: float | None = Field(default=0.35, ge=0, le=1)
    voice_use_speaker_boost: bool | None = True
    voice_speed: float | None = Field(default=1.0, gt=0, le=2)


class OpenAIAgentConfig(_StrictModel):
    model: str = "gpt-5.3-chat-latest"
    transcription_model: str = "gpt-4o-mini-transcribe"
    specialists_enabled: bool = False
    specialist_model: str | None = None
    specialist_max_turns: int = Field(default=8, ge=1)


class ObservabilityAgentConfig(_StrictModel):
    langfuse_pipefacil_user_id_mode: Literal["contact_id", "contact_name_phone"] = "contact_id"


class AgentConfig(_StrictModel):
    schema_version: Literal[1] = 1
    app_name: str = "SDR Agent Template"
    app_slug: str = Field(default="sdr-agent-template", pattern=r"^[a-z0-9][a-z0-9-]{1,62}$")
    pipefacil: PipefacilAgentConfig = Field(default_factory=PipefacilAgentConfig)
    audio: AudioAgentConfig = Field(default_factory=AudioAgentConfig)
    elevenlabs: ElevenLabsAgentConfig = Field(default_factory=ElevenLabsAgentConfig)
    openai: OpenAIAgentConfig = Field(default_factory=OpenAIAgentConfig)
    observability: ObservabilityAgentConfig = Field(default_factory=ObservabilityAgentConfig)

    @model_validator(mode="before")
    @classmethod
    def reject_sensitive_keys(cls, value: Any) -> Any:
        sensitive_suffixes = (
            "api_key",
            "secret",
            "secret_key",
            "password",
            "access_token",
            "auth_token",
        )

        def walk(node: Any) -> None:
            if isinstance(node, dict):
                for key, child in node.items():
                    normalized_key = str(key).lower()
                    if normalized_key.endswith(sensitive_suffixes):
                        raise ValueError(f"Sensitive configuration key is not allowed: {key}")
                    walk(child)
            elif isinstance(node, list):
                for child in node:
                    walk(child)

        walk(value)
        return value

    @model_validator(mode="after")
    def validate_audio_limits(self) -> AgentConfig:
        if self.audio.auto_enabled and self.audio.auto_min_chars > self.audio.max_chars:
            raise ValueError("audio.auto_min_chars cannot exceed audio.max_chars")
        return self


def load_agent_config(path: Path) -> AgentConfig:
    return AgentConfig.model_validate_json(path.read_text(encoding="utf-8"))


def agent_defaults(config: AgentConfig) -> dict[str, Any]:
    return {
        "app_name": config.app_name,
        "app_slug": config.app_slug,
        "pipefacil_timeout_seconds": config.pipefacil.timeout_seconds,
        "pipefacil_media_max_bytes": config.pipefacil.media_max_bytes,
        "pipefacil_webhook_idempotency_ttl_seconds": (
            config.pipefacil.webhook_idempotency_ttl_seconds
        ),
        "pipefacil_ai_attendance_field_slug": config.pipefacil.ai_attendance_field_slug,
        "pipefacil_max_tokens_per_lead": config.pipefacil.max_tokens_per_lead,
        "pipefacil_conversation_history_path": config.pipefacil.conversation_history_path,
        "pipefacil_webhook_signature_header": config.pipefacil.webhook_signature_header,
        "generated_audio_enabled": config.audio.enabled,
        "generated_audio_auto_enabled": config.audio.auto_enabled,
        "generated_audio_auto_min_chars": config.audio.auto_min_chars,
        "generated_audio_max_chars": config.audio.max_chars,
        "generated_audio_ttl_seconds": config.audio.ttl_seconds,
        "generated_audio_storage_dir": config.audio.storage_dir,
        "generated_audio_auto_text": config.audio.auto_text,
        "generated_audio_convert_to_ogg_opus": config.audio.convert_to_ogg_opus,
        "elevenlabs_base_url": config.elevenlabs.base_url,
        "elevenlabs_voice_id": config.elevenlabs.voice_id,
        "elevenlabs_model_id": config.elevenlabs.model_id,
        "elevenlabs_output_format": config.elevenlabs.output_format,
        "elevenlabs_tts_cost_per_1k_chars_usd": config.elevenlabs.tts_cost_per_1k_chars_usd,
        "elevenlabs_timeout_seconds": config.elevenlabs.timeout_seconds,
        "elevenlabs_max_attempts": config.elevenlabs.max_attempts,
        "elevenlabs_retry_backoff_seconds": config.elevenlabs.retry_backoff_seconds,
        "elevenlabs_voice_stability": config.elevenlabs.voice_stability,
        "elevenlabs_voice_similarity_boost": config.elevenlabs.voice_similarity_boost,
        "elevenlabs_voice_style": config.elevenlabs.voice_style,
        "elevenlabs_voice_use_speaker_boost": config.elevenlabs.voice_use_speaker_boost,
        "elevenlabs_voice_speed": config.elevenlabs.voice_speed,
        "openai_model": config.openai.model,
        "openai_transcription_model": config.openai.transcription_model,
        "openai_specialists_enabled": config.openai.specialists_enabled,
        "openai_specialist_model": config.openai.specialist_model,
        "openai_specialist_max_turns": config.openai.specialist_max_turns,
        "langfuse_pipefacil_user_id_mode": config.observability.langfuse_pipefacil_user_id_mode,
    }
