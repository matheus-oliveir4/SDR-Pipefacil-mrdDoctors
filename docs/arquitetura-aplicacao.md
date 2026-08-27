# Arquitetura da Aplicacao

Este documento descreve como a aplicacao esta organizada hoje, quais sao as camadas
principais e como uma requisicao percorre o sistema.

## Visao geral

O projeto e um scaffold de agente de IA para Pipefacil com quatro blocos principais:

- API HTTP com `FastAPI`;
- fluxo conversacional com `LangGraph`;
- observabilidade e prompts com `Langfuse`;
- integracao inbound e outbound com a API publica do Pipefacil.

O runtime real da aplicacao e a API `FastAPI` em [`src/app/main.py`](../src/app/main.py).
O `langgraph dev` existe para desenvolvimento local e debugging visual, mas nao e o
servidor principal em producao.

## Camadas

### `api`

Responsavel por expor endpoints HTTP, validar payloads e traduzir requests e responses.

Pecas principais:

- [`src/app/api/router.py`](../src/app/api/router.py):
  agrega os routers.
- [`src/app/api/routes/chat.py`](../src/app/api/routes/chat.py):
  endpoint manual de chat.
- [`src/app/api/routes/conversations.py`](../src/app/api/routes/conversations.py):
  endpoint para carregar historico externo e retomar uma conversa.
- [`src/app/api/routes/threads.py`](../src/app/api/routes/threads.py):
  consulta de estado da thread.
- [`src/app/api/routes/webhooks.py`](../src/app/api/routes/webhooks.py):
  entrada de eventos do Pipefacil.
- [`src/app/api/routes/ops.py`](../src/app/api/routes/ops.py):
  liveness e readiness checks.
- [`src/app/api/routes/generated_audio.py`](../src/app/api/routes/generated_audio.py):
  entrega arquivos temporarios de audio por nome opaco.

Regra pratica:

- a camada `api` nao deve conter regra de negocio do agente;
- ela apenas recebe, valida, injeta dependencias e delega.

### `application`

Responsavel por orquestrar casos de uso da aplicacao.

Pecas principais:

- [`src/app/application/chat.py`](../src/app/application/chat.py):
  executa uma rodada de chat e busca estado de thread.
- [`src/app/application/conversations.py`](../src/app/application/conversations.py):
  orquestra a busca do historico Pipefacil, a retomada pelo grafo e a entrega opcional.
- [`src/app/application/pipefacil.py`](../src/app/application/pipefacil.py):
  traduz o webhook inbound em execucao do agente e envio outbound.
- [`src/app/application/idempotency.py`](../src/app/application/idempotency.py):
  define o contrato do store de idempotencia e o fallback atomico em memoria.
- [`src/app/application/pipefacil_deals.py`](../src/app/application/pipefacil_deals.py):
  expoe a movimentacao direcional de deal para uma etapa explicitamente informada.
- [`src/app/application/generated_audio.py`](../src/app/application/generated_audio.py):
  coordena TTS, conversao, armazenamento e consulta do audio temporario.
- [`src/app/application/whatsapp.py`](../src/app/application/whatsapp.py):
  divide a resposta canonica em partes deterministicas para leitura/envio no WhatsApp.
- [`src/app/application/dto.py`](../src/app/application/dto.py):
  resultados estruturados retornados para a API.

Regra pratica:

- a camada `application` coordena chamadas entre agente, integracoes e DTOs;
- ela ainda deve continuar fina, sem esconder regra critica em fluxo opaco.
- formatacao de entrega por canal, como `response_messages`, fica aqui e nao no estado
  LangGraph.

### `agent`

Responsavel pelo estado conversacional, nodes, prompts, cadeias e runtime do grafo.

Pecas principais:

- [`src/app/agent/state.py`](../src/app/agent/state.py):
  schema do estado compartilhado entre nodes.
- [`src/app/agent/nodes/`](../src/app/agent/nodes):
  nodes finos do grafo.
- [`src/app/agent/graph.py`](../src/app/agent/graph.py):
  topologia do fluxo.
- [`src/app/agent/routing.py`](../src/app/agent/routing.py):
  nomes de nodes e funcoes puras de roteamento.
- [`src/app/agent/chains/`](../src/app/agent/chains):
  monta chains LangChain, modelo, structured outputs e fallback de temperatura.
- [`src/app/agent/prompts/`](../src/app/agent/prompts):
  nomes e fallbacks dos prompts.
- [`src/app/agent/tools/`](../src/app/agent/tools):
  tools expostas ao agente.
- [`src/app/agent/specialists/`](../src/app/agent/specialists):
  base para especialistas OpenAI Agents SDK chamados pelo grafo quando necessario.
- [`src/app/agent/service.py`](../src/app/agent/service.py):
  executa o grafo e serializa snapshots.
- [`src/app/agent/runtime.py`](../src/app/agent/runtime.py):
  escolhe o checkpointer e monta o runtime do grafo.

Regra pratica:

- regra de fluxo do agente mora aqui;
- o estado deve carregar dados reutilizaveis, nao texto pronto de prompt;
- nodes devem ser finos e retornar updates parciais de estado;
- chains nao decidem roteamento;
- tools nao devem espalhar `httpx` ou contratos externos dentro do grafo;
- integracoes externas nao devem ficar embutidas dentro dos nodes.
- especialistas podem usar tools, MCPs, handoffs e skills dentro de suas factories, mas
  retornam apenas trabalho estruturado para o responder.

A arquitetura interna do agente esta detalhada em
[`docs/arquitetura-agente.md`](arquitetura-agente.md).

### `integrations`

Responsavel por falar com sistemas externos e mapear contratos.

Pecas principais:

- [`src/app/integrations/pipefacil/contracts.py`](../src/app/integrations/pipefacil/contracts.py):
  contratos Pydantic do webhook.
- [`src/app/integrations/pipefacil/mapping.py`](../src/app/integrations/pipefacil/mapping.py):
  extracao, normalizacao e metadata do payload inbound, incluindo texto, midia e arquivos.
- [`src/app/integrations/pipefacil/client.py`](../src/app/integrations/pipefacil/client.py):
  cliente HTTP para mensagens outbound, deals e download seguro de midia/arquivo inbound.
- [`src/app/integrations/postgres_idempotency.py`](../src/app/integrations/postgres_idempotency.py):
  implementa a reivindicacao atomica de mensagens em Postgres, compartilhando o pool do
  runtime LangGraph.
- [`src/app/integrations/openai_audio.py`](../src/app/integrations/openai_audio.py):
  transcricao de audio inbound via OpenAI.
- [`src/app/integrations/elevenlabs/`](../src/app/integrations/elevenlabs):
  contratos e cliente HTTP de TTS, incluindo retry curto para falhas transitorias.
- [`src/app/integrations/generated_audio/`](../src/app/integrations/generated_audio):
  adaptadores de conversao FFmpeg e armazenamento temporario atomico.

Regra pratica:

- toda conversa com API externa deve passar por `integrations`;
- mapping e cliente devem continuar separados.

### `core` e `observability`

Responsaveis por configuracao transversal e tracing.

Pecas principais:

- [`src/app/core/config.py`](../src/app/core/config.py):
  carrega configuracao via `BaseSettings`.
- [`src/app/core/logging.py`](../src/app/core/logging.py):
  configura logs estruturados da aplicacao.
- [`src/app/observability/langfuse.py`](../src/app/observability/langfuse.py):
  clientes Langfuse, callbacks, prompts e mascaramento de dados sensiveis.

## Fluxos principais

### Fluxo `POST /chat`

1. A rota recebe `thread_id` e `message`.
2. `run_chat_turn()` cria um `HumanMessage`.
3. `run_agent()` injeta `configurable.thread_id`.
4. O grafo executa `classify-intent -> respond`.
5. `run_chat_turn()` deriva `response_messages` a partir de `response_text`.
6. `run_chat_turn()` monta `response_parts`: texto primeiro, midias depois.
7. O resultado volta para a API como `ChatResponse`.

Esse endpoint e o caminho mais simples para testar o agente sem depender do Pipefacil.
Use `response_messages` no Insomnia para visualizar como a resposta seria fatiada no
WhatsApp; use `response_parts` para visualizar o plano ordenado de entrega. `response_text`
continua sendo a resposta canonica.

### Fluxo `POST /events/message-received`

1. `EventRequestMiddleware` registra a borda HTTP de `/events/*` e descompacta body
   `gzip`/`deflate` antes do parser JSON, preservando o corpo bruto para assinatura.
2. A rota valida assinatura, contrato e IDs; quando existe `deal`, tambem valida tipo da
   mensagem e texto obrigatorio, sem acessar rede, midia, LLM ou estado do agente.
3. A rota anexa o processamento a uma `BackgroundTasks`, registra
   `pipefacil.webhook.accepted` e responde imediatamente `200` com `status=accepted`.
4. Depois que a resposta HTTP e enviada, `handle_pipefacil_message_received()` resolve
   `session_id` e `user_id`. Se `deal` nao
   existir, encerra com `contact_without_lead_ignored`, sem lookup, estado, midia, LLM ou
   outbound. Essa regra identifica contatos internos do Pipefacil e sempre tem precedencia.
5. Para um lead existente, a aplicacao reivindica atomicamente a mensagem por
   `event + channel + externalId/id`. Uma chave ja reivindicada encerra com
   `duplicate_message_ignored`. Resultados controlados permanecem gravados; somente uma
   excecao inesperada libera a chave para nova tentativa.
6. A aplicacao verifica o campo configurado em `PIPEFACIL_AI_ATTENDANCE_FIELD_SLUG`
   (padrao: `atendimento_por_ia`). Apenas valor explicitamente falso/desligado bloqueia a
   IA. Campo ausente, vazio ou verdadeiro atende normalmente. Se o webhook nao trouxer o
   campo, a aplicacao busca `/api/v1/deals/{seq}`: `404` equivale a contato sem lead;
   transporte, `5xx` ou outra falha defaultam para atendimento habilitado e geram
   `ai_attendance_default_enabled`. Slug vazio desativa somente esse gate opcional.
7. Se a IA estiver permitida e `PIPEFACIL_MAX_TOKENS_PER_LEAD` for maior que zero, a
   aplicacao soma os tokens estimados do estado persistido do lead com a mensagem atual. Se o
   total atingir o limite, a aplicacao tenta desligar o campo no CRM com
   `PATCH /api/v1/deals/{seq}` e `customFields.<slug>=false`, e o fluxo encerra sem normalizar
   midia, chamar o SDR ou enviar resposta outbound. Se a atualizacao no CRM falhar, a falha e
   registrada em log e o lead continua sem resposta da IA.
8. Se a IA estiver permitida e dentro do limite, a aplicacao normaliza a mensagem inbound.
9. Texto entra como string; imagem, figurinha e arquivo/documento entram como content blocks
   multimodais; audio e baixado, convertido com `ffmpeg`, transcrito e enviado ao agente
   como texto.
10. O agente roda com metadata adicional para tracing, sem `downloadUrl`, base64 ou arquivo
   bruto.
11. A resposta canonica do agente vira `response_messages` deterministicas.
12. O responder escolhe texto para dados exatos/copiaveis, audio para explicacoes faladas ou
   os dois em uma resposta hibrida. Quando `generated_audio` estiver presente, a aplicacao
   gera um audio temporario via ElevenLabs e o insere depois da parte util em texto. A regra
   legada por tamanho so roda com `GENERATED_AUDIO_AUTO_ENABLED=true` e usa o limite de
   `GENERATED_AUDIO_AUTO_MIN_CHARS`. Falhas conhecidas geram fallback textual sem transformar
   o webhook em `500`.
13. As escolhas de midia validadas por ID viram partes `image`, `video`, `audio` ou
   `document` em `response_parts`.
14. Cada parte e enviada em ordem: texto via `send_public_text_message()` e midia via
   `send_whatsapp_media_message()`.
15. Se uma parte falhar, as partes restantes nao sao enviadas e a reivindicacao idempotente
    e mantida para impedir reenvio parcial.
16. O resultado final e registrado em `pipefacil.webhook.processing_completed`; uma excecao
    fica em `pipefacil.webhook.processing_failed` e nao pode mais alterar o `200` ja enviado.

Esse endpoint adiciona responsabilidades extras:

- traducao do payload inbound;
- tratamento recuperavel de midia inbound;
- entrega outbound para o contato no Pipefacil.

### Fluxo `POST /conversations/resume`

1. A rota valida a assinatura HMAC e o contrato com `thread_id` e pelo menos um identificador
   de historico (`deal_seq`, `deal_id`, `contact_id` ou `channel_id`).
2. A integracao consulta o endpoint configurado em
   `pipefacil.conversation_history_path` no `.agent.json` — por padrao `GET /api/v1/messages` — e converte
   as mensagens Pipefacil em `HumanMessage`/`AIMessage` ordenadas.
3. `run_chat_turn_from_history()` substitui as mensagens do checkpoint pela fonte externa
   antes de executar o grafo, evitando duplicar historico quando a thread ja existe.
4. O campo `context` da requisicao vira `resume_context` no estado do agente. Ele e uma
   orientacao interna para a retomada, nao uma mensagem do lead e nao deve aparecer na
   resposta.
5. Com `send_response=true`, o mesmo pipeline de entrega do webhook envia texto, midia e
   audio pelo Pipefacil. Com `false`, a rota funciona como dry run e retorna apenas o
   resultado do agente.

### Extensao direcional de etapa do deal

`move_pipefacil_deal_stage(deal_seq, target_stage_id)` e um caso de uso reutilizavel da
camada `application`. Ele valida os identificadores na integracao e envia
`{"stageId": "<target>"}` para `PATCH /api/v1/deals/{seq}`. A base nao define etapa padrao,
endpoint, tool de LLM ou movimentacao automatica; cada cliente decide quando e para onde
mover o lead sem acoplar essa regra ao grafo base.

Midias outbound sao uma responsabilidade de entrega/canal. O grafo escolhe apenas
`media_id`; a aplicacao valida IDs habilitados, resolve o catalogo completo e nunca expoe
`media_url` no prompt, no `ChatResponse` ou em logs.

O catalogo padrao fica vazio para evitar assets de cliente/teste no template. Para habilitar
midias reais, preencha `src/app/outbound_media/catalog.json` seguindo
[`catalogo-midias-outbound.md`](catalogo-midias-outbound.md).

### Fluxo `GET /generated-audio/{filename}`

1. A rota valida apenas a borda HTTP e delega para `application/generated_audio.py`.
2. A aplicacao consulta o adaptador de armazenamento sem acoplar a API a `integrations`.
3. Nome invalido, arquivo ausente ou expirado responde `404`.
4. Falha operacional inesperada de filesystem responde `500` pelo handler central.

O armazenamento padrao e local. Em producao com mais de uma replica, use volume
compartilhado ou roteamento que leve a leitura para a instancia que criou o arquivo.

### Fluxo `GET /threads/{thread_id}/state`

1. A rota resolve a thread pedida.
2. `fetch_thread_state()` busca o snapshot do grafo.
3. `serialize_thread_state()` transforma o snapshot em payload legivel.
4. A API devolve `404` quando a thread ainda nao existe.

## Ciclo de vida da aplicacao

No startup, a aplicacao:

- carrega settings;
- configura logging;
- valida configuracao obrigatoria de producao;
- aquece o cliente Langfuse quando habilitado;
- constroi o runtime do grafo;
- monta o store de idempotencia e falha o startup se a tabela Postgres nao puder ser
  preparada;
- expoe `graph`, `checkpointer`, store de idempotencia e `settings` em `app.state`.

No shutdown, a aplicacao:

- fecha recursos do runtime;
- faz flush do Langfuse.

Esse ciclo esta centralizado em [`src/app/main.py`](../src/app/main.py).

## Persistencia e memoria

O projeto usa memoria curta por `thread_id`.

Comportamento atual:

- sem `DATABASE_URL`, usa `InMemorySaver`;
- com `DATABASE_URL`, usa `PostgresSaver` sobre `psycopg_pool.ConnectionPool`;
- com `LANGGRAPH_CHECKPOINT_SCHEMA`, guarda as tabelas do LangGraph em um schema
  especifico do cliente/repo dentro do mesmo database Postgres.
- com `DATABASE_URL`, o mesmo pool e schema guardam
  `pipefacil_webhook_idempotency`, com TTL configurado por
  `PIPEFACIL_WEBHOOK_IDEMPOTENCY_TTL_SECONDS`;
- sem `DATABASE_URL`, a idempotencia usa memoria local: restart perde reivindicacoes e
  replicas diferentes nao compartilham a garantia.
- cada conexao nova do pool recebe o `search_path` do schema configurado;
- cada checkout do pool valida a conexao antes de entregar ao LangGraph, evitando
  reaproveitar conexoes fechadas por timeout de ociosidade no Postgres.

Consequencia pratica:

- ambiente simples sobe sem banco;
- se houver necessidade de persistir threads entre reinicios, configure Postgres;
- varios clientes podem compartilhar o database `postgres` usando schemas diferentes.

## Observabilidade

O tracing do agente acontece principalmente em [`src/app/agent/service.py`](../src/app/agent/service.py)
e [`src/app/observability/langfuse.py`](../src/app/observability/langfuse.py).

Pontos importantes:

- cada execucao do agente gera observacao com `session_id`, `user_id`, `tags` e `metadata`;
- prompts podem vir do Langfuse ou cair no fallback local;
- dados sensiveis passam por mascaramento antes de irem para spans.

O contrato completo de observabilidade, labels e versionamento de prompts fica em
[`observabilidade-langfuse.md`](observabilidade-langfuse.md).

## Logging

Logs operacionais sao configurados em [`src/app/core/logging.py`](../src/app/core/logging.py).

Regras principais:

- producao usa JSON por padrao;
- desenvolvimento usa texto por padrao;
- dados dinamicos entram em `extra`;
- segredos nao devem ir para logs, e payload inbound nao entra por padrao;
- payload inbound validado e sanitizado so entra com `LOG_INBOUND_PAYLOADS=true`;
- traces Langfuse continuam sendo o lugar certo para investigar prompts, LLM e fluxo do agente.

O contrato completo fica em [`logging.md`](logging.md).

## Tratamento de erros

A API usa o formato padrao do FastAPI para respostas de erro.

Comportamento atual:

- `422` para erro esperado de payload ou regra de entrada do webhook;
- `404` para thread inexistente;
- `404` para audio gerado invalido, ausente ou expirado;
- `500` para erro inesperado de request, com logging centralizado;
- falha de configuracao em producao aborta o startup;
- falha no processamento ou outbound em background e registrada, mas nao altera o `200` de
  aceite ja enviado ao Pipefacil.

Os detalhes da politica ficam em [`tratamento-de-excecoes.md`](tratamento-de-excecoes.md).

## Decisoes arquiteturais importantes

- `FastAPI` e o runtime de producao; `langgraph dev` fica restrito ao desenvolvimento.
- `application` faz a orquestracao entre camadas, sem acoplamento direto da API com integracoes.
- `agent` concentra fluxo, estado, routing, nodes, chains, tools e prompts.
- `integrations` isola contratos, clientes HTTP e adaptadores de infraestrutura.
- `observability` isola SDK Langfuse, callbacks, masking e prompt loading.
- persistencia em Postgres e opt-in, nao obrigatoria.

## Onde colocar novas responsabilidades

- novo endpoint HTTP: `src/app/api/routes/`
- novo schema de request ou response: `src/app/api/schemas/`
- novo caso de uso: `src/app/application/`
- novo node do agente: `src/app/agent/nodes/`
- nova chain do agente: `src/app/agent/chains/`
- nova tool do agente: `src/app/agent/tools/`
- novo routing do agente: `src/app/agent/routing.py`
- novo estado do agente: `src/app/agent/state.py`
- nova integracao externa: `src/app/integrations/`
- nova configuracao global: `src/app/core/config.py`
- nova concern de tracing ou prompts: `src/app/observability/`

## Limites desta base

Este scaffold ainda e propositalmente pequeno.

Ele nao tenta resolver de saida:

- autenticacao;
- streaming;
- memoria de longo prazo;
- filas;
- retries distribuidos;
- regras comerciais especificas do Pipefacil;
- autenticacao, painel e orquestracao operacional completa da fila de supervisao.

Esses pontos devem ser adicionados conforme o caso de uso do agente evoluir.
