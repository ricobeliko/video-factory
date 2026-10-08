# ROADMAP — Video Factory / MoneyPrinterTurbo

## Política atual de validação

- Testes massivos registrados em fases antigas são EVIDÊNCIA HISTÓRICA, não obrigação futura.
- Menções antigas a "regressão de 22 suítes", centenas de testes ou full regression NÃO são gates automáticos.
- Validação padrão atual = teste direcionado mínimo.
- Full regression exige autorização humana explícita.
- Esta política prevalece sobre registros históricos de validação de fases anteriores.

---

# Estado Atual Canônico — 08/10/2026

- **CURRENT_FOCUS** = `VIDEO_QUALITY_GOOGLE_FLOW`
- **CURRENT_PHASE** = `V1.5_VISUAL_DIRECTOR`
- **PROJECT_STATUS** = `ACTIVE_DEV / V1.4_CONCLUDED`
- **ACTIVE_BRANCH** = `feat/v1-4c-flow-pipeline-integration`
- **NEXT_GATE** = `V1.5_VISUAL_DIRECTOR`
- **DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT** = 6
- **LOCAL_GENERATIVE_VIDEO_GPU_STATUS** = `NOT_RECOMMENDED_ON_CURRENT_HARDWARE (MuseTalk/RX580 frozen as lab/fallback)`
- **BLOCKED_BY** = `NONE`

> [!IMPORTANT]
> **Precedência Canônica:** Esta seção reflete o estado real, auditado e vigente da fábrica de vídeos. Ela prevalece formalmente sobre quaisquer menções, metas pendentes ou notas de snapshots históricos mantidos nas seções inferiores para rastreabilidade de engenharia.

## Status Consolidado por Componente

- **Google Flow / External Video Quality Track** = ACTIVE (CURRENT_FOCUS)
- **V1.1 First Real Video Workflow** = CONCLUÍDA / HOMOLOGADA
- **V1.2 Manual Flow Optimization** = CONCLUÍDA / HOMOLOGADA (`scripts/flow_workflow.py`)
- **V1.3 Agent Director Assistance** = CONCLUÍDA / HOMOLOGADA (vídeo `terra_parou_5s_final.mp4` gerado no nicho `curiosidades_ciencia` com 4 clipes Flow + fallback Coverr; novo padrão estabelecido para 6 cenas Flow por Short)
- **V1.4 Autonomous Flow Pipeline** = CONCLUÍDA / HOMOLOGADA (Playwright 1.63.0 + Edge `msedge`, single-flight, idempotência, resume, checkpoint atômico, recovery pós-consumo, multi-tile isolation, source-aware Flow/stock, fallback configurável)
- **V1.5 Visual Director** = PLANNED (NEXT_PHASE)
- **V16.0 Quality Audit** = DONE
- **V16.1 Brazilian Content Contract** = PRODUCTION HOMOLOGATED (Deploy SHA: `3983d37a29d1f169e513f19bd7186348a74ad5e9`)
- **V16.2 Subtitle Reliability Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `0744fd2b8593fa276a2d3117d88b270475b5b05c`)
- **V16.3 Final Media Quality Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `9e3fde0b35e28781aab67117d5ff33c182b337ef`)
- **V16.4 Scene-Based Video Generation** = PRODUCTION HOMOLOGATED
- **V16.4.1A Scene Render Performance Hardening** = PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **V16.4.1B Final Render Performance** = PRODUCTION HOMOLOGATED (Deploy SHA: `e7f40ed6f4b7df45e5868cd7de03495239d103ec`, Task Homologada: `f9a9608b-512d-43c4-92f4-f864a0424512`)
- **V16.4.1C Render Pipeline Gap Instrumentation** = PRODUCTION HOMOLOGATED (Deploy SHA: `d231e3900bbbace180c0c71e60e9fb08c2d713e0`, Task Homologada: `337639bb-1740-4398-a923-c5f75b1f236a`)
- **V16.4.1D Post-Encode Performance Investigation** = ACTIVE
- **V16.5 Visual Matching v2** = MERGED (PR #53, SHA `b6e900ed93edb6e0e59c00600532f7ca2afeb6bd`)
- **V16.5.1 Subtitle & Narration Quality Recovery** = MERGED (PR #54, SHA `4823a799d3030982d27e0eeccea1ab3f73a065f7`)
- **V16.6 Hybrid Visual Generation Foundation** = MERGED (PR #55, SHA `ae988e76777b0ab879385c33807361090990c45e`)
- **V16.6.1 Hardware-Aware Open Source Benchmark** = DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS
- **V16.6.2 Contextual Image-to-Video Foundation** = MERGED (PR #56, SHA `0264fb7daaf327e1677cc209cd20308a9af6c8ce`)
- **V16.7 Hybrid Scene Director** = MERGED (PR #57, SHA `ae6738821516d3310493060654d4a8776bc74548`)
- **V16.8 Controlled Hybrid Render Validation** = DEV_VALIDATED / STRUCTURAL_AND_PROXY_PASS (PR #58, SHA `fd205f24275a43ab67486e9261cd6b45cfbfd4d8`)
- **V16.8.1 Real Generated Image Quality Gate** = REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED
- **V16.8.2 Alternative Visual Sources Evaluation** = DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)
- **V16.9 Final Hybrid Pipeline Foundation** = DEV_COMPLETE / CONSOLIDATED
- **V16.10 Single Full DEV Render** = DEV_HOMOLOGATED / READY_FOR_PRODUCTION_DEPLOY
- **V16.11 Adaptive Visual Feedback** = MERGED (PR #64, SHA `894aea6`)
- **V16.12 Upstream v1.3.8 Selective Backport** = DEV_HOMOLOGATED / READY_FOR_V1_3_8_SELECTIVE_PRODUCTION_DEPLOY
- **V12-E Autonomous Production** = PRODUCTION HOMOLOGATED
- **V12-F.1 Analytics Auto Collection** = PRODUCTION HOMOLOGATED
- **V12-F.2 Closed Feedback Loop** = IMPLEMENTED / ACTIVE / PRODUCTION HOMOLOGATED
- **V12-F.3 Per-Channel Learning Isolation** = IMPLEMENTED / ACTIVE
- **V12-F.4 Second Channel Warm-Up** = PRODUCTION HOMOLOGATED
- **V12-F.5 Multi-Channel Capacity** = IMPLEMENTED / ACTIVE
- **V13-A Safe Update Foundation** = MERGED
- **V13-A.1 Backup JSON Capture Hotfix** = MERGED
- **V13-B Safe Production Update** = PRODUCTION HOMOLOGATED
- **V14-A Copyright Audit** = COMPLETED
- **V14-B Copyright Baseline Hardening** = PRODUCTION HOMOLOGATED
- **V14-B.1 Legacy Stock Quarantine** = PRODUCTION HOMOLOGATED
- **V14-B.2 Copyright Status + Closed Feedback Loop Exclusion** = PRODUCTION HOMOLOGATED
- **V14-B.2.1 Copyright UI Feedback** = PRODUCTION HOMOLOGATED
- **V14-C Presenter Framework** = MERGED BUT DORMANT
- **V14-C.1 / C.2 Presenter Expression Framework** = MERGED BUT DORMANT
- **V14-C.3 Nox Foundation** = EXPERIMENT ARCHIVED / DORMANT
- **Presenter autonomous**: OFF
- **avatar_mode**: `none`
- **TikTok**: OFF / NOT HOMOLOGATED
- **V15-A Production Observability Baseline** = DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET

## Produção Atual (Estado Operacional Consolidado)

- **PC forte** = autoridade de produção (`C:\Projetos\MoneyPrinterTurbo`)
- **Scheduler** = ON
- **Auto Publish** = ON
- **Dry Run** = OFF
- **YouTube** = ON
- **TikTok** = OFF
- **Autonomous Production** = ON
- **Analytics Auto** = ON
- **Closed Feedback Loop** = ON
- **Growth Mode** = WARMUP
- **MPT Auto Upload** = OFF
- **Presenter/Nox** = OFF
- **Multi-profile autonomous worker** = ACTIVE
- **Copyright provenance gate** = ACTIVE
- **Copyright status exclusion** = ACTIVE
- **Safe updater** = ACTIVE

**Safe updater oficial:**
`scripts/update_production.ps1`
Fluxo mandatário: Preflight → Backup SQLite → integrity_check → Stop → Fast-Forward Update → Start → Health Check → Rollback automático se necessário. Proibido git pull manual como fluxo padrão.

**Última homologação real de produção (V13-B):**
- **TARGET/FINAL_SHA:** `46e44c2495a8fe38484977ad1aa7cff439e26679`
- **BACKUP:** PASS (`storage/backups/database/video_factory_20260923_061728.db`, SHA-256: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`)
- **SQLITE_INTEGRITY:** OK
- **STOP:** PASS
- **FF UPDATE:** PASS
- **START:** PASS
- **HEALTH:** PASS — HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`
- **ROLLBACK:** NOT_REQUIRED
- **DEPLOY:** SUCCESS
- **Documentação posterior:** main `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`

---

# V15 — Production Observation & Optimization

**Status:** OPEN / OBSERVATION FIRST

## Objetivo
Observar a fábrica completa em funcionamento real no PC forte antes de adicionar grandes features.

A V15 deve medir se o sistema atual está:
- produzindo de forma autônoma e sustentável
- aprovando dentro dos critérios de Safety, Quality e Copyright
- estocando adequadamente por perfil
- agendando dentro das janelas operacionais
- publicando com sucesso no YouTube
- coletando métricas de analytics pontualmente
- aprendendo com o Closed Feedback Loop sem sobreajuste
- mantendo isolamento estrito por canal
- respeitando direitos autorais e políticas de conteúdo
- respeitando limites de custo e volume (Cost Guard)

## Princípio Fundamental da V15
A V15 **NÃO** deve começar criando novas features ou alterando parâmetros de forma especulativa.

Fluxo metodológico:
> **OBSERVAR → MEDIR → IDENTIFICAR GARGALO REAL → PRIORIZAR → OTIMIZAR**

Evitar rigorosamente:
- Otimização prematura
- Adição de novos provedores sem necessidade
- Novo avatar ou insistência no Nox neste ciclo
- Criação de novos canais
- Ativação ou dependência de TikTok
- Aumento forçado de volume
- Alteração de thresholds sem evidência empírica coletada

---

## V15-A — Production Observability Baseline

**Status:** DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET

- **Implementação DEV Concluída:**
  - Serviço read-only: `app/services/production_observability.py`.
  - Função principal: `get_production_observability_snapshot()`.
  - CLI com saída JSON estrita e sanitizada: `python -m app.services.production_observability --json`.
  - Coleta passiva das 9 dimensões operacionais para `default` e `profile-historias-misterio`.
  - Alertas factuais observáveis (sem score arbitrário): `READY_STOCK_EMPTY`, `COPYRIGHT_BLOCKED`, `SCHEDULER_FAILURES_PRESENT`, `CLOSED_LOOP_BASELINE`, `ANALYTICS_STALE`, `GLOBAL_COST_GUARD_NEAR_LIMIT`.
  - Seção read-only no Operator Console: `"📊 Production Observability — V15"` com visualização lado a lado.
  - Zero mutações, zero alteração de schema, zero network.
  - Validação direcionada: 7 testes PASS (`test/services/test_production_observability.py`).
- **Próximo Gate:** Deploy seguro via `scripts/update_production.ps1` e execução read-only no PC forte.

### Objetivo
Criar um diagnóstico PASSIVO e estruturado do comportamento real dos dois canais em produção contínua:
- **Canal Principal:** `profile_id = default`
- **Canal Secundário:** `profile_id = profile-historias-misterio`

### 9 Dimensões de Observação Passiva:
1. **Autonomous Production:** Estado, último ciclo, geração atual, waiting task, estoque pronto por perfil.
2. **Scheduler:** Contagem de posts agendados, publicados, com falha, em retry e próximos slots por canal.
3. **Gates:** Telemetria de aprovação e rejeição nos gates de Safety, Quality e Copyright Provenance.
4. **Produção 24h:** Tentativas (attempts), aprovações, rejeições e principais motivos agregados e por perfil.
5. **Publicações:** Sucessos, falhas, visibilidade (público comprovado) e status de direitos autorais (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`).
6. **Analytics:** Snapshots coletados, idade do último fetch, provider utilizado e erros de coleta.
7. **Closed Feedback Loop:** Modo atual (baseline/adaptive), quantidade de amostras elegíveis, decisões recentes de tema/estrutura narrativa, razões de fallback e garantia de isolamento por canal.
8. **Multi-Channel:** Confirmação de que a seleção visual da UI no Operator Console NÃO controla nem interfere no worker em background, e confirmação de atividade independente dos perfis.
9. **Cost Guard:** Validação do cumprimento dos limites por perfil (WARMUP / SCALE) e do limite mestre global, garantindo ausência de explosão de chamadas ou gastos descontrolados.

### Critérios de Aceite para V15-A:
V15-A será considerada concluída com sucesso quando conseguirmos obter, de forma estritamente passiva e sem alterar o estado da produção:
- Status operacional dos dois perfis
- Estoque de cada perfil
- Estado do scheduler
- Histórico das últimas publicações
- Últimas métricas de analytics
- Status de copyright das publicações ativas
- Estado do Closed Feedback Loop por perfil
- Contadores de produção em 24h
- Principais problemas e rejeições recentes identificados

*Preferência técnica:* Reutilizar o Operator Console e serviços de diagnóstico existentes (`production_health.py`, `operator_console.py`). Zero adições de tabelas ou alterações de schema no SQLite sem necessidade comprovada.

### Próximas Decisões (Pós V15-A):
Somente após a consolidação da observação real e identificação de gargalos empíricos serão priorizadas as frentes de evolução:
- Otimização de geração
- Melhoria de hooks e roteiros
- Diversidade visual
- Qualidade de assets
- Frequência de publicação
- Estratégia dedicada por canal
- Monetização
- Revisão de fornecedores de stock/áudio
- Melhorias na UI/UX do Operator Console

*Não antecipar decisões nem escolher caminhos prioritários antes das medições da V15-A.*

---

## V13-B — Production Homologation / Safe Remote Deployment Active — 23/09/2026

Homologação real executada com sucesso no PC forte de produção (`C:\Projetos\MoneyPrinterTurbo`) utilizando `scripts/update_production.ps1` com o hotfix de captura de JSON (V13-A.1).
Status: **PRODUCTION HOMOLOGATED**.

- **Evidência Operacional Real:**
  - `CURRENT_SHA`: `e3f024938c5338c197a1f1654775686227f3eb05`
  - `TARGET/FINAL_SHA`: `46e44c2495a8fe38484977ad1aa7cff439e26679`
  - `BACKUP`: PASS
  - `BACKUP_FILE`: `storage/backups/database/video_factory_20260923_061728.db`
  - `BACKUP_SHA256`: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`
  - `SQLITE_INTEGRITY`: OK
  - `SAFE_STOP`: PASS (`schtasks /End /TN "VideoFactory Production"`)
  - `FAST_FORWARD_UPDATE`: PASS (`git merge --ff-only 46e44c2495a8fe38484977ad1aa7cff439e26679`)
  - `SAFE_START`: PASS (`schtasks /Run /TN "VideoFactory Production"`)
  - `HEALTH`: PASS — HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`
  - `ROLLBACK`: NOT_REQUIRED
  - `DEPLOY_STATUS`: DEPLOY_SUCCESS
- **Histórico e Status Consolidado dos Componentes:**
  - `V13-A` = MERGED
  - `V13-A.1` = MERGED (hotfix de separação de stdout e stderr no backup)
  - `V13-B` = PRODUCTION HOMOLOGATED
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT / OFF (`avatar_mode="none"`)
- **Novo Contrato Operacional Obrigatório:**
  - Todas as atualizações futuras da produção devem usar estritamente `scripts/update_production.ps1`.
  - Fluxo oficial obrigatório: Preflight -> Backup SQLite -> integrity_check -> Stop -> Fast-Forward Update -> Start -> Health Check -> Rollback automático se necessário.
  - Proibido uso de git pull manual ou intervenção destrutiva como fluxo padrão.


## V13-A — Safe Update Foundation — 23/09/2026

Implementação concluída em desenvolvimento: fundação para atualização remota e headless segura da produção via `scripts/update_production.ps1`.
Status nesta fase: **MERGED** (V13-A e V13-A.1 homologados na V13-B).

- **Pipeline Seguro:** `PRE-FLIGHT -> BACKUP -> STOP -> UPDATE FF-ONLY -> START -> HEALTH CHECK -> SUCCESS`.
- **Pre-flight Fail-Closed:** Valida repo Git, working tree limpa (sem alterações não commitadas ou arquivos críticos untracked), ambiente virtual (.venv), existência e resolução de `CURRENT_SHA` e `TARGET_SHA`. Flag `-PreflightOnly` executa apenas diagnósticos e exibe o plano sem mutações.
- **Fast-Forward Only:** Validação prévia estrita via `git merge-base --is-ancestor`. Zero merges ou rebases automáticos.
- **Backup Transacional Pré-Stop:** Criação de snapshot do SQLite via `app.services.production_backup` com `PRAGMA integrity_check` obrigatório e hash SHA-256 registrado antes de parar o serviço.
- **Parada e Inicialização Seguras:** Controle exclusivo via Scheduled Task do Windows (`schtasks /End` e `schtasks /Run`), aguardando encerramento sem matar processos aleatórios.
- **Health Check Delimitado:** Verificação com timeout finito (75s) em `http://127.0.0.1:8501/_stcore/health` aguardando HTTP 200 e corpo contendo `ok`.
- **Rollback Não-Destrutivo:** Se o health check pós-update falhar, a Scheduled Task é parada, a working tree é retornada para `CURRENT_SHA` via `git switch --detach CURRENT_SHA` (zero `git reset`, `git restore` ou `git clean`, preservando a branch `main`), e a aplicação é reiniciada. Se o health check pós-rollback passar: `ROLLBACK_SUCCESS`; se falhar: `ROLLBACK_FAILED` exigindo intervenção humana.
- **Lock e Logging Local Sanitizado:** Lock exclusivo em `storage/locks/update_production.lock` com limpeza em bloco `finally`. Logs timestampados em `logs/deploy/` sem exposição de credenciais, tokens ou dumps de configuração.
- **Ambientes e Status Vigentes:**
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT
  - Produção física (`C:\Projetos\MoneyPrinterTurbo`) homologada no commit `46e44c2`.
- **Próxima Fase Global:** V15 — Production Observation & Optimization.


## V14-B.2 — Manual Copyright Status + Closed Feedback Loop Exclusion — 23/09/2026

Implementação concluída em desenvolvimento: rastreamento persistente e auditável de status de direitos autorais por publicação/tarefa (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`), com fail-closed para o Closed Feedback Loop.

- **Status de Direitos Autorais Auditáveis:** `set_publication_copyright_status_op` e `get_publication_copyright_status` persistidos em `operational_events` com metadata estruturado completo (`task_id`, `publication_event_id`, `platform`, `external_id`, `copyright_status`, `source='operator'`, `timestamp`, `note`).
- **Zero Schema Change:** Reutiliza `operational_events` existente sem migrações ou tabelas novas. Idempotente quando o mesmo status e nota são reaplicados.
- **Regra Crítica do Closed Feedback Loop:**
  - `clean_manual`: elegível do ponto de vista de copyright (pode compor amostras de aprendizado).
  - `claimed`, `blocked`, `strike`: SEMPRE EXCLUÍDOS.
  - `unknown` (incluindo publicações legadas sem status): FAIL CLOSED (EXCLUÍDOS).
  - Razões explícitas de auditoria registradas: `copyright_unknown`, `copyright_claimed`, `copyright_blocked`, `copyright_strike`.
- **Preservação de Dados:** Nenhum evento de publicação, métrica de analytics ou histórico de tarefas é apagado ou modificado.
- **Operator Console:** Exibição clara no card Copyright / Assets com badges de status, source e elegibilidade do loop, além de formulário auditável não-destrutivo para o operador marcar status manualmente (PRIMARY only).
- **Vídeo Bloqueado Conhecido:** Fluxo preparado para marcação manual pós-deploy da task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) como `blocked`.
- **Presenter:** DORMANT (experimento arquivado em branch separada, produção e main mantidas com `avatar_mode="none"`).
- **Próxima fase subsequente:** V13 (concluída e homologada na V13-B); Fase global atual: V15.


## V12-E.3 — gate DEV controlado — 21/09/2026

Hardening independente da V12-F.2: estoque YouTube recuperável por persistência,
fila de múltiplas aprovações e seleção de uma ação por ciclo. WARMUP sem slot
permite reposição até a meta 3, mantendo uma geração/ciclo e cinco/24h.
Deduplicação persistente de eventos Growth e cooldown de retry de 15 minutos.
Sem mudança de schema, Growth Mode, Auto Publish, publicação direta ou TikTok.

Implementação e validação DEV concluídas: **600 testes + 32 subtestes passaram**
em 23 suítes (246,12s), com geração fake e rede bloqueada; 16 testes novos E.3.
Próximo gate: revisão do diff E.3 isolado.
Sem commit/push/deploy e sem acesso à produção. A fase V12-F.2 permanece separada.

## [HISTORICAL SNAPSHOT / SUPERSEDED] Estado vigente — 21/09/2026

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o estado histórico em 21/09/2026. As fases V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Isolation), V12-F.4 (Second Channel Warm-Up), V12-F.5 (Multi-Channel Capacity), V13-A/A.1/B (Safe Production Update) e V14-A/B/B.1/B.2/B.2.1 (Copyright Hardening) foram posteriormente implementadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece.

V12-E e V12-F.1A/B/C HOMOLOGADAS EM PRODUÇÃO na baseline `54875c6`, conforme
evidências do operador. YouTube Data API, fetch e persistência real homologados.
Factory/PRIMARY headless/Scheduler ativos; Autonomous ON, Auto Publish ON,
Analytics Auto ON (1 fetch/ciclo, 300s), Dry Run OFF, YouTube ON, TikTok OFF,
Growth Mode WARMUP e MPT Auto Upload OFF. Produção não acessada nesta implementação.

V12-F.2: implementação DEV em validação; sem deploy/homologação de produção.
Escopo MVP: tema/cluster e narrative_structure. Flag default OFF.
Reutiliza Analytics → evidência isolada → Content Strategy → Autonomous → VideoParams;
12 publicações, cinco por grupo, dois grupos; coorte 72–96h, histórico 60 dias;
medianas, estabilidade leave-one-out, bônus máximo cinco, diversidade persistida e
auditoria transacional. Não usa performance_score legado para eleger vencedores.
Schema NONE. Rollback funcional pela flag; nenhum histórico é removido.

Aceite DEV: testes de elegibilidade/privacidade/scope, gate, outlier, replay,
diversidade/restart, equivalência OFF, fail-safe e integração com submissão fake;
regressão das 22 suítes requeridas com rede bloqueada. Resultado final pendente da execução.
Próximos gates: revisão → autorização de deploy com flag OFF → homologação separada
→ autorização explícita de ativação. V12-F.3 mantém isolamento multicanal como fase formal;
V12-F.4/segundo canal e TikTok não são ativados por esta entrega.

Os marcos abaixo preservam histórico; snapshots OFF e baselines antigas não substituem
o estado vigente desta seção.


## V12-E.2.2 — Persistent Waiting Schedule Recovery (20/09/2026)

Hotfix V12-E.2.2 deployado e homologado em produção em 21/09/2026 com a aplicação em `66f92a4`. V12-E concluída; PUBLIC GATE = PASS, conforme evidências fornecidas pelo operador.

Causa raiz confirmada: após perda do MemoryState, WAITING_SCHEDULE enviava apenas `task_id`. O scheduler descartava o payload sem COMPLETE ou `video_file`, antes de resolver os destinos persistidos.

Correção: o retry verifica vídeo final existente e não vazio via `get_task_final_video()`, Safety PASS explícito, último Quality finito >= 70 com label GOOD/STRONG, YouTube em `task_platforms`, vínculo em `task_profiles`, perfil ativo e canal YouTube habilitado. Reconstrói o payload quando a memória está ausente/incompleta e preserva vetos de estado presentes em memória. Reutiliza o scheduler para Growth Mode e deduplicação por task/canal; envia somente YouTube.

Recuperação inválida mantém WAITING_SCHEDULE com `reason=waiting_recovery_failed` e diagnóstico na mensagem. Sem slot, permanece em espera; sucesso agenda e retorna. Nenhum desses caminhos gera outra task no mesmo ciclo. Auto Publish, TikTok, MPT Auto Upload, schema e thresholds de produção permanecem inalterados.

Validação: **234 testes + 19 subcasos PASS** nas oito suítes abaixo. Cenários novos: memória presente/ausente/incompleta, vídeo ausente/vazio, Safety BLOCK/REVIEW/ausente, Quality ausente/baixo/label inválido, perfil/canal/destino inválidos, slot WARMUP ocupado, idempotência e destinos terminais, one_shot com Autonomous OFF, nenhuma nova geração, Auto Publish OFF e exclusão de TikTok. Publicação é interceptada por mocks e conexões externas são bloqueadas nos novos retries. Sete testes legados do scheduler agora declaram SCALE apenas no SQLite temporário para verificar tetos técnicos; Growth Mode de produção não mudou.

```powershell
.venv/Scripts/python.exe -m pytest test/services/test_autonomous_production.py test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_quality_score.py test/services/test_operator_console.py test/services/test_single_instance.py test/services/test_schedule_cancellation.py test/services/test_production_health.py -q -p no:cacheprovider
```

Recuperação persistida homologada com publicação PUBLIC. Em futuros casos sem slot, aguardar Growth Mode; em `waiting_recovery_failed`, inspecionar o diagnóstico sem forçar COMPLETE nem limpar o waiting ID. Próximo passo: planejar a auditoria V12-F.1, sem alterar produção nesta tarefa.

---

**Atualizado em:** 21/09/2026

**Projeto:** Video Factory

**Base:** MoneyPrinterTurbo v1.3.7

---

## Visão do produto

Objetivo final: operar uma fábrica de vídeos curtos 24/7 no PC forte, com seleção de temas, geração, validação, agendamento, publicação pública no YouTube, coleta de analytics e realimentação da estratégia.

Princípio central:

> Segurança, qualidade e monetização têm prioridade sobre volume.

---

## Fases concluídas

- Base / Fundação ✅
- Publicação manual ✅
- Batch controlado ✅
- V2.1 Scheduler ✅
- V2.2 Scheduler Execution Engine ✅
- V3 Monetization Presets + Safety Gate ✅
- V3.1 Account Warm-Up / Growth Mode ✅
- V4 Trend Radar ✅
- V5 Analytics + Feedback Loop ✅
- V6 Quality Score ✅
- V7 Content Strategy / Optimization Engine ✅
- V8 Production Readiness / Operator Console ✅
- V8.1 Remote Operation & Single-Instance Safety ✅
- V9 Multi-Profile / Multi-Channel Management ✅
- V10 Automatic Analytics Providers ✅
- V11 Clip Mode / Long-form Repurposing ✅
- V12-A Production Host ✅
- V12-B Production Startup ✅
- V12-C Backup / Recovery ✅
- V12-D Schedule Cancellation Safety ✅
- V12-D.1 PRIMARY Guard ✅
- V12-D.2 Legacy Cancellation Compatibility ✅
- V12-E Autonomous Production Loop ✅ — homologada em produção; PUBLIC GATE PASS
- V12-F.1 Analytics Auto Collection ✅ — homologada em produção
- V12-F.2 Closed Feedback Loop ✅ — homologada em produção
- V12-F.3 Per-Channel Learning Isolation ✅ — implementada / ativa
- V12-F.4 Second Channel Warm-Up ✅ — homologada em produção
- V12-F.5 Multi-Channel Capacity ✅ — implementada / ativa
- V13-A Safe Update Foundation ✅ — merged
- V13-A.1 Backup JSON Capture Hotfix ✅ — merged
- V13-B Safe Production Update ✅ — homologada em produção
- V14-A Copyright Audit ✅ — concluída
- V14-B Copyright Baseline Hardening ✅ — homologada em produção
- V14-B.1 Legacy Stock Quarantine ✅ — homologada em produção
- V14-B.2 Copyright Status + Closed Feedback Loop Exclusion ✅ — homologada em produção
- V14-B.2.1 Copyright UI Feedback Hotfix ✅ — homologada em produção
- V14-C Presenter Framework ✅ — merged (dormant)
- V14-C.1 / C.2 Presenter Expression Framework ✅ — merged (dormant)
- V14-C.3 Nox Foundation ⏸️ — experiment archived / dormant

---

# V12-E — Autonomous Production Loop

**Status:** ✅ HOMOLOGADA EM PRODUÇÃO — 21/09/2026

Objetivo:
- detectar déficit de estoque
- selecionar tema
- gerar vídeo
- aplicar Safety Gate
- aplicar Quality Score
- abastecer Scheduler
- respeitar Growth Mode
- nunca publicar diretamente
- operar fail-closed

Regras atuais:
- Autonomous Mode default OFF
- máximo de 1 nova geração por ciclo
- máximo de 5 gerações / 24h
- intervalo normal de 15 min
- estoque-alvo: 3
- Quality mínimo: 70
- apenas GOOD / STRONG
- Safety precisa ser PASS explícito
- fontes autônomas permitidas: Pexels, Pixabay, Coverr
- TikTok bloqueado nesta fase

### V12-E.1 — Hardening
Status: ✅ concluído

### V12-E.1.1 — Provider / Stock Contract
Status: ✅ concluído

### V12-E.1.2 — Generation Config Contract
Status: ✅ concluído

### V12-E.2 — Homologação real
Status: ✅ homologada em produção

### V12-E.2.1 — One-cycle / One-transition Hotfix

Commit:
`08c644feb9677c4b3dd7567f50755ce7139da44c`

Status:
- ✅ implementado
- ✅ 197/197 testes PASS no PC forte
- ✅ deploy realizado
- ✅ homologação real concluída

Regra consolidada:

> Um ciclo autônomo deve executar apenas uma transição operacional principal.

---

## Homologação V12-E em produção — 21/09/2026

**V12-E HOMOLOGADA EM PRODUÇÃO. PUBLIC GATE = PASS.** Registro baseado nas evidências fornecidas pelo operador; nenhuma consulta ou alteração de produção nesta tarefa documental.

Produção atualizada para `66f92a4` antes da homologação. Commits: `fd57f84` (hotfix funcional V12-E.2.2), `66f92a4` (documentação/encoding), `de62a4b` (governança de agentes, sem necessidade de deploy para validar a aplicação).

Backup pré-deploy: `video_factory_20260921_014133.db`.
SHA-256: `79313b694f54000b57d704eadfc8a6e5b1871ac5198e95006ef4890cd82f44a5`.
Integridade: `ok`. Regressão em produção: **234 passed; 19 subtests passed; 0 failed**.

Task: `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`; Safety PASS; Quality 78.3; label GOOD.
Sem slot, permaneceu corretamente em WAITING_SCHEDULE. Após abertura de slot e deploy do hotfix, a task foi recuperada, sem geração indevida; `waiting_task_id` foi limpo e a task entrou no Scheduler.

| Evidência | Resultado |
| --- | --- |
| Scheduled Post | id=15; platform=youtube; profile_id=default; channel_id=channel-default-youtube |
| Estado final | published; attempts=0; last_error=None |
| Publication Event | id=16; status=success; platform=youtube |
| external_id | fTrkUqSnYqs |
| provider_request_id | 9f5c57e089314532a686492a47a74690 |
| external_url | https://www.youtube.com/watch?v=fTrkUqSnYqs |
| Gate visual | YouTube Studio confirmou VISIBILIDADE = PÚBLICO |

Fluxo real validado: Autonomous Production → geração → Safety Gate → Quality Gate → WAITING_SCHEDULE → recuperação persistida → Scheduler → Worker → Upload-Post → YouTube → PUBLIC.

Estado operacional atual: Factory RUNNING; Scheduler ON; Auto Publish ON; Dry Run OFF; YouTube ON; TikTok OFF; Growth Mode WARMUP; Autonomous Production ON; MPT Auto Upload OFF. Produção em modo autônomo contínuo.

Próxima fase (à época da homologação V12-E): **V12-F — Adaptive Learning + Multi-Channel Warm-Up**. *(Nota histórica: As fases V12-F, V13 e V14 foram subsequentemente homologadas em produção. O Estado Atual Canônico no topo prevalece).*

---

# [HISTORICAL SNAPSHOT / SUPERSEDED] V12-F — Adaptive Learning + Multi-Channel Warm-Up

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o planejamento inicial histórico da V12-F em 21/09/2026. As subfases V12-F.1 (Analytics Auto Collection), V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Learning Isolation), V12-F.4 (Second Channel Warm-Up) e V12-F.5 (Multi-Channel Capacity) foram subsequentemente implementadas, ativadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece formalmente sobre este registro.

Objetivo original: transformar o feedback de desempenho em um ciclo fechado de otimização, sem treinamento de pesos do modelo e sem sacrificar segurança, diversidade ou controle por canal.

## V12-F.1 — Analytics Auto-Collection Audit & Activation

**Status: HOMOLOGADA EM PRODUÇÃO.** V12-F.1A/B/C, fetch e persistência real homologados pelo operador em 21/09/2026; Analytics Auto ON na baseline `54875c6`.

Objetivo concluído: coleta automática de Analytics auditada, ativada e homologada.

Contratos da homologação:
- `analytics_scheduler.py`, integração do worker e settings atuais;
- `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED`;
- persistência de métricas e cooldowns por idade do vídeo;
- comportamento após reboot e nenhuma chamada duplicada;
- nenhuma coleta de vídeos privados;
- isolamento por profile/channel.

Gate F.1: PASS conforme evidências do operador. A implementação F.2 não altera essa ativação.

### V12-F.1A — Analytics Activation Hardening

**Status: ✅ HOMOLOGADA EM PRODUÇÃO (21/09/2026), baseline `54875c6`. Analytics Auto ON.**

Endureceu sete contratos em `analytics_scheduler.py` e `analytics_providers/*`: coleta automática restrita a YouTube; privacidade fail-closed (PUBLIC comprovado exigido; PRIVATE/UNKNOWN bloqueiam); deduplicação/revalidação de elegibilidade antes de cada chamada ao provider; exclusão mútua entre ciclo manual e automático via lock persistido; revalidação de backoff por publicação antes de cada fetch; sanitização de erros de rede/HTTP para nunca expor API key/token/query; `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED` como fonte real do default. Regressão: 338 passed, 19 subtests passed, 0 failed. Detalhes completos em `PROJECT_HANDOFF.md`.

### V12-F.1B — Headless Worker Bootstrap

**Status: ✅ implementada e HOMOLOGADA em produção (21/09/2026). Headless gate PASS.**

Bloqueador identificado durante V12-F.1A corrigido: `scripts/production_entrypoint.py` agora inicializa `operator_console.ensure_instance_initialized()` e, se PRIMARY, `scheduler.start_scheduler_worker(interval_seconds=30)` no MESMO processo que hospedará o Streamlit (`streamlit.web.bootstrap.load_config_options` + `.run`), antes de qualquer sessão de navegador conectar. `scripts/start_production.ps1` passou a chamar esse entrypoint em vez de `streamlit run` diretamente, preservando os mesmos parâmetros operacionais. SECONDARY nunca inicia o worker; shutdown libera worker e lock de forma idempotente. Regressão: 349 passed, 19 subtests passed, 0 failed. Gate headless homologado com evidências do operador: Scheduled Task Running, HTTP 200/ok, heartbeat do PRIMARY e `executor_last_tick` avançando sem navegador. Produção em `d1a8677`. Detalhes completos em `PROJECT_HANDOFF.md`.

### V12-F.1C — Publication Privacy Persistence

**Status: ✅ HOMOLOGADA EM PRODUÇÃO (21/09/2026), baseline `54875c6`. Analytics Auto ON.**

Cria fonte persistente e auditável de `privacy_status` em `publication_events` (migração aditiva/idempotente) e faz todos os caminhos de Analytics YouTube respeitarem essa evidência: publicação futura persiste o `privacyStatus` efetivamente usado; elegibilidade do Analytics automático prioriza o valor persistido com fallback legado para `task.json`, mantendo fail-closed (PRIVATE/UNLISTED/UNKNOWN bloqueiam); coleta manual (`fetch_real_metrics_for_publication`) agora exige PUBLIC comprovado antes de qualquer requisição real, para `persist=False` e `persist=True`; nova operação auditável `confirm_publication_privacy_op` no Operator Console permite homologar eventos legados (ex.: evento real 16) sem SQL manual, exigindo PRIMARY e validação exata do evento. Regressão das suítes exigidas: 329 passed, 19 subtests passed, 0 failed. Detalhes completos em `PROJECT_HANDOFF.md`.

## V12-F.2 — Closed Feedback Loop

**Status: ✅ IMPLEMENTED / ACTIVE / PRODUCTION HOMOLOGATED (22/09/2026)**

> [!NOTE]
> *(Nota de atualização: O Closed Feedback Loop foi implementado, integrado à estratégia de conteúdo autônoma e homologado com exclusão fail-closed de copyright na V14-B.2. O Estado Atual Canônico no topo prevalece).*

Fluxo implementado: YouTube publication → automatic analytics collection → performance history → content strategy → próximas decisões de tema/hook/estrutura/duração → novos vídeos → nova medição.

A infraestrutura em `analytics.py`, `analytics_scheduler.py`, `content_strategy.py` e `quality_score.py` oferece feedback parcial; o closed loop automático ainda precisa ser homologado.

Regras:
- Não é fine-tuning/retraining de pesos; usar memória persistida de performance.
- Exigir mínimo de amostras antes de adaptação.
- Manter diversidade, evitar perseguir viral isolado e evitar overfitting em poucos vídeos.
- Preservar Safety e Quality Gates.
- Decisão determinística/auditável sempre que possível.

Gate futuro: demonstrar que métricas persistidas influenciam decisões futuras de forma rastreável, com amostras suficientes e diversidade preservada.

## V12-F.3 — Per-Channel Learning Isolation

**Status: ✅ IMPLEMENTED / ACTIVE (22/09/2026)**

> [!NOTE]
> *(Nota de atualização: O isolamento de aprendizado por canal está implementado e ativo no Content Strategy e Analytics, garantindo aprendizado independente entre perfis sem contaminação cruzada de métricas. O Estado Atual Canônico no topo prevalece).*

Cada canal deve aprender separadamente. Não misturar automaticamente métricas, performance histórica, nicho, hooks vencedores, estruturas narrativas, duração ótima ou frequência entre canais/perfis.

Canal principal: manter perfil `default` já homologado.
Segundo canal criado manualmente: **Dose Diária de Histórias e Mistério**.
Handle: **@DoseDiáriadeHistóriasemistério**.

Planejar integração futura pela infraestrutura V9 Multi-Profile/Multi-Channel como perfil/canal separado. Não conectar nem publicar automaticamente nesta tarefa.

Gate futuro: confirmar métricas e decisões associadas ao profile/channel correto, sem contaminação automática entre canais.

## V12-F.4 — Second Channel Warm-Up

**Status: ✅ COMPLETED / PRODUCTION HOMOLOGATED (22/09/2026).**

Homologação do segundo canal concluída em produção com sucesso. Evidências reais registradas:
- **Segundo perfil isolado:** `profile-historias-misterio` ("Dose Diária de Histórias e Mistério", nicho `historias_misterio`).
- **Canal YouTube isolado:** `channel-historias-misterio-youtube` (handle `@DoseDiáriadeHistóriasemistério`, Upload-Post `dose-diaria-misterio`).
- **Geração real em produção:** task_id `815b0958-b94e-457b-932d-b10dfb0e8dba`.
- **Safety Gate:** PASS.
- **Quality Gate:** 79.2 (Strong Quality, limiar >= 70).
- **Scheduler:** Adoção e agendamento automático para YouTube.
- **Publicação pública real:** Vídeo `XVy8MbpJFqw` publicado com visibilidade pública no YouTube.
- **Analytics youtube_api:** Coleta e métricas isoladas por canal via YouTube Data API.
- **PR #9 Recovery:** Recuperação de tasks aprovadas mesmo após reinicialização de processos sem dependência de MemoryState volátil.
- **Autonomous secondary ON:** Produção autônoma do perfil secundário ativada e operacional em produção.
- **Canal principal preservado:** Perfil `default` 100% isolado e inalterado.

## V12-F.5 — Multi-Channel Capacity & True Multi-Profile Autonomous Worker

**Status: ✅ COMPLETED / IMPLEMENTED (22/09/2026).**

> [!IMPORTANT]
> **UI PROFILE SELECTION IS NOT A BACKGROUND EXECUTION SELECTOR.**
> A seleção de perfil na UI do Operator Console serve exclusivamente para inspeção visual, telemetria, controles manuais e disparos supervisionados pontuais daquele perfil. O worker em segundo plano processa de forma determinística e independente todos os perfis ativos e habilitados (`run_enabled_profiles_autonomous_cycle`).

Capacidade multi-canal e governança de custos implementada:
- **True Multi-Profile Background Worker:** Loop do scheduler worker desacoplado de `get_active_profile_id()`. O worker itera de forma determinística sobre todos os perfis ativos com `autonomous_mode_enabled=True`, executando no máximo 1 transição por perfil por ciclo com isolamento de falha (falha em um canal não aborta os demais).
- **Ready Stock por perfil:** Configuração `autonomous_target_ready_stock:<profile_id>` (WARMUP default 3, SCALE default 5; intervalo configurável [3, 6]). Fallback backward-compatible para a chave legada no perfil `default`.
- **Limites de produção por perfil (24h):**
  - WARMUP: 2 gerações aprovadas / 24h; 8 tentativas / 24h.
  - SCALE: 5 gerações aprovadas / 24h; 15 tentativas / 24h.
  - Configurações isoladas: `autonomous_max_generations_24h:<profile_id>` e `autonomous_max_attempts_24h:<profile_id>`.
- **Global Cost Guard:** Freio mestre agregado somando todos os perfis (`autonomous_global_max_generations_24h = 10`, `autonomous_global_max_attempts_24h = 25`). Contadores agregados explícitos (`count_all_profiles_generations_24h`, `count_all_profiles_attempts_24h`). Protege o início de novas gerações sem bloquear agendamento, recuperação de vídeos já prontos ou publicação.
- **Elegibilidade de destinos multi-plataforma:** Conceito arquitetural `check_asset_eligibility_for_destination` permitindo futuro reuso de 1 asset aprovado para múltiplos destinos sem re-renderização.
- **TikTok estritamente OFF:** Nenhuma publicação, chamada de API ou credencial criada para TikTok.
- **Ponteiros e estado isolados:** `current_task_id`, `waiting_task_id`, `autonomous_state` e mensagens 100% isolados por perfil.

### Pendência Futura: Copyright / Content ID Hardening + Character Narrator

- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` publicado com sucesso porém bloqueado mundialmente por Content ID / direitos autorais reivindicados.
- **Backlog Futuro:**
  - Identificar mídia e faixa musical (BGM) causadora da reivindicação.
  - Personagem / apresentador narrador virtual (V14 Hybrid Presenter) para enriquecer teor transformativo.
  - Composição visual e de áudio mais original, revisando fontes e licenças.
  - Gate preventivo de verificação de copyright.
  - Vídeos bloqueados/reivindicados não devem alimentar o Closed Feedback Loop.
- **Observação:** Nenhum filtro ou mitigação implementado na V12-F.5 (pendência estritamente documentada).

---

# [HISTORICAL SNAPSHOT / SUPERSEDED] V13 — Headless Remote Deployment / Safe Update

**Status: ✅ HOMOLOGADA EM PRODUÇÃO — 23/09/2026 (V13-A / V13-A.1 / V13-B)**

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o planejamento original da V13. A fundação de atualização remota e headless segura (`scripts/update_production.ps1`) foi integralmente desenvolvida, testada (V13-A e V13-A.1) e homologada com sucesso no PC forte de produção (V13-B, commit `46e44c2`). O **Estado Atual Canônico** no topo prevalece sobre este registro histórico.

Objetivo original (concluído e homologado):
- atualizar produção sem monitor físico
- deploy remoto controlado
- backup antes de update
- stop seguro
- pull `--ff-only`
- regressão direcionada
- start
- health checks
- rollback seguro
- zero interação física no PC forte

Entregáveis homologados:
- `scripts/update_production.ps1`
- gate de worktree clean
- backup automático com SQLite integrity check e sidecar SHA-256
- validação Fast-Forward estrita do commit alvo
- health check delimitado (HTTP 200 / ok)
- rollback não-destrutivo via git switch detach

---

# V14 — Virtual Presenter & Copyright Hardening

## V14-A — Auditoria e Plano Técnico
- **Status:** ✅ AUDIT COMPLETED
- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` publicado com sucesso, porém posteriormente bloqueado mundialmente por Content ID (conteúdo reivindicado; sem evidência de strike).
- **Causa Raiz Identificada:** Faixas padrão de `resource/songs/*.mp3` originadas de vídeos do YouTube conforme aviso do README upstream, associadas ao sorteio `bgm_type="random"`.
- **Arquitetura Recomendada:** Character Overlay Transparente Local (WebM VP9 alfa / PNG) + Copyright Baseline Hardening.

## V14-B — Copyright Baseline Hardening
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Escopo:**
  1. Bloqueio estrito de faixas legadas (`resource/songs/`) em novas gerações autônomas (`resolve_autonomous_bgm` com `bgm_type="none"`, `volume=0.0`, `SAFE_NO_BGM`).
  2. Uso manual legado preservado sem exclusão física dos arquivos.
  3. Rastreabilidade auditável (`asset_provenance` com BGM e clips visuais persistidos em `script.json` e memória).
  4. Copyright Provenance Gate no pipeline autônomo (fail-closed antes da aprovação da tarefa).
  5. Nenhum mecanismo local de evasão de Content ID; resposta formal `COPYRIGHT_PROVENANCE_GATE = PASS` (sem falsas promessas de `CONTENT_ID_SAFE`).
  6. Preparação conceitual de status futuro (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`) e fontes (`operator`, `future_provider`).
  7. Backlog: exclusão no Closed Feedback Loop de publicações com reivindicação comprovada.
  8. Card "Copyright / Assets" no Operator Console.

## V14-B.1 — Legacy Stock Copyright Quarantine (Hotfix)
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Causa Raiz:** Vídeos antigos já renderizados (23 assets não publicados) possuíam `bgm_type="random"` ou `bgm_type="custom"` e ausência de `asset_provenance`. O loop autônomo recuperava esses vídeos no `get_autonomous_ready_stock()` e `_recover_waiting_task()`. Além disso, `build_asset_provenance` não lia corretamente parâmetros quando em formato `dict`.
- **Correções:**
  1. Suporte universal a `dict` e objetos em `build_asset_provenance()` via `_get_param()`.
  2. Tarefas antigas com `bgm_type="random"` e `bgm_type="custom"` sem proveniência avaliam estritamente como `COPYRIGHT_PROVENANCE_GATE = FAIL`.
  3. `_recover_waiting_task()` e `get_autonomous_ready_stock()` agora exigem `evaluate_copyright_provenance_gate == PASS`, excluindo automaticamente os 23 vídeos legados do estoque autônomo e do agendamento autônomo.
  4. Preservação física e histórica: nenhum arquivo apagado, nenhum registro cancelado. Fluxo manual legado preservado.

## V14-C — Hybrid Character Overlay MVP
- **Status:** ✅ MERGED
- **Arquitetura Selecionada:** Character Overlay Transparente Local (WebM VP9 alfa / PNG transparente).
- **Custo e Dependências:** R$ 0,00; sem chamadas pagas, 100% offline via MoviePy 2.x existente.
- **Implementação:**
  1. Suporte completo em `VideoParams` (`avatar_mode`, `avatar_provider`, `avatar_character_id`, `avatar_asset_path`, `avatar_position`, `avatar_scale`, `avatar_opacity`).
  2. Módulo dedicado `app/services/presenter.py` com validação de config, bloqueio de traversal, layout seguro (safe margins para Shorts) e timeline híbrida determinística (`build_hybrid_presenter_segments`).
  3. Composição Z-Order no `video.generate_video()` com legendas renderizadas no topo (`source_video_clip` -> `presenter_clips` -> `text_clips`).
  4. Proveniência de presenter integrada a `build_asset_provenance()` em `copyright_gate.py`.
  5. Telemetria no Operator Console: Mode, Character ID, Provider e Asset Status.
  6. Modo autônomo estritamente mantido em `avatar_mode="none"`.

## V14-C.1 — Cartoon Character Asset Pack + Preview
- **Status:** ✅ MERGED
- **Personagem:** **Nox** (`nox_v1` / `misterio_host_v1`), estilo cartoon / semi-cartoon, definido como personagem-base unificado para todos os canais (`SINGLE_CHARACTER_ALL_CHANNELS = YES`).
- **Implementação:**
  1. Especificação completa do personagem documentada em `docs/CHARACTER_PRESENTER_SPEC.md` (direção visual, paleta de cores sóbrias, vestimenta grafite/vinho, enquadramento waist-up e lista de poses).
  2. Contrato de Asset Pack local estabelecido em `storage/presenter_assets/<character_id>/` e `resource/presenter_assets/<character_id>/` com catálogo de poses (`neutral`, `talking_1`, `talking_2`, `surprised`, `serious`, `thinking`, `pointing_left`, `pointing_right`, `cta`) e `config.json`.
  3. Resolução de Character Pack por `character_id` em `presenter.py` (`resolve_character_pack`) com fail-closed para poses obrigatórias ausentes.
  4. Pose Controller determinístico (`select_presenter_pose`) selecionando poses por segmento narrativo (hook, return, cta, corner).
  5. Suporte a Preview controlado (`render_presenter_preview` e `generate_presenter_preview_frame`) para validação estática e render sem tocar produção.
  6. Produção autônoma estritamente preservada com `avatar_mode="none"`.

## V14-C.2 — Expressive Presenter + Subtitle Interaction
- **Status:** ✅ MERGED
- **Implementação:**
  1. Parser determinístico e tolerante a falhas de SRT (`parse_srt_timeline`), convertendo legendas para estrutura temporal unificada.
  2. Classificador prioritário de legendas (`classify_subtitle_reaction`) com categorias PT-BR: SURPRISE, THINKING, SERIOUS, CTA e DEFAULT com precedência estrita (`CTA > SERIOUS > SURPRISE > THINKING > TALKING > NEUTRAL`).
  3. Alternância determinística de fala (`talking_1` e `talking_2` em intervalos de 0.35s) sem requerer lip-sync neural.
  4. Interação de apontamento (`pointing_left` para `bottom_right`, `pointing_right` para `bottom_left`).
  5. Tom de canal respeitado: `profile-historias-misterio` utiliza reações sóbrias e contidas (`mystery_contained_reaction`).
  6. Construção da timeline de expressões (`build_presenter_expression_timeline`) respeitando estritamente os segmentos do presenter e sem sobreposição temporal inválida.
  7. Performance otimizada no MoviePy via cache único de clips de pose no ExitStack.
  8. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).

## V14-C.3 — Nox Canonical Visual Asset Pack + Real Local Preview
- **Status: ⏸️ EXPERIMENT ARCHIVED / DORMANT**
- **Observação Crítica:** O experimento visual estático com Nox não atingiu o resultado desejado de qualidade e dinamismo para operação em produção. Por este motivo, **V14-C.4 NÃO é a próxima fase ativa**.
- **Presenter/Nox DORMANT:** Os frameworks de apresentador e expressões (V14-C, V14-C.1, V14-C.2) permanecem no código, mas o modo autônomo está estritamente fixado em `avatar_mode="none"` (OFF).
- **Branch de Arquivamento:** Todos os assets experimentais e tuning visual de Nox foram preservados na branch de arquivo: `archive/v14-c3-nox-presenter-experiment`. Não há novos trabalhos de desenvolvimento planejados para Nox nesta etapa.
- **Implementação Realizada (Histórico):**
  1. Estrutura canônica de diretórios criada em `assets/presenter/nox_v1/` com `manifest.json`, `reference/`, `poses/` e `previews/`.
  2. Manifest declarativo versionado com metadados de identidade visual canônica (idade 20-30 anos, pele morena clara, cabelo preto com reflexos roxos, olhos castanhos, roupa jaqueta/moletom preto).
  3. Contrato estrito de Core Poses (9 poses obrigatórias) e catálogo de Extended Motion Pack (13 poses opcionais).
  4. Fallback Graph determinístico implementado para poses estendidas (`EXTENDED_POSE_FALLBACKS`).
  5. Validação rigorosa de consistência de assets (`validate_character_pack_assets`) checando formato PNG, canal alfa real e uniformidade de dimensões entre poses.
  6. Gerador local de Contact Sheet (`generate_contact_sheet`) para inspeção de layout e coerência visual pelo operador.
  7. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).
- **Próxima Fase Global:** V15-E.2 — Post for Me YouTube Production Publisher.

---

## V15-E.1 — YouTube Direct Publisher Foundation + Private POC
- **Status:** ✅ HOMOLOGATED (POC Validada nos 2 Canais)
- **Implementação:**
  - Módulo `app/services/youtube_direct.py` com suporte oficial a OAuth 2.0 por canal/perfil.
  - Upload resumable oficial via YouTube Data API v3 (`videos.insert`).
  - Guard estrita de privacidade `private` para POC (`DIRECT_POC_PRIVATE_ONLY`).
  - CLI de sondagem `scripts/youtube_direct_probe.py`.
  - Homologada com sucesso nos canais default e mistério.

## V15-E.2 — Post for Me YouTube Production Publisher
- **Status:** 🚀 DEV IMPLEMENTED / READY FOR POC HOMOLOGATION
- **Implementação:**
  - Novo cliente API oficial `app/services/post_for_me.py` para Post for Me API v1 (`https://api.postforme.dev/v1`).
  - Roteador de publicação YouTube `app/services/youtube_publisher.py` chaveado por `autopilot_settings.youtube_publish_provider` (default `upload_post`).
  - Resolução determinística fail-closed dos 2 canais conectados no Post for Me:
    - Default: `channel-default-youtube` -> `UCss-ng7mkGuB2v-5KKtIN9A` (display "Dose Diária De Internet")
    - Mistério: `channel-historias-misterio-youtube` -> `UCGJaC83EuaOwiZ0a3-KqUZA` (display "Dose Diária de Histórias e mistérios")
  - Suporte completo a privacidade pública (`public`, `private`, `unlisted`).
  - Idempotência preventiva com external_id determinístico (`video-factory:<task_id>:youtube:<channel_id>`) e consulta prévia (`GET /v1/social-posts?external_id=...`) antes de criar novo post.
  - Polling bounded com erro transitório (`timeout`) para retry do scheduler sem duplicação de vídeo.
  - Preservação do YouTube Video ID nativo para `publication_events.external_id` (compatibilidade total com Analytics).
  - TikTok permanece estritamente OFF.
  - Auto Publish em produção permanece OFF.
  - Provider default permanece `upload_post` até homologação real controlada.
  - API Key lida exclusivamente de `POST_FOR_ME_API_KEY`. Nenhuma credencial no Git.

---

# V16 — Audiovisual Quality & Brazilian Content Contract

## Regra Permanente
Cada projeto deve ter somente UMA fase ativa de implementação.

## V16.0 — Quality Audit
- **Status:** ✅ DONE
- **Causa raiz confirmada em produção:**
  - profile language = pt-BR
  - roteiro = pt-BR
  - geração autônoma herdou voice_name estrangeira: `af-ZA-AdriNeural-Female`
  - subtitle_enabled = False em vídeo publicado
  - text_fore_color = #000000
  - outro vídeo possuía subtitle.srt, mas também usava cor preta
  - match_materials_to_script = False
  - Quality Gate atual avalia tema/conteúdo, mas não garante qualidade audiovisual final

## V16.1 — Brazilian Content Contract
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Deploy SHA:** `3983d37a29d1f169e513f19bd7186348a74ad5e9`
- **Evidências de Homologação Real:**
  - A UI persistida em produção ainda continha `af-ZA-AdriNeural-Female`, `subtitle_enabled=False`, `text_fore_color=#000000`.
  - A produção autônoma bloqueou corretamente a voz estrangeira de forma fail-closed sem gerar falha silenciosa.
  - Nenhum vídeo/API/publicação espúria ocorreu no teste.
- **Regras Canônicas:**
  - `video_language = "pt-BR"`
  - `region = "BR"`
  - `subtitle_enabled = True`
  - `text_fore_color = "#FFFFFF"`
  - `stroke_color = "#000000"`
  - `stroke_width >= 1.5` (default autônomo 2.0)
  - `match_materials_to_script = True` (ordem sequencial do roteiro)
  - Voz TTS: validação estrita de locale `pt-BR` (ex: `pt-BR-AntonioNeural`, `pt-BR-FranciscaNeural`, `pt-BR-ThalitaMultilingualNeural`).
  - Voz estrangeira (`af-ZA-*`, `en-*`, `zh-*`, `pt-PT-*`, etc.) ou vazia = FAIL CLOSED / BLOCK.

## V16.2 — Subtitle Reliability Gate
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Deploy SHA:** `0744fd2b8593fa276a2d3117d88b270475b5b05c`
- **Regra Fundamental:** `AUTONOMOUS_VIDEO_WITHOUT_VALID_CAPTIONS = FORBIDDEN`
- **Arquitetura Implementada:**
  - **PRIMARY:** Edge subtitles (`voice.create_subtitle`).
  - **SRT VALIDATOR:** Validador físico, sintático e semântico dedicado (`subtitle.validate_subtitle_file`).
  - **FALLBACK:** Whisper (`subtitle.create` + `subtitle.correct`).
  - **FAIL CLOSED:** Se ambos os provedores falharem ou produzirem SRT inválido, a tarefa falha estruturadamente (`stage="subtitle"`, `error="subtitle_required_but_unavailable..."`) antes de baixar materiais ou renderizar.
  - **STALE PROTECTION:** Limpeza de arquivos parciais/inválidos e substituição atômica via arquivo temporário.
  - **PRESERVAÇÃO DO FLUXO MANUAL:** Quando `subtitle_required=False`, o comportamento manual não executa download inadvertido de modelos nem altera a flexibilidade do operador.
  - **MODEL ENVIRONMENT:** O modelo Whisper real não foi baixado na fase de testes/desenvolvimento (mocks estritos). Recomendação de produção: `large-v3-turbo`.

## V16.3 — Final Media Quality Gate
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Deploy SHA:** `9e3fde0b35e28781aab67117d5ff33c182b337ef`
- **Regra Fundamental:** `AUTONOMOUS_FINAL_MEDIA_WITH_CRITICAL_DEFECT = FORBIDDEN`
- **Objetivo:** Garantir integridade física, visual e de áudio do arquivo MP4 renderizado antes de torná-lo elegível para agendamento e publicação.
- **Arquitetura Implementada:**
  - **Módulo Centralizado:** `app/services/media_quality.py`.
  - **Probing Helper Seguro:** `probe_media(file_path)` baseado em `ffprobe` com subprocess seguro (sem shell=True, timeout, capture_output, validação estrutural do payload).
  - **Critical Gates:**
    - Arquivo: existência, arquivo regular, tamanho > 10KB (`MIN_VALID_MEDIA_FILE_BYTES`).
    - Probe: ffprobe disponível, execução sem erro, JSON parseável e estruturalmente válido (dict, streams list, format dict).
    - Vídeo: stream de vídeo presente, dimensões > 0, resolução compatível com orientação, aspect ratio dentro da tolerância (ex: vertical 9:16 portrait).
    - Duração: duração > 0 e coerência com a narração da pipeline (`AUDIO_VIDEO_DURATION_MISMATCH`).
    - Áudio: áudio presente na produção autônoma com duração válida (duration inválida/não-numérica/NaN/inf/<=0 falha fechada; ausência tolerada).
    - Legenda: confirmação de contrato de que o artefato SRT válido foi persistido.
    - Pipeline Gate: bloqueia cross-posting e publicação antes de despachar chamadas externas; persiste diagnóstico em `script_data` mesmo em caso de BLOCK.
    - Multi-Vídeo: avaliação estrita de cada `final-N.mp4`.
    - Preservação Manual: flag `final_media_quality_required=True` ativa o gate estrito para autônomo, preservando chamadas manuais.
- **Limites e Escopo (O que NÃO é feito em V16.3):**
  - Sem OCR de legenda gravada.
  - Sem detecção de black frames ou freeze frames.
  - Sem análise subjetiva de estética ou relevância semântica.
  - Sem dependências de bibliotecas de Computer Vision.

## V16.4 — Scene-Based Video Generation
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Validação:** 20 testes PASS em `test/services/test_v16_4_scene_based_video_generation.py`
- **Priority:** P1
- **Regra Fundamental:** `AUTONOMOUS_SCENE_VISUALS_MUST_FOLLOW_SCRIPT_ORDER = REQUIRED`
- **REUSE-FIRST RULE:** Before implementing scene-based video generation, audit current upstream MoneyPrinterTurbo implementation/PR and reuse/port existing code when technically compatible. (Auditoria realizada: upstream PR #1315 não disponível localmente no fork; reaproveitamento focado em `material.py`, `video.py`, cache e contratos existentes).
- **Objetivo:** Introduzir geração orientada a cenas, garantindo que o visual acompanhe a progressão narrativa do roteiro, com termos de busca específicos por cena, resolução sequencial de materiais com fallback rastreável e montagem estritamente ordenada.
- **Arquitetura Implementada:**
  - `ScenePlan` e `ScenePlanItem`: representação estruturada de cenas com indexação determinística, narração, termos de busca e duração estimada.
  - Planner determinístico local (`app/services/scene_planner.py`): segmentação semântica do roteiro por pontuação/parágrafos e extração de termos visuais sem dependência obrigatória de LLM/rede.
  - Scene Material Resolver (`app/services/scene_material.py`): resolução de material por cena, fallback entre termos da própria cena e para termo genérico derivado se necessário.
  - Scene Assembly (`app/services/scene_assembly.py`): montagem e sequenciamento estrito das cenas em instruções ordenadas (`SceneClipInstruction`).
  - Flag de ativação: `scene_based_generation_enabled=True` no autônomo, `False` como padrão no manual.
  - Persistência e auditoria: `scene_plan` e `scene_materials` gravados em `script_data` com proveniência de ativos preservada.
  - Fail-closed: bloqueio em caso de cenas sem narração, termos vazios, ordem inconsistente ou falha crítica de resolução de material.
- **Limites e Escopo (O que NÃO é feito em V16.4):**
  - Sem CLIP embeddings ou reranking por visão computacional (V16.5).
  - Sem geração de imagem/vídeo por IA (V16.7/V16.8).
  - Sem OCR ou classificação visual de frames.

## V16.4.1 — Scene Render Performance Hardening

### V16.4.1A — Scene Render Performance Hardening
- **Status:** 🟢 PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **Priority:** P1
- **Branch:** `perf/v16-4-1-scene-render-performance` (PR #41)
- **Validação:** 10 testes PASS em `test/services/test_v16_4_1_scene_render_performance.py`
- **Objetivo:** Instrumentar e acelerar a pipeline de renderização orientada a cenas sem alterar codecs, filtros ou infraestrutura externa.
- **Entregas V16.4.1A:**
  - Instrumentação com `perf_counter` para `SCENE_RENDER_PREP_SECONDS`, `SCENE_RENDER_CLIPS_SECONDS`, `CONCAT_SECONDS`, `FINAL_RENDER_SECONDS` e `TOTAL_RENDER_SECONDS`.
  - Concatenação stream-copy no caminho scene-based (`-c copy`) com validação de saída e fallback automático para transcode (`CONCAT_MODE=STREAM_COPY` ou `CONCAT_MODE=TRANSCODE_FALLBACK`).
  - Propagação correta de `threads` nas escritas scene-based em `combine_videos`.

### V16.4.1B — Final Render Performance
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `e7f40ed6f4b7df45e5868cd7de03495239d103ec` (PR #43)
- **Evidência de Produção:** Task `f9a9608b-512d-43c4-92f4-f864a0424512`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Entregas V16.4.1B:**
  - Subtitle burn-in nativo acelerado em C via FFmpeg libass (`FINAL_RENDER_MODE=FFMPEG_NATIVE`).
  - Stream-copy direto via FFmpeg (`FINAL_RENDER_MODE=FFMPEG_STREAM_COPY`) para vídeos sem legenda.
  - Preservação de fallback MoviePy legado (`FINAL_RENDER_MODE=MOVIEPY_FALLBACK`).
  - Hardening de métricas: `FINAL_RENDER_SECONDS` interno canônico e `FINAL_RENDER_CALL_SECONDS` externo.

### V16.4.1C — Render Pipeline Gap Instrumentation
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `d231e3900bbbace180c0c71e60e9fb08c2d713e0` (PR #44)
- **Evidência de Produção:** Task `337639bb-1740-4398-a923-c5f75b1f236a`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Resultados de Produção:**
  - `FINAL_RENDER_UNACCOUNTED_SECONDS = 0.0000273` (gaps internos de render final eliminados).
  - `TOTAL_RENDER_UNACCOUNTED_SECONDS = 0.0033855` (gaps macro do pipeline eliminados).
  - `COMBINE_VIDEOS_UNACCOUNTED_SECONDS = 0.0028849`.
  - Ponto remanescente identificado para investigação: `FINAL_RENDER_POST_ENCODE_SECONDS = 111.4239390` (~1m51s).

### V16.4.1D — Post-Encode Performance Investigation
- **Status:** 🟢 MERGED (04/10/2026)
- **Deploy SHA:** `d13d9347fc96c6a967561821552bbb19452eb281` (PR #45)
- **Validação:** 34 testes PASS (`test_v16_4_1_scene_render_performance.py`, `test_v16_4_1b_final_render_performance.py`, `test_v16_4_1c_render_gap_instrumentation.py`, `test_v16_4_1d_post_encode_performance.py`)
- **Objetivo:** Investigar rigorosamente as operações de `FINAL_RENDER_POST_ENCODE_SECONDS`, sub-instrumentar as fases internas e identificar a raiz da retenção pós-encode.
- **Classificação de Evidências:**
  - **CONFIRMED:**
    - Não existem probes duplicados, reaberturas MoviePy, handles pendentes, retries ou I/O de disco oculto dentro de `FINAL_RENDER_POST_ENCODE_SECONDS`.
    - A região pós-encode executa unicamente a atribuição de estado local (`native_rendered`, `final_render_mode`) e a emissão do log `logger.info("FINAL_RENDER_MODE=...")`.
    - Sub-instrumentação contígua implementada: `FINAL_RENDER_POST_ENCODE_STATE_SECONDS`, `FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS` e `FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS`.
    - Invariantes matemáticos pós-encode validados em `verify_render_timing_invariants`.
  - **INFERRED:**
    - O tempo anômalo de 111.42s em ambiente interativo Windows decorreu de suspensão por console lock (QuickEdit Mode no conhost bloqueando `sys.stderr` após interação de mouse/seleção durante os 5 minutos de encode contínuo).
  - **NOT_YET_VALIDATED_IN_PRODUCTION:**
    - Verificação da latência pós-encode em execução totalmente desassistida no PC forte (`C:\Projetos\MoneyPrinterTurbo`).
- **Limites e Escopo (O que NÃO é feito em V16.4.1D):**
  - Sem alteração de parâmetros de vídeo (codec, resolução, FPS, CRF, preset)
  - Sem remoção ou enfraquecimento do Final Media Quality Gate
  - Sem otimização especulativa não fundamentada em evidências
  - Sem tocar PC forte / produção

### V16.4.2R / V16.4.2R.1 / V16.4.2R.2 — Pre-Repair Publishing Reset & Stale Lock Recovery
- **Status:** ✅ PRODUCTION HOMOLOGATED (04/10/2026, PR #48, Deploy SHA: `83be45cb95fc5c8b74c43844621ebf9c6d328b9c`)
- **Priority:** P1
- **Branch:** `fix/v16-4-2r2-stale-primary-recovery`
- **Validação:** 16 testes PASS (8 em `test_v16_4_2r_pre_repair_publishing_reset.py` + 8 em `test_stale_primary_lock_recovery.py`), Dry-run e Reset real validados com backup íntegro e zero deleção de arquivos.
- **Objetivo:** Estabelecer um baseline limpo e auditado no subsistema de publicação antes das correções V16.4.2A/B/C, neutralizando todas as publicações antigas pendentes, stale processing ou retries armados, preservando integralmente o histórico de publicações realizadas com sucesso e fornecendo recuperação segura e auditada de locks primários stale.
- **Entregas V16.4.2R / V16.4.2R.1 / V16.4.2R.2:**
  - Serviço reutilizável `app/services/publication_reset.py` e CLI `scripts/reset_pending_publications.py`.
  - Operação administrativa `release_stale_instance_lock` em `app/services/operator_console.py` (`--release-stale-primary` no CLI).
  - Critério objetivo e conservador de detecção de stale (heartbeat > 90s e ausência de processo local com mesmo PID/host).
  - Verificação fail-closed de pré-condições (`scheduler_enabled = False`, `auto_publish_enabled = False`, `active_primary = False`).
  - Preservação obrigatória de `scheduled_posts.status = 'published'`: posts publicados com retry residual têm `next_attempt_at` limpo sem conversão indevida para `cancelled`.
  - Preservação de registros `failed` com `publication_events(success)` para reconciliação determinística na V16.4.2A (retry desarmado, não executável).
  - Backup transacional físico prévio com `PRAGMA integrity_check` e SHA-256 (`storage/backups/database/`).
  - Neutralização de posts pendentes (`status = 'cancelled'`, `next_attempt_at = NULL`).
  - Preservação total de `publication_events` com `status = 'success'`, vídeos locais em `storage/tasks/` e posts `published`.
  - Registro de auditoria detalhado em `operational_events` (`PRE_REPAIR_PUBLICATION_RESET` e `STALE_PRIMARY_LOCK_RELEASED`).

### V16.4.2A — Publishing State Reconciliation
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Priority:** P1
- **Branch:** `feat/v16-4-2a-publishing-state-reconciliation`
- **Validação:** 8 testes PASS em `test/services/test_publication_reconciliation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Estabelecer uma reconciliação determinística entre `publication_events` e `scheduled_posts`, tratando `publication_events.status = 'success'` como evidência canônica de publicação concluída.
- **Entregas V16.4.2A:**
  - Guard Canônico no Scheduler runtime (`scheduler.run_scheduler_cycle` e `scheduler.has_existing_or_terminal_destination`): bloqueia qualquer provider call se já existir `publication_event` com status `success`, desarmando retries e marcando o scheduled post como `published`.
  - Serviço `app/services/publication_reconciliation.py`: reconcilia inconsistências históricas (`failed + success` -> `published`, `processing + success` -> `published`, `published + retry` -> retry limpo, neutralização determinística de duplicatas).
  - CLI `scripts/reconcile_publication_state.py`: modo `--dry-run` por padrão e execução real protegida via `--execute --confirm RECONCILE_PUBLICATION_STATE`.
  - Auditoria completa com eventos em `operational_events`: `PUBLICATION_RECONCILED_SUCCESS`, `DUPLICATE_SCHEDULE_DETECTED`, `RETRY_DISARMED_AFTER_SUCCESS`, `STALE_PROCESSING_DETECTED`, `HISTORICAL_ORPHAN_SUCCESS_RECONCILED`.
  - Preservação estrita: zero deleção de eventos de publicação, zero deleção de arquivos de mídia, zero requisições externas a providers.
- **Transição Homologada em Produção:** V16.4.2A executada com 0 mutations pendentes no PC Forte.

### V16.4.2B — Publishing Idempotency / Duplicate Protection
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Priority:** P1
- **Branch:** `feat/v16-4-2b-publishing-idempotency-duplicate-protection`
- **Validação:** 10 testes PASS em `test/services/test_publishing_idempotency.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Impedir definitivamente que o sistema crie, agende, processe ou envie mais de uma publicação externa para a mesma tupla canônica `(task_id, platform)` quando já existir sucesso registrado ou fluxo executável equivalente.
- **Entregas V16.4.2B:**
  - Multi-Layer Protection:
    - Camada 1: Criação e Agendamento (`app.services.publishing_idempotency.can_schedule_task` / `scheduler.plan_schedule`): bloqueia se já houver sucesso canônico, post agendado executável, processamento ativo ou post publicado.
    - Camada 2: Scheduler Runtime / Seleção de Candidatos (`can_execute_scheduled_post` em `run_scheduler_cycle`): detecta sucesso canônico antes do ciclo e neutraliza duplicatas para `cancelled` (`next_attempt_at = NULL`).
    - Camada 3: Just-In-Time Idempotency Gate imediatamente pré-provider (`jit_provider_idempotency_guard`): executado no scheduler, `task.publish_task`, `youtube_publisher` e `post_for_me` client logo antes de qualquer requisição externa.
  - Race condition mitigada: se sucesso for registrado entre o início do ciclo e a chamada ao provider, a chamada é abortada com segurança e o post é marcado como `published`.
  - Duplicatas históricas canceladas não interferem com posts ativos elegíveis.
  - Múltiplas plataformas para a mesma task permanecem independentes.
  - Preservação estrita: zero deleção de registros em `publication_events` ou `scheduled_posts`; zero deleção de arquivos de mídia.

### V16.4.2C — Retry Metadata Cleanup
- **Status:** 🚀 MERGED (PR #51) (04/10/2026)
- **Priority:** P1
- **Branch:** `feat/v16-4-2c-retry-metadata-cleanup`
- **Validação:** 12 testes PASS em `test/services/test_publishing_retry_cleanup.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Eliminar estados residuais e regras inconsistentes de retry que possam rearmar publicações já concluídas, canceladas, reconciliadas ou terminalmente falhadas.
- **Entregas V16.4.2C:**
  - Módulo canônico `app/services/retry_policy.py`: centraliza classificação de erros, elegibilidade de retry (`evaluate_retry_decision`) e cleanup determinístico de metadados residuais (`cleanup_residual_retries`).
  - Estados terminais garantidos com `next_attempt_at = NULL`: `published`, `cancelled` e falhas permanentes/esgotadas (`attempts >= 3`).
  - Sucesso canônico em `publication_events` sempre desarma retry em `scheduled_posts`.
  - Reagendamento de retry restrito a falhas transitórias comprovadas com `attempts < 3`.
  - Scheduler Runtime integrado: executa limpeza de retries residuais preventivamente antes da busca de posts vencidos em cada ciclo.
  - CLI `scripts/cleanup_retry_metadata.py`: suporta auditoria (`--dry-run`) e execução controlada (`--execute --confirm CLEANUP_RETRY_METADATA`).
  - Preservação estrita: zero deleção de registros e zero deleção de mídia.

### V16.4.2H — Final Publishing Health Audit
- **Status:** 🚀 DEV AUDITED / INTEGRATED SUITE PASSED (05/10/2026)
- **Priority:** P1
- **Branch:** `feat/v16-4-2h-final-publishing-health-audit`
- **Validação:** 10 testes PASS em `test/services/test_publishing_health_audit.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, 12 testes PASS não-regressão V16.4.2C, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Auditoria final do subsistema de publicação e comprovação de segurança para deploy consolidado em produção.
- **Entregas V16.4.2H:**
  - JIT Idempotency Guard integrado ao caminho de fallback Upload-Post em `task._execute_cross_post_process`.
  - Transições de terminal em `scheduler.py` reforçadas com `next_attempt_at = NULL`.
  - Suíte de auditoria integrada em `test/services/test_publishing_health_audit.py` cobrindo ciclo de vida controlado, contagem estrita de chamadas ao provider, retries progressivos, falhas terminais, concorrência JIT, independência de plataformas e invariantes de métricas operacionais.
  - Zero pontos de escape ou regressão identificados.
- **Próximo Passo:** `CONSOLIDATED_PRODUCTION_DEPLOY_AND_CONTROLLED_PUBLICATION_TEST`.







## V16.5 — Visual Matching v2
- **Status:** ✅ DEV IMPLEMENTED / VALIDATED
- **Priority:** P1
- **Escopo:**
  - Extração de intenção visual estruturada por cena (`SceneVisualIntent`: primary_subject, action, environment, style, must_include, avoid, search_queries).
  - Search Query v2: geração de consultas em inglês ricas e em tiers de especificidade, evitando pesquisas genéricas.
  - Pontuação determinística de candidatos (0-100 pts) considerando aderência semântica de termos, título/tags, proporção/aspecto, duração útil e penalidade de repetição.
  - Diversidade global: penalização (-35 pts) de repetição de ativo no mesmo vídeo (além de -50 pts para repetição consecutiva imediata).
  - Fallback resiliente em cascata sem quebra de pipeline.
  - Observabilidade e auditoria persistidas em `script_data` (`visual_intent`, `match_score`, `selection_reason`, `queries_tried`, `fallback_tier`).
  - Suíte de 9 testes direcionados + 20 testes da V16.4 passando com 100% de sucesso.

## V16.5.1 — Subtitle & Narration Quality Recovery
- **Status:** ✅ DEV IMPLEMENTED / VALIDATED
- **Priority:** P1
- **Objetivo:** Recuperar a qualidade perceptual de legenda e narração observada em degradação recente antes de novo render completo em produção.
- **Root Causes & Correções Implementadas:**
  - **Legenda no Topo / Margem 5%:** O rodapé absoluto histórico (5% da altura) colidia diretamente com a barra de UI do Shorts/TikTok (título do som, perfil, botões). Subtitle position "top" foi rejeitado como default e normalizado para safe bottom. Margem vertical em 9:16 portrait ajustada para ~22% (`margin_v = int(video_height * 0.22)` em ASS e `video_height * 0.78 - _clip.h` em MoviePy), mantendo as legendas confortavelmente na zona segura entre 70% e 80% da altura útil.
  - **Bug Histórico 2/3:** Corrigido bug na MoviePy que calculava `(video_height - _clip.h) / 3.0` (33% do topo), restaurando o posicionamento no terço inferior (67%-75%).
  - **Fonte Pequena (30px):** Guard implementado para vídeo vertical garantindo tamanho legível mínimo de 50px (default canônico 60px).
  - **Margem Horizontal em 9:16:** Reduzida para 85% (`0.85 * video_width`) para evitar sobreposição dos ícones laterais do TikTok/Shorts (like, salvar, compartilhar).
  - **Contraste & Stroke:** Contrato visual reforçado com texto branco puro (`#FFFFFF`), contorno preto (`#000000`) e stroke mínimo de 2.0px.
  - **Narração Arrastada (Rate 0.8):** A velocidade 0.8 tornava as vozes neurais em pt-BR artificiais, sonolentas e arrastadas. Normalizado para velocidade natural canônica 1.0 (faixa de segurança 0.95 - 1.30).
  - **Benchmark Local de Vozes:** Validado áudio sintético em DEV sem publicação:
    - Baseline 1: `pt-BR-AntonioNeural` @ rate 1.0 (38.1 KB, 4.7s) -> natural, claro, ritmo dinâmico.
    - Degraded State: `pt-BR-AntonioNeural` @ rate 0.8 (47.6 KB, 5.9s) -> +25% tempo, cadência lenta/artificial.
    - Candidate 2: `pt-BR-FranciscaNeural` @ rate 1.0 (39.8 KB, 4.9s) -> expressiva, fluida e excelente para formato vertical.
  - **Licenciamento Comercial:** Kokoro-82M (Apache 2.0) possui licença comercial permissiva mas suporte pt-BR ainda experimental sem word-level timestamps; Edge-TTS / Azure Neural mantidos como baseline canônico e estável.

## V16.6 — Hybrid Visual Generation Foundation
- **Status:** ✅ DEV IMPLEMENTED / VALIDATED
- **Priority:** P1
- **Escopo e Componentes Entregues:**
  - Arquitetura provider-agnostic implementada em `app/services/hybrid_visual.py`.
  - Contratos de dados: `ProviderCapabilities`, `GenerationRequest`, `GenerationResult`, `GenerationMetrics`.
  - Providers preparados:
    - `StockVisualProvider`: Baseline de alta confiabilidade (Pexels, Pixabay, biblioteca local).
    - `NanoBananaImageAdapter`: Adapter para geração de keyframe de imagem estática (`text_to_image`) em modo stub/configurável (zero chamadas pagas, zero credencial obrigatória em DEV).
    - `ComfyUIClient` + `ComfyUIVisualProvider`: Suporte a backend headless local/remoto no PC Forte (endpoints `/system_stats`, `/prompt`, `/history`, `/view`).
  - Orquestrador: `HybridVisualDirector` com política rigorosa de fallback transparente para stock footage em caso de indisponibilidade, timeout, erro ou capability não suportada. O pipeline nunca falha por indisponibilidade de IA.
  - Compatibilidade: `visual_generation_enabled = false` por padrão em `config.toml`, `config.example.toml` e `VideoParams`.
  - Validação direcionada: 13 testes unitários com 100% de sucesso (`test/services/test_hybrid_visual_generation.py`).

## V16.6.1 — Hardware-Aware Open Source Benchmark
- **Status:** ✅ DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS
- **Priority:** P1
- **Hardware Audit & Registro Operacional:**
  - `LOCAL_GENERATIVE_VIDEO_GPU_STATUS = NOT_RECOMMENDED_ON_CURRENT_HARDWARE`
  - PC Forte de Produção: AMD Radeon RX 580 2048SP (~4 GB VRAM visível, sem NVIDIA, sem CUDA, sem ComfyUI/torch).
  - Modelos modernos de difusão de vídeo (Wan 2.2, LTX-Video, FramePack) exigem >= 8-16 GB VRAM com aceleração CUDA. Forçar execução local causaria lentidão extrema e instabilidade.
  - Alternativas viáveis adotadas: Provedor de vídeo remoto, geração contextual de keyframes estáticos (Nano Banana) e efeitos leves de motion local (Ken Burns / Pan / Zoom).
- **Harness e Script Entregues:**
  - `scripts/benchmark_video_models.py` com suporte a `--hardware-probe` (relatório completo de vendor, VRAM, CUDA, ROCm, classificação e modelos recomendados).
  - Classificação automática: `LOCAL_GPU_READY` (NVIDIA >=16GB), `LIMITED` (8-15GB), `NOT_RECOMMENDED` (<8GB / sem CUDA).
  - Execução segura: se classificado como `NOT_RECOMMENDED`, avisa e previne execução GPU não viável, mantendo suporte ao modo `--dry-run`.

## V16.6.2 — Contextual Image-to-Video Foundation
- **Status:** ✅ DEV IMPLEMENTED / VALIDATED
- **Priority:** P1
- **Escopo e Componentes Entregues:**
  - **Decisão Híbrida Inteligente (`HybridVisualDirector`):**
    - `STOCK_HIGH_CONFIDENCE`: score de matching >= threshold (default 60) utiliza clipe de stock direto.
    - `GENERATED_IMAGE_PREFERRED`: score intermediário (35 a 59) gera keyframe contextual de alta qualidade via Nano Banana.
    - `GENERATED_VIDEO_PREFERRED`: score fraco (< 35) tenta geração de vídeo ou imagem + motion.
    - `FALLBACK_STOCK`: qualquer falha técnica, indisponibilidade ou timeout aciona fallback transparente para stock.
  - **Síntese Contextual de Prompts (`build_image_prompt_from_visual_intent`):**
    - Transforma `SceneVisualIntent` (`visual_intent_v2`) em prompts descritivos concisos (sujeito + ação + ambiente + estilo foto-realista + aspect ratio vertical 9:16 + prompt negativo anti-artefatos e sem marca d'água).
  - **Adapter Nano Banana Configurável:**
    - `NanoBananaImageAdapter` integrado, suportando modo mock leve e seguro para testes sem chamadas pagas.
  - **Image Quality Gate (`evaluate_keyframe_quality`):**
    - Verificação de existência, tamanho, formato, resolução mínima e orientação vertical (9:16 portrait).
  - **Motion from Still Foundation (`generate_still_motion_instructions`):**
    - Efeitos de movimento suave em keyframes estáticos (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `ken_burns`) sem carga pesada de render nos testes.
  - **Observabilidade por Cena:**
    - Persistência estruturada em `SceneMaterialSelection` e `script_data` (`visual_source_type`, `stock_match_score`, `generation_provider`, `generation_model`, `generation_prompt`, `generation_status`, `generated_asset_path`, `motion_mode`).
  - **Validação Local:** 20 testes unitários direcionados com 100% de sucesso (`test/services/test_hybrid_visual_generation.py`).

## V16.7 — Hybrid Scene Director
- **Status:** ✅ COMPLETED
- **Priority:** P1
- **Princípio Operacional:**
  - IA generativa não deve ser chamada indiscriminadamente (evitar desperdício de GPU, custo, tempo de render e perda de dinamismo).
  - Decisão automática por cena baseada em score de aderência semântica de stock, importância da cena, aspect ratio, penalidade de repetição e duração.
- **Decision Engine Canônico:**
  1. `STOCK_HIGH_CONFIDENCE` (Score >= 60): Usa clipe stock direto sem acionar IA.
  2. `GENERATED_IMAGE_PREFERRED` (35 <= Score < 60): Gera keyframe contextual (ex: Nano Banana). Se aprovado, usa Still Motion (ou I2V se provider habilitado).
  3. `GENERATED_VIDEO_PREFERRED` (Score < 35): Tenta geração de imagem + I2V se habilitado; caso contrário fallback para stock.
  4. `FALLBACK_STOCK`: Fail-safe robusto e transparente para qualquer timeout, erro ou falha no quality gate.
- **Classificação Leve de Importância de Cena (Sem LLM):**
  - `HERO`: Cenas de abertura (hook), clímax, keywords de ação/urgência ou duração ultra-curta (< 2.5s). Limiares mais agressivos para permitir geração.
  - `NORMAL`: Comportamento balanceado padrão.
  - `LOW`: Cenas de transição ou genéricas. Prioriza stock para economizar recursos.
- **Heurística de Custo/Benefício:**
  - Ajustes dinâmicos de limiares considerando aspect ratio (alinhamento vertical 9:16), penalidade por reuso de candidato stock e histórico de fallbacks da tarefa.
- **Still Motion Integrado:**
  - Suporte determinístico a 5 modos de movimento (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `static`) quando I2V estiver desabilitado.
- **Observabilidade Completa & Resumo de Vídeo:**
  - Metadados por cena em `SceneMaterialSelection` e `script_data`.
  - Resumo de métricas por vídeo (`VideoVisualSummary`): contagem de cenas por estratégia, média de score stock, tentativas e taxas de sucesso de geração.

## V16.8 — Controlled Hybrid Render Validation
- **Status:** ✅ DEV_VALIDATED / STRUCTURAL_AND_PROXY_PASS
- **Priority:** P1
- **Resultado do Experimento (Task 17386147... - 3 Curiosidades sobre Marte):**
  - **Validação Estrutural e Proxy:** PASS (arquitetura, decision engine, fallback, scoring, still motion e observabilidade validados com sucesso).
  - **Baseline Quality Score:** 57.8 / 100 (Stock library retornou praias tropicais e piers terrestres para Marte).
  - **Hybrid Quality Score:** 94.1 / 100 (Keyframes contextuais proxy Nano Banana + Still Motion dinâmico).
  - **Quality Delta:** +36.3 pts de ganho perceptual proxy comprovado.
  - **Nota Canônica:** A qualidade perceptual real definitiva depende de keyframes gerados por modelo de imagem real (avaliado na V16.8.1).

## V16.8.1 — Real Generated Image Quality Gate
- **Status:** ⚠️ REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED
- **Priority:** P1
- **Resultado da Tentativa Real:**
  - A tentativa real com chave oficial Google AI Studio foi bloqueada por cota do provedor externo: `HTTP 429 Free Tier limit = 0 requests/day`.
  - **Decisão Canônica:** Não ativar billing, não depender de providers pagos. O adaptador oficial Gemini/Nano Banana foi preservado para uso opcional futuro, mas deixou de ser pré-requisito da esteira de produção.
  - A necessidade real comprovada é: quando o stock genérico for fraco, encontrar fontes visuais autênticas, melhores e contextuais.

## V16.8.2 — Alternative Visual Sources Evaluation
- **Status:** ✅ DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)
- **Priority:** P1
- **Nova Prioridade Visual Canônica:**
  1. `STOCK_HIGH_CONFIDENCE` (acervo stock existente de alta confiança)
  2. `TRUSTED_THEMATIC_SOURCE` (NASA Image Library, Wikimedia Commons)
  3. `FREE_GENERATIVE_PROVIDER` (somente se gratuito, sem chave e sem fricção)
  4. `STATIC_IMAGE + STILL_MOTION` (movimento suave determinístico)
  5. `FALLBACK_STOCK` (resiliência total sem interrupção de pipeline)
- **Fontes Temáticas Implementadas & Avaliadas:**
  - **NASA Image Library (`nasa_image_library`):** API aberta, sem chave, autoridade 15.0, registros de domínio público com rigor científico.
  - **Wikimedia Commons (`wikimedia_commons`):** API MediaWiki, autoridade 12.0, licenças abertas (CC-BY, CC-BY-SA, Domínio Público).
- **Validação Real na Task de Marte (`17386147-cb1b-4192-b827-251a1bbd411f`):**
  - **Cena 3 (Monte Olimpo):** Stock baseline fraco `9354647` (28.0) -> Fonte Temática `wiki_98866197` (**82.78** pts, CC-BY) -> **APROVADO**.
  - **Cena 4 (Escala titânica):** Stock baseline com astronauta e vaso `8474871` (28.0) -> Mapa geológico autêntico `wiki_127759484` (**78.0** pts, Domínio Público) -> **APROVADO**.
  - **Cena 7 (Pôr do sol azul marciano):** Stock terrestre `8474684` (22.0) -> Foto real do pôr do sol azul pelo Rover Perseverance Mastcam-Z `nasa_PIA24935` (**73.0** pts, Domínio Público NASA) -> **APROVADO**.
- **Quality Gate de Licenças & Resolução:**
  - Rejeição estrita de ativos com `LICENSE_REVIEW_REQUIRED` (ex: imagens com direitos incertos bloqueadas automaticamente).
  - Penalidade de repetição de -25 pts para evitar redundâncias entre cenas consecutivas.
  - Previews curtos de Still-Motion gerados via FFmpeg (zoom_out, pan_left, pan_right) em `storage/validation/v16_8_2/previews/`.
- **Auditoria de Provedores Generativos Gratuitos:**
  - **Cloudflare Workers AI:** `REQUIRES_ACCOUNT` (cota gratuita de 10k neurons/dia esgota rapidamente com SDXL/Flux; requer account ID e token).
  - **Hugging Face Inference Providers:** `FREE_QUOTA_UNKNOWN` (cold-starts, erros 503 frequentes, cota não garantida sem endpoint dedicado).
  - **Conclusão:** Provedores gratuitos generativos não oferecem estabilidade zero-config; fontes públicas confiáveis (NASA/Wikimedia) são a base sustentável e superior para a fábrica.
- **Próximo Passo Esperado:**
  - `V16.9 — Final Hybrid Pipeline Foundation` e `V16.10 — Single Full DEV Render Homologation`.

## V16.9 — Final Hybrid Pipeline Foundation
- **Status:** ✅ DEV_COMPLETE / CONSOLIDATED (06/10/2026)
- **Priority:** P1
- **Resultado:**
  - Consolidação definitiva da hierarquia de seleção visual:
    1. `STOCK_HIGH_CONFIDENCE` (Score >= 60.0 / aderência comprovada)
    2. `THEMATIC_SOURCE_PREFERRED` (NASA Image Library / Wikimedia Commons)
    3. `FREE_GENERATIVE_PROVIDER` (somente se gratuito, sem chave e disponível; desabilitado por padrão)
    4. `STILL_MOTION` (movimento sutil determinístico Ken Burns 9:16 safe crop para imagens)
    5. `FALLBACK_STOCK` (resiliência total sem quebras)
  - Congelamento estrito de defaults de áudio e legenda:
    - Legendas: `subtitle_position = bottom`, `font_size = 60`, `text_fore_color = #FFFFFF`, `stroke_color = #000000`, `stroke_width = 2.0`.
    - Narração: `voice_name = pt-BR-AntonioNeural-Male`, `voice_rate = 1.0`.

## V16.10 — Single Full DEV Render Homologation
- **Status:** ✅ DEV_HOMOLOGATED / READY_FOR_PRODUCTION_DEPLOY (06/10/2026)
- **Priority:** P1
- **Execução Única Homologada em DEV:**
  - Task ID Canônica: `17386147-cb1b-4192-b827-251a1bbd411f` (3 curiosidades surpreendentes sobre Marte).
  - Vídeo Final: `storage/validation/v16_10/final_render_mars.mp4` (38.38 MB, 1080x1920, 46.70s, 30fps).
  - Total de Cenas: 7 (4 stock alta confiança + 3 temáticas autênticas com still-motion 9:16).
  - Cenas Críticas (Hero) Contextualizadas: 3/3 (Cena 3 Olympus Mons wiki_98866197 @ 82.8, Cena 4 Mapa Caldera wiki_127759484 @ 78.0, Cena 7 Blue Sunset NASA Mastcam-Z nasa_PIA24935 @ 73.0).
  - Score Médio de Matching: 83.9/100 (contra baseline de stock fraco 28.0, 28.0, 22.0).
  - Ativos Repetidos: 0.
  - Chamadas Pagas de IA: 0 (Zero billing, zero custo).
  - Falhas / Quedas no Pipeline: 0.
  - Relatórios de Auditoria: `storage/validation/v16_10/full_render_audit.json` e `full_render_audit.md`.
## V16.11 — Adaptive Visual Feedback (Learning Loop)
- **Status:** ✅ DEV_HOMOLOGATED / READY_FOR_ADAPTIVE_VISUAL_PRODUCTION_DEPLOY (06/10/2026)
- **Priority:** P1
- **Escopo e Implementação:**
  - Aprendizado operacional incremental leve sem modelos pesados de ML e zero dependências pagas.
  - Tabela persistente `visual_experience` em `storage/video_factory.db` com migração idempotente e 7 índices analíticos (`video_subject`, `provider`, `asset_id`, `search_query`, `human_feedback`, `task_id`, `created_at`).
  - Auto-registro transparente acoplado ao fechamento da resolução de materiais de cena (`SceneMaterialSelection`), rastreando estratégias, notas, fallbacks e repetições com chave idempotente `task_id + scene_index + asset_id + strategy_selected`.
  - Ranking adaptativo contextual integrado ao `HybridVisualDirector` com saturação rígida na faixa segura `[-15.0, +15.0]`:
    - Bônus para feedback humano GOOD (+5 pts) e notas altas (score 5: +8 pts, score 4: +5 pts).
    - Penalidades severas para histórico BAD (-10 pts) e nota 1 (-12 pts).
    - Penalidade preventiva de repetição no mesmo vídeo ou histórico recente (-15 pts).
    - Penalidade para queries com alta taxa de fallback (> 50%: -5 pts).
    - Bônus de autoridade temático para provedores com taxa de sucesso > 85% no mesmo domínio (+3 pts).
  - Fluxo de feedback humano granular e global: script CLI `scripts/rate_visual_task.py` e serviço `record_human_feedback` com proteção fail-closed (`confirm_all` obrigatório para alterar status individual de cenas).
  - Bootstrap canônico da homologação de Marte V16.10 (`17386147-cb1b-4192-b827-251a1bbd411f`): 7 cenas migradas com status técnico PASS e cenas individuais mantidas como UNREVIEWED.
  - Testes direcionados: 13 testes PASS em 3.97s (`test/services/test_adaptive_visual_feedback.py`).
- **Próximo Gate Seguro:**
  - `SINGLE_CONSOLIDATED_PRODUCTION_DEPLOY` (Deploy único consolidado de DEV para Produção no PC Forte).

## V16.12 — Upstream v1.3.8 Selective Backport
- **Status:** ✅ DEV_HOMOLOGATED / READY_FOR_V1_3_8_SELECTIVE_PRODUCTION_DEPLOY (06/10/2026)
- **Priority:** P1
- **Escopo e Auditoria da Release v1.3.8:**
  - Backport cirúrgico e seletivo das melhorias da release upstream v1.3.8, preservando 100% da arquitetura proprietária (Thematic Sources NASA/Wikimedia, Visual Matching v2, Adaptive Visual Feedback, Scene-based rendering, Subtitle/Narration recovery, SQLite experience store).
  - Tabela de Auditoria e Classificação:
    | Feature / Componente | Arquivo Upstream | Classificação | Racional / Justificativa | Arquivo Local |
    | :--- | :--- | :--- | :--- | :--- |
    | FFmpeg Timeout & Heartbeat | `video.py` | ADAPT | Timeout explícito de 3600s com log de heartbeat a cada 30s; falha com `TimeoutError` sem fallback síncrono para MoviePy concat (evita travar host). | `app/services/video.py` |
    | Atomic Video Render & Replace | `video.py` | ADAPT | Render grava em `.tmp` intermediário e promove com `os.replace` atômico; render falho não corrompe vídeo pré-existente válido. | `app/services/video.py` |
    | Temp Clip Cleanup on Finally | `video.py` | ADOPT | Clips intermediários gerados em `combine_videos` são sempre deletados em bloco `finally`, mesmo em falhas de concat. | `app/services/video.py` |
    | BT.709 Color Space Consistency | `video.py` | ADAPT | Filtro `-vf "colorspace=all=bt709:trc=bt709:primaries=bt709:format=yuv420p"` aplicado no stream copy, legendas ASS nativas e zoom rendering. | `app/services/video.py` |
    | Stage Progress Reporting | `task.py`, `video.py` | ADAPT | 7 subestágios explícitos emitidos (`SCENE_RENDER_PREP`, `SCENE_RENDER_CLIPS`, `CONCAT`, `FINAL_RENDER_AUDIO`, `FINAL_RENDER_SUBTITLE`, `FINAL_RENDER_ENCODE`, `FINAL_RENDER`) com percentual real de cobertura. | `app/services/task.py`, `app/services/video.py` |
    | Stock Streaming & 512MB Limit | `material.py` | ADOPT | Streaming em blocos de 1MB com teto estrito de 512MB, arquivo staged temporário, validação por probe e promote atômico via `os.replace`. | `app/services/material.py` |
    | Video Cache Cleanup | `cache_manager.py` | ADAPT | Reconhecimento de `.vid-*.mp4` órfãos (>24h); verificação consistente de dispositivo, inode e mtime compatível com Windows e Linux para evitar race conditions com downloads ativos. | `app/services/cache_manager.py` |
    | Concurrency Config Defaults | `config.py` | ADAPT | Suporte a concorrência configurável, mas com defaults estritos `= 1` (`material_concurrency = 1`, `video_clip_concurrency = 1`), mantendo comportamento serial em produção. | `app/config/config.py` |
    | Upload-Post Redirect Rejection | `upload_post.py` | ADOPT | `allow_redirects=False` rejeitando status 3xx que possam corromper multipart upload. | `app/services/upload_post.py` |
    | Upload-Post Client Request ID | `upload_post.py` | ADAPT | UUID4 `client_request_id` enviado em form-data para idempotência de publicação; retorno `unconfirmed_response` em timeout/500 preservando `external_profile_name` e YouTube `privacyStatus`. | `app/services/upload_post.py` |
    | Thread Log Scoping | `logging_utils.py` | ADAPT | Vinculação de escopo de thread para redirecionamento transparente de logs de subprocessos/workers no Streamlit/WebUI. | `app/utils/logging_utils.py`, `app/services/webui_task.py` |
    | Concurrency Defaults > 1 | `config.py` | SKIP | Upstream configurou concorrência padrão como 4; rejeitado para preservar estabilidade de host e evitar contenção de CPU/GPU. | `app/config/config.py` |
    | Novos LLMs / VoxCPM / MuAPI | Vários | SKIP | Rejeitados por política: mantemos edge-tts / azure / gpt-sovits sem provedores pagos desnecessários. | N/A |
    | Auto Publish Activation | `task.py` | SKIP | Rejeitado: Auto Publish permanece estritamente desativado em DEV e sob controle humano no PC forte. | N/A |
- **Validação Local Controlada:**
  - Script executado: `scripts/validate_v16_12_controlled_render.py`.
  - Render success: `True`, timeout não disparado (`elapsed=50.48s` < 3600s).
  - Resolução: `1080x1920` (9:16 portrait), duração 3.0s, tamanho: 511.977 bytes.
  - BT.709 detectado: `yuv420p(tv, bt709, progressive)` validado via FFmpeg stream info.
  - Subestágios capturados: `SCENE_RENDER_PREP`, `SCENE_RENDER_CLIPS`, `CONCAT`.
  - Limpeza de temporários: 0 arquivos residuais em diretório de validação.
  - Testes direcionados: 10 testes PASS em 2.70s (`test/services/test_v16_12_backport.py`), lint limpo (`uv run ruff check` — 0 erros).
- **Próximo Gate Seguro:**
  - `SINGLE_CONSOLIDATED_PRODUCTION_DEPLOY` (Deploy único consolidado de DEV para Produção no PC Forte).

---

# Nova Frente: Qualidade Visual Externa (Google Flow / Google AI Pro / Nano Banana)

**Status:** ✅ ACTIVE (07/10/2026)
**CURRENT_FOCUS:** `VIDEO_QUALITY_GOOGLE_FLOW`
**CURRENT_PHASE:** `V1.3_AGENT_DIRECTOR`

## Objetivo da Frente
Melhorar significativamente a qualidade visual dos vídeos gerados utilizando **Google AI Pro / Google Flow / Nano Banana** como geração externa de clipes, mantendo a **Video Factory (MoneyPrinterTurbo)** como o motor central responsável por:
- Roteiro (scriptwriting e estrutura de cenas)
- Narração (TTS neural, timing e áudio)
- Montagem (concatenação e edição)
- Legendas (estilos ASS / burn-in nativo)
- Música (trilha sonora de fundo)
- Publicação (YouTube e canais configurados)

## Princípio Fundamental: "FAZER MENOS"
- **Sem arquitetura excessiva:** Evitar camadas de abstração prematuras ou especulativas.
- **Sem testes redundantes:** Testes direcionados somente quando estritamente necessários; alterações puramente documentais não disparam pytest.
- **Sem gates desnecessários:** Eliminar etapas burocráticas que não agreguem valor imediato.
- **Não reconstruir o que já existe:** Aproveitar integralmente os serviços consolidados de TTS, legendagem, montagem e publicação da Video Factory.
- **Se funcionou, considerar concluído:** Evitar refinamento infinito sobre o que já atingiu o objetivo.
- **Priorizar solução pronta:** Focar no resultado prático e entrega rápida de vídeo real.

## Isolamento Rígido de Ambientes (DEV-FIRST / PRODUCTION-LAST)
- **DEV / Notebook (`D:\Projetos\MoneyPrinterTurbo`):** Todo desenvolvimento, experimentação, criação de scripts e validações locais ocorrem aqui.
- **PRODUÇÃO / PC Forte (`C:\Projetos\MoneyPrinterTurbo`):** Ambiente estrito de produção.
- **Diretrizes Operacionais Mandatórias:**
  - Não implementar, experimentar ou fazer investigação exploratória no PC Forte quando isso puder ser feito no notebook.
  - Só levar alterações ao PC Forte quando: (1) a implementação estiver pronta e validada no notebook; ou (2) houver um teste que dependa especificamente do ambiente de produção.
  - Não sincronizar mudanças parciais apenas para testar hipóteses.
  - Sempre preservar a regra: nunca misturar os dois ambientes.

## Fronteiras e Escopo de Modelos
- **Google Flow API:** **NÃO integrar neste momento.** Produzir primeiro vídeos reais manualmente no Google Flow para entender e lapidar o workflow antes de qualquer tentativa de automação.
- **MuseTalk local (RX580 + DirectML):** POC concluída com sucesso; permanece estritamente **congelado** como laboratório/fallback futuro. Não trabalhar nele agora.
- **Fora de escopo atual:** Krea, HeyGen pago e ElevenLabs vídeo não fazem parte do escopo desta frente.

---

## Roadmap da Nova Frente

### V1.1 — Produzir Primeiro Vídeo Real
- **Objetivo:** Produzir o primeiro vídeo REAL de ponta a ponta combinando o melhor dos dois mundos:
  1. Roteiro e narração integral já existentes gerados pela Video Factory (~90s com voz Antônio Neural).
  2. 4 clipes de alta fidelidade gerados no Google Flow utilizados como cenas premium nos momentos narrativos correspondentes (`flow_01_dallas.mp4`, `flow_02_parkland.mp4`, `flow_03_nuclear_briefcase.mp4`, `flow_04_cold_war.mp4`).
  3. Preenchimento do restante do vídeo com clipes locais/stock já existentes da Video Factory, sem repetição de clipes Flow e sem esticamento artificial.
  4. Video Factory responsável por montagem, descarte do áudio dos clipes Flow, legendas ASS nativas, trilha sonora e render 1080x1920 (9:16).
- **Critério de Aceite:** Duração >= 60s, meta 75–90s, narração completa, legendas corretas e qualidade visual consistente.
- **Status:** ✅ CONCLUÍDA / APROVADA
  - **Runner final:** `scripts/run_v1_1_flow_jfk_video.py`
  - **Commit funcional de referência:** `65ff981`
  - **Duração final obtida:** 90.50s (tamanho 30.08 MB, 1080x1920, áudio íntegro).
  - **Resultado:** `QUALITY_BASELINE = APROVADA`, `PUBLICÁVEL = SIM`.
  - **Core da aplicação:** 100% preservado sem nenhuma modificação.

### V1.2 — Otimizar Passos Manuais com Fricção Real
- **Objetivo:** Reduzir exclusivamente os passos manuais que efetivamente causarem atrito ou retrabalho durante a operação prática da frente:
  - Preparação e estruturação de prompts visuais para o Google Flow (9:16 portrait em `prompts_for_flow.md`);
  - Divisão de cenas temporizada e alinhamento com a narração via `scene_planner`;
  - Organização e nomenclatura padronizada dos clipes baixados (`manifest.json` e `clips/flow_scene_XX.mp4`);
  - Ingestão simplificada dos clipes pela Video Factory no pipeline de renderização em comando único (`render` com `--dry-run` e fallback híbrido).
- **Regra Rígida:** **NÃO integrar API do Google Flow ainda.** Manter fluxo operacional manual até validação de múltiplos vídeos reais.
- **Status:** ✅ CONCLUÍDA / HOMOLOGADA
  - **Utilitário Padronizado:** `scripts/flow_workflow.py` com modos `prepare`, `status` e `render`.
  - **Validação:** 3 testes unitários PASS em `test/services/test_flow_workflow.py` (0.07s).

### V1.3 — Assistência do Agente (Cenas, Prompts e Manifesto) (CURRENT_PHASE)
- **Objetivo:** Agente assume o papel de diretor assistente:
  - Divisão automatizada de cenas baseada no roteiro/áudio.
  - Formulação de prompts visuais detalhados prontos para colar no Google Flow.
  - Geração de manifesto de mídia estruturado para ingestão facilitada na montagem.
- **Status:** `ACTIVE / IN PROGRESS`

### V1.4 — Avaliação de API e Automação
- **Objetivo:** Avaliar a viabilidade de automação via API ou conectores programáticos somente após a produção e validação de múltiplos vídeos reais manuais.
- **Critério:** Decisão baseada em volume real, estabilidade do workflow e custo-benefício.
- **Status:** `FUTURE / CONDITIONAL`

---

## Visão e Diretrizes Futuras (Planned / Backlog)

- **FUTURE_MULTI_CHANNEL_MULTI_NICHE = planned:**
  - **Arquitetura Mandatória:** Uma ÚNICA Video Factory atendendo múltiplos canais, perfis e nichos, sem criar aplicações separadas para cada canal.
- **FUTURE_LONG_FORM_VIDEO = planned:**
  - Suporte à produção de vídeos longos horizontais (16:9) utilizando a mesma esteira de qualidade visual híbrida.
- **FUTURE_FLOW_API_AUTOMATION = evaluate_later:**
  - Avaliação de conectores e APIs oficiais após consolidação do processo manual.
- **FUTURE_LOCAL_VIDEO_AI = evaluate_after_hardware_upgrade:**
  - Avaliação de geração local de vídeo após futuro upgrade de hardware e GPU dedicada (mantendo MuseTalk DirectML como laboratório congelado).

---

## Regra de evolução

Toda nova fase deve:
- ter escopo fechado
- ter critérios de aceite
- ter testes
- passar regressão adequada
- atualizar `PROJECT_HANDOFF.md`
- atualizar este `ROADMAP.md`
- atualizar `PRODUCTION_RUNBOOK.md` se alterar operação
- não ativar produção automaticamente
- não mudar TikTok sem homologação explícita
- não enfraquecer Safety / Quality / Growth Mode
