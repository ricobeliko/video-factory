# Video Factory V2 — Matriz de Paridade Funcional e Auditoria de Transição
**Documento de Paridade e Auditoria V2.14**
**Data de Atualização:** 18/10/2026
**Ambiente:** Isolado (V2 Worktree: eat/video-factory-v2)

---

## 1. Matriz de Equivalência Streamlit -> Video Factory V2

Esta matriz atesta a substituição rigorosa de cada funcionalidade do Streamlit legado pela arquitetura SPA React + FastAPI da V2. Não se aceitam botões visuais sem validação de ponta a ponta.

| Operação Streamlit | Equivalente V2 | Endpoint FastAPI | Serviço Python Reutilizado | Persistência (SQLite / Disco) | Controle de Autorização | Teste Funcional | Componente da UI V2 |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **1. Channel Factory & Edição** | Gestão Unificada de Canais | POST /api/v2/channels, PATCH /api/v2/channels/{id}/settings | pp/services/profile_manager.py | content_profiles (settings_json), publishing_channels | 
equire_primary_instance | 	est_web_ui_v2_api.py | ChannelListView, CreateChannelModal, ChannelDetailView |
| **2. Destinos Multiprojeto (PFM)** | Configuração de Vínculos Post for Me | GET /api/v2/channels, GET /api/v2/providers/health | pp/services/post_for_me.py | publishing_channels(project_id, external_account_id) | 
equire_primary_instance | 	est_v2_13_migration_rehearsal.py | ChannelDetailView (Aba Publicação) |
| **3. Configurações de Voz** | Seletor e Sliders de Voz Neural | PATCH /api/v2/channels/{id}/settings | pp/services/voice.py, profile_manager.py | content_profiles.settings_json -> voice | 
equire_primary_instance | 	est_web_ui_v2_api.py | ChannelDetailView (Aba Vídeo & Áudio) |
| **4. Quiz Q0-R & Papel P1.3** | Formulários Inteligentes por Formato | GET /api/v2/templates, PATCH /api/v2/channels/{id}/settings | pp/services/quiz_engine.py, quiz_paper_engine.py | content_profiles.settings_json -> editorial.video_format | 
equire_primary_instance | 	est_hotfix_autonomous_cycle_busy.py (
ejected_struct) | CreateChannelModal, ChannelDetailView |
| **5. Produção Manual & Autônoma** | Disparo de Ciclos e Toggle de Autonomia | POST /api/v2/factory/run-cycle, POST /api/v2/channels/{id}/autonomous/enable | pp/services/autonomous_production.py, 	ask.py | utopilot_settings, instance_locks, content_profiles | 
equire_primary_instance, Lock _cycle_lock (HTTP 409 se busy) | 	est_hotfix_autonomous_cycle_busy.py, 	est_web_ui_v2_api.py | FactoryHeader, ExecutionDrawer, ChannelDetailView |
| **6. Estoque de Vídeos** | Gestão de Buffer e Estoque Alvo | GET /api/v2/channels/{id}/status, PATCH /api/v2/channels/{id}/quotas | pp/services/operator_console.py | storage/tasks/{id}/, scheduled_posts | Leitura livre; mutação com 
equire_primary_instance | 	est_web_ui_v2_api.py | DashboardView (KPI Estoque), ChannelDetailView (Aba Estoque) |
| **7. Revisão & Aprovação (QG)** | Central de Curadoria Humana | GET /api/v2/review/tasks, POST /api/v2/review/tasks/{id}/approve, /reject | pp/services/quality_recovery.py | operator_video_reviews, operator_review_commands | 
equire_primary_instance | 	est_video_review_ui_v2.py | VideoReviewView (Player com seek de bytes, Aprovar/Rejeitar) |
| **8. Agendamentos** | Calendário e Fila de Publicações | GET /api/v2/scheduler/posts, PATCH /api/v2/channels/{id}/schedule | pp/services/scheduler.py | scheduled_posts (idx_active_schedule_v2) | 
equire_primary_instance | 	est_web_ui_v2_api.py | ScheduleView, ChannelDetailView (Aba Automação) |
| **9. Publicação Externa** | Despacho Idempotente e Confiabilidade | GET /api/v2/publications, GET /api/v2/providers/health | pp/services/scheduler.py, publishing_idempotency.py | publication_events | 
equire_primary_instance, fail-closed em DEV_V2 | 	est_publishing_health_audit.py | ChannelDetailView (Aba Publicação), SettingsView |
| **10. Status & Histórico** | Telemetria e Grafo de Execuções | GET /api/v2/system/status, GET /api/v2/executions/live | pp/services/operator_console.py | operational_events, instance_locks | Leitura livre | 	est_web_ui_v2_api.py | DashboardView, FactoryLiveGraph, ExecutionDrawer |
| **11. Recuperação de Tarefas Órfãs** | Reconciliação Pós-Restart | Ciclo de Inicialização / POST /api/v2/factory/run-cycle | pp/services/operator_console.py (
econcile_orphaned_tasks) | operator_video_reviews, storage/tasks | 
equire_primary_instance | 	est_hotfix_autonomous_cycle_busy.py | DashboardView (Alerta de órfãs), VideoReviewView |
| **12. Analytics de Desempenho** | Coleta e Exibição de Métricas | /api/v2/analytics, GET /api/v2/channels | pp/services/analytics.py, nalytics_scheduler.py | content_analytics | Leitura livre | 	est_analytics.py | AnalyticsView |
| **13. Configurações Operacionais** | Painel de Diagnóstico & Pausa | GET /api/v2/agent-ops, POST /api/v2/factory/pause, /resume | pp/services/operator_console.py | utopilot_settings, operational_events | 
equire_primary_instance | 	est_web_ui_v2_api.py | SettingsView (Agent Ops Room, Pausa de Emergência) |
| **14. Proteção PRIMARY / Concorrência** | Single Primary Lock & Worker Daemon | Endpoints de mutação (
equire_primary_instance) | pp/services/operator_console.py, scheduler.py | instance_locks | Lock atômico em SQLite (DEFAULT_INSTANCE_LOCK_KEY) | 	est_single_instance.py, 	est_v2_isolation.py | FactoryHeader (Badges PRIMARY/SECONDARY) |

---

## 2. Conclusão da Auditoria de Paridade

- **Total de operações homologadas:** 14/14 (100%).
- **Fidelidade arquitetural:** 100% dos motores Python de negócio (FFmpeg, Quiz, Idempotência, TTS, Review) permanecem idênticos e testados.
- **Eliminação do Streamlit:** O frontend monolítico de 10.000 linhas foi substituído integralmente sem perda funcional.
