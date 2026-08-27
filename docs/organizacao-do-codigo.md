# Organizacao do Codigo

Este documento funciona como um mapa do repositorio. A ideia e responder rapido:

- onde cada responsabilidade mora;
- em qual arquivo mexer para cada tipo de mudanca;
- como manter a organizacao consistente conforme o projeto cresce.

## Visao geral do repositorio

```text
.
|-- docs/
|   `-- api/
|-- scripts/
|-- src/app/
|-- tests/
|-- Dockerfile
|-- Makefile
|-- README.md
|-- compose.yml
|-- langgraph.json
|-- nixpacks.toml
`-- pyproject.toml
```

## Raiz do projeto

### [`README.md`](../README.md)

Documento de entrada do repositorio. Explica proposta, stack, comandos, ambientes e
integracoes.

### [`pyproject.toml`](../pyproject.toml)

Define metadados do projeto, dependencias e configuracao de ferramentas como `pytest` e `ruff`.

### [`Makefile`](../Makefile)

Atalhos operacionais para instalacao, desenvolvimento, staging, testes e stack Docker.

### [`langgraph.json`](../langgraph.json)

Configuracao usada pelo `langgraph dev` e pelo Studio local.

### [`Dockerfile`](../Dockerfile)

Imagem da API para deploy containerizado.

### [`nixpacks.toml`](../nixpacks.toml)

Config de deploy para plataformas que usam Nixpacks, como Coolify quando o build pack fica
automatico. Garante que `README.md` e `src/` existam durante `pip install .` e fixa o start
command da API FastAPI.

### [`compose.yml`](../compose.yml)

Compose da stack self-hosted. Hoje sobe apenas a API.

## Pasta `src/app`

`src/app` contem o codigo da aplicacao propriamente dita.

### `src/app/main.py`

Ponto de entrada da `FastAPI`.

Responsabilidades:

- criar a aplicacao;
- montar o lifespan;
- aquecer observabilidade;
- instanciar o runtime do grafo;
- publicar recursos compartilhados em `app.state`;
- montar o store de idempotencia em memoria ou Postgres reutilizando o pool do runtime;
- registrar o middleware de borda de `/events/*`, incluindo log HTTP e decode seguro de
  `Content-Encoding: gzip`/`deflate`.

### `src/app/api/`

Camada HTTP.

Arquivos principais:

- [`src/app/api/router.py`](../src/app/api/router.py):
  agrega todos os routers.
- [`src/app/api/dependencies.py`](../src/app/api/dependencies.py):
  expoe `graph`, `settings` e o store de idempotencia para injecao nas rotas.
- [`src/app/api/presenters.py`](../src/app/api/presenters.py):
  converte resultados da aplicacao nos contratos HTTP expostos.

Subpastas:

- `routes/`: endpoints HTTP.
- `schemas/`: contratos Pydantic de entrada e saida.

#### `src/app/api/routes/`

- [`chat.py`](../src/app/api/routes/chat.py):
  endpoint manual `POST /chat`.
- [`threads.py`](../src/app/api/routes/threads.py):
  endpoint `GET /threads/{thread_id}/state`.
- [`webhooks.py`](../src/app/api/routes/webhooks.py):
  endpoint `POST /events/message-received`.
- [`ops.py`](../src/app/api/routes/ops.py):
  endpoints `GET /health` e `GET /ready`.
- [`generated_audio.py`](../src/app/api/routes/generated_audio.py):
  endpoint `GET /generated-audio/{filename}`, delegado para `application`.

#### `src/app/api/schemas/`

- [`chat.py`](../src/app/api/schemas/chat.py):
  request e response do endpoint de chat.
- [`threads.py`](../src/app/api/schemas/threads.py):
  response serializada de estado da thread.
- [`webhooks.py`](../src/app/api/schemas/webhooks.py):
  schema exposto pela API para o webhook.

### `src/app/application/`

Casos de uso da aplicacao.

Arquivos principais:

- [`chat.py`](../src/app/application/chat.py):
  roda o agente para um turno e busca estado de thread.
- [`pipefacil.py`](../src/app/application/pipefacil.py):
  coordena o fluxo inbound e outbound do Pipefacil.
- [`idempotency.py`](../src/app/application/idempotency.py):
  contrato do store de reivindicacao de mensagens e implementacao concorrente em memoria.
- [`pipefacil_deals.py`](../src/app/application/pipefacil_deals.py):
  caso de uso generico para mover um deal a uma etapa explicitamente escolhida.
- [`generated_audio.py`](../src/app/application/generated_audio.py):
  coordena geracao, conversao, persistencia temporaria e consulta de audio.
- [`delivery.py`](../src/app/application/delivery.py):
  monta o plano ordenado de texto e midia para entrega.
- [`token_budget.py`](../src/app/application/token_budget.py):
  estima e aplica o limite de tokens por lead.
- [`whatsapp.py`](../src/app/application/whatsapp.py):
  divide texto em mensagens deterministicas adequadas ao WhatsApp.
- [`dto.py`](../src/app/application/dto.py):
  dataclasses de retorno para a camada HTTP.

Quando usar esta pasta:

- quando a mudanca envolve coordenar mais de um modulo;
- quando a rota comeca a ficar "inteligente" demais;
- quando faz sentido expor um caso de uso reutilizavel para API e testes.

### `src/app/agent/`

Nucleo do agente.

Arquivos principais:

- [`state.py`](../src/app/agent/state.py):
  campos do estado compartilhado.
- [`messages.py`](../src/app/agent/messages.py):
  utilitarios para lidar com mensagens LangChain.
- [`graph.py`](../src/app/agent/graph.py):
  topologia do `StateGraph`.
- [`routing.py`](../src/app/agent/routing.py):
  nomes de nodes e funcoes puras de decisao.
- [`service.py`](../src/app/agent/service.py):
  execucao do grafo, acesso a estado e serializacao de snapshots.
- [`runtime.py`](../src/app/agent/runtime.py):
  montagem do runtime e selecao do checkpointer.
- [`agent.py`](../src/app/agent/agent.py):
  exporta `graph` para o caminho esperado pelo tooling.

Subpastas:

- [`nodes/`](../src/app/agent/nodes):
  steps finos do grafo.
- [`chains/`](../src/app/agent/chains):
  prompts, modelos e structured outputs usados por nodes com LLM.
- [`prompts/`](../src/app/agent/prompts):
  nomes de prompts Langfuse e fallbacks locais.
- [`specialists/`](../src/app/agent/specialists):
  contratos, registry e runner de especialistas OpenAI Agents SDK.
- [`tools/`](../src/app/agent/tools):
  tools expostas ao agente.

Quando mexer aqui:

- nova etapa do fluxo do agente;
- alteracao de estado;
- novos prompts;
- novas regras de roteamento;
- nova tool exposta ao agente;
- mudanca na forma de executar ou persistir o grafo.

O contrato detalhado desta pasta fica em
[`docs/arquitetura-agente.md`](arquitetura-agente.md).

### `src/app/integrations/`

Adaptadores para sistemas externos.

Hoje existem estes adaptadores:

- [`openai_audio.py`](../src/app/integrations/openai_audio.py):
  transcricao de audio inbound via OpenAI.

Integracao `pipefacil/`:

- [`contracts.py`](../src/app/integrations/pipefacil/contracts.py):
  contratos internos da integracao.
- [`mapping.py`](../src/app/integrations/pipefacil/mapping.py):
  extracao de dados uteis, normalizacao e metadata.
- [`client.py`](../src/app/integrations/pipefacil/client.py):
  cliente para mensagens, consulta/atualizacao de deals e download seguro de midia/arquivo
  inbound. Campos personalizados usam `{"customFields": ...}` e etapa usa
  `{"stageId": ...}`.

Infraestrutura de idempotencia:

- [`postgres_idempotency.py`](../src/app/integrations/postgres_idempotency.py):
  cria e opera `pipefacil_webhook_idempotency` atomicamente no mesmo pool e schema do
  runtime LangGraph. A camada HTTP nao importa esse adaptador diretamente.

Integracao `elevenlabs/`:

- [`client.py`](../src/app/integrations/elevenlabs/client.py):
  cliente HTTP de TTS e retry limitado para falhas transitorias.
- [`contracts.py`](../src/app/integrations/elevenlabs/contracts.py):
  resultados e erros estaveis da API externa.

Infraestrutura `generated_audio/`:

- [`conversion.py`](../src/app/integrations/generated_audio/conversion.py):
  conversao isolada com FFmpeg.
- [`storage.py`](../src/app/integrations/generated_audio/storage.py):
  escrita atomica, TTL, validacao de nomes e leitura do armazenamento local.

Boa pratica:

- se surgir nova API externa, crie uma nova subpasta em `integrations/`;
- evite espalhar `httpx` direto pela aplicacao.

### `src/app/core/`

Codigo transversal de configuracao.

- [`config.py`](../src/app/core/config.py):
  `Settings` central da aplicacao e precedencia de overrides por ambiente.
- [`agent_config.py`](../src/app/core/agent_config.py):
  schema estrito e transformacao dos defaults universais de `.agent.json`.
- [`agent_config_generated.py`](../src/app/core/agent_config_generated.py):
  modulo gerado e versionado consumido pelo runtime.
- [`database.py`](../src/app/core/database.py):
  normalizacao e preparacao compartilhada de conexoes Postgres.
- [`exceptions.py`](../src/app/core/exceptions.py):
  excecoes estaveis de configuracao do runtime.
- [`logging.py`](../src/app/core/logging.py):
  configuracao de logs estruturados.

### `src/app/outbound_media/`

- [`catalog.py`](../src/app/outbound_media/catalog.py):
  carrega, valida e expoe a visao segura do catalogo de midias outbound.
- [`catalog.json`](../src/app/outbound_media/catalog.json):
  catalogo ativo, vazio por padrao para nao misturar assets de clientes.
- [`catalog.example.json`](../src/app/outbound_media/catalog.example.json):
  exemplo versionado para novas implementacoes.

### `src/app/observability/`

Codigo de tracing e prompt management.

- [`langfuse.py`](../src/app/observability/langfuse.py):
  cliente, callbacks, prompt loading, fallback local e mascaramento de dados.

O contrato local desta pasta fica em
[`docs/observabilidade-langfuse.md`](observabilidade-langfuse.md).

## Pasta `scripts/`

Automacoes operacionais e bootstrap.

Arquivos principais:

- [`generate_agent_config.py`](../scripts/generate_agent_config.py):
  valida `.agent.json` e gera os defaults Python usados no runtime.
- [`bootstrap_langfuse_prompts.py`](../scripts/bootstrap_langfuse_prompts.py):
  sincroniza de forma idempotente os prompts staging no Langfuse.
- [`bootstrap_postgres_checkpointer.py`](../scripts/bootstrap_postgres_checkpointer.py):
  prepara schema do checkpointer Postgres quando usado.
- [`export_openapi.py`](../scripts/export_openapi.py):
  exporta o schema OpenAPI da API FastAPI para uso em ferramentas como Insomnia.
- [`validate_golden_dataset.py`](../scripts/validate_golden_dataset.py):
  valida manifest, schema e exemplos do dataset padrao ouro.
- [`sync_langfuse_golden_dataset.py`](../scripts/sync_langfuse_golden_dataset.py):
  sincroniza os casos revisados com o Langfuse.
- [`env.sh`](../scripts/env.sh):
  helpers para resolver env base e aplicar override `.local`.
- [`run_langgraph_dev.sh`](../scripts/run_langgraph_dev.sh):
  sobe `langgraph dev` com env base mais override local ignorado.
- [`run_staging_stack.sh`](../scripts/run_staging_stack.sh):
  sobe app e tunnel no modo staging.
- [`run_dev_tunnel.sh`](../scripts/run_dev_tunnel.sh):
  utilitario para tunnel em desenvolvimento.

## Pasta `tests/`

Cobertura de comportamento da aplicacao.

Arquivos principais:

- [`test_api.py`](../tests/test_api.py):
  comportamento dos endpoints.
- [`test_application.py`](../tests/test_application.py):
  casos de uso da camada `application`.
- [`test_generated_audio.py`](../tests/test_generated_audio.py):
  ElevenLabs, retries, FFmpeg, filesystem, fallbacks e endpoint de audio temporario.
- [`test_pipefacil.py`](../tests/test_pipefacil.py):
  integracao e mapping do Pipefacil.
- [`test_langgraph_nodes.py`](../tests/test_langgraph_nodes.py):
  nodes do agente.
- [`test_langgraph_structure.py`](../tests/test_langgraph_structure.py):
  estrutura do grafo.
- [`test_runtime.py`](../tests/test_runtime.py):
  runtime, checkpointer e tracing.
- [`test_idempotency.py`](../tests/test_idempotency.py):
  stores de idempotencia em memoria e Postgres.
- [`test_pipefacil_deals.py`](../tests/test_pipefacil_deals.py):
  movimentacao direcional de etapa do deal.
- [`test_outbound_media_catalog.py`](../tests/test_outbound_media_catalog.py):
  contrato e seguranca do catalogo de midias.
- [`test_golden_dataset.py`](../tests/test_golden_dataset.py) e
  [`test_langfuse_golden_dataset.py`](../tests/test_langfuse_golden_dataset.py):
  validacao local e sincronizacao do dataset padrao ouro.
- [`test_whatsapp_formatting.py`](../tests/test_whatsapp_formatting.py):
  divisao deterministica das mensagens de texto.
- [`test_env_files.py`](../tests/test_env_files.py):
  separacao entre defaults universais e configuracao de ambiente.
- [`test_agent_config.py`](../tests/test_agent_config.py):
  schema tipado, seguranca, precedencia e consistencia da configuracao gerada.
- [`test_langfuse_prompts.py`](../tests/test_langfuse_prompts.py):
  prompts e fallback.
- [`test_langfuse_observability.py`](../tests/test_langfuse_observability.py):
  comportamento de observabilidade.
- [`test_logging.py`](../tests/test_logging.py):
  formatter, masking e eventos de log esperados.
- [`test_specialists.py`](../tests/test_specialists.py):
  fluxo de delegacao para especialistas.
- [`test_architecture_boundaries.py`](../tests/test_architecture_boundaries.py):
  limites entre camadas.

## Onde adicionar codigo novo

- endpoint novo: `src/app/api/routes/`
- schema novo: `src/app/api/schemas/`
- caso de uso novo: `src/app/application/`
- node novo: `src/app/agent/nodes/`
- chain nova: `src/app/agent/chains/`
- prompt novo: `src/app/agent/prompts/`
- roteamento novo: `src/app/agent/routing.py`
- tool nova: `src/app/agent/tools/`
- campo de estado novo: `src/app/agent/state.py`
- integracao externa nova: `src/app/integrations/`
- configuracao global: `src/app/core/`
- logging global: `src/app/core/logging.py`
- catalogo compartilhado de midias outbound: `src/app/outbound_media/`
- guia do catalogo de midias outbound: `docs/catalogo-midias-outbound.md`
- tracing ou prompts: `src/app/observability/`
- contexto de documentacao Langfuse: `docs/contexto-desenvolvimento-langfuse.md`
- teste de comportamento: `tests/`
- script operacional: `scripts/`

## Pasta `docs/api/`

Artefatos para consumo manual ou ferramental da API.

- [`openapi.json`](api/openapi.json):
  schema OpenAPI exportado da aplicacao FastAPI.
- [`insomnia.md`](api/insomnia.md):
  guia de importacao no Insomnia, variaveis locais e payloads de exemplo.

## Convencoes uteis

- rotas HTTP devem delegar rapido para `application` e nao importar `integrations`;
- contratos externos devem ficar isolados em `integrations`;
- DTOs de retorno da aplicacao ficam em `application/dto.py`;
- estado do agente deve ser expandido em `agent/state.py` antes de espalhar campos soltos;
- novos fluxos do agente devem ser refletidos em `agent/graph.py` e cobertos por testes.
- nodes devem continuar finos e retornar apenas updates parciais de estado;
- tools podem adaptar a interface do agente, mas clientes HTTP ficam em `integrations`.

## Sinais de que a organizacao esta escorregando

- rota HTTP falando direto com `httpx`;
- node contendo regra de transporte HTTP ou parsing de webhook;
- arquivo `application` virando deposito de logica heterogenea;
- configuracao de ambiente sendo lida fora de `core/config.py`;
- mocks de integracao aparecendo espalhados em testes sem ponto central claro.
