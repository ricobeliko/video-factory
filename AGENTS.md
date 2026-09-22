# Video Factory Agent Instructions

Este arquivo complementa — e não duplica — a documentação em `docs/` e as
[instruções do Copilot](.github/copilot-instructions.md).

## Antes de trabalhar

1. Leia os quatro documentos canônicos em `docs/`: `PROJECT_HANDOFF.md`, `ROADMAP.md`,
   `PRODUCTION_RUNBOOK.md`, `DOCUMENTATION_POLICY.md`.
2. Execute `git status`.
3. Execute `git log -5 --oneline`.
4. Identifique a fase/gate atual do projeto.
5. Não suponha que documentação antiga representa o estado atual de produção sem verificar.

## Regras

- Um agente modifica o repositório por vez.
- Preservar o trabalho existente.
- Nenhuma operação destrutiva.
- Nenhum deploy sem autorização.
- Nenhum acesso ou modificação de secrets.
- Relatar exatamente: arquivos alterados, testes executados, commit (se houver) e o
  próximo gate seguro.

## TEST POLICY — PRECEDÊNCIA ALTA

Esta política de testes prevalece sobre instruções ou referências históricas de testes em `ROADMAP.md`, `PROJECT_HANDOFF.md` e `PRODUCTION_RUNBOOK.md`.

- Por padrão, executar somente teste diretamente relacionado à mudança.
- Máximo inicial: 1 comando de teste direcionado.
- Preferir arquivo específico e/ou -k.
- Se passar, PARAR.
- Não expandir automaticamente para outras suítes.
- Full regression somente com autorização humana explícita.
- Coverage somente com autorização humana explícita.
- CI não deve ser executado ou monitorado automaticamente.
- Não repetir teste que já passou sem mudança posterior relevante.
- Não criar testes novos por reflexo; somente quando houver gap real relacionado à alteração.
- Mudança somente documental não exige pytest.
- Concluir um gate NÃO autoriza regressão completa.
- Nenhuma referência histórica no ROADMAP/HANDOFF/RUNBOOK autoriza executar aquelas suítes novamente.
- Se houver dúvida entre testar mais e parar: PARAR e informar.

## Precedência

Se houver conflito entre este arquivo e `docs/PRODUCTION_RUNBOOK.md`, o
`PRODUCTION_RUNBOOK.md` prevalece para operações de produção.
