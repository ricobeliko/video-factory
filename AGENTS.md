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
- Testes antes de finalizar.
- Relatar exatamente: arquivos alterados, testes executados, commit (se houver) e o
  próximo gate seguro.

## Precedência

Se houver conflito entre este arquivo e `docs/PRODUCTION_RUNBOOK.md`, o
`PRODUCTION_RUNBOOK.md` prevalece para operações de produção.
