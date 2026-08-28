# Estrutura LangGraph do Projeto

Este projeto usa `LangGraph` como biblioteca de orquestracao, com `FastAPI` como runtime HTTP real e `langgraph dev` apenas como ferramenta de desenvolvimento.

## Objetivo

A organizacao atual separa:

- montagem do grafo
- nodes finos
- routing puro
- runtime HTTP da aplicacao
- persistencia por checkpointer
- observabilidade e prompts versionados

Assim a gente consegue manter o fluxo visual do LangGraph sem depender do Agent Server licenciado.

## Arquivos principais

### `langgraph.json`

Continua existindo para `langgraph dev`.

Responsabilidades:

- apontar o grafo exportado para Studio
- carregar o env de desenvolvimento usado pelo `make dev`
- manter o projeto compativel com debugging visual

### `src/app/main.py`

Ponto de entrada da FastAPI.

Responsabilidades:

- criar a app
- inicializar Langfuse
- montar o grafo de runtime com checkpointer apropriado
- fechar recursos no shutdown

### `src/app/agent/agent.py`

Constroi o grafo base e exporta `graph` para o caminho de desenvolvimento visual.

### `src/app/agent/graph.py`

Monta o `StateGraph`, registra nodes e edges, compila o grafo e anexa callbacks Langfuse
quando habilitados.

O fluxo principal continua:

```text
START -> classify-intent -> qualify-lead -> respond -> END
```

O grafo tambem tem um caminho condicional para trabalho interno mais complexo:

```text
START -> classify-intent -> qualify-lead -> delegate-specialist -> respond -> END
```

O classificador decide se a rodada precisa de especialista, o node executa o OpenAI Agents
SDK atras de feature flag e o responder mantem a mensagem final.

O node `qualify-lead` usa structured output para avaliar cinco criterios comerciais sobre o
historico completo. O status final e derivado deterministicamente no codigo: todos os
criterios confirmados geram `qualified`, informacao faltante gera `qualifying` e qualquer
contradicao explicita gera `not_qualified`.

### `src/app/agent/routing.py`

Centraliza nomes de nodes e funcoes puras de decisao para `add_conditional_edges` ou
`Command`.

Routing nao deve chamar LLM, HTTP, banco, Langfuse ou integracoes.

### `src/app/agent/nodes/`

Implementa steps finos do grafo. Cada node le `AgentState`, chama uma chain/tool/regra e
retorna um update parcial de estado.

`delegate-specialist` chama especialistas OpenAI Agents SDK quando `requires_specialist`
esta marcado no estado. Ele nao envia mensagem ao usuario e retorna apenas resultado
estruturado para o responder.

### `src/app/agent/chains/`

Monta prompts, modelos, structured outputs e compatibilidades de modelo usadas pelos nodes.

### `src/app/agent/prompts/`

Define nomes de prompts Langfuse e fallbacks locais.

O contrato de labels, versionamento e promocao desses prompts fica em
[`observabilidade-langfuse.md`](observabilidade-langfuse.md).

### `src/app/agent/tools/`

Espaco para tools expostas ao agente. Detalhes de API externa continuam em
`src/app/integrations/`.

### `src/app/agent/runtime.py`

Decide qual checkpointer usar:

- `InMemorySaver` por padrao
- `PostgresSaver` com `psycopg_pool.ConnectionPool` quando `DATABASE_URL` estiver
  configurada

Tambem centraliza normalizacao de URL JDBC/Postgres, aplicacao de
`LANGGRAPH_CHECKPOINT_SCHEMA`, configuracao do pool e bootstrap do schema do Postgres.

### `src/app/agent/service.py`

Concentra a execucao do agente e a leitura/serializacao do estado da thread.

Tambem abre a observacao raiz do agente e propaga `session_id`, `user_id`, `tags` e
`metadata` para o Langfuse quando a observabilidade esta habilitada.

O contrato interno completo de `src/app/agent/` esta em
[`arquitetura-agente.md`](arquitetura-agente.md).

## Persistencia

O projeto usa short-term memory por `thread_id`.

Boas praticas adotadas:

- toda execucao HTTP passa `configurable.thread_id`
- Postgres e opcional
- quando varios clientes compartilham o mesmo database, cada cliente usa um schema proprio
  em `LANGGRAPH_CHECKPOINT_SCHEMA`
- o `setup()` do Postgres roda em passo explicito, nao no startup da API

## Comandos

### Desenvolvimento local

```bash
make dev
```

O alvo gera um config temporario ignorado para o LangGraph CLI e carrega `.env.dev`
junto com `.env.dev.local`, quando existir. Isso mantem defaults versionados separados
de segredos locais.

### Bootstrap do checkpointer Postgres

```bash
make db-setup
```

Exemplo recomendado para manter todos os clientes no database `postgres`, isolados por
schema:

```env
DATABASE_URL=postgresql://user:password@db.example.com:5432/postgres
LANGGRAPH_CHECKPOINT_SCHEMA=sdr_cliente
```

### Stack self-hosted

```bash
make prod
```

## O que fica fora deste v1

Este scaffold ainda nao implementa:

- streaming
- autenticacao
- memoria de longo prazo
- endpoints estilo LangSmith
- regras comerciais da Pipefacil
