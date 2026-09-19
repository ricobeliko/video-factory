# Arquitetura e Guia de Deploy de Produção (V12-A)

Este documento descreve a arquitetura operacional oficial para execução contínua do **MoneyPrinterTurbo** em ambiente de produção em um computador dedicado (Windows PC).

---

## 1. Visão Geral da Arquitetura

O sistema opera com um modelo **Host Centralizado (Primary Factory)** e **Clientes de Interface Remota (Browser Only)**:

```text
+-------------------------------------------------------------------------+
|                  HOST DEDICADO (PC FORTE - WINDOWS)                     |
|                                                                         |
|  [ scripts/start_production.ps1 ]                                       |
|                  |                                                      |
|                  v                                                      |
|  +-------------------------------------------------------------------+  |
|  |                 PRIMARY FACTORY (Processo Python)                 |  |
|  |                                                                   |  |
|  |  * SQLite Autoritativo (storage/video_factory.db - WAL Mode)      |  |
|  |  * Task Generation Worker (Thread local)                          |  |
|  |  * Scheduler Execution Worker (Thread local - 30s interval)       |  |
|  |  * Single Instance Manager (Lock PRIMARY_FACTORY)                 |  |
|  |  * Local Storage (storage/clip_sources, storage/tasks)            |  |
|  |  * Streamlit WebUI Server (0.0.0.0:8501, headless)                |  |
|  +-------------------------------------------------------------------+  |
+-------------------------------------------------------------------------+
                                    |
          Rede Segura (LAN Privada ou Tailscale Mesh VPN)
                                    |
          +-------------------------+-------------------------+
          |                                                   |
          v                                                   v
+-----------------------+                           +-----------------------+
|    CLIENTE REMOTO 1   |                           |    CLIENTE REMOTO 2   |
|   (Notebook / Mac)    |                           |  (Smartphone / Tablet)|
|   Navegador Web       |                           |  Navegador Web        |
|   http://<ip>:8501    |                           |  http://<ip>:8501     |
+-----------------------+                           +-----------------------+
```

---

## 2. Regras de Ouro e Princípios Inegociáveis

1. **NUNCA compartilhe o arquivo SQLite via rede:**
   - O arquivo `video_factory.db` e seus arquivos WAL/SHM devem residir em disco local rápido (SSD/NVMe).
   - Não use pastas compartilhadas SMB/CIFS, NFS, Google Drive, Dropbox ou OneDrive para armazenar o banco. SQLite em redes de arquivos distribuídos pode sofrer corrupção de lock e perda de dados.

2. **NUNCA execute duas instâncias de backend apontando para o mesmo banco:**
   - Apenas **uma única instância** (`PRIMARY`) tem permissão de executar mutações, agendamentos, tarefas de renderização e publicações.
   - Qualquer processo secundário detecta o lock ativo (`PRIMARY_FACTORY`) e entra em modo `SECONDARY_VIEW_ONLY` (somente leitura).

3. **Navegadores remotos NÃO são instâncias secundárias:**
   - Conexões de navegadores em notebooks ou celulares via HTTP/WebSocket conectam-se diretamente à instância Streamlit rodando no Host.
   - Os clientes remotos consomem a aplicação sem inicializar novos processos Python de backend.

4. **NÃO abra portas no roteador de Internet (Sem Port Forwarding):**
   - Não faça encaminhamento de porta (port forwarding) na porta 8501 do roteador residencial/empresarial.
   - Acesso externo seguro deve ser feito exclusivamente via **Tailscale** (ou VPN privada equivalente), mantendo o servidor completamente isolado de acessos não autorizados da internet pública.

---

## 3. Serviços e Workers em Background

O processo `PRIMARY` coordena autonomamente:
- **Single-Instance Safety:** Mantém lock com heartbeat de 15 segundos e timeout de 90 segundos.
- **Scheduler Worker:** Verifica a cada 30 segundos agendamentos prontos, publicações e estoque mínimo.
- **Generation Worker:** Processa tarefas em fila (`storage/tasks`).
- **Health & Readiness Check:** Disponibiliza verificações estruturadas de saúde e prontidão técnica via `app.services.production_health`.

---

## 4. Inicialização do Servidor de Produção

Para iniciar o servidor no PC dedicado:

```powershell
# Executar no PowerShell a partir da raiz do projeto:
powershell -ExecutionPolicy Bypass -File scripts\start_production.ps1
```

O script:
- Valida o interpretador Python em `.venv\Scripts\python.exe`.
- Valida o entrypoint `webui\Main.py`.
- Define o diretório de trabalho correto.
- Inicia o Streamlit com bind em `0.0.0.0` e porta `8501` em modo headless (sem abrir navegador no host).

---

## 5. Estratégia de Backup Seguro do Banco de Dados

Como o SQLite opera em modo **WAL (`PRAGMA journal_mode=WAL;`)**, nunca faça cópias diretas de arquivos com o processo em execução usando ferramentas genéricas.

O método oficial recomendado é o **SQLite Online Backup API** ou comando `VACUUM INTO`:

```python
import sqlite3
from app.services import scheduler

def safe_backup_database(backup_target_path: str):
    source_db = scheduler.get_db_path()
    with sqlite3.connect(source_db) as conn:
        conn.execute(f"VACUUM INTO '{backup_target_path}';")
```

Isso garante um snapshot transacional 100% íntegro sem interromper as operações da fábrica.

---

## 6. Diagnósticos de Produção

O serviço `app/services/production_health.py` oferece duas funções essenciais:

1. `get_production_health()`:
   Retorna `HEALTHY`, `DEGRADED` ou `UNHEALTHY` com status de SQLite, storage (espaço livre e gravação), FFmpeg, scheduler e provedores configurados.

2. `get_production_readiness()`:
   Retorna se a máquina e dependências estão prontas para produção (Python >= 3.11, venv presente, binário FFmpeg, tabelas SQLite e presença de credenciais sem expor segredos).
