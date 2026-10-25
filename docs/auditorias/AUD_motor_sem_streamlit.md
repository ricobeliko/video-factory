# Auditoria Técnica: O que o Streamlit faz além de desenhar tela (Motor sem Streamlit)

> **Documento Canônico de Auditoria — Missão A (Fase V2)**
> **Status:** AUDITORIA READ-ONLY CONCLUÍDA
> **Branch Alvo:** `v2/auditoria-motor`
> **Repositório:** `https://github.com/ricobeliko/video-factory`
> **Ambiente de Análise:** DEV (`C:\Projetos\MoneyPrinterTurbo-V1`)

---

## 1. O que roda no boot ou em loop no Streamlit (além de renderizar)

Auditoria exaustiva em `webui/Main.py`, `webui/components/operator_console.py` e `webui/components/channel_factory.py`.

| # | Arquivo & Linha | Componente / Mecanismo | O que faz tecnicamente | O motor depende para produzir/publicar? | Onde deve viver sem o Streamlit |
| :-: | :--- | :--- | :--- | :-: | :--- |
| **1.1** | `webui/Main.py:10060` | `operator_console.ensure_instance_initialized()` | Adquire o lock transacional no SQLite (`instance_locks`), define papel do processo (`ROLE_PRIMARY` ou `ROLE_SECONDARY_VIEW_ONLY`), grava evento de inicialização e inicia thread de heartbeat (`_start_instance_heartbeat`, a cada 15s). | **SIM** | No bootstrap/lifespan do novo processo motor (`scripts/engine_entrypoint.py` ou lifespan de `app/asgi.py`). |
| **1.2** | `webui/Main.py:10064` | `tm.recover_interrupted_cross_posts()` | Recupera uploads interrompidos por crash/reboot no arranque do sistema, evitando que tarefas em publicação fiquem presas para sempre como "processing". | **SIM** | No startup/lifespan do motor (já chamado em `app/asgi.py:43`, mas precisa ser garantido antes de iniciar o worker). |
| **1.3** | `webui/Main.py:10071` | `operator_console.reconcile_orphaned_tasks()` | Identifica tarefas que estavam com status `processing` no momento de uma queda de energia/reboot sem worker vivo correspondente, reconciliando-as para falha ou recuperação limpa para não travar o Autopilot. | **SIM** | No startup/lifespan do motor, logo após adquirir `ROLE_PRIMARY` e antes de ligar o worker. |
| **1.4** | `webui/Main.py:7996`, `8026` | `scheduler.start_scheduler_worker(interval_seconds=30)` | Inicia a thread daemon em background `_scheduler_worker_loop`, responsável pelo loop operacional contínuo (executa agendamento de posts, coleta de analytics e ciclo autônomo). | **SIM** | No startup do motor após aquisição confirmada de `ROLE_PRIMARY`. |
| **1.5** | `webui/Main.py:9886`, `10010` | `webui_task.submit_generation(task_id, params, ...)` | Enfileira e dispara a thread de geração de vídeo do formulário manual/batch em memória via `InMemoryTaskManager(max_concurrent_tasks=1)`. | **NÃO** *(para autônomo)* / **SIM** *(para gerações manuais na UI)* | No endpoint da API V2 de geração manual (`POST /api/v2/tasks/generate`), desacoplado de Streamlit. A produção autônoma roda direto em `autonomous_production` sem passar por `webui_task`. |
| **1.6** | `webui/Main.py:10142` | `_save_runtime_config(force=False)` | Persiste em disco (`config.toml`) todas as alterações e rascunhos de formulário do Streamlit ao final de cada interação/rerun. | **NÃO** | Endpoints específicos de configuração na API V2 (`PUT/PATCH`), salvando apenas quando o operador submeter alterações deliberadamente. |
| **1.7** | `webui/Main.py:2217` | `init_log()` | Configura os sinks do Loguru e formato do console/arquivo no startup. | **NÃO** | Já configurado globalmente em `app/utils/logging_utils.py` no ASGI/Uvicorn. |
| **1.8** | `webui/Main.py:1568`, `1575` | `@st.fragment(run_every="5s" / "30s")` `_render_task_manager_entry` | Polling periódico da lista de tarefas em execução e prontas via Streamlit Fragment. | **NÃO** | Endpoint REST `GET /api/v2/tasks` consumido via polling leve pelo React frontend. |
| **1.9** | `webui/Main.py:2439` | `@st.fragment(run_every=0.5s)` `_render_task_log_stream` | Polling dos logs de geração de vídeo in-process via deque de memória em `webui_task._task_logs`. | **NÃO** | Endpoint SSE (`/api/v2/tasks/{id}/logs/stream`) ou polling HTTP GET no backend. |
| **1.10** | `webui/Main.py:8401` | `@st.fragment(run_every="30s")` `_render_publication_schedule_active` | Polling de 30s da agenda de publicação que verifica se o worker de agendamento está ativo e chama `start_scheduler_worker` se encontrar o worker inativo. | **TALVEZ** *(rede de segurança redundante)* | O motor deve garantir o worker vivo de forma determinística no processo principal, com monitoramento interno de thread/healthcheck. |
| **1.11** | `webui/Main.py:7989`, `8002`, `8011` | `scheduler.set_setting(...)` | Gravações no SQLite (`scheduler_settings`) acionadas por callbacks de checkbox (`scheduler_enabled`, `auto_publish_enabled`, `dry_run`). | **SIM** *(regras de controle)* | Endpoints REST dedicados na API V2 (`PATCH /api/v2/scheduler/settings`). |
| **1.12** | `webui/Main.py:8213`, `8237`, `8257`, `8362` | Mutações do Scheduler | Adoção manual (`adopt_tasks_into_scheduler`), planejamento manual (`plan_schedule`), limpeza (`clear_future_schedule`) e reagendamento (`reschedule_post_for_test`). | **SIM** *(quando acionadas)* | Endpoints REST de operações da fábrica na API V2. |
| **1.13** | `webui/Main.py:8380` | `scheduler.run_scheduler_cycle()` | Disparo manual de ciclo de publicação via botão de teste. | **NÃO** *(opcional/teste)* | Endpoint `POST /api/v2/scheduler/run-cycle`. |
| **1.14** | `webui/Main.py:9445` | `scheduler.save_task_platforms(task_id, assigned)` | Persiste destinos de publicação da tarefa em `task_platforms` (SQLite). | **SIM** | Centralizado em `task.py` e `autonomous_production.py` durante o fluxo de criação da tarefa. |
| **1.15** | `webui/components/operator_console.py:839`, `844`, `922`, `1082`, `1087` | `@st.fragment(run_every=...)` no Mission Control | Polling de 5s a 30s no Operator Console para atualizar cards de telemetria, tarefa ativa, fila de geração e produção autônoma. | **NÃO** | Polling HTTP GET via endpoint consolidado `GET /api/v2/system/status` pelo frontend SPA. |
| **1.16** | `webui/components/operator_console.py:1369` | `scheduler.set_channel_auto_publish_authorized(...)` | Grava flag de autorização de publicação no SQLite (`publishing_channels.auto_publish_authorized`). | **SIM** | Endpoint `PATCH /api/v2/channels/{id}/authorization` na API V2. |
| **1.17** | `webui/components/operator_console.py:1649`, `1654` | `operator_console.set_analytics_auto_collection_enabled_op(...)` | Grava toggle de coleta automática no SQLite (`autopilot_settings.auto_collection_enabled`). | **SIM** | Endpoint `PATCH /api/v2/analytics/scheduler/settings`. |
| **1.18** | `webui/components/operator_console.py:1756`, `1764` | `operator_console.set_autonomous_mode_enabled_op(...)` | Grava ativação do piloto autônomo por canal em `content_profile_settings.autonomous_mode_enabled`. | **SIM** | Endpoint `PATCH /api/v2/channels/{id}/autonomous` (já existente em `app/controllers/v2/operations.py:287`). |
| **1.19** | `webui/components/operator_console.py:1773` | `operator_console.run_autonomous_cycle_op(...)` | Disparo manual supervisionado de ciclo autônomo ("Run Cycle Now"). | **SIM** | Endpoint `POST /api/v2/factory/run-cycle` (já existente em `operations.py:102`). |
| **1.20** | `webui/components/operator_console.py:2027` | `operator_console.set_publication_copyright_status_op(...)` | Grava aprovação/rejeição manual de copyright em `tasks.copyright_status`. | **SIM** | Endpoint `POST /api/v2/tasks/{id}/copyright/approve`. |
| **1.21** | `webui/components/operator_console.py:2361`, `2414`, `2448`, `2606`, `2638` | Mutações de Clip Mode | Criação, seleção, rejeição e aprovação de segmentos de clipes em SQLite (`clip_segments`, `clip_reviews`). | **NÃO** *(formato secundário)* | Endpoints dedicados em `app/controllers/v2/review.py`. |
| **1.22** | `webui/components/channel_factory.py:447` | `save_global_voice(voice_name)` | Grava em `config.ui["voice_name"]` e persiste no `config.toml`. | **SIM** *(se voz não definida no perfil)* | Configuração persistida via API REST em tabela SQLite ou settings globais. |
| **1.23** | `webui/components/channel_factory.py:548`, `626` | `autonomous_production.set_profile_autonomous_mode_enabled(...)` | Mutações de ativação de canais no onboarding/gerenciamento de canais. | **SIM** | Endpoint `PATCH /api/v2/channels/{id}/status`. |
| **1.24** | `webui/Main.py` & `components` | Estado de negócio em `st.session_state` (`cross_post_recovery_checked`, `operator_reconciled`, `loomloom_video_quote`, `pending_generation_task_id`, rascunhos) | Variáveis voláteis de sessão do Streamlit guardando checkpoints de boot ou rascunhos de formulário. | **NÃO** *(são contingências de sessão do Streamlit)* | Flags de processo devem ser variáveis globais/singleton no Python; rascunhos de UI devem viver no client state (React/Vite). |

---

## 2. O que o backend lê de `config.ui` em produção e quem escreve hoje

Auditoria em todo o código sob `app/` que faz referência a `config.ui`.

| Parâmetro em `config.ui` | Onde o backend lê (`app/`) | O que faz no backend / impacto na produção | Quem escreve hoje | Onde deve viver sem o Streamlit |
| :--- | :--- | :--- | :--- | :--- |
| `voice_name` | `autonomous_production.py:1726, 1737, 1808, 2020`<br>`profile_manager.py:1212, 1407`<br>`app/models/schema.py:71` | Voz fallback de narração TTS para geração autônoma quando o perfil editorial não define voz própria em `content_profile_settings`. | `channel_factory.py:447` (`save_global_voice`)<br>`Main.py:10142` (`_save_runtime_config`) | No SQLite em `content_profile_settings.voice_name` (por canal) e fallback global em tabela de sistema ou `config.toml [app]`. |
| `voice_rate` | `autonomous_production.py:1826`<br>`profile_manager.py:1421` | Velocidade de fala padrão do TTS para vídeos autônomos. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.voice_rate` por perfil e fallback global. |
| `voice_volume` | `autonomous_production.py:1820`<br>`profile_manager.py:1427` | Volume padrão da faixa de voz no áudio. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.voice_volume` por perfil e fallback global. |
| `voice_mode` | `autonomous_production.py:1792, 2016` | Modo de voz padrão ("tts", "upload", "none"). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.voice_mode`. |
| `tts_server` | `autonomous_production.py:1793` | Servidor/provedor TTS padrão ("azure-tts", "openai", "edge-tts", "elevenlabs"). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.tts_server` ou `config.app["tts_server"]`. |
| `font_name` | `autonomous_production.py:1881`<br>`production_health.py:397` | Família de fonte padrão das legendas de vídeo. `production_health` valida se o arquivo de fonte existe em `resource/fonts`. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.font_name` por perfil e fallback de sistema. |
| `subtitle_position` | `autonomous_production.py:1882`<br>`app/models/schema.py:158, 304`<br>`profile_manager.py:1475` | Posição vertical da legenda ("bottom", "top", "custom"). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.position`. |
| `custom_position` | `autonomous_production.py:1895`<br>`app/models/schema.py:167` | Coordenada Y relativa (porcentagem da altura do frame, default 70.0). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.custom_position`. |
| `font_size` | `autonomous_production.py:1901`<br>`profile_manager.py:1476` | Tamanho da fonte da legenda em pixels. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.font_size`. |
| `stroke_width` | `autonomous_production.py:1913` | Largura da borda/contorno da legenda. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.stroke_width`. |
| `subtitle_background` | `autonomous_production.py:1922` | Booleano que define se desenha caixa de fundo sob a legenda. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.background`. |
| `subtitle_background_color` | `autonomous_production.py:1923` | Cor RGBA da caixa de fundo da legenda. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.background_color`. |
| `rounded_subtitle_background` | `autonomous_production.py:1925` | Booleano para cantos arredondados na caixa da legenda. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.subtitle.rounded`. |
| `video_aspect_{video_source}` | `autonomous_production.py:1842` | Proporção de tela por fonte de mídia (ex: "9:16", "16:9"). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.video_aspect`. |
| `video_fit_mode` | `autonomous_production.py:1848` | Modo de enquadramento de vídeo ("crop", "pad"). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.video_fit_mode`. |
| `video_transition_mode` | `autonomous_production.py:1859` | Modo de transição entre cenas de vídeo. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.video_transition_mode`. |
| `video_clip_duration` | `autonomous_production.py:1870` | Duração máxima por clipe visual (default 3s). | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.video_clip_duration`. |
| `video_count` | `autonomous_production.py:1875` | Quantidade de materiais/clipes a buscar por tema. | `Main.py:10142` (`_save_runtime_config`) | Em `content_profile_settings.video_count`. |
| `hide_log` | `webui_task.py:89`, `Main.py:9889, 10013` | Controla se oculta saída detalhada de log no console. | `Main.py:10142` (`_save_runtime_config`) | Flag de configuração geral em `config.app["hide_log"]`. |

> **Conclusão Crítica do Item 2:** Quase todas as leituras de `config.ui` em `autonomous_production.py` funcionam como **fallback de última instância** quando o perfil do canal não possui a respectiva chave configurada no seu JSON em `content_profile_settings`. Na arquitetura sem Streamlit, o modelo canônico por canal (`profile_manager` / `content_profile_settings`) já cobre 100% dessas configurações, tornando `config.ui` obsoleto.

---

## 3. O que assumem os scripts de produção sobre o Streamlit

Auditoria nos scripts operacionais em `scripts/`.

| Script | O que assume sobre o Streamlit | Porta assumida | Nome do Processo / Tarefa | Impacto na transição para o Motor V2 |
| :--- | :--- | :---: | :--- | :--- |
| `scripts/production_entrypoint.py` | Importa `streamlit.web.bootstrap`, converte argumentos CLI em `flag_options` do Streamlit e chama `streamlit.web.bootstrap.run(webui/Main.py, ...)` bloqueando o processo. | `8501` (default) | Processo Python hospedeiro da task `VideoFactory Production`. | Deve ser substituído por `scripts/engine_entrypoint.py` que executa exatamente o mesmo bootstrap de PRIMARY/worker, mas sobe Uvicorn com `app.asgi:app` no lugar do Streamlit. |
| `scripts/start_production.ps1` | Executa `.venv\Scripts\python.exe scripts\production_entrypoint.py` passando argumentos exclusivos do Streamlit (`--server.port=8501`, `--server.headless=true`, `--client.toolbarMode=minimal`, etc.). | `8501` | Janela de serviço ou Scheduled Task `VideoFactory Production`. | Deve apontar para o novo entrypoint do motor e passar argumentos do servidor Uvicorn/ASGI (ou parâmetros nativos do motor). |
| `scripts/start_webui_v2.ps1` | Assume que a V2 roda em porta dedicada (`8080`), que o Streamlit permanece ativo na porta `8501` ("Streamlit Fallback: 8501") e que a V2 **não** sobe worker nem disputa lock PRIMARY. | `8080` (V2)<br>`8501` (V1) | Processo Uvicorn independente com PID gravado em `storage/logs/webui_v2/webui_v2.pid`. | Na fase sem Streamlit, este script e o `start_production.ps1` convergem para um único launcher do motor unificado (servindo UI V2 e API na mesma porta). |
| `scripts/register_webui_v2_task.ps1` | Assume que a tarefa `VideoFactory Production` hospeda o nó PRIMARY na 8501 e que a tarefa `VideoFactory WebUI V2` deve rodar como secundária sem interferir na primária. | `8080` | `VideoFactory WebUI V2` (secundária)<br>`VideoFactory Production` (primária) | No modelo com motor único, existirá apenas uma Scheduled Task de produção que roda o motor (PRIMARY + Worker + Web UI V2). |
| `scripts/update_production.ps1` | Assume parâmetro `$HealthUrl = "http://127.0.0.1:8501/_stcore/health"`, esperando resposta HTTP 200 contendo a string `'ok'`. Reinicia a Scheduled Task `VideoFactory Production` e aguarda esse endpoint. | `8501` | Scheduled Task `VideoFactory Production`. | O health check de update deve passar a consultar o endpoint nativo do FastAPI: `http://127.0.0.1:<porta>/health` (HTTP 200, status `'healthy'`), já implementado em `app/asgi.py`. |
| `scripts/production_status.ps1` | Executa `app.services.production_health`. | — | Consulta banco SQLite e sistema local via Python. | Não faz chamadas HTTP para o Streamlit; continuará funcionando 100% inalterado. |

---

## 3b. O que `production_health` e `production_observability` checam que dependa do Streamlit

Auditoria nos serviços de diagnóstico passivo:

1. **`app/services/production_health.py`:**
   - **Zero dependência direta de rede do Streamlit:** Não faz chamadas HTTP para a porta 8501 nem importa módulos do Streamlit.
   - **Dependência indireta do nó PRIMARY e do Worker:**
     - Em `production_health.py:74-92`, consulta `operator_console.get_instance_info()`. Se a instância local for `ROLE_PRIMARY`, avalia se a thread do worker está viva via `scheduler.get_worker_health()`.
     - Em `production_health.py:183-185`, se `instance_role == ROLE_PRIMARY` e a thread do worker estiver inativa, classifica a saúde do scheduler como `DEGRADED` ("Thread do scheduler worker inativa na instância primária").
     - Se o Streamlit for desligado sem que o novo processo motor assuma o lock PRIMARY e ligue o worker, o `production_health` reportará status degradado.
   - **Dependência de `config.ui["font_name"]`:**
     - Em `production_health.py:397`, lê `config.ui.get("font_name")` para checar se o arquivo `.ttf` existe na pasta `resource/fonts`.
2. **`app/services/production_observability.py`:**
   - **Zero dependência do Streamlit:** O módulo é estritamente passivo e abre o SQLite em modo somente leitura (`mode=ro`).
   - Avalia apenas tabelas do SQLite (`operator_heartbeats`, `instance_locks`, `scheduled_posts`, `tasks`, `content_profiles`) e filesystem.
   - Não verifica portas, processos Streamlit ou páginas web.

---

## 4. Evidência no código: PRIMARY vs SECONDARY_VIEW_ONLY e viabilidade do FastAPI

### 4.1. Quando o Streamlit já é PRIMARY, o processo FastAPI vira SECONDARY_VIEW_ONLY e retorna 403?

**SIM. Comprovado pelas seguintes evidências no código:**

1. **Detecção do Lock em `operator_console.py`:**
   - O Streamlit adquire o lock no boot via `production_entrypoint.py:88` chamando `operator_console.ensure_instance_initialized()`. Ele insere seu PID e inicia a thread de heartbeat que atualiza `instance_locks.last_heartbeat` a cada 15 segundos (`operator_console.py:590-608`).
   - Quando o processo FastAPI sobe, qualquer rota que avalia permissão invoca `operator_console.is_primary_instance()` (`operator_console.py:569-574`), que por sua vez executa `ensure_instance_initialized()` sob demanda.
   - O método `acquire_instance_lock()` (`operator_console.py:465-495`) consulta `instance_locks` e detecta que já existe um PRIMARY ativo com heartbeat fresco (< 45 segundos).
   - O código salta para `operator_console._enter_view_only(...)` (`operator_console.py:507-534`), gravando na memória do processo FastAPI:
     ```python
     _current_role = ROLE_SECONDARY_VIEW_ONLY
     _instance_initialized = True
     ```
2. **Rejeição com HTTP 403 nas Mutações da API V2:**
   - Todas as rotas de alteração de estado no FastAPI (`app/controllers/v2/operations.py`) invocam comandos que chamam internamente `operator_console.require_primary_instance()` (`operator_console.py:577-586`):
     ```python
     def require_primary_instance(db_path: Optional[str] = None) -> None:
         if not is_primary_instance(db_path=db_path):
             raise PermissionError("Operação bloqueada: Esta instância está operando em modo VIEW ONLY...")
     ```
   - Os handlers das rotas capturam `PermissionError` e levantam `HttpException` com status HTTP 403:
     - `POST /api/v2/factory/pause` (`operations.py:39-44`): HTTP 403.
     - `POST /api/v2/factory/resume` (`operations.py:71-76`): HTTP 403.
     - `POST /api/v2/factory/run-cycle` (`operations.py:126-131`): HTTP 403.
     - `PATCH /api/v2/channels/{id}/autonomous` (`operations.py:355-360`): HTTP 403.
     - `PATCH /api/v2/channels/{id}/growth-mode` (`operations.py:468-473`): HTTP 403.
     - `PATCH /api/v2/channels/{id}/target-stock` (`operations.py:545-550`): HTTP 403.
   - As rotas de leitura (`GET /api/v2/...`) não chamam `require_primary_instance()` e respondem HTTP 200 normalmente.

### 4.2. E se o FastAPI fosse o único processo, conseguiria ser PRIMARY e subir o worker?

1. **Assumir `ROLE_PRIMARY`:** **SIM.**
   - Na ausência do Streamlit, `acquire_instance_lock()` encontraria a tabela `instance_locks` vazia ou com heartbeat expirado (> 45s), adquirindo `ROLE_PRIMARY` com sucesso e ativando a thread de heartbeat do processo FastAPI.
2. **Subir o Worker:** **NÃO (no código atual).**
   - Atualmente, **nenhuma linha** de `app/asgi.py`, `app/router.py` ou `app/controllers/v2/` chama `scheduler.start_scheduler_worker()`.
   - Como documentado no item 2 do handoff (`docs/PROJECT_HANDOFF.md:207`): *"O processo FastAPI (main.py -> app.asgi:app) não inicializa workers de scheduler (scheduler.start_scheduler_worker() nunca é chamado)"*.
   - Portanto, se o FastAPI rodasse sozinho hoje, ele se tornaria PRIMARY, mas o `SchedulerExecutionWorker` **permaneceria desligado**, interrompendo a produção autônoma de vídeos e a publicação de posts.
   - Além disso, `operator_console.reconcile_orphaned_tasks()` (necessário para resgate após queda de energia) hoje só existe no topo de `webui/Main.py:10071` e não rodaria no boot do FastAPI.

---

## 5. Proposta arquitetural: Desenho mínimo do Motor sem Streamlit

Sem escrever código de implementação nesta fase, o desenho mínimo do processo "motor" unificado é delineado a seguir.

### 5.1. Onde hospedar o motor: `scripts/engine_entrypoint.py` vs Lifespan de `app/asgi.py`

**Recomendação Técnica:** **`scripts/engine_entrypoint.py` como processo orquestrador CLI** (equivalente direto e evolução natural de `production_entrypoint.py`), utilizando o lifespan do `app/asgi.py` para gerenciamento de contexto ASGI.

- **Por que `scripts/engine_entrypoint.py`?**
  - Mantém a mesma interface de processo adotada pelo Windows Task Scheduler e pelos scripts PowerShell (`start_production.ps1`).
  - Permite encerramento determinístico com controle de exceção de baixo nível (fail-closed antes de abrir portas de rede).
  - Executa o Uvicorn de forma programática (`uvicorn.run(...)`) servindo `app.asgi:app` no mesmo interpretador.

### 5.2. Ordem de Inicialização (Bootstrap Determinístico)

1. **Carregamento de Ambiente & Logging:**
   - Adiciona raiz do projeto ao `sys.path`.
   - Inicializa Loguru com formatação operacional persistente.
2. **Aquisição de Lock PRIMARY (Fail-Closed):**
   - Chama `operator_console.ensure_instance_initialized(node_name="ProductionEngine")`.
   - Se retornar `ROLE_SECONDARY_VIEW_ONLY`: emite alerta e aborta com exit code != 0 (ou sobe sem worker se explicitamente configurado como réplica).
3. **Rotinas de Recuperação de Boot (Crash Recovery):**
   - Chama `task.recover_interrupted_cross_posts()` (desbloqueia uploads pendentes de rede).
   - Chama `operator_console.reconcile_orphaned_tasks()` (resgata tarefas órfãs de quedas de energia).
4. **Inicialização do Worker do Scheduler:**
   - Chama `scheduler.start_scheduler_worker(interval_seconds=30)`.
   - Verifica `scheduler.is_worker_alive()`; se falso, aborta imediatamente com `RuntimeError`.
5. **Servidor Web & API Unificados (Uvicorn):**
   - Inicia Uvicorn servindo `app.asgi:app` na porta configurada (ex: `8080` ou porta unificada `8501`).
   - O FastAPI serve simultaneamente:
     - As rotas REST operacionais (`/api/v2/...`);
     - Os endpoints de saúde (`/health` e `/api/v2/health`);
     - O frontend compilado da Web UI V2 (`webui-v2/dist/`) na raiz `/`.

### 5.3. Ordem de Encerramento Limpo (Graceful Shutdown)

Executado no bloco `finally` do entrypoint (ou no evento de shutdown do ASGI e tratador de sinais `SIGINT`/`SIGTERM`):

1. **Interrupção de Requisições:** Uvicorn encerra o recebimento de novos pacotes HTTP e conclui requisições em trânsito.
2. **Parada do Worker:** Executa `scheduler.stop_scheduler_worker()` (espera o tick atual do ciclo finalizar, evitando cortar geração de vídeo no meio).
3. **Liberação do Lock de Instância:** Executa `operator_console.release_instance_lock()`, limpando o registro em `instance_locks` e parando a thread de heartbeat.
4. **Registro de Auditoria:** Grava evento de shutdown gracioso no SQLite (`operator_events`).

### 5.4. O que reaproveitar de `scripts/production_entrypoint.py`

- As funções estruturais já homologadas e testadas:
  - `bootstrap_primary_and_worker()`: validação de papel e startup do scheduler worker.
  - `shutdown_worker_and_lock()`: parada segura e liberação de lock.
  - `parse_args()`: mapeamento de flags CLI (`--server.port`, `--server.address`).
- **O que descartar:**
  - Importação de `streamlit.web.bootstrap`.
  - Flags proprietárias do Streamlit (`--client.toolbarMode`, `--browser.gatherUsageStats`, `--server.enableCORS`).
  - Execução monolítica de `webui/Main.py`.

### 5.5. Riscos Mapeados: Duas instâncias PRIMARY ou Dois Workers Concorrentes

| Risco Crítico | Causa Raiz | Impacto Operacional | Mitigação Arquitetural Obrigatória |
| :--- | :--- | :--- | :--- |
| **Dois Workers Concorrentes** | Streamlit legado e Motor V2 rodando em paralelo sem exclusão mútua. | Dois loops de 30s chamando `run_scheduler_cycle` e `autonomous_production` simultaneamente: **duplicação de posts no YouTube/TikTok**, **estouro de cotas diárias**, e **duas gerações paralelas disputando a GPU/FFmpeg**. | O worker **só pode ser iniciado** após confirmação estrita de `ROLE_PRIMARY` concedido pelo lock SQLite. Em `_scheduler_worker_loop`, verificar `operator_console.is_primary_instance()` a cada tick. |
| **Conflito de Porta de Rede** | Tentativa de bind na mesma porta (ex.: duas aplicações tentando escutar na 8080 ou 8501). | Falha no arranque do Uvicorn com `OSError: [Errno 10048] Address already in use`. | Checagem de socket prévia nos scripts PowerShell (`Test-NetConnection` / socket connect) antes do boot com `-KillExisting` explícito se autorizado. |
| **Lock Stale / Órfão pós-queda** | Queda abrupta de energia impede a execução do `shutdown_worker_and_lock`. | Nova instância do motor não sobe por acreditar que a anterior ainda está rodando. | Já mitigado em `operator_console.py`: locks com heartbeat sem atualização há mais de 45 segundos são considerados órfãos (stale) e sobrescritos com segurança pelo novo processo. |
| **Race Condition no Bootstrap** | Dois processos arrancando no mesmo milissegundo disputando `acquire_instance_lock`. | Ambos acreditarem ser primários. | Lock transacional com SQLite `BEGIN IMMEDIATE` em `operator_console.py` já garante atomicidade e exclusão mútua a nível de banco. |
