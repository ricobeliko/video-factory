# Video Factory V2 — Matriz de Paridade Funcional
**Documento de Paridade V2.6**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Matriz de Equivalência Streamlit ➔ Video Factory V2

| Funcionalidade Streamlit | Equivalente Video Factory V2 | Endpoint / Serviço Utilizado | Status | Validação / Teste |
| :--- | :--- | :--- | :--- | :--- |
| **Grid de Geração Principal (4 Colunas)** | Channel Workspace & Smart Form por Formato | `/api/v2/channels`, `/api/v2/templates` | **MIGRADO** | Componente `CreateChannelModal` e `ChannelDetailView` |
| **Channel Factory (Cadastro de Canais)** | `ChannelListView` + `CreateChannelModal` | `POST /api/v2/channels`, `profile_manager.py` | **MIGRADO** | Rota FastAPI testada e funcional |
| **Console do Operador (Métricas & Estoque)** | Dashboard V2 & Metrics Grid | `GET /api/v2/operations/system/status` | **MIGRADO** | Polling assíncrono em `App.jsx` |
| **Monitoramento de Tarefas em Tempo Real** | `FactoryLiveGraph` (Grafo Dinâmico Snake 2x6) | `GET /api/v2/operations/executions/live` | **MIGRADO** | Visualização em tempo real via SVG / React Flow |
| **Logs Detalhados de Tarefas** | `ExecutionDrawer` Lateral Desacoplado | `GET /api/v2/operations/executions/{task_id}` | **MIGRADO** | Drawer com telemetria de LLM, TTS, Clipes e FFmpeg |
| **Revisão Humana de Vídeos** | `VideoReviewView` com Player Integrado | `/api/v2/review/tasks`, `/video` (Streaming) | **MIGRADO** | Streaming seguro com suporte a seek de bytes |
| **Aprovação / Descarte para Estoque** | Botões de 1 clique na Central de Revisão | `POST /api/v2/review/tasks/{id}/approve` | **MIGRADO** | Atualização imediata do status no SQLite |
| **Controle de Autonomia por Canal** | Switch de Autonomia no Card e Detalhe | `PATCH /api/v2/channels/{id}/autonomous` | **MIGRADO** | `operator_console.set_autonomous_mode_enabled_op` |
| **Configuração de Quotas e Metas** | Aba "Automação & Metas" no Detalhe do Canal | `PATCH /api/v2/channels/{id}/quotas` | **MIGRADO** | `profile_manager.update_profile_quotas` |
| **Configuração de Janela de Publicação** | Aba "Automação" no Detalhe do Canal | `PATCH /api/v2/channels/{id}/schedule` | **MIGRADO** | `profile_manager.update_profile_schedule` |
| **Pausa Operacional de Emergência** | Botão Pausar/Retomar na Sidebar e Settings | `POST /api/v2/factory/pause`, `/resume` | **MIGRADO** | Pausa segura não-destrutiva |
| **Roteamento Post for Me (Multiprojeto)** | Aba "Publicação" no Detalhe do Canal | `GET /api/v2/channels`, `post_for_me_service.py` | **MIGRADO** | Resolução isolada por `project_id` |
| **Isolamento e Segurança de DEV** | `SettingsView` + `isolation_guard.py` | `app/services/isolation_guard.py` | **MIGRADO** | Bloqueio de `C:\` e publicação externa |

---

## 2. Resumo da Paridade

- **Total de recursos mapeados do Streamlit:** 13
- **Recursos migrados com êxito:** 13 (100%)
- **Recursos bloqueados:** 0
- **Botões fictícios ou sem endpoint real:** 0
- **Resultado do Gate V2.6:** `FUNCTIONAL_PARITY_PASS`
