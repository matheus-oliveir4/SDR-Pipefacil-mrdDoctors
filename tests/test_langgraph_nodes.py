import importlib

import httpx
import pytest
from langchain_core.messages import AIMessage, HumanMessage
from openai import BadRequestError

import app.agent.chains.llm as llm_chains
import app.agent.nodes.intent as intent_nodes
import app.agent.nodes.qualification as qualification_nodes
import app.agent.nodes.response as response_nodes
from app.agent.chains.schemas import (
    AgentResponsePlan,
    GeneratedAudioChoice,
    IntentClassification,
    LeadQualificationAssessment,
    OutboundMediaChoice,
    QualificationCriterionAssessment,
)
from app.agent.messages import has_sensitive_multimodal_content, message_to_text, serialize_messages
from app.agent.specialists import SpecialistResult
from app.core.config import get_settings
from app.outbound_media import OUTBOUND_MEDIA_CATALOG_UNAVAILABLE_TEXT, OutboundMediaAsset

delegate_nodes = importlib.import_module("app.agent.nodes.delegate_specialist")


@pytest.fixture(autouse=True)
def local_response_style(monkeypatch) -> None:
    monkeypatch.setattr(response_nodes, "_get_response_style", lambda: "Use WhatsApp style.")
    monkeypatch.setattr(
        response_nodes,
        "_get_available_media_prompt_view",
        lambda: OUTBOUND_MEDIA_CATALOG_UNAVAILABLE_TEXT,
    )


def _unsupported_temperature_error() -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "message": (
                    "Unsupported value: 'temperature' does not support 0.0 with this "
                    "model. Only the default (1) value is supported."
                ),
                "type": "invalid_request_error",
                "param": "temperature",
                "code": "unsupported_value",
            }
        },
    )
    return BadRequestError(
        "temperature not supported",
        response=response,
        body=response.json()["error"],
    )


def _unsupported_file_error() -> BadRequestError:
    request = httpx.Request("POST", "https://api.openai.com/v1/responses")
    response = httpx.Response(
        400,
        request=request,
        json={
            "error": {
                "message": "Unsupported file type: application/vnd.pf-excel.",
                "type": "invalid_request_error",
                "param": "messages[1].content[1].file",
                "code": "unsupported_file",
            }
        },
    )
    return BadRequestError(
        "unsupported file",
        response=response,
        body=response.json()["error"],
    )


def test_classify_intent_returns_structured_update(monkeypatch) -> None:
    expected_config = {"callbacks": ["trace"]}

    class FakeClassifierChain:
        def invoke(self, payload, config=None):
            assert payload == {"latest_user_message": "Oi, tudo bem?"}
            assert config == expected_config
            return IntentClassification(
                intent="greeting",
                reason="A mensagem e uma saudacao simples.",
            )

    monkeypatch.setattr(intent_nodes, "_build_classifier_chain", lambda: FakeClassifierChain())

    result = intent_nodes.classify_intent(
        {"messages": [HumanMessage(content="Oi, tudo bem?")]},
        config=expected_config,
    )

    assert result == {
        "latest_user_message": "Oi, tudo bem?",
        "intent": "greeting",
        "intent_reason": "A mensagem e uma saudacao simples.",
        "requires_specialist": False,
        "specialist_name": None,
        "specialist_reason": None,
        "status": "classified",
    }


def test_classify_intent_can_request_test_specialist(monkeypatch) -> None:
    class FakeClassifierChain:
        def invoke(self, payload, config=None):
            return IntentClassification(
                intent="request",
                reason="Usuario pediu analise especialista.",
                requires_specialist=True,
                specialist_name="test_specialist",
                specialist_reason="Pedido explicito de especialista.",
            )

    monkeypatch.setattr(intent_nodes, "_build_classifier_chain", lambda: FakeClassifierChain())

    result = intent_nodes.classify_intent(
        {"messages": [HumanMessage(content="roda um teste com especialista")]}
    )

    assert result["intent"] == "request"
    assert result["requires_specialist"] is True
    assert result["specialist_name"] == "test_specialist"
    assert result["specialist_reason"] == "Pedido explicito de especialista."


def test_qualify_lead_requires_all_five_confirmed_criteria(monkeypatch) -> None:
    input_message = HumanMessage(
        content=(
            "Tenho uma loja de fardamentos, preciso repor scrubs este mes, tenho verba "
            "reservada e eu decido a compra."
        )
    )
    confirmed = QualificationCriterionAssessment(
        status="confirmed",
        evidence="Confirmado pelo lead.",
    )

    class FakeQualificationChain:
        def invoke(self, payload, config=None):
            assert payload["conversation_history"] == [
                {"role": "user", "content": input_message.content}
            ]
            return LeadQualificationAssessment(
                profile="retailer_reseller",
                segment_fit=confirmed,
                real_need=confirmed,
                purchase_intent=confirmed,
                plausible_plan=confirmed,
                decision_access=confirmed,
                next_question="Esta pergunta deve ser descartada.",
                reason="Todos os criterios possuem evidencia.",
            )

    monkeypatch.setattr(
        qualification_nodes,
        "_build_qualification_chain",
        lambda: FakeQualificationChain(),
    )

    result = qualification_nodes.qualify_lead(
        {"messages": [input_message], "latest_user_message": input_message.content}
    )

    qualification = result["lead_qualification"]
    assert qualification["status"] == "qualified"
    assert qualification["missing_criteria"] == []
    assert qualification["contradicted_criteria"] == []
    assert qualification["next_question"] is None


def test_qualify_lead_keeps_missing_evidence_as_qualifying(monkeypatch) -> None:
    confirmed = QualificationCriterionAssessment(
        status="confirmed",
        evidence="A lead informou que administra uma clinica de estetica.",
    )
    missing = QualificationCriterionAssessment(status="missing")

    class FakeQualificationChain:
        def invoke(self, payload, config=None):
            return LeadQualificationAssessment(
                profile="healthcare_professional",
                segment_fit=confirmed,
                real_need=confirmed,
                purchase_intent=missing,
                plausible_plan=missing,
                decision_access=missing,
                reason="O segmento e a necessidade estao claros, mas faltam dados de compra.",
            )

    monkeypatch.setattr(
        qualification_nodes,
        "_build_qualification_chain",
        lambda: FakeQualificationChain(),
    )

    result = qualification_nodes.qualify_lead(
        {
            "messages": [HumanMessage(content="Tenho uma clinica e preciso de uniformes.")],
            "latest_user_message": "Tenho uma clinica e preciso de uniformes.",
        }
    )

    qualification = result["lead_qualification"]
    assert qualification["status"] == "qualifying"
    assert qualification["missing_criteria"] == [
        "purchase_intent",
        "plausible_plan",
        "decision_access",
    ]
    assert qualification["next_question"] == (
        "Você está buscando comprar agora ou planejando uma reposição?"
    )


def test_qualify_lead_marks_explicit_contradiction_as_not_qualified(monkeypatch) -> None:
    contradicted = QualificationCriterionAssessment(
        status="contradicted",
        evidence="A pessoa informou que nao atua nos segmentos atendidos.",
    )
    missing = QualificationCriterionAssessment(status="missing")

    class FakeQualificationChain:
        def invoke(self, payload, config=None):
            return LeadQualificationAssessment(
                profile="other",
                segment_fit=contradicted,
                real_need=missing,
                purchase_intent=missing,
                plausible_plan=missing,
                decision_access=missing,
                next_question="Pergunta ignorada para lead nao qualificado.",
                reason="Ha contradicao explicita no criterio de segmento.",
            )

    monkeypatch.setattr(
        qualification_nodes,
        "_build_qualification_chain",
        lambda: FakeQualificationChain(),
    )

    result = qualification_nodes.qualify_lead(
        {
            "messages": [HumanMessage(content="Nao atuo com uniformes, saude ou estetica.")],
            "latest_user_message": "Nao atuo com uniformes, saude ou estetica.",
        }
    )

    qualification = result["lead_qualification"]
    assert qualification["status"] == "not_qualified"
    assert qualification["contradicted_criteria"] == ["segment_fit"]
    assert qualification["next_question"] is None


def test_respond_appends_ai_message(monkeypatch) -> None:
    expected_config = {"callbacks": ["trace"]}
    input_message = HumanMessage(content="Me ajuda com isso.")
    output_message = AIMessage(content="Posso ajudar com uma resposta neutra.")

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            assert payload["intent"] == "request"
            assert payload["latest_user_message"] == "Me ajuda com isso."
            assert payload["conversation_history"] == [input_message]
            assert payload["specialist_result"] is None
            assert payload["specialist_context"] == "No specialist result."
            assert payload["response_style"] == "Use WhatsApp style."
            assert config == expected_config
            return output_message

    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Me ajuda com isso.",
            "intent": "request",
            "intent_reason": "O usuario pediu ajuda.",
            "status": "classified",
        },
        config=expected_config,
    )

    assert result["latest_user_message"] == "Me ajuda com isso."
    assert result["response_text"] == "Posso ajudar com uma resposta neutra."
    assert result["status"] == "responded"
    assert len(result["messages"]) == 1
    assert result["messages"][0] is output_message


def test_respond_passes_specialist_result_to_chain(monkeypatch) -> None:
    input_message = HumanMessage(content="Analisa isso com especialista.")
    specialist_result = {
        "status": "completed",
        "summary": "Pedido analisado.",
        "response_guidance": "Responder com proximo passo curto.",
        "extracted_fields": {"topic": "teste"},
        "confidence": 0.87,
        "error_code": None,
    }

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            assert payload["specialist_result"] == specialist_result
            assert '"summary":"Pedido analisado."' in payload["specialist_context"]
            return AIMessage(content="Resposta baseada no especialista.")

    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Analisa isso com especialista.",
            "intent": "request",
            "specialist_result": specialist_result,
        },
    )

    assert result["response_text"] == "Resposta baseada no especialista."


def test_respond_accepts_structured_response_without_media(monkeypatch) -> None:
    input_message = HumanMessage(content="Oi")

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            assert payload["available_media"] == OUTBOUND_MEDIA_CATALOG_UNAVAILABLE_TEXT
            assert payload["conversation_history"] == [input_message]
            return AgentResponsePlan(response_text="Oi! Posso ajudar?", media_choices=[])

    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Oi",
            "intent": "greeting",
        }
    )

    assert result["response_text"] == "Oi! Posso ajudar?"
    assert result["response_media"] == []
    assert isinstance(result["messages"][0], AIMessage)
    assert result["messages"][0].content == "Oi! Posso ajudar?"


def test_respond_accepts_generated_audio_plan(monkeypatch) -> None:
    input_message = HumanMessage(content="Me explica por audio.")

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            return AgentResponsePlan(
                response_text="Te mandei um audio explicando melhor.",
                generated_audio=GeneratedAudioChoice(
                    text=(
                        "Funciona assim: primeiro eu entendo seu caso e depois te passo "
                        "o proximo passo."
                    ),
                    reason="Usuario pediu explicacao por audio.",
                ),
            )

    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Me explica por audio.",
            "intent": "request",
        }
    )

    assert result["response_text"] == "Te mandei um audio explicando melhor."
    assert result["response_audio"] == {
        "text": ("Funciona assim: primeiro eu entendo seu caso e depois te passo o proximo passo."),
        "reason": "Usuario pediu explicacao por audio.",
    }


def test_respond_keeps_valid_outbound_media_choice(monkeypatch) -> None:
    input_message = HumanMessage(content="Me manda o catalogo.")
    media_asset = OutboundMediaAsset(
        id="catalogo-pdf",
        type="document",
        title="Catalogo PDF",
        description="Catalogo comercial resumido.",
        when_to_use="Quando o usuario pedir o catalogo.",
        media_url="https://cdn.example.com/catalogo.pdf",
        content_type="application/pdf",
        filename="catalogo.pdf",
        enabled=True,
    )

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            assert "https://cdn.example.com" not in payload["available_media"]
            return AgentResponsePlan(
                response_text="Claro, segue o catalogo.",
                media_choices=[
                    OutboundMediaChoice(
                        media_id="catalogo-pdf",
                        caption="Catalogo em PDF",
                        reason="Usuario pediu o catalogo.",
                    )
                ],
            )

    monkeypatch.setattr(
        response_nodes,
        "_get_available_media_prompt_view",
        lambda: '{"media_id":"catalogo-pdf","type":"document"}',
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {"catalogo-pdf": media_asset},
    )
    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Me manda o catalogo.",
            "intent": "request",
        }
    )

    assert result["response_text"] == "Claro, segue o catalogo."
    assert result["response_media"] == [
        {
            "media_id": "catalogo-pdf",
            "type": "document",
            "caption": "Catalogo em PDF",
            "reason": "Usuario pediu o catalogo.",
            "content_type": "application/pdf",
            "filename": "catalogo.pdf",
        }
    ]
    assert "media_url" not in str(result["response_media"])


def test_respond_injects_delivery_context_for_requested_audio_media(monkeypatch) -> None:
    input_message = HumanMessage(
        content="Boa tarde, consegue me mandar um audio apresentando as coisas?"
    )
    media_asset = OutboundMediaAsset(
        id="audio_apresentacao_produto",
        type="audio",
        title="Audio de apresentacao do produto",
        description="Audio curto de apresentacao do produto.",
        when_to_use="Quando o lead pedir uma apresentacao rapida por audio.",
        media_url="https://cdn.example.com/apresentacao-produto.ogg",
        content_type="audio/ogg",
        filename="apresentacao-produto.ogg",
        enabled=True,
    )

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            delivery_context = payload["conversation_history"][0]
            assert delivery_context.type == "system"
            assert "Do not say you cannot send media" in delivery_context.content
            assert "audio_apresentacao_produto" in delivery_context.content
            assert "media_url" not in delivery_context.content
            assert "https://cdn.example.com" not in delivery_context.content
            assert payload["conversation_history"][1] is input_message
            return AgentResponsePlan(
                response_text="Boa tarde! Te mando um audio rapidinho.",
                media_choices=[
                    OutboundMediaChoice(
                        media_id="audio_apresentacao_produto",
                        caption=None,
                        reason="Usuario pediu audio de apresentacao.",
                    )
                ],
                generated_audio=GeneratedAudioChoice(
                    text="Este audio gerado nao deve ser enviado.",
                    reason="Catalog audio already satisfies the request.",
                ),
            )

    monkeypatch.setattr(
        response_nodes,
        "_get_available_media_prompt_view",
        lambda: (
            '{"media_id":"audio_apresentacao_produto","type":"audio",'
            '"title":"Audio de apresentacao do produto",'
            '"description":"Audio curto de apresentacao do produto.",'
            '"when_to_use":"Quando o lead pedir uma apresentacao rapida por audio."}'
        ),
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {"audio_apresentacao_produto": media_asset},
    )
    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": input_message.content,
            "intent": "request",
        }
    )

    assert result["response_text"] == "Boa tarde! Te mando um audio rapidinho."
    assert result["response_media"][0]["media_id"] == "audio_apresentacao_produto"
    assert result["response_media"][0]["type"] == "audio"
    assert result["response_audio"] is None


def test_respond_infers_explicit_monthly_image_when_model_omits_media_choice(
    monkeypatch,
) -> None:
    input_message = HumanMessage(content="Me manda a imagem dos preços mensais.")
    media_asset = OutboundMediaAsset(
        id="planos-mensais",
        type="image",
        title="Planos mensais",
        description="Imagem com preços mensais.",
        when_to_use="Quando o usuário pedir valores do plano mensal em imagem.",
        media_url="https://cdn.example.com/planos-mensais.png",
        content_type="image/png",
        filename="planos-mensais.png",
        enabled=True,
    )

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            return AgentResponsePlan(
                response_text="Claro, segue a imagem.",
                media_choices=[],
                generated_audio=GeneratedAudioChoice(
                    text="Também posso explicar os valores por áudio.",
                    reason="Complemento falado.",
                ),
            )

    monkeypatch.setattr(
        response_nodes,
        "_get_available_media_prompt_view",
        lambda: '{"media_id":"planos-mensais","type":"image"}',
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {"planos-mensais": media_asset},
    )
    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": input_message.content,
            "intent": "request",
        }
    )

    assert result["response_media"][0]["media_id"] == "planos-mensais"
    assert result["response_media"][0]["type"] == "image"
    assert result["response_audio"] == {
        "text": "Também posso explicar os valores por áudio.",
        "reason": "Complemento falado.",
    }


def test_respond_infers_catalog_audio_after_invalid_model_choice_and_suppresses_tts(
    monkeypatch,
) -> None:
    input_message = HumanMessage(content="Pode mandar o áudio de apresentação?")
    media_asset = OutboundMediaAsset(
        id="audio-apresentacao",
        type="audio",
        title="Áudio de apresentação",
        description="Apresentação geral em áudio.",
        when_to_use="Quando o usuário pedir um áudio de apresentação.",
        media_url="https://cdn.example.com/apresentacao.ogg",
        content_type="audio/ogg",
        filename="apresentacao.ogg",
        enabled=True,
    )

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            return AgentResponsePlan(
                response_text="Claro, vou mandar.",
                media_choices=[
                    OutboundMediaChoice(
                        media_id="inexistente",
                        reason="Escolha inválida do modelo.",
                    )
                ],
                generated_audio=GeneratedAudioChoice(
                    text="Este áudio dinâmico não deve ser enviado.",
                    reason="Catálogo já contém o áudio.",
                ),
            )

    monkeypatch.setattr(
        response_nodes,
        "_get_available_media_prompt_view",
        lambda: '{"media_id":"audio-apresentacao","type":"audio"}',
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {"audio-apresentacao": media_asset},
    )
    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": input_message.content,
            "intent": "request",
        }
    )

    assert result["response_media"][0]["media_id"] == "audio-apresentacao"
    assert result["response_audio"] is None


def test_catalog_media_inference_prefers_default_plan_without_period(monkeypatch) -> None:
    default_asset = OutboundMediaAsset(
        id="planos-padrao",
        type="document",
        title="Planos disponíveis",
        description="Resumo dos planos.",
        when_to_use="Quando pedirem preços sem indicar periodicidade.",
        media_url="https://cdn.example.com/planos.pdf",
        content_type="application/pdf",
        filename="planos.pdf",
        enabled=True,
    )
    monthly_asset = default_asset.model_copy(
        update={
            "id": "planos-mensais",
            "title": "Planos mensais",
            "when_to_use": "Quando pedirem preços mensais.",
            "media_url": "https://cdn.example.com/planos-mensais.pdf",
            "filename": "planos-mensais.pdf",
        }
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {
            default_asset.id: default_asset,
            monthly_asset.id: monthly_asset,
        },
    )

    choice = response_nodes._infer_catalog_media_choice("Quais são os preços dos planos?")

    assert choice is not None
    assert choice.media_id == "planos-padrao"


def test_catalog_media_inference_rejects_ambiguous_or_mismatched_requests(monkeypatch) -> None:
    annual_asset = OutboundMediaAsset(
        id="anual-a",
        type="image",
        title="Plano anual A",
        description="Imagem anual.",
        when_to_use="Quando pedirem plano anual.",
        media_url="https://cdn.example.com/anual-a.png",
        content_type="image/png",
        filename="anual-a.png",
        enabled=True,
    )
    second_annual_asset = annual_asset.model_copy(
        update={
            "id": "anual-b",
            "media_url": "https://cdn.example.com/anual-b.png",
            "filename": "anual-b.png",
        }
    )
    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {
            annual_asset.id: annual_asset,
            second_annual_asset.id: second_annual_asset,
        },
    )

    assert response_nodes._infer_catalog_media_choice("Manda a imagem anual") is None
    assert response_nodes._infer_catalog_media_choice("Manda imagem ou PDF anual") is None
    assert response_nodes._infer_catalog_media_choice("Manda a imagem mensal ou anual") is None

    monkeypatch.setattr(
        response_nodes,
        "get_enabled_outbound_media_by_id",
        lambda: {annual_asset.id: annual_asset},
    )
    assert response_nodes._infer_catalog_media_choice("Manda a imagem mensal") is None
    assert response_nodes._infer_catalog_media_choice("Tudo bem por aí?") is None


def test_respond_discards_unknown_outbound_media_choice(monkeypatch) -> None:
    input_message = HumanMessage(content="Me manda algo.")
    fake_logger = type(
        "FakeLogger",
        (),
        {
            "records": [],
            "warning": lambda self, message, *args, **kwargs: self.records.append(
                (message, kwargs.get("extra") or {})
            ),
        },
    )()

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            return AgentResponsePlan(
                response_text="Nao tenho esse material aqui.",
                media_choices=[
                    OutboundMediaChoice(
                        media_id="inventado",
                        caption="Arquivo",
                        reason="Escolha invalida.",
                    )
                ],
            )

    monkeypatch.setattr(response_nodes, "LOGGER", fake_logger)
    monkeypatch.setattr(response_nodes, "get_enabled_outbound_media_by_id", lambda: {})
    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Me manda algo.",
            "intent": "request",
        }
    )

    assert result["response_media"] == []
    assert fake_logger.records == [
        (
            "agent.outbound_media.ignored",
            {
                "pipeline_step": "agent.outbound_media.ignored",
                "media_id": "inventado",
                "reason": "unknown_or_disabled_media",
            },
        )
    ]


def test_classify_intent_retries_without_temperature(monkeypatch) -> None:
    calls: list[bool] = []

    class FakeClassifierChain:
        def __init__(self, *, should_fail: bool) -> None:
            self.should_fail = should_fail

        def invoke(self, payload, config=None):
            calls.append(self.should_fail)
            assert payload == {"latest_user_message": "Oi, tudo bem?"}
            assert config == {"callbacks": ["trace"]}
            if self.should_fail:
                raise _unsupported_temperature_error()
            return IntentClassification(
                intent="greeting",
                reason="A mensagem e uma saudacao simples.",
            )

    monkeypatch.setattr(
        intent_nodes,
        "_build_classifier_chain",
        lambda *, use_custom_temperature=True: FakeClassifierChain(
            should_fail=use_custom_temperature
        ),
    )

    result = intent_nodes.classify_intent(
        {"messages": [HumanMessage(content="Oi, tudo bem?")]},
        config={"callbacks": ["trace"]},
    )

    assert calls == [True, False]
    assert result["intent"] == "greeting"
    assert result["status"] == "classified"


def test_respond_retries_without_temperature(monkeypatch) -> None:
    calls: list[bool] = []
    input_message = HumanMessage(content="Me ajuda com isso.")
    output_message = AIMessage(content="Posso ajudar com uma resposta neutra.")

    class FakeResponderChain:
        def __init__(self, *, should_fail: bool) -> None:
            self.should_fail = should_fail

        def invoke(self, payload, config=None):
            calls.append(self.should_fail)
            assert payload["conversation_history"] == [input_message]
            assert config == {"callbacks": ["trace"]}
            if self.should_fail:
                raise _unsupported_temperature_error()
            return output_message

    monkeypatch.setattr(
        response_nodes,
        "_build_responder_chain",
        lambda *, use_custom_temperature=True: FakeResponderChain(
            should_fail=use_custom_temperature
        ),
    )

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": "Me ajuda com isso.",
            "intent": "request",
            "intent_reason": "O usuario pediu ajuda.",
            "status": "classified",
        },
        config={"callbacks": ["trace"]},
    )

    assert calls == [True, False]
    assert result["response_text"] == "Posso ajudar com uma resposta neutra."
    assert result["messages"][0] is output_message


def test_respond_retries_with_text_only_history_when_file_block_is_rejected(monkeypatch) -> None:
    calls: list[list[object]] = []
    input_message = HumanMessage(
        content=[
            {"type": "text", "text": "Tipo de mensagem: file\nArquivo recebido: relatorio.xls."},
            {
                "type": "file",
                "base64": "very-sensitive-file-base64",
                "mime_type": "application/vnd.pf-excel",
                "filename": "relatorio.xls",
            },
        ]
    )

    class FakeResponderChain:
        def invoke(self, payload, config=None):
            calls.append(payload["conversation_history"])
            assert config == {"callbacks": ["trace"]}
            if len(calls) == 1:
                raise _unsupported_file_error()

            assert payload["conversation_history"] == [
                {
                    "role": "user",
                    "content": (
                        "Tipo de mensagem: file\nArquivo recebido: relatorio.xls.\n"
                        "[file mime_type=application/vnd.pf-excel]"
                    ),
                }
            ]
            assert "very-sensitive-file-base64" not in payload["conversation_history"][0]["content"]
            return AIMessage(content="Recebi o arquivo, mas preciso do conteudo em texto.")

    monkeypatch.setattr(response_nodes, "_build_responder_chain", lambda: FakeResponderChain())

    result = response_nodes.respond(
        {
            "messages": [input_message],
            "latest_user_message": (
                "Tipo de mensagem: file\nArquivo recebido: relatorio.xls.\n"
                "[file mime_type=application/vnd.pf-excel]"
            ),
            "intent": "request",
        },
        config={"callbacks": ["trace"]},
    )

    assert len(calls) == 2
    assert calls[0] == [input_message]
    assert result["response_text"] == "Recebi o arquivo, mas preciso do conteudo em texto."


def test_latest_user_message_prefers_last_human_message() -> None:
    latest_message = intent_nodes._latest_user_message(
        {
            "messages": [
                HumanMessage(content="Oi"),
                AIMessage(content="Como posso ajudar?"),
            ]
        }
    )

    assert latest_message == "Oi"


def test_latest_user_message_supports_protocol_dict_messages() -> None:
    latest_message = intent_nodes._latest_user_message(
        {
            "messages": [
                {"type": "human", "content": "Oi pelo protocolo"},
                {"type": "ai", "content": "Resposta anterior"},
            ]
        }
    )

    assert latest_message == "Oi pelo protocolo"


def test_multimodal_messages_are_serialized_without_binary_payload() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Tipo de mensagem: image\nArquivo recebido: imagem."},
            {
                "type": "image",
                "base64": "very-sensitive-base64",
                "mime_type": "image/jpeg",
            },
        ]
    )

    text = message_to_text(message)
    serialized = serialize_messages([message])

    assert text == (
        "Tipo de mensagem: image\nArquivo recebido: imagem.\n[image mime_type=image/jpeg]"
    )
    assert "very-sensitive-base64" not in text
    assert serialized == [
        {
            "role": "user",
            "content": (
                "Tipo de mensagem: image\nArquivo recebido: imagem.\n[image mime_type=image/jpeg]"
            ),
        }
    ]
    assert "very-sensitive-base64" not in serialized[0]["content"]


def test_file_messages_are_serialized_without_binary_payload() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Tipo de mensagem: file\nArquivo recebido: contrato.pdf."},
            {
                "type": "file",
                "base64": "very-sensitive-file-base64",
                "mime_type": "application/pdf",
                "filename": "contrato.pdf",
            },
        ]
    )

    text = message_to_text(message)
    serialized = serialize_messages([message])

    assert text == (
        "Tipo de mensagem: file\nArquivo recebido: contrato.pdf.\n[file mime_type=application/pdf]"
    )
    assert "very-sensitive-file-base64" not in text
    assert "contrato.pdf" in text
    assert serialized == [
        {
            "role": "user",
            "content": (
                "Tipo de mensagem: file\nArquivo recebido: contrato.pdf.\n"
                "[file mime_type=application/pdf]"
            ),
        }
    ]
    assert "very-sensitive-file-base64" not in serialized[0]["content"]


def test_sensitive_multimodal_content_is_detected() -> None:
    safe_message = HumanMessage(content="oi")
    file_message = HumanMessage(
        content=[
            {"type": "text", "text": "Tipo de mensagem: file"},
            {
                "type": "file",
                "base64": "very-sensitive-file-base64",
                "mime_type": "application/pdf",
            },
        ]
    )

    assert has_sensitive_multimodal_content([safe_message]) is False
    assert has_sensitive_multimodal_content([file_message]) is True


def test_delegate_specialist_skips_when_feature_flag_is_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "false")
    get_settings.cache_clear()

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [HumanMessage(content="usa especialista")],
            "latest_user_message": "usa especialista",
            "intent": "request",
            "requires_specialist": True,
            "specialist_name": "test_specialist",
        },
        config={"configurable": {"thread_id": "thread-1"}},
    )

    assert result["specialist_status"] == "skipped"
    assert result["specialist_name"] == "test_specialist"
    assert result["specialist_result"]["error_code"] == "openai_specialists_disabled"
    get_settings.cache_clear()


def test_delegate_specialist_normalizes_known_alias_when_feature_flag_is_disabled(
    monkeypatch,
) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "false")
    get_settings.cache_clear()

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [HumanMessage(content="usa especialista")],
            "latest_user_message": "usa especialista",
            "intent": "request",
            "requires_specialist": True,
            "specialist_name": "testing/deep agent",
        },
    )

    assert result["specialist_name"] == "test_specialist"
    assert result["specialist_status"] == "skipped"
    assert result["specialist_result"]["error_code"] == "openai_specialists_disabled"
    get_settings.cache_clear()


def test_delegate_specialist_fails_unknown_specialist_before_sdk(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "true")
    get_settings.cache_clear()

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [HumanMessage(content="usa especialista")],
            "latest_user_message": "usa especialista",
            "intent": "request",
            "requires_specialist": True,
            "specialist_name": "unknown specialist",
        },
    )

    assert result["specialist_name"] == "unknown specialist"
    assert result["specialist_status"] == "failed"
    assert result["specialist_result"]["error_code"] == "specialist_unknown"
    get_settings.cache_clear()


def test_delegate_specialist_runs_mocked_runner_when_enabled(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "true")
    monkeypatch.setenv("OPENAI_SPECIALIST_MAX_TURNS", "3")
    get_settings.cache_clear()
    captured: dict[str, object] = {}

    def fake_run_specialist(*, specialist_name, request, settings):
        captured["specialist_name"] = specialist_name
        captured["request"] = request
        captured["max_turns"] = settings.openai_specialist_max_turns
        return SpecialistResult(
            status="completed",
            summary="Resumo interno.",
            response_guidance="Use o resumo.",
            extracted_fields={"kind": "test"},
            confidence=0.9,
        )

    monkeypatch.setattr(delegate_nodes, "_run_specialist", fake_run_specialist)

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [HumanMessage(content="usa especialista")],
            "latest_user_message": "usa especialista",
            "intent": "request",
            "intent_reason": "Pedido explicito.",
            "requires_specialist": True,
            "specialist_name": "test_specialist",
            "specialist_reason": "Rodar analise especializada.",
        },
        config={"configurable": {"thread_id": "thread-1"}},
    )

    request = captured["request"]
    assert captured["specialist_name"] == "test_specialist"
    assert captured["max_turns"] == 3
    assert request.latest_user_message == "usa especialista"
    assert request.objective == "Rodar analise especializada."
    assert result["specialist_status"] == "completed"
    assert result["specialist_result"]["extracted_fields"] == {"kind": "test"}
    get_settings.cache_clear()


def test_delegate_specialist_records_failed_result(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "true")
    get_settings.cache_clear()

    def fake_run_specialist(*, specialist_name, request, settings):
        return SpecialistResult(
            status="failed",
            summary="Falhou.",
            response_guidance="Continue sem especialista.",
            error_code="openai_specialist_error",
        )

    monkeypatch.setattr(delegate_nodes, "_run_specialist", fake_run_specialist)

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [HumanMessage(content="usa especialista")],
            "latest_user_message": "usa especialista",
            "intent": "request",
            "requires_specialist": True,
            "specialist_name": "test_specialist",
        },
    )

    assert result["specialist_status"] == "failed"
    assert result["specialist_result"]["error_code"] == "openai_specialist_error"
    get_settings.cache_clear()


def test_delegate_specialist_handles_invalid_request(monkeypatch) -> None:
    monkeypatch.setenv("OPENAI_SPECIALISTS_ENABLED", "true")
    get_settings.cache_clear()

    result = delegate_nodes.delegate_specialist(
        {
            "messages": [],
            "intent": "request",
            "requires_specialist": True,
            "specialist_name": "test_specialist",
        },
    )

    assert result["specialist_status"] == "failed"
    assert result["specialist_result"]["error_code"] == "specialist_request_invalid"
    get_settings.cache_clear()


def test_specialist_request_uses_safe_serialized_history() -> None:
    message = HumanMessage(
        content=[
            {"type": "text", "text": "Arquivo recebido."},
            {
                "type": "image",
                "base64": "very-sensitive-base64",
                "mime_type": "image/jpeg",
            },
        ]
    )

    request = delegate_nodes._build_specialist_request(
        {
            "messages": [message],
            "latest_user_message": "Arquivo recebido.\n[image mime_type=image/jpeg]",
            "intent": "request",
        }
    )

    serialized_request = request.model_dump_json()
    assert "very-sensitive-base64" not in serialized_request
    assert "downloadUrl" not in serialized_request
    assert "[image mime_type=image/jpeg]" in serialized_request


def test_gpt5_models_skip_custom_temperature(monkeypatch) -> None:
    captured_kwargs = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setenv("OPENAI_MODEL", "gpt-5.3-chat-latest")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_chains, "ChatOpenAI", FakeChatOpenAI)
    get_settings.cache_clear()

    llm_chains.get_chat_model(temperature=0.3)

    assert captured_kwargs == {
        "model": "gpt-5.3-chat-latest",
        "api_key": "sk-test",
    }
    get_settings.cache_clear()


def test_non_gpt5_models_keep_custom_temperature(monkeypatch) -> None:
    captured_kwargs = {}

    class FakeChatOpenAI:
        def __init__(self, **kwargs) -> None:
            captured_kwargs.update(kwargs)

    monkeypatch.setenv("OPENAI_MODEL", "gpt-4.1-mini")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setattr(llm_chains, "ChatOpenAI", FakeChatOpenAI)
    get_settings.cache_clear()

    llm_chains.get_chat_model(temperature=0.3)

    assert captured_kwargs == {
        "model": "gpt-4.1-mini",
        "api_key": "sk-test",
        "temperature": 0.3,
    }
    get_settings.cache_clear()
