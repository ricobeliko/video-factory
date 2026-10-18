# Video Factory V2 — Arquitetura do Sistema
**Documento de Arquitetura V2.2**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Visão Geral da Arquitetura em Camadas

A Video Factory V2 substitui completamente a interface Streamlit por uma aplicação web desacoplada de alto desempenho (SPA em React 18 + Vite), conectada diretamente à fábrica Python através de uma API FastAPI leve e assíncrona.

```
┌───────────────────────────────────────────────────────────────────┐
│              INTERFACE WEB V2 (React 18 + Vite SPA)              │
│   • Sidebar de Navegação Unificada                                │
│   • Canal como Centro (Channel Workspace & 7 Abas de Gestão)     │
│   • Formulários Inteligentes por Formato (Traditional, Q0-R, P1.3)│
│   • Live Pipeline & Drawer de Telemetria                          │
│   • Central de Revisão Humana de Vídeos                           │
└─────────────────────────────────┬─────────────────────────────────┘
                                  │ JSON / REST via HTTP / SSE
                                  ▼
┌───────────────────────────────────────────────────────────────────┐
│               CAMADA DE API REST (FastAPI / ASGI)                 │
│   • /api/v2/operations/* (Status, Canais, Autonomia, Quotas)      │
│   • /api/v2/channels/*   (CRUD Canal, Formatos, Destinos Post)   │
│   • /api/v2/review/*     (Central de Revisão, Streaming Vídeo)    │
│   • /api/v2/templates/*  (Metadados e Regras de Formato)          │
│   • Guards de Isolamento (Bloqueio C:\ e desativação de publish)  │
└─────────────────────────────────┬─────────────────────────────────┘
                                  │ Chamadas Diretas de Serviço Python
                                  ▼
┌───────────────────────────────────────────────────────────────────┐
│               MOTORES E SERVIÇOS EXISTENTES (Python)              │
│   • profile_manager.py     • channel_service.py                   │
│   • quiz_engine.py         • operator_console.py                  │
│   • post_for_me_service.py • autonomous_production.py             │
│   • video.py (FFmpeg)      • quality_recovery.py                  │
└─────────────────────────────────┬─────────────────────────────────┘
                                  │ Leitura e Escrita
                                  ▼
┌───────────────────────────────────────────────────────────────────┐
│                     PERSISTÊNCIA & ARQUIVOS                       │
│   • SQLite: storage/video_factory.db (DEV_V2 Isolado)             │
│   • Configurações: config.toml (DEV)                              │
│   • Tarefas & Mídia: storage/tasks/{task_id}                      │
│   • Templates JSON: resource/quiz_templates/*.json                │
└───────────────────────────────────────────────────────────────────┘
```

---

## 2. Princípios de Sustentabilidade e Isolamento

1. **Reaproveitamento Total dos Motores Homologados:** O motor de renderização FFmpeg, o Quiz Engine Q0-R, o Quiz de Papel P1.3 e os algoritmos de telemetria continuam intactos.
2. **Desacoplamento do Ciclo de Vida da UI:** A interface web não roda no mesmo processo do interpretador que renderiza vídeos. Erros ou reloads do frontend não interrompem renderizações em andamento.
3. **Isolamento de Produção Obrigatório:** Todo request passa por `app/services/isolation_guard.py`. Se houver qualquer tentativa de acessar `C:\Projetos\MoneyPrinterTurbo` ou publicar vídeos externamente em DEV, a requisição é abortada com HTTP 403 Forbidden.
4. **Entrega Estática de Alta Velocidade:** Em produção, o bundle estático gerado pelo Vite (`webui-v2/dist/`) é servido diretamente pelo FastAPI através da classe `SPAStaticFiles`, garantindo carregamento inicial instantâneo (< 200ms) sem necessidade de servidor Node.js em background.
