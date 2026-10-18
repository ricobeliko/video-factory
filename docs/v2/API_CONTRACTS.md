# Video Factory V2 — Contratos de API REST
**Documento de Arquitetura V2.2**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Visão Geral das Rotas da API

Todas as rotas da V2 utilizam o prefixo `/api/v2/` e retornam respostas JSON no envelope padronizado do projeto:
```json
{
  "code": 200,
  "message": "Mensagem informativa",
  "data": { ... }
}
```

---

## 2. Endpoints do Sistema e Operações (`/api/v2/operations/`)

### `GET /api/v2/operations/health`
Retorna a saúde operacional do backend e confirmação de prontidão do frontend estático.
- **Resposta 200:**
  ```json
  {
    "status": "healthy",
    "app": "MoneyPrinterTurbo",
    "version": "v1.2.0-v2",
    "role": "PRIMARY",
    "is_primary": true,
    "webui_v2_available": true
  }
  ```

### `GET /api/v2/operations/system/status`
Snapshot consolidado da fábrica: estado de pausa, tarefas ativas, saúde dos provedores e alertas operacionais.

### `POST /api/v2/operations/factory/pause`
Pausa imediatamente a execução autônoma do scheduler e novas renderizações de forma segura (não-destrutiva).

### `POST /api/v2/operations/factory/resume`
Retoma o scheduler e a esteira de produção.

### `POST /api/v2/operations/factory/run-cycle`
Dispara um ciclo autônomo supervisionado para um canal ou todos os canais ativos.

---

## 3. Endpoints de Gestão de Canais (`/api/v2/operations/channels/`)

### `GET /api/v2/operations/channels`
Lista todos os canais configurados com métricas essenciais em uma única chamada:
- Nome, slug, nicho, idioma, formato.
- Contas vinculadas (YouTube e TikTok com Post for Me).
- Estado da automação (habilitado/desabilitado).
- Estoque atual (pronto, em processamento, agendado, com falha) e meta de estoque.
- Configurações do canal (`settings`).

### `GET /api/v2/operations/channels/{channel_id}/settings`
Retorna configurações detalhadas do canal:
- Quotas: `target_ready_stock`, `max_generations_24h`, `posts_per_day`.
- Agendamento: `publish_start_hour`, `publish_end_hour`, `timezone`, `min_interval_hours`.
- Workspace: nicho, voz, formato de vídeo, regras de prompt.

### `PATCH /api/v2/operations/channels/{channel_id}/settings`
Atualiza de forma atômica configurações, quotas e agendamento do canal.

### `PATCH /api/v2/operations/channels/{channel_id}/autonomous`
Habilita ou desabilita a produção autônoma para aquele canal específico.

---

## 4. Endpoints de Estoque e Revisão Humana (`/api/v2/review/`)

### `GET /api/v2/review/tasks`
Fila de vídeos gerados aguardando inspeção do operador ou prontos para publicação:
- Query params: `filter` (`pending`, `approved`, `discarded`, `all`), `profile_id`.

### `GET /api/v2/review/tasks/{task_id}/video`
Faz o streaming seguro do arquivo de vídeo renderizado (`final-1.mp4`) com cabeçalhos `Accept-Ranges: bytes` para reprodução suave no player de revisão da interface.

### `POST /api/v2/review/tasks/{task_id}/approve`
Aprova o vídeo inspecionado para o estoque pronto (`Ready Stock`), tornando-o elegível para agendamento e publicação.

### `POST /api/v2/review/tasks/{task_id}/discard`
Descarta o vídeo do estoque sem exclusão de logs de auditoria.

---

## 5. Endpoints de Telemetria e Execuções em Tempo Real

### `GET /api/v2/operations/executions/live`
Retorna a árvore de execução em tempo real de cada canal para o pipeline visual (geração de roteiro, TTS, busca de clipes, renderização FFmpeg e publicação).

### `GET /api/v2/operations/executions/{task_id}`
Detalhe completo de execução de uma tarefa específica para exibição no drawer lateral do operador.
