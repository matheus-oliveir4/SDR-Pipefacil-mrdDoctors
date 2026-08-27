# Documentacao do Projeto

Este diretorio concentra a documentacao tecnica do repositorio.

## Guias disponiveis

- [`arquitetura-aplicacao.md`](arquitetura-aplicacao.md)
  Visao geral da arquitetura, camadas, fluxo de execucao e decisoes principais.
- [`organizacao-do-codigo.md`](organizacao-do-codigo.md)
  Mapa do repositorio e responsabilidades de cada pasta e arquivo principal.
- [`arquitetura-agente.md`](arquitetura-agente.md)
  Contrato arquitetural interno de `src/app/agent`, incluindo nodes, chains, routing,
  prompts e tools.
- [`tratamento-de-excecoes.md`](tratamento-de-excecoes.md)
  Politica de excecoes, mapeamento HTTP, startup em producao e semantica de `delivery_status`.
- [`estrutura-langgraph.md`](estrutura-langgraph.md)
  Como o LangGraph esta encaixado no projeto e como o runtime escolhe o checkpointer.
- [`boas-praticas-agente.md`](boas-praticas-agente.md)
  Guia de modelagem do agente, nodes, estado, regras e fluxo conversacional.
- [`contexto-desenvolvimento-langgraph.md`](contexto-desenvolvimento-langgraph.md)
  Como conectar a documentacao oficial LangChain/LangGraph via `llms.txt` e MCP em
  ferramentas locais de desenvolvimento.
- [`contexto-desenvolvimento-langfuse.md`](contexto-desenvolvimento-langfuse.md)
  Como conectar a documentacao oficial Langfuse via `llms.txt` e MCP em ferramentas locais
  de desenvolvimento.
- [`observabilidade-langfuse.md`](observabilidade-langfuse.md)
  Contrato local de tracing, callbacks, masking, prompt management, labels e promocao de
  prompts no Langfuse.
- [`logging.md`](logging.md)
  Contrato de logs estruturados, niveis, campos, seguranca e relacao com traces Langfuse.
- [`catalogo-midias-outbound.md`](catalogo-midias-outbound.md)
  Como preencher o catalogo versionado de midias que o agente pode escolher por `media_id`.
- [`dataset-padrao-ouro.md`](dataset-padrao-ouro.md)
  Como organizar exemplos padrao ouro, sincronizar com Langfuse e revisar runs com
  `answer_correct`, `failure_note` e `Corrected Output`.
- [`api/insomnia.md`](api/insomnia.md)
  Guia para importar o OpenAPI no Insomnia e testar endpoints manualmente.

## Ordem sugerida para onboarding

1. Ler o [`README.md`](../README.md) da raiz.
2. Ler [`arquitetura-aplicacao.md`](arquitetura-aplicacao.md).
3. Ler [`organizacao-do-codigo.md`](organizacao-do-codigo.md).
4. Ler [`arquitetura-agente.md`](arquitetura-agente.md).
5. Ler [`tratamento-de-excecoes.md`](tratamento-de-excecoes.md).
6. Ler [`estrutura-langgraph.md`](estrutura-langgraph.md).
7. Consultar [`boas-praticas-agente.md`](boas-praticas-agente.md) antes de expandir o fluxo do agente.
8. Ler [`observabilidade-langfuse.md`](observabilidade-langfuse.md) antes de alterar prompts ou tracing.
9. Ler [`logging.md`](logging.md) antes de adicionar logs em fluxo de producao.
10. Ler [`catalogo-midias-outbound.md`](catalogo-midias-outbound.md) antes de habilitar envio de midias pelo agente.
11. Ler [`dataset-padrao-ouro.md`](dataset-padrao-ouro.md) antes de montar casos de
    avaliacao do agente.
12. Abrir [`api/insomnia.md`](api/insomnia.md) antes de testar a API manualmente.
13. Conferir [`contexto-desenvolvimento-langgraph.md`](contexto-desenvolvimento-langgraph.md) e [`contexto-desenvolvimento-langfuse.md`](contexto-desenvolvimento-langfuse.md) ao configurar um novo editor ou assistente de codigo.

## Quando atualizar esta pasta

Atualize os arquivos de `docs/` quando houver mudancas em:

- fluxo HTTP ou contratos publicos;
- organizacao das camadas;
- responsabilidades de pastas e modulos;
- estrategia de persistencia;
- observabilidade, prompts ou integracoes externas;
- convencoes de extensao do agente.
