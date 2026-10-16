# Web UI V2 — Especificação Técnica de Migração e Auditoria Streamlit

## Status
`FASE R4A: DISCOVERY / READ-ONLY AUDIT (COMPLETED)`
`FASE R5A: THIN READ-ONLY API MVP (COMPLETED)`
`FASE R5B: LIVE MULTI-CHANNEL EXECUTION CONTRACT / UI-005 (COMPLETED)`
`FASE R6A: WEB UI V2 / FACTORY LIVE MVP (COMPLETED)`
`FASE R6A.3: VISUAL IDENTITY + METRICS + MULTI-CHANNEL LIVE (COMPLETED)`
`FASE R6A.5: VISUAL IDENTITY SYSTEM + SINGLE-FOCUS PIPELINE (COMPLETED / HUMAN APPROVED)`
`FASE R6A.6: ORGANIC MOTION LANGUAGE + SCALABILITY (DEV IMPLEMENTED)`
`FLOW-UI-001: GOOGLE FLOW TELEMETRY IN FACTORY LIVE = DEV VALIDATED`
`FLOW-CREDIT-002: REAL BALANCE EXTRACTION VIA VERIFY = DEV VALIDATED`
`FASE R8: PRODUCTION CONSOLIDATION & LAUNCHER = DEV VALIDATED`
`FASE R9.1: LIVE PIPELINE TELEMETRY CONSOLIDATION = DEV VALIDATED`
`FASE R9.2: MULTI-CHANNEL OPERATIONS & UX CONSOLIDATION = DEV VALIDATED`
`FASE R9.3: E2E SMOKE & POLISH = DEV PENDING`
`FASE R10: CONTROLLED PRODUCTION ROLLOUT PACKAGE = PROD PENDING`

---

## 1. Objectives (Objetivos)

1. **Preservar Integralmente o Backend Operacional:**
   - O princípio arquitetural mandatório é: **PRESERVE BACKEND. REPLACE CONTROL SURFACE.**
   - Todos os serviços Python canônicos (`operator_console`, `profile_manager`, `autonomous_production`, `scheduler`, `quality_score`, `safety`, `copyright_provenance`, `post_for_me`, `analytics`, `closed_loop`) permanecem intactos como autoridades de negócio.
   - Nenhuma regra de negócio deve ser reescrita ou duplicada na camada de interface ou na API.

2. **Eliminar as Limitações Arquiteturais do Streamlit:**
   - Eliminar a latência perceptível e os reruns de script inteiro causados pelo modelo monolítico reativo do Streamlit.
   - Eliminar os 90 pontos de `st.rerun()` forçado e o overhead de 11 `st.fragment()` de polling.
   - Separar a interface visual em uma SPA moderna (React + Vite), desacoplada do ciclo de execução do servidor backend.

3. **Consolidar Pontos Únicos de Controle Operacional:**
   - Eliminar duplicidades e ambiguidades de interface (ex.: Growth Mode global vs Growth Mode por perfil).
   - Garantir que cada ação na UI corresponda a uma única função de serviço canônica documentada.

4. **Permitir Transição Suave e com Risco Zero:**
   - Executar a migração em fases graduais (Read-Only primeiro, comandos simples depois, configurações por perfil, e finalmente remoção do legado).
   - O Streamlit permanece ativo e funcional como fallback operacional durante todo o período de validação.

---

## 2. Non-Goals (O que NÃO faz parte desta frente)

- **NÃO alterar regras de negócio, limites de Growth Mode ou gates:**
  - Limites de slots WARMUP/SCALE, thresholds de Quality (70.0), Safety Gate e Copyright Provenance Gate permanecem inalterados.
- **NÃO alterar o banco de dados operacional SQLite:**
  - Nenhuma tabela, coluna ou migration de schema é criada nesta fase.
- **NÃO implementar código de API ou Frontend nesta entrega (R4A):**
  - Esta etapa é estritamente de descoberta, inventário, mapeamento funcional e especificação técnica.
- **NÃO interferir no piloto autônomo em execução:**
  - O canal piloto autônomo (*Dose Diária De Internet*) continua rodando em produção sem qualquer alteração.
- **NÃO reativar ou alterar a frente Google Flow:**
  - `FLOW_TRACK = FROZEN / DEFERRED`.

---

## 3. Current Streamlit Inventory (Inventário Streamlit)

A auditoria do repositório localizou os seguintes arquivos que compõem a camada de apresentação Streamlit:

| Arquivo | Linhas | Papel Arquitetural | Widgets Mutantes | Elementos Leitura | `st.rerun` | `st.fragment` | `session_state` |
| :--- | :---: | :--- | :---: | :---: | :---: | :---: | :---: |
| `webui/Main.py` | 9.994 | Monólito original da aplicação; formulário de vídeo, configurações de provedores, geração batch e orquestrador de seções | 167 | 336 | 45 | 6 | 366 |
| `webui/components/operator_console.py` | 2.877 | Mission Control da fábrica; header de comando, telemetria, filas, saúde de provedores, copyright audit e observabilidade | 87 | 326 | 39 | 5 | 17 |
| `webui/components/channel_factory.py` | 525 | Cards de canais editoriais, onboarding de novos canais e configuração de voz global | 39 | 48 | 6 | 0 | 6 |
| `scripts/production_entrypoint.py` | 166 | Bootstrap headless de produção; garante lock PRIMARY e inicia `scheduler_worker` antes de subir o Streamlit | 0 | 0 | 0 | 0 | 0 |
| `webui/.streamlit/config.toml` | 12 | Configuração de servidor Streamlit (port 8501, headless, CORS) | — | — | — | — | — |
| `webui/styles.css` | 741 | Estilos CSS customizados injetados no Streamlit para ocultar menus e estilizar stepper/cards | — | — | — | — | — |
| **TOTAL CONSOLIDADO** | **14.315** | — | **293** | **710** | **90** | **11** | **389** |

### Detalhamento dos Componentes Interativos

- **Widgets Mutantes (293 controles totais):**
  - `st.button`: 88 ocorrências
  - `st.text_input`: 77 ocorrências
  - `st.checkbox`: 40 ocorrências
  - `st.selectbox`: 47 ocorrências
  - `st.number_input`: 18 ocorrências
  - `st.text_area`: 8 ocorrências
  - `st.file_uploader`: 5 ocorrências
  - `st.form` / `st.form_submit_button`: 4 ocorrências
  - `st.slider`: 6 ocorrências
- **Elementos de Leitura / Feedback (710 exibições):**
  - `st.markdown`: 167 ocorrências
  - `st.caption`: 125 ocorrências
  - `st.error`: 123 ocorrências
  - `st.warning`: 77 ocorrências
  - `st.toast`: 71 ocorrências
  - `st.write`: 40 ocorrências
  - `st.success`: 36 ocorrências
  - `st.info`: 49 ocorrências
  - `st.metric`: 4 ocorrências
  - `st.dataframe` / `st.table`: 2 ocorrências
  - `st.spinner`: 16 ocorrências

---

## 4. Functional Migration Matrix (Matriz Funcional)

Mapeamento completo de todas as capacidades operacionais da UI atual para serviços backend canônicos:

| ID | Tela / Componente | Função UI Atual | Tipo de Ação | Serviço Backend | Função Backend Canônica | Leitura/Escrita | Fonte Canônica | Risco Prod. | Prioridade Migração |
| :--- | :--- | :--- | :--- | :--- | :--- | :---: | :--- | :---: | :---: |
| **FN-01** | Operator Console | Macro Meta Bar | STATUS | `operator_console` | `get_instance_info()` | READ | SQLite `operator_heartbeats` | LOW | P1 (MVP) |
| **FN-02** | Operator Console | Command Header (State) | STATUS | `operator_console` | `get_factory_state()` | READ | SQLite `operator_settings` | HIGH | P1 (MVP) |
| **FN-03** | Operator Console | Pause / Resume Buttons | COMMAND | `operator_console` | `pause_factory()`, `resume_factory()` | WRITE | SQLite `operator_settings` | HIGH | P1 (MVP) |
| **FN-04** | Operator Console | Emergency Pause | COMMAND | `operator_console` | `emergency_pause()` | WRITE | SQLite `operator_settings` | HIGH | P1 (MVP) |
| **FN-05** | Operator Console | Health Cards Row | STATUS | `operator_console` | `get_system_status()` | READ | Multi-service aggregated | MEDIUM | P1 (MVP) |
| **FN-06** | Operator Console | Active Task Card & Stepper | STATUS | `operator_console` | `get_instance_info()`, `state.get_task()` | READ | Memory / SQLite `tasks` | MEDIUM | P2 |
| **FN-07** | Operator Console | Safe Task Cancel | COMMAND | `operator_console` | `request_task_cancel()` | WRITE | SQLite `tasks` (checkpoint) | HIGH | P2 |
| **FN-08** | Operator Console | Generation Queue Summary | STATUS | `operator_console` | `get_generation_queue_summary()` | READ | SQLite `tasks` | MEDIUM | P1 (MVP) |
| **FN-09** | Operator Console | Scheduler Queue Summary | STATUS | `operator_console` | `get_scheduler_queue_summary()` | READ | SQLite `scheduled_posts` | MEDIUM | P1 (MVP) |
| **FN-10** | Operator Console | Canonical Ready Stock | STATUS | `operator_console` | `get_canonical_ready_stock()` | READ | SQLite `tasks` + filesystem check | MEDIUM | P1 (MVP) |
| **FN-11** | Operator Console | Profile Operations Table | STATUS | `operator_console` | `get_profile_operations_overview()` | READ | SQLite `content_profiles` | MEDIUM | P1 (MVP) |
| **FN-12** | Operator Console | Profile Growth Mode Select | CONFIGURATION | `profile_manager` | `set_profile_growth_mode()` | WRITE | SQLite `content_profiles.growth_mode` | HIGH | P1 (MVP) |
| **FN-13** | Operator Console | Profile Target Stock | CONFIGURATION | `autonomous_production` | `set_target_ready_stock()` | WRITE | SQLite `content_profile_settings` | MEDIUM | P1 (MVP) |
| **FN-14** | Operator Console | Profile Autonomous Toggle | COMMAND | `autonomous_production` | `set_profile_autonomous_mode()` | WRITE | SQLite `content_profile_settings` | HIGH | P1 (MVP) |
| **FN-15** | Operator Console | Provider Health Summary | DIAGNOSTIC | `operator_console` | `get_provider_health_summary()` | READ | Service ping / health checks | LOW | P1 (MVP) |
| **FN-16** | Operator Console | Run Autonomous Cycle | COMMAND | `operator_console` | `run_autonomous_cycle_op()` | WRITE | Autonomous Worker trigger | HIGH | P1 (MVP) |
| **FN-17** | Operator Console | Run Analytics Cycle | COMMAND | `operator_console` | `run_analytics_collection_cycle_op()` | WRITE | Analytics Worker trigger | MEDIUM | P1 (MVP) |
| **FN-18** | Operator Console | Closed Loop Feedback Toggle | CONFIGURATION | `operator_console` | `set_closed_feedback_loop_enabled_op()`| WRITE | SQLite `autopilot_settings` | MEDIUM | P2 |
| **FN-19** | Operator Console | Copyright Provenance Audit | DIAGNOSTIC | `operator_console` | `get_copyright_provenance_summary_op()`| READ | SQLite `tasks` + manifest | HIGH | P2 |
| **FN-20** | Operator Console | Manual Legacy Copyright Approve| COMMAND | `operator_console` | `approve_legacy_task_copyright_op()` | WRITE | SQLite `tasks.copyright_status` | CRITICAL | P2 |
| **FN-21** | Operator Console | Observability Events & Errors | HISTORY | `operator_console` | `get_operational_events()`, `get_recent_errors()`| READ | SQLite `operator_events` | LOW | P2 |
| **FN-22** | Channel Factory | Channel Cards Overview | STATUS | `channel_factory` | `_get_channel_card_data()` | READ | Profile manager + PFM accounts | MEDIUM | P1 (MVP) |
| **FN-23** | Channel Factory | New Channel Onboarding Form | CONFIGURATION | `profile_manager` | `create_profile()`, `create_channel()` | WRITE | SQLite `content_profiles` | HIGH | P2 |
| **FN-24** | Channel Factory | Global Voice Config | CONFIGURATION | `config` | `try_save_config()` | WRITE | `config.toml` | LOW | P3 |
| **FN-25** | Main (Top Bar) | Language Switcher | CONFIGURATION | `Main` / Session | Client-side locale | READ/WRITE| Client state / localStorage | LOW | P1 (MVP) |
| **FN-26** | Main (Dialogs) | Settings Provider Modal | CONFIGURATION | `config` | `try_save_config()`, `update_config_nonblocking()`| WRITE | `config.toml` | HIGH | P3 |
| **FN-27** | Main (Dialogs) | Presets & Key Backup/Restore | CONFIGURATION | `Main` | `_backup_api_keys()`, `_restore_api_keys()`| READ/WRITE| Encrypted/JSON backup | MEDIUM | P3 |
| **FN-28** | Main (Generation) | Single Video Generation Form | COMMAND | `tm` / `video` | `save_task()`, `start_video_generation()`| WRITE | Background video pipeline | HIGH | P2 |
| **FN-29** | Main (Generation) | Batch Topics Generation | COMMAND | `Main` / `tm` | Loop over `save_task()` | WRITE | Task queue | HIGH | P3 |
| **FN-30** | Main (Publish) | Manual Post For Me Publish | COMMAND | `tm` | `publish_task()` | WRITE | Post For Me API + SQLite | HIGH | P2 |
| **FN-31** | Main (Monitor) | Live Task Progress & Log Polling| STATUS | `webui_task` | `get_task_log()`, `sm.get_task()` | READ | In-memory queue + SQLite | MEDIUM | P2 |
| **FN-32** | Main (Radar) | Trend Radar & Topics Suggester| DIAGNOSTIC | `trend_radar` | `get_trending_topics()` | READ | TikTok/Google trends | LOW | P4 (Later) |
| **FN-33** | Main (Autopilot)| Batch Narrative Structuring | CONFIGURATION | `autopilot` | `assign_batch_narrative_structures()`| READ/WRITE| Content strategy | LOW | P4 (Later) |
| **FN-34** | Operator Console | Long-Form Clip Repurposing | COMMAND/STATUS| `operator_console` | `import_clip_source_op()`, `render_clip_segment_op()`| READ/WRITE| SQLite clip tables | LOW | P4 (Later) |

---

## 5. Duplicate / Legacy Paths (Duplicações e Puxadinhos)

Durante a auditoria, foram mapeadas as seguintes redundâncias e pontos de divergência:

### A. Growth Mode (Classificação: `AMBIGUOUS / DUPLICATED`)
- **Problema:** A UI possui um seletor global no Streamlit e seletores por perfil na tabela do Operator Console.
- **Evidência Operacional:** O seletor global da UI altera apenas variáveis de sessão/TOML sem alterar o banco dos perfis. A autoridade canônica real é `content_profiles.growth_mode` em SQLite (`profile_manager.set_profile_growth_mode`).
- **Mapeado como:** `UI-001` e `UI-002`.

### B. Ativação de Modo Autônomo (Classificação: `DUPLICATED`)
- **Problema:** O modo autônomo possui um controle master global no Operator Console (`operator_console.set_autonomous_mode_enabled_op`), um controle booleano por perfil em `content_profile_settings`, e uma aba legada `_render_autopilot_section` em `Main.py`.
- **Autoridade Canônica:** `autonomous_production.py` (que exige tanto o loop global ativo quanto o perfil individual habilitado). A aba legada de Autopilot em `Main.py` gera planos estáticos que não alimentam o loop contínuo e pode ser descontinuada.

### C. Scheduler & Status Visual Stale (Classificação: `LEGACY_ADAPTER / STALE_FEEDBACK`)
- **Problema:** O Streamlit pode manter visualmente um alerta de timeout ou retry ("Retry 1/3") mesmo após o worker em background ter concluído a publicação no YouTube com sucesso e registrado `publication_events.status='success'`.
- **Causa:** O Streamlit lê o estado da sessão local gravado durante a chamada síncrona do botão antes de consultar o banco consolidado.
- **Mapeado como:** `UI-004`.

### D. Destino de Canal & Binding Post For Me (Classificação: `LEGACY_ADAPTER`)
- **Problema:** O perfil padrão (*Dose Diária De Internet*) possui `channel_id = 'channel-default-youtube'` e `external_account_id = NULL` no banco de dados. A publicação ocorre via fallback estático mapeado no código Python (`post_for_me.py`), enquanto novos canais criados pelo Channel Factory persistem `external_account_id` real.
- **Mapeado como:** `CFG-004`.

### E. Dispersão de Configurações (Classificação: `AMBIGUOUS`)
- Configurações do sistema encontram-se distribuídas em 5 locais distintos:
  1. `config.toml`: Chaves de API, segredos, URLs base;
  2. `content_profiles` (SQLite): Metadados de canais e `growth_mode`;
  3. `content_profile_settings` (SQLite): Configurações editoriais do perfil em formato JSON;
  4. `autopilot_settings` (SQLite): Flags operacionais globais (`closed_feedback_loop_enabled`, `auto_collection_enabled`);
  5. `st.session_state` (Memória Streamlit): Preferências visuais temporárias e rascunhos de formulário.

---

## 6. Performance / Rerun Findings (Diagnóstico de Performance do Streamlit)

A latência perceptível relatada pelo operador decorre de fatores estruturais do Streamlit:

| Padrão de Custo | Frequência | Causa Raiz Técnica | Impacto Operacional | Abordagem na Web UI V2 |
| :--- | :--- | :--- | :--- | :--- |
| **Rerun de Script Inteiro** | A cada interação (clique, select, input) | O interpretador Python reexecuta as 9.994 linhas de `Main.py` do topo ao final, instanciando centenas de widgets. | **ALTO:** Ações simples demoram de 800ms a 2.500ms para responder. | Arquitetura SPA (React). Apenas o componente alterado renderiza localmente no navegador. |
| **90 `st.rerun()` Forçados** | Em todas as mutações | Botões executam lógica de backend e chamam explicitamente `st.rerun()`, dobrando o tempo de ciclo. | **ALTO:** Sensação de travamento após cliques ("Running..."). | Resposta HTTP síncrona leve (`200 OK`) com atualização otimista de estado no cliente. |
| **Polling com 11 Fragments** | A cada 0.5s – 5s | `st.fragment(run_every=...)` roda tarefas periódicas no processo Streamlit, disputando o GIL Python com o worker de produção. | **MÉDIO:** Picos aleatórios de CPU e contenção de lock no SQLite. | Server-Sent Events (SSE) ou polling leve via HTTP GET desacoplado do worker. |
| **Consultas Repetidas ao SQLite Sem Cache** | Dezenas por rerun | A cada execução, `operator_console` abre conexões independentes para buscar heartbeats, tarefas ativas e eventos. | **MÉDIO:** IO desnecessário em banco. | FastAPI com connection pooling / cache em memória de leituras rápidas (TTL 2s). |
| **Filesystem Traversal na UI** | A cada render de Ready Stock | `get_canonical_ready_stock` verifica existência física e tamanho de arquivos de vídeo em `storage/tasks/*/final-1.mp4`. | **MÉDIO:** Bloqueia o thread de renderização em operações de disco no Windows. | Cache de inventário em banco ou background worker; API retorna dados já indexados. |
| **Auto-Save de `config.toml` em Todo Rerun** | Final de cada render | `_save_runtime_config()` tenta persistir configurações no disco mesmo quando nada foi alterado. | **BAIXO:** Desgaste desnecessário de disco. | Endpoints `PUT/PATCH` específicos executados apenas quando o usuário salva explicitamente. |

---

## 7. Proposed Architecture (Arquitetura Proposta para Web UI V2)

```
+-------------------------------------------------------------------------------+
|                             CLIENT CONTROL SURFACE                            |
|                     React 18 + Vite + Tailwind CSS / Vanilla CSS              |
|             (SPA: Component-Driven, Zero Python in Browser, Fast Navigation)  |
+-------------------------------------------------------------------------------+
                                      |
                           HTTP REST / SSE (JSON)
                                      |
+-------------------------------------------------------------------------------+
|                            THIN API LAYER (FastAPI)                           |
|      (app/api/v2/... montado no app/asgi.py já existente - fastapi==0.136.3)  |
|                                                                               |
|   - Zero Regras de Negócio Duplicadas                                         |
|   - Pydantic DTOs para Validação Estrita de Entrada/Saída                     |
|   - Tratamento de Erros e Conversão para HTTP Status Codes Padronizados      |
|   - Endpoints Desacoplados do Ciclo de Renderização                           |
+-------------------------------------------------------------------------------+
                                      |
                             Chamadas Diretas Python
                                      |
+-------------------------------------------------------------------------------+
|                          EXISTING BACKEND SERVICES                            |
|                          (TOTALMENTE PRESERVADOS)                             |
|                                                                               |
|   +-------------------+  +-------------------+  +-----------------------+     |
|   | operator_console  |  |  profile_manager  |  | autonomous_production |     |
|   +-------------------+  +-------------------+  +-----------------------+     |
|   +-------------------+  +-------------------+  +-----------------------+     |
|   |     scheduler     |  |   safety_gate     |  |     quality_score     |     |
|   +-------------------+  +-------------------+  +-----------------------+     |
|   +-------------------+  +-------------------+  +-----------------------+     |
|   | copyright_provenance | post_for_me / YT  |  | analytics / feedback  |     |
|   +-------------------+  +-------------------+  +-----------------------+     |
|                                                                               |
|                                 SQLite Database                               |
|              (tasks, scheduled_posts, content_profiles, settings)             |
+-------------------------------------------------------------------------------+
```

---

## 8. Proposed API Surface (Superfície Preliminar de Endpoints)

A API fina será construída utilizando o FastAPI existente no projeto (`app/asgi.py`, `fastapi==0.136.3`), sem introduzir novos frameworks backend:

| Método | Endpoint | Objetivo | Serviço Backend Canônico | Leitura/Escrita | Autoridade | Risco |
| :--- | :--- | :--- | :--- | :---: | :--- | :---: |
| `GET` | `/api/v2/system/status` | Macro status da fábrica, instância, nó, heartbeats e modo operacional | `operator_console.get_system_status()` | READ | SQLite `operator_heartbeats` | LOW |
| `POST` | `/api/v2/system/pause` | Pausa operacional não-destrutiva da fábrica | `operator_console.pause_factory()` | WRITE | SQLite `operator_settings` | HIGH |
| `POST` | `/api/v2/system/resume` | Retomada operacional da fábrica | `operator_console.resume_factory()` | WRITE | SQLite `operator_settings` | HIGH |
| `POST` | `/api/v2/system/emergency-pause` | Parada de emergência imediata | `operator_console.emergency_pause()` | WRITE | SQLite `operator_settings` | HIGH |
| `GET` | `/api/v2/channels` | Listagem consolidada de todos os canais/perfis com métricas | `channel_factory._get_channel_card_data()` | READ | SQLite `content_profiles` | LOW |
| `GET` | `/api/v2/channels/{profile_id}` | Detalhes operacionais e configurações de um canal específico | `profile_manager.get_profile_settings()` | READ | SQLite `content_profiles` | LOW |
| `PATCH`| `/api/v2/channels/{profile_id}/growth-mode` | Altera Growth Mode do canal (WARMUP / SCALE) | `profile_manager.set_profile_growth_mode()` | WRITE | SQLite `content_profiles` | HIGH |
| `POST` | `/api/v2/channels/{profile_id}/autonomous/enable` | Habilita produção autônoma para o canal | `autonomous_production.set_profile_autonomous_mode()` | WRITE | SQLite `content_profile_settings` | HIGH |
| `POST` | `/api/v2/channels/{profile_id}/autonomous/disable` | Pausa produção autônoma para o canal | `autonomous_production.set_profile_autonomous_mode()` | WRITE | SQLite `content_profile_settings` | HIGH |
| `PATCH`| `/api/v2/channels/{profile_id}/target-stock` | Altera meta de estoque pronto do canal | `autonomous_production.set_target_ready_stock()` | WRITE | SQLite `content_profile_settings` | MEDIUM |
| `GET` | `/api/v2/channels/{profile_id}/ready-stock` | Detalhamento das tarefas prontas em estoque para o perfil | `operator_console.get_canonical_ready_stock()` | READ | SQLite `tasks` | LOW |
| `GET` | `/api/v2/scheduler/queue` | Lista de postagens agendadas e status da fila | `operator_console.get_scheduler_queue_summary()` | READ | SQLite `scheduled_posts` | LOW |
| `GET` | `/api/v2/publications/recent` | Histórico consolidado de publicações no YouTube com status terminal | `operator_console.get_operational_events()` | READ | SQLite `publication_events` | LOW |
| `GET` | `/api/v2/providers/health` | Resumo de integridade e conectividade dos provedores | `operator_console.get_provider_health_summary()` | READ | Service Health Checks | LOW |
| `POST` | `/api/v2/operations/run-autonomous-cycle` | Dispara execução forçada de um ciclo autônomo (respeitando cooldown) | `operator_console.run_autonomous_cycle_op()` | WRITE | Autonomous Worker | HIGH |
| `POST` | `/api/v2/operations/run-analytics-cycle` | Dispara coleta manual de métricas analíticas | `operator_console.run_analytics_collection_cycle_op()` | WRITE | Analytics Worker | MEDIUM |
| `GET` | `/api/v2/observability/events` | Log de eventos operacionais recentes | `operator_console.get_operational_events()` | READ | SQLite `operator_events` | LOW |
| `GET` | `/api/v2/observability/errors` | Central de erros e falhas recentes | `operator_console.get_recent_errors()` | READ | SQLite `operator_errors` | LOW |

---

## 9. MVP Scope (Escopo do Mínimo Produto Viável)

Para maximizar a velocidade de entrega sem assumir riscos desnecessários, o escopo foi dividido estritamente em três horizontes:

### MVP (Fase R5 — Control Surface Essencial)
1. **Header Operacional:** Status Macro (RUNNING/PAUSED), badge de Instância (PRIMARY), botões Pause/Resume e Parada de Emergência.
2. **Cards dos Canais:** Grid visual com todos os perfis ativos, nicho, métrica de estoque atual vs meta.
3. **Status Autônomo por Canal:** Chave liga/desliga de autonomia por perfil com confirmação visual.
4. **Growth Mode por Canal:** Seletor canônico e único de Growth Mode (WARMUP / SCALE) por perfil.
5. **Ready Stock:** Indicador de estoque canônico com contagem de vídeos validados e aprovados.
6. **Scheduler / Próximas Publicações:** Próximos horários agendados, tempo restante e estado da fila.
7. **Histórico Recente de Publicações:** Lista de vídeos publicados recentemente com link do YouTube e status terminal (`success`).
8. **Provider Health:** Cartões de conectividade dos provedores configurados (LLM, TTS, YouTube/PFM).
9. **Comandos Essenciais:** Botões "Executar Ciclo Autônomo" e "Executar Coleta Analítica".
10. **Gerenciamento Básico de Canais:** Onboarding de novo canal e edição de metas de estoque.

### Phase 2 (Fase R6 — Operações Avançadas)
- Live Operations com Stepper de 7 estágios e cancelamento seguro de tarefas em andamento.
- Copyright Provenance Audit e aprovação manual de artefatos legados.
- Central de Erros e Linha do Tempo de Observabilidade.
- Formulário de geração manual de vídeo com preview de áudio.
- Modal de publicação manual no YouTube via Post For Me.

### Later (Fase R7+ — Recursos Complementares)
- Repurposing de vídeos longos (Clip Mode).
- Trend Radar e gerador de ideias em lote.
- Configuração avançada de credenciais de provedores e backup/restore de chaves.
- Temas visuais e métricas analíticas avançadas com gráficos.

---

## 10. Migration Phases (Estratégia Gradual de Migração)

```
[ FASE A: API Read-Only ]
        |
        v
[ FASE B: Nova UI Consome Status Read-Only ]
        |
        v
[ FASE C: Adicionar Comandos Simples (Pause/Resume/Cycles) ]
        |
        v
[ FASE D: Migrar Configurações por Perfil (Growth Mode, Autonomia) ]
        |
        v
[ FASE E: Migrar Operações Restantes (Criação de Canais, Geração Manual) ]
        |
        v
[ FASE F: Streamlit Mantido Apenas como Fallback Secundário ]
        |
        v
[ FASE G: Desativação e Remoção Definitiva do Streamlit ]
```

- **FASE A — API Read-Only:** Implementar roteadores FastAPI (`/api/v2/...`) exclusivamente para leitura dos estados operacionais já consolidados no SQLite. Zero risco de mutação.
- **FASE B — Nova UI Read-Only:** Construir a SPA (React + Vite) consumindo a API da Fase A, exibindo o dashboard de monitoramento em paralelo ao Streamlit.
- **FASE C — Comandos Simples e Seguros:** Habilitar endpoints POST para Pause, Resume e disparos de ciclos manuais, com autenticação e validação estrita de instância PRIMARY.
- **FASE D — Configurações por Perfil:** Implementar endpoints PATCH para alteração de Growth Mode e ativação de modo autônomo diretamente por perfil.
- **FASE E — Operações Restantes:** Migrar onboarding de canais, formulário manual e auditoria de copyright.
- **FASE F — Streamlit como Fallback:** Nova Web UI v2 passa a ser a interface padrão no endereço principal. Streamlit fica restrito a uma porta de contingência.
- **FASE G — Desativação do Streamlit:** Após estabilidade comprovada em produção, remover os arquivos legados de `webui/` e dependências exclusivas do Streamlit.

---

## 11. Cleanup Checklist (Checklist Consolidado de Limpeza)

| ID | Área | Problema | Comportamento Atual | Fonte Canônica | Risco | Ação Planejada | Fase Alvo | Status |
| :--- | :--- | :--- | :--- | :--- | :---: | :--- | :---: | :---: |
| **UI-001** | Growth Mode | Seletor global no Streamlit muda display mas não altera o estado operacional dos perfis. | Profile `growth_mode` é o estado real em produção. | Profile `growth_mode` em SQLite | LOW | Eliminar o seletor global na Web UI v2; manter exclusivamente controle por perfil. | R4 / R8 | **OPEN** |
| **UI-002** | Growth Mode | Growth Mode pode ser visualizado ou alterado em múltiplos pontos da interface. | Múltiplos caminhos visuais para conceito único. | `profile_manager.set_profile_growth_mode` | LOW | Mapear controles; criar endpoint único `PATCH /api/v2/channels/{id}/growth-mode`. | R4 / R7 / R8 | **OPEN** |
| **UI-003** | Performance | Interface Streamlit lenta com reruns de página inteira e bloqueio no thread principal. | Script monolítico de 9.994 linhas executado a cada clique. | Arquitetura SPA + API REST assíncrona | LOW (backend) / MED (usabilidade) | Migrar para React + Vite com API FastAPI leve, preservando regras de negócio. | R4 / R5 / R6 / R7 | **OPEN** |
| **UI-004** | Scheduler UI | UI pode exibir status stale de timeout/retry mesmo após publicação confirmada no banco. | Feedback visual desatualizado induz operador ao erro. | SQLite `publication_events.status='success'` | LOW (backend) / MED (operação) | API retornará status terminal canônico consolidado, separando retries transitórios de sucesso final. | R4 / R5 / R6 | **OPEN** |
| **CFG-004** | Publishing | Perfil default possui `external_account_id=NULL` e depende de fallback estático no código. | Publicação funciona por dicionário fixo em `post_for_me.py`. | SQLite `publishing_channels.external_account_id` | LOW | Migrar canal default para binding explícito no banco e descontinuar mapa estático pós-validação. | R4 / R5 / R8 | **OPEN** |

---

## 12. Risks (Riscos e Mitigações)

1. **Risco de Duplicação de Publicação durante a Transição:**
   - *Mitigação:* O backend `scheduler` e o lock `PRIMARY` continuam sendo os únicos pontos autorizados a interagir com provedores de publicação. A nova UI apenas envia comandos para os serviços existentes.
2. **Risco de Divergência de Estado entre UI e Banco:**
   - *Mitigação:* A API não manterá cache com escrita atrasada (write-back). Toda mutação escreve no SQLite e confirma antes de responder à UI.
3. **Risco de Concorrência entre Streamlit e Web UI V2:**
   - *Mitigação:* Ambos consumirão a mesma camada de serviços Python que já utiliza locks transacionais e SQLite com timeout configurado.

---

## 13. Rollback Strategy (Estratégia de Reversão)

- Durante todas as fases de migração até a Fase G, o servidor Streamlit permanece totalmente operacional no backend.
- Caso qualquer anomalia seja detectada na nova interface, basta fechar a aba da Web UI v2 e utilizar o Streamlit normalmente.
- Nenhuma alteração irreversível de banco de dados ou estrutura de arquivos é realizada durante a migração.

---

## 14. Decisions Pending (Decisões Pendentes para Fases Futuras)

1. **Local de Hospedagem dos Arquivos Estáticos da Nova UI:**
   - *Opção 1:* FastAPI serve a build de produção do React via `StaticFiles` na mesma porta HTTP.
   - *Opção 2:* Servidor web leve separado (ex: Nginx local ou Caddy) apontando para a API FastAPI.
   - *Recomendação Preliminar:* Opção 1 (FastAPI serve os arquivos estáticos de `frontend/dist`), mantendo uma única porta e processo único.
2. **Mecanismo de Atualização em Tempo Real:**
   - *Opção 1:* Server-Sent Events (SSE) para stream unidirecional de eventos de log e status.
   - *Opção 2:* Polling curto (intervalo de 2s a 5s) via React Query / SWR.
   - *Recomendação Preliminar:* Polling curto no MVP pela simplicidade e robustez no Windows; SSE na Fase 2 para os logs do stepper.

---

## 15. Phase R5A — Thin Read-Only API MVP (Entregue em 11/10/2026)

### A. Endpoints Implementados (6 GETs)
Todos os endpoints montados em `app/asgi.py` através do roteador central `app/router.py` sob o prefixo `/api/v2`:

1. `GET /api/v2/system/status`:
   - Macro status operacional, instância e estado dos workers.
   - Serviço canônico: `operator_console.get_system_status(profile_id=...)`.
2. `GET /api/v2/profiles`:
   - Lista operacional dos perfis e canais com contagens de estoque e agendamentos.
   - Serviço canônico: `operator_console.get_profile_operations_overview()`.
3. `GET /api/v2/profiles/{profile_id}/status`:
   - Snapshot de um perfil agregando identidade, `growth_mode`, status autônomo, estoque pronto canônico e canais.
   - Retorna HTTP 404 para perfis inexistentes.
   - Serviços canônicos: `profile_manager.get_profile`, `autonomous_production.get_autonomous_status`, `operator_console.get_canonical_ready_stock`.
4. `GET /api/v2/scheduler/posts`:
   - Resumo da fila do scheduler e próximos posts agendados, com parâmetro opcional `profile_id` e `limit` validado (1..100).
   - Serviço canônico: `operator_console.get_scheduler_queue_summary(limit=...)`.
5. `GET /api/v2/publications`:
   - Histórico recente de publicações ordenadas por `id DESC`, com filtro opcional por `profile_id` e `limit` validado (1..100).
   - Evidencia `status='success'` como sucesso terminal canônico (resolvendo UI-004 na camada de API).
   - Serviço canônico: `operator_console.get_recent_publications(limit=..., profile_id=...)`.
6. `GET /api/v2/providers/health`:
   - Diagnóstico passivo de saúde de provedores (FFmpeg, Gemini, Pexels, etc.).
   - Serviço canônico: `operator_console.get_provider_health_summary()`.
   - Zero chamadas externas pagas, zero secrets expostos.

### B. Serviços Canônicos Reutilizados e Novas Funções
- **Reutilizados:**
  - `operator_console.get_system_status()`
  - `operator_console.get_profile_operations_overview()`
  - `operator_console.get_scheduler_queue_summary()`
  - `operator_console.get_canonical_ready_stock()`
  - `operator_console.get_provider_health_summary()`
  - `profile_manager.get_profile()`
  - `profile_manager.list_channels()`
  - `autonomous_production.get_autonomous_status()`
  - `autonomous_production.resolve_autonomous_youtube_channel()`
- **Nova função no service layer:**
  - `operator_console.get_recent_publications(limit=20, profile_id=None, db_path=None)` (função read-only pequena consultando `publication_events`).

### C. Autenticação e Segurança
- Reutiliza canonicamente `app.controllers.base.verify_token` aplicado no roteador `/api/v2` via `Depends(base.verify_token)`.
- Compatível com autenticação opcional quando `api_key` é vazia (desenvolvimento local) e proteção estrita via header `x-api-key` quando configurada.
- Zero secrets ou credenciais retornadas nas respostas.

### D. Limitações Conhecidas
- **Apenas leitura (Read-Only):** Zero endpoints `POST`/`PUT`/`PATCH`/`DELETE` implementados nesta fase. Operações mutantes (pause, resume, run cycle, alteração de growth mode) permanecem na UI Streamlit até a Fase R6.
- **Filtragem de Scheduler por Perfil:** A função `operator_console.get_scheduler_queue_summary` retorna métricas agregadas globais; o filtro `profile_id` nesta fase atua sobre a lista de `upcoming_posts` sem alterar as contagens globais para evitar refatoração prematura do service layer.
- **CFG-004 Preservado:** Perfil default continua operando com `external_account_id=NULL` e fallback estático em `post_for_me.py` sem impacto funcional.

### E. Validação e Impacto em Produção
- Teste unitário direcionado: `test/services/test_api_v2_readonly.py` (8 testes aprovados, cobrindo rotas, imutabilidade, 404, validação 400, autenticação, sanitização e status terminal).
- Zero impacto no banco de dados SQLite operacional (schema inalterado).
- Zero impacto no piloto autônomo em execução no canal *Dose Diária De Internet*.

---

## 16. Phase R5B — Live Multi-Channel Execution Contract / UI-005 (Entregue em 11/10/2026)

### A. Registro Formal: UI-005 — Live Multi-Channel Execution Graph

- **ITEM:** `UI-005`
- **TITLE:** `LIVE MULTI-CHANNEL EXECUTION GRAPH`
- **PRIORITY:** `P0 / MVP`
- **OBJECTIVE:** Provide a real-time visual representation of what every autonomous channel is currently doing and which canonical backend component/provider owns the current execution step.
- **PRIMARY SCREEN:** `FACTORY LIVE`

#### 1. Princípio Arquitetural
- `BACKEND = SOURCE OF TRUTH`
- `FRONTEND = PRESENTATION ONLY`
- O frontend nunca deverá inventar stage, progress ou status.
- **Regra de Não-Inferência Estrita:** Se o backend conhece apenas `state=PROCESSING` e `progress=40%`, a API retorna `pipeline_stage=null` e `pipeline_stage_label=null`. É terminantemente proibido inferir `stage="VISUALS"` baseando-se em heurísticas ou porcentagens.

#### 2. Pipeline Primário Canônico (12 Estágios)
O grafo de execução modela o ciclo de vida completo de cada vídeo gerado:
```
TOPIC → SCRIPT → NARRATION → VISUALS → RENDER → SAFETY → QUALITY → COPYRIGHT → READY STOCK → SCHEDULER → PUBLISHER → YOUTUBE
```

#### 3. Estados Visuais Canônicos Permitidos
- `PENDING`
- `RUNNING`
- `SUCCESS`
- `WAITING`
- `SCHEDULED`
- `RETRYING`
- `BLOCKED`
- `FAILED`
- `IDLE`

#### 4. Campos Expostos por Task / Canal
Cada execução expõe canonicamente:
- `task_id` (identificador único da task em processamento ou aguardando)
- `profile_id` (identificador do perfil)
- `profile_name` (nome do canal/perfil)
- `channel_id` (identificador do canal YouTube)
- `channel_name` (nome legível do canal)
- `topic` (assunto do vídeo / título)
- `pipeline_stage` (código normalizado do estágio canônico: `TOPIC`, `SCRIPT`, `NARRATION`, etc., ou `null`)
- `pipeline_stage_label` (label legível para apresentação na UI)
- `status` (`PENDING`, `RUNNING`, `SUCCESS`, `WAITING`, `SCHEDULED`, `RETRYING`, `BLOCKED`, `FAILED`, `IDLE`)
- `progress` (0 a 100 inteiro)
- `component` (componente backend dono da etapa: `autonomous_production`, `task`, `scheduler`, `publisher`, `quality_score`, etc.)
- `provider` (provedor ativo: `edge_tts`, `gemini`, `ffmpeg`, `post_for_me`, etc., quando houver evidência real)
- `started_at` / `updated_at` (timestamps ISO ou epoch)
- `elapsed_seconds` (tempo decorrido calculado quando disponível)
- `message` (mensagem legível de progresso ou erro)
- `retry_state` (`null` ou objeto com contagem e tentativas de retry)
- `fallback_state` (`null` ou indicador de fallback ativo)
- `next_stage` (próxima etapa lógica esperada)
- `error` (mensagem de falha quando em estado FAILED ou BLOCKED)
- `publication_state` (snapshot do estado de publicação no YouTube quando aplicável)

---

### B. Auditoria Streamlit — Descoberta de Inferências Legadas (Stepper)

Durante a auditoria de `webui/components/operator_console.py` (linhas 420-435), foi identificado que para qualquer tarefa em estado real `PROCESSING`, o Stepper da UI legada utilizava valores genéricos e inferidos hardcoded:
```python
# CÓDIGO LEGADO AUDITADO NO STREAMLIT (NÃO-CANÔNICO):
stage = "Processando etapa do pipeline"
stage_idx = 4
progress = int(t.get("progress") or 50)
safety_status = t.get("safety_status") or "PASS"
quality_score = t.get("quality_score") or 75
```
**Decisão Arquitetural:**
Essa inferência arbitrária do Streamlit foi classificada como apresentação legada enganosa. A Web UI V2 **rejeita categoricamente** essas inferências. Se um dado não estiver explicitamente gravado na tarefa ou nos eventos operacionais, ele é retornado como `null` e exibido na UI como "Não reportado / Em processamento".

---

### C. Matriz de Cobertura de Telemetria (12 Estágios Canônicos)

| PIPELINE_STAGE | CURRENT_SOURCE | CURRENT_FIELD/EVENT | REAL_OR_INFERRED | PROVIDER_AVAILABLE | TIMING_AVAILABLE | GAP | ACTION |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **TOPIC** | `autonomous_production` / `tasks` | `tasks.video_subject`, `video_script` | REAL | SIM (`gemini` / `deepseek` / `manual`) | SIM (`tasks.created_at`) | Nenhum | `CANONICAL_NOW` |
| **SCRIPT** | `tasks` / `storage/tasks/*/script.json` | `task.video_script` | PARTIAL | SIM (config do LLM) | SIM (`task.created_at`) | Durante a geração ao vivo, a sub-etapa in-flight não atualiza campo `stage` persistido | `PARTIAL` (expor quando gerado; gap de instrumentação in-flight) |
| **NARRATION** | `tasks` / `storage/tasks/*/audio.mp3` | Presença de áudio em storage / eventos | PARTIAL | SIM (`edge_tts`, `azure`, `cosyvoice`) | SIM (`operational_events`) | Sub-etapa de áudio em andamento não possui callback gravando `task['stage'] = 'tts'` em tempo real | `PARTIAL` |
| **VISUALS** | `tasks` / `flow_manifest` / `material` | Materiais locais / storage | PARTIAL | SIM (`pexels`, `pixabay`, `flow`) | SIM (`operational_events`) | Coleta e download de vídeo em andamento sem status granular persistido no banco | `PARTIAL` |
| **RENDER** | `tasks` / `operational_events` | `tasks.state='PROCESSING'/'COMPLETE'` | REAL | SIM (`ffmpeg` / `moviepy`) | SIM (`operational_events`, `task.created_at`) | Nenhum | `CANONICAL_NOW` |
| **SAFETY** | `tasks` / `operational_events` | `tasks.safety_status`, `safety_details` | REAL | SIM (`gemini` / `rule_engine`) | SIM (`operational_events`) | Nenhum | `CANONICAL_NOW` |
| **QUALITY** | `tasks` / `operational_events` | `tasks.quality_score`, `quality_details` | REAL | SIM (`internal_scorer`) | SIM (`operational_events`) | Nenhum | `CANONICAL_NOW` |
| **COPYRIGHT** | `tasks` / `operational_events` | `tasks.copyright_status`, `copyright_manifest` | REAL | SIM (`provenance_engine`) | SIM (`operational_events`) | Nenhum | `CANONICAL_NOW` |
| **READY_STOCK** | `operator_console` / `tasks` | `tasks.state=1` + arquivo `final-1.mp4` verificado | REAL | NÃO (local filesystem / sqlite) | SIM (`task.created_at`) | Nenhum | `CANONICAL_NOW` |
| **SCHEDULER** | `scheduled_posts` | `scheduled_posts.status`, `scheduled_at` | REAL | SIM (`scheduler_worker`) | SIM (`scheduled_posts.created_at`, `scheduled_at`) | Nenhum | `CANONICAL_NOW` |
| **PUBLISHER** | `scheduled_posts` / `publication_events` | `scheduled_posts.status='retrying'`, `last_error` | REAL | SIM (`post_for_me` / `youtube_api`) | SIM (`scheduled_posts.updated_at`) | Nenhum | `CANONICAL_NOW` |
| **YOUTUBE** | `publication_events` | `publication_events.status='success'`, `video_url` | REAL | SIM (`post_for_me` / `youtube`) | SIM (`publication_events.created_at`) | Nenhum | `CANONICAL_NOW` |

#### Resumo de Classificação dos Estágios:
- **CANONICAL_NOW (9 estágios):** `TOPIC`, `RENDER`, `SAFETY`, `QUALITY`, `COPYRIGHT`, `READY_STOCK`, `SCHEDULER`, `PUBLISHER`, `YOUTUBE`.
- **PARTIAL (3 estágios):** `SCRIPT`, `NARRATION`, `VISUALS` (os artefatos finais são reais e persistidos, mas durante o processamento em tempo real o backend não persiste a sub-etapa ativa na task, apenas em logs).
- **MISSING (0 estágios):** Nenhuma etapa é fabricada ou inexistente.

---

### D. Endpoints Implementados (2 Novos GETs)

Ambos montados em `/api/v2/executions`:

#### 1. `GET /api/v2/executions/live`
- **Objetivo:** Fornecer visão agregada multicanal em tempo real para a tela Factory Live.
- **Serviço Canônico:** `operator_console.get_live_execution_overview(db_path=None)`.
- **Comportamento:**
  - Itera sobre todos os perfis ativos;
  - Resolve se o perfil possui task em execução ativa (`autonomous_current_task_id`), task aguardando pós-geração (`autonomous_waiting_task_id`), ou post agendado/publicado recente;
  - Se não houver atividade, retorna `status='IDLE'` limpo;
  - Se houver task em processamento, extrai apenas dados reais persistidos (zero inferência);
  - **Resolução Canônica de UI-004:** Sucesso terminal em `publication_events` (`status='success'`) tem precedência absoluta sobre retries antigos ou mensagens de timeout em `scheduled_posts`;
  - Performance: Zero chamadas externas pagas, zero locks concorrentes, query leve otimizada para polling de 2–5 segundos na futura UI.

#### 2. `GET /api/v2/executions/{task_id}`
- **Objetivo:** Traço causal detalhado de uma tarefa específica ("Quem chamou quem").
- **Serviço Canônico:** `operator_console.get_execution_detail(task_id, db_path=None)`.
- **Trace Causal Reconstruído com Fatos Existentes:**
  - `CHANNEL`: Perfil e canal de destino associados à task;
  - `TRIGGER / AUTONOMOUS_PRODUCTION`: Identifica se a tarefa foi disparada pelo Autonomous Worker (compara com `autonomous_current_task_id` ou `autonomous_waiting_task_id`) ou submetida via manual/webui;
  - `COMPONENT`: Componente backend responsável pelo estágio atual (`task_service`, `scheduler`, `publisher`, `quality_score`);
  - `PROVIDER`: Provedor real registrado nos metadados ou na configuração;
  - `RESULT`: Estado terminal consolidado (Gates, Ready Stock, Publicação);
  - `TIMELINE`: Timeline cronológica de eventos operacionais reais registrados para a task;
  - `SCHEDULER & PUBLICATION`: Detalhes dos registros em `scheduled_posts` e `publication_events`.

---

### E. Validação e Impacto em Produção
- **Arquivo de Teste Estendido:** `test/services/test_api_v2_readonly.py` (total de 15 testes aprovados: 8 da R5A + 7 da R5B).
- **Garantias Validadas nos Testes:**
  - `/api/v2/executions/live` e `/api/v2/executions/{task_id}` retornam HTTP 200 e dados estruturados;
  - Métodos mutantes (`POST`, `PUT`, `DELETE`) retornam HTTP 405 Method Not Allowed;
  - Tasks são isoladas por profile/channel correspondente;
  - Estágios reais persistidos são normalizados fielmente;
  - Estágios ausentes NÃO são adivinhados (retornam `null`);
  - Sucesso terminal em `publication_events` sobrepõe status de retry antigo em `scheduled_posts`;
  - Perfis ociosos retornam `IDLE` de forma limpa;
  - Zero secrets expostos nas respostas.
- **Produção:**
  - Zero impacto no banco de dados SQLite operacional (schema inalterado).
  - Zero alteração no piloto autônomo em execução no PC Forte.

---

## 17. Phase R6A — Web UI V2 / Factory Live MVP (Entregue em 11/10/2026)

### A. Objetivo & Escopo Entregue
Implementação da primeira interface real desacoplada da Web UI V2, focada exclusivamente na observabilidade visual em tempo real através da tela **FACTORY LIVE**.

- **Princípio:** `BACKEND = SOURCE OF TRUTH / FRONTEND = PRESENTATION ONLY`.
- **Diretório Frontend Isolado:** `webui-v2/`.
- **Tecnologias:** React 18, Vite 6, `@xyflow/react` v12, Vanilla CSS.
- **Zero Dependências Pesadas:** Sem Tailwind, shadcn, Material UI, Bootstrap, Redux, Zustand, React Query, Axios ou bibliotecas externas de ícones/gráficos. Uso exclusivo de `fetch()` nativo do navegador.

### B. Arquitetura do Frontend
```
webui-v2/
  ├── package.json
  ├── vite.config.js       # Proxy /api -> http://127.0.0.1:8080 (zero CORS no DEV)
  ├── index.html           # Dark dashboard HTML shell
  ├── .gitignore           # Exclui node_modules e dist
  └── src/
      ├── main.jsx         # React DOM bootstrap
      ├── App.jsx          # Polling loop (3s), gerenciamento de estado e layout
      ├── api.js           # Cliente HTTP nativo para endpoints /api/v2/...
      ├── styles.css       # Design system dark dashboard (tokens de status, grid e drawer)
      └── components/
          ├── FactoryHeader.jsx      # Top bar (saúde da fábrica, workers, última sincronização)
          ├── ChannelCard.jsx        # Deck dinâmico de cards por canal/perfil
          ├── FactoryLiveGraph.jsx   # Canvas único React Flow com Lanes horizontais por canal
          ├── ExecutionNode.jsx      # Nós visuais dos 12 estágios do pipeline com não-inferência estrita
          ├── LaneHeaderNode.jsx     # Âncora lateral esquerda de identificação do canal
          └── ExecutionDrawer.jsx    # Painel lateral com trace causal ("Quem chamou quem") e timeline
```

### C. Telas & Componentes Funcionais

1. **Factory Header (`FactoryHeader.jsx`):**
   - Exibe status da fábrica (Online/Pausada), Worker, Scheduler, Auto Publish e Dry Run.
   - Timestamp de última atualização em tempo real com botão de refresh manual.
   - Banner de resiliência: se a API ficar offline, o frontend **não quebra** e mantém o último snapshot válido em memória, exibindo aviso claro de offline.

2. **Deck de Canais (`ChannelCard.jsx`):**
   - Renderização 100% dinâmica a partir do endpoint `/api/v2/executions/live` (zero canais hardcoded).
   - Exibe nome do canal, badge autônomo, Growth Mode (`Warmup`/`Scale`), contagem de estoque pronto e resumo da task ativa ou estado `IDLE`.
   - Interativo: clicar em um canal foca a execução no drawer lateral.

3. **Grafo de Execução Multicanal (`FactoryLiveGraph.jsx`):**
   - Instanciado em um **único canvas** React Flow (evitando múltiplos canvas concorrentes).
   - Cada canal é modelado como uma **Lane horizontal independente**, com nó de cabeçalho à esquerda seguido pelos 12 nós do pipeline canônico:
     `TOPIC → SCRIPT → NARRATION → VISUALS → RENDER → SAFETY → QUALITY → COPYRIGHT → READY_STOCK → SCHEDULER → PUBLISHER → YOUTUBE`.
   - Grafo configurado estritamente para visualização: `nodesDraggable=false`, `nodesConnectable=false`. Zoom e pan livres.

4. **Regra Estrita de Não-Inferência Mantida no Frontend:**
   - Nenhum percentual de progresso é mapeado arbitrariamente para estágios do pipeline.
   - Apenas estágios com telemetria explícita do backend recebem destaque ativo (`RUNNING`, `SUCCESS`, etc.).
   - Estágios `SCRIPT`, `NARRATION` e `VISUALS` sem callback granular in-flight exibem mensagem explícita: *"Sub-etapa ainda não instrumentada"*.
   - Se o backend reportar `pipeline_stage=null`, a interface exibe: *"Etapa detalhada não informada pelo backend"*.

5. **Drawer de Execução Causal (`ExecutionDrawer.jsx`):**
   - Painel lateral deslizante acionado ao clicar em qualquer canal, task ou nó do pipeline.
   - Exibe snapshot completo: IDs, tema, status, componente, provedor, tempo decorrido, erros e mensagens.
   - **Trace Causal ("Quem chamou quem"):**
     `CANAL` ↓ `AUTONOMOUS_PRODUCTION` ↓ `COMPONENTE` ↓ `PROVEDOR` ↓ `RESULTADO` ↓ `PRÓXIMA ETAPA`.
   - **Prioridade Terminal de Publicação (UI-004):** Se `publication_events.status='success'`, exibe confirmação definitiva de publicação no YouTube com link direto (`video_url`), sem exibir alertas stale de retry.
   - Linha do tempo cronológica com eventos operacionais obtidos de `GET /api/v2/executions/{task_id}`.

### D. Validação de Build
- Validação executada: `npm run build` dentro de `webui-v2/`.
- Resultado: **PASS** (195 módulos compilados em 21.74s, zero erros, bundle otimizado de 112 kB gzip).
- Zero alterações no backend, zero endpoints WRITE criados, zero migrations de SQLite.
- Streamlit permanece 100% intacto em `webui/Main.py` como fallback operacional.

---

### E. Refinamento de Layout Visual (Fase R6A.2 — Homologação Operacional)

Após validação visual do operador, o layout linear contínuo de 12 estágios foi refatorado para otimizar leitura imediata sem necessidade de pan/zoom contínuo:

1. **Pipeline Layout em 2 Linhas x 6 Estágios (Snake Layout):**
   - **Row 1 (Esquerda → Direita):**
     `① TOPIC → ② SCRIPT → ③ NARRATION → ④ VISUALS → ⑤ RENDER → ⑥ SAFETY`
   - **Conexão Vertical:**
     `⑥ SAFETY ↓ ⑦ QUALITY`
   - **Row 2 (Direita → Esquerda):**
     `⑫ YOUTUBE ← ⑪ PUBLISHER ← ⑩ SCHEDULER ← ⑨ READY_STOCK ← ⑧ COPYRIGHT ← ⑦ QUALITY`
   - Edges direcionais explícitas com setas pontilhando/indicando inequívoca sequência `1 → 2 → ... → 12`.

2. **Identidade do Canal:**
   - Prioriza `profile_name` como identidade primária destacada (ex.: *Dose Diária de Internet* / *Video Factory Default*).
   - Nome do canal e identificador da plataforma aparecem como subtítulo secundário (ex.: *YouTube (Default) • channel-default-youtube*).

3. **Dimensões e Legibilidade dos Nodes:**
   - Nós redimensionados confortavelmente para 180px × 88px, exibindo:
     - Badge com número ordinal da etapa (`#1` .. `#12`);
     - Código canônico do estágio (`NARRATION`);
     - Label em português (`Narração`);
     - Status destacado (`RUNNING`, `SUCCESS`, `PENDING`, `IDLE`);
     - Provedor ativo e barra de progresso quando disponíveis.

4. **Destaque do Status Ativo (`RUNNING`):**
   - Borda espessa âmbar (2px), glow discreto e ponto pulsante de execução em tempo real.

5. **Remoção do MiniMap & Altura Dinâmica:**
   - MiniMap removido para eliminar obstrução visual.
 
---

### F. R6A.3 — Identidade Visual, Métricas Reais e Live Multicanal (DEV IMPLEMENTED)

1. **Auditoria Multicanal e Dynamic Rendering:**
   - Auditoria nos perfis de canal:
     - `Dose Diária De Internet` (`default` / `channel-default-youtube`): ativo e renderizado no endpoint.
     - `Dose Diária de Histórias e Mistério` (`profile-historias-misterio` / `channel-historias-misterio-youtube`): cadastrado via mecanismo canônico idempotente `ensure_second_channel_profile()` em DEV.
     - `Dose Diária de GTA VI` (`profile-2095da4fbe23`): legado de produção, ausente de definição canônica em DEV; classificado estritamente como `DEV_DATA_MISSING` (zero dados falsos/segredos criados).
   - O Channels Deck e o Factory Live Graph renderizam dinamicamente N canais retornados pelo backend (zero hardcode de quantidade ou nomes em JSX).

2. **Identidade Visual e Mapeamento Centralizado:**
   - Mapeamento centralizado de estágios e cores em `stageVisuals.js`:
     - Temas semânticos de status: `RUNNING` (azul ativo / borda destacada), `SUCCESS`/`COMPLETE` (verde), `RETRY`/`COOLDOWN` (laranja), `BLOCKED` (âmbar), `FAILED` (vermelho), `IDLE` (cinza azulado).
     - Categorias com pips discretos e ícones: Topic/Script (texto), Narração (mic), Visuals/Render (filme/render), Safety/Quality/Copyright (escudo/check/copyright), Stock/Scheduler (estoque/relógio), Publisher/YouTube (upload/play).
     - Remoção de pulsação contínua pesada; microinterações suaves.

3. **Métricas Estritas (Fail-Closed):**
   - **Ready Stock:** Exibe percentual factual somente quando `target_stock > 0` (`min(100, (ready_stock / target_stock) * 100)`), com mini progress bar discreta e cores semânticas (verde se 100%, azul/âmbar se parcial, cinza/âmbar se 0). Denominador ausente ou <= 0 oculta percentual.
   - **Pipeline Progress:** Calculado estritamente por estágios em estado terminal positivo real (`SUCCESS` ou `COMPLETE`). Se 0 estágios concluídos, percentual omitido.
   - **Google Flow:** Saldo absoluto verificado exibido (`164 créditos` / `1.050 créditos`, total `1.214 créditos conhecidos`). Zero inferência de percentual de plano ou denominador falso (sem `credits / 1000`). Barra visual estritamente qualitativa.

4. **Navegação Estável:**
   - Desativado qualquer auto-zoom, recenter automático, `fitView` ou reposicionamento acionado pelo ciclo de polling (~3s).
   - Viewport permanece estável durante toda a operação.

---

### G. FASE R6A.5 — Factory Live Visual Identity System + Single-Focus Pipeline (DEV IMPLEMENTED)

1. **Single-Focus Pipeline Architecture (Escalabilidade Extrema):**
   - O grafo de execução inferior (`FactoryLiveGraph`) renderiza estritamente **1 pipeline detalhado por vez**, desacoplando a quantidade N de canais do tamanho do canvas.
   - Resolução determinística de seleção:
     - 1. Seleção manual do operador (clique no card superior ou botão "Ver Pipeline");
     - 2. Fallback dinâmico: canal com task ativa `RUNNING`;
     - 3. Fallback estático: primeiro canal da lista (`channels[0]`).
   - Cards do Channels Deck ganham destaque ativo em foco (`active-focused`, borda ciano/neon, badge `● EM FOCO` e background gradiente).

2. **Preenchimento Tonal e Linguagem Visual por Etapa:**
   - Eliminação de caixas neutras: cada uma das 12 etapas recebeu tonal background (`tonalBg`) e borda tonal (`tonalBorder`) exclusivas integradas à paleta da etapa (indigo, violeta, fúcsia, ciano, âmbar, esmeralda, topázio, teal, cobalto, rubi).
   - O status operacional (`RUNNING`, `SUCCESS`, `BLOCKED`, `FAILED`, `IDLE`) atua como modulador semântico de primeiro nível.

3. **Autonomous Agent Persona System (Mascotes/Bots Tech-Factory):**
   - Mapeamento de 12 agentes operacionais especializados:
     - `Scout-01` (Ideator / Radar de Tendências) — `💡 / 🧭`
     - `Scribe-02` (Roteirista Algorítmico) — `📝 / 🖋️`
     - `Vocal-03` (Sintetizador de Voz) — `🎙️ / 🎧`
     - `Cine-04` (Diretor Visual Flow) — `🎬 / 🎥`
     - `Forge-05` (Motor de Render GPU) — `⚡ / ⚙️`
     - `Sentinel-06` (Guardião de Políticas) — `🛡️`
     - `Auditor-07` (Avaliador de Retenção) — `✨ / 💎`
     - `Notary-08` (Custodiante de Autoria) — `⚖️ / 📜`
     - `Vault-09` (Guarda-Estoque) — `📦 / 🗄️`
     - `Chronos-10` (Despachante Temporal) — `📅 / ⏱️`
     - `Relay-11` (Transmissor Multi-Rede) — `🚀 / 🛰️`
     - `Herald-12` (Embaixador do Canal) — `▶️ / 📺`
   - Chips de persona integrados a cada nó (`node-persona-chip`) e cards detalhados no drawer lateral (`agent-persona-card`).

4. **Conexões / Edges com Semântica de Estado:**
   - Edges dinâmicas baseadas na transição real de estados:
     - `RUNNING`: ciano vivo (`#38bdf8`), animado com efeito de fluxo, drop-shadow neon;
     - `COMPLETED`: verde esmeralda (`#10b981`), traço contínuo sólido;
     - `BLOCKED` / `WAITING`: âmbar (`#f59e0b`), traço tracejado;
     - `FAILED`: vermelho (`#ef4444`), traço sólido;
     - `DIMMED` / `PENDING`: ardósia escuro (`#334155`), traço sutil e discreto.

5. **Upgrade Visual da Seção Google Flow:**
   - Estilização em formato "AI Compute Vault".
   - Tipografia de alto impacto para saldo numérico verificado (`balance-number` com glow ciano).
   - Gauge qualitativo e slot preparado para futura cota/capacidade percentual quando houver denominador canônico.
   - Total verificado de 1.214 créditos em destaque.

---

### H. FASES R9.1, R9.2, R9.3 e R10 — Plano Canônico de Fechamento da Web UI V2

1. **R9.1 — Live Pipeline Telemetry Consolidation (DEV VALIDATED):**
   - **Checkpoints Determinísticos:** Gravação explícita de `stage` em `app/services/task.py` em cada fase (`TOPIC`, `SCRIPT`, `NARRATION`, `VISUALS`, `RENDER`, `READY_STOCK`), além de `_mark_task_failed(stage=...)`.
   - **Provedor Factual:** Resolução precisa da conta utilizada no Google Flow (`flow_account_id`), FFmpeg e engine TTS, expostos no payload read-only do `/api/v2/executions/live`.
   - **Desacoplamento de Gates:** Separação estrita entre progressão mecânica de etapas e aprovação factual de Gates (Safety, Quality, Copyright). Gates permanecem `PENDING` até a verificação factual de seus vereditos e scores em `execution.gates`, nunca sendo promovidos a `SUCCESS` meramente por avanço da tarefa.
   - **Correção do Estado IDLE:** Canais sem tarefas em execução permanecem com nós 1..8 em `IDLE` (0% de progresso concluído), com o nó `READY_STOCK` refletindo estritamente o inventário real sem falso progresso prévio.

2. **R9.2 — Multi-Channel Operations & UX Consolidation (DEV VALIDATED):**
   - **Foco Persistente & Rastreamento Inteligente:** Implementação de toggle no header do Factory Live permitindo alternar entre "Foco Manual" (preservando o canal selecionado pelo operador durante o polling de 3s) e "Rastreamento Dinâmico Ativo" (acompanhando automaticamente qualquer canal com processamento ativo).
   - **Sanitização de HTML Bruto:** Utilização universal da função `sanitizeDisplayText(str)` em `ChannelCard`, `ExecutionDrawer`, `LaneHeaderNode` e `AgentOpsView`, eliminando exibição acidental de tags HTML brutas em erros, logs ou títulos.
   - **Cards Factuais de Gates no Drawer:** Exibição dedicada no `ExecutionDrawer` dos status individuais de Safety, Quality Score (com indicação do threshold $\ge 70.0$) e Copyright.
   - **Estados de Publicação:** Suporte visual completo aos estados `SCHEDULED` e `RETRYING` no grafo e no drawer.
   - **Acessibilidade e Fluidez:** Respeito absoluto a `prefers-reduced-motion` e atualização sem flicker.

3. **R9.3 — E2E Smoke & Edge Cases Validation (DEV PENDING):**
   - Validação E2E em DEV com fixtures simulando transições multicanal completas.
   - Verificação visual de cenários de erro do pool Flow (`AUTH_FAILED`, `LOW_CREDITS`, `COOLDOWN`).
   - Smoke test de responsividade e Drawer de Execução sem disparar tarefas reais nem consumir créditos.

4. **R10 — Controlled Production Rollout Package (PROD PENDING):**
   - Execução do deploy em produção no PC Forte na porta 8080 (`scripts/start_webui_v2.ps1`).
   - Servidor FastAPI servindo os assets compilados do `webui-v2/dist` via `SPAStaticFiles`.
   - Streamlit original preservado na porta 8501 como fallback operacional.
   - Transição assistida e homologada com o operador.


