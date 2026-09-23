# PROJECT_HANDOFF — Video Factory / MoneyPrinterTurbo

## V14-C.2 — Expressive Presenter + Subtitle Interaction — DEV controlado

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
- **Próximo Passo:** V14-C.3 — Nox Visual Asset Pack + Real Local Preview.

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

## Estado vigente — 21/09/2026 — V12-F.2 em validação DEV

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
