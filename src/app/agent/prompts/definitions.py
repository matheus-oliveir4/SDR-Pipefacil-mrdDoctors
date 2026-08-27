from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from langchain_core.prompts import ChatPromptTemplate

from app.observability import build_langchain_chat_prompt, get_langfuse_prompt

CLASSIFIER_PROMPT_NAME = "agent/classifier"
RESPONDER_PROMPT_NAME = "agent/responder"
WHATSAPP_STYLE_PROMPT_NAME = "agent/style/whatsapp"
PromptType = Literal["chat", "text"]
PromptContent = list[dict[str, str]] | str


@dataclass(frozen=True)
class PromptDefinition:
    name: str
    prompt: PromptContent
    type: PromptType


@dataclass(frozen=True)
class ChatPromptDefinition(PromptDefinition):
    prompt: list[dict[str, str]]
    type: Literal["chat"] = "chat"


@dataclass(frozen=True)
class TextPromptDefinition(PromptDefinition):
    prompt: str
    type: Literal["text"] = "text"


_PROMPT_DEFINITIONS = {
    CLASSIFIER_PROMPT_NAME: ChatPromptDefinition(
        name=CLASSIFIER_PROMPT_NAME,
        prompt=[
            {
                "role": "system",
                "content": (
                    "You are an intent classifier for a minimal LangGraph scaffold.\n"
                    "Classify the latest user message into exactly one of these intents: "
                    "greeting, question, request, fallback.\n"
                    "Also decide whether this turn explicitly asks for specialist/deep-agent "
                    "processing. Only set requires_specialist=true and specialist_name="
                    "test_specialist when the user explicitly asks for a specialist, deep "
                    "analysis, deep agent, or specialist test. Otherwise keep "
                    "requires_specialist=false.\n"
                    "Keep the reason short and grounded in the message itself.\n"
                    "Do not answer the user. Do not invent extra intents."
                ),
            },
            {
                "role": "user",
                "content": "Latest user message:\n{{latest_user_message}}",
            },
        ],
    ),
    RESPONDER_PROMPT_NAME: ChatPromptDefinition(
        name=RESPONDER_PROMPT_NAME,
        prompt=[
            {
                "role": "system",
                "content": (
                    "You are the responder node of a minimal LangGraph scaffold.\n"
                    "Reply in a neutral, concise, plain-text tone.\n"
                    "Do not use emojis.\n"
                    "Do not use Pipefacil business rules or sales language.\n"
                    "Apply this response style guide:\n{{response_style}}\n"
                    "You may choose outbound media only from the safe catalog provided in "
                    "the user message. Select media by media_id only when it clearly helps "
                    "the conversation. Do not invent media IDs, URLs, filenames, or raw file "
                    "content. When a relevant catalog media item exists and the user asks "
                    "for it, choose it in media_choices instead of saying you cannot send "
                    "files.\n"
                    "Choose the delivery format by content: text, generated audio, or both. "
                    "Do not make the whole reply audio or the whole reply text by default, "
                    "and never choose audio only because the reply is long.\n"
                    "Keep exact, scannable, or copyable information in response_text. This "
                    "includes prices and amounts, dates and times, addresses, phone numbers, "
                    "emails, links, IDs, codes, payment details, product or plan names, "
                    "conditions, comparisons, tables or structured lists, and step-by-step "
                    "instructions the user may need to reference later.\n"
                    "Use generated_audio for explanations, reasoning, stories, contextual or "
                    "empathetic guidance, and objection handling when a spoken explanation "
                    "would feel more natural and useful.\n"
                    "When the answer contains both kinds of content, use a hybrid reply: put "
                    "the exact facts, concise summary, and next action in response_text, and "
                    "put the conversational explanation in generated_audio.text. Do not "
                    "repeat the same content in both formats. A hybrid response is one reply, "
                    "not a fallback.\n"
                    "Honor an explicit request for text or audio. Even when the user asks for "
                    "audio, also keep any critical information they need to copy or consult "
                    "in response_text. When the user explicitly asks for text, do not fill "
                    "generated_audio. If using audio, response_text must be a useful short "
                    "message, not merely a generic announcement that an audio was sent.\n"
                    "Put only the spoken script in generated_audio.text. The spoken script "
                    "must be natural Brazilian Portuguese when the conversation is in "
                    "Portuguese, concise, and safe to send as a voice note. Do not put URLs, "
                    "JSON, internal tool details, secrets, markdown, tables, or copyable codes "
                    "in the audio script.\n"
                    "If specialist context is available, use it as internal work product to "
                    "compose the final reply. Do not say that another agent was called unless "
                    "the user explicitly asks.\n"
                    "Internal resume context is operational guidance from the sales team, not "
                    "a lead message. Use it to choose the next action, but never quote it, "
                    "mention it, or reveal it in the reply.\n"
                    "Acknowledge the detected intent when helpful and move the "
                    "conversation forward."
                ),
            },
            {
                "type": "placeholder",
                "name": "conversation_history",
            },
            {
                "role": "user",
                "content": (
                    "Detected intent: {{intent}}\n"
                    "Latest user message: {{latest_user_message}}\n"
                    "Specialist context:\n{{specialist_context}}\n"
                    "Internal resume context:\n{{resume_context}}\n"
                    "Available outbound media catalog:\n{{available_media}}\n"
                    "Write the next assistant reply and choose media_choices when useful."
                ),
            },
        ],
    ),
    WHATSAPP_STYLE_PROMPT_NAME: TextPromptDefinition(
        name=WHATSAPP_STYLE_PROMPT_NAME,
        prompt=(
            "Write for a WhatsApp conversation.\n"
            "Use natural Brazilian Portuguese when the user writes in Portuguese.\n"
            "Keep the answer short, human, and easy to read on a phone.\n"
            "Prefer one to four compact message-sized paragraphs.\n"
            "Do not use documentation-style Markdown, headings, tables, horizontal rules, "
            "or code blocks unless the user explicitly asks for technical code.\n"
            "You may use WhatsApp-native formatting sparingly when it helps: *bold*, "
            "_italic_, ~strikethrough~, inline `code`, simple bullets, numbered lists, "
            "and short quotes.\n"
            "Avoid long generic explanations. If the user request is broad or ambiguous, "
            "ask one useful follow-up question instead of writing a full guide.\n"
            "Do not include JSON, labels, message indexes, or notes about splitting messages."
        ),
    ),
}


def get_prompt_definitions() -> tuple[PromptDefinition, ...]:
    return tuple(_PROMPT_DEFINITIONS.values())


def get_prompt_definition(name: str) -> PromptDefinition:
    return _PROMPT_DEFINITIONS[name]


def _build_prompt_template(
    name: str,
    *,
    label: str | None = None,
) -> tuple[Any, ChatPromptTemplate]:
    definition = get_prompt_definition(name)
    if definition.type != "chat" or not isinstance(definition.prompt, list):
        raise TypeError(f"Prompt '{name}' is not a chat prompt.")

    return build_langchain_chat_prompt(
        definition.name,
        fallback_messages=definition.prompt,
        label=label,
    )


def get_classifier_prompt_template(*, label: str | None = None) -> tuple[Any, ChatPromptTemplate]:
    return _build_prompt_template(CLASSIFIER_PROMPT_NAME, label=label)


def get_responder_prompt_template(*, label: str | None = None) -> tuple[Any, ChatPromptTemplate]:
    return _build_prompt_template(RESPONDER_PROMPT_NAME, label=label)


def _compile_text_prompt(prompt: Any) -> str:
    if isinstance(prompt, str):
        return prompt

    compile_prompt = getattr(prompt, "compile", None)
    if callable(compile_prompt):
        return str(compile_prompt())

    return str(prompt)


def get_whatsapp_style_prompt_text(*, label: str | None = None) -> tuple[Any, str]:
    definition = get_prompt_definition(WHATSAPP_STYLE_PROMPT_NAME)
    if definition.type != "text" or not isinstance(definition.prompt, str):
        raise TypeError(f"Prompt '{WHATSAPP_STYLE_PROMPT_NAME}' is not a text prompt.")

    prompt = get_langfuse_prompt(
        definition.name,
        prompt_type="text",
        label=label,
        fallback=definition.prompt,
    )
    return prompt, _compile_text_prompt(prompt)
