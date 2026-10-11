# DOCUMENTATION_POLICY — Video Factory

**Objetivo:** garantir continuidade entre Antigravity/Gemini, ChatGPT e futuros chats sem depender da memória de uma conversa específica.

---

## Fonte de verdade documental

A documentação canônica deve viver no repositório:

```text
docs/
├── PROJECT_HANDOFF.md
├── ROADMAP.md
├── PRODUCTION_RUNBOOK.md
└── DOCUMENTATION_POLICY.md
```

---

## Responsabilidade do agente de desenvolvimento

O agente Antigravity/Gemini deve manter os documentos atualizados ao concluir marcos relevantes.

> [!IMPORTANT]
> **REGRA DE OURO — ATUALIZAÇÃO NA MESMA ENTREGA:**
> `docs/PROJECT_HANDOFF.md` é a **porta de entrada única e memória viva** do projeto. Ele DEVE ser atualizado obrigatoriamente na **MESMA entrega** (no mesmo commit ou PR) sempre que ocorrer qualquer um dos eventos abaixo. **NUNCA deixar atualização do HANDOFF para "depois"**.

Atualizar `PROJECT_HANDOFF.md` obrigatoriamente na mesma entrega quando ocorrer:
- fase concluída ou iniciada;
- hotfix implementado ou integrado;
- merge importante no main;
- deploy em produção realizado;
- homologação real (sucesso ou falha);
- bug real descoberto;
- bug resolvido ou deliberadamente adiado (com registro de decisão);
- mudança de configuração operacional relevante (Growth Mode, providers, etc.);
- mudança de arquitetura ou persistência;
- alteração de Safety / Quality / Scheduler / Copyright Gates;
- alteração de fluxo de publicação;
- novo backup de referência;
- novo gate de homologação ou mudança de próximo passo.

---

## PROJECT_HANDOFF.md

Deve conter sempre:
- estado atual do projeto
- ambiente de desenvolvimento
- ambiente de produção
- commit atual
- último deploy
- último backup de referência
- estado das features
- bugs conhecidos
- decisões arquiteturais
- tasks reais em andamento
- configurações críticas
- resultados de testes
- próximos passos
- riscos / bloqueios
- comandos especiais que não podem ser esquecidos

Ele deve permitir que um novo agente ou novo chat continue o projeto sem depender do histórico inteiro da conversa.

---

## ROADMAP.md

Deve conter:
- fases concluídas
- fase atual
- próximos marcos
- critérios de aceite
- dependências
- itens explicitamente adiados
- ideias futuras aprovadas
- gates que bloqueiam fases seguintes

---

## PRODUCTION_RUNBOOK.md

Deve conter procedimentos operacionais seguros:
- backup
- stop
- update
- testes
- start
- health
- PRIMARY
- recovery
- rollback
- scheduler
- autonomous
- publicação
- troubleshooting operacional

---

## Regra de atualização

No fim de cada fase ou hotfix, o agente deve:

1. atualizar os documentos afetados
2. mostrar o diff resumido
3. validar que nenhum secret foi incluído
4. executar `git diff --check`
5. mostrar `git status --porcelain`
6. commitar documentação junto da mudança ou em commit dedicado
7. fazer push somente quando autorizado pelo fluxo atual

---

## Regra de segurança

Nunca documentar:
- API keys
- tokens
- cookies
- passwords
- client secrets
- access tokens
- conteúdo sensível de `config.toml`
- dados pessoais desnecessários

Pode documentar:
- nome da configuração
- estado ON/OFF
- provider
- comportamento
- caminho genérico

---

## Como iniciar um novo chat

No novo chat, basta dizer:

```text
Leia docs/PROJECT_HANDOFF.md do repositório video-factory e me apresente o relatório de alinhamento antes de continuarmos.
```

O novo agente deverá ler `docs/PROJECT_HANDOFF.md` por completo e apresentar imediatamente o relatório contendo:
- Fase atual e ambientes (DEV / PROD);
- Último commit/deploy e última homologação real;
- Gate atual e próximo passo exato;
- Pendências conhecidas e itens adiados.
- Divergências entre documento e Git, se houver.

---

## Prompt permanente para o agente Antigravity

```text
REGRA PERMANENTE DE DOCUMENTAÇÃO DO PROJETO

A partir de agora, trate os arquivos abaixo como documentação canônica:

docs/PROJECT_HANDOFF.md
docs/ROADMAP.md
docs/PRODUCTION_RUNBOOK.md
docs/DOCUMENTATION_POLICY.md

Sempre que concluir uma fase, hotfix, deploy, gate operacional ou mudança arquitetural:

1. Atualize PROJECT_HANDOFF.md com o estado real mais recente.
2. Atualize ROADMAP.md se o status de qualquer fase mudar.
3. Atualize PRODUCTION_RUNBOOK.md se o procedimento operacional mudar.
4. Não registre secrets, tokens, API keys ou credenciais.
5. Preserve histórico útil, mas mantenha o "estado atual" claro e fácil de localizar.
6. Registre commit SHA, testes executados e resultado.
7. Registre produção tocada ou não tocada.
8. Registre Auto Publish, Autonomous, TikTok, Growth Mode e privacy quando relevantes.
9. Registre bugs reais encontrados em homologação e sua resolução.
10. Antes de finalizar, rode git diff --check e git status --porcelain.

NÃO faça deploy ou publicação externa apenas para atualizar documentação.
NÃO altere configurações de produção sem autorização explícita.

Ao entregar qualquer fase importante, inclua no relatório:
DOCUMENTATION_UPDATED = YES/NO
FILES_UPDATED = [...]
```

---

## Resultado esperado

Com essa política, o repositório passa a carregar o contexto do projeto e a conversa deixa de ser a única fonte de memória.

O próximo ChatGPT ou agente consegue recuperar o estado lendo os documentos canônicos.
