# SDR Pipefacil

<p align="center">
  <img src="docs/assets/sdr-pipefacil-hero-v2.jpg" alt="Pipefacil virtual SDR agent powered by Python, LangGraph, and Langfuse" width="100%">
</p>

Official Pipefacil template for SDR agents integrated with the Pipefacil CRM.

This base provides an HTTP runtime with `FastAPI`, conversational orchestration with
`LangGraph`, observability and prompt management with `Langfuse`, inbound/outbound
integration with the Pipefacil public API, and short-term memory persisted by `thread_id`.

The goal is to serve as a starting point for sales agents, SDRs, lead triage,
qualification, assisted support, and automations connected to Pipefacil, while keeping a
clear separation between API, graph, business rules, integrations, and observability.

## What This Repository Provides

- HTTP API for chat, webhooks, health checks, and state lookup.
- LangGraph graph with separate nodes for classification and response.
- Short-term conversation memory using `thread_id`.
- In-memory checkpointer by default, with optional Postgres support.
- Pipefacil integration to receive messages and send replies.
- WhatsApp-ready `response_messages` derived from the canonical `response_text`.
- Ordered `response_parts` for Insomnia/debug, including outbound media selected by ID.
- Versioned outbound media catalog for images, videos, audio, and documents.
- Versioned prompts in Langfuse.
- Tests for the API, application, runtime, graph, observability, and Pipefacil integration.
- Docker Compose for a self-hosted production environment.

## Stack

- `FastAPI` as the application's HTTP runtime.
- `LangGraph` to model the agent flow.
- `LangChain + OpenAI` in nodes that use an LLM.
- `Langfuse` for traces, callbacks, and versioned prompts.
- Optional `PostgresSaver` for persistent checkpointing.
- `langgraph dev` only for Studio and local visual debugging.

## Structure

```text
src/app/
  api/              HTTP routes, schemas, and FastAPI dependencies
  agent/            State, prompts, nodes, graph, runtime, and agent service
  application/      Application use cases
  core/             Environment-loaded settings
  integrations/     External clients, contracts, and mappings
  outbound_media/    Versioned outbound media catalog and safe prompt views
  observability/    Langfuse, callbacks, and trace flushing

docs/               Internal architecture and best-practice guides
scripts/            Bootstraps and operational scripts
tests/              Automated tests
```

## Create an Agent for a New Client

Use GitHub's **Use this template** action so the client receives an independent repository
without inheriting this template's Git history. Do not start by cloning this repository and
pushing back to its `origin`.

From the GitHub UI:

1. Open this repository and select **Use this template**.
2. Create a private repository named `sdr-<client>`.
3. Clone the new repository into its own local folder.

Equivalent GitHub CLI command:

```bash
gh repo create cardosolucass96/sdr-<client> \
  --private \
  --template cardosolucass96/sdr-pipefacil \
  --clone
```

Before the first deploy, give the client a unique `app_name` and `app_slug` in `.agent.json`,
`LANGGRAPH_CHECKPOINT_SCHEMA`, webhook secret, Pipefacil key, and deployment URL. Use a
separate Langfuse project per client; if projects must be shared, rename the canonical prompt
prefixes before bootstrapping so one client cannot move another client's `production` label.
Keep client credentials only in ignored `.env.*.local` files or in the deployment platform.

## Getting Started

Create the virtual environment and install dependencies:

```bash
make install
```

The `.env.dev`, `.env.staging`, and `.env.prod` files are versioned with safe environment
configuration. Universal non-secret agent defaults live in [`.agent.json`](.agent.json).
For real keys, tokens, and secrets, create a local override ignored by Git:

```bash
cp .env.example .env.dev.local
```

For local development with `langgraph dev`:

```bash
make dev
```

This command uses [`langgraph.json`](langgraph.json)
and loads `.env.dev` together with `.env.dev.local`, when it exists.

## Environments

- `dev`: uses `.env.dev` + `.env.dev.local`, `APP_ENV=development`, and prompt label `staging`.
- `staging`: uses `.env.staging` + `.env.staging.local`, `APP_ENV=staging`, and prompt label `staging`.
- `prod`: uses `.env.prod` + `.env.prod.local`, `APP_ENV=production`, and prompt label `production`.

File convention:

- `.env.example`: catalog of variables and placeholders.
- `.env.dev`, `.env.staging`, `.env.prod`: infrastructure and selected per-environment
  overrides, without real secrets.
- `.env`, `.env.local`, `.env.*.local`: local overrides ignored by Git.

The versioned environment files keep `DATABASE_URL=` empty on purpose, so a runtime such as
staging does not accidentally inherit a local `.env` database URL. Put real Postgres
credentials in the matching ignored override, for example `.env.staging.local`.

Never put a real key, token, HMAC secret, or database credential in versioned files. In a
managed deployment, prefer registering secrets in the platform dashboard.

Main commands:

```bash
make dev          # Local LangGraph Studio/runtime
make staging      # Local FastAPI + Cloudflare Tunnel
make staging-app  # FastAPI only with staging env
make prod         # Docker Compose with prod env
```

## Agent Configuration

The versioned [`.agent.json`](.agent.json) is the typed source of truth for universal,
non-secret defaults such as Pipefacil limits, generated-audio policy, ElevenLabs tuning,
OpenAI models, and the Langfuse user-ID mode. After changing it, regenerate and validate the
committed Python module:

```bash
make agent-config
make agent-config-check
```

The application imports only the generated module at runtime, so the Docker image does not
need to locate `.agent.json`. Configuration precedence remains: explicit `Settings` argument,
environment variable, then generated default. Never add credentials, tokens, passwords, or
signing secrets to `.agent.json`; its strict schema rejects secret-like keys.

To stop the Docker stack:

```bash
make compose-down
```

## Deployment

The recommended path for containerized deployment is the
[`Dockerfile`](Dockerfile).

Platforms such as Coolify may choose Nixpacks automatically. For that case, the repo
versions [`nixpacks.toml`](nixpacks.toml), ensuring
that `README.md` and `src/` exist during `pip install .` and that the container starts with:

```bash
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

With `APP_ENV=production`, the app does not register `/chat`, `/threads/{id}/state`, Swagger,
ReDoc, or OpenAPI routes. Health, readiness, generated media, and the signed Pipefacil
webhook remain available. Production startup requires signature validation to be enabled and
`PIPEFACIL_WEBHOOK_SIGNATURE_SECRET` to be configured.

## Main Variables

Environment and secret variables live in the base `.env.*` files and local `.env.*.local`
overrides. Agent defaults listed below may instead come from `.agent.json`; every existing
environment variable name remains a valid runtime override. Use [`.env.example`](.env.example)
as the deployment-variable reference.

- `APP_ENV`: defines the application environment.
- `app_name` and `app_slug` in `.agent.json`: service identity used by the API, health
  checks, OpenAPI, logs, and Langfuse.
- `APP_VERSION`: service version also included in the Pipefacil client User-Agent.
- `OPENAI_API_KEY`: key used by nodes with LLM calls.
- `OPENAI_MODEL`: OpenAI model used by the agent.
- `OPENAI_TRANSCRIPTION_MODEL`: OpenAI model used to transcribe inbound audio.
- `OPENAI_SPECIALISTS_ENABLED`: enables delegation to OpenAI Agents SDK specialists.
- `OPENAI_SPECIALIST_MODEL`: optional specialist model; when empty, uses `OPENAI_MODEL`.
- `OPENAI_SPECIALIST_MAX_TURNS`: turn limit for the specialist runner.
- `PIPEFACIL_BASE_URL`: Pipefacil API host.
- `PIPEFACIL_API_KEY`: key used to send messages through the Pipefacil public API.
  Required when `APP_ENV=production`.
- `pipefacil.conversation_history_path` in `.agent.json`: GET endpoint used to load
  conversation history for `POST /conversations/resume`. Default: `/api/v1/messages`.
  Override with `PIPEFACIL_CONVERSATION_HISTORY_PATH` when the Pipefacil deployment uses a
  different path.
- `PIPEFACIL_TIMEOUT_SECONDS`: timeout for HTTP calls to the Pipefacil API and downloads.
- `PIPEFACIL_MEDIA_MAX_BYTES`: maximum inbound media download size. Default:
  `25000000`.
- `PIPEFACIL_WEBHOOK_IDEMPOTENCY_TTL_SECONDS`: deduplication window for inbound messages.
  Default: `86400` (24 hours); `0` disables idempotency. Postgres is used when
  `DATABASE_URL` is configured, otherwise the guarantee is local to the current process.
- `PIPEFACIL_AI_ATTENDANCE_FIELD_SLUG`: Pipefacil deal custom field slug used to gate AI
  replies. Default: `atendimento_por_ia`. If the field is explicitly disabled (`false`,
  `0`, `nao`, `off`, `desligado`, etc.), the webhook skips the SDR response. Empty or
  enabled values allow the agent to reply. An absent field or a lookup failure other than
  `404` defaults to enabled; an empty slug disables this optional gate.
- `PIPEFACIL_MAX_TOKENS_PER_LEAD`: maximum persisted conversation tokens per lead before
  the webhook stops the SDR response. Default: `0` disables this limit.
- `PIPEFACIL_WEBHOOK_SIGNATURE_ENABLED`: enables inbound webhook signature validation.
  Default: `true`. Production refuses to start when it is disabled.
- `PIPEFACIL_WEBHOOK_SIGNATURE_SECRET`: HMAC-SHA256 secret used to validate inbound
  webhooks. Required when `APP_ENV=production`.
- `PIPEFACIL_WEBHOOK_SIGNATURE_HEADER`: HTTP header that carries the signature. Default:
  `X-Pipefacil-Signature-256`.
- `OUTBOUND_MEDIA_CATALOG_PATH`: optional path to a JSON outbound media catalog. When
  empty, the app uses the versioned default at `src/app/outbound_media/catalog.json`.
- `GENERATED_AUDIO_ENABLED`: enables dynamic outbound audio replies with ElevenLabs.
  Default: `false`.
- `GENERATED_AUDIO_AUTO_ENABLED`: enables the legacy length-based audio fallback. Keep it
  `false` so the responder chooses text, audio, or a hybrid reply according to the content.
- `GENERATED_AUDIO_AUTO_MIN_CHARS`: minimum canonical response length used only when
  `GENERATED_AUDIO_AUTO_ENABLED=true`. Default: `650`.
- `GENERATED_AUDIO_MAX_CHARS`: maximum spoken script size sent to ElevenLabs. Default:
  `1200`.
- `GENERATED_AUDIO_PUBLIC_BASE_URL`: public HTTPS base URL for this app to serve generated
  audio files to Pipefacil/WhatsApp. When empty, `CLOUDFLARE_TUNNEL_HOSTNAME` is used as
  `https://<hostname>`.
- `audio.storage_dir` in `.agent.json`: local temporary directory for generated audio files.
- `GENERATED_AUDIO_TTL_SECONDS`: how long generated audio files remain available.
- `GENERATED_AUDIO_AUTO_TEXT`: short intro used before automatically generated audio.
- `GENERATED_AUDIO_CONVERT_TO_OGG_OPUS`: legacy compatibility switch for converting generated
  speech with `ffmpeg`. The default TTS format is already direct Ogg/Opus, so keep this
  `false`; FFmpeg remains required for inbound audio transcription.
- `ELEVENLABS_API_KEY`: ElevenLabs API credential.
- `elevenlabs.voice_id` and `elevenlabs.model_id` in `.agent.json`: ElevenLabs voice and
  model. Use a Brazilian Portuguese voice ID selected from your workspace or voice library.
- `ELEVENLABS_BASE_URL`, `ELEVENLABS_OUTPUT_FORMAT`, `ELEVENLABS_TIMEOUT_SECONDS`: provider
  endpoint, source audio format, and per-attempt HTTP timeout.
- `ELEVENLABS_MAX_ATTEMPTS`: total attempts for transport errors, HTTP `429`, and HTTP
  `5xx`. Default: `2`; permanent `4xx` responses are not retried.
- `ELEVENLABS_RETRY_BACKOFF_SECONDS`: delay before the single retry. Default: `0.5`.
- `ELEVENLABS_VOICE_STABILITY`, `ELEVENLABS_VOICE_SIMILARITY_BOOST`, and
  `ELEVENLABS_VOICE_STYLE`: optional ElevenLabs voice controls. The template defaults are
  `0.45`, `0.85`, and `0.35` for a more natural but still consistent voice.
- `ELEVENLABS_VOICE_USE_SPEAKER_BOOST` and `ELEVENLABS_VOICE_SPEED`: optional speaker
  boost and speech-speed controls. Defaults: `true` and `1.0`.
- `DATABASE_URL`: optional Postgres connection for persistent checkpoints. JDBC-style
  `jdbc:postgresql://...` URLs are accepted and normalized for psycopg. Remote Postgres
  instances that require authentication must include user and password in the URL.
- `LANGGRAPH_CHECKPOINT_SCHEMA`: optional Postgres schema for LangGraph checkpoint
  tables. Use one schema per client/repo when several SDR agents share the same database.
- `LANGGRAPH_CHECKPOINT_POOL_MIN_SIZE`: minimum number of open checkpointer pool
  connections when Postgres is enabled. Default: `1`.
- `LANGGRAPH_CHECKPOINT_POOL_MAX_SIZE`: maximum number of checkpointer pool connections
  when Postgres is enabled. Default: `10`.
- `LANGGRAPH_CHECKPOINT_POOL_TIMEOUT_SECONDS`: startup, checkout, and reconnect timeout
  for the checkpointer pool. Default: `10`.
- `LANGFUSE_ENABLED`: enables remote tracing and prompt management.
- `LANGFUSE_PUBLIC_KEY`, `LANGFUSE_SECRET_KEY`, and `LANGFUSE_BASE_URL`: Langfuse
  credentials and host.
- `LANGFUSE_TRACING_ENVIRONMENT`: environment sent to traces.
- `LANGFUSE_PROMPT_LABEL`: label used to fetch remote prompts.
- `LANGFUSE_DEBUG`: enables Langfuse SDK debug logs.
- `LANGFUSE_PIPEFACIL_USER_ID_MODE`: Langfuse user identity policy for Pipefacil traces.
  Default `contact_id` emits `contact:<id>` without PII. The explicit opt-in
  `contact_name_phone` emits a recognizable value of at most 200 characters and preserves
  only that `user.id`; phone, email, credentials and media remain masked elsewhere.
- `LOG_LEVEL`: minimum log level.
- `LOG_FORMAT`: `json` or `text`; by default, production uses `json` and other
  environments use `text`.
- `LOG_INBOUND_PAYLOADS`: when `true`, logs the validated inbound payload with sensitive
  media sanitized, without `downloadUrl` or raw files.
- `CLOUDFLARE_TUNNEL_*`: configuration for the tunnel used in local staging.
  `CLOUDFLARE_TUNNEL_HOSTNAME` has no versioned default and must be set in the client's
  ignored local env before running `make staging`.

## API

Available endpoints:

- `GET /health`
- `GET /ready`
- `GET /generated-audio/{filename}`
- `POST /chat`
- `POST /conversations/resume`
- `GET /threads/{thread_id}/state`
- `POST /events/message-received`

`GET /health` is a simple liveness check. `GET /ready` verifies that the runtime loaded the
graph and checkpointer and, when `DATABASE_URL` is configured, validates Postgres
connectivity plus the configured checkpoint schema. The Docker `HEALTHCHECK` uses
`/ready`.

`POST /chat` receives `thread_id` in the request body. This value is used as the Langfuse
`session_id` and as the LangGraph memory key. The response keeps `response_text` as the
canonical reply, returns `response_messages` as the deterministic WhatsApp text split, and
returns `response_parts` as the ordered delivery/debug plan.

`POST /conversations/resume` loads the conversation history from the configured Pipefacil
endpoint, runs the same LangGraph flow, and optionally sends the generated response through
Pipefacil. Use `context` for internal operational guidance that should influence the next
reply without being treated as a lead message. The endpoint accepts `deal_seq`, `deal_id`,
`contact_id`, or `channel_id` as the history filter and requires `thread_id` for LangGraph
memory. `history_limit` accepts 1 to 500 messages and defaults to `100`.
`send_response` defaults to `true`; set it to `false` for a dry run.

Example:

```json
{
  "thread_id": "deal-example-001",
  "deal_seq": 100,
  "recipient_phone": "+5511000000001",
  "sender_phone_number_id": "111111111111111",
  "context": "Faz 3 dias que ele nao responde e ficou de passar o cartao.",
  "send_response": true
}
```

The resume endpoint uses the same HMAC webhook signature validation as the inbound webhook.

`POST /events/message-received` receives the inbound Pipefacil payload, normalizes `text`,
`image`, `sticker`, `audio`, and file messages, runs the agent, derives `response_parts`,
and sends each part back in order. Text and outbound media both use `POST /api/v1/messages`
with the catalog `mediaLink` resolved only in the application/integration boundary.
When generated audio is enabled, the responder chooses text for exact/copyable information,
audio for spoken explanations, or a hybrid reply containing both. The optional legacy
length rule runs only when `GENERATED_AUDIO_AUTO_ENABLED=true`. For audio and hybrid replies,
the webhook sends the useful text portion first, then an `audio` media part backed by a
temporary public URL under `/generated-audio/...`.
If generation fails, explicit audio requests fall back to the spoken script as text, while
automatic generation keeps the original text reply.
Images and stickers are sent to the LLM as multimodal content blocks. Files/documents,
including PDFs, are sent as `file` content blocks with `mime_type` and `filename`, respecting
`PIPEFACIL_MEDIA_MAX_BYTES`. `audio/ogg` audio is converted with `ffmpeg`, transcribed, and
sent as text with `Message type: audio` and the transcript.

After the webhook is authenticated and its local payload checks pass, the endpoint returns
HTTP `200` with `status=accepted`. The remaining work runs in a FastAPI background task, in
this order:

1. A contact without `deal` is treated as an internal Pipefacil contact and produces
   `contact_without_lead_ignored`. No deal lookup is attempted.
2. The message is claimed by `event + channel + externalId/id`. A repeated delivery produces
   `duplicate_message_ignored`. Controlled outcomes, including outbound failure, keep the
   claim; only unexpected exceptions release it.
3. For an existing lead, the custom field configured in
   `PIPEFACIL_AI_ATTENDANCE_FIELD_SLUG` is checked. Only an explicitly false/disabled value
   blocks the agent. If the field is absent, the application fetches
   `/api/v1/deals/{seq}`; `404` is treated as a contact without lead, while other lookup
   failures default to enabled.

With `DATABASE_URL`, idempotency uses `pipefacil_webhook_idempotency` in the same configured
schema and shares the LangGraph connection pool. Without a database it uses memory: process
restart clears claims and multiple replicas do not share them, so production deployments
that need a distributed guarantee should configure Postgres.

If `PIPEFACIL_MAX_TOKENS_PER_LEAD` is greater than zero, the webhook then reads the latest
LangGraph thread state for the lead and estimates the persisted conversation tokens plus the
current inbound message. When the total reaches the configured limit, the application stops
before media normalization, does not call the SDR, does not send an outbound message, and
attempts to set the same Pipefacil custom field to `false` through `PATCH /api/v1/deals/{seq}`
using the `customFields` payload.
If that CRM update fails, the lead is still blocked from receiving an AI response and the
failure is logged.

The integration also exposes the application use case
`move_pipefacil_deal_stage(deal_seq, target_stage_id)` for client-specific workflows. It
validates and sends an explicit target stage, but this base defines no default stage,
endpoint, LLM tool or automatic movement.

Stickers are treated as WebP images. If a sticker is animated, this version does not extract
frames or describe the full motion; it is still sent to the model as an image.

Not every model accepts every file type. The inbound flow downloads and forwards any
attachment within the configured limit, but the model may reply that it cannot read a
specific format.

In the Dockerfile and Nixpacks setup, `ffmpeg` is installed by the image/build. In local
execution outside these paths, the binary must be available in `PATH` to transcribe audio.

When `PIPEFACIL_WEBHOOK_SIGNATURE_ENABLED=true` and
`PIPEFACIL_WEBHOOK_SIGNATURE_SECRET` is configured, the endpoint requires an HMAC-SHA256
signature of the raw body in the header defined by
`PIPEFACIL_WEBHOOK_SIGNATURE_HEADER`. Hex, base64, and base64url values are accepted, with
or without the `sha256=` prefix. Common webhook headers such as `X-Webhook-Signature`,
`X-Hub-Signature-256`, `X-Signature`, and `X-Hook-Signature` are also accepted. If the
provider sends the secret as a shared token instead of HMAC, `X-Webhook-Secret` and
`Authorization: Bearer ...` are also accepted.

Webhooks under `/events/*` accept bodies with `Content-Encoding: gzip` or `deflate`. The
application stores the raw body for signature validation and sends the decompressed body to
the JSON parser.

Webhook response semantics:

- `200 OK`: the signature, request schema, and IDs passed local validation; for events with a
  deal, the message type and required text are also checked. The body has `status=accepted`,
  while agent and outbound work continue in the background.
- `401 Unauthorized`: the webhook signature is missing or invalid.
- `422 Unprocessable Content`: the request or inbound message failed validation before it
  could be accepted.

The acknowledgement does not report the final outbound result. Inspect
`pipefacil.webhook.processing_completed` and `pipefacil.webhook.processing_failed` logs for
that outcome. Background tasks run in the API process, so an accepted task can be lost if the
process stops before it finishes; use a durable external queue if restart-safe delivery becomes
a requirement.

In `production`, the application fails at startup if `PIPEFACIL_API_KEY` is not
configured, if signature validation is disabled, or if
`PIPEFACIL_WEBHOOK_SIGNATURE_SECRET` is not configured.

### Insomnia

Import [`docs/api/openapi.json`](docs/api/openapi.json) into Insomnia to test the API
manually. Regenerate it after API changes with:

```bash
make openapi
```

See [`docs/api/insomnia.md`](docs/api/insomnia.md) for local environment setup, example
payloads, and webhook signature notes.

## Pipefacil Integration

The integration lives in `src/app/integrations/pipefacil`.

- `client.py`: HTTP client for the public API.
- `contracts.py`: expected integration contracts.
- `conversation.py`: normalization of Pipefacil conversation history into chat messages.
- `mapping.py`: translation between Pipefacil payloads and internal DTOs.

The currently recommended host is:

```text
https://pipefacil-server.matchsales.com.br
```

This is a legacy infrastructure hostname retained by the Pipefacil public API; it is not
the CRM's current product name.

## Outbound Media Catalog

Outbound media lives in a versioned JSON catalog at
`src/app/outbound_media/catalog.json`. The default catalog is intentionally empty so the
template does not ship client-specific test assets.

Each entry has `id`, `type`, `title`, `description`, `when_to_use`, `media_url`,
`content_type`, `filename`, and `enabled`.

The responder prompt receives only a safe view: `media_id`, type, title, description, and
when to use it. The LLM never sees `media_url` and cannot send media directly. It returns a
structured plan with `response_text` and `media_choices`; the application validates enabled
IDs, builds `response_parts`, resolves URLs internally, and stops delivery on the first
failed part.

Use [`src/app/outbound_media/catalog.example.json`](src/app/outbound_media/catalog.example.json)
as a starting point and follow
[`docs/catalogo-midias-outbound.md`](docs/catalogo-midias-outbound.md) before enabling real
assets. Only use direct HTTPS file URLs, not storage console/browser URLs. For outbound
audio, use Ogg Opus with `audio/ogg`, mono, 48 kHz, and validate the real delivery before
setting `enabled=true`.

Dynamic generated audio does not need a catalog entry. Set `GENERATED_AUDIO_ENABLED=true`,
configure ElevenLabs, and expose this app through a stable HTTPS base URL. The application
generates speech directly as Ogg Opus, stores it temporarily
under `audio.storage_dir` from `.agent.json`, and passes only the generated URL directly to the
Pipefacil delivery client. The LLM never sees generated audio URLs.

The default storage is local to the application instance. Production deployments must use
a single replica, a shared volume, or routing that guarantees `/generated-audio/...` reaches
the instance that created the file. Distributed object storage is not provided by this base.

## LangGraph

The base graph is in `src/app/agent/graph.py`.

Current flow:

```text
START -> classify-intent -> respond -> END
```

When the classifier explicitly requests an internal specialist, the conditional path is:

```text
START -> classify-intent -> delegate-specialist -> respond -> END
```

Common customization points:

- add qualification nodes;
- query CRM data;
- validate commercial rules;
- record human handoff;
- create actions to change status, tags, tickets, or opportunities in Pipefacil;
- expand the state in `src/app/agent/state.py`.

The agent's internal architecture is documented in
[`docs/arquitetura-agente.md`](docs/arquitetura-agente.md).

Summary of the main subfolders:

- `src/app/agent/nodes/`: fine-grained graph steps.
- `src/app/agent/chains/`: prompts, models, and structured outputs.
- `src/app/agent/prompts/`: Langfuse names and local fallbacks.
- `src/app/agent/tools/`: tools exposed to the agent.

## Persistence

- without `DATABASE_URL`: `InMemorySaver`.
- with `DATABASE_URL`: `PostgresSaver` backed by a psycopg `ConnectionPool`.

Recommended shared Postgres layout:

```env
DATABASE_URL=postgresql://user:password@db.example.com:5432/postgres
LANGGRAPH_CHECKPOINT_SCHEMA=sdr_cliente
```

`postgres` is the database. `sdr_cliente` is the schema that isolates this repo/client's
LangGraph tables from other SDR agents in the same database.

The Postgres checkpointer pool validates a connection before handing it to LangGraph and
applies `LANGGRAPH_CHECKPOINT_SCHEMA` to every new pool connection. This prevents webhook
runs from reusing a stale closed connection after Postgres idle timeouts.

If you want to use Postgres to persist checkpoints, prepare the schema first:

```bash
make db-setup
```

## Langfuse

Versioned prompts used by this base:

- `agent/classifier`
- `agent/responder`
- `agent/style/whatsapp`

These short names are safe when every client has its own Langfuse project. When multiple
clients share one project, change the names to a client-specific namespace before the first
bootstrap; labels such as `production` are unique per prompt name and otherwise one client
could replace another client's active prompt.

The local observability, tracing, labels, and prompt promotion contract is documented in
[`docs/observabilidade-langfuse.md`](docs/observabilidade-langfuse.md).

Prompt bootstrap:

```bash
.venv/bin/python scripts/bootstrap_langfuse_prompts.py \
  --env-file .env.staging \
  --env-file .env.staging.local
```

The script reads the current `staging` version without cache and creates a new version only
when canonical content changed. A successful push to `main` runs the same staging-only sync
after CI quality checks, using the configured GitHub secrets and `LANGFUSE_BASE_URL` variable.
The workflow records the source commit and never moves the `production` label.

Explicit promotion to `production`:

```bash
.venv/bin/python scripts/bootstrap_langfuse_prompts.py \
  --env-file .env.prod \
  --env-file .env.prod.local \
  --promote-production
```

## Tests and Quality

```bash
make test
make lint
make format
make test-cov
make agent-config-check
make pre-commit-install
pre-commit run --all-files
```

The local `pre-commit` hook runs quick file hygiene checks and Ruff with automatic lint
fixes followed by formatting. The GitHub Actions CI runs on Python 3.12 with generated-config
validation, linting, format checking, tests, report-only coverage, and staging prompt sync
after successful pushes to `main`.

## AI Development Context

This template versions documentation context for assistants and editors that support MCP:

- `.mcp.json`
- `.cursor/mcp.json`
- `.vscode/mcp.json`
- `AGENTS.md`

All of them point to the official documentation used by the template:

```text
https://docs.langchain.com/mcp
https://langfuse.com/api/mcp
```

Before changing LangGraph/LangChain or Langfuse, also consult:

```text
https://docs.langchain.com/llms.txt
https://langfuse.com/llms.txt
```

These files are development-only. They are not part of the API runtime or production
dependencies.

Details are available in
[`docs/contexto-desenvolvimento-langgraph.md`](docs/contexto-desenvolvimento-langgraph.md)
and
[`docs/contexto-desenvolvimento-langfuse.md`](docs/contexto-desenvolvimento-langfuse.md).

## Checklist for Creating a New Agent

1. Create a new private repository with **Use this template**; never reuse this `origin`.
2. Adjust `app_name` and `app_slug` in `.agent.json`, plus `APP_VERSION`, deployment URLs,
   and environment variables.
3. Give the client a unique `LANGGRAPH_CHECKPOINT_SCHEMA`.
4. Use a separate Langfuse project or rename prompt namespaces before bootstrapping.
5. Rotate and configure client-specific Pipefacil, webhook, OpenAI, ElevenLabs, Langfuse,
   Postgres, and Cloudflare credentials outside Git.
6. Define the agent's statuses, business rules, escalation rules, and token limits.
7. Expand `AgentState`, nodes, routing, tools, and prompts as required by the client flow.
8. Replace the outbound media catalog and verify every enabled asset with real delivery.
9. Adjust Pipefacil mappings according to the real CRM payload.
10. Regenerate `docs/api/openapi.json`, run the full test suite, and validate staging before
    promoting prompts or deploying production.

Also read:

- [`docs/README.md`](docs/README.md)
- [`docs/arquitetura-aplicacao.md`](docs/arquitetura-aplicacao.md)
- [`docs/arquitetura-agente.md`](docs/arquitetura-agente.md)
- [`docs/organizacao-do-codigo.md`](docs/organizacao-do-codigo.md)
- [`docs/tratamento-de-excecoes.md`](docs/tratamento-de-excecoes.md)
- [`docs/estrutura-langgraph.md`](docs/estrutura-langgraph.md)
- [`docs/boas-praticas-agente.md`](docs/boas-praticas-agente.md)
- [`docs/contexto-desenvolvimento-langgraph.md`](docs/contexto-desenvolvimento-langgraph.md)
- [`docs/contexto-desenvolvimento-langfuse.md`](docs/contexto-desenvolvimento-langfuse.md)
- [`docs/observabilidade-langfuse.md`](docs/observabilidade-langfuse.md)
- [`docs/logging.md`](docs/logging.md)
- [`docs/api/insomnia.md`](docs/api/insomnia.md)
