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

---

## 5. Estratégia de Backup Seguro do Banco de Dados (Fase V12-C)

Como o SQLite opera em modo **WAL (`PRAGMA journal_mode=WAL;`)**, **NUNCA** faça cópias diretas de arquivos (`.db`, `.db-wal`, `.db-shm`) enquanto a aplicação estiver em execução.

O MoneyPrinterTurbo utiliza a API oficial **`sqlite3.Connection.backup()`** através do serviço `app/services/production_backup.py`, garantindo snapshots atômicos e consistentes sem travar o processamento da fábrica.

### Localização e Nomenclatura dos Backups
- **Diretório padrão:** `storage/backups/database/`
- **Banco de Dados:** `video_factory_YYYYMMDD_HHMMSS.db` (timestamp determinístico em UTC)
- **Manifesto Sidecar:** `video_factory_YYYYMMDD_HHMMSS.json` (SHA-256, tamanho, integridade e metadados)

### Política de Retenção e Integridade
1. Todo backup é gerado primeiramente em arquivo temporário (`.tmp`).
2. É submetido obrigatoriamente a um `PRAGMA integrity_check;`. Somente se o retorno for estritamente `ok` o arquivo é renomeado atomicamente via `os.replace()`.
3. É gerado um manifesto JSON com hash SHA-256.
4. É aplicada a política de retenção (padrão: **últimos 24 backups** mantidos). Backups antigos além da cota são podados automaticamente junto com seus respectivos manifestos. Arquivos estranhos não são tocados.

### Execução de Backup Manual ou Agendado
```powershell
# Execução direta via PowerShell a partir da raiz do projeto:
powershell -ExecutionPolicy Bypass -File scripts\backup_production.ps1
```

---

## 6. Procedimento de Restauração Segura (Recovery)

> [!CAUTION]
> **REGRA ABSOLUTA DE SEGURANÇA:**
> **NUNCA** restaure um banco de dados com o backend do MoneyPrinterTurbo em execução.
> O script e o serviço de recovery bloqueiam incondicionalmente a restauração se detectarem a porta `8501` aberta ou processo com lock `PRIMARY` ativo.
> Não existe flag `--force` ou parâmetro de bypass operacional: o backend ativo sempre rejeita a restauração.

### Passo a Passo para Restauração:

1. **Parar o Servidor:**
   No Windows Task Scheduler ou console interativo, encerre a tarefa/processo do servidor antes de restaurar.
   *(Nota: O script de restauração não encerra processos automaticamente por segurança; o operador deve realizar a parada manual).*

2. **Listar Backups Disponíveis:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\restore_production_backup.ps1
   ```

3. **Executar a Restauração:**
   ```powershell
   powershell -ExecutionPolicy Bypass -File scripts\restore_production_backup.ps1 -BackupFile storage\backups\database\video_factory_YYYYMMDD_HHMMSS.db
   ```

4. **Garantias Automáticas do Processo de Restauração:**
   - Validação prévia de integridade e conferência de SHA-256 contra o manifesto sidecar.
   - Criação automática de **Safety Copy** do banco atual em `storage/backups/recovery_safety/video_factory_pre_restore_YYYYMMDD_HHMMSS.db`.
   - Limpeza obrigatória de arquivos companheiros `-wal` e `-shm` obsoletos do destino (evitando corrupção por replay de transações antigas).
   - Execução de `PRAGMA integrity_check;` final no banco restaurado.

---

## 7. Observabilidade, Logs e Diagnóstico Operacional

### Logs Operacionais Persistentes do Launcher
Quando executado em segundo plano pelo Windows Task Scheduler (conta SYSTEM), o script `scripts/start_production.ps1` mantém registros estruturados com rotação automática limitada (bounded em 5 MB):

- `storage/logs/production/production_startup.log`: Registros de boot, PID, porta, diretório, interpretador Python e exit code de encerramento.
- `storage/logs/production/production_error.log`: Falhas críticas e exceções de inicialização.

### Diagnóstico Rápido e Sanitizado do Servidor
Para consultar o status em tempo real sem expor chaves de API:

```powershell
# Relatório legível no console:
powershell -ExecutionPolicy Bypass -File scripts\production_status.ps1

# Ou em formato JSON:
powershell -ExecutionPolicy Bypass -File scripts\production_status.ps1 -Json
```

O diagnóstico reporta:
- **Health Global:** `HEALTHY`, `DEGRADED` ou `UNHEALTHY` (incluindo idade e integridade do último backup).
- **Readiness Técnica:** Verificação de Python 3.11+, venv, integridade do SQLite, permissões de storage e FFmpeg.
- **Factory & Scheduler:** Estado (PAUSED/RUNNING), workers vivos e modo dry-run.
- **Credenciais:** Reportadas exclusivamente como `PRESENT` ou `MISSING` (zero segredos expostos).

---

## 8. Política de Isolamento de Segredos e Réplicas Externas

1. **Separação entre Banco de Dados e Segredos:**
   - O arquivo `config.toml` e os arquivos de tokens OAuth (`youtube_token.json`, etc.) **NÃO** são incluídos nos backups automáticos do SQLite para evitar vazamento acidental de credenciais.
   - O operador deve manter uma cópia segura e criptografada (ex: cofre de senhas ou pendrive seguro) do `config.toml` e credenciais.

2. **Cópia para Armazenamento Externo / Nuvem:**
   - Os arquivos de backup em `storage/backups/database/` podem ser copiados periodicamente para HDs externos, NAS ou serviços de nuvem (ex: Rclone, OneDrive).
   - **IMPORTANTE:** O banco de produção ativo (`storage/video_factory.db`) **SEMPRE** deve residir em disco local SSD/NVMe da máquina host. **NUNCA** configure pastas sincronizadas por nuvem ou compartilhamentos de rede SMB como diretório do banco ao vivo.
