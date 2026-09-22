# Instruções para GitHub Copilot — Video Factory (MoneyPrinterTurbo)

Estas instruções aplicam-se a qualquer sugestão, edição ou execução de agente do Copilot
neste repositório. O Copilot atua como agente **secundário/fallback** deste projeto.

## Leitura obrigatória antes de qualquer mudança relevante

Antes de propor ou aplicar qualquer mudança não trivial, leia:

- [docs/PROJECT_HANDOFF.md](../docs/PROJECT_HANDOFF.md)
- [docs/ROADMAP.md](../docs/ROADMAP.md)
- [docs/PRODUCTION_RUNBOOK.md](../docs/PRODUCTION_RUNBOOK.md)
- [docs/DOCUMENTATION_POLICY.md](../docs/DOCUMENTATION_POLICY.md)

Não presuma que esses documentos, se antigos, ainda refletem o estado atual de produção —
verifique com `git status` e `git log` antes de agir.

## Princípios de engenharia

- Preserve a arquitetura atual do projeto.
- Faça mudanças mínimas e auditáveis; evite refatorações não solicitadas.
- Investigue a causa raiz antes de corrigir qualquer bug — não aplique correções superficiais.
- Concluir um gate NÃO autoriza regressão completa.
- Nunca declare uma fase ou etapa do roadmap concluída sem cumprir explicitamente o gate
  correspondente definido na documentação.

## TEST POLICY — PRECEDÊNCIA ALTA

Esta política de testes prevalece sobre qualquer menção ou suíte histórica de testes no repositório.

- Por padrão, executar somente teste diretamente relacionado à mudança ("testes relevantes" significa o teste mínimo diretamente afetado).
- Máximo inicial: 1 comando de teste direcionado.
- Preferir arquivo específico e/ou -k.
- Se passar, PARAR imediatamente.
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

## Mecanismos de controle a preservar

Nunca remova, contorne ou enfraqueça:

- Safety Gate
- Quality Gate
- Growth Mode
- Regra de Single PRIMARY

## Proibições absolutas

Nenhuma das ações abaixo pode ser realizada, **exceto** com autorização humana explícita
e específica para aquela operação:

- Ativar integração com TikTok sem homologação explícita.
- Ativar o MPT Auto Upload.
- Publicar conteúdo real sem autorização explícita.
- Alterar o ambiente de produção sem autorização explícita.
- Ler, exibir, copiar, versionar ou modificar secrets, tokens, API keys, credenciais ou
  quaisquer valores sensíveis de `config.toml`.
- Expor tokens, API keys ou credenciais em código, logs, commits ou respostas.
- Usar `git reset`, `git restore`, `git clean`, force push ou `--force-with-lease`.

## Antes de commit

1. Executar `git status`.
2. Revisar o diff das mudanças.
3. Executar o teste mínimo diretamente relacionado (conforme TEST POLICY), se aplicável.

## Antes de push

1. Confirmar a branch atual.
2. Confirmar que o worktree está limpo/esperado.
3. Nunca reescrever histórico compartilhado.

## Deploy

Nunca execute deploy por conta própria.

## Ambientes

- Produção: `C:\Projetos\MoneyPrinterTurbo`
- Desenvolvimento principal: `D:\Projetos\MoneyPrinterTurbo`

## Publicação e automação

- O Scheduler é o único caminho automático de publicação.
- Em qualquer ciclo autônomo, preserve a regra: **uma transição operacional principal por ciclo**.
