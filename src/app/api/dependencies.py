from __future__ import annotations

from typing import Any

from fastapi import Request

from app.application.idempotency import MessageIdempotencyStore
from app.core.config import Settings


def get_graph(request: Request) -> Any:
    return request.app.state.graph


def get_settings(request: Request) -> Settings:
    return request.app.state.settings


def get_pipefacil_message_idempotency_store(request: Request) -> MessageIdempotencyStore:
    return request.app.state.pipefacil_message_idempotency_store
