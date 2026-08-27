from __future__ import annotations

from typing import Any

from langchain_openai import ChatOpenAI

from app.core.config import get_settings


def model_supports_custom_temperature(model_name: str) -> bool:
    normalized_name = model_name.strip().lower()
    return not normalized_name.startswith("gpt-5")


def get_chat_model(*, temperature: float | None) -> ChatOpenAI:
    settings = get_settings()
    model_kwargs: dict[str, Any] = {"model": settings.openai_model}
    if settings.openai_api_key:
        model_kwargs["api_key"] = settings.openai_api_key
    if temperature is not None and model_supports_custom_temperature(settings.openai_model):
        model_kwargs["temperature"] = temperature
    return ChatOpenAI(**model_kwargs)
