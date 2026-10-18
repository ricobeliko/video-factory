# Video Factory V2.15 — Roteiro de Execução do Cutover no PC Forte
**Manual Operacional de Substituição da Interface**
**Data:** 18/10/2026
**Ambiente Alvo:** PC Forte (`C:\Projetos\MoneyPrinterTurbo`)
**Operador:** Humano (via RustDesk / PowerShell)

---

> [!CRITICAL]
> **ESTE PROCEDIMENTO DEVE SER EXECUTADO EXCLUSIVAMENTE PELO OPERADOR NO PC FORTE.**
> Tempo estimado medido (RTO): **10 a 15 minutos**.
> Em caso de falha em qualquer gate, abortar imediatamente e seguir `ROLLBACK_PLAN.md`.

---

## Pré-Requisito Mandatório: Auditoria Passiva Aprovada

Antes de qualquer ação, execute:
```powershell
powershell.exe -ExecutionPolicy Bypass -File scripts\v2_pre_cutover_audit.ps1
```
Somente prossiga se o resultado for **`STATUS AUDITORIA : PASS`**.

---

## Etapa 1: Quiescência e Congelamento de Estado

1. **Aguardar Quiescência:**
   Verificar se há tarefas em andamento. Não interromper renderizações ativas de vídeo.
2. **Pausar Despachos:**
   ```powershell
   python -c "from app.services import operator_console; operator_console.pause_factory()"
   ```
3. **Parar a Interface Streamlit Legada e Agendador:**
   ```powershell
   Stop-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
   # Finalizar processos python residuais do Streamlit se necessário
   Get-Process python -ErrorAction SilentlyContinue | Where-Object { $_.CommandLine -like "*streamlit*" } | Stop-Process -Force
   ```
4. **Verificar Liberação das Portas:**
   ```powershell
   Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue
   Get-NetTCPConnection -LocalPort 8080 -ErrorAction SilentlyContinue
   ```

---

## Etapa 2: Backup Transacional Consistente

1. **Criar diretório de backup timestamped:**
   ```powershell
   $ts = Get-Date -Format "yyyyMMdd_HHmmss"
   $backupDir = "storage\backups\pre_v2_cutover_$ts"
   New-Item -ItemType Directory -Path $backupDir -Force
   ```
2. **Backup Físico do Banco SQLite:**
   ```powershell
   if (Test-Path "db.sqlite3") { Copy-Item "db.sqlite3" "$backupDir\db.sqlite3" }
   if (Test-Path "storage\db.sqlite3") { Copy-Item "storage\db.sqlite3" "$backupDir\storage_db.sqlite3" }
   ```
3. **Preservar Arquivos de Configuração e Credenciais:**
   ```powershell
   Copy-Item ".env" "$backupDir\.env"
   Copy-Item "config.toml" "$backupDir\config.toml"
   ```

---

## Etapa 3: Reconciliação do Hotfix Local e Estratégia Git

No PC Forte, o arquivo `app/services/autonomous_production.py` possui uma modificação pontual (`rejected_struct = None`) e um arquivo `.bak` criado manualmente fora do Git. Essa alteração **já está incorporada** na branch V2 e na main.

1. **Preservar o hotfix local em pasta de segurança:**
   ```powershell
   $hotfixBakDir = "$backupDir\local_hotfix"
   New-Item -ItemType Directory -Path $hotfixBakDir -Force
   Copy-Item "app\services\autonomous_production.py" "$hotfixBakDir\"
   Get-ChildItem "app\services\*.bak" -ErrorAction SilentlyContinue | Copy-Item -Destination "$hotfixBakDir\"
   ```
2. **Reconciliar com Git sem destruir arquivos não commitados:**
   ```powershell
   # NUNCA usar git reset --hard ou git clean
   git restore app/services/autonomous_production.py
   # Limpar o arquivo .bak apenas após arquivado no backup
   Remove-Item "app\services\autonomous_production.py.bak" -ErrorAction SilentlyContinue
   ```
3. **Atualizar Repositório para a V2:**
   ```powershell
   git fetch origin
   # Fazer checkout da branch homologada V2
   git checkout feat/video-factory-v2
   git pull origin feat/video-factory-v2
   ```

---

## Etapa 4: Configuração de Ambiente e Migração do Banco

1. **Garantir Variável de Ambiente de Produção:**
   No PC Forte, definir:
   ```powershell
   [System.Environment]::SetEnvironmentVariable("MPT_ENVIRONMENT", "PRODUCTION", "Machine")
   $env:MPT_ENVIRONMENT = "PRODUCTION"
   ```
   > [!NOTE]
   > Em produção (`MPT_ENVIRONMENT=PRODUCTION`), o `IsolationGuard` permite o acesso ao caminho `C:\Projetos\MoneyPrinterTurbo`, mantendo as travas de publicação externa sob a autoridade PRIMARY e aprovação do operador.

2. **Executar Migrações Idempotentes do Banco:**
   ```powershell
   python scripts/rehearse_v2_migration.py --apply
   ```
   *Regra de Não-Invenção de IDs:*
   - Canais legados sem `project_id` preservam estritamente `NULL`.
   - Canais ambíguos são sinalizados e mantidos com segurança.

---

## Etapa 5: Inicialização e Validação da Nova V2 (Porta 8080)

1. **Iniciar a Aplicação V2:**
   ```powershell
   python main.py
   ```
2. **Validar Saúde e Endpoints:**
   - Acessar no navegador: `http://localhost:8080`
   - Testar API de saúde: `http://localhost:8080/api/health`
   - Testar canais: `http://localhost:8080/api/channels`
   - Testar tarefas: `http://localhost:8080/api/tasks`
3. **Validar Autoridade PRIMARY:**
   - Confirmar no log que o `SchedulerExecutionWorker` adquiriu a trava de PRIMARY e está em estado pausado/aguardando comando.
4. **Verificar Isolamento e Publicação:**
   - Publicações automáticas permanecem bloqueadas até que o operador ative o console.

---

## Etapa 6: Homologação Operacional e Desativação do Streamlit

1. O operador realiza teste visual na interface React V2.
2. Criar ou atualizar a Scheduled Task do Windows para iniciar a V2 automaticamente no boot (`python main.py` na porta 8080).
3. Desativar definitivamente a Scheduled Task antiga do Streamlit (`VideoFactory Production`).

---

## Critério de Abort / Rollback Imediato
Se o serviço não subir na porta 8080 em até 5 minutos, ou se houver erro de banco de dados, interrompa e execute imediatamente o `ROLLBACK_PLAN.md`.
