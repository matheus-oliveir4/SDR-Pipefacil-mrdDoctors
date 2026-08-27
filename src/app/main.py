from __future__ import annotations

import gzip
import json
import logging
import time
import zlib
from collections.abc import Mapping, Sequence
from contextlib import asynccontextmanager
from typing import Any
from urllib.parse import urlparse

from fastapi import FastAPI, Request, status
from fastapi.encoders import jsonable_encoder
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from app.agent import AgentGraphRuntime, build_runtime
from app.api.router import build_api_router
from app.application.idempotency import (
    InMemoryMessageIdempotencyStore,
    MessageIdempotencyStore,
)
from app.core import RuntimeConfigurationError, configure_logging, get_settings
from app.integrations.postgres_idempotency import PostgresMessageIdempotencyStore
from app.observability import flush_langfuse, warm_up_langfuse

LOGGER = logging.getLogger(__name__)
MESSAGE_RECEIVED_PATH = "/events/message-received"
MAX_VALIDATION_LOG_ITEMS = 8
MAX_VALIDATION_BODY_SHAPE_ITEMS = 80
MAX_VALIDATION_BODY_SHAPE_DEPTH = 5
QUIET_HTTP_PATHS = {"/health", "/ready", "/docs", "/openapi.json"}
RAW_REQUEST_BODY_SCOPE_KEY = "sdr_pipefacil_raw_request_body"
DECODED_REQUEST_BODY_SCOPE_KEY = "sdr_pipefacil_decoded_request_body"


class RequestBodyDecodeError(ValueError):
    pass


def _is_production_environment(app_env: str) -> bool:
    return app_env.strip().lower() == "production"


def _validate_startup_settings(settings) -> None:
    is_production = _is_production_environment(settings.app_env)
    if is_production and not (settings.pipefacil_api_key or "").strip():
        raise RuntimeConfigurationError("PIPEFACIL_API_KEY is required when APP_ENV=production.")

    if is_production and not settings.pipefacil_webhook_signature_enabled:
        raise RuntimeConfigurationError(
            "PIPEFACIL_WEBHOOK_SIGNATURE_ENABLED must remain true when APP_ENV=production."
        )

    if is_production and not (settings.pipefacil_webhook_signature_secret or "").strip():
        raise RuntimeConfigurationError(
            "PIPEFACIL_WEBHOOK_SIGNATURE_SECRET is required when APP_ENV=production."
        )

    if settings.generated_audio_enabled:
        if not (settings.elevenlabs_api_key or "").strip():
            raise RuntimeConfigurationError(
                "ELEVENLABS_API_KEY is required when GENERATED_AUDIO_ENABLED=true."
            )
        if not (settings.elevenlabs_voice_id or "").strip():
            raise RuntimeConfigurationError(
                "ELEVENLABS_VOICE_ID is required when GENERATED_AUDIO_ENABLED=true."
            )
        public_base_url = _generated_audio_public_base_url(settings)
        if not public_base_url:
            raise RuntimeConfigurationError(
                "GENERATED_AUDIO_PUBLIC_BASE_URL or CLOUDFLARE_TUNNEL_HOSTNAME is required "
                "when GENERATED_AUDIO_ENABLED=true."
            )
        parsed_url = urlparse(public_base_url)
        if parsed_url.scheme != "https" or not parsed_url.netloc:
            raise RuntimeConfigurationError(
                "Generated audio public base URL must be absolute HTTPS when "
                "GENERATED_AUDIO_ENABLED=true."
            )


def _generated_audio_public_base_url(settings) -> str | None:
    configured_url = (settings.generated_audio_public_base_url or "").strip()
    if configured_url:
        return configured_url

    hostname = (settings.cloudflare_tunnel_hostname or "").strip()
    if hostname:
        return hostname if "://" in hostname else f"https://{hostname}"

    return None


def _build_pipefacil_message_idempotency_store(
    runtime: AgentGraphRuntime,
) -> MessageIdempotencyStore:
    if runtime.database_pool is None:
        return InMemoryMessageIdempotencyStore()

    store = PostgresMessageIdempotencyStore(
        runtime.database_pool,
        schema=runtime.database_schema,
    )
    store.setup()
    return store


def _route_path(request: Request) -> str:
    return getattr(request.scope.get("route"), "path", request.url.path)


def _validation_error_path(error: dict[str, Any]) -> str:
    location = error.get("loc", ())
    if isinstance(location, list | tuple):
        return ".".join(str(part) for part in location)
    return str(location)


def _validation_error_values(
    errors: list[dict[str, Any]],
    *,
    key: str,
) -> list[str]:
    values: list[str] = []
    for error in errors[:MAX_VALIDATION_LOG_ITEMS]:
        value = error.get(key)
        if value is not None:
            values.append(str(value))
    return values


def _validation_error_locations(errors: list[dict[str, Any]]) -> list[str]:
    return [_validation_error_path(error) for error in errors[:MAX_VALIDATION_LOG_ITEMS]]


def _json_type_name(value: Any) -> str:
    if isinstance(value, Mapping):
        return "object"
    if isinstance(value, list):
        return "array"
    if isinstance(value, str):
        return "string"
    if isinstance(value, bool):
        return "boolean"
    if isinstance(value, int | float):
        return "number"
    if value is None:
        return "null"
    return type(value).__name__


def _json_key_paths(
    value: Any,
    *,
    prefix: str = "",
    depth: int = 0,
    paths: list[str] | None = None,
) -> list[str]:
    resolved_paths = paths if paths is not None else []
    if len(resolved_paths) >= MAX_VALIDATION_BODY_SHAPE_ITEMS:
        return resolved_paths
    if depth >= MAX_VALIDATION_BODY_SHAPE_DEPTH:
        return resolved_paths

    if isinstance(value, Mapping):
        for key in sorted(str(item_key) for item_key in value):
            path = f"{prefix}.{key}" if prefix else key
            resolved_paths.append(path)
            if len(resolved_paths) >= MAX_VALIDATION_BODY_SHAPE_ITEMS:
                return resolved_paths
            _json_key_paths(
                value.get(key),
                prefix=path,
                depth=depth + 1,
                paths=resolved_paths,
            )
        return resolved_paths

    if isinstance(value, Sequence) and not isinstance(value, str | bytes | bytearray):
        if not value:
            return resolved_paths
        path = f"{prefix}[]" if prefix else "[]"
        resolved_paths.append(path)
        if len(resolved_paths) >= MAX_VALIDATION_BODY_SHAPE_ITEMS:
            return resolved_paths
        return _json_key_paths(
            value[0],
            prefix=path,
            depth=depth + 1,
            paths=resolved_paths,
        )

    return resolved_paths


def _validation_body_shape(payload: Any) -> dict[str, Any]:
    context: dict[str, Any] = {
        "request_json_root_type": _json_type_name(payload),
        "request_json_key_paths": _json_key_paths(payload),
    }
    if isinstance(payload, Mapping):
        data = payload.get("data")
        if isinstance(data, Mapping):
            context["request_json_data_keys"] = sorted(str(key) for key in data)
    return context


async def _request_validation_body_shape(request: Request) -> dict[str, Any]:
    body = request.scope.get(DECODED_REQUEST_BODY_SCOPE_KEY)
    if not isinstance(body, bytes):
        body = request.scope.get(RAW_REQUEST_BODY_SCOPE_KEY)
    if not isinstance(body, bytes):
        try:
            body = await request.body()
        except RuntimeError:
            return {"request_json_unavailable": True}

    if not body:
        return {"request_json_root_type": "empty"}

    try:
        payload = json.loads(body)
    except json.JSONDecodeError:
        return {"request_json_root_type": "invalid_json"}

    return _validation_body_shape(payload)


def _should_log_http_request(*, path: str, status_code: int) -> bool:
    if path in QUIET_HTTP_PATHS:
        return False

    return path.startswith("/events/") or status_code >= 400


def _http_request_log_context(request: Request) -> dict[str, Any]:
    return {
        "http_method": request.method,
        "http_path": request.url.path,
        "content_type": request.headers.get("content-type"),
        "content_encoding": request.headers.get("content-encoding"),
        "content_length": request.headers.get("content-length"),
        "user_agent": request.headers.get("user-agent"),
    }


def _scope_header_value(scope: dict[str, Any], header_name: str) -> str | None:
    expected_name = header_name.lower().encode("latin-1")
    for name, value in scope.get("headers", ()):
        if name.lower() == expected_name:
            return value.decode("latin-1")

    return None


def _scope_header_names(scope: dict[str, Any]) -> list[str]:
    return sorted(name.decode("latin-1").lower() for name, _ in scope.get("headers", ()))


def _http_scope_log_context(scope: dict[str, Any]) -> dict[str, Any]:
    return {
        "http_method": scope.get("method"),
        "http_path": scope.get("path"),
        "content_type": _scope_header_value(scope, "content-type"),
        "content_encoding": _scope_header_value(scope, "content-encoding"),
        "content_length": _scope_header_value(scope, "content-length"),
        "user_agent": _scope_header_value(scope, "user-agent"),
    }


def _scope_content_encodings(scope: dict[str, Any]) -> tuple[str, ...]:
    content_encoding = _scope_header_value(scope, "content-encoding")
    if not content_encoding:
        return ()

    return tuple(
        encoding.strip().lower() for encoding in content_encoding.split(",") if encoding.strip()
    )


def _decode_request_body(raw_body: bytes, encodings: tuple[str, ...]) -> bytes:
    decoded_body = raw_body
    for encoding in reversed(encodings):
        if encoding == "identity":
            continue
        if encoding in {"gzip", "x-gzip"}:
            try:
                decoded_body = gzip.decompress(decoded_body)
            except OSError as exc:
                raise RequestBodyDecodeError("Could not decompress gzip request body.") from exc
            continue
        if encoding == "deflate":
            try:
                decoded_body = zlib.decompress(decoded_body)
            except zlib.error as exc:
                raise RequestBodyDecodeError("Could not decompress deflate request body.") from exc
            continue

        raise RequestBodyDecodeError(f"Unsupported request body content encoding: {encoding}.")

    return decoded_body


async def _read_asgi_body(receive) -> bytes:
    body = b""
    more_body = True
    while more_body:
        message = await receive()
        if message["type"] != "http.request":
            continue
        body += message.get("body", b"")
        more_body = message.get("more_body", False)

    return body


def _asgi_body_receiver(body: bytes):
    sent = False

    async def receive() -> dict[str, Any]:
        nonlocal sent
        if sent:
            return {
                "type": "http.request",
                "body": b"",
                "more_body": False,
            }

        sent = True
        return {
            "type": "http.request",
            "body": body,
            "more_body": False,
        }

    return receive


class EventRequestMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope: dict[str, Any], receive, send) -> None:
        if scope.get("type") != "http":
            await self.app(scope, receive, send)
            return

        start = time.perf_counter()
        http_path = str(scope.get("path") or "")
        should_log_started = http_path.startswith("/events/")

        if should_log_started:
            LOGGER.info(
                "http.request.started",
                extra={
                    **_http_scope_log_context(scope),
                    "request_header_names": _scope_header_names(scope),
                },
            )

        encodings = _scope_content_encodings(scope)
        downstream_receive = receive
        if encodings:
            raw_body = await _read_asgi_body(receive)
            try:
                decoded_body = _decode_request_body(raw_body, encodings)
            except RequestBodyDecodeError as exc:
                duration_ms = round((time.perf_counter() - start) * 1000, 2)
                LOGGER.warning(
                    "http.request.body_decode_failed",
                    extra={
                        **_http_scope_log_context(scope),
                        "duration_ms": duration_ms,
                        "error_code": "request_body_decode_failed",
                        "status_code": status.HTTP_400_BAD_REQUEST,
                    },
                )
                response = JSONResponse(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    content={"detail": str(exc)},
                )
                await response(scope, downstream_receive, send)
                LOGGER.info(
                    "http.request.completed",
                    extra={
                        **_http_scope_log_context(scope),
                        "status_code": status.HTTP_400_BAD_REQUEST,
                        "duration_ms": duration_ms,
                    },
                )
                return

            scope[RAW_REQUEST_BODY_SCOPE_KEY] = raw_body
            scope[DECODED_REQUEST_BODY_SCOPE_KEY] = decoded_body
            downstream_receive = _asgi_body_receiver(decoded_body)

        response_status_code: int | None = None

        async def send_wrapper(message: dict[str, Any]) -> None:
            nonlocal response_status_code
            if message["type"] == "http.response.start":
                response_status_code = int(message["status"])
            await send(message)

        try:
            await self.app(scope, downstream_receive, send_wrapper)
        except Exception:
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            LOGGER.exception(
                "http.request.failed",
                extra={
                    **_http_scope_log_context(scope),
                    "duration_ms": duration_ms,
                    "error_code": "http_request_failed",
                },
            )
            raise

        status_code = response_status_code or status.HTTP_500_INTERNAL_SERVER_ERROR
        if _should_log_http_request(path=http_path, status_code=status_code):
            duration_ms = round((time.perf_counter() - start) * 1000, 2)
            LOGGER.info(
                "http.request.completed",
                extra={
                    **_http_scope_log_context(scope),
                    "status_code": status_code,
                    "duration_ms": duration_ms,
                },
            )


def create_app() -> FastAPI:
    settings = get_settings()
    configure_logging(settings)
    is_production = _is_production_environment(settings.app_env)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        LOGGER.info(
            "Application startup started.",
            extra={
                "app_env": settings.app_env,
                "app_version": settings.app_version,
            },
        )
        _validate_startup_settings(settings)
        warm_up_langfuse()
        runtime = build_runtime(settings)
        try:
            idempotency_store = _build_pipefacil_message_idempotency_store(runtime)
        except Exception:
            runtime.close()
            raise
        app.state.graph_runtime = runtime
        app.state.graph = runtime.graph
        app.state.checkpointer = runtime.checkpointer
        app.state.pipefacil_message_idempotency_store = idempotency_store
        if isinstance(idempotency_store, InMemoryMessageIdempotencyStore):
            LOGGER.warning(
                "pipefacil.webhook.idempotency_memory_store",
                extra={
                    "pipeline_step": "pipefacil.webhook.idempotency_memory_store",
                    "pipefacil_idempotency_store": type(idempotency_store).__name__,
                    "pipefacil_idempotency_scope": "process",
                    "pipefacil_idempotency_restart_safe": False,
                    "pipefacil_idempotency_multi_replica_safe": False,
                },
            )
        LOGGER.info(
            "Application startup completed.",
            extra={
                "app_env": settings.app_env,
                "app_version": settings.app_version,
                "checkpointer": type(runtime.checkpointer).__name__,
                "pipefacil_idempotency_store": type(idempotency_store).__name__,
                "pipefacil_webhook_signature_enabled": (
                    settings.pipefacil_webhook_signature_enabled
                ),
                "pipefacil_webhook_signature_header": (settings.pipefacil_webhook_signature_header),
                "pipefacil_webhook_signature_has_secret": bool(
                    (settings.pipefacil_webhook_signature_secret or "").strip()
                ),
            },
        )

        try:
            yield
        finally:
            runtime.close()
            flush_langfuse()
            LOGGER.info("Application shutdown completed.")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        lifespan=lifespan,
        docs_url=None if is_production else "/docs",
        redoc_url=None if is_production else "/redoc",
        openapi_url=None if is_production else "/openapi.json",
    )
    app.add_middleware(EventRequestMiddleware)

    @app.exception_handler(Exception)
    async def handle_unexpected_exception(request: Request, exc: Exception) -> JSONResponse:
        LOGGER.exception(
            "Unhandled application error.",
            extra={
                "http_method": request.method,
                "http_path": _route_path(request),
                "status_code": status.HTTP_500_INTERNAL_SERVER_ERROR,
                "error_code": "unhandled_application_error",
            },
            exc_info=exc,
        )
        return JSONResponse(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            content={"detail": "Internal Server Error"},
        )

    @app.exception_handler(RequestValidationError)
    async def handle_request_validation_error(
        request: Request,
        exc: RequestValidationError,
    ) -> JSONResponse:
        errors = exc.errors()
        http_path = _route_path(request)
        pipeline_step = (
            "pipefacil.webhook.validation_failed"
            if http_path == MESSAGE_RECEIVED_PATH
            else "http.request.validation_failed"
        )
        log_extra = {
            "pipeline_step": pipeline_step,
            "error_code": "request_validation_error",
            "http_method": request.method,
            "http_path": http_path,
            "content_type": request.headers.get("content-type"),
            "content_length": request.headers.get("content-length"),
            "status_code": status.HTTP_422_UNPROCESSABLE_CONTENT,
            "validation_error_count": len(errors),
            "validation_error_locations": _validation_error_locations(errors),
            "validation_error_types": _validation_error_values(errors, key="type"),
        }
        if http_path == MESSAGE_RECEIVED_PATH:
            log_extra.update(await _request_validation_body_shape(request))

        LOGGER.warning(
            pipeline_step,
            extra=log_extra,
        )
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
            content={"detail": jsonable_encoder(errors)},
        )

    app.state.settings = settings
    app.include_router(build_api_router(include_internal_routes=not is_production))
    return app


app = create_app()
