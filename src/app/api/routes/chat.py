from __future__ import annotations

from typing import Annotated, Any

from fastapi import APIRouter, Depends

from app.api.dependencies import get_graph
from app.api.presenters import chat_turn_response_payload
from app.api.schemas.chat import ChatRequest, ChatResponse
from app.application import run_chat_turn

chat_router = APIRouter()
GraphDep = Annotated[Any, Depends(get_graph)]


@chat_router.post("/chat", response_model=ChatResponse)
def chat(payload: ChatRequest, graph: GraphDep) -> ChatResponse:
    result = run_chat_turn(
        message=payload.message,
        thread_id=payload.thread_id,
        user_id=payload.user_id,
        metadata=payload.metadata,
        graph=graph,
    )
    return ChatResponse(**chat_turn_response_payload(result))
