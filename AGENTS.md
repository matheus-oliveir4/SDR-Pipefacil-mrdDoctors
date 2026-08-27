# Development Agent Context

This repository is the LangGraph-based SDR template integrated with the Pipefacil CRM.

Before changing LangChain, LangGraph, LangSmith, Langfuse, MCP, prompts, chains, nodes,
tools, checkpointers, or agent runtime behavior, consult the current official docs:

- Documentation index: https://docs.langchain.com/llms.txt
- LangChain docs MCP server: https://docs.langchain.com/mcp
- Langfuse documentation index: https://langfuse.com/llms.txt
- Langfuse docs MCP server: https://langfuse.com/api/mcp

Prefer the MCP server when the current AI/client supports MCP. Use the documentation index
to discover relevant pages before relying on memory.

Important local architecture docs:

- `docs/arquitetura-agente.md`
- `docs/estrutura-langgraph.md`
- `docs/boas-praticas-agente.md`
- `docs/arquitetura-aplicacao.md`
- `docs/observabilidade-langfuse.md`
- `docs/contexto-desenvolvimento-langfuse.md`

Development-only rule:

- MCP documentation connectors and AI assistant settings are for local development only.
- Do not import MCP docs clients in production code.
- Do not add docs/MCP assistant tooling to runtime dependencies.
- Do not require these tools in the Docker image or production startup path.

Core boundary:

- `api` validates HTTP and delegates to `application`.
- `application` orchestrates use cases.
- `agent` owns LangGraph state, graph, routing, nodes, chains, prompts, and tools.
- `integrations` owns external API contracts, mapping, and HTTP clients.
- `observability` owns Langfuse clients, tracing helpers, prompt fetching, fallback behavior,
  and masking.
