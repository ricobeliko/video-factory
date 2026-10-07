# CONTEXT — Video Factory / MoneyPrinterTurbo

> **Documento de Contexto Operacional e Estratégico**
> Atualizado em: 07/10/2026

---

## 1. Estado Atual Canônico

- **CURRENT_FOCUS** = `LOCAL_AI_BRAIN_AND_VIDEO_QUALITY`
- **CURRENT_FOCUS** = `LOCAL_AI_BRAIN_AND_VIDEO_QUALITY`
- **CURRENT_PHASE** = `V1.4C_LOCAL_AI_SHADOW_RUNNER`
- **PROJECT_STATUS** = `ACTIVE_DEV / V1.4B_CONCLUDED / V1.4C_SHADOW_IMPLEMENTED`
- **ACTIVE_BRANCH** = `feat/v1-4a-local-ai-lab`
- **NEXT_GATE** = `LOCAL_AI_SHADOW_VALIDATION_OR_INTEGRATION_GATE`
- **DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT** = 6
- **LOCAL_AI_MODE** = `off` (DEFAULT = off; shadow disponível para testes/lab; active NÃO habilitado)
- **LOCAL_AI_VIABLE** = `YES`
- **BLOCKED_BY** = `NONE`

> [!WARNING]
> **ESTADO DE PRODUÇÃO:** O LOCAL AI ainda **NÃO ESTÁ ATIVO** no pipeline de produção. O modo padrão é `off`. Em modo `shadow`, o Local Brain apenas observa e persiste métricas analíticas no SQLite sem alterar decisões operacionais, sem substituir roteiros oficiais e sem publicar vídeos.

### Implementação da V1.4C (Local AI Shadow Runner):
- **V1.4C_LOCAL_AI_SHADOW_RUNNER** = IMPLEMENTADA & TESTADA (22/22 tests pass)
- **Componentes Entregues:**
  - `LOCAL_AI_MODE`: Suporte nativo a modos `off|shadow|active` (padrão: `off`).
  - `LocalAIShadowRunner`: Executor isolado que roda o Local Brain (Qwen3-8B + FactGuard) em paralelo sem efeitos colaterais.
  - Zero Impacto em Produção: Se o servidor local estiver offline, o erro é capturado e persistido na auditoria, mantendo o pipeline principal 100% intacto (fail-safe total).
  - Estimativa de Duração: Medição de palavras faladas em pt-BR (`count_spoken_words`, `estimate_duration_seconds`) comparando duração declarada vs estimada.
  - Persistência e Reuso: Tabela `local_ai_shadow_runs` criada idempotentemente em `storage/video_factory.db` (nenhum banco novo criado).
  - Higienização: Bloqueio estrito de gravação de tokens, chaves ou senhas em mensagens de erro (`sanitize_message`).
  - Script para PC Forte: `scripts/start_local_ai_server.ps1` portável com aceleração Vulkan GPU (RX 580) estritamente em `127.0.0.1:8089` (bind 0.0.0.0 terminantemente bloqueado).

### Validação Concluída da V1.4B (Local Brain + FactPack + FactGuard):
- **V1.4B_LOCAL_BRAIN_FACT_GUARD** = CONCLUÍDA
- **Componentes Entregues:**
  - `LocalAIProvider`: HTTP client leve (urllib, zero dependências externas), compatível com OpenAI (`/v1/chat/completions`), localhost restrito por padrão, fail-closed e timeouts explícitos.
  - `FactPack`: Modelo de fatos canônicos atômicos com validação de IDs únicos e formatação para prompt.
  - `GroundedContent`: Geração de roteiro, hooks e cenas com rastreabilidade de IDs de fatos.
  - `FactGuard`: Auditor pós-geração com modelo crítico (`temperature=0.0`), tolerância zero a afirmações inventadas (`unsupported_claims`), com política estrita de fail-closed e no máximo 1 tentativa de reescrita.
  - `LocalAIRouter`: Roteamento mínimo desacoplado entre papéis `FAST` (metadata, classificação, tags) e `QUALITY` (roteiro, crítica, planejamento de cenas).

### Validação Concluída da V1.3 (Agente Diretor & Multi-Nicho):
- **V1.3_AGENT_DIRECTOR** = CONCLUÍDA
- **VÍDEO REAL PRODUZIDO** = `storage/manual_media/terra_parou_5s/final/terra_parou_5s_final.mp4` (69s, 25.28 MB)
- **NICHO VALIDADO** = `curiosidades_ciencia` (multi-nicho comprovado)
- **COMPOSIÇÃO HÍBRIDA** = 4 clipes Google Flow Premium preservados + 4 cenas stock filler resolvidas contextualmente via Coverr.
- **NOVO PADRÃO VISUAL DEFINIDO** = `DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT = 6` (6 cenas Flow por Short para produções futuras, com seleção distribuída de maior impacto visual; demais cenas via Coverr).

### Validação Concluída da V1.2 (Otimização do Fluxo Manual):
- **V1.2_FLOW_OPTIMIZATION** = CONCLUÍDA
- **WORKFLOW_RUNNER** = `scripts/flow_workflow.py`
- **TESTES_DIRECIONADOS** = 3 PASS (`test/services/test_flow_workflow.py` in 0.07s)
- **MELHORIAS ENTREGUES**:
  - Preparação automatizada de prompts cinematográficos para Google Flow (9:16 vertical, `prompts_for_flow.md`).
  - Divisão de cenas temporizada e alinhamento com a narração via `scene_planner`.
  - Padronização da estrutura de diretório (`manifest.json`, `clips/flow_scene_XX.mp4`).
  - Ingestão simplificada e montagem em comando único (`python scripts/flow_workflow.py render <dir>`), com suporte a `--dry-run` e fallback híbrido automático para estoque stock da Video Factory.
  - Zero alteração no core da aplicação.

### Validação Concluída da V1.1 (Primeiro Vídeo Real):
- **V1.1_FIRST_REAL_VIDEO** = CONCLUÍDA
- **QUALITY_BASELINE** = APROVADA
- **PUBLICÁVEL** = SIM
- **DURATION** = 90.50s
- **V1.1 runner final** = `scripts/run_v1_1_flow_jfk_video.py`
- **Commit funcional de referência** = `65ff981`

---

## 2. Objetivo da Frente de Qualidade Visual

Melhorar significativamente a qualidade visual dos vídeos produzidos pela fábrica utilizando **Google AI Pro / Google Flow / Nano Banana** como geração visual externa, mantendo a **Video Factory (MoneyPrinterTurbo)** como o núcleo orquestrador e produtor responsável por:

- **Roteiro:** geração de script estruturado por cenas.
- **Narração:** síntese de voz TTS neural e temporização de áudio.
- **Montagem:** composição final dos clipes, alinhamento temporal e renderização.
- **Legendas:** renderização de legendas dinâmicas ou nativas (formato ASS / burn-in).
- **Música:** trilha sonora de fundo e mixagem de áudio.
- **Publicação:** gestão de canais, metadados e publicação automatizada no YouTube.

---

## 3. Filosofia Operacional: "FAZER MENOS"

Todas as tarefas desta frente devem seguir rigorosamente os seguintes princípios:

1. **Fazer menos:** não construir código ou processos além do estritamente necessário.
2. **Sem arquitetura excessiva:** não criar camadas de abstração prematuras ou especulativas.
3. **Sem testes redundantes:** executar somente testes diretamente relacionados às alterações; alterações puramente documentais não disparam testes (`pytest`).
4. **Sem gates desnecessários:** eliminar burocracias que atrasem a entrega de resultados reais.
5. **Não reconstruir o que já existe:** reaproveitar integralmente a infraestrutura consolidada da Video Factory.
6. **Se funcionou, considerar concluído:** evitar loops de polimento desnecessários.
7. **Não pedir aprovação de cada comando:** agir com autonomia técnica dentro dos limites seguros do projeto.
8. **Não criar infraestrutura especulativa:** implementar apenas o que for exigido pelo passo imediato.
9. **Priorizar solução pronta:** preferir ferramentas, scripts e fluxos já existentes e validados.

---

## 4. Separação Estrita de Ambientes: DEV-FIRST / PRODUCTION-LAST

O projeto opera sob a regra mandatória **DEV-FIRST / PRODUCTION-LAST** em dois ambientes físicos totalmente distintos. **NUNCA misturar os dois ambientes:**

| Ambiente | Host / Máquina | Diretório Raiz | Função |
| :--- | :--- | :--- | :--- |
| **DEV** | Notebook (Desenvolvimento) | `D:\Projetos\MoneyPrinterTurbo` | Todo desenvolvimento, criação de scripts, validações locais, experimentação e testes pontuais. |
| **PRODUÇÃO** | PC Forte (Produção) | `C:\Projetos\MoneyPrinterTurbo` | Ambiente de produção: execução autônoma, render oficial, agendador (`Scheduler`) e publicação ativa. |

### Regras Mandatórias de Operação:
1. **Todo desenvolvimento ocorre no NOTEBOOK:** `D:\Projetos\MoneyPrinterTurbo`.
2. **O PC FORTE é ambiente de produção:** `C:\Projetos\MoneyPrinterTurbo`.
3. **Sem experimentação no PC Forte:** Não implementar, experimentar ou fazer investigação exploratória no PC Forte quando isso puder ser feito no notebook.
4. **Critérios estritos de promoção:** Só levar alterações ao PC Forte quando:
   - A implementação estiver pronta e validada no notebook; ou
   - Houver um teste que dependa especificamente do ambiente de produção.
5. **Sem sincronizações parciais:** Não sincronizar mudanças parciais apenas para testar hipóteses.
6. **Isolamento absoluto:** Sempre preservar a regra: nunca misturar os dois ambientes.

---

## 5. Delimitação de Modelos e Escopo

- **Google Flow API:** **NÃO integrar neste momento.** Primeiro devemos produzir vídeos reais manualmente no Google Flow para vivenciar e aprender o workflow na prática antes de qualquer automação.
- **MuseTalk local (RX580 + DirectML):** POC já concluída com sucesso. Fica **estritamente congelado** como laboratório e fallback futuro. Não trabalhar nele nesta fase.
- **Modelos/Serviços fora de escopo:** Krea, HeyGen pago e ElevenLabs vídeo estão formalmente fora do escopo atual.
- **Hardware Generativo Local:** Geração pesada de vídeo localmente na GPU atual não é recomendada; foco total em geração externa via Google Flow.

---

## 6. Roadmap da Nova Frente
 
```text
V1.1 (Concluída) ──> V1.2 (Concluída) ──> V1.3 (Concluída) ──> V1.4 (Atual: Avaliação Automação) ──> Futuro
```

- **V1.1 — Primeiro Vídeo REAL (CONCLUÍDA):**
  - Produzido e aprovado o vídeo completo de JFK com 90.50s de duração.
  - 4 clipes premium Google Flow + clipes stock/cache da Video Factory para preenchimento.
  - Narração, legendas, áudio e formato 9:16 (1080x1920) 100% validados.
- **V1.2 — Otimizar Passos Manuais (CONCLUÍDA):**
  - Entregue utilitário padronizado `scripts/flow_workflow.py` com `prepare`, `status` e `render`.
  - Preparação automatizada de prompts visuais para Google Flow (9:16 portrait em `prompts_for_flow.md`).
  - Divisão de cenas temporizada e alinhamento via `scene_planner`.
  - Organização de arquivos em `manifest.json` e `clips/flow_scene_XX.mp4`.
  - Ingestão em comando único com `--dry-run` e fallback híbrido para estoque stock.
  - Testes: 3 PASS em `test/services/test_flow_workflow.py`.
- **V1.3 — Agente Assistente de Cenas & Prompts (CONCLUÍDA):**
  - Agente atuando como diretor na divisão de cenas, prompts e manifesto estruturado no nicho `curiosidades_ciencia`.
  - Render real validado: `terra_parou_5s_final.mp4` (69s).
  - Padrão visual consolidado: 6 cenas Flow por Short (`DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT = 6`) com seleção distribuída; stock filler contextual via Coverr.
- **V1.4 — Avaliação de API & Automação (CURRENT_PHASE):**
  - Avaliar viabilidade de automação e integração de API do Google Flow.

### Visão e Diretrizes Futuras:
- **FUTURE_MULTI_CHANNEL_MULTI_NICHE** = planned
  - **Arquitetura Mandatória:** Uma ÚNICA Video Factory atendendo múltiplos canais, perfis e nichos, sem criar aplicações separadas para cada canal.
- **FUTURE_LONG_FORM_VIDEO** = planned
- **FUTURE_FLOW_API_AUTOMATION** = evaluate_later
- **FUTURE_LOCAL_VIDEO_AI** = evaluate_after_hardware_upgrade (GPU dedicada)

---

## 7. Documentação Canônica de Referência

A documentação detalhada e histórico completo de engenharia residem em `docs/`:

- [docs/PROJECT_HANDOFF.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/PROJECT_HANDOFF.md) — Estado consolidado dos componentes, deploys e backlog.
- [docs/ROADMAP.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/ROADMAP.md) — Linha do tempo de todas as fases e evolução do sistema.
- [docs/PRODUCTION_RUNBOOK.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/PRODUCTION_RUNBOOK.md) — Procedimentos operacionais seguros em produção (PC Forte).
- [docs/DOCUMENTATION_POLICY.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/DOCUMENTATION_POLICY.md) — Regras de governança de documentação para agentes e desenvolvedores.
