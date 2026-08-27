# Boas Praticas Para Desenvolver o Agente

Guia pratico para desenvolver agentes com LangGraph neste projeto.

Base conceitual: "Thinking in LangGraph", adaptado para uma realidade de agente conversacional com regras de negocio, qualificacao, cobertura, objeções e handoff humano.

## Objetivo

Antes de escrever qualquer prompt, defina:

- qual problema o agente resolve
- quais decisoes ele precisa tomar
- quais resultados finais ele pode produzir
- quando ele deve pedir ajuda humana
- quais regras de negocio nao podem ficar implícitas

O erro mais comum e tentar "fazer o agente ficar inteligente" no prompt antes de modelar o processo.

## Principios centrais

- Pense no agente como um fluxo com estado, nao como uma resposta unica do LLM.
- Cada node deve fazer uma coisa so.
- Estado deve guardar dados brutos, nao texto formatado para prompt.
- Regras de negocio criticas devem ser explicitas no codigo ou no estado, nao escondidas em linguagem vaga.
- Erros e excecoes fazem parte do fluxo e precisam de tratamento deliberado.
- Perguntas laterais do usuario nao devem quebrar o objetivo principal da conversa.

## 1. Comece pelo processo, nao pelo prompt

Antes de implementar, desenhe o fluxo:

1. entrada
2. classificacao
3. coleta de dados faltantes
4. validacoes de negocio
5. decisao
6. resposta
7. encerramento ou proximo passo

Exemplo de perguntas que devem ser respondidas antes de codar:

- O que faz um lead virar `apto`, `em_analise`, `fora_cobertura` ou `perdido`?
- O que acontece se o usuario responder parcialmente?
- O que acontece se ele mandar texto primeiro e imagem depois?
- O que acontece se surgir uma objeção no meio do fluxo?
- O que acontece se ele perguntar "como funciona?" antes de concluir a triagem?

Se essas respostas nao estiverem claras, o agente vai parecer inconsistente mesmo com um modelo bom.

## 2. Quebre o fluxo em nodes pequenos

Use nodes pequenos e especializados.

Bom:

- `classificar_intencao`
- `coletar_estado`
- `validar_cobertura`
- `extrair_valor_da_conta`
- `avaliar_elegibilidade`
- `responder_objecao`
- `encerrar_conversa`

Ruim:

- `resolver_conversa_inteira`

Nodes menores ajudam em:

- depuracao
- testes
- reuso
- checkpoint
- retentativa
- observabilidade

## 3. Separe tipos de node

Pense em quatro grupos:

- `LLM node`: entender intencao, resumir, classificar, responder
- `Data node`: buscar CRM, cobertura, documentos, historico
- `Action node`: enviar mensagem, criar ticket, registrar status
- `Human node`: pedir aprovacao, revisar, tratar excecao operacional

Essa separacao deixa mais claro:

- o que depende de modelo
- o que depende de dado externo
- o que mexe em sistema
- o que precisa de humano

## 4. Estado e memoria: guarde dados brutos

O estado deve conter informacao reutilizavel.

Exemplos bons para guardar:

- mensagens do usuario
- classificacao atual
- estado informado
- cidade ou cobertura
- valor extraido da conta
- evidencia enviada, como foto
- flags de objecao
- status da triagem
- motivo da decisao final

Evite guardar:

- prompts inteiros
- mensagens formatadas para o modelo
- texto redundante que pode ser derivado

Regra pratica:

- se o dado precisa sobreviver entre nodes, guarde no estado
- se o dado pode ser reconstruido facilmente, gere sob demanda

## 5. Regras de negocio precisam estar explicitas

Nao deixe criterios criticos só "implícitos" no LLM.

Exemplos de regras que devem estar declaradas de forma objetiva:

- estados com cobertura e sem cobertura
- valor minimo aceito
- quando uma foto e obrigatoria
- quando uma foto invalida o valor digitado antes
- quando um caso vira `perdido`
- quando um caso vira `fora_cobertura`
- quando o agente deve insistir
- quando o agente deve parar

Idealmente, toda decisao importante deve conseguir responder:

- qual regra foi aplicada
- com base em qual evidência
- em qual node isso aconteceu

## 6. Perguntas laterais e objeções nao devem quebrar o fluxo

Em agente conversacional, o usuario raramente segue linha reta.

Ele pode:

- perguntar "como funciona?"
- questionar preco
- duvidar do processo
- mudar de assunto temporariamente
- mandar uma informacao nova que altera o diagnostico

Boa pratica:

- trate objeção como um estado da conversa, nao como reset do fluxo
- responda a pergunta lateral
- preserve o contexto principal
- depois retome exatamente o que faltava

Exemplo:

- faltava confirmar o valor da conta
- usuario pergunta "como funciona?"
- agente responde brevemente
- agente volta para "me manda a foto da conta para eu confirmar o valor"

## 7. Dados conflitantes devem reavaliar a decisao

O agente nao pode assumir que o primeiro dado informado e definitivo.

Exemplos:

- usuario escreveu um valor
- depois mandou uma foto
- a foto mostra outro valor

Boa pratica:

- a evidencia mais confiavel deve prevalecer
- o agente deve reavaliar a elegibilidade
- o estado deve registrar origem do dado

Exemplo de campos uteis:

- `valor_conta_informado_texto`
- `valor_conta_extraido_foto`
- `valor_conta_confirmado`
- `fonte_valor_confirmado`

## 8. Use roteamento claro

No LangGraph, cada node deve deixar claro para onde pode ir.

Perguntas boas na hora de desenhar edges:

- esse node sempre vai para o mesmo proximo passo?
- ou ele decide entre caminhos diferentes?
- essa decisao depende de regra ou de classificacao do LLM?

Regra simples:

- fluxo fixo: `add_edge`
- decisao dinamica: `add_conditional_edges` ou `Command`

## 9. Erros devem ter tratamento por tipo

Nem todo erro deve ser tratado igual.

Use esta separacao:

- erro transiente
  exemplo: timeout, rate limit, indisponibilidade temporaria
  acao: retry

- erro recuperavel pelo proprio agente
  exemplo: parse ruim, ferramenta falhou, resposta incompleta
  acao: registrar no estado e tentar de novo com contexto

- erro dependente do usuario
  exemplo: faltou foto, faltou conta, cidade nao informada
  acao: pedir a informacao e pausar o fluxo

- erro inesperado
  exemplo: regra sem cobertura, formato nao previsto, bug
  acao: deixar explodir, logar e investigar

Nao esconda erro real com fallback genérico demais.

## 10. Human-in-the-loop deve entrar onde o risco e alto

Use revisao humana quando houver:

- caso fora da regra
- conflito entre evidencias
- usuario irritado
- suspeita de erro de classificacao
- impacto financeiro
- excecao operacional

Nao jogue tudo para humano, mas tambem nao automatize cegamente o que pode gerar decisao errada.

## 11. Defina status finais finitos

O agente precisa terminar em um conjunto pequeno e claro de estados.

Exemplo:

- `aguardando_dado`
- `em_analise`
- `apto`
- `fora_cobertura`
- `perdido`
- `encaminhar_humano`

Cada status final ou intermediario deve ter:

- definicao objetiva
- criterio de entrada
- resposta esperada do agente
- proximo passo operacional

## 12. Teste cenarios, nao so nodes isolados

Nao basta testar se uma funcao roda. Teste conversas reais.

Monte uma matriz de casos:

- informou valor abaixo do minimo
- informou estado sem cobertura
- disse um valor, depois mandou foto com valor diferente
- perguntou "como funciona?" no meio
- resistiu ao envio da foto
- mandou imagem invalida
- mandou dado parcial
- voltou depois com nova informacao

Para cada caso, documente:

- entrada
- caminho esperado no grafo
- status final esperado
- mensagem final esperada

## 13. Observabilidade e rastreabilidade sao obrigatorias

Voce precisa conseguir responder:

- em qual node a conversa esta
- qual classificacao o agente fez
- qual regra de negocio disparou
- por que ele marcou `perdido`
- qual dado faltou
- quando uma objeção foi detectada

Se a resposta for "o modelo decidiu", falta estrutura.

## 14. Prompts devem orientar, nao substituir arquitetura

Prompt bom:

- explica papel do node
- define formato de saida
- lista criterios de classificacao
- delimita quando pedir dado faltante

Prompt ruim:

- tenta conter todo o processo inteiro
- mistura regra de negocio, UX, fallback e decisao final num bloco gigante

Arquitetura decide o fluxo.
Prompt decide o comportamento local do node.

## 15. Documente edge cases antes de escalar

Antes de considerar o agente "pronto", documente pelo menos:

- regras de cobertura
- regras de elegibilidade
- tratamento de objecao
- precedencia entre texto e imagem
- criterios de `perdido`
- criterios de handoff humano
- mensagens de retomada de contexto

Isso reduz muito o risco de comportamento inconsistente em producao.

## Estrutura recomendada para este projeto

A estrutura oficial do agente fica em `src/app/agent/` e assume um agente por repositorio:

```text
src/app/agent/
├── state.py
├── graph.py
├── routing.py
├── messages.py
├── service.py
├── runtime.py
├── nodes/
├── chains/
├── prompts/
└── tools/
```

Separacao sugerida:

- `state.py`: schema do estado
- `graph.py`: montagem do StateGraph
- `routing.py`: funcoes de decisao
- `nodes/`: steps finos do grafo
- `chains/`: prompts + modelos + structured output
- `prompts/`: nomes Langfuse e fallbacks locais
- `tools/`: tools expostas ao agente
- `integrations/`: clientes, contratos e mapping de APIs externas

Regra importante: `nodes/` e `tools/` nao devem espalhar `httpx` nem contratos externos.
Quando uma tool precisar falar com outro sistema, ela deve delegar para `integrations/` ou
para um caso de uso em `application/`.

O contrato completo fica em
[`arquitetura-agente.md`](arquitetura-agente.md).

## Checklist antes de implementar um novo node

- Esse node faz uma coisa só?
- Ele precisa mesmo de LLM?
- O que entra nele?
- O que ele devolve?
- Qual regra de negocio ele aplica?
- Para onde ele pode roteiar?
- Como ele falha?
- Precisa retry?
- Precisa handoff humano?
- Precisa teste de conversa?

## Checklist antes de marcar o agente como pronto

- Regras de negocio criticas estao explicitas
- Status finais estao definidos
- Edge cases principais estao testados
- Perguntas laterais nao quebram o fluxo
- Dados conflitantes geram reavaliacao
- Logs permitem entender a decisao
- Handoff humano existe para excecoes reais
- Prompt nao esta segurando sozinho a logica do sistema

## Resumo

Desenvolver bem um agente nao e "dar um prompt bom".

E:

- desenhar o processo
- explicitar regras
- separar responsabilidades
- preservar contexto
- tratar excecoes
- testar cenarios reais

Se o agente precisar decidir algo importante, a decisao precisa ser rastreavel.
