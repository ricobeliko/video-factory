# Análise e Unificação do Status Operacional do Canal (V2)

> **Missão**: `v2/status-canal-analise` (a partir de `v2/base` = `9fb3ecd41a9d369189ef1ffa6fce488a9b4096be`)
> **Escopo**: Somente análise de código e proposta arquitetural (nenhuma alteração em código de produção).
> **Princípio regente**: *"Um controle = um lugar. Uma informação = uma fonte."* (`docs/v2/REGRAS_DAS_MISSOES.md`)

---

## 1. Os 5 Cálculos Atuais de Status do Canal

Hoje o backend calcula ou expõe o estado operacional de um canal em **5 lugares distintos**, cada um com seu próprio vocabulário, suas próprias fontes de dados e sua própria ordem de prioridade.

---

### 1.1. `operator_console.get_fleet_summary` (Frota)

- **Arquivo e linhas**: `app/services/operator_console.py:3954-4297` (regra de decisão do `status` nas linhas `4209-4246`).
- **Endpoint que expõe**: `GET /api/v2/fleet/summary` (`app/controllers/v2/fleet.py:13-25`).
- **Quem consome no `webui-v2`**:
  - `webui-v2/src/api.js:32` (`getFleetSummary`)
  - `webui-v2/src/components/Fleet/FleetView.jsx` (tabela principal da tela **Frota**)
  - `webui-v2/src/components/Fleet/fleetLogic.js:7-28` (`STATUS_META`, `SORT_WEIGHT`, `computeTotals`)
- **Entradas que lê**:
  - **Tabelas SQLite** (`state.db` via `_get_db_connection()`):
    - `content_profiles` (`profile_id`, `name`, `is_active`, `params_json`)
    - `autopilot_settings` (mapa completo `key -> value`: `autonomous_state[:pid]`, `autonomous_message[:pid]`, `autonomous_last_error[:pid]`, `autonomous_consecutive_rejections[:pid]`, `autonomous_max_consecutive_rejections`, `scheduler_interval_minutes`, `last_scheduler_run_at`)
    - `scheduled_posts` (próximo post `status IN ('pending','ready')` por canal e contagem de `status = 'failed'` nas últimas 24h)
    - `publication_events` (`status = 'success'` desde meia-noite UTC para `published_today`, e `status = 'failed'` nas últimas 24h)
    - `tasks` + `task_profiles` (`state IN (0, 1)` para `pending_proc` e `state = 3` nas últimas 24h para falhas)
  - **Memória (`sm.state`)**: tarefas em memória (`state IN (0, 1)` para `pending_proc` e `state == 3` nas últimas 24h, deduplicadas por `task_id`).
  - **Funções canônicas** (após `v2/fontes-unicas`):
    - `get_factory_state()` (`app/services/operator_console.py:3912`)
    - `profile_manager.get_generation_profile_context(pid)` (para `growth_mode`, `target_ready_stock`, `max_generations_24h`, `max_attempts_24h`, `daily_publish_limit`)
    - `autonomous_production.is_profile_autonomous_mode_enabled(pid)`
    - `get_canonical_ready_stock(pid)` (sem fallback: retorna `None` em caso de falha de leitura)
    - `autonomous_production.count_generations_in_last_24h(pid)`
    - `autonomous_production.count_generation_attempts_in_last_24h(pid)`
- **Vocabulário exato de saída**:
  - Campo `status`: `{"paused", "blocked", "running", "attention", "ok"}` (strings em minúsculas).
  - Campo complementar `issue`: `Optional[str]` em português explicando o motivo (ou `None` quando `status in ("running", "ok")`).
  - Na UI (`fleetLogic.js`), traduzido para os rótulos: `"Pausado"`, `"Bloqueado"`, `"Gerando"`, `"Atenção"`, `"OK"`.
- **Regras de decisão em ordem exata de prioridade** (`operator_console.py:4210-4245`):
  1. `is_factory_paused` (`factory_state in ("PAUSED", "EMERGENCY_PAUSED")`) $\rightarrow$ `status = "paused"`, `issue = "Fábrica pausada pelo operador"`
  2. `not is_active` (`content_profiles.is_active == 0`) $\rightarrow$ `status = "paused"`, `issue = "Canal desativado pelo operador"`
  3. `not autonomous_enabled` (`is_profile_autonomous_mode_enabled(pid) == False`) $\rightarrow$ `status = "paused"`, `issue = "Modo autônomo desligado"`
  4. `consec_rejections >= max_rejections` $\rightarrow$ `status = "blocked"`, `issue = f"Disjuntor acionado: {consec_rejections} rejeições consecutivas"`
  5. `auto_state in ("blocked", "error")` $\rightarrow$ `status = "blocked"`, `issue = auto_msg or auto_err or "Produção autônoma bloqueada"`
  6. `auto_state in ("generating", "planning") or pending_proc > 0` $\rightarrow$ `status = "running"`, `issue = None`
  7. `auto_state == "cooldown"` $\rightarrow$ `status = "attention"`, `issue = "Em período de espera (cooldown)"`
  8. `ready_stock is None` $\rightarrow$ `status = "attention"`, `issue = "Estoque desconhecido (falha na leitura)"`
  9. `ready_stock == 0` $\rightarrow$ `status = "attention"`, `issue = "Estoque esgotado (0 vídeos prontos)"`
  10. `ready_stock < target_stock` $\rightarrow$ `status = "attention"`, `issue = f"Estoque abaixo da meta ({ready_stock}/{target_stock})"`
  11. `failed_count > 0` (soma de falhas nas últimas 24h em `scheduled_posts`, `publication_events` e `tasks`) $\rightarrow$ `status = "attention"`, `issue = f"Atenção: {failed_count} falha(s) registrada(s)"`
  12. Caso contrário $\rightarrow$ `status = "ok"`, `issue = None`

---

### 1.2. `operator_console.get_live_execution_overview` (Factory Live / Oficina / Gaveta)

- **Arquivo e linhas**: `app/services/operator_console.py:3222-3665` (cálculo por canal nas linhas `3268-3609`; tarefas órfãs `"Sem Canal"` nas linhas `3612-3651`).
- **Endpoint que expõe**: `GET /api/v2/executions/live` (`app/controllers/v2/operations.py:701-708`).
- **Quem consome no `webui-v2`**:
  - `webui-v2/src/api.js:24` (`getLiveExecutions`)
  - `webui-v2/src/App.jsx` (polling global de `liveData`, alimentando a tela **Factory Live** e a gaveta lateral)
  - `webui-v2/src/components/FactoryLive/ChannelCard.jsx` (card do canal na tela Factory Live)
  - `webui-v2/src/components/FactoryLive/FactoryLiveGraph.jsx` (grafo de pipeline por canal)
  - `webui-v2/src/components/ExecutionDrawer/ExecutionDrawer.jsx` (gaveta lateral de detalhes de execução do canal)
  - `webui-v2/src/components/Workshop/Workshop.jsx` (aba Oficina)
- **Entradas que lê**:
  - `profile_manager.list_profiles()`, `profile_manager.list_channels()`
  - `autonomous_production.get_autonomous_status(pid)` (`enabled`, `state`, `message`, `current_task_id`, `waiting_task_id`)
  - `webui_task.get_active_task_ids()`, `sm.state.get_task(tid)`, `sm.state.get_all_tasks(page=1, page_size=30)`
  - `get_canonical_ready_stock(pid)` (usado apenas para preencher `ready_stock` numérico no retorno; **não** entra no cálculo do `status`!)
  - **Tabelas SQLite**:
    - `scheduled_posts` (`WHERE profile_id = ? AND status IN ('pending', 'failed', 'ready') ORDER BY scheduled_for ASC, updated_at DESC LIMIT 1`)
    - `publication_events` (`WHERE task_id = ? AND status = 'success' LIMIT 1`)
    - `task_profiles` (para mapear `task_id -> profile_id` e descobrir tarefas sem canal)
- **Vocabulário exato de saída**:
  - Campo `status` (tanto em `channel["status"]` quanto em `channel["execution"]["status"]`):
    `{"RUNNING", "FAILED", "WAITING", "SUCCESS", "RETRYING", "SCHEDULED", "BLOCKED", "IDLE"}` (strings em MAIÚSCULAS).
  - Campo complementar `pipeline_stage`: `{"SCRIPT", "VOICE_BGM", "MEDIA", "SUBTITLES", "RENDER", "QUALITY_GATE", "READY_STOCK", "SCHEDULER", "PUBLISHER", "YOUTUBE", "IDLE"}`.
- **Regras de decisão em ordem exata de prioridade** (`operator_console.py:3308-3609`):
  1. **Se existe tarefa de geração ativa (`current_task_id` ou tarefa `PROCESSING` em `webui_task`/`sm.state`)**:
     - `t_state == TASK_STATE_PROCESSING (1)` $\rightarrow$ `status = "RUNNING"` (com `pipeline_stage` derivado do progresso/mensagem da tarefa: `SCRIPT`, `VOICE_BGM`, `MEDIA`, `SUBTITLES`, `RENDER`, `QUALITY_GATE`)
     - `t_state == TASK_STATE_FAILED (3)` $\rightarrow$ `status = "FAILED"`, `pipeline_stage = _map_task_to_stage(...)`
     - `t_state == TASK_STATE_COMPLETE (2)` $\rightarrow$ `status = "WAITING"`, `pipeline_stage = "READY_STOCK"`
     - Qualquer outro `t_state` $\rightarrow$ `status = "WAITING"`
  2. **Senão, se existe `waiting_task_id` no `autonomous_status`**:
     - $\rightarrow$ `status = "WAITING"`, `pipeline_stage = "READY_STOCK"`
  3. **Senão, se existe linha em `scheduled_posts` com `status IN ('pending', 'failed', 'ready')`**:
     - Se `publication_events` já tem `status = 'success'` para esse `task_id` $\rightarrow$ `status = "SUCCESS"`, `pipeline_stage = "YOUTUBE"`
     - Senão, se `attempts > 0` $\rightarrow$ `status = "RETRYING"`, `pipeline_stage = "PUBLISHER"`
     - Senão $\rightarrow$ `status = "SCHEDULED"`, `pipeline_stage = "SCHEDULER"`
  4. **Senão (quando `execution is None`)**:
     - `auto_state == "blocked"` $\rightarrow$ `status = "BLOCKED"`, `pipeline_stage = "IDLE"`
     - `auto_state == "cooldown"` $\rightarrow$ `status = "WAITING"`, `pipeline_stage = "IDLE"`
     - `not auto_enabled or auto_state == "disabled"` $\rightarrow$ `status = "IDLE"`, `pipeline_stage = "IDLE"`
     - Caso contrário $\rightarrow$ `status = "IDLE"`, `pipeline_stage = "IDLE"`
  5. **Pseudo-canal `"Sem Canal"` (`id = "unassigned"`)**:
     - Criado dinamicamente se houver tarefa ativa sem `profile_id` em `task_profiles`, sempre com `status = "RUNNING"`.

---

### 1.3. `operator_console.get_profile_operations_overview` + `GET /api/v2/channels` e `GET /api/v2/profiles` (Sistema)

- **Arquivo e linhas**:
  - `app/services/operator_console.py:1399-1475` (`get_profile_operations_overview`)
  - `app/controllers/v2/operations.py:174-224` (`list_profiles` em `/api/v2/profiles` e `get_channels_overview` em `/api/v2/channels`)
- **Quem consome no `webui-v2`**:
  - `webui-v2/src/api.js:35` (`getChannelsOverview` $\rightarrow$ `GET /api/v2/channels`, usado em `webui-v2/src/components/System/SystemView.jsx:62`)
  - `webui-v2/src/api.js:115` (`getProfiles` $\rightarrow$ `GET /api/v2/profiles`)
- **Entradas que lê**:
  - `profile_manager.list_profiles()`, `profile_manager.list_channels()`, `profile_manager.get_active_profile_id()`, `profile_manager.get_profile_settings(pid)`
  - `get_canonical_ready_stock(pid)` (com `int(get_canonical_ready_stock(pid) or 0)` — **atenção**: converte `None` em `0` na linha `1464`!)
  - `autonomous_production.is_profile_autonomous_mode_enabled(pid)`
  - `autonomous_production.get_target_ready_stock(pid)`
  - **Tabelas SQLite**: `scheduled_posts` (`GROUP BY profile_id, status`) e `task_profiles` (`task_id, profile_id`)
  - **Memória**: `sm.state.get_all_tasks(page=1, page_size=200)` (conta `pending_processing` para `state in (0, 1)` e `failed` para `state == 3` apenas nas 200 tarefas mais recentes em memória, sem janela de 24h)
- **Vocabulário exato de saída**:
  - **Não retorna campo `status` unificado!**
  - Expõe flags e contadores soltos:
    - `is_active: bool` (se `profile.is_active` no banco é verdadeiro)
    - `is_active_profile: bool` (se é o perfil selecionado como ativo na sessão legada)
    - `autonomous_enabled: bool` (apenas em `/api/v2/channels`)
    - `growth_mode: str` (`"WARMUP"` | `"SCALE"`, apenas em `/api/v2/channels`)
    - `ready_stock: int` (onde erro de leitura `None` vira `0`), `target_stock: int`, `pending_processing: int`, `scheduled: int`, `published: int`, `failed: int`, `cancelled: int`, `channels_count: int`, `channels_enabled: int`.
- **Regras de decisão**:
  - Como não há `status` consolidado, a tela `SystemView.jsx` exibe apenas `"SIM (Ativo)"` / `"NÃO (Desligado)"` baseado em `autonomous_enabled` e o badge `WARMUP`/`SCALE`, sem informar ao operador se o canal está bloqueado por disjuntor, pausado pela fábrica ou com estoque zerado.

---

### 1.4. `operations.get_profile_status` + `autonomous_production.get_autonomous_status` (Status Autônomo do Perfil)

- **Arquivo e linhas**:
  - `app/controllers/v2/operations.py:226-256` (`get_profile_status`, exposto em `GET /api/v2/profiles/{profile_id}/status`)
  - `app/services/autonomous_production.py:739-851` (`get_autonomous_status`)
- **Quem consome**:
  - `webui-v2/src/api.js:116` (`getProfileStatus` — declarado no cliente HTTP, atualmente sem consumidor visual direto nas telas React, mas testado em `test/services/test_api_v2_readonly.py`)
  - Chamado internamente por `get_live_execution_overview` (`operator_console.py:3284`) e pelo console V1 (`webui/components/operator_console_ReadOnly.py`).
- **Entradas que lê**:
  - `profile_manager.get_profile(profile_id)` e `profile_manager.get_generation_profile_context(target_profile)`
  - `is_profile_autonomous_mode_enabled(target_profile)`
  - `scheduler_service.is_scheduler_enabled()`
  - `autopilot_settings` via `_get_cycle_setting`: `autonomous_state[:pid]`, `autonomous_message[:pid]`, `autonomous_current_task_id[:pid]`, `autonomous_waiting_task_id[:pid]`, `autonomous_last_check_at[:pid]`, `autonomous_last_action_at[:pid]`, `autonomous_last_error[:pid]`, `autonomous_cooldown_until[:pid]`, `autonomous_consecutive_rejections[:pid]`
  - `get_autonomous_ready_stock(target_profile)` (que delega para `get_canonical_ready_stock`, mas com `or 0`, ocultando `None`!)
  - `count_generations_in_last_24h(target_profile)`, `count_generation_attempts_in_last_24h(target_profile)`
  - `get_global_cost_guard_status()`
- **Vocabulário exato de saída**:
  - Campo `autonomous_status.state`:
    `{"disabled", "idle", "planning", "generating", "reviewing", "scheduling", "waiting_schedule", "cooldown", "blocked", "error"}` (10 estados da máquina interna do loop autônomo em minúsculas).
  - Campos booleanos adicionais: `enabled: bool`, `is_below_target: bool`, `global_cost_guard.blocked: bool`.
- **Regras de decisão em ordem exata de prioridade** (`autonomous_production.py:749-755`):
  1. `enabled = is_profile_autonomous_mode_enabled(target_profile)`
  2. Lê `state` persistido na tabela `autopilot_settings` (`autonomous_state:{pid}`), usando como fallback `"disabled"` se `not enabled` ou `"idle"` se `enabled`.
  3. `if not enabled and not is_sched and state != STATE_BLOCKED: state = STATE_DISABLED`
  - **Falha lógica importante na linha 753**: Como em produção `is_sched` (`scheduler_enabled`) é `True`, a condição `not enabled and not is_sched` é **falsa**! Assim, se um canal tinha `autonomous_state:{pid} = "waiting_schedule"`, `"idle"` ou `"error"` gravado no SQLite antes de o operador desligar o modo autônomo do canal (`enabled = False`), `get_autonomous_status` **continua retornando o `state` antigo** em vez de `"disabled"`. Além disso, essa função não consulta `get_factory_state()` (`PAUSED`) nem `profile.is_active`!

---

### 1.5. `production_diagnostics.get_diagnostics_overview` (Diagnóstico — branch `v2/diagnostico`)

- **Arquivo e linhas**: `app/services/production_diagnostics.py:205-1201` na branch `v2/diagnostico` (cálculo do `status` final do canal nas linhas `1140-1155`; detectores nas linhas `556-1091`).
- **Endpoint que expõe**: `GET /api/v2/diagnostics/overview` (`app/controllers/v2/diagnostics.py:15-25` na branch `v2/diagnostico`).
- **Quem consome no `webui-v2`**:
  - `webui-v2/src/api.js` (`getDiagnosticsOverview` na branch `v2/diagnostico`)
  - `webui-v2/src/components/Diagnostics/DiagnosticsView.jsx`
  - `webui-v2/src/components/Diagnostics/diagnosticsLogic.js:11-17` (`STATUS_META`)
- **Entradas que lê**:
  - Conexão SQLite somente-leitura (`mode=ro`) lendo: `instance_locks`, `autopilot_settings`, `content_profiles`, `task_profiles` (24h), `scheduled_posts`, `monetization_safety` (24h), `content_quality_scores` (24h), `operational_events` (24h).
  - Funções de `autonomous_production`: `get_global_max_attempts_24h`, `count_all_profiles_attempts_24h`, `get_global_max_generations_24h`, `count_all_profiles_generations_24h`, `get_profile_growth_mode`, `is_profile_autonomous_mode_enabled`, `get_max_generations_24h`, `count_generations_in_last_24h`, `get_max_attempts_24h`, `count_generation_attempts_in_last_24h`, `get_consecutive_rejections`.
  - Função de `operator_console`: `get_canonical_ready_stock(cid)`.
  - **Bug de leitura na linha 531-532**: só chama `is_profile_autonomous_mode_enabled(cid)` se a chave literal `f"autonomous_mode_enabled:{cid}"` existir em `autopilot_settings`; caso contrário, faz `autonomous_enabled = is_factory_enabled` (`True`), divergindo de `is_profile_autonomous_mode_enabled(cid)` que retorna `False` por padrão para canais secundários sem chave explícita no banco!
- **Vocabulário exato de saída**:
  - Campo `status`: `{"PARADO", "PAUSADO", "ATENCAO", "OK", "UNKNOWN"}` (MAIÚSCULAS em português, sem acento).
  - Na UI (`diagnosticsLogic.js`), traduzido para os rótulos: `"Parado"`, `"Pausado"`, `"Atenção"`, `"Normal"`, `"Desconhecido"`.
- **Regras de decisão em ordem exata de prioridade** (`production_diagnostics.py:1142-1155`):
  1. `any(d["severity"] == "critical" for d in diagnoses) or factory_state == "ERROR"` $\rightarrow$ `"PARADO"`
     *(onde `critical` dispara em: `TASK_STUCK_AFTER_RENDER`, `FALSE_INTERRUPTION_LIKELY`, `REJECTION_STREAK` [3+ rejeições seguidas pelo mesmo motivo], `NO_GENERATION_GAP` [sem geração há $\ge 12\text{h}$ e `stock == 0`], `FACTORY_PAUSED_OR_ERROR` [se `ERROR`], `REJECTION_BREAKER` [`cr_used >= cr_limit`], `GLOBAL_COST_GUARD` [`ratio >= 1.0`])*
  2. `is_factory_paused or not is_channel_active or autonomous_enabled is False` $\rightarrow$ `"PAUSADO"`
  3. `any(d["severity"] == "warning" for d in diagnoses)` $\rightarrow$ `"ATENCAO"`
     *(onde `warning` dispara em: `NO_GENERATION_GAP` [sem geração há $\ge 6\text{h}$ e `stock < target`], `INVALID_TOPIC`, `APPROVED_CAP_EXCEEDED` [`app_used > app_cap`], `REJECTION_BREAKER` [`cr_used >= 50%`], `GLOBAL_COST_GUARD` [`ratio >= 80%`], `GENERATION_FAILURE_STREAK` [3+ `generation_failed` seguidos])*
  4. `stock_status == "UNKNOWN"` (`ready_stock is None`) $\rightarrow$ `"ATENCAO"`
  5. `any(d["severity"] == "info" for d in diagnoses) or len(diagnoses) == 0` $\rightarrow$ `"OK"`
     *(onde `info` inclui: `THROTTLED_NORMAL`, `AUTONOMOUS_DISABLED`, `DAILY_APPROVED_CAP_REACHED`, `DAILY_ATTEMPT_CAP_REACHED`)*
  6. Caso contrário $\rightarrow$ `"UNKNOWN"`

---

## 2. Tabela de Conflitos entre os 5 Cálculos

A tabela abaixo mostra situações reais de operação (incluindo os 5 canais da frota de produção) em que os 5 cálculos respondem coisas diferentes para o **mesmo canal no mesmo instante**:

| # | Situação Real / Canal de Referência | 1. `get_fleet_summary` (Frota) | 2. `get_live_execution_overview` (Factory Live) | 3. `get_profile_operations_overview` (`/channels` - Sistema) | 4. `get_autonomous_status` (`/profiles/{id}/status`) | 5. `get_diagnostics_overview` (Diagnóstico) | Por que conflitam? |
|---|---|---|---|---|---|---|---|
| **C1** | **Canal com autônomo desligado e estoque cheio (`39/10`), mas com 1 post agendado no scheduler**<br>*(Caso real: **Dose Diária de Escolhas**)* | `"paused"`<br>*(Modo autônomo desligado)* | `"SCHEDULED"`<br>*(ou `"SUCCESS"` se o último post já publicou)* | `is_active: true`,<br>`autonomous_enabled: false`<br>*(sem campo `status`)* | `"disabled"`<br>*(ou estado antigo se `autonomous_state:{id}` ficou sujo com `scheduler_enabled=true`)* | `"PAUSADO"`<br>*(ou `"PARADO"` se o Global Cost Guard da fábrica bater 100%!)* | O Factory Live olha primeiro para `scheduled_posts` antes de checar se o autônomo está desligado; já o Diagnóstico roda detectores `critical` globais antes de checar `autonomous_enabled=False`. |
| **C2** | **Canal pausado/desligado de propósito pelo operador após 3 rejeições ou falha anterior**<br>*(Caso real: **Dose Diária de GTA VI**)* | `"paused"`<br>*(Modo autônomo desligado / Canal desativado)* | `"IDLE"`<br>*(ou `"BLOCKED"` se `auto_state` ficou gravado como `"blocked"`)* | `autonomous_enabled: false` | `"blocked"` ou `"disabled"` | **`"PARADO"`** (Crítico!)<br>*(ou `"OK"` se não tinha chave explícita no banco e caiu no bug do default `True`!)* | Em `get_fleet_summary`, `paused` tem prioridade máxima (prioridades 1-3). No Diagnóstico, `PARADO` (`critical`: `REJECTION_STREAK`, `REJECTION_BREAKER`, `TASK_STUCK`) tem prioridade **acima** de `PAUSADO`, alarmando canal desligado de propósito. |
| **C3** | **Canal em `SCALE` com teto diário de aprovações atingido (`10/10` em 24h), estoque `2/3` (abaixo da meta) e 1 post agendado**<br>*(Caso real: **Quiz_Quiz**)* | **`"attention"`**<br>*(Estoque abaixo da meta (2/3))* | **`"SCHEDULED"`** | `ready_stock: 2`,<br>`target_stock: 3`,<br>`autonomous_enabled: true` | `state: "idle"`,<br>`is_below_target: true` | **`"OK"`**<br>*(Com info `DAILY_APPROVED_CAP_REACHED`, pois `gap < 6h` não dispara warning)* | A Frota marca `"attention"` sempre que `ready_stock < target_stock`, mesmo quando o canal **não pode gerar mais hoje** porque já bateu a cota diária `10/10` (`DAILY_APPROVED_CAP_REACHED`). O Diagnóstico considera isso `"OK"` (esperado). |
| **C4** | **Canal em `WARMUP` com limite diário de aprovações atingido (`2/2` em 24h) e estoque `1/3`**<br>*(Caso real: **Dose Diária de Histórias e Mistério**)* | **`"attention"`**<br>*(Estoque abaixo da meta (1/3))* | `"IDLE"` ou `"SCHEDULED"` | `growth_mode: "WARMUP"`,<br>`ready_stock: 1`,<br>`target_stock: 3` | `state: "idle"`,<br>`is_below_target: true` | **`"OK"`**<br>*(Info `DAILY_APPROVED_CAP_REACHED`: cota 2/2 atingida)* | Mesmo conflito: a Frota acusa problema (`"attention"`) num canal em Warmup que já cumpriu 100% da sua meta diária (`2/2`) e está aguardando o dia seguinte por regra de negócio. |
| **C5** | **Canal principal gerando vídeo ativamente agora, com estoque `3/3`, mas teve 1 falha de tarefa há 5 horas**<br>*(Caso real: **Dose Diária De Internet**)* | **`"running"`**<br>*(Gerando)* | **`"RUNNING"`**<br>*(Stage: `RENDER`, etc.)* | `pending_processing: 1`,<br>`failed: 1` | `state: "generating"` | **`"OK"`** (ou **`"ATENCAO"`** se teve 3 falhas seguidas)<br>*(Não existe estado `"GERANDO"` no Diagnóstico!)* | O Diagnóstico não possui estado de execução ativa (`GERANDO`/`RUNNING`); quando a geração termina, a Frota cai para `"attention"` por 24h por causa de **1 única falha histórica**, enquanto o Diagnóstico só dá `"ATENCAO"` com 3 falhas seguidas. |
| **C6** | **Estoque zerado (`0/3`) ou abaixo da meta (`1/3`), sem geração ativa, última tentativa há 2 horas (`gap < 6h`)** | **`"attention"`**<br>*(Estoque esgotado / abaixo da meta)* | **`"IDLE"`**<br>*(Se não houver post agendado)* | `ready_stock: 0`,<br>`target_stock: 3` | `state: "idle"`,<br>`is_below_target: true` | **`"OK"`**<br>*(Porque `gap_hours < 6.0` não dispara `NO_GENERATION_GAP`!)* | Conflito direto entre Frota e Diagnóstico: um canal com **0 vídeos prontos** aparece como `"Atenção"` na Frota, `"IDLE"` no Factory Live e **`"Normal" (OK)`** no Diagnóstico até completar 6 horas sem tentar gerar. |
| **C7** | **Fábrica pausada globalmente pelo operador (`factory_state == "PAUSED"`)** | **`"paused"`**<br>*(Fábrica pausada pelo operador — para todos os canais)* | **`"SCHEDULED"` / `"IDLE"` / `"WAITING"`**<br>*(Ignora `factory_state`!)* | Ignora `factory_state` nos canais | **`"idle"` / `"waiting_schedule"`**<br>*(Ignora `factory_state`!)* | **`"PAUSADO"`** nos canais sem alerta crítico, mas **`"PARADO"`** nos canais com alerta crítico 24h! | Só `get_fleet_summary` respeita `factory_state == "PAUSED"` como prioridade #1 em todos os canais. O Factory Live e o `get_autonomous_status` ignoram a pausa global da fábrica. |
| **C8** | **Canal em período de espera (`auto_state == "cooldown"`) ou limite diário de tentativas atingido (`attempts >= max_attempts_24h`)** | Cooldown: **`"attention"`**<br>Limite tentativas c/ estoque cheio: **`"ok"`** | Cooldown: **`"WAITING"`**<br>Limite tentativas: **`"IDLE"`** | Não exibe | Cooldown: **`"cooldown"`**<br>Limite tentativas: **`"idle"`** ou **`"cooldown"`** | Cooldown: **`"OK"`** (`THROTTLED_NORMAL`)<br>Limite tentativas: **`"OK"`** (`DAILY_ATTEMPT_CAP_REACHED`) | Na Frota, `"cooldown"` é tratado como alerta amarelo (`"attention"`), enquanto no Diagnóstico é tratado como operação normal regulada (`"OK"` / `THROTTLED_NORMAL`). |
| **C9** | **Bloqueio de provedor / sem permissão (YouTube OAuth expirado, TTS/LLM bloqueado, `auto_state in ("blocked", "error")` ou disjuntor de rejeições)** | **`"blocked"`** | `"BLOCKED"` *(apenas se não houver task nem `scheduled_post`! Se houver `scheduled_post`, mostra `"SCHEDULED"` ou `"RETRYING"`!)* | Não exibe bloqueio | `"blocked"` ou `"error"` *(mas ignora disjuntor se `auto_state` ainda for `"idle"`)* | **`"PARADO"`** *(se disjuntor $\ge 100\%$ ou 3 rejeições)*, mas **`"OK"`** se `auto_state == "blocked"` sem detector correspondente! | O Diagnóstico **não lê `autonomous_state:{pid}`** (`"blocked"`/`"error"`); ele só olha seus 13 detectores. Já o Factory Live esconde `"BLOCKED"` se existir qualquer post agendado na fila! |
| **C10** | **Falha de leitura do estoque canônico (`get_canonical_ready_stock(pid) is None`)** | **`"attention"`**<br>*(Estoque desconhecido)* | `ready_stock: None`, mas `status` continua **`"IDLE"`** ou **`"SCHEDULED"`** | Converte `None` em `0` (`int(None or 0)` $\rightarrow$ `0`)! | Converte `None` em `0` (`get_autonomous_ready_stock` faz `or 0`)! | **`"ATENCAO"`**<br>(`stock_status = "UNKNOWN"`) | Apenas Frota e Diagnóstico tratam `ready_stock is None` como desconhecido/atenção; `get_profile_operations_overview` e `get_autonomous_status` mascaram a falha de leitura como `0`. |

---

## 3. Proposta de Unificação: Um Vocabulário e Uma Função Canônica

### 3.1. Separação Conceitual Obrigatória

A análise mostra que hoje o sistema mistura **duas perguntas diferentes** num único campo `status`:

1. **Status Operacional do Canal (`channel_status`)**: *"Qual é a saúde e disponibilidade operacional deste canal agora?"*
   - Deve ser **exatamente o mesmo** em todas as telas (**Frota**, **Diagnóstico**, **Factory Live**, **Gaveta do Canal**, **Sistema** e **Status do Perfil**).
2. **Estágio da Execução / Pipeline (`pipeline_stage` / `execution_status`)**: *"Se há uma tarefa ou publicação vinculada a este canal no grafo do Factory Live, em qual etapa do pipeline ela está?"*
   - Exclusivo do grafo visual do **Factory Live** (`SCRIPT` $\rightarrow$ `VOICE_BGM` $\rightarrow$ `MEDIA` $\rightarrow$ `SUBTITLES` $\rightarrow$ `RENDER` $\rightarrow$ `QUALITY_GATE` $\rightarrow$ `READY_STOCK` $\rightarrow$ `SCHEDULER` $\rightarrow$ `PUBLISHER` $\rightarrow$ `YOUTUBE`).
   - Ter um vídeo agendado para mais tarde (`SCHEDULER`) **não é o status de saúde do canal**; é apenas o próximo agendamento (`next_scheduled_at`).

---

### 3.2. Vocabulário Único do Status Operacional do Canal (5 Estados)

Propomos **5 estados canônicos** (códigos estáveis em maiúsculas sem acento para API/banco, com rótulo único em português para a UI):

| Código Canônico (`status`) | Rótulo Único na UI (`status_label`) | Severidade Visual | Significado Exato em Português |
|---|---|---|---|
| **`PAUSADO`** | **Pausado** | Neutro / Cinza | O canal **não está operando por decisão explícita**: fábrica pausada pelo operador (`PAUSED`/`EMERGENCY_PAUSED`), canal inativo (`is_active == False`) ou modo autônomo desligado neste canal (`autonomous_enabled == False`). **Prevalece sobre alertas históricos** (canal desligado não apita como bloqueado/parado). |
| **`BLOQUEADO`** | **Bloqueado** | Crítico / Vermelho | O canal **deveria estar operando, mas está impedido de produzir ou publicar**: disjuntor de rejeições acionado (`consec_rejections >= max_rejections`), guarda global de custo estourada (`global_cost_guard >= 100%`), `auto_state in ("blocked", "error")`, fábrica em `"ERROR"`, tarefa presa pós-render (`TASK_STUCK_AFTER_RENDER`), falsa interrupção (`FALSE_INTERRUPTION_LIKELY`), sequência crítica de rejeições (`REJECTION_STREAK`) ou sem geração há $\ge 12\text{h}$ com estoque `0` e sem cota diária atingida. |
| **`GERANDO`** | **Gerando** | Ativo / Azul | O canal está saudável e **executando ativamente uma tarefa de geração/planejamento agora** (`auto_state in ("generating", "planning", "reviewing", "scheduling")` ou `pending_proc > 0`). |
| **`ATENCAO`** | **Atenção** | Alerta / Amarelo | O canal está ativo e não está bloqueado, mas **requer observação ou está operando abaixo do ideal**: falha na leitura do estoque (`ready_stock is None`), estoque abaixo da meta (`ready_stock < target_stock`) **sem** ter batido o teto diário de aprovações/tentativas, falhas recentes de geração/publicação nas últimas 24h, ou alertas de aviso do diagnóstico (`REJECTION_BREAKER >= 50%`, `GLOBAL_COST_GUARD >= 80%`, `INVALID_TOPIC`, `APPROVED_CAP_EXCEEDED`). |
| **`OK`** | **OK** | Saudável / Verde | O canal está ativo, sem bloqueios, com estoque na meta (`ready_stock >= target_stock`) **ou** já cumpriu seu limite diário planejado (`DAILY_APPROVED_CAP_REACHED` / `DAILY_ATTEMPT_CAP_REACHED` / `cooldown` normal entre ciclos com estoque saudável), e sem falhas ativas que exijam intervenção. |

> **Regra de ouro resolvida pelo vocabulário único**:
> - **Pausa intencional (`PAUSADO`) vem sempre na Prioridade #1**: se o operador desligou o canal (**GTA VI**, **Escolhas**) ou pausou a fábrica, o status operacional é **sempre `PAUSADO`** (nunca `BLOQUEADO`/`PARADO`). Eventuais rejeições anteriores continuam visíveis na lista de diagnósticos informativos do canal, mas não transformam um canal desligado em alarme vermelho.
> - **Cota diária cumprida (`Quiz_Quiz` 10/10, `Histórias` 2/2) sem falha**: se `ready_stock < target_stock`, mas o canal já atingiu `generations_24h >= max_generations_24h` (e `ready_stock > 0`), o canal cumpriu sua regra diária $\rightarrow$ status **`OK`** com `reason = "Meta diária de aprovações atingida (X/Y em 24h)"` (ou se `ready_stock == 0`, mantém **`ATENCAO`** com `reason = "Estoque esgotado (0 prontos) e limite diário atingido (X/Y)"`, para o operador saber que não há vídeo para postar hoje).

---

### 3.3. Função Única Canônica no Backend

- **Onde mora**: `app/services/channel_status.py` (módulo leve e dedicado, importado por `operator_console.py`, `autonomous_production.py` e `production_diagnostics.py`, evitando import circular entre eles).
- **Assinatura exata**:

```python
from typing import Any, Dict, List, Optional, Literal

CanonicalChannelStatus = Literal["PAUSADO", "BLOQUEADO", "GERANDO", "ATENCAO", "OK"]

def evaluate_canonical_channel_status(
    profile_id: str,
    *,
    factory_state: str,
    is_channel_active: bool,
    autonomous_enabled: bool,
    auto_state: str,
    auto_message: Optional[str] = None,
    auto_last_error: Optional[str] = None,
    ready_stock: Optional[int],
    target_stock: int,
    pending_proc: int = 0,
    consec_rejections: int = 0,
    max_rejections: int = 3,
    generations_24h: int = 0,
    max_generations_24h: int = 0,
    attempts_24h: int = 0,
    max_attempts_24h: int = 0,
    failed_24h: int = 0,
    global_cost_guard_blocked: bool = False,
    diagnoses: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """
    Única função que decide o status operacional de um canal na V2.
    Retorna:
    {
        "status": CanonicalChannelStatus,       # "PAUSADO" | "BLOQUEADO" | "GERANDO" | "ATENCAO" | "OK"
        "status_label": str,                    # "Pausado" | "Bloqueado" | "Gerando" | "Atenção" | "OK"
        "reason": Optional[str],                # Frase curta em PT-BR explicando o estado atual
        "reason_code": str,                     # Código estável (ex.: "AUTONOMOUS_DISABLED", "BELOW_TARGET_STOCK", "HEALTHY")
        "is_healthy": bool,                     # True se status in ("OK", "GERANDO")
    }
    """
```

- **Ordem única de prioridade dentro de `evaluate_canonical_channel_status`**:
  1. **Pausado intencionalmente (`PAUSADO`)**:
     - `factory_state in ("PAUSED", "EMERGENCY_PAUSED")` $\rightarrow$ `PAUSADO` (`"Fábrica pausada pelo operador"`, `FACTORY_PAUSED`)
     - `not is_channel_active` $\rightarrow$ `PAUSADO` (`"Canal desativado pelo operador"`, `CHANNEL_INACTIVE`)
     - `not autonomous_enabled` $\rightarrow$ `PAUSADO` (`"Modo autônomo desligado"`, `AUTONOMOUS_DISABLED`)
  2. **Bloqueio operacional (`BLOQUEADO`)**:
     - `factory_state == "ERROR"` $\rightarrow$ `BLOQUEADO` (`"Fábrica em estado de erro"`, `FACTORY_ERROR`)
     - `global_cost_guard_blocked` $\rightarrow$ `BLOQUEADO` (`"Guarda global de custo atingida"`, `GLOBAL_COST_GUARD`)
     - `consec_rejections >= max_rejections` $\rightarrow$ `BLOQUEADO` (`f"Disjuntor acionado: {consec_rejections} rejeições consecutivas"`, `REJECTION_BREAKER`)
     - `auto_state in ("blocked", "error")` $\rightarrow$ `BLOQUEADO` (`auto_message or auto_last_error or "Produção autônoma bloqueada"`, `AUTONOMOUS_BLOCKED`)
     - Qualquer item em `diagnoses` com `severity == "critical"` $\rightarrow$ `BLOQUEADO` (`d["title"]`, `d["code"]`)
  3. **Execução ativa (`GERANDO`)**:
     - `auto_state in ("generating", "planning", "reviewing", "scheduling") or pending_proc > 0` $\rightarrow$ `GERANDO` (`"Geração em andamento"`, `GENERATING`)
  4. **Atenção operacional (`ATENCAO`)**:
     - `ready_stock is None` $\rightarrow$ `ATENCAO` (`"Estoque desconhecido (falha na leitura)"`, `STOCK_UNKNOWN`)
     - `ready_stock == 0` $\rightarrow$ `ATENCAO` (`"Estoque esgotado (0 vídeos prontos)"`, `STOCK_EMPTY`)
     - Qualquer item em `diagnoses` com `severity == "warning"` $\rightarrow$ `ATENCAO` (`d["title"]`, `d["code"]`)
     - `ready_stock < target_stock` **e** `not (max_generations_24h > 0 and generations_24h >= max_generations_24h)` $\rightarrow$ `ATENCAO` (`f"Estoque abaixo da meta ({ready_stock}/{target_stock})"`, `STOCK_BELOW_TARGET`)
     - `failed_24h > 0` $\rightarrow$ `ATENCAO` (`f"Atenção: {failed_24h} falha(s) registrada(s) nas últimas 24h"`, `RECENT_FAILURES`)
     - `auto_state == "cooldown"` e `ready_stock < target_stock` $\rightarrow$ `ATENCAO` (`"Em período de espera (cooldown)"`, `COOLDOWN`)
  5. **Saudável (`OK`)**:
     - Se `ready_stock < target_stock` mas `generations_24h >= max_generations_24h` (com `ready_stock > 0`) $\rightarrow$ `OK` (`f"Meta diária atingida ({generations_24h}/{max_generations_24h} em 24h)"`, `DAILY_CAP_REACHED`)
     - Caso contrário $\rightarrow$ `OK` (`None`, `HEALTHY`)

---

### 3.4. Como Cada Consumidor Passa a Usar a Função Única

| Consumidor | Como passará a funcionar | O que muda visualmente para o operador |
|---|---|---|
| **1. `get_fleet_summary` (Tela Frota)** | Substitui o bloco `if/elif` (`operator_console.py:4210-4245`) por uma chamada a `evaluate_canonical_channel_status(...)`. Expõe `status` (`PAUSADO`, `BLOQUEADO`, `GERANDO`, `ATENCAO`, `OK`), `status_label` e `issue = reason`. | Nomenclatura idêntica à que o operador já vê hoje na Frota (`Pausado`, `Bloqueado`, `Gerando`, `Atenção`, `OK`). **Correção prática**: canais que já bateram a meta diária de aprovações (**Quiz_Quiz** `10/10`, **Histórias** `2/2`) e têm vídeos em estoque deixam de mostrar falso alerta amarelo de `"Estoque abaixo da meta"` e passam a mostrar **`OK`** com observação `"Meta diária atingida"`. |
| **2. `get_diagnostics_overview` (Tela Diagnóstico)** | Corrige o bug de leitura de `autonomous_enabled` (`production_diagnostics.py:531-532` passa a chamar sempre `is_profile_autonomous_mode_enabled(cid)`) e substitui as linhas `1140-1155` por `evaluate_canonical_channel_status(..., diagnoses=diagnoses)`. | O Diagnóstico passa a usar exatamente os mesmos 5 estados da Frota (`Pausado`, `Bloqueado`, `Gerando`, `Atenção`, `OK`), trocando o antigo `"Parado"` por `"Bloqueado"` e adicionando `"Gerando"`. **Correção crítica**: canais desligados pelo operador (**GTA VI**, **Escolhas**) deixam de aparecer como `"Parado"` (vermelho) e aparecem como **`Pausado`**; canais com estoque `0/3` sem geração ativa aparecem sempre como **`Atenção`** mesmo antes de 6h. |
| **3. `get_live_execution_overview` (Tela Factory Live e Gaveta)** | Mantém `execution.status` e `execution.pipeline_stage` para animar os nós do grafo (`RUNNING`, `SCHEDULED`, `RETRYING`, `SUCCESS`), mas adiciona no nível do canal `channel_status` / `channel_status_label` / `channel_issue` vindos de `evaluate_canonical_channel_status(...)`. | No card do canal (`ChannelCard.jsx`) e no topo da gaveta (`ExecutionDrawer.jsx`), o operador passa a ver o badge real de saúde do canal (`Pausado`, `Bloqueado`, `Gerando`, `Atenção`, `OK`) separado do estágio da tarefa/agendamento (`Agendado`, `Renderizando`, etc.). Um canal desligado (**Escolhas**) não finge mais estar ativo só porque tem 1 post agendado. |
| **4. `get_profile_operations_overview` / `GET /api/v2/channels` (Tela Sistema)** | Para de converter `ready_stock = None` em `0` e inclui o resultado de `evaluate_canonical_channel_status(...)` em cada canal retornado por `/api/v2/channels`. | Na tela **Sistema**, ao lado do nome de cada canal, o operador passa a ver o mesmo badge de status (`Pausado`, `Bloqueado`, `Gerando`, `Atenção`, `OK`) que vê na Frota e no Diagnóstico. |
| **5. `get_autonomous_status` / `GET /api/v2/profiles/{id}/status`** | Corrige a linha `753` de `autonomous_production.py` (se `not enabled` e `state != "blocked"`, `state` da máquina interna é sempre `"disabled"`, independentemente de `scheduler_enabled`), preserva `ready_stock = None` sem `or 0`, e inclui `canonical_status` vindo de `evaluate_canonical_channel_status(...)`. | Elimina o estado fantasma em que um canal com autônomo desligado continuava reportando `waiting_schedule` ou `idle` por causa do scheduler global ativo. |

---

### 3.5. Menor Passo e Ordem Segura de Implementação

Para não quebrar produção nem misturar mudanças de contrato de várias telas num único commit, a implementação deve ser dividida em **3 missões curtas e independentes**:

1. **Passo 1 — Backend Canônico + Frota (`v2/status-canal-canonico`)**:
   - Criar `app/services/channel_status.py` com `evaluate_canonical_channel_status(...)` e testes unitários cobrindo todos os cenários da Tabela de Conflitos (C1 a C10).
   - Corrigir `autonomous_production.get_autonomous_status` (linha 753: `if not enabled: state = STATE_DISABLED` e preservar `ready_stock = None`).
   - Plugar `evaluate_canonical_channel_status` em `get_fleet_summary` e em `GET /api/v2/channels`, atualizando `fleetLogic.js` para aceitar o código canônico (`PAUSADO`, `BLOQUEADO`, `GERANDO`, `ATENCAO`, `OK`).
2. **Passo 2 — Alinhar Diagnóstico (`v2/diagnostico-status-unico`)**:
   - Ao integrar/atualizar a branch `v2/diagnostico`, corrigir a leitura de `is_profile_autonomous_mode_enabled(cid)` em `production_diagnostics.py:531-532` e delegar a decisão final do `status` do canal (linhas `1140-1155`) para `evaluate_canonical_channel_status(...)`.
   - Atualizar `diagnosticsLogic.js` e `test_production_diagnostics.py` para o vocabulário único (`PAUSADO`, `BLOQUEADO`, `GERANDO`, `ATENCAO`, `OK`).
3. **Passo 3 — Separar Saúde do Canal vs. Fase do Pipeline no Factory Live (`v2/live-status-separado`)**:
   - Em `get_live_execution_overview`, expor `channel_status` (canônico) separado de `execution.status` / `pipeline_stage`, atualizando `ChannelCard.jsx` e `ExecutionDrawer.jsx`.

---

## 4. Riscos de Implementação (O que pode quebrar e como evitar)

1. **Risco na Frota (`FleetView.jsx` e `fleetLogic.js`)**:
   - *O que pode quebrar*: `fleetLogic.js` (`STATUS_META` e `SORT_WEIGHT`) e `computeTotals` em `operator_console.py:4249-4259` hoje indexam chaves em inglês minúsculo (`paused`, `blocked`, `running`, `attention`, `ok`), e `test/services/test_api_v2_fleet_summary.py` + `webui-v2/src/components/Fleet/fleet_logic.test.js` validam essas chaves.
   - *Mitigação*: Atualizar no mesmo commit do Passo 1 o dicionário `totals` do backend, o `fleetLogic.js` e os dois arquivos de teste (`test_api_v2_fleet_summary.py` e `fleet_logic.test.js`).
2. **Risco no Diagnóstico (`DiagnosticsView.jsx`, `diagnosticsLogic.js` e `test_production_diagnostics.py`)**:
   - *O que pode quebrar*: Na branch `v2/diagnostico`, os contadores de resumo (`summary.parado_channels`, `summary.normal_channels`) e os testes em `test/services/test_production_diagnostics.py` esperam `"PARADO"` em vez de `"BLOQUEADO"` e esperam que `REJECTION_STREAK` sobreponha `PAUSADO`.
   - *Mitigação*: No Passo 2, atualizar explicitamente os testes de `test_production_diagnostics.py` para refletir a regra de negócio correta (canal desligado = `PAUSADO`; canal bloqueado = `BLOQUEADO`).
3. **Risco no Grafo do Factory Live (`FactoryLiveGraph.jsx` e `ChannelCard.jsx`)**:
   - *O que pode quebrar*: `FactoryLiveGraph.jsx` usa `channel.status === 'RUNNING'` / `'FAILED'` / `'WAITING'` e `channel.pipeline_stage` para acender os nós da esteira visual e desenhar partículas. Se substituirmos `channel.status` diretamente por `PAUSADO`/`OK`/`ATENCAO` sem separar o campo da execução, o grafo deixará de animar os estágios `SCHEDULED`, `RETRYING` e `SUCCESS`.
   - *Mitigação*: Manter `execution.status` e `pipeline_stage` intactos para o grafo de execução, e usar `channel_status` (da função canônica) exclusivamente para o crachá de saúde operacional do canal.
4. **Risco com o pseudo-canal `"Sem Canal"` (`id = "unassigned"`) no Factory Live**:
   - *O que pode quebrar*: `get_live_execution_overview` cria um item virtual `"unassigned"` quando há tarefas legadas rodando sem `profile_id` em `task_profiles`. Esse item não existe em `content_profiles`.
   - *Mitigação*: Não chamar `evaluate_canonical_channel_status` para `id == "unassigned"` (ou tratá-lo explicitamente como container transitório de tarefas órfãs com `status = "GERANDO"`).
