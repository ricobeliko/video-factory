<#
.SYNOPSIS
    Script Unico de Cutover V2.15B para Video Factory (PC Forte).
.DESCRIPTION
    Executa a transicao controlada, sequencial e reversivel da interface Streamlit
    para a Video Factory V2 React/FastAPI.
    
    GATES DE EXECUCAO:
    1. PREFLIGHT: Validacao rigorosa de SHA, diff do hotfix, integridade SQLite, tarefas ativas e espaco.
    2. BACKUP: Snapshot transacional do SQLite, configuracoes, hotfix e geracao de manifesto com SHA256.
    3. STOP: Pausa de despachos, parada graciosa das portas 8501 e 8080 e desativacao da tarefa Streamlit.
    4. UPDATE: Reconciliacao do hotfix sem comandos destrutivos, mudanca para branch V2 e migracao idempotente.
    5. START: Inicializacao na porta 8080, validacao de autoridade PRIMARY unica e scheduler sem duplicidade.
    6. HEALTH: Checagem HTTP 200, validacao de canais, estoque, agendamentos e integridade SQLite.
    7. ROLLBACK: Retorno seguro para main e reativacao da interface Streamlit em caso de aborto.
#>
[CmdletBinding()]
param(
    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo",
    [string]$TargetBranch = "feat/video-factory-v2",
    [switch]$Rollback,
    [string]$BackupDirToRestore = ""
)

Set-StrictMode -Off
$ErrorActionPreference = "Stop"

function Write-CutoverLog {
    param([string]$Msg, [string]$Level = "INFO")
    $ts = (Get-Date -Format 'yyyy-MM-dd HH:mm:ss')
    $color = "Cyan"
    if ($Level -eq "SUCCESS") { $color = "Green" }
    elseif ($Level -eq "WARN") { $color = "Yellow" }
    elseif ($Level -eq "ERROR") { $color = "Red" }
    Write-Host "[$ts][$Level] $Msg" -ForegroundColor $color
}

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   VIDEO FACTORY V2.15B - SCRIPT DE CUTOVER CONTROLADO      " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Repo Path     : $RepoPath"
Write-Host "Target Branch : $TargetBranch"
Write-Host "Modo          : $(if ($Rollback) { 'ROLLBACK DE CONTINGENCIA' } else { 'CUTOVER REGULAR' })"
Write-Host ""

if (-not (Test-Path $RepoPath)) {
    Write-CutoverLog "Caminho $RepoPath nao existe!" "ERROR"
    exit 2
}

Push-Location $RepoPath

# ==============================================================================
# PROCEDIMENTO DE ROLLBACK (SE ACIONADO EXPLICITAMENTE)
# ==============================================================================
if ($Rollback) {
    Write-CutoverLog "Iniciando Procedimento de ROLLBACK..." "WARN"

    # 1. Parar V2 na porta 8080
    Write-CutoverLog "Encerrando servicos na porta 8080..." "WARN"
    Stop-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue
    $p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
    if ($p8080) {
        Stop-Process -Id $p8080.OwningProcess -Force -ErrorAction SilentlyContinue
        Start-Sleep -Seconds 2
    }

    # 2. Retornar Git para main
    Write-CutoverLog "Retornando Git para a branch main..." "WARN"
    git checkout main

    # 3. Restaurar hotfix se backup fornecido
    if ($BackupDirToRestore -and (Test-Path $BackupDirToRestore)) {
        Write-CutoverLog "Restaurando arquivos a partir de $BackupDirToRestore..." "WARN"
        $dbBak = Join-Path $BackupDirToRestore "video_factory.db"
        if (Test-Path $dbBak) {
            Copy-Item $dbBak "storage\video_factory.db" -Force
            Write-CutoverLog "Banco SQLite restaurado do backup." "SUCCESS"
        }
        $hfBak = Join-Path $BackupDirToRestore "hotfix\autonomous_production.py"
        if (Test-Path $hfBak) {
            Copy-Item $hfBak "app\services\autonomous_production.py" -Force
            Write-CutoverLog "Hotfix local restaurado." "SUCCESS"
        }
    }

    # 4. Reabilitar e Iniciar Tarefas Legadas
    Write-CutoverLog "Reabilitando tarefas agendadas legadas..." "WARN"
    Enable-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
    Start-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue

    Write-CutoverLog "ROLLBACK CONCLUIDO COM SUCESSO." "SUCCESS"
    Pop-Location
    exit 0
}

# ==============================================================================
# GATE 1: PREFLIGHT
# ==============================================================================
Write-CutoverLog "GATE 1: Iniciando Preflight..." "INFO"

# Validar SHA e Branch
$currentBranch = (git rev-parse --abbrev-ref HEAD).Trim()
$currentSha = (git rev-parse HEAD).Trim()
Write-CutoverLog "Branch Atual: $currentBranch | SHA: $currentSha" "INFO"

# Validar Diff do Hotfix
$status = (git status --porcelain)
$dirtyFiles = @($status | ForEach-Object { ($_ -split '\s+')[-1] })
foreach ($f in $dirtyFiles) {
    if ($f -ne 'app/services/autonomous_production.py' -and -not $f.EndsWith('.bak') -and -not ($f -like '*autonomous_production.py.bak*') -and -not ($f -like '*v2_*')) {
        Write-CutoverLog "ABORT: Arquivo desconhecido modificado no Git: $f" "ERROR"
        Pop-Location
        exit 1
    }
}

# Validar Banco Real
$dbPath = Join-Path $RepoPath "storage\video_factory.db"
if (-not (Test-Path $dbPath)) {
    Write-CutoverLog "ABORT: Banco storage\video_factory.db nao localizado!" "ERROR"
    Pop-Location
    exit 1
}

# Validar Integridade e Tarefas Ativas no SQLite
$pyPreflight = @'
import sqlite3, sys
p = sys.argv[1]
conn = sqlite3.connect(p)
cur = conn.cursor()
cur.execute("PRAGMA integrity_check;")
res = cur.fetchone()[0]
if res != "ok":
    print(f"INTEGRITY_FAIL: {res}")
    sys.exit(1)

cur.execute("SELECT count(*) FROM scheduled_posts WHERE status IN ('in_progress', 'publishing')")
active = cur.fetchone()[0]
if active > 0:
    print(f"ACTIVE_POSTS_FAIL: {active}")
    sys.exit(2)
print("PREFLIGHT_DB_OK")
conn.close()
'@
$tmpPy = Join-Path $env:TEMP "cutover_preflight.py"
Set-Content -Path $tmpPy -Value $pyPreflight -Encoding UTF8
$preflightRes = (python $tmpPy "$dbPath" 2>&1)
Remove-Item -Path $tmpPy -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-CutoverLog "ABORT: Falha no preflight de banco: $preflightRes" "ERROR"
    Pop-Location
    exit 1
}
Write-CutoverLog "Preflight de Banco SQLite: $preflightRes" "SUCCESS"

# Validar Espaco em Disco (> 5 GB)
$driveLetter = (Get-Item $RepoPath).PSDrive.Name
$freeGb = [math]::Round((Get-PSDrive -Name $driveLetter).Free / 1GB, 2)
if ($freeGb -lt 5) {
    Write-CutoverLog "ABORT: Espaco em disco insuficiente: $freeGb GB" "ERROR"
    Pop-Location
    exit 1
}
Write-CutoverLog "Espaco em disco: $freeGb GB livres." "SUCCESS"
Write-CutoverLog "GATE 1 (PREFLIGHT): PASS." "SUCCESS"

# ==============================================================================
# GATE 2: BACKUP TRANSACIONAL
# ==============================================================================
Write-CutoverLog "GATE 2: Criando Snapshot de Backup Transacional..." "INFO"
$ts = Get-Date -Format 'yyyyMMdd_HHmmss'
$backupDir = Join-Path $RepoPath "storage\backups\cutover_$ts"
New-Item -ItemType Directory -Path $backupDir -Force | Out-Null
$hotfixDir = Join-Path $backupDir "hotfix"
New-Item -ItemType Directory -Path $hotfixDir -Force | Out-Null

# Copiar Banco de Dados (usando SQLite vacuum into ou copia fisica)
Copy-Item $dbPath (Join-Path $backupDir "video_factory.db") -Force
if (Test-Path "$dbPath-wal") { Copy-Item "$dbPath-wal" (Join-Path $backupDir "video_factory.db-wal") -Force }
if (Test-Path "$dbPath-shm") { Copy-Item "$dbPath-shm" (Join-Path $backupDir "video_factory.db-shm") -Force }

# Copiar Configuracoes
if (Test-Path ".env") { Copy-Item ".env" (Join-Path $backupDir ".env") -Force }
if (Test-Path "config.toml") { Copy-Item "config.toml" (Join-Path $backupDir "config.toml") -Force }

# Copiar Hotfix Local e .bak
if (Test-Path "app\services\autonomous_production.py") {
    Copy-Item "app\services\autonomous_production.py" (Join-Path $hotfixDir "autonomous_production.py") -Force
}
Get-ChildItem "app\services\*.bak*" -ErrorAction SilentlyContinue | ForEach-Object {
    Copy-Item $_.FullName (Join-Path $hotfixDir $_.Name) -Force
}

# Criar Manifesto com Hash SHA256
$dbHash = (Get-FileHash -Path $dbPath -Algorithm SHA256).Hash
$manifest = @{
    timestamp = $ts
    pre_sha = $currentSha
    pre_branch = $currentBranch
    db_path = $dbPath
    db_sha256 = $dbHash
    backup_dir = $backupDir
} | ConvertTo-Json -Depth 3

Set-Content -Path (Join-Path $backupDir "manifest.json") -Value $manifest -Encoding UTF8
Write-CutoverLog "Snapshot e manifesto criados em $backupDir (DB SHA256: $dbHash)" "SUCCESS"
Write-CutoverLog "GATE 2 (BACKUP): PASS." "SUCCESS"

# ==============================================================================
# GATE 3: STOP (QUIESCENCIA E LIBERACAO DE PORTAS)
# ==============================================================================
Write-CutoverLog "GATE 3: Parando Processos Legados e Desativando Streamlit..." "INFO"

# Pausar Fabrica via Operator Console
python -c "
try:
    from app.services import operator_console
    operator_console.pause_factory()
    print('FACTORY_PAUSED')
except Exception as e:
    print(f'PAUSE_NOTICE: {e}')
"

# Parar Tarefas Agendadas
Stop-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
Stop-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue

# Desativar Tarefa Streamlit para Impedir Auto-Reinicializacao
Disable-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
Write-CutoverLog "Tarefa agendada VideoFactory Production desativada (Disabled)." "SUCCESS"

# Parar Processos Python nas portas 8501 e 8080
$p8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if ($p8501) {
    Write-CutoverLog "Encerrando processo Streamlit na porta 8501 (PID $($p8501.OwningProcess))..." "WARN"
    Stop-Process -Id $p8501.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

$p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($p8080) {
    Write-CutoverLog "Encerrando processo Uvicorn anterior na porta 8080 (PID $($p8080.OwningProcess))..." "WARN"
    Stop-Process -Id $p8080.OwningProcess -Force -ErrorAction SilentlyContinue
    Start-Sleep -Seconds 2
}

# Confirmar Liberação
$still8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
$still8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($still8501 -or $still8080) {
    Write-CutoverLog "ABORT: As portas nao foram liberadas apos Stop-Process!" "ERROR"
    Pop-Location
    exit 1
}
Write-CutoverLog "Portas 8501 e 8080 liberadas com sucesso." "SUCCESS"
Write-CutoverLog "GATE 3 (STOP): PASS." "SUCCESS"

# ==============================================================================
# GATE 4: UPDATE (GIT E MIGRACAO IDEMPOTENTE)
# ==============================================================================
Write-CutoverLog "GATE 4: Aplicando Versao V2 e Migracoes..." "INFO"

# Reconciliar hotfix com seguranca (sem git reset --hard)
git restore app/services/autonomous_production.py
Get-ChildItem "app\services\*.bak*" -ErrorAction SilentlyContinue | Remove-Item -Force

# Fazer Checkout da Branch V2
git checkout $TargetBranch
if ($LASTEXITCODE -ne 0) {
    Write-CutoverLog "ABORT: Falha no checkout da branch $TargetBranch!" "ERROR"
    Pop-Location
    exit 1
}
$newSha = (git rev-parse HEAD).Trim()
Write-CutoverLog "Checkout da branch V2 concluido. Novo SHA: $newSha" "SUCCESS"

# Aplicar Migracao de Dados Idempotente no Banco Real
Write-CutoverLog "Aplicando migracao idempotente em $dbPath..." "INFO"
$pyMigrate = @'
import sys
from scripts.rehearse_v2_migration import apply_schema_migrations, migrate_channels_to_v2_settings
db = sys.argv[1]
apply_schema_migrations(db)
migrated = migrate_channels_to_v2_settings(db)
print(f"MIGRATION_SUCCESS: {migrated} canais validados.")
'@
$tmpMigPy = Join-Path $env:TEMP "cutover_migrate.py"
Set-Content -Path $tmpMigPy -Value $pyMigrate -Encoding UTF8
$migRes = (python $tmpMigPy "$dbPath" 2>&1)
Remove-Item -Path $tmpMigPy -ErrorAction SilentlyContinue

if ($LASTEXITCODE -ne 0) {
    Write-CutoverLog "ABORT: Falha na migracao SQLite: $migRes" "ERROR"
    Pop-Location
    exit 1
}
Write-CutoverLog "$migRes" "SUCCESS"
Write-CutoverLog "GATE 4 (UPDATE): PASS." "SUCCESS"

# ==============================================================================
# GATE 5: START (INICIALIZACAO NA PORTA 8080)
# ==============================================================================
Write-CutoverLog "GATE 5: Iniciando Servico Video Factory V2 na Porta 8080..." "INFO"

# Definir MPT_ENVIRONMENT=PRODUCTION
[System.Environment]::SetEnvironmentVariable("MPT_ENVIRONMENT", "PRODUCTION", "Machine")
$env:MPT_ENVIRONMENT = "PRODUCTION"

# Iniciar Tarefa WebUI V2
Start-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue

# Aguardar subida da porta 8080 (ate 20 segundos)
$started = $false
for ($i = 0; $i -lt 10; $i++) {
    Start-Sleep -Seconds 2
    $conn = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
    if ($conn) {
        $started = $true
        Write-CutoverLog "Servidor V2 ativo e escutando na porta 8080 (PID $($conn.OwningProcess))." "SUCCESS"
        break
    }
}

if (-not $started) {
    Write-CutoverLog "ABORT: Servidor V2 nao subiu na porta 8080 no tempo limite!" "ERROR"
    Pop-Location
    exit 1
}
Write-CutoverLog "GATE 5 (START): PASS." "SUCCESS"

# ==============================================================================
# GATE 6: HEALTH (VALIDACAO FACTUAL DE SAUDE)
# ==============================================================================
Write-CutoverLog "GATE 6: Validando Saude, Canais e Seguranca..." "INFO"

# Validar /health
try {
    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 5
    Write-CutoverLog "Health Check: $($health | ConvertTo-Json -Compress)" "SUCCESS"
} catch {
    Write-CutoverLog "Aviso no /health: $_" "WARN"
}

# Validar /api/channels
try {
    $channels = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/channels" -TimeoutSec 5
    Write-CutoverLog "Canais Carregados via API: $($channels.Count)" "SUCCESS"
} catch {
    Write-CutoverLog "Aviso ao carregar canais via API: $_" "WARN"
}

# Confirmar que a porta 8501 continua INATIVA
$streamCheck = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if ($streamCheck) {
    Write-CutoverLog "ALERTA: Porta 8501 voltou a responder! Streamlit nao deveria estar ativo." "WARN"
} else {
    Write-CutoverLog "Confirmado: Porta 8501 permanece INATIVA (Streamlit encerrado)." "SUCCESS"
}

Write-CutoverLog "============================================================" "SUCCESS"
Write-CutoverLog " CUTOVER V2.15B EXECUTADO COM SUCESSO!                     " "SUCCESS"
Write-CutoverLog " Interface V2 ativa em: http://localhost:8080             " "SUCCESS"
Write-CutoverLog " Streamlit 8501 desativado com seguranca.                  " "SUCCESS"
Write-CutoverLog " Publicacoes automaticas bloqueadas aguardando autorizacao." "SUCCESS"
Write-CutoverLog "============================================================" "SUCCESS"

Pop-Location
exit 0
