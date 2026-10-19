# Video Factory V2.15B — Roteiro de Execução de Cutover Controlado
**Documento Canônico de Substituição da Interface de Produção**
**Data:** 18/10/2026
**Ambiente Alvo:** PC Forte (`C:\Projetos\MoneyPrinterTurbo`)
**Baseline Auditado:** `main` @ `cf7d64767e13f94eb710809057dbcbc6efc19a27`
**Nova Versão:** `feat/video-factory-v2` @ `8835a08c900dbe7ccff03c5a9a1caa7b373932cd`
**Banco de Dados Efetivo:** `C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db` (~8.65 MB)

---

> [!CRITICAL]
> **ESTA MISSÃO PREPARA E HOMOLOGA OS SCRIPTS E GATES. O CUTOVER SERÁ EXECUTADO POSTERIORMENTE PELO OPERADOR NO PC FORTE VIA RUSTDESK / POWERSHELL.**
> RTO Medido: **10 a 15 minutos**.
> Em caso de qualquer bloqueio, o procedimento de reversão imediata está embutido no script e detalhado neste guia.

---

## 1. Diagnóstico Real e Contexto Operacional do PC Forte

A auditoria real do PC Forte revelou o seguinte estado:
- **Git:** Branch `main`, SHA `cf7d64767e13f94eb710809057dbcbc6efc19a27`.
- **Modificações Locais:**
  - `M app/services/autonomous_production.py` (Adição pontual autorizada de `rejected_struct = None` na linha antes de `fixed_format`).
  - `?? app/services/autonomous_production.py.bak_20261018_110834` (Arquivo de backup local).
- **Processos e Portas:**
  - **Porta 8501 (PID 13056):** `python.exe scripts/production_entrypoint.py` iniciado pela Scheduled Task `VideoFactory Production` (detém autoridade `PRIMARY` e roda o `SchedulerExecutionWorker`).
  - **Porta 8080 (PID 9280):** `python.exe -m uvicorn app.asgi:app` iniciado pela Scheduled Task `VideoFactory WebUI V2` (servidor FastAPI/Uvicorn em modo secundário/respeitando locks).
- **Banco de Dados Real:** `storage/video_factory.db` (~8.65 MB) íntegro.
- **Espaço Livre em Disco:** ~335 GB no drive `C:`.

---

## 2. Estratégia de Distribuição Git da V2 para o PC Forte

Como a branch `feat/video-factory-v2` foi desenvolvida no Novo PC DEV, sua distribuição para o PC Forte pode ser realizada de duas formas rigorosamente controladas, **sem qualquer uso de `git reset --hard` ou `git clean`**:

### Opção 1: Via Repositório Remoto (Recomendada após autorização de push)
1. No Novo PC DEV:
   ```powershell
   git push origin feat/video-factory-v2
   git tag release-v2.15-cutover
   git push origin release-v2.15-cutover
   ```
2. No PC Forte:
   ```powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git fetch origin
   # Criar branch local de segurança para checkpoint do SHA antigo
   git branch backup-pre-v2-cutover cf7d64767e13f94eb710809057dbcbc6efc19a27
   ```

### Opção 2: Offline via Git Bundle (Sem push para GitHub)
1. No Novo PC DEV:
   ```powershell
   git bundle create C:\Projetos\v2_release.bundle feat/video-factory-v2
   ```
2. Transferir `v2_release.bundle` via RustDesk para `C:\Projetos\` no PC Forte.
3. No PC Forte:
   ```powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git fetch C:\Projetos\v2_release.bundle feat/video-factory-v2:feat/video-factory-v2
   ```

---

## 3. Transferência dos Scripts de Transição para o PC Forte

Transferir via RustDesk para `C:\Projetos\`:
1. `C:\Projetos\MoneyPrinterTurbo-V2\scripts\v2_pre_cutover_audit.ps1` -> `C:\Projetos\v2_pre_cutover_audit.ps1`
2. `C:\Projetos\MoneyPrinterTurbo-V2\scripts\v2_cutover.ps1` -> `C:\Projetos\v2_cutover.ps1`

---

## 4. Execução do Cutover no PC Forte (Passo a Passo)

### Passo 1: Executar Auditoria Passiva
No PowerShell como Administrador:
```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\Projetos\v2_pre_cutover_audit.ps1 -RepoPath C:\Projetos\MoneyPrinterTurbo
```
Critério de parada: Somente avançar se `STATUS AUDITORIA : PASS`.

### Passo 2: Executar Script Único de Cutover
```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\Projetos\v2_cutover.ps1 -RepoPath C:\Projetos\MoneyPrinterTurbo -TargetBranch feat/video-factory-v2
```

O script executará automaticamente os 6 Gates:
- **GATE 1 (PREFLIGHT):** Checagem de SHA, validação precisa do diff de `rejected_struct = None`, integridade de `storage/video_factory.db`, ausência de renderizações FFmpeg ativas, ausência de posts em andamento (`status = 'processing'`) e espaço em disco (>5 GB).
- **GATE 2 (BACKUP):** Snapshot transacional de `storage/video_factory.db` (incluindo WAL/SHM), `.env`, `config.toml`, arquivamento do hotfix e gravação de `manifest.json` com hashes SHA256.
- **GATE 3 (STOP):** Pausa da fábrica via `operator_console.pause_factory()`, desativação explícita de auto-publish (`auto_publish_enabled = false`), encerramento gracioso dos processos nas portas 8501 e 8080, liberação auditada do lock stale de PRIMARY (`operator_console.release_stale_instance_lock`) e desativação (`Disable-ScheduledTask`) da tarefa `VideoFactory Production` (Streamlit).
- **GATE 4 (UPDATE):** Reconciliação não-destrutiva via `git restore app/services/autonomous_production.py` (preservando arquivos não rastreados), checkout da branch V2 e aplicação de migrações canônicas idempotentes no banco real via serviços oficiais (`profile_manager`, `scheduler`, etc.), sem uso de scripts sintéticos.
- **GATE 5 (START):** Configuração de `MPT_ENVIRONMENT=PRODUCTION`, inicialização da V2 na porta 8080 e garantia de autoridade PRIMARY única.
- **GATE 6 (HEALTH):** Validação de `/health` (HTTP 200), `/api/v2/health` (confirmando `role: PRIMARY` e `is_primary: true`), carregamento de canais via `/api/v2/channels`, verificação de que `auto_publish_enabled` permanece `false` e confirmação de que a porta 8501 permanece desativada.

---

## 5. Procedimento de Rollback de Contingência

Se por qualquer motivo o operador desejar reverter a substituição e reativar imediatamente o Streamlit:

```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\Projetos\v2_cutover.ps1 -RepoPath C:\Projetos\MoneyPrinterTurbo -Rollback -BackupDirToRestore "C:\Projetos\MoneyPrinterTurbo\storage\backups\cutover_<TIMESTAMP>"
```

O script de Rollback:
1. Encerra o Uvicorn na porta 8080.
2. Faz checkout de volta para a branch `main` (`cf7d64767e13f94eb710809057dbcbc6efc19a27`).
3. Restaura o banco SQLite e o hotfix de `autonomous_production.py` a partir do backup.
4. Reabilita e inicia a Scheduled Task `VideoFactory Production` na porta 8501.
5. Inicia a Scheduled Task `VideoFactory WebUI V2` na porta 8080.
Tempo de retorno estimado: **10 a 12 minutos**.
