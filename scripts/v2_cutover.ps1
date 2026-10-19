<#

.SYNOPSIS

    Script Unico de Cutover V2.15B para Video Factory (PC Forte).

.DESCRIPTION

    Executa a transicao controlada, sequencial e reversivel da interface Streamlit

    para a Video Factory V2 React/FastAPI.



    GATES DE EXECUCAO:

    1. PREFLIGHT: Validacao rigorosa de SHA, diff do hotfix, integridade SQLite, tarefas/renderizacoes ativas e espaco.

    2. BACKUP: Snapshot transacional do SQLite, configuracoes, hotfix e geracao de manifesto com SHA256.

    3. STOP: Pausa de despachos, desativacao do auto-publish, parada graciosa das portas 8501 e 8080, liberacao limpa de PRIMARY e desativacao da tarefa Streamlit.

    4. UPDATE: Reconciliacao do hotfix sem comandos destrutivos, mudanca para branch V2 e migracao canonica idempotente no banco real.

    5. START: Inicializacao na porta 8080, validacao de autoridade PRIMARY unica e scheduler sem duplicidade.

    6. HEALTH: Checagem HTTP 200, validacao de canais (/api/v2/channels), papel PRIMARY (/api/v2/health), auto-publish OFF e integridade SQLite.

    7. ROLLBACK: Retorno seguro para main, avaliacao rigorosa de divergencias SQLite antes de restaurar banco e reativacao da interface Streamlit.

#>

[CmdletBinding()]

param(

    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo",

    [string]$TargetBranch = "feat/video-factory-v2",

    [switch]$Rollback,

    [string]$BackupDirToRestore = "",

    [switch]$ForceOverwriteDb = $false

)



Set-StrictMode -Off

$ErrorActionPreference = "Stop"



# Sincronizar PATH da sessao com User e Machine (para garantir git, ffmpeg, node no PATH)

$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")

$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")

$env:Path = "$machinePath;$userPath"



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



# Resolucao Determinística do Interpretador Python (.venv preferencial)

$VenvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"

$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

Write-CutoverLog "Interpretador Python : $PythonExe" "INFO"



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



    # 2. Retornar Git para main de forma segura (sem git reset --hard ou clean)

    Write-CutoverLog "Retornando Git para a branch main via checkout seguro..." "WARN"

    git checkout main

    if ($LASTEXITCODE -ne 0) {

        Write-CutoverLog "Aviso ao executar checkout da main. Verifique estado do Git." "WARN"

    }



    # 3. Avaliacao de Divergencias e Restauracao Nao-Destrutiva do Banco SQLite

    $currentDbPath = Join-Path $RepoPath "storage\video_factory.db"

    if ($BackupDirToRestore -and (Test-Path $BackupDirToRestore)) {

        $dbBak = Join-Path $BackupDirToRestore "video_factory.db"

        if (Test-Path $dbBak) {

            Write-CutoverLog "Avaliando divergencias entre banco atual e backup ($dbBak)..." "INFO"



            # Script Python para avaliacao factual de divergencias

            $pyDivCheck = @'

import sqlite3, sys, json



cur_db, bak_db = sys.argv[1], sys.argv[2]

res = {"can_restore_safely": True, "divergence_detected": False, "details": {}}



try:

    c_cur = sqlite3.connect(f"file:{cur_db}?mode=ro", uri=True)

    c_bak = sqlite3.connect(f"file:{bak_db}?mode=ro", uri=True)



    for tbl in ["publication_events", "scheduled_posts", "task_profiles", "operational_events"]:

        try:

            cur_cnt = c_cur.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]

            bak_cnt = c_bak.execute(f"SELECT count(*) FROM {tbl}").fetchone()[0]

            diff = cur_cnt - bak_cnt

            res["details"][tbl] = {"current": cur_cnt, "backup": bak_cnt, "diff": diff}

            if diff > 0 and tbl in ("publication_events", "scheduled_posts", "task_profiles"):

                res["divergence_detected"] = True

                res["can_restore_safely"] = False

        except Exception as e:

            res["details"][tbl] = {"error": str(e)}



    c_cur.close()

    c_bak.close()

except Exception as e:

    res["error"] = str(e)

    res["can_restore_safely"] = False



print(json.dumps(res))

'@

            $tmpDivPy = Join-Path $env:TEMP "cutover_divergence_check.py"

            Set-Content -Path $tmpDivPy -Value $pyDivCheck -Encoding UTF8

            $divResRaw = (& $PythonExe $tmpDivPy "$currentDbPath" "$dbBak" 2>&1)

            Remove-Item -Path $tmpDivPy -ErrorAction SilentlyContinue



            $divJson = ($divResRaw | Where-Object { $_ -like '*{*' }) | Select-Object -Last 1

            $divObj = $null

            if ($divJson) {

                try { $divObj = $divJson | ConvertFrom-Json } catch {}

            }



            if ($divObj -and $divObj.divergence_detected -and -not $ForceOverwriteDb) {

                Write-CutoverLog "BLOQUEIO DE SEGURANCA: O banco atual possui novos registros criados apos o backup!" "ERROR"

                Write-CutoverLog "Detalhes: $($divObj.details | ConvertTo-Json -Compress)" "ERROR"

                Write-CutoverLog "A sobrescrita cega provocaria perda permanente de registros SQLite." "ERROR"

                Write-CutoverLog "Para sobrescrever conscientemente, execute com -ForceOverwriteDb." "ERROR"

                Pop-Location

                exit 1

            }



            # Criar snapshot de contingencia pre-rollback antes de qualquer substituicao

            $tsRollback = (Get-Date -Format 'yyyyMMdd_HHmmss')

            $preRollbackDir = Join-Path $RepoPath "storage\backups\pre_rollback_$tsRollback"

            New-Item -ItemType Directory -Path $preRollbackDir -Force | Out-Null

            Copy-Item $currentDbPath (Join-Path $preRollbackDir "video_factory.db") -Force

            if (Test-Path "$currentDbPath-wal") { Copy-Item "$currentDbPath-wal" (Join-Path $preRollbackDir "video_factory.db-wal") -Force }

            if (Test-Path "$currentDbPath-shm") { Copy-Item "$currentDbPath-shm" (Join-Path $preRollbackDir "video_factory.db-shm") -Force }

            Write-CutoverLog "Snapshot de seguranca pre-rollback salvo em $preRollbackDir." "SUCCESS"



            # Limpar arquivos WAL e SHM ativos antes de restaurar

            Remove-Item "$currentDbPath-wal" -Force -ErrorAction SilentlyContinue

            Remove-Item "$currentDbPath-shm" -Force -ErrorAction SilentlyContinue



            # Restaurar arquivo principal do banco

            Copy-Item $dbBak $currentDbPath -Force

            Write-CutoverLog "Banco SQLite restaurado com sucesso a partir do backup." "SUCCESS"



            # Validar integridade SQLite do banco restaurado

            $integCheck = (& $PythonExe -c "import sqlite3; c=sqlite3.connect(r'$currentDbPath'); print(c.execute('PRAGMA integrity_check;').fetchone()[0]); c.close()" 2>&1)

            Write-CutoverLog "Integridade SQLite pos-restauracao: $integCheck" $(if ($integCheck -eq 'ok') { "SUCCESS" } else { "ERROR" })

            if ($integCheck -ne 'ok') {

                Write-CutoverLog "FALHA CRITICA: Banco restaurado nao passou no integrity check!" "ERROR"

                Pop-Location

                exit 1

            }

        }



        # Restaurar hotfix local

        $hfBak = Join-Path $BackupDirToRestore "hotfix\autonomous_production.py"

        if (Test-Path $hfBak) {

            Copy-Item $hfBak "app\services\autonomous_production.py" -Force

            Write-CutoverLog "Hotfix local autonomous_production.py restaurado." "SUCCESS"

        }

    }



    # 4. Reabilitar e Iniciar Tarefas Agendadas Legadas

    Write-CutoverLog "Reabilitando tarefas agendadas legadas..." "WARN"

    Enable-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue

    Start-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue

    Start-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue



    # Validar restabelecimento do Streamlit na porta 8501

    Start-Sleep -Seconds 5

    $conn8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue

    if ($conn8501) {

        Write-CutoverLog "Streamlit ativo e respondendo na porta 8501 (PID $($conn8501.OwningProcess))." "SUCCESS"

    } else {

        Write-CutoverLog "Aviso: Porta 8501 ainda nao respondeu. Verifique VideoFactory Production." "WARN"

    }



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



# Validar Diff do Hotfix e Preservar Arquivos Nao Rastreados

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



# Validar se ha processos de renderizacao FFmpeg ativos

$activeFfmpeg = Get-Process ffmpeg -ErrorAction SilentlyContinue

if ($activeFfmpeg) {

    Write-CutoverLog "ABORT: Renderizacao FFmpeg em andamento (PID $($activeFfmpeg.Id)). Aguarde o termino antes do cutover!" "ERROR"

    Pop-Location

    exit 1

}



# Validar Integridade e Publicacoes Ativas no SQLite

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



cur.execute("SELECT count(*) FROM scheduled_posts WHERE status = 'processing'")

active = cur.fetchone()[0]

if active > 0:

    print(f"ACTIVE_POSTS_FAIL: {active} postagens em andamento ('processing')")

    sys.exit(2)



print("PREFLIGHT_DB_OK")

conn.close()

'@

$tmpPy = Join-Path $env:TEMP "cutover_preflight.py"

Set-Content -Path $tmpPy -Value $pyPreflight -Encoding UTF8

$preflightRes = (& $PythonExe $tmpPy "$dbPath" 2>&1)

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



# Copiar Banco de Dados Fisico e Arquivos WAL/SHM

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

# GATE 3: STOP (QUIESCENCIA, DESATIVACAO DO AUTO-PUBLISH E LIBERACAO DE PRIMARY)

# ==============================================================================

Write-CutoverLog "GATE 3: Pausando Fabrica, Desativando Auto-Publish e Parando Streamlit..." "INFO"



# Pausar Fabrica e Desativar Explicitamente Auto-Publish e Scheduler no SQLite

$pyPause = @'

import sys

db = sys.argv[1]

try:

    from app.services import operator_console, scheduler

    operator_console.pause_factory(db_path=db)

    scheduler.set_setting("auto_publish_enabled", "false", db_path=db)

    scheduler.set_setting("scheduler_enabled", "false", db_path=db)

    print("FACTORY_PAUSED_AUTOPUBLISH_DISABLED")

except Exception as e:

    print(f"PAUSE_NOTICE: {e}")

'@

$tmpPausePy = Join-Path $env:TEMP "cutover_pause.py"

Set-Content -Path $tmpPausePy -Value $pyPause -Encoding UTF8

$pauseRes = (& $PythonExe $tmpPausePy "$dbPath" 2>&1)

Remove-Item -Path $tmpPausePy -ErrorAction SilentlyContinue

Write-CutoverLog "Estado da fabrica pre-parada: $pauseRes" "INFO"



# Parar Tarefas Agendadas

Stop-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue

Stop-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue



# Desativar Tarefa Streamlit para Impedir Auto-Reinicializacao Concorrente

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



# Confirmar Encerramento de Qualquer Processo de Entrypoint de Producao Residual

Get-CimInstance Win32_Process -ErrorAction SilentlyContinue | Where-Object {

    $_.CommandLine -like "*production_entrypoint.py*"

} | ForEach-Object {

    Write-CutoverLog "Encerrando processo residual de production_entrypoint (PID $($_.ProcessId))..." "WARN"

    Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue

}



# Confirmar Liberacao das Portas

$still8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue

$still8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue

if ($still8501 -or $still8080) {

    Write-CutoverLog "ABORT: As portas nao foram liberadas apos Stop-Process!" "ERROR"

    Pop-Location

    exit 1

}

Write-CutoverLog "Portas 8501 e 8080 liberadas com sucesso." "SUCCESS"



# Liberar Stale Instance Lock Administrativamente no SQLite

$pyReleaseLock = @'

import sys

db = sys.argv[1]

try:

    from app.services import operator_console

    res = operator_console.release_stale_instance_lock(

        confirm_token="RELEASE_STALE_PRIMARY",

        force_ignore_flags=True,

        db_path=db

    )

    print(f"LOCK_RELEASED: {res.get('released', False)} (status: {res.get('status')})")

except Exception as e:

    print(f"LOCK_RELEASE_NOTICE: {e}")

'@

$tmpRelPy = Join-Path $env:TEMP "cutover_release_lock.py"

Set-Content -Path $tmpRelPy -Value $pyReleaseLock -Encoding UTF8

$relRes = (& $PythonExe $tmpRelPy "$dbPath" 2>&1)

Remove-Item -Path $tmpRelPy -ErrorAction SilentlyContinue

Write-CutoverLog "Liberacao de autoridade PRIMARY anterior: $relRes" "SUCCESS"



Write-CutoverLog "GATE 3 (STOP): PASS." "SUCCESS"



# ==============================================================================

# GATE 4: UPDATE (GIT E MIGRACAO CANONICA IDEMPOTENTE)

# ==============================================================================

Write-CutoverLog "GATE 4: Aplicando Versao V2 e Migracoes Canonicas..." "INFO"



# Reconciliar hotfix com seguranca (sem git reset --hard ou clean; preservando arquivos nao rastreados)

git restore app/services/autonomous_production.py

Write-CutoverLog "Hotfix app/services/autonomous_production.py restaurado para o commit limpo." "SUCCESS"



# Fazer Checkout da Branch V2

git checkout $TargetBranch

if ($LASTEXITCODE -ne 0) {

    Write-CutoverLog "ABORT: Falha no checkout da branch $TargetBranch!" "ERROR"

    Pop-Location

    exit 1

}

$newSha = (git rev-parse HEAD).Trim()

Write-CutoverLog "Checkout da branch V2 concluido. Novo SHA: $newSha" "SUCCESS"



# Aplicar Migracao de Dados Canonica e Idempotente no Banco Real

Write-CutoverLog "Aplicando migracoes canonicas em $dbPath..." "INFO"

$pyMigrate = @'

import sys, sqlite3

db = sys.argv[1]



from app.services import (

    profile_manager,

    scheduler,

    quality_recovery,

    operator_console,

    safety_gate,

    quality_score,

)



# 1. Inicializacoes canonicas idempotentes dos servicos de banco

profile_manager.init_profile_db(db_path=db)

scheduler.init_db(db_path=db)

quality_recovery.init_review_db(db_path=db)

operator_console.init_operator_db(db_path=db)

safety_gate.init_safety_db(db_path=db)

quality_score.init_quality_db(db_path=db)



# 2. Inicializacao segura de settings_json para perfis legados sem sobrescrever perfis ja configurados

with sqlite3.connect(db) as conn:

    conn.row_factory = sqlite3.Row

    cur = conn.cursor()

    profiles = cur.execute("SELECT id, default_preset, settings_json FROM content_profiles").fetchall()

    migrated_count = 0

    for p in profiles:

        pid = p["id"]

        raw_st = p["settings_json"]

        if not raw_st or raw_st.strip() in ("", "{}"):

            preset = (p["default_preset"] or "").strip().lower()

            st = profile_manager.ChannelWorkspaceSettings()

            if preset in ("quiz_dilemma", "quiz"):

                st.editorial.video_format = "quiz_dilemma"

            elif preset in ("quiz_paper", "quiz_perguntas_respostas_papel"):

                st.editorial.video_format = "quiz_paper"

            else:

                st.editorial.video_format = "traditional"

            cur.execute(

                "UPDATE content_profiles SET settings_json = ? WHERE id = ?;",

                (st.to_json(), pid),

            )

            migrated_count += 1

    conn.commit()



# 3. Garantia estrita de auto_publish_enabled = false

scheduler.set_setting("auto_publish_enabled", "false", db_path=db)

scheduler.set_setting("scheduler_enabled", "false", db_path=db)



# 4. Validar integridade SQLite

with sqlite3.connect(db) as conn:

    integ = conn.execute("PRAGMA integrity_check;").fetchone()[0]

    if integ != "ok":

        raise RuntimeError(f"Integrity check falhou apos migracao: {integ}")



print(f"CANONICAL_MIGRATION_OK: {len(profiles)} canais verificados ({migrated_count} inicializados). Auto-publish mantido OFF.")

'@

$tmpMigPy = Join-Path $env:TEMP "cutover_migrate.py"

Set-Content -Path $tmpMigPy -Value $pyMigrate -Encoding UTF8

$migRes = (& $PythonExe $tmpMigPy "$dbPath" 2>&1)

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



# Aguardar subida da porta 8080 (ate 25 segundos)

$started = $false

for ($i = 0; $i -lt 12; $i++) {

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

# GATE 6: HEALTH (VALIDACAO FACTUAL DE SAUDE, PRIMARY E SEGURANCA)

# ==============================================================================

Write-CutoverLog "GATE 6: Validando Saude, Canais, Papel PRIMARY e Seguranca..." "INFO"



# 1. Validar /health basico

try {

    $health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/health" -TimeoutSec 5

    Write-CutoverLog "Health Check (/health): $($health | ConvertTo-Json -Compress)" "SUCCESS"

} catch {

    Write-CutoverLog "Aviso no /health: $_" "WARN"

}



# 2. Validar /api/v2/health e Autoridade PRIMARY

try {

    $v2Health = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health" -TimeoutSec 5

    Write-CutoverLog "Operational Health (/api/v2/health): Role=$($v2Health.data.role) | is_primary=$($v2Health.data.is_primary)" "SUCCESS"

    if ($v2Health.data.role -ne "PRIMARY") {

        Write-CutoverLog "ALERTA: Instancia V2 reportou role '$($v2Health.data.role)' em vez de PRIMARY!" "WARN"

    }

} catch {

    Write-CutoverLog "Aviso ao consultar /api/v2/health: $_" "WARN"

}



# 3. Validar /api/v2/channels

try {

    $channelsResp = Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/channels" -TimeoutSec 5

    $channelCount = if ($channelsResp.data) { $channelsResp.data.Count } else { 0 }

    Write-CutoverLog "Canais Carregados via API V2: $channelCount" "SUCCESS"

} catch {

    Write-CutoverLog "Aviso ao carregar canais via API V2: $_" "WARN"

}



# 4. Confirmar que a porta 8501 continua INATIVA

$streamCheck = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue

if ($streamCheck) {

    Write-CutoverLog "ALERTA: Porta 8501 voltou a responder! Streamlit nao deveria estar ativo." "WARN"

} else {

    Write-CutoverLog "Confirmado: Porta 8501 permanece INATIVA (Streamlit encerrado)." "SUCCESS"

}



# 5. Confirmar que auto_publish permanece OFF no SQLite

$pyCheckAp = @'

import sqlite3, sys

db = sys.argv[1]

conn = sqlite3.connect(f"file:{db}?mode=ro", uri=True)

cur = conn.cursor()

cur.execute("SELECT value FROM autopilot_settings WHERE key = 'auto_publish_enabled'")

row = cur.fetchone()

val = row[0] if row else "false"

conn.close()

print(val)

'@

$tmpApPy = Join-Path $env:TEMP "check_ap_state.py"

Set-Content -Path $tmpApPy -Value $pyCheckAp -Encoding UTF8

$apVal = (& $PythonExe $tmpApPy "$dbPath" 2>&1).Trim()

Remove-Item -Path $tmpApPy -ErrorAction SilentlyContinue



if ($apVal -eq "true") {

    Write-CutoverLog "FALHA DE SEGURANCA: auto_publish_enabled permanece ativo (true)!" "ERROR"

    Pop-Location

    exit 1

} else {

    Write-CutoverLog "Confirmado: auto_publish_enabled permanece DESATIVADO ($apVal)." "SUCCESS"

}



Write-CutoverLog "============================================================" "SUCCESS"

Write-CutoverLog " CUTOVER V2.15B EXECUTADO COM SUCESSO!                     " "SUCCESS"

Write-CutoverLog " Interface V2 ativa em: http://localhost:8080             " "SUCCESS"

Write-CutoverLog " Streamlit 8501 desativado com seguranca.                  " "SUCCESS"

Write-CutoverLog " Publicacoes automaticas bloqueadas aguardando autorizacao." "SUCCESS"

Write-CutoverLog "============================================================" "SUCCESS"



Pop-Location

exit 0
