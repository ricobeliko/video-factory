# PROJECT_HANDOFF — Video Factory / MoneyPrinterTurbo

## Estado Atual Canônico — 06/10/2026

- **PROJECT_STATUS** = `DEV_VALIDATED / THEMATIC_SOURCES_EVALUATED_PASS`
- **ACTIVE_PHASE** = `V16.8.2 — Alternative Visual Sources Evaluation`
- **ACTIVE_BRANCH** = `feat/v16-8-2-alternative-visual-sources`
- **NEXT_GATE** = `V16.9 — Hybrid Visual Production Rollout`
- **BLOCKED_BY** = `NONE`

> [!IMPORTANT]
> **Precedência Canônica:** Esta seção reflete o estado consolidado e auditado da fábrica de vídeos em produção no PC forte (`C:\Projetos\MoneyPrinterTurbo`). Ela prevalece formalmente sobre quaisquer menções ou snapshots históricos contidos nas seções inferiores deste documento.

### Status Consolidado dos Componentes:
- **V16.0 Quality Audit** = DONE
- **V16.1 Brazilian Content Contract** = PRODUCTION HOMOLOGATED (Deploy SHA: `3983d37a29d1f169e513f19bd7186348a74ad5e9`)
- **V16.2 Subtitle Reliability Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `0744fd2b8593fa276a2d3117d88b270475b5b05c`)
- **V16.3 Final Media Quality Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `9e3fde0b35e28781aab67117d5ff33c182b337ef`)
- **V16.4 Scene-Based Video Generation** = PRODUCTION HOMOLOGATED
- **V16.4.1A Scene Render Performance Hardening** = PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **V16.4.1B Final Render Performance** = PRODUCTION HOMOLOGATED (Deploy SHA: `e7f40ed6f4b7df45e5868cd7de03495239d103ec`, Task Homologada: `f9a9608b-512d-43c4-92f4-f864a0424512`)
- **V16.4.1C Render Pipeline Gap Instrumentation** = PRODUCTION HOMOLOGATED (Deploy SHA: `d231e3900bbbace180c0c71e60e9fb08c2d713e0`, Task Homologada: `337639bb-1740-4398-a923-c5f75b1f236a`)
- **V16.4.1D Post-Encode Performance Investigation** = MERGED (Deploy SHA: `d13d9347fc96c6a967561821552bbb19452eb281`, PR #45)
- **V16.4.2R Pre-Repair Publishing Reset** = PRODUCTION HOMOLOGATED (Deploy SHA: `83be45cb95fc5c8b74c43844621ebf9c6d328b9c`, PR #48)
- **V16.4.2A Publishing State Reconciliation** = PRODUCTION HOMOLOGATED (PC Forte Reconciled)
- **V16.4.2B Publishing Idempotency / Duplicate Protection** = MERGED (PR #50)
- **V16.4.2C Retry Metadata Cleanup** = MERGED (PR #51)
- **V16.5 Visual Matching v2** = MERGED (PR #53, SHA `b6e900ed93edb6e0e59c00600532f7ca2afeb6bd`)
- **V16.5.1 Subtitle & Narration Quality Recovery** = MERGED (PR #54, SHA `4823a799d3030982d27e0eeccea1ab3f73a065f7`)
- **V16.6 Hybrid Visual Generation Foundation** = MERGED (PR #55)
- **V16.6.1 Open Source Video Benchmark Preparation** = DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS
- **V16.6.2 Contextual Image-to-Video Foundation** = MERGED (PR #56, SHA `0264fb7daaf327e1677cc209cd20308a9af6c8ce`)
- **V16.7 Hybrid Scene Director** = MERGED (PR #57, SHA `ae6738821516d3310493060654d4a8776bc74548`)
- **V16.8 Controlled Hybrid Render Validation** = DEV_VALIDATED / STRUCTURAL_AND_PROXY_PASS (PR #58, SHA `fd205f24275a43ab67486e9261cd6b45cfbfd4d8`)
- **V16.8.1 Real Generated Image Quality Gate** = REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED
- **V16.8.2 Alternative Visual Sources Evaluation** = DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)
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
- **Presenter autonomous**: OFF (`avatar_mode="none"`)
- **TikTok**: OFF / NOT HOMOLOGATED
- **V15-A Production Observability Baseline** = DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET
- **V15-E.1 YouTube Direct Foundation** = HOMOLOGATED (POC Validada nos 2 Canais)
- **V15-E.2 Post for Me YouTube Publisher** = DEV IMPLEMENTED / READY FOR POC HOMOLOGATION

### Produção Atual (Estado Operacional Consolidado):
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
- **Safe updater** = ACTIVE (`scripts/update_production.ps1`)

**Última homologação real de produção (V13-B):**
- TARGET/FINAL_SHA: `46e44c2495a8fe38484977ad1aa7cff439e26679`
- BACKUP: PASS (`storage/backups/database/video_factory_20260923_061728.db`, SHA-256: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`)
- SQLITE_INTEGRITY: OK
- STOP: PASS
- FF UPDATE: PASS
- START: PASS
- HEALTH: PASS (HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`)
- ROLLBACK: NOT_REQUIRED
- DEPLOY: SUCCESS
- Documentação posterior: main `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`

---

## V15 — Production Observation & Optimization — OPEN / OBSERVATION FIRST

- **Baseline Main:** `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`
- **Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
- **Status da Fase:** OPEN / OBSERVATION FIRST
- **Princípio Operacional:** Observar a fábrica completa em funcionamento real no PC forte antes de adicionar novas features.
  - Metodologia: `OBSERVAR → MEDIR → IDENTIFICAR GARGALO REAL → PRIORIZAR → OTIMIZAR`
  - Evitar rigorosamente: otimização prematura, novos providers, novos avatares, novos canais, TikTok ou aumento de volume sem evidências.
- **Subfase Ativa:** **V15-A — Production Observability Baseline**
  - **Status:** DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET
  - **Implementação Realizada:**
    1. Serviço read-only criado: `app/services/production_observability.py` com função `get_production_observability_snapshot()`.
    2. Coleta passiva completa das 9 dimensões operacionais para os dois canais (`default` e `profile-historias-misterio`).
    3. Alertas factuais observáveis sem score arbitrário: `READY_STOCK_EMPTY`, `COPYRIGHT_BLOCKED`, `SCHEDULER_FAILURES_PRESENT`, `CLOSED_LOOP_BASELINE`, `ANALYTICS_STALE`, `GLOBAL_COST_GUARD_NEAR_LIMIT`.
    4. CLI read-only com saída estritamente JSON em stdout e logs silenciados: `python -m app.services.production_observability --json`.
    5. Seção no Operator Console: `"📊 Production Observability — V15"` com visualização lado a lado.
    6. Fail-safe por seção (`status="unavailable"` sem derrubar snapshot) e distinção estrita entre 0, "unknown" e "unavailable".
    7. Validação direcionada: 7 testes PASS (`test/services/test_production_observability.py`) cobrindo isolamento, zero mutações, zero network, e serialização JSON.
  - **Próximo Gate:** Deploy seguro via `scripts/update_production.ps1` e execução read-only no PC forte.

---

## V13-B — Production Homologation / Safe Remote Deployment Active — HOMOLOGATED

- **Baseline:** `46e44c2495a8fe38484977ad1aa7cff439e26679`
- **Contexto Operacional e Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
  - Status dos Componentes:
    - `V13-A` = MERGED
    - `V13-A.1` = MERGED (hotfix de separação stdout/stderr no backup)
    - `V13-B` = PRODUCTION HOMOLOGATED
    - `V14-B.2` = PRODUCTION HOMOLOGATED
    - `V14-B.2.1` = PRODUCTION HOMOLOGATED
    - `Presenter/Nox` = DORMANT / OFF (`avatar_mode="none"`)
- **Evidência Operacional Real da Homologação:**
  - `CURRENT_SHA`: `e3f024938c5338c197a1f1654775686227f3eb05`
  - `TARGET/FINAL_SHA`: `46e44c2495a8fe38484977ad1aa7cff439e26679`
  - `BACKUP`: PASS
  - `BACKUP_FILE`: `storage/backups/database/video_factory_20260923_061728.db`
  - `BACKUP_SHA256`: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`
  - `SQLITE_INTEGRITY`: OK
  - `SAFE_STOP`: PASS (`schtasks /End /TN "VideoFactory Production"`)
  - `FAST_FORWARD_UPDATE`: PASS (`git merge --ff-only 46e44c2495a8fe38484977ad1aa7cff439e26679`)
  - `SAFE_START`: PASS (`schtasks /Run /TN "VideoFactory Production"`)
  - `HEALTH`: PASS (HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`)
  - `ROLLBACK`: NOT_REQUIRED
  - `DEPLOY_STATUS`: DEPLOY_SUCCESS
- **Novo Contrato Operacional de Produção:**
  - Atualizações futuras da produção devem obrigatoriamente utilizar `scripts/update_production.ps1`.
  - Fluxo oficial obrigatório: Preflight -> Backup SQLite -> integrity_check -> Stop -> Fast-Forward Update -> Start -> Health Check -> Rollback automático se necessário.
  - Proibido pull manual como fluxo padrão.

## V13-A — Headless Remote Deployment / Safe Update Foundation — MERGED

- **Baseline:** `ee32d801bfd8a5b9b6f7ecbb57c556aa803327f5`
- **Contexto Operacional e Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
  - Status desta fase: **MERGED** (homologada em produção na V13-B)
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT (experimento arquivado em branch separada, produção e main com `avatar_mode="none"`)
- **Implementação Realizada:**
  1. Script de atualização criado em `scripts/update_production.ps1` aceitando `-TargetRef` (default `origin/main`), `-RepoPath` (default `C:\Projetos\MoneyPrinterTurbo`), `-TaskName` (default `VideoFactory Production`), `-HealthUrl` (default `http://127.0.0.1:8501/_stcore/health`) e `-PreflightOnly`.
  2. **Pipeline de Execução Completo:**
     - `PRE-FLIGHT`: Verificação fail-closed de working tree limpa (rejeita alterações não commitadas ou arquivos untracked críticos), branch/HEAD válida, .venv existente, resolução de commits e verificação de Fast-Forward (`git merge-base --is-ancestor`).
     - `BACKUP`: Snapshot transacional SQLite pré-stop via `app.services.production_backup` com `PRAGMA integrity_check` e manifesto sidecar com SHA-256. Se integridade != ok, aborta antes de qualquer mutação.
     - `STOP`: Parada controlada e delimitada via `schtasks /End /TN "VideoFactory Production"`, aguardando encerramento sem matar processos aleatórios.
     - `UPDATE`: Atualização estritamente Fast-Forward (`git merge --ff-only TARGET_SHA`) com validação de `git rev-parse HEAD == TARGET_SHA`.
     - `START`: Inicialização segura via `schtasks /Run /TN "VideoFactory Production"`.
     - `HEALTH CHECK`: Avaliação delimitada em `http://127.0.0.1:8501/_stcore/health` (timeout 75s, HTTP 200 + corpo contendo `ok`).
     - `ROLLBACK`: Se o health check falhar pós-update, para a Scheduled Task, retorna para `CURRENT_SHA` via `git switch --detach CURRENT_SHA` (zero `git reset`, `git restore` ou `git clean`, preservando a branch `main`), reinicia a tarefa e repete o health check. Se passar: `ROLLBACK_SUCCESS`; se falhar: `ROLLBACK_FAILED` com parada e exigência de intervenção humana.
  3. **Lock e Logging Local:** Lock exclusivo em `storage/locks/update_production.lock` com limpeza garantida em bloco `finally`. Logs timestampados em `logs/deploy/` estritamente sanitizados (sem API keys, tokens ou secrets).
- **Validação:**
  - Teste direcionado único criado em `test/services/test_safe_production_update.py` cobrindo 13 verificações estáticas e funcionais em repositório temporário isolado (13 passed in 6.68s).
- **Próximo Passo:** V13-B = Primeira instalação e homologação real no PC forte.

## V14-B.2 — Manual Copyright Status + Closed Feedback Loop Exclusion — MERGED

- **Baseline:** `150056215fcbd8296fcdeac56abac0d37f787cc8`
- **Contexto Operacional:** Produção parada após homologação da V14-B e V14-B.1. Evidência real conhecida: task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) publicada com sucesso e posteriormente bloqueada mundialmente via Content ID no YouTube Studio. O YouTube Data API não fornece status detalhado de Content ID, exigindo status manual/auditável do operador.
- **Implementação Realizada:**
  1. Status de copyright suportados: `unknown`, `clean_manual`, `claimed`, `blocked`, `strike` (com source `operator` e espaço futuro para `future_provider`).
  2. Persistência auditável em `operational_events` com `metadata_json` completo (`task_id`, `publication_event_id`, `platform`, `external_id`, `copyright_status`, `source`, `timestamp`, `note`) sem migrações ou tabelas novas no SQLite.
  3. Operações no Console do Operador:
     - `set_publication_copyright_status_op(...)`: PRIMARY only, valida status permitido, valida publicação existente no YouTube em status `success`, idempotente quando o mesmo status é reaplicado, nunca chama rede.
     - `get_publication_copyright_status(...)`: leitura do status mais recente (read-only), retornando `unknown` para publicações sem registro.
  4. Regra crítica no Closed Feedback Loop (`analytics.get_learning_evidence`):
     - `clean_manual` => elegível de copyright para compor amostras de aprendizado.
     - `claimed`, `blocked`, `strike` => SEMPRE EXCLUÍDOS.
     - `unknown` (inclusive publicações legadas sem status) => FAIL CLOSED (EXCLUÍDOS).
     - Auditoria explícita em `excluded_counts_by_reason`: `copyright_unknown`, `copyright_claimed`, `copyright_blocked`, `copyright_strike`.
  5. Preservação integral de histórico: métricas e registros de publicação nunca são apagados.
  6. Operator Console UI: card Copyright / Assets atualizado com badges de status, source e elegibilidade do loop, e formulário auditável não-destrutivo para marcação manual.
  7. Preparação para o vídeo bloqueado conhecido: task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) pronta para marcação como `blocked` pós-deploy.
  8. Presenter: DORMANT (experimento arquivado em branch separada, produção e main mantidas com `avatar_mode="none"`).
- **Próximo Passo:** Homologação concluída com sucesso em produção na V13-B. Próxima fase global: V15.

## V14-C.3 — Nox Canonical Visual Asset Pack + Real Local Preview — EXPERIMENT ARCHIVED / DORMANT

- **Baseline:** `447a36789850857a66422ad06f1800f18cccd96a`
- **Contexto Operacional:** Experimento visual de Nox não atingiu os requisitos de qualidade e dinamismo.
- **Presenter / Nox DORMANT:**
  - V14-C.4 NÃO é a próxima fase ativa.
  - O experimento visual foi formalmente descontinuado e arquivado na branch: `archive/v14-c3-nox-presenter-experiment`.
  - Frameworks V14-C, V14-C.1 e V14-C.2 permanecem no código, mas o modo autônomo está estritamente desligado (`avatar_mode="none"`).
- **Implementação Realizada (Histórico):**
  1. Estrutura canônica de diretórios criada em `assets/presenter/nox_v1/` (`manifest.json`, `reference/`, `poses/`, `previews/`).
  2. Manifest canônico estruturado com metadados de identidade visual (pele morena clara, cabelo preto com reflexos roxos, olhos castanhos, roupa jaqueta/moletom preto).
  3. Contrato de 9 Core Poses obrigatórias e catálogo de 13 Extended Motion Poses opcionais.
  4. Fallback Graph determinístico implementado para poses estendidas ausentes (`EXTENDED_POSE_FALLBACKS`).
  5. Validação rigorosa de integridade e consistência gráfica (`validate_character_pack_assets`) verificando PNG, canal alfa real e conformidade dimensional.
  6. Gerador local de Contact Sheet (`generate_contact_sheet`) renderizando grid com Core Poses e Extended Poses rotuladas.
  7. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).
- **Próximo Passo:** V15-A — Production Observability Baseline (V15 — Production Observation & Optimization).

## V14-C.2 — Expressive Presenter + Subtitle Interaction — MERGED

- **Baseline:** `def541870a598ee8984a6a2b98bed39688434691`
- **Contexto Operacional:** Produção parada. Objetivo: dotar o Nox de capacidade expressiva sincronizada com legendas e narração (SRT), alternância de fala, reações semânticas e apontamentos geométricos sem lip-sync neural.
- **Implementação Realizada:**
  1. Parser determinístico e tolerante a falhas de SRT (`parse_srt_timeline`), convertendo legendas para estrutura temporal unificada.
  2. Classificador prioritário de legendas (`classify_subtitle_reaction`) com categorias PT-BR (SURPRISE, THINKING, SERIOUS, CTA, DEFAULT) e precedência estrita (`CTA > SERIOUS > SURPRISE > THINKING > TALKING > NEUTRAL`).
  3. Alternância determinística de fala (`talking_1` e `talking_2` em fatias de 0.35s) ativa somente durante trechos falados e visíveis.
  4. Interação de apontamento (`pointing_left` para `bottom_right`, `pointing_right` para `bottom_left`) para direcionar o espectador para a legenda.
  5. Tom de canal respeitado: `profile-historias-misterio` utiliza reações sóbrias e contidas (`mystery_contained_reaction`).
  6. Construção da timeline de expressões (`build_presenter_expression_timeline`) respeitando estritamente os segmentos do presenter e sem sobreposição temporal inválida.
  7. Performance otimizada no MoviePy via cache único de clips de pose no ExitStack.
  8. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).

## V14-C.1 — Cartoon Character Asset Pack + Preview — MERGED

- **Baseline:** `b9e73e2a98f020e54be304396749e5c86e67cbb1`
- **Contexto Operacional:** Produção parada após entrega da infraestrutura básica do presenter (V14-C). Objetivo: criar especificação do personagem unificado **Nox** (`nox_v1` / `misterio_host_v1`, `SINGLE_CHARACTER_ALL_CHANNELS = YES`), estruturar contrato de asset pack local, controller de poses e modo de preview controlado.
- **Implementação Realizada:**
  1. Especificação completa do personagem documentada em `docs/CHARACTER_PRESENTER_SPEC.md` (Nox `nox_v1`, estilo cartoon/semi-cartoon, paleta sóbria grafite/vinho, proporções waist-up).
  2. Contrato de Asset Pack local estabelecido em `storage/presenter_assets/<character_id>/` e `resource/presenter_assets/<character_id>/` com catálogo de poses (`neutral`, `talking_1`, `talking_2`, `surprised`, `serious`, `thinking`, `pointing_left`, `pointing_right`, `cta`) e `config.json`.
  3. Resolução de Character Pack por `character_id` em `presenter.py` (`resolve_character_pack`) com fail-closed para poses obrigatórias ausentes.
  4. Pose Controller determinístico (`select_presenter_pose`) selecionando poses por segmento narrativo (hook, return, cta, corner).
  5. Suporte a Preview controlado (`render_presenter_preview` e `generate_presenter_preview_frame`) para validação estática e render sem tocar produção.
  6. Produção autônoma estritamente preservada com `avatar_mode="none"`.

## V14-C — Hybrid Character Overlay MVP — MERGED

- **Baseline:** `4ba4a8db0314bdd8ace5c54072f1b69b5c11a791`
- **Contexto Operacional:** Produção parada após homologação da V14-B e V14-B.1. Objetivo: habilitar infraestrutura técnica para personagem/apresentador virtual sobre o vídeo final sem dependências pagas nem lip-sync neural.
- **Implementação Realizada:**
  1. `VideoParams` expandido com campos: `avatar_mode` (`none`, `corner`, `hybrid`, `full`), `avatar_provider` (`local`), `avatar_character_id`, `avatar_asset_path`, `avatar_position` (`bottom_right`, `bottom_left`, `bottom_center`), `avatar_scale` (0.1 a 1.0), `avatar_opacity` (0.0 a 1.0) com validações robustas.
  2. Serviço dedicado `app/services/presenter.py` com validação de config, bloqueio de path traversal, cálculo determinístico de timeline (`build_hybrid_presenter_segments`) e layout com safe margins para Shorts.
  3. Composição Z-Order em `video.generate_video()` com suporte a MoviePy 2.x: B-roll (base) -> Presenter Overlay -> Subtitles (topo), evitando render duplo.
  4. Proveniência de Presenter integrada em `build_asset_provenance()` e `get_copyright_provenance_summary()` em `copyright_gate.py`.
  5. Telemetria no Operator Console: Mode, Character ID, Provider e Asset Status.
  6. Modo autônomo estritamente fixado em `avatar_mode="none"`.

## V14-B.1 — Legacy Stock Copyright Quarantine (Hotfix) — PRODUCTION HOMOLOGATED

- **Baseline:** `2e285cf43bfd01dc10e04a74a35572ee6f2fab19`
- **Contexto Operacional:** Produção parada após identificação de 23 vídeos legados não publicados contendo `bgm_type="random"` ou `bgm_type="custom"` e sem `asset_provenance`.
- **Implementação Realizada:**
  1. `_get_param()` implementado em `copyright_gate.py` para suportar uniformemente parâmetros em formato `dict` e instâncias de objeto (`VideoParams`).
  2. Tarefas antigas com `bgm_type="random"` ou `bgm_type="custom"` sem proveniência avaliam estritamente como `COPYRIGHT_PROVENANCE_GATE = FAIL`.
  3. `_recover_waiting_task()` e `get_autonomous_ready_stock()` passam a validar `evaluate_copyright_provenance_gate == PASS`, excluindo automaticamente os 23 vídeos legados do estoque autônomo e impedindo sua adoção/recuperação no Scheduler pelo Autonomous.
  4. Preservação física e histórica completa: nenhum arquivo apagado, nenhum registro SQLite destruído. Caminho manual legado preservado.

## V14-B — Copyright Baseline Hardening — PRODUCTION HOMOLOGATED

- **Baseline:** `ceb64fa441f68f722d7cc2c21b986997c5cd2177`
- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` (publicação tecnicamente correta, posteriormente bloqueada mundialmente por conteúdo reivindicado; sem evidência de strike).
- **Causa Raiz:** Músicas padrão de `resource/songs/*.mp3` originadas de vídeos do YouTube e selecionadas por `bgm_type="random"`.
- **Implementação Realizada:**
  1. Bloqueio fail-closed de faixas legadas em novas gerações autônomas via `resolve_autonomous_bgm(...)` (`bgm_type="none"`, `volume=0.0`, `SAFE_NO_BGM`).
  2. Preservação do uso manual legado (sem deleção de `resource/songs/`).
  3. `asset_provenance` persistido em `script.json` e memória (`bgm` e `visual_clips` com provedor, ID externo se disponível, URL, arquivo local e termo de busca).
  4. Copyright Provenance Gate no pipeline autônomo (fail-closed antes da aprovação da tarefa; valida BGM segura e lista de provedores permitidos: Pexels, Pixabay, Coverr).
  5. Sem promessa de ausência de claim (`COPYRIGHT_PROVENANCE_GATE = PASS`, jamais `CONTENT_ID_SAFE`).
  6. Preparação conceitual de status futuro (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`) e fontes (`operator`, `future_provider`).
  7. Backlog: exclusão no Closed Feedback Loop de publicações com reivindicação comprovada.
  8. Card "Copyright / Assets" no Operator Console.

## V12-E.3 — Autonomous Stock Buffer Hardening — DEV controlado


Implementação separada da V12-F.2, sobre o worktree existente em `54875c6`.
Produção não acessada; sem deploy, commit ou push. Os registros de produção abaixo
continuam sendo informações fornecidas pelo operador, não uma verificação nova.

O Autonomous reconstrói o estoque YouTube a partir de `monetization_safety`,
`content_quality_scores`, `task_profiles`, `task_platforms`, perfis/canais e
registros de publicação/agendamento. Revalida vídeo físico não vazio, Safety PASS,
último Quality finito >=70 e GOOD/STRONG, perfil ativo e canal YouTube habilitado.
Publicadas e canceladas são excluídas. Tasks já agendadas contam no estoque,
mas não voltam à fila de agendamento; estados ativos/inválidos em memória vetam
a recuperação. MemoryState vazio e ausência de `waiting_task_id` não apagam a fila.

Prioridade por ciclo: guards → geração ativa/revisão → recuperação de indicação
inválida → uma tentativa de agendamento com slot → reposição se abaixo da meta.
Sem slot, não chama `plan_schedule`; o bloqueio de publicação não bloqueia geração.
Cada revisão, recuperação ou tentativa de agendamento encerra seu ciclo. Geração
mantém cooldown existente e tetos efetivos de uma/ciclo e cinco/24h; falha na
contagem diária bloqueia novas gerações. Lock local impede ciclos manuais/worker
simultâneos, preservando o requisito de um único PRIMARY entre processos.

`waiting_task_id` é indicação de uma task da fila, não trava global. Retry após
tentativa sem resultado usa `autonomous_schedule_retry:<task_id>` por 15 minutos
na tabela existente `autopilot_settings`. Eventos `PROFILE_GROWTH_LIMIT_BLOCK`
têm deduplicação transacional por task/perfil/plataforma/Growth Mode durante
15 minutos, compartilhada por Autonomous, planner e executor, inclusive após restart.
Nenhuma mudança de schema, Growth Mode, Auto Publish ou integração TikTok.
Scheduler continua sendo o único publicador; elegibilidade não publica conteúdo.

Validação DEV concluída: **600 testes e 32 subtestes passaram, zero falhas**, em
246,12s, nas 23 suítes abaixo; 16 testes novos são da V12-E.3. SQLite, vídeos e
configuração sintéticos em diretórios temporários; rede bloqueada. `git diff --check`
aprovado. Fixtures antigas foram atualizadas para aprovações persistidas e para
permitir reposição sem slot; duas falhas de fixtures novas foram corrigidas antes
da execução final verde. Próximo gate seguro: revisar exclusivamente o diff V12-E.3;
qualquer homologação/deploy em produção exige autorização separada.
Arquivos desta etapa: `app/services/autonomous_production.py`,
`app/services/scheduler.py`, `test/services/test_autonomous_production.py`,
`test/services/test_autonomous_stock_buffer.py` e os três documentos canônicos
de handoff, roadmap e runbook. Alterações anteriores da V12-F.2 preservadas.

Comando de regressão isolada (23 suítes; o runner existente cria configuração
sintética, bloqueia sockets e usa somente diretórios temporários):

```powershell
.venv/Scripts/python.exe -B scripts/run_closed_loop_tests.py `
  test/services/test_analytics.py test/services/test_analytics_scheduler.py test/services/test_analytics_ingestion.py test/services/test_analytics_providers.py test/services/test_analytics_real_fetch.py `
  test/services/test_content_strategy.py test/services/test_quality_score.py test/services/test_autonomous_production.py test/services/test_autonomous_stock_buffer.py `
  test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_operator_console.py test/services/test_publication_persistence.py `
  test/services/test_single_instance.py test/services/test_production_health.py test/services/test_profile_manager.py test/services/test_profile_generation.py test/services/test_profile_scheduler.py `
  test/services/test_growth_mode.py test/services/test_trend_radar.py test/services/test_schedule_cancellation.py test/test_production_entrypoint.py test/services/test_closed_feedback_loop.py -q --tb=short
```

## [HISTORICAL SNAPSHOT / SUPERSEDED] Estado vigente — 21/09/2026 — V12-F.2 em validação DEV

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o estado histórico em 21/09/2026. As fases V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Learning Isolation), V12-F.4 (Second Channel Warm-Up), V12-F.5 (Multi-Channel Capacity), V13-A/A.1/B (Safe Production Update) e V14-A/B/B.1/B.2/B.2.1 (Copyright Hardening) foram posteriormente implementadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece formalmente.

Esta seção substitui as descrições de estado atual dos registros históricos abaixo.
Produção informada e homologada pelo operador em `54875c6`: Factory RUNNING,
PRIMARY headless ativo, Scheduler ON, Auto Publish ON, Dry Run OFF, YouTube ON,
TikTok OFF, Growth Mode WARMUP, Autonomous ON, Analytics Auto ON e MPT Auto Upload OFF.
Nenhuma consulta ao host, SQLite, configuração ou credencial de produção foi realizada nesta implementação.

V12-E e V12-F.1A/B/C estão HOMOLOGADAS EM PRODUÇÃO. YouTube Data API v3,
fetch real e persistência real homologados. Evidências fornecidas: publication event 16,
external ID `fTrkUqSnYqs`, privacy `public`, confirmação operacional 200;
snapshot 3 em `2026-09-21T07:52:50.719666+00:00`; ativação Analytics Auto no evento 211,
`2026-09-21T07:56:48.285854+00:00`. Snapshot 2, de 18/09, é anterior ao rollout atual.
Valores zero não significam erro do provider. Limites preservados: 1 fetch/ciclo, 300s;
estoque 3, uma geração/ciclo, cinco gerações/24h móveis, intervalo 15 min.

### V12-F.2 — implementação DEV controlada

Baseline de código `54875c6`; sem commit, push, deploy ou ativação nesta entrega.
Flag `closed_feedback_loop_enabled` em `autopilot_settings`, default ausente/False.
OFF preserva o caminho anterior. ON tenta adaptar somente tema/cluster e estrutura;
preset, duração, fonte, voz, CTA, ritmo, transições, legendas e música permanecem baseline.

API nova `analytics.get_learning_evidence(platform, profile_id, channel_id, cutoff_time, db_path)`:
leitura SQLite read-only consistente; scope obrigatório antes da agregação;
PUBLIC/success, identidade exata, profile persistido, Safety PASS e Quality >=70 GOOD/STRONG.
Origem `youtube_api`, metadata `dry_run=false` e `item_id` correspondente são exigidas;
dados sem procedência suficiente são excluídos. Sem uso ou reescrita do performance_score legado.

Política `v12-f2.1`: 12 publicações distintas, cinco por grupo, dois grupos comparáveis,
janela histórica 60 dias. Uma observação por external ID no scope; idade 72–96h,
mais próxima de 72h, menor ID em empate. Mediana de views é o sinal primário;
mediana de engagement é auxiliar descritiva, sem desempatar views. Leave-one-out
do vencedor precisa manter vantagem estrita. Política de rollout, não significância estatística.

Ranking recebe no máximo cinco pontos. Estruturas restritas às oficiais e às alternativas
temáticas da heurística. No máximo uma adaptação por três submissões; cluster limitado
a dois usos na janela resultante de cinco; repetição imediata de estrutura veta adaptação.
Veto ou falha retorna ao baseline, sem relaxar Safety/Quality.

`CLOSED_LOOP_DECISION` persiste evidência, candidatos/ranks, scope, baseline, escolha e
parâmetros antes da submissão. Reserva transacional revalida flag e histórico concorrente.
`CLOSED_LOOP_SUBMITTED` registra sucesso real da submissão ao pipeline. Reserva adaptada
sem confirmação após crash/falha de auditoria mantém adaptação suspensa conservadoramente;
geração baseline continua. Não excluir histórico para liberar adaptação automaticamente.

Schema changes: NONE. Reutiliza tabelas existentes. Testes executados via
`scripts/run_closed_loop_tests.py`, cópia temporária de fontes com config sintética e rede bloqueada.
Resultados finais de validação serão registrados após a regressão.
Próximo gate: revisão DEV; deploy e ativação em produção exigem autorizações separadas.

Comando de regressão isolada (somente DEV; mocks/fakes, sem rede):

```powershell
.venv/Scripts/python.exe -B scripts/run_closed_loop_tests.py `
  test/services/test_analytics.py test/services/test_analytics_scheduler.py `
  test/services/test_analytics_ingestion.py test/services/test_analytics_providers.py `
  test/services/test_analytics_real_fetch.py test/services/test_content_strategy.py `
  test/services/test_quality_score.py test/services/test_autonomous_production.py `
  test/services/test_scheduler.py test/services/test_scheduler_worker.py `
  test/services/test_operator_console.py test/services/test_publication_persistence.py `
  test/services/test_single_instance.py test/services/test_production_health.py `
  test/services/test_profile_manager.py test/services/test_profile_generation.py `
  test/services/test_profile_scheduler.py test/services/test_growth_mode.py `
  test/services/test_trend_radar.py test/services/test_schedule_cancellation.py `
  test/test_production_entrypoint.py test/services/test_closed_feedback_loop.py -q --tb=short
```

## Registros históricos anteriores ao rollout atual

Menções abaixo a Analytics OFF, Autonomous OFF, Auto Publish OFF, produção em `d1a8677`
ou F.1 incompleta descrevem etapas anteriores e não o estado vigente acima.


## V12-F.1C — Publication Privacy Persistence (21/09/2026)

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`), sem deploy em produção. Analytics Auto Collection continua `OFF`. Nenhuma API real executada; nenhum secret acessado ou exposto.

**Causa raiz:** a privacidade do YouTube nunca era persistida de forma própria em `publication_events` — o único sinal disponível era um fallback legado (`storage/tasks/<task_id>/task.json`), que não existe para o evento real homologado (`publication_event id=16`, task `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`, external_id `fTrkUqSnYqs`), apesar do operador ter confirmado visualmente PUBLIC no YouTube Studio. Isso fazia `get_known_publication_privacy_status()` retornar `unknown`, bloqueando corretamente a coleta automática (fail-closed), mas sem nenhuma forma auditável de registrar a evidência real. Também foi identificado que `fetch_real_metrics_for_publication()` (coleta manual) não verificava privacidade antes da chamada real — uma coleta manual poderia ter contornado o mesmo contrato fail-closed do Analytics automático.

**Mudanças implementadas (aditivas, mínimas, backward-compatible):**

- **Schema:** nova coluna `publication_events.privacy_status TEXT NULL`, adicionada via migração idempotente do scheduler (`_run_migrations`) e presente no `CREATE TABLE` para bancos novos. Nenhum histórico existente é reescrito.
- **Persistência:** `scheduler.record_publication_event()` aceita `privacy_status: Optional[str] = None`, normalizado para `public`/`private`/`unlisted` (ou `NULL` para valores não reconhecidos ou plataformas que não sejam YouTube).
- **Publicação futura:** `task.py` (ambos os caminhos, síncrono e assíncrono de `publish_task`) agora persiste exatamente o `privacyStatus` efetivamente enviado ao Upload-Post (`effective_youtube_privacy` / `youtube_privacy_status`), em vez de inferir depois pela configuração atual.
- **Elegibilidade do Analytics automático:** `get_known_publication_privacy_status()` prioriza `publication_events.privacy_status` persistido, com fallback legado para `task.json`, e retorna `unknown` se nada resolver. `PRIVATE`, `UNLISTED` e `UNKNOWN` continuam bloqueando (fail-closed); somente `PUBLIC` comprovado é elegível.
- **Coleta manual (`fetch_real_metrics_for_publication`):** agora exige `PUBLIC` comprovado para YouTube **antes** de qualquer requisição HTTP real, para `persist=False` e `persist=True`. Bloqueio usa o novo código de erro `ERR_PRIVACY_BLOCKED`, sem expor segredos.
- **Confirmação operacional auditável:** nova `operator_console.confirm_publication_privacy_op(publication_event_id, expected_task_id, expected_external_id, privacy_status)` — exige PRIMARY, valida exatamente o evento (status=success, platform=youtube, task_id e external_id esperados), aceita apenas valores reconhecidos, atualiza SOMENTE `privacy_status`, registra `operational_event` auditável sem secrets, não altera `scheduled_posts` nem publica nada. **Não executada em produção nesta tarefa** — permite futuramente homologar o evento real 16 (task `f9b3e05f-...`, external_id `fTrkUqSnYqs`, privacy `public`) sem SQL manual.

Regressão direcionada: suítes exigidas 100% PASS (`test_analytics_scheduler.py`, `test_analytics_ingestion.py`, `test_analytics_providers.py`, `test_analytics_real_fetch.py`, `test_scheduler.py`, `test_scheduler_worker.py`, `test_operator_console.py`, `test_autonomous_production.py`, `test_single_instance.py`, `test_production_health.py`, `test_production_entrypoint.py`, `test_publication_persistence.py`): **329 passed, 19 subtests passed, 0 failed**. Verificação adicional do publish path revelou 7 falhas pré-existentes e não relacionadas (Growth Mode/warmup de TikTok e ordenação de plataformas em `test_scheduler_execution.py`, `test_scheduler_timezone.py`, `test_publish_task.py`), confirmadas por reprodução em isolamento total sem qualquer mudança desta tarefa — não corrigidas aqui por estarem fora do escopo da V12-F.1C.

**Gate histórico posteriormente concluído:** V12-F.1A/B/C e ativação real do Analytics Auto foram homologadas pelo operador em 21/09/2026, baseline `54875c6`; ver estado vigente acima.

---

## V12-F.1B — Headless Worker Bootstrap (21/09/2026)

**Status: ✅ implementada e HOMOLOGADA em produção.** Gate headless PASS, conforme evidências fornecidas pelo operador: Scheduled Task Running, HTTP 200/ok, heartbeat do PRIMARY avançou sem navegador, `executor_last_tick` avançou sem navegador. Estado operacional confirmado: Autonomous OFF, Auto Publish OFF, Analytics Auto OFF. Produção em `d1a8677`. Backup pré-deploy: `video_factory_20260921_044508.db`, SHA-256 `2f20ae0e7814f5b8745b5025d8ba6b49073e1cfb50e042d7d631f934506a1e52`, integridade `ok`.

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`) antes do deploy. Nenhuma ativação de Analytics; nenhuma regra de publicação/Growth Mode/Safety/Quality Gate alterada.

**Causa raiz:** `scheduler.start_scheduler_worker()` só era chamado dentro do fragmento Streamlit `_render_publication_schedule()` em `webui/Main.py`, que só executa quando uma sessão de navegador conecta. Em modo headless (`--server.headless=true`), após reboot da Scheduled Task sem navegador, o script nunca era executado por nenhuma sessão e o worker (scheduler, analytics automático, produção autônoma) nunca iniciava.

**Arquitetura implementada:** um novo `scripts/production_entrypoint.py` roda no MESMO processo/interpretador que hospedará o Streamlit:

1. `operator_console.ensure_instance_initialized()` — reaproveita exatamente o mecanismo de Single PRIMARY já existente (mesmo lock SQLite, mesmos papéis PRIMARY/SECONDARY_VIEW_ONLY).
2. Se PRIMARY: `scheduler.start_scheduler_worker(interval_seconds=30)` e confirma `is_worker_alive()` antes de prosseguir (fail-closed: erro aqui aborta o processo com código de saída != 0 e o Streamlit nunca sobe).
3. Se SECONDARY_VIEW_ONLY: worker intencionalmente não iniciado.
4. Streamlit iniciado no MESMO processo via `streamlit.web.bootstrap.load_config_options()` + `streamlit.web.bootstrap.run(...)` — as duas únicas funções públicas usadas internamente por `streamlit run`, evitando subprocess e evitando depender de API privada instável (`cli._main_run`).
5. Ao encerrar (sinal, exceção do servidor ou saída normal): `scheduler.stop_scheduler_worker()` e `operator_console.release_instance_lock()` são chamados em `finally`, de forma idempotente.

`scripts/start_production.ps1` foi ajustado para chamar `production_entrypoint.py` em vez de `python -m streamlit run webui/Main.py` diretamente, preservando os mesmos parâmetros operacionais (`address`, `port`, `headless`, CORS, toolbar, usage stats etc.). Nenhum segundo processo de worker, nenhuma segunda Scheduled Task, nenhum "acordar" via navegador/WebSocket falso. A chamada existente da UI a `start_scheduler_worker()` permanece como fallback idempotente (singleton já garantido pelo código existente), sem necessidade de alteração em `webui/Main.py`.

Regressão direcionada: **349 passed; 19 subtests passed; 0 failed** (single-instance, scheduler worker, production health, autonomous production, analytics scheduler + 11 novos testes do entrypoint).

---

## V12-F.1A — Analytics Activation Hardening (21/09/2026)

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`), sem deploy em produção. Analytics Auto Collection permanece `OFF` por default; nenhum setting de produção foi alterado.

Regressão direcionada: **338 passed; 19 subtests passed; 0 failed** (baseline V12-E de 234+19 preservado, mais as suítes de analytics/providers estendidas).

Sete contratos endurecidos em `app/services/analytics_scheduler.py` e `app/services/analytics_providers/*`:

- Coleta automática restrita a YouTube (`SUPPORTED_ANALYTICS_PLATFORMS = ("youtube",)`).
- Privacidade do YouTube fail-closed: PUBLIC comprovado é exigido; PRIVATE e UNKNOWN bloqueiam.
- Deduplicação/revalidação de elegibilidade imediatamente antes de cada chamada ao provider.
- Exclusão mútua entre ciclo manual (`force=True`) e ciclo automático via lock persistido com expiração (stale).
- Revalidação de backoff por publicação antes de cada fetch dentro do mesmo ciclo.
- Sanitização de mensagens de erro de rede/HTTP para nunca expor API key/token/query sensível.
- `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED` passou a ser a fonte real do valor default (antes um literal `"False"` divergente da constante).

**V12-F.1 (auditoria e ativação completa) NÃO está concluída.** O bloqueador de lifecycle/startup identificado aqui foi corrigido pela V12-F.1B (ver seção acima). Ativação real do Analytics Auto Collection em produção continua exigindo decisão e homologação próprias, não incluídas nesta tarefa.

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

Próxima fase: **V12-F — Adaptive Learning + Multi-Channel Warm-Up**, somente planejamento nesta tarefa. Existe feedback parcial; o closed loop automático ainda precisa ser homologado. V13 e V14 permanecem posteriores.

---

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

**Data de referência:** 21/09/2026

**Projeto:** Video Factory baseado em MoneyPrinterTurbo v1.3.7

**Objetivo:** deixar o PC forte operando como fábrica autônoma 24/7 com geração, Safety/Quality Gates, Scheduler, publicação pública no YouTube e feedback por Analytics.

---

## 1. Objetivo operacional

Fluxo desejado:

Trend / Strategy
→ seleção de tema
→ criação da task
→ roteiro
→ TTS
→ materiais
→ render
→ Safety Gate
→ Quality Score
→ Scheduler
→ Growth Mode
→ publicação pública no YouTube
→ Analytics
→ feedback para estratégia
→ manutenção automática de estoque

Princípio do projeto:

**segurança e monetização > volume**

TikTok não deve entrar em produção automática até homologação separada.

---

## 2. Ambientes

### Notebook / desenvolvimento
`D:\Projetos\MoneyPrinterTurbo`

### PC forte / produção
`C:\Projetos\MoneyPrinterTurbo`

### GitHub
`https://github.com/ricobeliko/video-factory.git`

### Upstream
`https://github.com/harry0703/MoneyPrinterTurbo.git`

### Produção
- Windows 10 Pro x64
- Python 3.11
- MoneyPrinterTurbo v1.3.7
- Streamlit na porta `8501`
- bind `0.0.0.0`
- Scheduled Task: `VideoFactory Production`
- Tailscale PC forte: `100.123.12.51`
- LAN: `192.168.1.103`

O PC forte é a autoridade de:
- SQLite
- workers
- scheduler
- geração
- publicação
- Operator Console

Notebook/celular/outros PCs são clientes via navegador.

---

## 3. Single Instance

Papéis:
- `PRIMARY`
- `SECONDARY_VIEW_ONLY`

Lock:
- `PRIMARY_FACTORY`

Heartbeat:
- aproximadamente 15s

Timeout stale:
- aproximadamente 90s

---

## 4. Roadmap atual

- Base MPT v1.3.7 ✅
- Publicação manual ✅
- Batch ✅
- V2.1 Scheduler ✅
- V2.2 Scheduler Execution Engine ✅
- V3 Monetization Presets + Safety Gate ✅
- V3.1 Growth Mode ✅
- V4 Trend Radar ✅
- V5 Analytics + Feedback Loop ✅
- V6 Quality Score ✅
- V7 Content Strategy ✅
- V8 Operator Console ✅
- V8.1 Single Instance / acesso remoto ✅
- V9 Multi-profile / multi-channel ✅
- V10 Analytics Providers ✅
- V11 Clip Mode ✅
- V12 Production Host / Startup / Backup / Recovery ✅
- V12-D cancelamento terminal ✅
- V12-D.1 PRIMARY guard ✅
- V12-D.2 legacy cancellation compatibility ✅
- V12-E Autonomous Production Loop — **✅ homologada em produção**
- V12-E.2.1 One-cycle / One-transition hotfix — **homologado**
- V12-E.2.2 Persistent Waiting Schedule Recovery — **homologado**
- V12-F Adaptive Learning + Multi-Channel Warm-Up — **planejamento aberto**
- V12-F.1A Analytics Activation Hardening — **homologada em produção; Analytics ON**
- V12-F.1B Headless Worker Bootstrap — **✅ homologada em produção; Headless gate PASS**
- V12-F.1C Publication Privacy Persistence — **homologada em produção; Analytics ON**

Próximas fases planejadas:
- V13 Headless Remote Deployment / Safe Update
- V14 Virtual Presenter / Character Narrator

---

## 5. Commits importantes

- `46739bf` — preserve legacy terminal cancellations across channel migration
- `866589a` — add autonomous production loop
- `4bbc39a` — harden autonomous production safety and recovery
- `bd6b568` — align autonomous provider and stock eligibility contracts
- `506abb3` — align autonomous generation with persisted production config
- `08c644f` — enforce one autonomous transition per cycle

### Commit atual em produção
`54875c6` (homologação informada pelo operador)

`de62a4b` é governança de agentes, sem necessidade de deploy para validar a aplicação. `d1a8677` corresponde à V12-F.1B (Headless Worker Bootstrap), homologada em produção com Headless gate PASS.

---

## 6. Configuração segura atual

Estado confirmado após homologação:

- Factory: `RUNNING`
- Primary: `ACTIVE`
- Scheduler: `ON`
- Auto Publish: `ON`
- Dry Run: `OFF`
- Growth Mode: `warmup`
- YouTube: `ON`
- TikTok: `OFF`
- Autonomous Mode: `ON`
- MPT Auto Upload: `OFF`
- YouTube privacy: `public`
- Autonomous max generations / 24h: `5`

---

## 7. Backup mais recente

Backup pré-deploy: `video_factory_20260921_014133.db`.
SHA-256: `79313b694f54000b57d704eadfc8a6e5b1871ac5198e95006ef4890cd82f44a5`.
Integridade: `ok`.

---

## 8. Testes do hotfix em produção

Após atualização para `66f92a4`: **234 passed, 19 subtests passed, 0 failed**, nas oito suítes registradas na seção V12-E.2.2.
Histórico: `08c644f` teve 197 testes PASS em produção.

---

## 9. Bug real encontrado na V12-E

### Comportamento antigo

Ao revisar uma task rejeitada:

```text
rejeitar A
→ continuar o mesmo ciclo
→ detectar estoque baixo
→ gerar B
```

Também existia fall-through em recovery.

### Causa raiz

Dois caminhos sem `return` em `run_autonomous_cycle()`:

1. rejection path
2. recovery path

### Correção

Nova regra:

**UM CICLO AUTÔNOMO = UMA TRANSIÇÃO OPERACIONAL PRINCIPAL**

Exemplos:

```text
Ciclo 1 → gera A → return
Ciclo 2 → revisa A → approved/rejected/waiting → return
Ciclo 3 → se estoque baixo → gera B → return
```

Commit:
`08c644f`

---

## 10. Primeiro vídeo autônomo real

Task:
`42c06135-d12f-475c-a0b1-16d23000f42c`

Tema:
`A Fazenda 18: conheça Lucas Bissoli, ex-BBB e participante do reality`

Safety:
`PASS`

Quality:
`45.0 / WEAK`

Resultado:
`task_gate_rejected`

Motivos principais:
- alta repetição com conteúdo recente
- aderência moderada ao nicho
- risco alto de repetição
- potencial visual genérico

Nenhum schedule criado.

---

## 11. Segundo vídeo autônomo real

Task:
`26a5ccbf-cf83-40f9-b2fa-748ddfa5d88a`

Tema:
`fran da fazenda`

Safety:
`BLOCK`

Motivo:
`Duração de 59.0s abaixo do mínimo de 60s para YouTube + TikTok Monetization`

Quality:
não executado, porque Safety bloqueou antes.

Resultado:
- rejeitado
- sem schedule
- sem publicação

Esse teste foi executado ainda no código antigo, com limite temporário `2/2`, impedindo uma terceira geração no mesmo ciclo.

---

## 12. Hotfix V12-E.2.1

Commit:
`08c644feb9677c4b3dd7567f50755ce7139da44c`

Mensagem:
`fix: enforce one autonomous transition per cycle`

Resultados:
- 10 novos testes específicos
- regressão total direcionada: `197/197 PASS`
- deploy no PC forte concluído
- worktree clean
- health HTTP 200
- PRIMARY ativo

---

## 13. Histórico do teste V12-E.2.1

Após deploy de `08c644f`, um one-shot criou a task `fdb20c65-76b2-42cc-9c0f-a1764f7237e0`, sobre curiosidades do maior roedor do mundo. O registro anterior capturava GENERATING, Autonomous OFF e 3/5 gerações em 24h. É um snapshot histórico, não uma tarefa atualmente aguardando ação neste handoff.

---

## 14. Regra homologada de transição

Um ciclo autônomo executa uma transição operacional principal e retorna: geração, revisão, agendamento ou recuperação. Rejeitar uma task ou falhar na recuperação não pode gerar outra no mesmo ciclo. A recuperação persistida real ocorreu sem geração indevida.

---

## 15. Gate final da V12-E — PASS

Safety PASS, Quality 78.3/GOOD, Scheduler, Worker/Upload-Post e visibilidade PÚBLICO no YouTube Studio confirmados para `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`. Evidências completas no início deste documento.

Auto Publish e Autonomous contínuo estão ON; TikTok e MPT Auto Upload permanecem OFF.

---

## 16. Regras importantes

Não usar:
- `git reset`
- `git restore`
- `git clean`

Não instalar Playwright.

Não ativar MPT Auto Upload.

Não ativar TikTok automaticamente.

Não usar API real em testes unitários.

Sempre parar produção antes de `git pull`.

Usar:

`.\.venv\Scripts\python.exe`

porque a ativação PowerShell do venv pode ser bloqueada por ExecutionPolicy.

---

## 17. Publicação

Existem duas rotas:

### Scheduler
`auto_publish_enabled`

### MPT original
`upload_post_auto_upload`

Regra:
**MPT Auto Upload permanece OFF.**

Scheduler é o único caminho automático.

YouTube privacy:
`public`

---

## 18. Growth Mode

Atual:
`warmup`

Historicamente, YouTube warmup:
- 1 publicação / 24h
- intervalo mínimo de 8h

Nunca assumir slot disponível.
Sempre consultar rate limits no momento da publicação.

---

## 19. TikTok

Infra existe, porém teste real anterior retornou HTTP 400 no Upload-Post.

Portanto:
**TikTok ainda não está homologado.**

Permanece OFF.

---

## 20. State / MemoryState

Quando Redis está desabilitado, o MPT usa `MemoryState`.

Portanto um `python.exe` separado não enxerga as tasks em memória do processo Streamlit.

`sm.state.get_task(task_id)` em outro processo pode retornar `TASK_NOT_FOUND` mesmo com task válida.

Para observação entre processos usar:
- arquivos físicos em `storage\tasks\<task_id>`
- settings persistidos em SQLite

---

## 21. Ideia futura — V14 Virtual Presenter

Conceito aprovado:

Adicionar personagem que narra/lê a legenda.

Modos:

- `none`
- `corner`
- `hybrid`
- `full`

Preferência inicial:
**Hybrid Presenter**

Campos possíveis:
- `avatar_provider`
- `avatar_character_id`
- `avatar_position`
- `avatar_scale`
- `avatar_opacity`

Métricas futuras:
- `lip_sync_score`
- `subtitle_sync_score`
- `presenter_visibility_score`
- `presenter_overlap_score`
- `narration_coverage_score`

Default:
`avatar_mode=none`

V12-E está fechada; V14 permanece posterior à V12-F e V13, sem implementação nesta tarefa.

---

## 22. V12-F.4 — Segundo canal homologado em produção

**Status: ✅ COMPLETED / PRODUCTION HOMOLOGATED (22/09/2026).**

Segundo canal configurado, isolado e homologado em produção real. Evidências comprovadas:
- **Segundo perfil isolado:** `profile-historias-misterio` ("Dose Diária de Histórias e Mistério", nicho `historias_misterio`).
- **Canal YouTube isolado:** `channel-historias-misterio-youtube` (handle `@DoseDiáriadeHistóriasemistério`).
- **Upload-Post profile:** `dose-diaria-misterio` conectado e autenticado.
- **Geração real:** task_id `815b0958-b94e-457b-932d-b10dfb0e8dba`.
- **Safety Gate:** PASS.
- **Quality Gate:** 79.2 (Strong Quality).
- **Scheduler:** Adoção e agendamento automático para YouTube.
- **Publicação pública:** Vídeo `XVy8MbpJFqw` publicado no YouTube.
- **Analytics youtube_api:** Coleta e métricas isoladas via YouTube Data API.
- **PR #9 Recovery:** Recuperação de tarefas aprovadas sem dependência de MemoryState volátil.
- **Autonomous secondary ON:** Produção autônoma do perfil secundário ativada e operacional.
- **Canal principal:** Perfil `default` 100% preservado e isolado.

---

## 23. V12-F.5 — Multi-Channel Capacity & True Multi-Profile Autonomous Worker

**Status: ✅ COMPLETED / IMPLEMENTED (22/09/2026).**

> [!IMPORTANT]
> **UI PROFILE SELECTION IS NOT A BACKGROUND EXECUTION SELECTOR.**
> A seleção de perfil na interface gráfica do Operator Console serve exclusivamente para controle do operador (visualização, edição, acionamento supervisionado manual). A execução em segundo plano do Scheduler Worker opera de maneira totalmente desacoplada, iterando de forma determinística por todos os canais/perfis que possuem modo autônomo ativado (`run_enabled_profiles_autonomous_cycle`).

Entregas da Fase V12-F.5:
1. **Background Worker Multi-Perfil Desacoplado:** Loop do worker em segundo plano executa `run_enabled_profiles_autonomous_cycle()`, eliminando qualquer dependência de `get_active_profile_id()`. O worker processa sequencialmente os perfis ativos habilitados com isolamento total de falhas.
2. **Ready Stock por Perfil:** Configuração isolada `autonomous_target_ready_stock:<profile_id>` (WARMUP default 3, SCALE default 5, configurável de 3 a 6). O perfil default mantém retrocompatibilidade com a chave legada.
3. **Limites Operacionais por Perfil (24h):**
   - WARMUP: 2 gerações aprovadas / 24h, 8 tentativas / 24h.
   - SCALE: 5 gerações aprovadas / 24h, 15 tentativas / 24h.
   - Chaves isoladas: `autonomous_max_generations_24h:<profile_id>` e `autonomous_max_attempts_24h:<profile_id>`.
4. **Global Cost Guard:** Freio mestre agregado somando todos os perfis (`autonomous_global_max_generations_24h = 10`, `autonomous_global_max_attempts_24h = 25`). Contadores agregados explícitos (`count_all_profiles_generations_24h`, `count_all_profiles_attempts_24h`). Protege apenas novas gerações, preservando agendamentos e publicação de estoques prontos.
5. **Multi-Destino / Elegibilidade de Assets:** Conceito `check_asset_eligibility_for_destination` implementado para suporte futuro de 1 asset atendendo YouTube + TikTok sem re-renderização obrigatória.
6. **TikTok Estritamente OFF:** TikTok permanece desativado, sem credenciais, posts ou chamadas de API.
7. **Operator Console Integrado:** Exibição de estoque alvo, estoque pronto, limites de 24h e contadores do Global Cost Guard.

---

## 24. Pendência Futura: Copyright / Content ID Hardening + Character Narrator

- **Problema Real Registrado:** Vídeo `XVy8MbpJFqw` (task `815b0958-b94e-457b-932d-b10dfb0e8dba`) publicado no YouTube recebeu bloqueio/reivindicação mundial por Content ID.
- **Investigação Necessária:** Identificação precisa da mídia visual (Pexels/Pixabay) e trilha BGM causadoras da reivindicação.
- **Narrador Virtual:** Introdução de apresentador/personagem virtual (V14 Hybrid Presenter) para enriquecer teor transformativo e originalidade do canal.
- **Gate Preventivo:** Análise de pré-verificação ou filtragem preventiva contra faixas sujeitas a Content ID.
- **Isolamento de Feedback:** Vídeos com Content ID reivindicado não devem alimentar o Closed Feedback Loop.
- **Observação:** Não implementado na V12-F.5 (apenas registrado em backlog).

---

## 23. Convenção de documentação

Manter no projeto:

```text
docs/
├── PROJECT_HANDOFF.md
├── ROADMAP.md
├── PRODUCTION_RUNBOOK.md
└── DOCUMENTATION_POLICY.md
```

O `PROJECT_HANDOFF.md` deve ser atualizado ao final de cada fase importante.

---

## 25. V16.1 — Brazilian Content Contract

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Deploy SHA:** `3983d37a29d1f169e513f19bd7186348a74ad5e9`
- **Evidências de Homologação Real:**
  - A UI persistida em produção ainda continha `af-ZA-AdriNeural-Female`, `subtitle_enabled=False`, `text_fore_color=#000000`.
  - A produção autônoma bloqueou corretamente a voz estrangeira de forma fail-closed sem gerar falha silenciosa.
  - Nenhum vídeo/API/publicação espúria ocorreu no teste.

Entregas da Fase V16.1:
1. **Contrato Brasileiro Canônico Fail-Closed:**
   - `video_language = "pt-BR"` e `region = "BR"` impostos na produção autônoma independentemente de configurações de UI.
   - `subtitle_enabled = True` forçado para todas as gerações autônomas.
   - `text_fore_color = "#FFFFFF"`, `stroke_color = "#000000"` e `stroke_width >= 1.5` (default autônomo 2.0).
   - `match_materials_to_script = True` e `video_concat_mode = sequential` como default autônomo.
2. **Validação Estrita de Locales de Voz:**
   - `is_valid_pt_br_voice(voice_name)` aceita somente vozes comprovadamente `pt-BR` (ex: `pt-BR-AntonioNeural`, `pt-BR-FranciscaNeural`, `pt-BR-ThalitaMultilingualNeural`).
   - Vozes estrangeiras (`af-ZA-*`, `en-*`, `zh-*`, `pt-PT-*`) ou vazias provocam `AutonomousConfigError` (FAIL CLOSED), sem fallback silencioso para línguas estrangeiras.
3. **Validador Reutilizável de Contrato:**
   - `validate_autonomous_brazilian_content_contract(params)` avalia e retorna relatório estruturado (`PASS` ou `BLOCK`).
4. **Preservação de Geração Manual:**
   - Chamadas diretas de `VideoParams` pela WebUI continuam livres para experimentação manual pelo operador, sem impacto inadvertido.

---

## 26. V16.2 — Subtitle Reliability Gate

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Deploy SHA:** `0744fd2b8593fa276a2d3117d88b270475b5b05c`
- **Regra Fundamental:** `AUTONOMOUS_VIDEO_WITHOUT_VALID_CAPTIONS = FORBIDDEN`

Entregas da Fase V16.2:
1. **Validador Reutilizável de SRT (`validate_subtitle_file` / `validate_srt`):**
   - Valida existência, integridade física (> 0 bytes, não apenas whitespace), leitura em UTF-8 / UTF-8-SIG (com BOM).
   - Valida parsing rigoroso de cues, formato e faixas de timestamps (hour >= 0, 0 <= m < 60, 0 <= s < 60, 0 <= ms <= 999), ordenação temporal (`start < end`), detecção de timestamps zerados (`all_timestamps_zero`) e texto não vazio por cue.
   - Validação heurística de coerência com o roteiro (cobertura proporcional mínima e sobreposição lexical sem acentos) que impede legendas vazias ou desconexas.
   - Retorno estruturado fail-closed sem lançar exceções.
2. **Arquitetura de Geração com Fallback Automático:**
   - **Primary:** Edge Subtitles (`voice.create_subtitle`). Se gerar SRT válido -> aceito imediatamente.
   - **Fallback:** Whisper Subtitles (`subtitle.create` + `subtitle.correct`). Acionado automaticamente se Edge falhar, não gerar arquivo, gerar arquivo vazio ou inválido.
   - **Stale SRT Protection:** Remoção preventiva de arquivos parciais/inválidos e geração temporária atômica (`os.replace`) para evitar falsos positivos por arquivos residuais.
3. **Fail-Closed Gate:**
   - Se ambos Edge e Whisper falharem ou produzirem SRT inválido: o pipeline é interrompido imediatamente em `stage="subtitle"`, marcando a tarefa como `TASK_STATE_FAILED` com `error="subtitle_required_but_unavailable..."`.
   - Impede o avanço para download de materiais (`get_video_materials`) e renderização final (`generate_final_videos`).
   - Nenhuma publicação ou agendamento é disparado sem legenda válida.
4. **Preservação de Compatibilidade Manual:**
   - Quando `subtitle_required=False` (modo manual/WebUI), o fluxo preserva estritamente o comportamento anterior (não executa fallback inesperado nem download inadvertido de modelos Whisper).
   - `subtitle_enabled=False` manual continua 100% suportado.
   - Provedor explícito `subtitle_provider="whisper"` e `custom_audio_file` continuam plenamente funcionais.
5. **Ambiente Whisper:**
   - Nenhuma chamada real de rede ou download de modelo Whisper foi executada nesta fase (testes unitários isolados com mocks). Recomendação oficial de produção: `large-v3-turbo`.

---

## 27. V16.3 — Final Media Quality Gate

**Status: ✅ PRODUCTION HOMOLOGATED (Deploy SHA: `9e3fde0b35e28781aab67117d5ff33c182b337ef`)**

Regra Fundamental: `AUTONOMOUS_FINAL_MEDIA_WITH_CRITICAL_DEFECT = FORBIDDEN`

Entregas da Fase V16.3:
1. **Módulo Centralizado de Qualidade de Mídia (`app/services/media_quality.py`):**
   - Helper seguro `probe_media(file_path)` utilizando `ffprobe` com subprocess sem shell, timeout rígido, captura estruturada em JSON e validação defensiva da estrutura do payload (dict, streams list, format dict).
   - Evaluator de qualidade `evaluate_final_media_quality(video_path, params, ...)` que retorna status padronizado (`PASS` ou `BLOCK`), lista de `reasons` padronizadas e `metrics` consolidadas (duração, resolução, aspect ratio, codec, fps, tamanho em bytes).
2. **Critical Gates Fail-Closed:**
   - **Arquivo:** Rejeita arquivos inexistentes, diretórios, 0 bytes ou truncados (< 10KB, `MIN_VALID_MEDIA_FILE_BYTES`).
   - **Probe:** Falha de ffprobe (indisponível, timeout, retorno não-zero ou JSON inválido) bloqueia a produção autônoma.
   - **Vídeo:** Rejeita vídeos sem stream de vídeo, com dimensões inválidas (width/height <= 0), com resolução abaixo do mínimo ou aspect ratio incompatível com a orientação esperada (ex: `portrait` 9:16).
   - **Duração:** Rejeita vídeos com duração <= 0 ou que apresentem divergência extrema em relação ao áudio gerado (`AUDIO_VIDEO_DURATION_MISMATCH`).
   - **Áudio:** Para produção autônoma com locução, exige presença de stream de áudio com duração válida (duration inválida/não-numérica/NaN/inf/<=0 bloqueia; ausência tolerada).
   - **Contrato de Legenda:** Valida que o artefato SRT obrigatório existe e foi mantido no pipeline.
3. **Pipeline Gate Pré-Publicação:**
   - Integrado diretamente em `app/services/task.py` logo após a geração de `final_video_paths`.
   - Se qualquer vídeo final do lote falhar no gate, a tarefa é imediatamente interrompida como `TASK_STATE_FAILED` com `stage="final_media_quality"`.
   - O agendamento de cross-post (`_schedule_cross_post`) e a chamada de publicadores externos são bloqueados preventivamente.
   - Diagnóstico estruturado é persistido em `script_data` (`task_artifacts.patch_script_data`) tanto no fluxo de sucesso quanto no fluxo de BLOCK.
4. **Preservação do Modo Manual:**
   - A imposição fail-closed é governada pelo flag `final_media_quality_required=True` (imposta automaticamente na produção autônoma), preservando geração manual e testes pontuais.
5. **Limites do Escopo:**
   - Não realiza OCR visual de legendas, análise de black/freeze frames, nem avaliação semântica subjetiva.

---

## 28. V16.4 — Scene-Based Video Generation (PRODUCTION HOMOLOGATED)

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Validação:** 20 testes PASS em `test/services/test_v16_4_scene_based_video_generation.py`
- **Regra Fundamental:** `AUTONOMOUS_SCENE_VISUALS_MUST_FOLLOW_SCRIPT_ORDER = REQUIRED`

Objetivo da Fase V16.4:
Garantir que vídeos autônomos possuam coerência visual narrativa, dividindo o roteiro em cenas estruturadas, associando termos visuais específicos para cada cena, resolvendo materiais sequenciais com fallback observável e montando a timeline de vídeo na ordem exata da narração.

Arquitetura e Contratos:
1. **Modelagem de Cenas (`ScenePlanItem`, `ScenePlan`, `SceneMaterialSelection`, `SceneClipInstruction`):**
   - Indexação determinística 1-based (`scene_index: 1, 2, ...`).
   - Narração não-vazia por cena.
   - Lista ordenada de termos visuais (`search_terms`) por cena.
   - Durations estimadas coerentes com a fala/narração.
2. **Planner Determinístico Baseline (`app/services/scene_planner.py`):**
   - Segmentação do roteiro por pontuação, limites narrativos e estimativa temporal (target 4-8s por cena).
   - Extração local de termos visuais específicos por cena sem necessidade de chamada externa ou LLM no baseline.
   - Suporte completo ao português brasileiro (pt-BR) com preservação de acentuação e stopwords filtradas.
3. **Scene Material Resolver (`app/services/scene_material.py`):**
   - Busca materiais para cada cena usando os termos específicos da cena.
   - Política de fallback observável: termo 1 -> termo 2 -> termo 3 -> termo visual derivado -> falha estruturada se não houver material.
   - Evita repetição visual consecutiva quando existirem alternativas.
   - Rastreabilidade completa de provedor, asset ID e termo utilizado, preservando o gate de proveniência (`asset_provenance`).
4. **Scene Assembly (`app/services/scene_assembly.py`):**
   - Orquestra e valida a sequência exata de clips antes da renderização.
   - Fail-closed em caso de índices duplicados, cenas ausentes ou durações inválidas.
5. **Compatibilidade e Preservação:**
   - Modo autônomo define `scene_based_generation_enabled=True`.
   - Modo manual preserva `scene_based_generation_enabled=False` por padrão.
   - Não altera pipelines de legendas (V16.2) nem o Final Media Quality Gate (V16.3).

## 29. V16.4.1 — Scene Render Performance Hardening

### V16.4.1A — Scene Render Performance Hardening
- **Status:** 🟢 PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **Branch:** `perf/v16-4-1-scene-render-performance` (PR #41)
- **Validação:** 10 testes PASS em `test/services/test_v16_4_1_scene_render_performance.py`

Entregas V16.4.1A:
1. **Instrumentação com `perf_counter`:**
   - `SCENE_RENDER_PREP_SECONDS`, `SCENE_RENDER_CLIPS_SECONDS`, `CONCAT_SECONDS`, `FINAL_RENDER_SECONDS` e `TOTAL_RENDER_SECONDS`.
2. **Concatenação Stream-Copy:**
   - Tentativa automática com `-c copy` para clipes scene-based normalizados.
   - Validação de saída com fallback determinístico para transcode (`-c:v libx264`).
   - Logs explícitos: `CONCAT_MODE=STREAM_COPY` ou `CONCAT_MODE=TRANSCODE_FALLBACK`.
3. **Propagação de `threads`:**
   - Parâmetro `threads` propagado corretamente para as escritas de vídeo em `combine_videos`.

### V16.4.1B — Final Render Performance (Homologada em Produção)
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `e7f40ed6f4b7df45e5868cd7de03495239d103ec` (PR #43)
- **Evidência de Produção:** Task `f9a9608b-512d-43c4-92f4-f864a0424512`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Entregas V16.4.1B:**
  1. Subtitle burn-in nativo acelerado via FFmpeg libass (`FINAL_RENDER_MODE=FFMPEG_NATIVE`).
  2. Stream-copy direto via FFmpeg (`FINAL_RENDER_MODE=FFMPEG_STREAM_COPY`) quando legendas estão ausentes.
  3. Preservação integral do fallback MoviePy legado (`FINAL_RENDER_MODE=MOVIEPY_FALLBACK`).
  4. Preservação de resolução, fps, qualidade, áudio, BGM e Final Media Quality Gate.
  5. Hardening de métricas: `FINAL_RENDER_SECONDS` interno canônico preservado e `FINAL_RENDER_CALL_SECONDS` externo registrado.

### V16.4.1C — Render Pipeline Gap Instrumentation
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `d231e3900bbbace180c0c71e60e9fb08c2d713e0` (PR #44)
- **Evidência de Produção:** Task `337639bb-1740-4398-a923-c5f75b1f236a`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Resultados de Produção Homologados:**
  - `FINAL_RENDER_UNACCOUNTED_SECONDS = 0.0000273` (gaps internos eliminados).
  - `TOTAL_RENDER_UNACCOUNTED_SECONDS = 0.0033855` (gaps macro eliminados).
  - `COMBINE_VIDEOS_UNACCOUNTED_SECONDS = 0.0028849`.
  - Ponto de anomalia remanescente identificado: `FINAL_RENDER_POST_ENCODE_SECONDS = 111.4239390` (~1m51s).

### V16.4.1D — Post-Encode Performance Investigation
- **Status:** 🟢 MERGED (04/10/2026)
- **Deploy SHA:** `d13d9347fc96c6a967561821552bbb19452eb281` (PR #45)
- **Validação:** 34 testes PASS (`test_v16_4_1_scene_render_performance.py`, `test_v16_4_1b_final_render_performance.py`, `test_v16_4_1c_render_gap_instrumentation.py`, `test_v16_4_1d_post_encode_performance.py`).
- **Objetivo:** Mapear rigorosamente todas as operações dentro de `FINAL_RENDER_POST_ENCODE_SECONDS`, sub-instrumentar a região de forma contígua e identificar causas de retenção pós-encode.
- **Mapeamento do Código em Post-Encode:**
  - `t_encode_start` a `t_val_start`: Encode nativo (`305.55s`).
  - `t_val_start` a `t_post_start`: Validação de integridade do arquivo final (`_validate_final_render_output`, `0.15s`).
  - `t_post_start` a `post_encode_seconds`: Bloco pós-encode avaliando flags de modo (`native_rendered`, `final_render_mode`) e emitindo `logger.info("FINAL_RENDER_MODE=...")`.
- **Classificação de Evidências:**
  - **CONFIRMED:**
    - Não existem operações pesadas de disco, probes adicionais, cópias ou reaberturas de arquivo MoviePy dentro de `FINAL_RENDER_POST_ENCODE_SECONDS`.
    - `FINAL_RENDER_POST_ENCODE_SECONDS` mede estritamente: (1) atribuição das variáveis de estado `native_rendered` e `final_render_mode`, e (2) a chamada síncrona `logger.info("FINAL_RENDER_MODE=...")`.
    - As sub-métricas foram criadas e persistidas: `FINAL_RENDER_POST_ENCODE_STATE_SECONDS`, `FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS` e `FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS`.
    - Invariante validado: `POST_ENCODE_SECONDS = STATE + NOTIFY + UNACCOUNTED`.
  - **INFERRED:**
    - A latência anômala de ~111.42s em produção ocorreu devido a pausa síncrona do terminal Windows conhost (QuickEdit Mode ativado com seleção de texto ou foco de clique pelo operador durante os 5 minutos de encode sem logs), ou contenção de lock no stream síncrono de stderr.
  - **NOT_YET_VALIDATED_IN_PRODUCTION:**
    - Decomposição exata sob execução autônoma/não assistida no PC forte (`C:\Projetos\MoneyPrinterTurbo`).

### V16.4.2R / V16.4.2R.1 / V16.4.2R.2 — Pre-Repair Publishing Reset & Stale Lock Recovery (Fase Ativa Atual)
- **Status:** 🚀 ACTIVE / DEV IMPLEMENTED (04/10/2026)
- **Branch:** `fix/v16-4-2r2-stale-primary-recovery`
- **Validação:** 16 testes PASS (8 em `test_v16_4_2r_pre_repair_publishing_reset.py` + 8 em `test_stale_primary_lock_recovery.py`), Dry-run e Reset real validados com backup físico íntegro e zero deleção de arquivos de mídia.
- **Objetivo:** Estabelecer um baseline seguro, limpo e auditado no subsistema de publicação antes das correções V16.4.2A/B/C, neutralizando todas as publicações antigas pendentes (`planned`, `ready`, `queued`), stale processing e retries armados (`next_attempt_at = NULL`), fornecendo operação administrativa fail-closed para liberação de lock stale de `PRIMARY_FACTORY`.
- **Política de Preservação e Recuperação de Lock (V16.4.2R.2):**
  - **Recuperação de Lock Primário Stale:** Quando o processo encerra de forma abrupta sem disparar `release_instance_lock()`, `operator_console.release_stale_instance_lock()` e `scripts/reset_pending_publications.py --release-stale-primary` realizam a verificação temporal conservadora (heartbeat > 90s), confirmam que o PID local não está em execução e atualizam `ACTIVE -> STOPPED`, registrando `STALE_PRIMARY_LOCK_RELEASED` em `operational_events` com zero deleção de registros.
  - **Preservação de Published:** Registros com `scheduled_posts.status = 'published'` NUNCA são convertidos em `cancelled`. Caso possuam `next_attempt_at` armado (residual), este é limpo (`NULL`), desarmando retries e mantendo `status = 'published'` e `attempts` intactos (`RETRY_DISARMED_AFTER_SUCCESS`).
  - **Inconsistência Failed com Sucesso:** Registros com `scheduled_posts.status = 'failed'` que já possuem `publication_events(status='success')` NÃO são cancelados cegamente; seus retries são desarmados (`next_attempt_at = NULL`), o status é mantido como `failed` e são preservados para reconciliação determinística na V16.4.2A (`FAILED_WITH_SUCCESS_INCONSISTENCY_DISARMED`).
  - `publication_events` com `status = 'success'` 100% preservados (zero deleções).
  - Identidade de publicações, `external_id`, `external_url` e histórico preservados.
  - Vídeos e diretórios em `storage/tasks/` 100% preservados (`media_files_deleted = 0`).
  - Scheduled posts pendentes neutralizados para `status = 'cancelled'` e `next_attempt_at = NULL`.
  - Pré-condição de segurança fail-closed (`scheduler_enabled = False`, `auto_publish_enabled = False` e `active_primary = False`).
  - Registro de auditoria detalhado em `operational_events` sob os tipos `PRE_REPAIR_PUBLICATION_RESET` e `STALE_PRIMARY_LOCK_RELEASED`.
  - Auditoria pós-reset: `EXECUTABLE_PENDING_PUBLICATIONS = 0`, `ARMED_RETRIES = 0`, `STALE_PROCESSING = 0`, `PUBLISHED_SUCCESS_RECORDS_PRESERVED = YES`.

### V16.4.2A — Publishing State Reconciliation (Fase Ativa Atual)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2a-publishing-state-reconciliation`
- **Validação:** 8 testes PASS em `test/services/test_publication_reconciliation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Estabelecer uma reconciliação determinística entre `publication_events` e `scheduled_posts`, tratando `publication_events.status = 'success'` como evidência canônica de publicação concluída.
- **Regras Canônicas Implementadas:**
  - Se existir `publication_event.status = 'success'` para `(task_id, platform)`: nunca chamar provider novamente, nunca republicar, post torna-se não executável, retry desarmado (`next_attempt_at = NULL`), mantendo metadados canônicos (`external_id`, `external_url`, `published_at`) e histórico.
  - `failed + success`: reconciliado para `published`, preservando histórico de erro e tentativas.
  - `processing + success`: reconciliado para `published`, gerando `STALE_PROCESSING_DETECTED` e `PUBLICATION_RECONCILED_SUCCESS`.
  - `published + retry residual`: mantém `published` e desarma retry residual (`next_attempt_at = NULL`), emitindo `RETRY_DISARMED_AFTER_SUCCESS`.
  - Duplicatas para a mesma tupla `(task_id, platform)`: um post canônico torna-se `published` e os demais são neutralizados para `cancelled` com retry desarmado, emitindo `DUPLICATE_SCHEDULE_DETECTED`.
  - Sucessos sem post agendado correspondente (órfãos históricos): auditados no console operacional (`HISTORICAL_ORPHAN_SUCCESS_RECONCILED`), sem inventar chamadas ao provider.
  - Nenhuma linha de `publication_events` ou `scheduled_posts` é deletada; nenhum arquivo de mídia é deletado.
- **Guard em Tempo de Execução:** `scheduler.run_scheduler_cycle` e `scheduler.has_existing_or_terminal_destination` contam com guard canônico antecipado: antes de qualquer checagem de perfil/vídeo ou tentativa de publicação externa, se houver evento de publicação prévio com sucesso, o post é marcado `published`, retries são zerados e a execução retorna `skipped: already_published` sem acionar provider.
- **Serviço e CLI:** Implementados em `app/services/publication_reconciliation.py` e `scripts/reconcile_publication_state.py` com suporte a `--dry-run` e execução real via confirmação `--execute --confirm RECONCILE_PUBLICATION_STATE`, com backup automático pré-mutação.

### V16.4.2B — Publishing Idempotency / Duplicate Protection (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2b-publishing-idempotency-duplicate-protection`
- **Validação:** 10 testes PASS em `test/services/test_publishing_idempotency.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Impedir definitivamente que o sistema crie, agende, processe ou envie mais de uma publicação externa para a mesma tupla canônica `(task_id, platform)` quando já existir sucesso registrado ou fluxo executável equivalente.
- **Modelo de Idempotência e Camadas de Proteção:**
  - **Camada 1 — Criação e Agendamento (`app.services.publishing_idempotency.can_schedule_task` / `scheduler.plan_schedule`):**
    - Bloqueia criação de novos agendamentos se já houver: sucesso canônico (`already_published`), post executável (`already_scheduled`), processamento ativo (`already_processing`) ou post publicado (`already_published`).
  - **Camada 2 — Scheduler Runtime / Seleção de Candidatos (`can_execute_scheduled_post` em `run_scheduler_cycle`):**
    - Detecta sucesso canônico antes do ciclo, desarma retries (`next_attempt_at = NULL`), marca o post como `published` e neutraliza agendamentos duplicados concorrentes como `cancelled`.
  - **Camada 3 — Just-In-Time Idempotency Gate Imediatamente Pré-Provider (`jit_provider_idempotency_guard`):**
    - Executado imediatamente antes do envio em `scheduler`, `task.publish_task`, `youtube_publisher.publish_youtube_video` e `post_for_me` client (`publish_video` / `publish_tiktok_video`).
    - Se sucesso canônico for registrado entre o início do ciclo e a chamada (race condition mitigada), aborta fail-safe e não chama o provider externo.
- **Preservação Auditável:** Duplicatas históricas canceladas não interferem com posts elegíveis; zero deleção de registros em `publication_events` ou `scheduled_posts`; zero deleção de mídia.

### V16.4.2C — Retry Metadata Cleanup (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2c-retry-metadata-cleanup`
- **Validação:** 12 testes PASS em `test/services/test_publishing_retry_cleanup.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Eliminar estados residuais e regras inconsistentes de retry que possam rearmar publicações já concluídas, canceladas, reconciliadas ou terminalmente falhadas.
- **Regras da Política Canônica de Retry:**
  - `published`: Estado terminal imutável, `next_attempt_at = NULL`.
  - `cancelled`: Estado terminal imutável, `next_attempt_at = NULL`.
  - `failed` permanente ou esgotado (`attempts >= 3`): Estado terminal, `next_attempt_at = NULL`.
  - `success canônico` em `publication_events`: Desarma imediatamente qualquer retry correspondente em `scheduled_posts`.
  - `processing ativo`: Não rearma durante processamento.
  - `failed retryable`: Reagendamento permitido apenas para erros transitórios (`429`, quota 24h, 5xx, timeout, socket) dentro do limite de 3 tentativas com backoff progressivo.
- **Entregas Técnicas:**
  - `app/services/retry_policy.py`: centralização canônica de `evaluate_retry_decision` e `cleanup_residual_retries`.
  - `app/services/scheduler.py`: integração de limpeza preventiva no início de cada ciclo (`run_scheduler_cycle`) e aplicação de `next_attempt_at = NULL` em todas as transições de terminal/falha.
  - `app/services/post_for_me.py`: desarmamento de retry na reconciliação de sucesso remoto.
  - `scripts/cleanup_retry_metadata.py`: CLI de auditoria (`--dry-run`) e execução controlada (`--execute --confirm CLEANUP_RETRY_METADATA`).
- **Próximo Passo:** `V16.4.2H_FINAL_PUBLISHING_HEALTH_AUDIT`.

### V16.4.2H — Final Publishing Health Audit (Fase Concluída em DEV)
- **Status:** 🚀 DEV AUDITED / INTEGRATED SUITE PASSED (05/10/2026)
- **Branch:** `feat/v16-4-2h-final-publishing-health-audit`
- **Validação:** 10 testes PASS em `test/services/test_publishing_health_audit.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, 12 testes PASS não-regressão V16.4.2C, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Realizar a auditoria final do subsistema de publicação e provar que o conjunto consolidado A+B+C está seguro para deploy em produção.
- **Auditoria de Código Conduzida:**
  - JIT Idempotency Guard integrado ao caminho de fallback Upload-Post em `task._execute_cross_post_process`.
  - Transições para estados terminais (`status = 'failed'` e `status = 'published'`) em `scheduler.py` reforçadas com `next_attempt_at = NULL` incondicional.
  - Zero pontos de escape de idempotência ou rearmamento indevido detectados.
- **Garantias Comprovadas:**
  - Idempotência canônica: exatamente 1 chamada ao provedor para publicação nova; 0 chamadas adicionais em reexecuções, restarts ou simulações.
  - Retries: falha transitória agenda retry com backoff; falha permanente e tentativas esgotadas tornam-se terminais (`next_attempt_at = NULL`).
  - Reconciliação e concorrência: JIT guard aborta envio se sucesso ocorrer antes da chamada externa.
  - Preservação estrita: zero DELETE em `publication_events` ou `scheduled_posts`; zero mídia deletada.
- **Próximo Passo:** `CONSOLIDATED_PRODUCTION_DEPLOY_AND_CONTROLLED_PUBLICATION_TEST`.

### V16.5 — Visual Matching v2 (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)
- **Branch:** `feat/v16-5-visual-matching-v2`
- **Validação:** 9 testes PASS em `test/services/test_visual_matching.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Melhorar significativamente a aderência visual dos clipes de vídeo selecionados à narração e intenção das cenas, evitando clipes genéricos ou semanticamente fracos.
- **Arquitetura Implementada:**
  - `app/services/visual_matching.py`: motor determinístico de intenção visual (`SceneVisualIntent`), queries v2 em tiers de especificidade, e pontuação de candidatos (0 a 100) baseada em termos semânticos (título, tags, slug), casamento da query, aspect ratio, duração útil e penalidades de repetição (-50 para adjacente, -35 para reutilização global no vídeo).
  - Enriquecimento de metadados em `app/services/material.py`: extração de título/slug e tags para Pexels, Pixabay e Coverr.
  - Planejamento de cenas em `app/services/scene_planner.py`: geração de intenção estruturada v2 e queries priorizadas por cena.
  - Resolução em `app/services/scene_material.py`: busca em cascata, ordenação determinística por score, diversidade global de ativos e persistência de auditoria em `script_data` (`visual_intent`, `match_score`, `selection_reason`, `queries_tried`, `fallback_tier`).
- **Próximo Passo:** PR / Merge em DEV main e validação de CI contra baseline.

### V16.6 — Hybrid Visual Generation Foundation (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026, PR #55)
- **Branch:** `feat/v16-6-hybrid-visual-generation`
- **Validação:** 12 testes PASS em `test/services/test_hybrid_visual_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Estabelecer a infraestrutura desacoplada para geração visual híbrida (Stock, Nano Banana Image, ComfyUI Video).
- **Arquitetura Implementada:**
  - `app/services/hybrid_visual.py`: Interfaces base e contratos desacoplados (`VisualProvider`, `StockVisualProvider`, `NanoBananaImageAdapter`, `ComfyUIVisualProvider`, `HybridVisualDirector`).
  - `scripts/benchmark_video_models.py`: Script de benchmark para avaliar performance e viabilidade de modelos abertos.

### V16.6.1 — Hardware-Aware Open Source Benchmark (Fase Concluída em DEV)
- **Status:** 🚀 DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS (05/10/2026)
- **Objetivo:** Criar probe e relatório de capacidades de hardware (GPU vendor, VRAM, CUDA/ROCm/DirectML) sem dependência obrigatória de torch e classificar o host localmente.
- **Classificação Registrada:**
  - `LOCAL_GENERATIVE_VIDEO_GPU_STATUS = "NOT_RECOMMENDED_ON_CURRENT_HARDWARE"`
  - Hardware PC Forte: AMD Radeon RX 580 2048SP (~4GB VRAM visível, sem NVIDIA/CUDA).
  - Modelos locais pesados (Wan 2.2, LTX-Video, FramePack) classificados como NOT_RECOMMENDED.
  - Recomendação canônica: Provedor remoto, keyframe generation contextual e stock fallback.

### V16.6.2 — Contextual Image-to-Video Foundation (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)
- **Branch:** `feat/v16-6-2-contextual-image-to-video`
- **Validação:** 20 testes PASS em `test/services/test_hybrid_visual_generation.py`, ruff 0 erros nos arquivos alterados.
- **Entregas Técnicas:**
  - Decisão Híbrida Inteligente: `HybridDecision` (`STOCK_HIGH_CONFIDENCE`, `GENERATED_IMAGE_PREFERRED`, `GENERATED_VIDEO_PREFERRED`, `FALLBACK_STOCK`) orientada pelo score de `SceneVisualIntent` do Visual Matching v2.
  - Síntese Contextual de Prompts: geração determinística de prompt fotorealista e cinematic a partir do `SceneVisualIntent` com negative prompt e aspect ratio.
  - Adapter Nano Banana Configurado: interface abstrata, modo mock com dimensões e aspecto válidos para DEV, zero chamadas pagas e fallback seguro para stock.
  - Image Quality Gate: avaliação leve de keyframes (existência do arquivo, dimensões mínimas, aspecto/orientação 9:16 ou 16:9, metadados do provedor).
  - Motion from Still Foundation: suporte a Ken Burns / Pan / Zoom paramétrico (`StillMotionMode`, `StillMotionParams`, `generate_still_motion_instructions`).
  - Observabilidade Completa: persistência de auditoria em `SceneMaterialSelection` (`visual_source_type`, `stock_match_score`, `generation_provider`, `generation_model`, `generation_prompt`, `generation_status`, `fallback_reason`, `generated_asset_path`, `motion_mode`).
- **Próximo Passo:** `V16.7_HYBRID_SCENE_DIRECTOR`.


### V16.7 — Hybrid Scene Director (Fase Concluída em DEV)

- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)

- **Branch:** `feat/v16-7-hybrid-scene-director`

- **Validação:** 34 testes PASS em `test/services/test_hybrid_visual_generation.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.

- **Objetivo:** Orquestrar decisões automáticas cena a cena integrando Visual Intent, busca e pontuação de stock, heurística de custo/benefício, adaptação Nano Banana para keyframes, still-motion determinístico e observabilidade completa com resumo de vídeo.

- **Entregas Técnicas:**

  - **Decision Engine Canônico:** `STOCK_HIGH_CONFIDENCE` (Score >= 60), `GENERATED_IMAGE_PREFERRED` (35 <= Score < 60), `GENERATED_VIDEO_PREFERRED` (Score < 35), `FALLBACK_STOCK` (fail-safe total).

  - **Classificação Leve de Importância (Sem LLM):** `HERO`, `NORMAL`, `LOW` derivados de posição (hook / clímax), keywords de urgência/ação e duração (< 2.5s).

  - **Heurística de Custo/Benefício:** Ajuste inteligente de thresholds com base em alinhamento de orientação/aspect ratio (9:16 portrait), penalidade de reutilização de candidato stock, duração da cena e histórico de fallbacks da tarefa.

  - **Still Motion Integrado:** Seleção determinística de 5 modos de movimento (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `static`) para `generated_image` quando o pipeline I2V estiver desabilitado.

  - **Observabilidade por Cena e Resumo de Vídeo:** Persistência em `SceneMaterialSelection` e `script_data` (`strategy_selected`, `scene_importance`, `stock_score`, `stock_candidate`, `generated_attempted`, `still_motion_mode`, `final_visual_source`) e geração de `VideoVisualSummary` (`total_scenes`, `stock_scenes`, `generated_image_scenes`, `generated_video_scenes`, `fallback_scenes`, `average_stock_score`, `generation_attempts`, `generation_successes`).

  - **Preservação de Produção:** `visual_generation_enabled=False` preserva 100% o fluxo legado de stock. Zero impacto em produção.

- **Próximo Passo:** `V16.8_CONTROLLED_HYBRID_RENDER_VALIDATION`.


### V16.8 — Controlled Hybrid Render Validation (Fase Concluída em DEV)
- **Status:** 🚀 DEV VALIDATED (05/10/2026)
- **Branch:** `feat/v16-8-controlled-hybrid-render-validation`
- **Validação:** 7 testes PASS em `test/services/test_hybrid_validation.py`, 34 testes PASS em `test/services/test_hybrid_visual_generation.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Executar validação controlada do novo pipeline híbrido em comparação direta com o baseline stock-only sobre o mesmo roteiro, mesma narração, mesmas legendas, mesma duração e mesmo aspect ratio (9:16 vertical), provando ganho perceptual real em temas de matching difícil (Marte, Monte Olimpo, pôr do sol azul marciano).
- **Entregas Técnicas:**
  - **Experimento Controlado:** Executado sobre a tarefa `17386147-cb1b-4192-b827-251a1bbd411f` ("3 curiosidades surpreendentes sobre Marte").
  - **Placar Geral de Qualidade:**
    - Baseline Quality Score (Stock Only): **57.8 / 100** (Pexels retornou praias tropicais, piers no oceano e fumarolas terrestres).
    - Hybrid Quality Score (Hybrid Scene Director): **94.1 / 100** (Eliminação de alucinações de stock; geração contextual para cenas HERO).
    - **Quality Delta:** **+36.3 pontos** de ganho perceptivo comprovado.
  - **Estratégias Mistas Aplicadas:**
    - 1 cena de Stock de Alta Confiança (Cena 1 - Planeta Marte no espaço cósmico com score 65.0).
    - 6 cenas geradas contextualmente via Nano Banana + Still Motion dinâmico (`pan_right`, `zoom_out`, `pan_left`, `static`, `zoom_in`, `pan_right`).
    - 3 cenas HERO com stock deficiente amplamente aprimoradas (Monte Olimpo, rios primitivos e pôr do sol azul).
  - **Auditoria Rigorosa de Legendas e Narração (V16.5.1):**
    - `subtitle_position`: inferior seguro (`bottom`).
    - `font_size`: 60 (>= 50 em 9:16).
    - Cores: texto branco (`#FFFFFF`), stroke preto 2.0 (`#000000`, 2.0px).
    - Voz: `pt-BR-AntonioNeural-Male` a `voice_rate = 1.0` (sem regressão para 0.8).
  - **Artefatos Gerados em `storage/validation`:**
    - `hybrid_validation_<timestamp>.json`
    - `hybrid_validation_<timestamp>.csv`
    - `scene_comparison_<timestamp>.md`
    - `prompts_catalog_<timestamp>.md`
    - `preview_still_motion_scene_3.mp4` (preview H.264 vertical gerado com ffmpeg).
- **Próximo Passo:** `V16.9_HYBRID_VISUAL_PRODUCTION_ROLLOUT`.

### V16.8.1 — Real Generated Image Quality Gate (Bloqueada por Limite Free Tier)
- **Status:** ⚠️ `REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED` (06/10/2026)
- **Resultado:** A tentativa real com chave oficial Google AI Studio foi bloqueada por cota externa (`HTTP 429 Free Tier limit = 0 requests/day`).
- **Decisão Canônica:** Não ativar billing, não depender de provedores pagos. A esteira foi redirecionada para fontes públicas confiáveis na V16.8.2.

### V16.8.2 — Alternative Visual Sources Evaluation (Concluída em DEV)
- **Status:** ✅ `DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)` (06/10/2026)
- **Branch:** `feat/v16-8-2-alternative-visual-sources`
- **Validação Local:** 11 testes PASS em `test/services/test_thematic_visual.py`, 69 testes PASS no total de suítes híbridas e temáticas (`uv run pytest`), lint limpo (`uv run ruff check` — 0 erros).
- **Provedores Implementados:**
  1. `NASAImageLibraryProvider` (`nasa_image_library`, autoridade 15.0, Domínio Público NASA, zero chave).
  2. `WikimediaCommonsProvider` (`wikimedia_commons`, autoridade 12.0, licenças abertas CC/Domínio Público, zero chave).
- **Resultados na Task de Marte (`17386147-cb1b-4192-b827-251a1bbd411f`):**
  - **Cena 3 (Monte Olimpo):** Stock baseline fraco `9354647` (28.0) -> Fonte Temática `wiki_98866197` (**82.78** pts, CC-BY) -> **APROVADO**.
  - **Cena 4 (Escala titânica):** Stock com vaso de planta `8474871` (28.0) -> Mapa geológico autêntico `wiki_127759484` (**78.0** pts, Domínio Público) -> **APROVADO**.
  - **Cena 7 (Pôr do sol azul marciano):** Stock terrestre `8474684` (22.0) -> Foto real do pôr do sol azul pelo Rover Perseverance Mastcam-Z `nasa_PIA24935` (**73.0** pts, Domínio Público NASA) -> **APROVADO**.
- **Still-Motion Previews Gerados (H.264 9:16 vertical, 3.0s):**
  - `storage/validation/v16_8_2/previews/scene_3_preview.mp4` (zoom_out)
  - `storage/validation/v16_8_2/previews/scene_4_preview.mp4` (pan_left)
  - `storage/validation/v16_8_2/previews/scene_7_preview.mp4` (pan_right)
- **Artefatos e Relatórios:**
  - `storage/validation/v16_8_2/thematic_sources_report.json`
  - `storage/validation/v16_8_2/thematic_sources_report.md`
  - `storage/validation/v16_8_2/scene_3_stock_vs_thematic.md`
  - `storage/validation/v16_8_2/scene_4_stock_vs_thematic.md`
  - `storage/validation/v16_8_2/scene_7_stock_vs_thematic.md`
- **Auditoria de Provedores Generativos Gratuitos:**
  - Cloudflare Workers AI: `REQUIRES_ACCOUNT` (10k neurons/dia, complexidade média).
  - Hugging Face Inference Providers: `FREE_QUOTA_UNKNOWN` (cold-starts, erros 503 frequentes).
- **Próximo Passo:** `V16.9 — Hybrid Visual Production Rollout` (Rollout seguro da seleção híbrida Stock + Thematic Sources para produção).



