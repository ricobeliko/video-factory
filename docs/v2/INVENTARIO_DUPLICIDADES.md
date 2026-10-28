# Inventário de Controles, Fontes de Informação e Duplicidades (V2)

> **Princípio Operacional Obrigatório:** *"Um controle = um lugar. Uma informação = uma fonte."*
> Nenhum controle pode existir em duas telas ou endpoints concorrentes. Nenhuma informação pode ser calculada em dois lugares diferentes. Outras telas apenas **exibem** o valor e levam até o único lugar onde se edita.

---

## 1. Resumo Executivo das Duplicidades Encontradas

A varredura completa de `webui-v2/src/`, `app/controllers/v2/`, `app/services/` e dos pontos de escrita legados da V1 (`webui/Main.py`, `webui/components/*`) identificou **12 duplicidades** divididas em três camadas:

1. **Duplicidade entre telas da própria Web UI V2** (`FactoryHeader.jsx` + `ExecutionDrawer.jsx` da aba *Factory Live* vs `SystemView.jsx` da aba *Sistema*):
   - Pausar/retomar a fábrica existe em **2 telas V2** (`FactoryHeader.jsx` e `SystemView.jsx`), além de 2 botões na V1 (`webui/components/operator_console.py`).
   - Meta de estoque (`target_ready_stock`), frequência (`posts_per_day`) e janela de publicação (`publish_start_hour`, `publish_end_hour`, `min_interval_hours`) são editáveis em **2 telas V2** (`ExecutionDrawer.jsx` e `SystemView.jsx`), com limites divergentes na UI (`ExecutionDrawer` limita estoque a `3..6` e posts a `1..3`; `SystemView` aceita `1..10`).
   - Disparo manual de ciclo (`runFactoryCycle`) existe em **2 lugares na V2** (`FactoryHeader.jsx` global e `ExecutionDrawer.jsx` por canal) e em 2 lugares na V1.
2. **Duplicidade de rotas/endpoints na API V2 (`app/controllers/v2/operations.py`)**:
   - Cada mutação de canal possui rota duplicada `/channels/{profile_id}/...` e `/profiles/{profile_id}/...`, além de um endpoint agregado `PATCH /api/v2/channels/{profile_id}/settings` que reimplementa gravações de `growth_mode`, `autonomous_enabled`, `quotas` e `schedule` (inclusive omitindo o log `PROFILE_QUOTAS_UPDATED` que `PATCH .../quotas` grava).
   - O campo `posts_per_day` pertence simultaneamente a dois contratos de mutação: `PATCH .../quotas` (`UpdateQuotasRequest`) e `PATCH .../schedule` (`UpdateScheduleRequest`).
3. **Duplicidade de cálculo / fonte no backend (`app/services/`) e convivência V1 vs V2**:
   - **Voz (`voice_name`) e Velocidade (`voice_rate`)**: editáveis por canal na V2 (`SystemView.jsx`), mas ainda editáveis globalmente em 2 lugares da V1 (`webui/Main.py` e `webui/components/channel_factory.py`) que escrevem direto em `config.ui`.
   - **Estoque pronto (`ready_stock`)**: possui a fonte canônica `operator_console.get_canonical_ready_stock` / `autonomous_production.get_autonomous_ready_stock`, mas ainda coexiste com implementações paralelas legadas (`operator_console.get_ready_stock`, `autopilot.calculate_stock` e queries SQL inline de fallback em `get_fleet_summary`).
   - **Status do canal (`status`)**: calculado por **4 funções distintas** com vocabulários e regras diferentes (`get_fleet_summary` retorna `ok/running/attention/blocked/paused`; `get_live_execution_overview` retorna `IDLE/RUNNING/WAITING/SCHEDULED/RETRYING/SUCCESS/FAILED/BLOCKED`; `operations.get_channel_status` retorna `autonomous_status.state`; `operator_console.get_profile_operations_overview` retorna contadores brutos).
   - **Limites e contagens de 24h (`approved_24h` / `attempts_24h`)**: calculados pela fonte canônica em `autonomous_production.py` (`count_generations_in_last_24h`, que exige `generation_started` na janela para eventos de agendamento), mas recalculados por SQL divergente dentro de `operator_console.get_fleet_summary` (que ainda soma `task_approved_and_scheduled` e `task_waiting_schedule` sem filtrar `generation_started`) e por `production_overview.get_production_overview`.

---

## 2. Inventário Detalhado: Controles e Informações

### 2.1. Voz do Canal / Voz Global (`voice_name`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:1063-1108` (`<select id="voice-{pid}">`, botões *"Voltar a herdar"* e *"Fixar no canal"*) -> dispara `updateProfileVoice` em `SystemView.jsx:418`.
  - **API V2 (2 rotas):** `app/controllers/v2/operations.py:690` (`PATCH /api/v2/channels/{profile_id}/voice`) e `app/controllers/v2/operations.py:694` (`PATCH /api/v2/profiles/{profile_id}/voice`). *(Nota: `UpdateProfileSettingsRequest` em `operations.py:293` também declara `voice`, mas `update_channel_settings` em `operations.py:461-535` ignora o campo).*
  - **UI V1 (Legado — 3 pontos de escrita):**
    - `webui/Main.py:7124-7134` (seletor `"Voiceover Voice"`, `on_change=_on_voice_name_changed` em `webui/Main.py:500-510` -> `save_validated_voice_name` em `webui/Main.py:462-497`, grava `config.ui["voice_name"]`).
    - `webui/components/channel_factory.py:475-493` (seletor `"Voz Global"` + botão `"💾 Salvar Voz Global"` -> `save_global_voice` em `webui/components/channel_factory.py:437-449`, grava `config.ui["voice_name"]`).
    - `webui/components/channel_factory.py:802` (`render_channel_factory` -> botão `"💾 Salvar Alterações"` grava `updated_settings.voice.voice_name = settings.voice.voice_name or global_voice`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema` — modo leitura):** `webui-v2/src/components/System/SystemView.jsx:1229-1238`.
  - **UI V2 (`Oficina / Factory Live`):** `webui-v2/src/components/Fleet/Workshop.jsx:411-415`, `webui-v2/src/components/ChannelCard.jsx:138`, `webui-v2/src/components/ExecutionDrawer.jsx:624` (exibem `execution.provider` quando a etapa ativa é `NARRATION`).
  - **UI V1:** `webui/components/channel_factory.py:471` e `webui/components/channel_factory.py:703`.
- **Onde é CALCULADO / FONTE:**
  - **Resolução efetiva por canal (herança `channel -> preset -> global`):** `app/services/autonomous_production.py:803-882` (`get_effective_voice_settings`).
  - **Voz global canônica e validação pt-BR:** `app/services/autonomous_production.py:753-800` (`is_valid_pt_br_voice`, `get_canonical_global_voice`) e catálogo V2 em `app/services/voice.py` exposto por `GET /api/v2/voices` (`app/controllers/v2/operations.py:673`).
  - **Persistência por canal:** `app/services/profile_manager.py` (`content_profiles.settings_json -> voice.voice_name`), gravado via `app/services/autonomous_production.py:885-935` (`update_profile_voice_settings`).
- **Proposta:**
  - **Lugar único:** A voz deve ser editada exclusivamente por canal na tela **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/voice`, tendo `autonomous_production.get_effective_voice_settings` como única fonte de resolução.
  - **Menor passo para chegar lá:** Remover o campo `voice` morto de `UpdateProfileSettingsRequest` (`operations.py:293`), remover o alias `/profiles/{profile_id}/voice` e desativar a escrita global de `config.ui["voice_name"]` em `webui/Main.py` e `webui/components/channel_factory.py` no cutover da V2.

---

### 2.2. Velocidade da Voz (`voice_rate`) e Volume (`voice_volume`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:1128-1167` (`voice_rate`) e `SystemView.jsx:1181-1220` (`voice_volume`) -> dispara `updateProfileVoice` (`SystemView.jsx:418`).
  - **API V2 (2 rotas):** `app/controllers/v2/operations.py:690` (`PATCH /api/v2/channels/{profile_id}/voice`) e `app/controllers/v2/operations.py:694` (`PATCH /api/v2/profiles/{profile_id}/voice`).
  - **UI V1 (Legado):**
    - `webui/Main.py:7196-7206` (`speech_rate_select` com `on_change=_on_voice_rate_changed` em `webui/Main.py:536-540` -> `save_validated_voice_rate` em `webui/Main.py:513-533`, grava `config.ui["voice_rate"]`).
    - `webui/Main.py:7209-7220` (`speech_volume_select`, grava `config.ui["voice_volume"]` a cada renderização na linha `7220`).
    - `webui/Main.py:1854-1855` (`apply_generation_State_to_ui` sobrescreve `voice_rate_select` e `voice_volume_select` na `session_state` ao carregar estado de tarefa).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema` — modo leitura):** `webui-v2/src/components/System/SystemView.jsx:1240-1267` (mostra valor efetivo ou aviso fixo `1.25x` para canais Quiz).
- **Onde é CALCULADO / FONTE:**
  - **Resolução efetiva por canal:** `app/services/autonomous_production.py:803-882` (`get_effective_voice_settings`), respeitando trava de `1.25x` para formato Quiz em `app/services/quiz_Dilemma.py` / `voiceEditLogic.js:39`.
- **Proposta:**
  - **Lugar único:** A velocidade e o volume da voz devem ser editados unicamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/voice`, lidos de `autonomous_production.get_effective_voice_settings`.
  - **Menor passo para chegar lá:** Remover o alias `/profiles/{profile_id}/voice` e aposentar a gravação de `config.ui["voice_rate"]` e `config.ui["voice_volume"]` em `webui/Main.py` no cutover da V2.

---

### 2.3. Play / Pausa Global da Fábrica (`factory_state` / `is_paused`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 — Lugar 1 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:650-665` (botão `"▶ Retomar Fábrica"` / `"⏸ Pausar Fábrica"`) + modal de confirmação `SystemView.jsx:1317-1374` -> chama `pauseFactory()` / `resumeFactory()` (`SystemView.jsx:218, 224`).
  - **UI V2 — Lugar 2 (`Factory Live` / Cabeçalho):** `webui-v2/src/components/FactoryHeader.jsx:197-244` (botão `"⏸ Pausar Fábrica"` / `"▶ Retomar"` com confirmação inline) -> chama `pauseFactory()` / `resumeFactory()` (`FactoryHeader.jsx:39, 41`).
  - **API V2:** `app/controllers/v2/operations.py:124` (`POST /api/v2/factory/pause`) e `app/controllers/v2/operations.py:149` (`POST /api/v2/factory/resume`).
  - **UI V1 (Legado — 3 botões em `webui/components/operator_console.py`):**
    - `webui/components/operator_console.py:570-580` (botão `"▶ Retomar Fábrica"` no banner de pausa).
    - `webui/components/operator_console.py:643-669` (botão `"⏸ Pausar Fábrica"` / `"▶ Retomar Fábrica"` no cabeçalho).
    - `webui/components/operator_console.py:678-691` (popover `"🛑 Pausar Tudo"` -> `operator_console.emergency_pause()`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:573-584` (badge e linha `"Estado Operacional"`).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/FactoryHeader.jsx:117-122` (pílula de estado), `webui-v2/src/components/ExecutionDrawer.jsx:292-301` (desabilita botão de disparo quando pausada).
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:414-433` (KPI `"Pausados"` e status `'paused'` nos canais quando a fábrica está pausada).
- **Onde é CALCULADO / FONTE:**
  - **Fonte persistente bruta (`RUNNING` / `PAUSED`):** `app/services/operator_console.py:960-966` (`get_factory_state`, lê `autopilot_settings.key = 'factory_state'`) e `app/services/operator_console.py:969-1019` (`set_factory_state`, `pause_factory`, `resume_factory`, `emergency_pause`).
  - **Cálculo derivado 1 (`get_system_status`):** `app/services/operator_console.py:2025-2034` (combina `factory_state` com saúde de provedores para retornar `RUNNING`, `PAUSED`, `DEGRADED` ou `ERROR`).
  - **Cálculo derivado 2 (`get_fleet_summary`):** `app/services/operator_console.py:3980-3981` (lê `SELECT key, value FROM autopilot_settings` diretamente via SQL e testa `factory_state in ("PAUSED", "EMERGENCY_PAUSED")`).
- **Proposta:**
  - **Lugar único:** O botão de Pausar/Retomar a fábrica deve viver exclusivamente na tela **Sistema -> Cartão Fábrica** (`SystemView.jsx`), via `POST /api/v2/factory/pause` e `/resume`, enquanto o cabeçalho de `Factory Live` e a tela `Frota` apenas exibem o estado e levam para `Sistema`.
  - **Menor passo para chegar lá:** Remover os botões de mutação `pauseFactory`/`resumeFactory` de `webui-v2/src/components/FactoryHeader.jsx:197-244` (substituindo por link para `#sistema`) e fazer `get_fleet_summary` usar `get_factory_state()` em vez de reconsultar `autopilot_settings` manualmente.

---

### 2.4. Modo Autônomo por Canal (`autonomous_enabled`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 (`Factory Live` -> `ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:397-406` (botão `"● AUTO (Ativo)"` / `"○ MANUAL (Pausado)"` -> chama `updateProfileAutonomousMode` em `ExecutionDrawer.jsx:153`). *(Nota: em `SystemView.jsx:882-885` o Modo Autônomo é apenas exibido como somente leitura, enquanto as demais configurações do canal ficam em `SystemView.jsx`!).*
  - **API V2 (5 rotas para o mesmo controle!):**
    1. `app/controllers/v2/operations.py:353` (`PATCH /api/v2/channels/{profile_id}/autonomous`)
    2. `app/controllers/v2/operations.py:357` (`PATCH /api/v2/profiles/{profile_id}/autonomous`)
    3. `app/controllers/v2/operations.py:406` (`POST /api/v2/channels/{profile_id}/autonomous/enable`)
    4. `app/controllers/v2/operations.py:414` (`POST /api/v2/channels/{profile_id}/autonomous/disable`)
    5. `app/controllers/v2/operations.py:461` e `507-508` (`PATCH /api/v2/channels/{profile_id}/settings` com `payload.autonomous_enabled`)
  - **UI V1 (Legado — 3 lugares):**
    - `webui/components/channel_factory.py:547-550` (botão `"▶️ Ativar Produção Deste Canal Agora"` pós-criação).
    - `webui/components/channel_factory.py:625-633` (botões `"⏸️ Pausar"` / `"▶️ Ativar"` no card do canal).
    - `webui/components/operator_console.py:1771-1785` (botões `"▶️ Ativar Produção Autônoma"` / `"⏸️ Desativar Produção Autônoma"`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:882-885` (`"Modo Autônomo: SIM (Ativo) / NÃO (Desligado)"`).
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:853-860` (gaveta lateral da Frota: `"Ligado"` / `"Desligado"`).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/ChannelCard.jsx:90-98` (pílula `"● AUTO"` / `"○ MANUAL"`).
- **Onde é CALCULADO / FONTE:**
  - **Fonte canônica:** `app/services/autonomous_production.py:140-152` (`is_profile_autonomous_mode_enabled`) e gravação em `autonomous_production.py:174-219` (`set_profile_autonomous_mode_enabled` / `set_autonomous_mode_enabled`).
  - **Cálculo duplicado em `get_fleet_summary`:** `app/services/operator_console.py:4196-4201` (reconstrói a leitura da chave `autonomous_mode_enabled:{pid}` em `settings_map` com fallback para `prof_ctx` e `settings_json`, o que diverge de `is_profile_autonomous_mode_enabled`, que retorna `False` por padrão para perfis secundários sem chave em `autopilot_settings`).
- **Proposta:**
  - **Lugar único:** O controle de ativar/desativar `autonomous_enabled` deve viver em **Sistema -> Ajustes por Canal** (`SystemView.jsx`, junto aos demais ajustes do canal) via `PATCH /api/v2/channels/{profile_id}/autonomous`, tendo `autonomous_production.is_profile_autonomous_mode_enabled` como única função de leitura.
  - **Menor passo para chegar lá:** Mover o toggle de `ExecutionDrawer.jsx` para `SystemView.jsx`, remover as 4 rotas redundantes em `operations.py` (`/profiles/.../autonomous`, `/autonomous/enable`, `/autonomous/disable` e o campo em `/settings`) e usar `is_profile_autonomous_mode_enabled` dentro de `get_fleet_summary`.

---

### 2.5. Modo de Crescimento por Canal (`growth_mode`: WARMUP / SCALE) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 (`Factory Live` -> `ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:369-387` (botões `"🌱 WARMUP"` e `"🚀 SCALE"` -> chama `updateProfileGrowthMode` em `ExecutionDrawer.jsx:130`).
  - **API V2 (3 rotas):**
    1. `app/controllers/v2/operations.py:296` (`PATCH /api/v2/channels/{profile_id}/growth-mode`)
    2. `app/controllers/v2/operations.py:300` (`PATCH /api/v2/profiles/{profile_id}/growth-mode`)
    3. `app/controllers/v2/operations.py:461` e `501-505` (`PATCH /api/v2/channels/{profile_id}/settings` com `payload.growth_mode`)
  - **UI V1 (Legado):** `webui/Main.py:8251-8262` (`growth_mode_selector_sb` -> `scheduler.set_growth_mode`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:857-859` e `935-937` (badge somente leitura no card do canal).
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:849-851` (gaveta lateral da Frota).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/ChannelCard.jsx:84-88` (badge `🌱 WARMUP` / `🚀 SCALE`).
- **Onde é CALCULADO / FONTE:**
  - **Fonte por canal:** `app/services/autonomous_production.py:221-244` (`get_profile_growth_mode`, lê `content_profiles.growth_mode` com fallback para `scheduler.get_growth_mode`).
- **Proposta:**
  - **Lugar único:** O seletor de `growth_mode` deve viver exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/growth-mode`, lido por `autonomous_production.get_profile_growth_mode`.
  - **Menor passo para chegar lá:** Mover a edição de `growth_mode` de `ExecutionDrawer.jsx` (deixando lá apenas exibição/link para `Sistema`), remover `/profiles/{profile_id}/growth-mode` e `payload.growth_mode` de `/settings` em `operations.py`.

---

### 2.6. Meta de Estoque Pronto (`target_ready_stock`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 — Lugar 1 (`Sistema -> Ajustes por Canal`):** `webui-v2/src/components/System/SystemView.jsx:903-911` (`<input type="number" min="1" max="10">`) -> chama `updateProfileQuotas` (`SystemView.jsx:412`) -> `PATCH /api/v2/channels/{profile_id}/quotas`.
  - **UI V2 — Lugar 2 (`Factory Live -> ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:421-431` (botões `[3, 4, 5, 6]`) + botão `"💾 Salvar Quotas e Janela"` (`ExecutionDrawer.jsx:533-540`) -> chama `updateProfileSettings` (`ExecutionDrawer.jsx:96`) -> `PATCH /api/v2/channels/{profile_id}/settings`.
  - **API V2 (3 rotas):**
    1. `app/controllers/v2/operations.py:538` (`PATCH /api/v2/channels/{profile_id}/quotas`)
    2. `app/controllers/v2/operations.py:542` (`PATCH /api/v2/profiles/{profile_id}/quotas`)
    3. `app/controllers/v2/operations.py:461` e `510-513` (`PATCH /api/v2/channels/{profile_id}/settings` — **agravação:** grava `set_target_ready_stock` sem emitir o evento auditável `PROFILE_QUOTAS_UPDATED` que `operations.py:584` emite!).
  - **UI V1 (Legado — 2 lugares):**
    - `webui/components/channel_factory.py:705` e `807` (`m_target_stock` grava em `settings.automation.target_ready_stock`, que é uma tabela/coluna diferente de `autopilot_settings` usada por `set_target_ready_stock`!).
    - `webui/Main.py:9021-9028` (`autopilot_desired_stock` em sessão).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema` — modo leitura):** `webui-v2/src/components/System/SystemView.jsx:955-957`.
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:685` (tabela `{readyStock}/{targetStock}`) e `FleetView.jsx:815` (gaveta lateral).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/ChannelCard.jsx:104` (`Estoque: {ready_stock}/{target_stock}`).
- **Onde é CALCULADO / FONTE:**
  - **Fonte canônica:** `app/services/autonomous_production.py:246-285` (`get_target_ready_stock`, intervalo `[3, 10]`, persistido em `autopilot_settings` via `set_target_ready_stock` em `autonomous_production.py:287-303`) e retornado em `get_canonical_ready_stock()["minimum_threshold"]` (`operator_console.py:1614`).
  - **Cálculo duplicado em `get_fleet_summary`:** `app/services/operator_console.py:4207-4215` (lê `autopilot_settings` manualmente com fallback `10 if growth_mode == "SCALE" else 3`, divergindo do default `5` de `get_target_ready_stock` em `autonomous_production.py:283` para SCALE!).
- **Proposta:**
  - **Lugar único:** A meta de estoque deve ser editada exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/quotas` (validando a faixa real `3..10` do backend) e calculada unicamente por `autonomous_production.get_target_ready_stock` / `get_canonical_ready_stock()["minimum_threshold"]`.
  - **Menor passo para chegar lá:** Remover a edição de quotas de `ExecutionDrawer.jsx:410-473`, alinhar a validação de `systemEditLogic.js` / `SystemView.jsx` para `3..10`, remover `/settings` e `/profiles/.../quotas` em `operations.py`, e fazer `get_fleet_summary` usar `canon["minimum_threshold"]` (da linha `4222`).

---

### 2.7. Posts por Dia (`posts_per_day`) e Janela de Publicação (`publish_start_hour`, `publish_end_hour`, `min_interval_hours`) — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 — Lugar 1 (`Sistema -> Ajustes por Canal`):** `webui-v2/src/components/System/SystemView.jsx:921-929` (`posts_per_day`) e `SystemView.jsx:981-1025` (`publish_start_hour`, `publish_end_hour`, `min_interval_hours`) -> chama `updateProfileQuotas` e `updateProfileSchedule` (`SystemView.jsx:412-415`).
  - **UI V2 — Lugar 2 (`Factory Live -> ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:459-470` (`posts_per_day`) e `ExecutionDrawer.jsx:485-529` (`publish_start_hour`, `publish_end_hour`, `min_interval_hours`) -> chama `updateProfileSettings` (`ExecutionDrawer.jsx:96-108`, enviando `posts_per_day` duplicado dentro de `quotas` e de `schedule`).
  - **API V2 (5 rotas / contratos sobrepostos):**
    1. `app/controllers/v2/operations.py:538` (`PATCH /api/v2/channels/{profile_id}/quotas` — aceita `posts_per_day`)
    2. `app/controllers/v2/operations.py:542` (`PATCH /api/v2/profiles/{profile_id}/quotas` — aceita `posts_per_day`)
    3. `app/controllers/v2/operations.py:613` (`PATCH /api/v2/channels/{profile_id}/schedule` — também aceita `posts_per_day`)
    4. `app/controllers/v2/operations.py:617` (`PATCH /api/v2/profiles/{profile_id}/schedule` — também aceita `posts_per_day`)
    5. `app/controllers/v2/operations.py:461` (`PATCH /api/v2/channels/{profile_id}/settings` — aceita `quotas` e `schedule`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema` — modo leitura):** `webui-v2/src/components/System/SystemView.jsx:958-961` (`Posts/Dia`) e `1038-1050` (`Janela Horária`, `Fuso Horário`, `Intervalo Mínimo`).
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:325` (KPI `"de meta {totals.goal_today}"`), `FleetView.jsx:702` e `823` (`{published_today} / {goal_today}`).
- **Onde é CALCULADO / FONTE:**
  - **Fonte canônica:** `app/controllers/v2/operations.py:50-71` (`_get_profile_schedule_dict` e `_get_profile_quotas_dict`, que leem `profile_manager.get_profile_settings(profile_id).schedule`).
  - **Leitura duplicada em `get_fleet_summary`:** `app/services/operator_console.py:4218` (faz `json.loads(settings_json)` manual para extrair `goal_today`).
- **Proposta:**
  - **Lugar único:** `posts_per_day` e a janela horária devem ser editados exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/schedule` (mantendo `posts_per_day` apenas no contrato de `schedule`).
  - **Menor passo para chegar lá:** Remover a edição de janela/posts de `ExecutionDrawer.jsx:454-542`, retirar `posts_per_day` de `UpdateQuotasRequest` e remover os aliases `/profiles/...` e `/settings` em `operations.py`.

---

### 2.8. Limites Diários (`max_generations_24h`, `max_attempts_24h`, Global Cost Guard) e Contagens 24h — **[DUPLICIDADE]**

- **Onde é EDITADO:**
  - **UI V2 (`Factory Live -> ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:440-450` (botões `[1, 2, 3, 4, 5]` para `"Gerações 24h"` -> chama `updateProfileSettings` em `ExecutionDrawer.jsx:99`).
  - **UI V2 (`Sistema -> Ajustes por Canal`):** Somente leitura em `webui-v2/src/components/System/SystemView.jsx:941-950` e `962-969`! *(Inversão arquitetural: `SystemView` mostra como somente leitura, enquanto `ExecutionDrawer` permite editar `max_generations_24h`).*
  - **API V2 (3 rotas para `max_generations_24h` e `max_attempts_24h`):**
    1. `app/controllers/v2/operations.py:538` (`PATCH /api/v2/channels/{profile_id}/quotas`)
    2. `app/controllers/v2/operations.py:542` (`PATCH /api/v2/profiles/{profile_id}/quotas`)
    3. `app/controllers/v2/operations.py:461` (`PATCH /api/v2/channels/{profile_id}/settings`)
    *(Nota: Global Cost Guard `global_max_generations_24h` / `global_max_attempts_24h` só possui setters em `autonomous_production.py:548, 564`, sem tela de edição).*
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:941-950` e `962-969` (`Gerações/24h` e `Tentativas/24h`).
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:706-711` e `835-843` (`approval_rate_24h`).
  - **UI V1 (`Operator Console`):** `webui/components/operator_console.py:1758-1759` (exibe `Aprovados (24h)`, `Tentativas` e `Global Cost Guard`).
- **Onde é CALCULADO / FONTE:**
  - **Fonte canônica dos tetos:** `app/services/autonomous_production.py:389-433` (`get_max_generations_24h`), `475-519` (`get_max_attempts_24h`), `539-562` (`get_global_max_generations_24h`, `get_global_max_attempts_24h`).
  - **Fonte canônica das contagens 24h (usada pelas Guardas 5.2–5.4 do laço):** `app/services/autonomous_production.py:937-1011` (`count_generations_in_last_24h` — pós-hotfix `20bed84`, exige `generation_started` na janela de 24h para não contar reagendamentos antigos), `1013-1069` (`count_generation_attempts_in_last_24h`) e `1071-1155` (`get_global_cost_guard_status`).
  - **Cálculo duplicado e divergente em `get_fleet_summary`:** `app/services/operator_console.py:4097-4129` e `4235-4238` (calcula `approved_24h` e `attempts_24h` via query SQL própria em `operational_events` usando `COUNT(*)` e somando `task_approved_and_scheduled` / `task_waiting_schedule` **sem** filtrar por `generation_started` na janela — ou seja, sofre do mesmo bug de reagendamento corrigido no hotfix `20bed84`!).
- **Proposta:**
  - **Lugar único:** Os tetos `max_generations_24h` e `max_attempts_24h` devem ser apenas derivados do `growth_mode` (ou editados exclusivamente em `SystemView.jsx` se o operador quiser override), e todas as contagens/taxas de 24h devem vir exclusivamente das funções canônicas de `autonomous_production.py`.
  - **Menor passo para chegar lá:** Remover o seletor `"Gerações 24h"` de `ExecutionDrawer.jsx:435-452` e substituir a query de `approved_24h`/`attempts_24h` em `operator_console.get_fleet_summary` (`linhas 4097-4129`) por chamadas ou mesma regra SQL de `autonomous_production.count_generations_in_last_24h` e `count_generation_attempts_in_last_24h`.

---

### 2.9. Estoque Pronto (`ready_stock`) — **[DUPLICIDADE DE FONTE NO BACKEND]**

- **Onde é EDITADO:** Não é editado diretamente (é resultado de vídeos aprovados nos Gates ou aprovados manualmente na Revisão Humana em `VideoReviewView.jsx:123` -> `POST /api/v2/review/tasks/{task_id}/approve`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:341-359` (KPI `"Estoque pronto total"`), `674-687` (barra da tabela) e `811-817` (gaveta lateral).
  - **UI V2 (`Produção`):** `webui-v2/src/components/Production/ProductionView.jsx:258-264` (KPI `"Estoque pronto"`) e `367-452` (tabela `"📦 Estoque pronto"`).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/ChannelCard.jsx:104` (`Estoque: {ready_stock}/{target_stock}`).
  - **UI V1:** `webui/components/operator_console.py:754-770`, `webui/components/channel_factory.py:619-620`, `webui/Main.py:9031-9040`.
- **Onde é CALCULADO / FONTE:**
  - **Fonte canônica (YouTube-first, fail-closed em Safety PASS, Quality >= 70 e arquivo físico):** `app/services/operator_console.py:1584-1625` (`get_canonical_ready_stock`) -> delega para `app/services/autonomous_production.py:665-736` (`get_autonomous_ready_stock`). Usada por `production_overview.py:354`, `get_live_execution_overview` (`operator_console.py:3610`), `get_profile_operations_overview` (`operator_console.py:1469`) e `get_fleet_summary` (`operator_console.py:4222`).
  - **Fonte paralela 1 (Fallback silencioso em `get_fleet_summary`):** `app/services/operator_console.py:4030-4096` e `4224-4225` (executa queries SQL em `monetization_safety` e `tasks` sem checar Quality Gate nem arquivo físico e, se `get_canonical_ready_stock` lançar exceção, usa `max(sqlite_ready, mem_ready)` inventando número em vez de sinalizar erro/UNKNOWN).
  - **Fonte paralela 2 (Legada V1):** `app/services/operator_console.py:1482-1581` (`get_ready_stock`, baseada apenas em `sm.state` em memória + Safety PASS, sem Quality Gate).
  - **Fonte paralela 3 (Legada V1 Autopilot):** `app/services/autopilot.py` (`calculate_stock`, chamada em `webui/Main.py:9031`).
- **Proposta:**
  - **Lugar único:** `operator_console.get_canonical_ready_stock` (delegando a `autonomous_production.get_autonomous_ready_stock`) deve ser a única fonte de cálculo do estoque pronto em todo o sistema, sem fallback que invente número sem Quality Gate.
  - **Menor passo para chegar lá:** Remover as queries `sqlite_ready`/`mem_ready` e o fallback silencioso em `operator_console.get_fleet_summary` (`linhas 4030-4062, 4224-4225`), tratando falha de leitura de estoque como `null`/`UNKNOWN`.

---

### 2.10. Status do Canal (`status` / `health_status`) — **[DUPLICIDADE DE FONTE E VOCABULÁRIO]**

- **Onde é EDITADO:** Não é editado diretamente (derivado do estado da fábrica, `is_active`, `autonomous_enabled`, estoque, rejeições consecutivas e tarefa ativa).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Frota`):** `webui-v2/src/components/Fleet/FleetView.jsx:460-498` (`"Precisa de você"`), `511-533` (`"Mapa da frota"`), `664-671` (coluna Status na tabela) e `770-807` (gaveta lateral).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/ChannelCard.jsx:68-73` (badge `status`) e `webui-v2/src/components/ExecutionDrawer.jsx:596-599`.
  - **UI V2 (`Oficina`):** `webui-v2/src/components/Fleet/Workshop.jsx:371-385`.
- **Onde é CALCULADO / FONTE:**
  - **Fonte 1 (`get_fleet_summary` — usada pela aba `Frota`):** `app/services/operator_console.py:4273-4306` -> calcula `status` em `{ok, running, attention, blocked, paused}` e `issue` em português.
  - **Fonte 2 (`get_live_execution_overview` — usada pela aba `Factory Live` e pela `Oficina`):** `app/services/operator_console.py:3268-3609` -> calcula `status` em `{IDLE, RUNNING, FAILED, WAITING, SCHEDULED, RETRYING, SUCCESS, BLOCKED}` olhando apenas para a tarefa ativa/agendada e `auto_state`, sem considerar estoque zerado ou fábrica pausada.
  - **Fonte 3 (`GET /api/v2/channels` e `GET /api/v2/profiles`):** `app/controllers/v2/operations.py:174-223` -> usa `operator_console.get_profile_operations_overview` (`operator_console.py:1399-1475`) enriquecido com `_get_profile_quotas_dict` e `_get_profile_schedule_dict`.
  - **Fonte 4 (`GET /api/v2/profiles/{profile_id}/status`):** `app/controllers/v2/operations.py:226-264` -> expõe `autonomous_production.get_autonomous_status`.
- **Proposta:**
  - **Lugar único:** Separar claramente dois conceitos com fontes únicas: (a) **Saúde Operacional do Canal** (`ok/running/attention/blocked/paused` + `issue`), calculada em uma única função canônica usada tanto por `Frota` quanto por `/api/v2/channels`, e (b) **Execução Ativa da Tarefa** (`execution`), calculada em uma única função para a `Oficina` / `Factory Live`.
  - **Menor passo para chegar lá:** Extrair a regra de saúde do canal de `get_fleet_summary` (`operator_console.py:4273-4306`) em uma função auxiliar única e reutilizá-la em todos os endpoints que retornam status de canal.

---

### 2.11. Estado Operacional do Sistema (`system_status`: Workers, Scheduler, Auto Publish, Dry Run) — **[DUPLICIDADE V1 vs V2]**

- **Onde é EDITADO:**
  - **UI V2:** Nenhum toggle para `scheduler_enabled`, `auto_publish_enabled` ou `dry_run` (são somente leitura em `SystemView.jsx:615-632`).
  - **UI V1 (Legado):** `webui/Main.py:8165-8186` (checkboxes `"Scheduler Enabled"`, `"Auto Publish Enabled"`, `"Simulation Mode (Dry Run)"` -> `_on_scheduler_enabled_changed`, `_on_auto_publish_enabled_changed`, `_on_dry_run_changed` em `webui/Main.py:8110-8140`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Sistema`):** `webui-v2/src/components/System/SystemView.jsx:600-646` (Worker de Geração, Worker do Agendador, Agendador Ativo, Auto Publicação, Dry Run, Heartbeats).
  - **UI V2 (`Factory Live`):** `webui-v2/src/components/FactoryHeader.jsx:145-192` (Auto Publish, Dry Run, Scheduler, Instância).
  - **UI V1 (`Operator Console`):** `webui/components/operator_console.py:474-490` e `701-835`.
- **Onde é CALCULADO / FONTE:**
  - **Fonte única no backend:** `app/services/operator_console.py:1995-2092` (`get_system_status`), exposta em `GET /api/v2/system/status` (`app/controllers/v2/operations.py:80-95`). *(Nota: em `operations.py:88-93`, o controller sobrescreve `scheduler_worker = "ACTIVE"` quando `scheduler.is_scheduler_worker_running()` é verdadeiro).*
- **Proposta:**
  - **Lugar único:** `operator_console.get_system_status` (via `GET /api/v2/system/status`) é a fonte única de leitura e a tela **Sistema** (`SystemView.jsx`) é o lugar canônico de exibição na V2.
  - **Menor passo para chegar lá:** Mover a verificação `scheduler.is_scheduler_worker_running()` de `app/controllers/v2/operations.py:88-93` para dentro do próprio `operator_console.get_system_status` (`operator_console.py:2021`), eliminando pós-processamento no controller.

---

### 2.12. Disparo Manual de Ciclo (`runFactoryCycle` / `POST /api/v2/factory/run-cycle`) — **[DUPLICIDADE]**

- **Onde é EDITADO / ACIONADO:**
  - **UI V2 — Lugar 1 (`Factory Live -> FactoryHeader`):** `webui-v2/src/components/FactoryHeader.jsx:247-294` (botão `"⚡ Executar Ciclo Agora"` -> dispara `runFactoryCycle({ force: true, oneShot: true })` em `FactoryHeader.jsx:75`).
  - **UI V2 — Lugar 2 (`Factory Live -> ExecutionDrawer`):** `webui-v2/src/components/ExecutionDrawer.jsx:284-322` (botão `"⚡ Disparar Ciclo do Canal"` -> dispara `runFactoryCycle({ profileId, channelId, force: true, oneShot: true })` em `ExecutionDrawer.jsx:178`).
  - **API V2:** `app/controllers/v2/operations.py:766` (`POST /api/v2/factory/run-cycle`).
  - **UI V1 (Legado — 2 botões):**
    - `webui/components/operator_console.py:1787-1795` (botão `"⚡ Executar Ciclo Agora (Run Cycle)"` -> `operator_console.run_autonomous_cycle_op`).
    - `webui/Main.py:8497-8505` (botão `"⚡ Run Cycle Now"` -> `scheduler.run_scheduler_cycle()`).
- **Onde é CALCULADO / FONTE:**
  - **Execução no backend:** `app/controllers/v2/operations.py:766-820` (`run_factory_cycle`, que dispara `autonomous_production.run_autonomous_cycle` em thread background).
- **Proposta:**
  - **Lugar único:** Manter apenas 1 ponto de disparo supervisionado na V2 (por canal, na gaveta de detalhes do canal ou na tela `Sistema`), removendo o botão global redundante do cabeçalho ou consolidando na aba `Frota`/`Sistema` quando a aba legada `Factory Live` for aposentada.
  - **Menor passo para chegar lá:** Retirar o botão global `"⚡ Executar Ciclo Agora"` de `FactoryHeader.jsx:247-294` quando `Factory Live` for consolidada na `Frota`.

---

### 2.13. Revisão Humana de Vídeos (`approveReviewTask` / `discardReviewTask`) — **[SEM DUPLICIDADE NA V2]**

- **Onde é EDITADO / ACIONADO:**
  - **UI V2 (`Revisão`):** `webui-v2/src/components/VideoReview/VideoReviewView.jsx:620-708` (botões `"✅ Aprovar para Estoque"` e `"🗑️ Descartar"` -> `approveReviewTask` em `VideoReviewView.jsx:123` e `discardReviewTask` em `VideoReviewView.jsx:155`).
  - **API V2:** `app/controllers/v2/review.py:124` (`POST /api/v2/review/tasks/{task_id}/approve`) e `app/controllers/v2/review.py:177` (`POST /api/v2/review/tasks/{task_id}/discard`).
- **Onde é só EXIBIDO:**
  - **UI V2 (`Revisão`):** `webui-v2/src/components/VideoReview/VideoReviewView.jsx:198-272` (contadores e lista de vídeos retidos/aprovados/descartados).
- **Onde é CALCULADO / FONTE:**
  - **Fonte única:** `app/services/video_review.py` (`list_review_tasks`, `approve_held_video_for_stock`, `discard_held_video`).
- **Status:** **CONFORME** (1 controle = 1 lugar; 1 informação = 1 fonte).

---

### 2.14. Telemetria de Agentes (`AgentOpsView`) — **[SEM DUPLICIDADE NA V2]**

- **Onde é EDITADO:** Somente leitura (nenhum controle de mutação de fábrica).
- **Onde é só EXIBIDO:** `webui-v2/src/components/AgentOps/AgentOpsView.jsx:184-542`.
- **Onde é CALCULADO / FONTE:** `app/controllers/v2/operations.py:854-899` (`GET /api/v2/agent-ops` -> `app/services/agent_ops.py:get_agent_ops_telemetry`).
- **Status:** **CONFORME** (1 informação = 1 fonte).

---

## 3. Tabela Consolidada de Duplicidades e Plano de Convergência

| # | Controle / Informação | Status | Onde é Editado / Calculado Hoje (Duplicado) | Lugar Único Proposto (1 frase) | Menor Passo para Chegar Lá (1 frase) |
|---|---|---|---|---|---|
| 1 | **Voz (`voice_name`)** | **DUPLICIDADE** | **V2:** `SystemView.jsx:1063` (`PATCH /channels/{id}/voice` e `/profiles/{id}/voice`). **V1:** `webui/Main.py:7124` e `channel_factory.py:485, 802`. | Editar exclusivamente por canal em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/voice`, resolvido por `autonomous_production.get_effective_voice_settings`. | Remover o alias `/profiles/{profile_id}/voice` e o campo morto `voice` de `UpdateProfileSettingsRequest` em `operations.py`, e desativar a escrita global em `webui/Main.py` e `channel_factory.py` no cutover. |
| 2 | **Velocidade e Volume (`voice_rate`, `voice_volume`)** | **DUPLICIDADE** | **V2:** `SystemView.jsx:1128, 1181` (`PATCH /channels/{id}/voice` e `/profiles/{id}/voice`). **V1:** `webui/Main.py:7196, 7209`. | Editar exclusivamente por canal em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/voice`, resolvido por `autonomous_production.get_effective_voice_settings`. | Remover o alias `/profiles/{profile_id}/voice` em `operations.py` e aposentar a gravação de `config.ui["voice_rate"]` / `config.ui["voice_volume"]` em `webui/Main.py` no cutover. |
| 3 | **Play / Pausa da Fábrica (`factory_state`)** | **DUPLICIDADE** | **V2 UI:** `SystemView.jsx:650` E `FactoryHeader.jsx:197`. **V1 UI:** `operator_console.py:570, 643, 678`. **Cálculo:** `get_factory_state`, `get_system_status` e SQL inline em `get_fleet_summary:3980`. | Pausar e retomar a fábrica exclusivamente em **Sistema -> Cartão Fábrica** (`SystemView.jsx`) via `POST /api/v2/factory/pause` e `/resume`, lendo de `operator_console.get_factory_state`. | Remover os botões de pausa/retomada de `FactoryHeader.jsx:197-244` (trocando por link para `#sistema`) e usar `get_factory_state()` dentro de `get_fleet_summary`. |
| 4 | **Modo Autônomo por Canal (`autonomous_enabled`)** | **DUPLICIDADE** | **V2 UI:** `ExecutionDrawer.jsx:397` (ausente na edição de `SystemView.jsx:882`). **API V2:** 5 rotas em `operations.py` (`353, 357, 406, 414, 507`). **Cálculo:** `is_profile_autonomous_mode_enabled` vs lógica inline em `get_fleet_summary:4196`. | Editar `autonomous_enabled` exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/autonomous`, lido por `is_profile_autonomous_mode_enabled`. | Mover o toggle de `ExecutionDrawer.jsx` para `SystemView.jsx`, remover as 4 rotas redundantes em `operations.py` e chamar `is_profile_autonomous_mode_enabled` em `get_fleet_summary`. |
| 5 | **Growth Mode (`growth_mode`)** | **DUPLICIDADE** | **V2 UI:** `ExecutionDrawer.jsx:369` (só leitura em `SystemView.jsx:857`). **API V2:** 3 rotas em `operations.py` (`296, 300, 501`). **V1 UI:** `webui/Main.py:8251`. | Editar `growth_mode` exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/growth-mode`, lido por `get_profile_growth_mode`. | Mover o seletor de `ExecutionDrawer.jsx` para `SystemView.jsx` e remover `/profiles/{profile_id}/growth-mode` e `payload.growth_mode` de `/settings` em `operations.py`. |
| 6 | **Meta de Estoque (`target_ready_stock`)** | **DUPLICIDADE** | **V2 UI:** `SystemView.jsx:903` (1..10) E `ExecutionDrawer.jsx:421` (3..6). **API V2:** 3 rotas (`operations.py:538, 542, 510`). **V1 UI:** `channel_factory.py:705`. **Cálculo:** `get_target_ready_stock` (SCALE=5) vs `get_fleet_summary:4213` (SCALE=10). | Editar a meta de estoque exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`, faixa `3..10`) via `PATCH /api/v2/channels/{profile_id}/quotas`, calculada por `get_target_ready_stock`. | Remover a edição de quotas de `ExecutionDrawer.jsx`, remover `/settings` e `/profiles/.../quotas` em `operations.py` e usar `canon["minimum_threshold"]` em `get_fleet_summary`. |
| 7 | **Posts por Dia e Janela (`posts_per_day`, `schedule`)** | **DUPLICIDADE** | **V2 UI:** `SystemView.jsx:921, 981` E `ExecutionDrawer.jsx:459, 485`. **API V2:** `posts_per_day` aceito tanto em `/quotas` quanto em `/schedule` e `/settings` (`operations.py:270, 278, 461, 538, 613`). | Editar `posts_per_day` e a janela de publicação exclusivamente em **Sistema -> Ajustes por Canal** (`SystemView.jsx`) via `PATCH /api/v2/channels/{profile_id}/schedule`. | Remover o formulário de quotas/janela de `ExecutionDrawer.jsx`, retirar `posts_per_day` de `UpdateQuotasRequest` e remover `/settings` e `/profiles/...` em `operations.py`. |
| 8 | **Limites e Contagens 24h (`max_generations_24h`, `approved_24h`)** | **DUPLICIDADE** | **V2 UI:** `ExecutionDrawer.jsx:440` edita `max_generations_24h`, enquanto `SystemView.jsx:944` só exibe. **Cálculo 24h:** `autonomous_production.count_generations_in_last_24h` vs query SQL divergente em `get_fleet_summary:4105`. | Manter `max_generations_24h` e `max_attempts_24h` derivados do `growth_mode` (exibidos em `SystemView.jsx`) e calcular contagens/taxas de 24h exclusivamente via `autonomous_production.py`. | Remover os botões de `"Gerações 24h"` de `ExecutionDrawer.jsx:435-452` e alinhar `get_fleet_summary` (`linhas 4097-4129`) para usar `count_generations_in_last_24h` e `count_generation_attempts_in_last_24h`. |
| 9 | **Estoque Pronto (`ready_stock`)** | **DUPLICIDADE** | **Cálculo:** `get_canonical_ready_stock` (`operator_console.py:1584`) coexiste com fallback SQL/memória sem Quality Gate em `get_fleet_summary:4030, 4225`, `get_ready_stock` (`1482`) e `autopilot.calculate_stock`. | Calcular o estoque pronto unicamente via `operator_console.get_canonical_ready_stock` (`autonomous_production.get_autonomous_ready_stock`), sem fallback que ignore o Quality Gate. | Remover as queries `sqlite_ready`/`mem_ready` e o fallback silencioso de `get_fleet_summary` (`operator_console.py:4030-4062, 4224-4225`). |
| 10 | **Status do Canal (`status`)** | **DUPLICIDADE** | **Cálculo:** 4 fontes com vocabulários distintos (`get_fleet_summary:4273`, `get_live_execution_overview:3268`, `get_profile_operations_overview:1399`, `get_channel_status:226`). | Ter uma única função de saúde operacional do canal (`ok/running/attention/blocked/paused` + `issue`) e uma única função de snapshot da execução ativa (`execution`). | Extrair o cálculo de status/issue de `get_fleet_summary` em função canônica única e reutilizá-la nos demais endpoints de canal. |
| 11 | **Estado dos Workers (`scheduler_worker`)** | **DUPLICIDADE** | `operator_console.get_system_status` (`operator_console.py:2021`) calcula `scheduler_worker`, e `operations.py:88-93` recalcula por cima usando `scheduler.is_scheduler_worker_running()`. | Calcular todo o payload de estado do sistema exclusivamente dentro de `operator_console.get_system_status`. | Mover a checagem `scheduler.is_scheduler_worker_running()` de `app/controllers/v2/operations.py:88-93` para `operator_console.get_system_status`. |
| 12 | **Disparo Supervisionado de Ciclo (`run-cycle`)** | **DUPLICIDADE** | **V2 UI:** `FactoryHeader.jsx:247` (global) E `ExecutionDrawer.jsx:284` (por canal). **V1 UI:** `operator_console.py:1787` e `webui/Main.py:8497`. | Manter um único controle de disparo supervisionado na V2 (contextual ao canal inspecionado ou na tela `Sistema`). | Remover o botão global duplicado de `FactoryHeader.jsx:247-294` e consolidar o controle por canal quando a aba `Factory Live` for absorvida. |
