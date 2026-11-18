# Mapa de Limpeza do Legado V1 (`docs/v2/MAPA_LIMPEZA_V1.md`)

- **Missão:** `v2/mapa-limpeza-v1` (somente mapeamento e inventário auditável; zero remoção/edição de arquivos existentes)
- **Base auditada (`origin/main`):** `552b20dacdbe18ce6b4b336f6d1850a989ae19a3`
- **Data da auditoria:** `16/11/2026`

---

## 1. Tamanho Atual do Repositório e Fontes de Verdade (Pontos de Entrada)

### 1.1 Medição do Git (`git count-objects -vH`) e Working Tree (`git ls-files`)

```text
count: 1355
size: 27.35 MiB
in-pack: 8305
packs: 311
size-pack: 199.06 MiB
prune-packable: 1
garbage: 0
size-garbage: 0 bytes
```

| Diretório Topo | Arquivos Rastreados | Tamanho (Bytes) | Tamanho (MiB) |
| :--- | ---: | ---: | ---: |
| `resource/` | 45 | 206.737.879 | 197,16 MiB |
| `test/` | 252 | 5.038.081 | 4,80 MiB |
| `webui-v2/` | 69 | 3.854.905 | 3,68 MiB |
| `docs/` | 60 | 3.759.607 | 3,59 MiB |
| `app/` | 119 | 3.661.159 | 3,49 MiB |
| `webui/` | 19 | 1.249.785 | 1,19 MiB |
| `(root)` | 25 | 978.659 | 0,93 MiB |
| `scripts/` | 45 | 795.136 | 0,76 MiB |
| `.github/` | 7 | 14.329 | 0,01 MiB |
| `.agents/` | 1 | 5.724 | 0,01 MiB |
| `assets/` | 4 | 2.293 | 0,00 MiB |
| **TOTAL (`git ls-files`)** | **646** | **226.097.557** | **215,62 MiB** |

### 1.2 Pontos de Entrada Reais Considerados (Fontes de Verdade de Produção V2)

1. **Launcher e Supervisor de Produção (Scheduled Task `"VideoFactory Production"`):**
   - `scripts/start_production.ps1` -> por padrão (`$Legacy = $false`, porta `8080`) executa `.venv\Scripts\python.exe scripts\engine_entrypoint.py` sob supervisor e valida a existência de `webui-v2\dist\index.html`.
   - `scripts/engine_entrypoint.py` -> inicializa logging, `wait_for_primary_lock()`, `bootstrap_primary_and_worker()` (atualmente importado de `scripts/production_entrypoint.py`), `task.recover_interrupted_cross_posts()`, `operator_console.reconcile_orphaned_tasks()`, `SchedulerWatchdog` e `uvicorn` servindo `app.asgi:app`.
2. **Aplicação ASGI / FastAPI (`main.py` e `app/asgi.py`):**
   - `app/asgi.py` -> monta `/tasks`, serve `webui-v2/dist` (ou fallback `resource/public/index.html`) via `SPAStaticFiles` e inclui `app/router.py`.
   - `app/router.py` -> registra `app/controllers/ping.py`, `app/controllers/v2/{operations,review,fleet,production,diagnostics}.py` e `app/controllers/v1/{video,llm}.py`.
3. **Scripts Operacionais de Deploy, Backup, Restore e Saúde:**
   - `scripts/update_production.ps1` -> usa `app.utils.utils`, `app.services.media_quality`, `requirements.txt` e extrai/executa `scripts/build_stamp.py` (`--verify`) contra `webui-v2/dist/BUILD_STAMP.json`.
   - `scripts/backup_production.ps1` -> executa `python -m app.services.production_backup`.
   - `scripts/restore_production_backup.ps1` -> executa `python -m app.services.production_recovery` e consulta `app.services.production_backup`.
   - `scripts/production_status.ps1` -> executa `python -m app.services.production_health` (também referenciado em `app/services/operator_console.py`).
   - `scripts/ocupado.py` -> importado por `app/services/operator_console.py` e `scripts/engine_entrypoint.py`.
4. **Subprocessos e Módulos Invocados pelo Pipeline de Geração/Publicação:**
   - **Google Flow:** `app/services/flow_bridge.py` e `app/services/copyright_gate.py` importam `scripts/flow_workflow.py`; `scripts/flow_workflow.py` e `app/services/flow_account_pool.py` importam `scripts/flow_playwright.py`; `scripts/flow_workflow.py` importa `app/services/visual_director.py`.
   - **Quizzes (`quiz_dilemma` e `quiz_paper`):** `app/services/task.py` e `app/services/quiz_generator.py` importam diretamente `scripts/poc_quiz_render.py` e `scripts/poc_quiz_paper_render.py`.
   - **Executor de Tasks em Background:** `app/services/webui_task.py` (apesar do prefixo histórico `webui_`, é o worker pool em memória usado por `autonomous_production.py`, `operator_console.py`, `production_overview.py` e `scheduler.py`).

---

## 2. Resumo Consolidado por Categoria

| Categoria | Descrição | Qtd. Arquivos | Tamanho na Working Tree |
| :--- | :--- | ---: | ---: |
| **Categoria A** | **Removível com alta confiança** (sem import/chamada do runtime V2; inclui `webui/`, scripts de POC/validação avulsos, 5 módulos `app/services/` órfãos, 5 fontes não usadas pelo motor, protótipo/logos em `docs/` e testes exclusivos) | **113 arquivos** | **~75,47 MiB** (79.136.410 B) |
| **Categoria B** | **Em uso (MANTER)** (motor FastAPI/V2, `webui-v2/`, `scripts/` operacionais e de pipeline como `poc_quiz_*` e `flow_*`, `webui_task.py`, testes ativos e docs canônicos) | **429 arquivos** | **~14,91 MiB** (15.635.098 B) |
| **Categoria C** | **Incerto / Requer decisão do Rico** (`resource/songs/*.mp3`, 2 fontes CJK default `STHeitiMedium.ttc` / `MicrosoftYaHeiBold.ttc`, scripts de transição R8/rollback `-Legacy`, `cli.py`, `presenter.py`/Nox, pipeline `hybrid_visual`, `docs/auditorias/`, Dockerfiles) | **104 arquivos** | **~125,24 MiB** (131.326.049 B) |

---

## 3. Inventário Detalhado por Área

### 3.1 Interface Legada `webui/` (Streamlit V1), Launchers Raiz e Serviços Exclusivos da UI V1

> **Evidência global (`grep`):** Nenhum arquivo em `app/` ou `webui-v2/` importa `webui` ou `streamlit`. Os únicos arquivos fora de `webui/` e `test/` que citam `webui/Main.py` ou `streamlit` são `scripts/production_entrypoint.py` (`MAIN_SCRIPT_PATH = str(PROJECT_ROOT / "webui" / "Main.py")`), `scripts/start_production.ps1` (ramo opcional `-Legacy`), `scripts/update_production.ps1` (detecção de processos `streamlit` antigos para parada), `webui.bat`, `webui.sh`, `cli.py` e `docker-compose*.yml`.

| Caminho | Tamanho | Cat. | Evidência (Grep / Imports / Chamadas) | Risco de Remover | Testes que Referenciam (Ação) |
| :--- | :--- | :---: | :--- | :--- | :--- |
| `webui/.streamlit/config.toml` | 208 B | **A** | Zero referências em `app/` e `scripts/`. | Baixo (sai junto com `webui/`). | Nenhum. |
| `webui/Main.py` | 457.609 B | **A** | Referenciado apenas por `scripts/production_entrypoint.py` (modo `-Legacy`), `webui.bat`, `webui.sh`, `cli.py` (subcomando `ui`) e testes de UI V1. Zero imports em `app/`. | Médio se removido antes de desativar `-Legacy` e limpar testes que fazem `import webui.Main` ou `AppTest.from_file("webui/Main.py")`. | 22 arquivos `test/services/test_webui_*.py`, `test_v1_*.py`, `test_streamlit_scheduler_session_state.py`, `test_fish_audio.py`, `test_generation_controls_and_ptbr.py`, `test_cli.py`, `test_production_entrypoint.py`. |
| `webui/components/__init__.py` | 37 B | **A** | Só usado por `webui/Main.py`. | Baixo. | Sai junto com `webui/`. |
| `webui/components/channel_factory.py` | 45.020 B | **A** | Importado em produção apenas por `webui/Main.py` e `webui/components/operator_console.py`. Zero imports em `app/` ou `scripts/`. | Atenção: 5 testes de serviços (`test_channel_factory.py`, `test_ambient_bgm.py`, `test_lote4_performance.py`, `test_mission_h_independent_scheduling.py`, `test_operator_console_status_semantics.py`) ainda importam helpers visuais daqui. | Remover/adaptar chamadas de UI V1 nesses 5 testes ao remover `webui/`. |
| `webui/components/operator_console.py` | 171.012 B | **A** | Importado apenas por `webui/Main.py`. Zero imports em `app/` ou `scripts/`. | Mesmo cuidado de limpar referências em `test_channel_factory.py`, `test_mission_o_flow_capacity_and_ui.py`, `test_v1_copyright_and_full_render.py`, `test_v1_ui_safety_loading_hotfix.py`. | Remover junto com `webui/` após ajustar testes. |
| `webui/i18n/*.json` (13 arquivos: `az, de, en, es, fr, id, it, ko, pt, ru, tr, vi, zh`) | 554.521 B | **A** | Lidos exclusivamente por `webui/Main.py` (`tr()`). A API V2 e `webui-v2` não usam `webui/i18n/`. | Atenção: `test/services/test_webui_i18n.py` e `test/services/test_generation_controls_and_ptbr.py` leem `webui/i18n/*.json`. | `test_webui_i18n.py` (remover junto); `test_generation_controls_and_ptbr.py` (remover caso de teste da V1). |
| `webui/styles.css` | 21.378 B | **A** | Carregado apenas por `webui/Main.py`. | Nenhum. | Nenhum. |
| `webui.bat` e `webui.sh` | 5.902 B | **A** | Launchers manuais antigos do Streamlit (`streamlit run ./webui/Main.py`). Não usados por nenhuma Scheduled Task nem script de produção. | Baixo (`test/services/test_webui_startup.py` testa `webui.sh`). | `test/services/test_webui_startup.py` (remover junto). |
| `app/services/version_checker.py` | 7.850 B | **A** | `[NO APP IMPORTER]`: importado exclusivamente por `webui/Main.py` (checa release GitHub do upstream no rodapé do Streamlit). | Baixo. | `test/services/test_version_checker.py` (remover junto). |
| `app/services/production_observability.py` | 27.023 B | **A** | `[NO APP IMPORTER]`: importado exclusivamente por `webui/components/operator_console.py`. A V2 usa `app/services/production_overview.py` e `app/services/production_diagnostics.py`. | Baixo. | `test/services/test_production_observability.py` (remover junto). |
| `app/services/cache_manager.py` | 9.030 B | **A** | `[NO APP IMPORTER]`: importado apenas por `webui/Main.py`. | Baixo. | `test/services/test_cache_manager.py` (remover junto) e 1 teste em `test/services/test_v16_12_backport.py`. |
| **`app/services/webui_task.py`** | **13.827 B** | **B (MANTER)** | **FALSO SUSPEITO:** apesar do nome `webui_task`, é importado e chamado por `app/services/autonomous_production.py`, `app/services/operator_console.py`, `app/services/production_overview.py` e `app/services/scheduler.py` para submeter e monitorar tasks ativas (`submit_generation`, `has_active_generation_tasks`, `get_active_task_ids`). | **CRÍTICO SE REMOVIDO** (quebra toda geração autônoma e manual). | `test/services/test_webui_task.py` (manter a cobertura do serviço). |

---

### 3.2 Diretório `scripts/` (Todos os 45 Arquivos Auditados) e Serviços `app/services/` Acoplados

| Caminho | Tamanho | Cat. | Evidência (Grep / Imports / Chamadas) | Risco de Remover | Testes Relacionados |
| :--- | :--- | :---: | :--- | :--- | :--- |
| `scripts/start_production.ps1` | 10.706 B | **B** | Ponto de entrada da Scheduled Task `"VideoFactory Production"`. | Crítico (não remover). | `test_start_production_supervisor.py`, `test_cutover_runbook_guard.py`. |
| `scripts/engine_entrypoint.py` | 20.169 B | **B** | Motor Unificado V2 chamado por `start_production.ps1` e `start_engine.ps1`. | Crítico (não remover). | `test_engine_entrypoint.py`, `test_v2_primary_lock_and_secondary_view_only.py`. |
| `scripts/production_entrypoint.py` | 7.124 B | **B -> A (após desacoplar)** | **CUIDADO CRÍTICO:** `scripts/engine_entrypoint.py:51-55` faz `from scripts.production_entrypoint import DEFAULT_WORKER_INTERVAL_SECONDS, bootstrap_primary_and_worker, shutdown_worker_and_lock`. Também usado por `start_production.ps1 -Legacy`. | **Alto hoje:** apagar sem mover essas 3 funções para `engine_entrypoint.py` quebra o boot do Motor V2. Após mover as 3 funções e retirar `-Legacy`, passa a Categoria A. | `test/test_production_entrypoint.py`. |
| `scripts/update_production.ps1` | 49.275 B | **B** | Script oficial de update FF-only da PROD. | Crítico (não remover). | `test_safe_production_update.py`, `test_update_production_health_and_rollback.py`, `test_cutover_runbook_guard.py`. |
| `scripts/build_stamp.py` | 13.005 B | **B** | Extraído e executado por `scripts/update_production.ps1` (linhas 702-721) para validar `webui-v2/dist/BUILD_STAMP.json`. | Crítico (se removido, `update_production.ps1` pula ou falha na validação de bundle). | `test/services/test_webui_dist_sync.py`. |
| `scripts/backup_production.ps1` | 1.927 B | **B** | Script operacional oficial (`python -m app.services.production_backup`), citado em `docs/PRODUCTION_RUNBOOK.md`. | Alto (ferramenta de operação). | `test_production_backup.py` (testa o serviço). |
| `scripts/restore_production_backup.ps1` | 4.067 B | **B** | Script operacional oficial (`python -m app.services.production_recovery`), citado no Runbook. | Alto (ferramenta de operação). | `test_production_recovery.py` (testa o serviço). |
| `scripts/production_status.ps1` | 1.607 B | **B** | Chamado/referenciado em `app/services/operator_console.py` e `docs/PRODUCTION_RUNBOOK.md` (`python -m app.services.production_health`). | Médio-Alto (manter). | `test_production_health.py`. |
| `scripts/ocupado.py` | 3.766 B | **B** | Importado por `app/services/operator_console.py` e `scripts/engine_entrypoint.py`. | Crítico (quebra motor e console se removido). | `test_cutover_runbook_guard.py`, `test_flow_saldo_real.py`, `test_flow_workflow.py`. |
| `scripts/flow_playwright.py` | 141.158 B | **B** | Importado por `app/services/flow_account_pool.py` e `scripts/flow_workflow.py`. Motor real de automação Playwright/Edge do Google Flow. | Crítico (não remover). | 9 suítes `test_flow_*.py` e `test_visual_director.py`. |
| `scripts/flow_workflow.py` | 62.295 B | **B** | Importado por `app/services/flow_bridge.py` e `app/services/copyright_gate.py`. | Crítico (não remover). | 9 suítes `test_flow_*.py`, `test_quality_gate_v2.py`, `test_visual_director.py`. |
| `scripts/poc_quiz_render.py` | 52.873 B | **B** | **FALSO SUSPEITO (`poc_`):** importado diretamente por `app/services/task.py` e `app/services/quiz_generator.py` para renderizar vídeos de `quiz_dilemma`. | Crítico (quebra o canal de Quiz de Escolhas). | 9 suítes `test_quiz_*.py` e `test_mission_a_*.py`. |
| `scripts/poc_quiz_paper_render.py` | 65.048 B | **B** | **FALSO SUSPEITO (`poc_`):** importado diretamente por `app/services/task.py` e `app/services/quiz_generator.py` para renderizar vídeos de `quiz_paper`. | Crítico (quebra o canal Quiz_Quiz de papel). | 6 suítes `test_quiz_paper_*.py` e `test_mission_i/k_*.py`. |
| `scripts/reconcile_publication_state.py` | 5.550 B | **B** | CLI operacional que expõe `app/services/publication_reconciliation.py`, documentado em `docs/PRODUCTION_RUNBOOK.md`. | Baixo-Médio (útil para operação; manter). | `test/services/test_publication_reconciliation.py`. |
| `scripts/reset_pending_publications.py` | 13.678 B | **B** | CLI operacional para `app/services/publication_reset.py`, documentado em `docs/PRODUCTION_RUNBOOK.md`. | Baixo-Médio (manter). | `test/services/test_v16_4_2r_pre_repair_publishing_reset.py`. |
| `scripts/cleanup_retry_metadata.py` | 1.975 B | **B** | CLI operacional para `app/services/retry_policy.py`, documentado em `docs/PRODUCTION_RUNBOOK.md`. | Baixo-Médio (manter). | `test/services/test_publishing_retry_cleanup.py`. |
| `scripts/inspect_held_quality_videos.py` | 11.653 B | **B** | CLI de inspeção de vídeos retidos no Quality Gate, validado por `test_quality_gate_v2.py`. | Baixo-Médio (manter). | `test/services/test_quality_gate_v2.py`. |
| `scripts/recover_held_quality_videos.py` | 8.028 B | **B** | CLI de recuperação de vídeos retidos (`app/services/quality_recovery.py`). | Baixo-Médio (manter). | `test/services/test_quality_gate_v2.py`. |
| `scripts/start_engine.ps1` | 6.544 B | **C** | Launcher manual dev/standalone do `engine_entrypoint.py` (sem o loop supervisor de `start_production.ps1`). Zero referências em outros scripts/testes. | Baixo (útil para rodar motor manualmente em DEV; Rico decide se mantém ou consolida em `start_production.ps1`). | Nenhum. |
| `scripts/start_webui_v2.ps1` | 7.274 B | **C** | Launcher da fase de transição R8 (quando a V2 rodava como `SECONDARY_VIEW_ONLY` ao lado do Streamlit). Referenciado por `register_webui_v2_task.ps1`, `package_webui_v2.ps1` e `test_webui_v2_autostart.py`. | Baixo após cutover definitivo (em PROD a task principal já usa `start_production.ps1`). | `test/services/test_webui_v2_autostart.py` (remover junto se descontinuado). |
| `scripts/register_webui_v2_task.ps1` | 11.847 B | **C** | Registrava a task secundária `"VideoFactory WebUI V2"` na época da convivência com Streamlit 8501. | Baixo se a task secundária já foi desregistrada no PC Forte. | `test/services/test_webui_v2_autostart.py`. |
| `scripts/package_webui_v2.ps1` | 9.352 B | **C** | Gerador de pacote `.zip` de `webui-v2/dist` da fase R10 (hoje `webui-v2/dist` é versionado no Git com `BUILD_STAMP.json`). | Baixo (Rico decide se ainda quer o empacotador avulso). | Nenhum. |
| `scripts/dev/auditar_vozes_canais.py` | 8.430 B | **A** | Zero referências em `app/`, `scripts/`, `test/` ou `docs/`. Script ad-hoc de diagnóstico DEV. | Nenhum. | Nenhum. |
| `scripts/dev/benchmark_stock_perf.py` | 13.779 B | **A** | Zero referências em `app/`, `scripts/`, `test/` ou `docs/`. Benchmark pontual de stock. | Nenhum. | Nenhum. |
| `scripts/dev/medir_endpoints.py` | 19.646 B | **A** | Zero referências em `app/`, `scripts/`, `test/` ou `docs/`. Script pontual de medição de latência. | Nenhum. | Nenhum. |
| `scripts/audit_learning_loop.py` | 21.464 B | **A** | Zero referências em código ou testes; citado apenas em `docs/auditorias/AUD_ciclo_aprendizado.md`. | Nenhum. | Nenhum. |
| `scripts/audit_voices.py` | 21.851 B | **A** | Zero referências em `app/` ou `scripts/`; usado apenas por seu próprio teste unitário. | Nenhum (remover junto com seu teste). | `test/services/test_audit_voices.py` (remover junto). |
| `scripts/benchmark_video_models.py` | 14.954 B | **A** | Benchmark de modelos locais na RX580 (fase V16.6.1 encerrada). Zero referências em `app/` ou `scripts/`. | Nenhum (remover ou ajustar asserção em `test_hybrid_visual_generation.py`). | `test/services/test_hybrid_visual_generation.py` (referencia o módulo). |
| `scripts/diagnose_v15b.py` + `app/services/flow_diagnostics.py` | 5.289 B + 44.880 B | **A** | `flow_diagnostics.py` só é importado por `scripts/diagnose_v15b.py` e `test_v15b_diagnostics.py` (não é usado pelo endpoint V2 `/api/v2/diagnostics`, que usa `app/services/production_diagnostics.py`). | Nenhum se removidos juntos (`diagnose_v15b.py` + `flow_diagnostics.py` + `test_v15b_diagnostics.py`). | `test/services/test_v15b_diagnostics.py` (remover junto). |
| `scripts/generate_quiz_content.py` | 4.525 B | **A** | Script CLI manual da fase inicial de protótipo de Quiz. Zero chamadas em `app/`, `scripts/` ou `test/`. | Nenhum. | Nenhum. |
| `scripts/resolve_quiz_assets.py` | 2.661 B | **A** | Script CLI manual da fase inicial de Quiz. Zero chamadas em `app/`, `scripts/` ou `test/`. | Nenhum. | Nenhum. |
| `scripts/remux_faststart.py` | 9.789 B | **A** | Utilitário avulso de remux MP4 (`+faststart`); o pipeline principal já aplica `+faststart` em `app/services/video.py` / `poc_quiz_*`. Zero chamadas em `app/`. | Nenhum (remover junto com seu teste). | `test/services/test_faststart_contract.py` (remover junto). |
| `scripts/reset_metrics_baseline.py` | 39.578 B | **A** | Script one-shot de reset de baseline histórico. Zero imports em `app/` ou `scripts/`. | Nenhum (remover junto com seu teste). | `test/services/test_reset_metrics_baseline.py` (remover junto). |
| `scripts/run_closed_loop_tests.py` | 2.661 B | **A** | Runner antigo de testes da fase V12-F.2. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/run_hybrid_validation.py` + `app/services/hybrid_validation.py` | 6.805 B + 24.284 B | **A** | `hybrid_validation.py` só é importado por `scripts/run_hybrid_validation.py` e `test_hybrid_validation.py`. Zero referências no pipeline `app/services/task.py`. | Nenhum se removidos juntos. | `test/services/test_hybrid_validation.py` (remover junto). |
| `scripts/run_q5b1_homologation.py` | 5.648 B | **A** | Script one-shot de homologação antiga Q5-B1. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/run_v16_10_full_dev_render.py` | 21.913 B | **A** | Script one-shot de homologação V16.10. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/run_v16_8_1_real_image_gate.py` + `app/services/real_image_gate.py` | 4.622 B + 21.678 B | **A** | `real_image_gate.py` só é importado por `scripts/run_v16_8_1_real_image_gate.py` e `test_real_image_gate.py`. Zero referências no runtime V2. | Nenhum se removidos juntos. | `test/services/test_real_image_gate.py` (remover junto). |
| `scripts/run_v16_8_2_thematic_evaluation.py` | 15.062 B | **A** | Script one-shot de avaliação V16.8.2. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/run_v1_1_flow_jfk_video.py` | 16.602 B | **A** | Script histórico do primeiro vídeo manual Flow (JFK, V1.1). Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/run_v1_5d_multi_niche_validation.py` | 13.749 B | **A** | Script one-shot de validação V1.5D. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/validate_g8_8_audio_homologation.py` | 16.763 B | **A** | Script one-shot de homologação de áudio G8.8. Zero referências em `app/`. | Nenhum (remover junto com seu teste). | `test/services/test_g8_8_audio_homologation.py` (remover junto). |
| `scripts/validate_v16_12_controlled_render.py` | 4.247 B | **A** | Script one-shot da fase V16.12. Zero referências em código/testes. | Nenhum. | Nenhum. |
| `scripts/youtube_direct_probe.py` + `app/services/youtube_direct.py` | 10.926 B + 15.282 B | **A** | `youtube_direct.py` só é importado por `scripts/youtube_direct_probe.py` e `test_youtube_direct.py` (a fábrica usa `app/services/analytics_providers/youtube.py` para YouTube Analytics e `post_for_me.py` / `youtube_publisher.py` para publicação). | Baixo (se removido junto com `youtube_direct.py` e `test_youtube_direct.py`, também permite avaliar a remoção de `google-api-python-client` / `google-auth-*` caso não sejam usados em mais nenhum lugar). | `test/services/test_youtube_direct.py` (remover junto). |
| `scripts/rate_visual_task.py` | 5.251 B | **C** | CLI para `app/services/adaptive_visual_feedback.py` (que ainda é importado por `app/services/scene_material.py` e `hybrid_visual.py`). | Médio (depende da decisão sobre manter ou remover `adaptive_visual_feedback.py`). | `test/services/test_adaptive_visual_feedback.py`. |

---

### 3.3 Dependências Python (`requirements.txt` e `pyproject.toml`)

> **Importante (`scripts/update_production.ps1`):** O preflight da atualização de produção executa `Test-VenvDependencies` comparando `requirements.txt` com os pacotes instalados no `.venv` da PROD. Remover um pacote de `requirements.txt` e `pyproject.toml` **não** exige desinstalá-lo imediatamente do `.venv` da PROD (o preflight apenas verifica se todos os itens listados em `requirements.txt` estão presentes no `.venv`).

| Pacote (`requirements.txt` / `pyproject.toml`) | Cat. | Onde é Importado (`app/`, `scripts/`, `webui/`) | Recomendação |
| :--- | :---: | :--- | :--- |
| `streamlit==1.59.1` | **A (Fase 4)** | `webui/*` (3 arquivos), `scripts/production_entrypoint.py` (lazy em `run_streamlit_server`), 23 arquivos de teste. Zero imports em `app/` ou `engine_entrypoint.py`. | Remover junto com `webui/` na Fase 4. |
| `streamlit-tour==1.1.0` | **A (Fase 4)** | Apenas `webui/Main.py` (1 import). Zero referências em `app/`, `scripts/` ou `test/`. | Remover junto com `webui/` na Fase 4. |
| `pyyaml==6.0.3` (`import yaml`) | **A** | **Zero imports** em todo o repositório (`app:0, scripts:0, webui:0, test:0`). | Pode ser removido de `requirements.txt` e `pyproject.toml`. |
| `socksio==1.0.0` | **C** | Zero imports diretos no código, mas é dependência de transporte SOCKS para `httpx`/`openai` quando há proxy configurado. | Manter se houver chance de proxy SOCKS, ou remover se não utilizado. |
| `google-api-python-client>=2.200.0`, `google-auth-oauthlib>=1.4.1`, `google-auth-httplib2>=0.4.2` | **A (com `youtube_direct.py`)** | Importados **exclusivamente** em `app/services/youtube_direct.py` (o provedor ativo `app/services/analytics_providers/youtube.py` usa `requests` direto nas APIs REST do Google). | Remover após remover `app/services/youtube_direct.py` e `scripts/youtube_direct_probe.py`. |
| `dashscope==1.20.14` | **C** | Importado em `app/models/llm_provider.py` e `app/services/llm.py` (provedor chinês Qwen/Alibaba herdado do upstream). | Decisão do Rico: manter por compatibilidade com código upstream de LLM ou limpar provedores não usados. |
| `redis==5.2.0` | **C** | Importado em `app/controllers/manager/redis_manager.py`, `app/controllers/v1/video.py` e `app/services/state.py` (quando `enable_redis = true` no `config.toml`; em PROD usa-se memória/SQLite). | Decisão do Rico: manter suporte opcional a Redis ou simplificar para memória/SQLite. |
| `moviepy==2.2.1`, `edge-tts==7.3.1`, `fastapi==0.136.3`, `uvicorn==0.32.1`, `openai==2.24.0`, `faster-whisper==1.1.0`, `loguru==0.7.3`, `google-genai==2.11.0`, `azure-cognitiveservices-speech==1.41.1`, `python-multipart==0.0.27`, `requests==2.33.1`, `packaging==24.2`, `pydub==0.25.1`, `audioop-lts==0.2.2`, `litellm==1.86.2`, `playwright==1.63.0` | **B (MANTER)** | Usados ativamente pelo motor V2, pipeline de geração, legendas, TTS, LLM, Flow e health checks. | **Manter todos.** |

---

### 3.4 Grandes Binários, Fontes e Áudios em `resource/`, `assets/` e `webui-v2/dist/`

> `resource/` sozinho representa **197,16 MiB de 215,62 MiB (91,4%)** de todos os arquivos rastreados no repositório!

| Caminho | Tamanho | Cat. | Evidência de Uso Real no Código | Risco e Ação Necessária |
| :--- | :--- | :---: | :--- | :--- |
| `resource/fonts/STHeitiLight.ttc` | **55.783.456 B (53,20 MiB)** | **A** | **Zero referências** em `app/`, `scripts/` ou `webui/`. Citada apenas em `test/services/test_cli.py` e `test/services/test_video.py`. | **Baixo:** atualizar os 2 testes para usar `BeVietnamPro-Bold.ttf` e remover os 53,20 MiB. |
| `resource/fonts/MicrosoftYaHeiNormal.ttc` | **19.701.556 B (18,79 MiB)** | **A** | **Zero referências** em `app/`, `scripts/` ou `webui/`. Citada apenas em `test/services/test_video.py`. | **Baixo:** ajustar `test_video.py` e remover os 18,79 MiB. |
| `resource/fonts/Charm-Bold.ttf` | 135.332 B (0,13 MiB) | **A** | Zero referências em código ou testes. | Nenhum. |
| `resource/fonts/Charm-Regular.ttf` | 134.560 B (0,13 MiB) | **A** | Zero referências em `app/` ou `scripts/` (apenas `test_video.py`). | Baixo (ajustar `test_video.py`). |
| `resource/fonts/UTM Kabel KT.ttf` | 35.456 B (0,03 MiB) | **A** | Zero referências em código ou testes. | Nenhum. |
| `resource/fonts/BeVietnamPro-Bold.ttf` e `BeVietnamPro-Medium.ttf` | 273.680 B (0,26 MiB) | **B (MANTER)** | Usadas ativamente por `app/services/quiz_assets.py`, `app/services/quiz_generator.py`, `scripts/poc_quiz_render.py` e `scripts/poc_quiz_paper_render.py`. | **Crítico manter.** |
| `resource/fonts/STHeitiMedium.ttc` | **55.754.164 B (53,17 MiB)** | **C (B hoje -> A se trocar default)** | Hardcoded como fallback default em `app/models/schema.py:99,168,311`, `app/services/production_health.py:397`, `app/services/video.py:1744,2193` e `scripts/flow_workflow.py:1059`. | **Decisão do Rico:** se substituirmos o fallback default nesses 4 arquivos para `BeVietnamPro-Bold.ttf`, libera **53,17 MiB**! |
| `resource/fonts/MicrosoftYaHeiBold.ttc` | **16.880.832 B (16,10 MiB)** | **C (B hoje -> A se trocar default)** | Hardcoded como fallback em `app/services/autonomous_production.py:2649` (`config.ui.get("font_name", "MicrosoftYaHeiBold.ttc")`) e `config.example.toml`. | **Decisão do Rico:** se trocarmos o default em `autonomous_production.py:2649` para `BeVietnamPro-Bold.ttf` (e conferirmos `config.toml` da PROD), libera **16,10 MiB**! |
| `resource/songs/output000.mp3` .. `output029.mp3` (29 arquivos) | **55.843.803 B (53,26 MiB)** | **C** | Na produção autônoma (`bgm.resolve_autonomous_bgm`, linhas 371-381), faixas de `resource/songs` são **proibidas fail-closed** (usa-se sintetizador procedural `ambient_bgm.py` nos canais Flow e `quiz_bgm.py` nos Quizzes). Porém `bgm.list_bgm_files()` / `resolve_bgm_file()` ainda varrem `utils.song_dir()` para API V1 e `test_bgm.py` / `test_mission_i_quiz_paper.py` / `test_quiz_bgm.py` usam `output000.mp3` como fixture de teste. | **Decisão do Rico:** manter apenas `output000.mp3` (2,15 MiB) para testes/compatibilidade e remover `output001.mp3`..`output029.mp3` (**economiza 51,11 MiB**). |
| `resource/quiz_templates/quiz_template_p1_3_papel_homologado.json`, `quiz_template_perguntas_respostas_papel.json`, `quiz_template_escolhas_impossiveis.json` | 23.219 B | **B (MANTER)** | Referenciados por `app/services/quiz_generator.py`, `scripts/poc_quiz_paper_render.py` e `scripts/poc_quiz_render.py`. | **Manter.** |
| `resource/quiz_templates/quiz_conhecimentos_animais_factual.json`, `quiz_escolhas_impossiveis_gerado.json`, `quiz_template_q0r_homologado.json` | 25.796 B | **A** | Referenciados apenas pelos scripts manuais obsoletos `scripts/generate_quiz_content.py` e `scripts/resolve_quiz_assets.py`. Zero referências em `app/` ou `test/`. | Baixo (remover junto com os 2 scripts). |
| `resource/public/index.html` | 707 B | **B (MANTER)** | Fallback estático montado por `app/asgi.py:254` quando `webui-v2/dist/index.html` não existe. | **Manter** (707 bytes, garante que `app/asgi.py` nunca falhe ao montar `/`). |
| `webui-v2/dist/*` (bundle compilado + `BUILD_STAMP.json`) | ~1,81 MiB | **B (MANTER)** | **NÃO REMOVER DO GIT:** o PC Forte (PROD) não exige Node.js para rodar; `scripts/start_production.ps1` exige `webui-v2/dist/index.html` e `scripts/update_production.ps1` valida `webui-v2/dist/BUILD_STAMP.json` via `scripts/build_stamp.py` no commit alvo antes de atualizar. | **Crítico manter versionado.** |

---

### 3.5 Documentação (`docs/`) e Arquivos Soltos na Raiz (`(root)`)

| Caminho | Tamanho | Cat. | Evidência (Grep / Uso) | Risco de Remover |
| :--- | :--- | :---: | :--- | :--- |
| `docs/PROJECT_HANDOFF.md`, `docs/ROADMAP.md`, `docs/PRODUCTION_RUNBOOK.md`, `docs/DOCUMENTATION_POLICY.md` | 489.338 B | **B (MANTER)** | Os 4 documentos canônicos exigidos por `AGENTS.md`. | **Proibido remover.** |
| `docs/v2/REGRAS_DAS_MISSOES.md`, `docs/v2/CUTOVER_PROD.md`, `docs/v2/PARIDADE_V1_V2.md`, `docs/v2/INVENTARIO_DUPLICIDADES.md`, `docs/v2/STATUS_CANAL_ANALISE.md` | 132.712 B | **B (MANTER)** | Documentação ativa da V2 (`CUTOVER_PROD.md` é validado por `test/services/test_cutover_runbook_guard.py`). | **Manter** (`test_cutover_runbook_guard.py` lê `docs/v2/CUTOVER_PROD.md`). |
| `docs/CHARACTER_PRESENTER_SPEC.md` | 8.984 B | **B / C** | Validado diretamente por `test/services/test_presenter_asset_pack.py:72` (`assert spec_path.is_file()`). | Manter enquanto `presenter.py` e `test_presenter_asset_pack.py` existirem. |
| `docs/v2/prototipo/*` (`Central_de_Frota.dc.html`, `LEIA-ME.md` e 8 PNGs em `docs/v2/prototipo/sprites/*.png`) | **1.357.075 B (1,29 MiB)** | **A** | Protótipo HTML estático inicial. Os 8 arquivos `.png` em `docs/v2/prototipo/sprites/` são **cópias byte a byte idênticas** às imagens já presentes em `webui-v2/src/assets/fleet/*.png`. Zero referências em código ou testes. | **Nenhum** (libera 1,29 MiB sem perder nenhum asset, pois os originais estão em `webui-v2/src/assets/fleet/`). |
| `docs/sponsors/*` (11 logos de patrocinadores chineses do repo upstream: `ccsub-logo.png`, `metaso-logo.png`, `apimart-logo.png`, etc.) | **592.451 B (0,56 MiB)** | **A** | Imagens promocionais dos READMEs originais do MoneyPrinterTurbo upstream. Zero uso pela aplicação. | **Nenhum.** |
| `docs/api.jpg`, `docs/webui.jpg`, `docs/webui-en.jpg` | **605.645 B (0,58 MiB)** | **A** | Screenshots da antiga interface Streamlit V1 do upstream. Zero uso pela aplicação. | **Nenhum.** |
| `docs/MoneyPrinterTurbo.ipynb` | 8.517 B | **A** | Notebook Google Colab do projeto upstream original. Zero uso. | **Nenhum.** |
| `docs/loomloom/*.template.json` (2 arquivos) | 6.406 B | **A** | Templates promocionais do upstream LoomLoom. Zero referências no código (apenas em `test_webui_loomloom.py`, que testa a UI V1). | Baixo (sai junto com `test_webui_loomloom.py`). |
| `docs/voice-list.txt` | 13.924 B | **A** | Lista estática de texto do upstream; zero referências no código. | **Nenhum.** |
| `docs/auditorias/*` (15 arquivos `.md` e `.json`, incluindo `inventario_dev_v1.json` e `inventario_prod_pc_forte.json`) | 629.776 B (0,60 MiB) | **C** | Relatórios históricos de auditorias anteriores. Zero referências em código ou testes. | **Decisão do Rico:** manter como histórico documental ou arquivar/remover. |
| `docs/WEB_UI_V2.md`, `docs/WEB_UI_V2_MIGRATION_RUNBOOK.md`, `docs/AGENT_ORCHESTRATION.md`, `docs/analytics_providers.md`, `docs/production_deployment.md`, `docs/remote_access.md` | 111.219 B | **C** | Documentos técnicos de fases anteriores (R4A-R8, V12). | **Decisão do Rico:** manter como referência arquitetural ou consolidar. |
| `README-en.md` (38.516 B) e `README-ja.md` (40.857 B) na raiz | 79.373 B | **A** | Traduções em inglês/japonês do upstream original (atenção: `assets/presenter/nox_v1/reference/README.md` não tem relação; já `README-en.md` é citado no campo `readme = "README-en.md"` do `pyproject.toml`). | Baixo: ao remover `README-en.md` e `README-ja.md`, alterar `readme = "README.md"` em `pyproject.toml`. |
| `Dockerfile`, `Dockerfile.claude`, `Dockerfile.gpu`, `docker-compose.yml`, `docker-compose.claude.yml`, `docker-compose.gpu.yml`, `docker-compose.release.yml`, `.dockerignore` | 14.040 B | **C** | Arquivos Docker herdados do upstream (apontam para `streamlit run ./webui/Main.py`). A produção real roda nativamente no Windows via `.venv` e Scheduled Task. | **Decisão do Rico:** remover se Docker não for usado, ou atualizar para FastAPI V2. |
| `cli.py` (na raiz) + `docs/skill/mpt_agent.py` + `docs/skill/SKILL.md` | 104.991 B | **C** | CLI legado do upstream MoneyPrinterTurbo + skill de agente upstream, testados por `test/services/test_cli.py` (86 KB) e `test/services/test_mpt_agent_skill.py` (29 KB). Não são usados pelo motor V2 nem pelas Scheduled Tasks. | **Decisão do Rico:** confirmar se `cli.py` / `mpt_agent.py` têm algum uso externo; se não, remover junto com `test_cli.py` e `test_mpt_agent_skill.py` (libera ~220 KB de código/testes). |

---

### 3.6 Suítes de Teste em `test/` Associadas ao Legado V1

1. **Testes 100% exclusivos de código Categoria A (28 arquivos, 396.425 B / ~0,38 MiB — entram como "remover junto" com o respectivo alvo):**
   - **Exclusivos do Streamlit `webui/` (19 arquivos, 224.222 B):**
     - `test/services/test_streamlit_scheduler_session_state.py` (9.695 B)
     - `test/services/test_webui_bgm.py` (25.950 B)
     - `test/services/test_webui_generation_defaults.py` (19.573 B)
     - `test/services/test_webui_grouped_select.py` (5.342 B)
     - `test/services/test_webui_headless_task_actions.py` (2.637 B)
     - `test/services/test_webui_i18n.py` (11.325 B)
     - `test/services/test_webui_kokoro.py` (3.870 B)
     - `test/services/test_webui_llm_settings.py` (7.403 B)
     - `test/services/test_webui_loomloom.py` (23.186 B)
     - `test/services/test_webui_loomloom_regressions.py` (15.142 B)
     - `test/services/test_webui_manual_publish.py` (10.875 B)
     - `test/services/test_webui_metaso_minimax.py` (5.144 B)
     - `test/services/test_webui_ofox.py` (2.156 B)
     - `test/services/test_webui_ofox_placement.py` (3.346 B)
     - `test/services/test_webui_seedance.py` (2.242 B)
     - `test/services/test_webui_startup.py` (2.394 B)
     - `test/services/test_webui_task_history.py` (7.539 B)
     - `test/services/test_webui_tts_settings.py` (15.124 B)
     - `test/services/test_webui_upload_post_settings.py` (5.664 B)
     - `test/services/test_webui_ux_stability.py` (6.008 B)
     - `test/services/test_webui_voice_panel_validation.py` (18.452 B)
     - `test/services/test_webui_voice_preview.py` (18.680 B)
   - **Exclusivos de scripts/serviços Categoria A (9 arquivos, 148.678 B):**
     - `test/services/test_audit_voices.py` (8.082 B) -> testa `scripts/audit_voices.py`
     - `test/services/test_cache_manager.py` (4.256 B) -> testa `app/services/cache_manager.py`
     - `test/services/test_faststart_contract.py` (4.539 B) -> testa `scripts/remux_faststart.py`
     - `test/services/test_g8_8_audio_homologation.py` (22.984 B) -> testa `scripts/validate_g8_8_audio_homologation.py`
     - `test/services/test_hybrid_validation.py` (9.647 B) -> testa `app/services/hybrid_validation.py`
     - `test/services/test_production_observability.py` (10.731 B) -> testa `app/services/production_observability.py`
     - `test/services/test_real_image_gate.py` (20.295 B) -> testa `app/services/real_image_gate.py` e `scripts/run_v16_8_1_real_image_gate.py`
     - `test/services/test_reset_metrics_baseline.py` (45.843 B) -> testa `scripts/reset_metrics_baseline.py`
     - `test/services/test_v15b_diagnostics.py` (20.003 B) -> testa `app/services/flow_diagnostics.py` e `scripts/diagnose_v15b.py`
     - `test/services/test_version_checker.py` (7.288 B) -> testa `app/services/version_checker.py`
     - `test/services/test_youtube_direct.py` (14.421 B) -> testa `app/services/youtube_direct.py` e `scripts/youtube_direct_probe.py`

2. **Testes mistos de serviços ativos que contêm referências pontuais a `webui/` (MANTER o arquivo de teste, limpando apenas os subtestes/imports de `webui/` na Fase 4):**
   - `test/services/test_channel_factory.py`, `test/services/test_v1_copyright_and_full_render.py`, `test/services/test_v1_ui_safety_loading_hotfix.py`, `test/services/test_mission_o_flow_capacity_and_ui.py`, `test/services/test_mission_h_independent_scheduling.py`, `test/services/test_operator_console_status_semantics.py`, `test/services/test_lote4_performance.py`, `test/services/test_fish_audio.py`, `test/services/test_generation_controls_and_ptbr.py`, `test/services/test_webui_settings_transfer.py`, `test/services/test_webui_task.py`.

---

## 4. Riscos de Ordem (O Que Precisa Sair Junto) e Plano Sugerido de Fases

### 4.1 Riscos de Ordem e Acoplamentos Obrigatórios

1. **`scripts/engine_entrypoint.py` depende de `scripts/production_entrypoint.py`:**
   - Antes de remover `scripts/production_entrypoint.py`, é obrigatório mover `DEFAULT_WORKER_INTERVAL_SECONDS`, `bootstrap_primary_and_worker` e `shutdown_worker_and_lock` para `scripts/engine_entrypoint.py` (ou para `app/services/operator_console.py`) e remover a flag `-Legacy` de `scripts/start_production.ps1`.
2. **`pyproject.toml` referencia `README-en.md` e `webui/Main.py`:**
   - Se `README-en.md` for removido, atualizar `readme = "README.md"` em `pyproject.toml`.
   - Ao remover `webui/`, atualizar `[tool.ruff.lint.per-file-ignores]` e `[tool.coverage.run].source` em `pyproject.toml`.
3. **Fontes em `resource/fonts/` vs Testes:**
   - Ao remover `STHeitiLight.ttc`, `MicrosoftYaHeiNormal.ttc` e `Charm-Regular.ttf`, atualizar as referências literais em `test/services/test_video.py` e `test/services/test_cli.py` no mesmo commit.
4. **Serviços órfãos + Scripts + Testes:**
   - Sempre remover o trio atômico no mesmo commit: `(script em scripts/) + (serviço exclusivo em app/services/) + (teste exclusivo em test/services/)`.

### 4.2 Sugestão de Fases de Remoção (1 Branch por Fase, do Menor para o Maior Risco)

| Fase | Escopo da Branch | Arquivos Removidos | Ganho Aproximado (Working Tree) | Risco |
| :--- | :--- | ---: | ---: | :---: |
| **Fase 1** (`v2/limpeza-fase1-docs-scripts-avulsos`) — **EXECUTADA (`20230bd576d414ee75d3e36f42b3a7181e0f659f`)** | Remover duplicatas visuais de `docs/v2/prototipo/` (8 PNGs duplicados + HTML + LEIA-ME), `docs/sponsors/*`, `docs/api.jpg`, `docs/webui*.jpg`, `docs/MoneyPrinterTurbo.ipynb`, `docs/voice-list.txt`, `scripts/dev/*` (3 scripts) e 10 scripts `scripts/run_*` / `validate_v16_12_*` / `audit_learning_loop.py` / `generate_quiz_content.py` / `resolve_quiz_assets.py` + 3 JSONs de quiz não usados em `resource/quiz_templates/`. | 42 arquivos | **~2,69 MiB** | **Mínimo** (zero imports em código ou testes). |
| **Fase 2** (`v2/limpeza-fase2-pocs-servicos-orfaos`) — **EXECUTADA (`5ccc4b8b6d7d601542767eba98c667d5d767d8e0`)** | Remover pares script+serviço+teste sem uso no runtime V2: `diagnose_v15b.py` + `flow_diagnostics.py`, `run_hybrid_validation.py` + `hybrid_validation.py`, `run_v16_8_1_real_image_gate.py` + `real_image_gate.py`, `youtube_direct_probe.py` + `youtube_direct.py`, `audit_voices.py`, `remux_faststart.py`, `reset_metrics_baseline.py`, `validate_g8_8_audio_homologation.py`, `benchmark_video_models.py`, as 4 suítes de teste 100% exclusivas, limpeza dos 5 testes mistos + remoção de `pyyaml` e `google-api-python-client`/`google-auth-oauthlib`/`google-auth-httplib2` de `requirements.txt`/`pyproject.toml`. | 17 arquivos (+ 5 testes mistos limpos) | **~0,42 MiB** | **Baixo** (isolados, cada um validado por grep). |
| **Fase 3** (`v2/limpeza-fase3-fontes-nao-usadas`) — **EXECUTADA** | Remover as 5 fontes em `resource/fonts/` nunca referenciadas por `app/` ou `scripts/`: `STHeitiLight.ttc` (53,20 MiB), `MicrosoftYaHeiNormal.ttc` (18,79 MiB), `Charm-Bold.ttf`, `Charm-Regular.ttf`, `UTM Kabel KT.ttf`, ajustando `test_video.py` e `test_cli.py`. | 5 arquivos | **~72,28 MiB** | **Baixo** (nenhum pipeline de produção usa essas 5 fontes). |
| **Fase 4** (`v2/limpeza-fase4-streamlit-webui-v1`) | Mover `bootstrap_primary_and_worker` / `shutdown_worker_and_lock` para `engine_entrypoint.py`; remover `-Legacy` e `production_entrypoint.py`; remover `webui/` (19 arquivos), `webui.bat`, `webui.sh`, `version_checker.py`, `production_observability.py`, `cache_manager.py`, os 22 testes exclusivos de Streamlit, limpar imports de `webui` nos testes mistos, e remover `streamlit` e `streamlit-tour` de `requirements.txt`/`pyproject.toml`. | 48 arquivos | **~1,62 MiB** no Git (+ ~150 MiB a menos no `.venv`) | **Médio-Baixo** (requer desacoplar `production_entrypoint.py` e ajustar testes mistos). |
| **Fase 5 (Condicional — Decisão do Rico)** | Itens aprovados da **Categoria C**: (a) substituir fallback default de fonte CJK (`STHeitiMedium.ttc` + `MicrosoftYaHeiBold.ttc`) por `BeVietnamPro-Bold.ttf` (**+69,27 MiB**); (b) remover `resource/songs/output001..029.mp3` mantendo apenas `output000.mp3` (**+51,11 MiB**); (c) decidir sobre `cli.py`, `docs/auditorias/*` e Dockerfiles. | Até 35+ arquivos | **Até ~120,60 MiB adicionais** | **Depende de decisão do Rico.** |

> **Nota sobre o tamanho de `.git/objects` (`size-pack: 199.06 MiB`):** A remoção de arquivos nas Fases 1 a 5 reduz imediatamente a working tree (de **215,62 MiB** para **~18,5 MiB** se incluída a Fase 5) e acelera checkouts, backups e varreduras de disco; os blobs antigos permanecem no histórico Git (`.git/objects/pack`) a menos que no futuro seja feita uma reescrita explícita de histórico (não recomendada sem necessidade operacional).
