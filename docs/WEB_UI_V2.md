# Web UI V2 — Especificação Técnica de Migração e Auditoria Streamlit

## Status
`DISCOVERY / READ-ONLY AUDIT (Fase R4A)`

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
