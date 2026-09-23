<#
.SYNOPSIS
    Script de Atualização Segura e Não-Destrutiva de Produção (Fase V13-A).
.DESCRIPTION
    Executa atualizações controladas, transacionais e verificáveis da instalação
    de produção do MoneyPrinterTurbo / Video Factory:
    PRE-FLIGHT -> BACKUP -> STOP -> UPDATE FF-ONLY -> START -> HEALTH CHECK -> SUCCESS
    com rollback seguro e não-destrutivo em caso de falha pós-update.

    PRINCÍPIOS DE SEGURANÇA:
    - Zero comandos destrutivos (NUNCA usar git reset, git restore ou git clean)
    - Somente aceita avanço Fast-Forward (merge-base --is-ancestor obrigatório)
    - Backup transacional do SQLite com PRAGMA integrity_check e SHA-256 antes da parada
    - Parada e inicialização exclusivas via Scheduled Task do Windows
    - Health check delimitado em http://127.0.0.1:8501/_stcore/health (HTTP 200 + 'ok')
    - Rollback via 'git switch --detach CURRENT_SHA' preservando a branch main intacta
    - Lock exclusivo contra execuções simultâneas
    - Registro de auditoria sanitizado em logs/deploy/ (zero credenciais ou segredos)
#>

[CmdletBinding()]
param(
    [string]$TargetRef = "origin/main",
    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo",
    [string]$TaskName = "VideoFactory Production",
    [string]$HealthUrl = "http://127.0.0.1:8501/_stcore/health",
    [switch]$PreflightOnly,
    [switch]$SkipTaskCheck = $false
)

$ErrorActionPreference = "Stop"

# ==============================================================================
# 1. FUNÇÕES AUXILIARES DE LOGGING E SAÚDE
# ==============================================================================

$Global:LogFilePath = $null

function Init-DeployLogger {
    param([string]$BasePath)
    $DeployLogDir = Join-Path $BasePath "logs\deploy"
    if (-not (Test-Path $DeployLogDir)) {
        New-Item -ItemType Directory -Path $DeployLogDir -Force | Out-Null
    }
    $Timestamp = (Get-Date).ToUniversalTime().ToString("yyyyMMdd_HHmmss")
    $Global:LogFilePath = Join-Path $DeployLogDir "update_$Timestamp.log"
}

function Write-DeployLog {
    param(
        [string]$Message,
        [string]$Level = "INFO",
        [switch]$IsError = $false
    )
    $UtcTime = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $Formatted = "[$UtcTime][$Level] $Message"

    if ($IsError) {
        Write-Host $Formatted -ForegroundColor Red
    } elseif ($Level -eq "WARN") {
        Write-Host $Formatted -ForegroundColor Yellow
    } elseif ($Level -eq "SUCCESS") {
        Write-Host $Formatted -ForegroundColor Green
    } else {
        Write-Host $Formatted -ForegroundColor Cyan
    }

    if ($Global:LogFilePath) {
        try {
            Add-Content -Path $Global:LogFilePath -Value $Formatted -Encoding UTF8
        } catch {
            # Evita interromper o script se a escrita do log falhar
        }
    }
}

function Test-HealthEndpoint {
    param(
        [string]$Url,
        [int]$TimeoutSeconds = 75,
        [int]$IntervalSeconds = 3
    )
    $Watch = [System.Diagnostics.Stopwatch]::StartNew()
    while ($Watch.Elapsed.TotalSeconds -lt $TimeoutSeconds) {
        try {
            $Response = Invoke-WebRequest -Uri $Url -Method Get -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
            if ($Response.StatusCode -eq 200 -and $Response.Content -match "ok") {
                $Watch.Stop()
                return $true
            }
        } catch {
            # Conexão recusada ou servidor inicializando; aguarda retry
        }
        Start-Sleep -Seconds $IntervalSeconds
    }
    $Watch.Stop()
    return $false
}

function Format-Summary {
    param(
        [string]$CurrentSha,
        [string]$TargetSha,
        [string]$BackupResult,
        [string]$UpdateResult,
        [string]$HealthResult,
        [string]$RollbackResult,
        [string]$FinalSha,
        [string]$Status,
        [string]$FailureReason = ""
    )
    Write-Host ""
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host " SAFE UPDATE RESULT" -ForegroundColor Cyan
    Write-Host "==================================================" -ForegroundColor Cyan
    Write-Host "CURRENT_SHA     = $CurrentSha"
    Write-Host "TARGET_SHA      = $TargetSha"
    Write-Host "BACKUP          = $BackupResult"
    Write-Host "UPDATE          = $UpdateResult"
    Write-Host "HEALTH          = $HealthResult"
    Write-Host "ROLLBACK        = $RollbackResult"
    Write-Host "FINAL_SHA       = $FinalSha"
    Write-Host "STATUS          = $Status"
    if ($FailureReason -ne "") {
        Write-Host "FAILURE_REASON  = $FailureReason" -ForegroundColor Yellow
    }
    Write-Host "==================================================" -ForegroundColor Cyan
}

# ==============================================================================
# 2. VALIDAÇÃO DE AMBIENTE E RESOLUÇÃO DE DIRETÓRIOS
# ==============================================================================

if (-not (Test-Path $RepoPath)) {
    Write-Error "ERRO CRÍTICO: Diretório do repositório não encontrado em '$RepoPath'."
    exit 1
}

$RepoPathResolved = (Resolve-Path $RepoPath).Path
Set-Location -Path $RepoPathResolved
$env:PYTHONPATH = $RepoPathResolved

Init-DeployLogger -BasePath $RepoPathResolved

Write-DeployLog "Iniciando processo de verificação e atualização segura."
Write-DeployLog "Repositório: $RepoPathResolved | TargetRef: $TargetRef | TaskName: $TaskName"

# ==============================================================================
# 3. GESTÃO DE LOCK EXCLUSIVO
# ==============================================================================

$LockDir = Join-Path $RepoPathResolved "storage\locks"
$LockFile = Join-Path $LockDir "update_production.lock"
$AcquiredLock = $false

if (-not $PreflightOnly) {
    if (-not (Test-Path $LockDir)) {
        New-Item -ItemType Directory -Path $LockDir -Force | Out-Null
    }

    if (Test-Path $LockFile) {
        $LockContent = Get-Content -Path $LockFile -Raw -ErrorAction SilentlyContinue
        $ActivePid = $null
        if ($LockContent -match 'PID:\s*(\d+)') {
            $ActivePid = [int]$Matches[1]
        }

        if ($ActivePid -and (Get-Process -Id $ActivePid -ErrorAction SilentlyContinue)) {
            Write-DeployLog "ABORT: Atualização já em andamento por outro processo (Lock: $LockFile, PID $ActivePid)." -Level "ERROR" -IsError
            Format-Summary -CurrentSha "UNKNOWN" -TargetSha "UNKNOWN" -BackupResult "NOT_ATTEMPTED" -UpdateResult "NOT_ATTEMPTED" -HealthResult "NOT_ATTEMPTED" -RollbackResult "NOT_REQUIRED" -FinalSha "UNKNOWN" -Status "DEPLOY_FAILED" -FailureReason "Conflito de Lock (atualização concorrente detectada)."
            exit 1
        } else {
            Write-DeployLog "Lock anterior órfão detectado e limpo com segurança." -Level "WARN"
            Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
        }
    }

    $LockPayload = "PID: $PID`nUTC: $((Get-Date).ToUniversalTime().ToString('o'))`nTargetRef: $TargetRef"
    Set-Content -Path $LockFile -Value $LockPayload -Encoding UTF8
    $AcquiredLock = $true
}

try {
    # ==============================================================================
    # 4. PRE-FLIGHT (FAIL-CLOSED)
    # ==============================================================================

    Write-DeployLog "Executando verificações de Pre-flight (fail-closed)..."

    # 4.1 Validação do Git
    $GitDir = Join-Path $RepoPathResolved ".git"
    if (-not (Test-Path $GitDir)) {
        Write-DeployLog "ABORT: Diretório .git não encontrado em '$RepoPathResolved'." -Level "ERROR" -IsError
        throw "Diretório Git não encontrado."
    }

    # 4.2 Validação do Ambiente Virtual Python (.venv)
    $VenvPython = Join-Path $RepoPathResolved ".venv\Scripts\python.exe"
    if (-not (Test-Path $VenvPython)) {
        Write-DeployLog "ABORT: Ambiente virtual (.venv) não encontrado em '$VenvPython'." -Level "ERROR" -IsError
        throw "Ambiente virtual (.venv) ausente."
    }

    # 4.3 Validação de Working Tree Limpa (FAIL-CLOSED)
    $StatusOutput = @(git status --porcelain 2>&1)
    if ($LASTEXITCODE -ne 0) {
        Write-DeployLog "ABORT: Falha ao executar 'git status': $StatusOutput" -Level "ERROR" -IsError
        throw "Falha ao consultar git status."
    }

    # Filtra modificações em arquivos rastreados ou arquivos untracked críticos (.py, .ps1, .toml, .json, .sh, .bat)
    $TrackedModifications = $StatusOutput | Where-Object { $_ -notmatch '^\?\?' }
    $CriticalUntracked = $StatusOutput | Where-Object { $_ -match '^\?\?\s+.*(\.py|\.ps1|\.sh|\.bat|\.toml|\.json)$' }

    if ($TrackedModifications.Count -gt 0 -or $CriticalUntracked.Count -gt 0) {
        Write-DeployLog "ABORT: Working tree não está limpa. Modificações não commitadas detectadas." -Level "ERROR" -IsError
        foreach ($line in $StatusOutput) {
            Write-DeployLog "  [DIRTY] $line" -Level "WARN"
        }
        throw "Working tree suja detectada antes do update."
    }
    Write-DeployLog "Working tree verificada: LIMPA."

    # 4.4 Identificação do Commit Atual (CURRENT_SHA)
    $CurrentSha = (git rev-parse HEAD 2>&1).Trim()
    if ($CurrentSha -notmatch '^[0-9a-fA-F]{40}$') {
        Write-DeployLog "ABORT: Não foi possível obter CURRENT_SHA válido: $CurrentSha" -Level "ERROR" -IsError
        throw "CURRENT_SHA inválido."
    }
    Write-DeployLog "CURRENT_SHA: $CurrentSha"

    # 4.5 Resolução do Remote e Fetch de TargetRef
    $Remotes = @(git remote)
    if ("origin" -in $Remotes) {
        $RemoteUrl = (git remote get-url origin).Trim()
        Write-DeployLog "Remote origin configurado: $RemoteUrl"
        Write-DeployLog "Executando fetch do remote origin..."
        git fetch origin --quiet
        if ($LASTEXITCODE -ne 0) {
            Write-DeployLog "AVISO: Falha ao executar 'git fetch origin'." -Level "WARN"
        }
    } else {
        Write-DeployLog "AVISO: Remote 'origin' não configurado localmente." -Level "WARN"
    }

    # 4.6 Resolução do Target Commit (TARGET_SHA)
    $TargetSha = (git rev-parse $TargetRef).Trim()
    if ($LASTEXITCODE -ne 0 -or $TargetSha -notmatch '^[0-9a-fA-F]{40}$') {
        Write-DeployLog "ABORT: TargetRef '$TargetRef' não pôde ser resolvido para um commit válido: $TargetSha" -Level "ERROR" -IsError
        throw "TargetRef não resolvido."
    }
    Write-DeployLog "TARGET_SHA : $TargetSha"

    # 4.7 Validação de Fast-Forward Safety (merge-base --is-ancestor)
    git merge-base --is-ancestor $CurrentSha $TargetSha
    if ($LASTEXITCODE -ne 0) {
        Write-DeployLog "ABORT: Fast-Forward safety violada. CURRENT_SHA ($CurrentSha) não é ancestral de TARGET_SHA ($TargetSha). Merge e rebase são proibidos." -Level "ERROR" -IsError
        throw "Atualização não é Fast-Forward."
    }
    Write-DeployLog "Fast-Forward safety verificada: COMPATÍVEL."

    # 4.8 Verificação da Scheduled Task
    if (-not $SkipTaskCheck) {
        $TaskQuery = schtasks /Query /TN $TaskName 2>&1
        if ($LASTEXITCODE -ne 0) {
            Write-DeployLog "Scheduled Task '$TaskName' não foi encontrada no sistema." -Level "WARN"
            if ($PreflightOnly) {
                Write-DeployLog "PREFLIGHT_FAIL: Scheduled Task ausente." -Level "ERROR" -IsError
                Format-Summary -CurrentSha $CurrentSha -TargetSha $TargetSha -BackupResult "NOT_ATTEMPTED" -UpdateResult "NOT_ATTEMPTED" -HealthResult "NOT_ATTEMPTED" -RollbackResult "NOT_REQUIRED" -FinalSha $CurrentSha -Status "PREFLIGHT_FAIL" -FailureReason "Scheduled Task '$TaskName' inexistente."
                exit 1
            } else {
                throw "Scheduled Task '$TaskName' inexistente."
            }
        }
        Write-DeployLog "Scheduled Task '$TaskName' verificada: PRESENTE."
    }

    # 4.9 Execução em Modo PreflightOnly
    if ($PreflightOnly) {
        Write-Host ""
        Write-Host "==================================================" -ForegroundColor Cyan
        Write-Host " PREFLIGHT PLAN (SOMENTE AUDITORIA / PASSIVO)" -ForegroundColor Cyan
        Write-Host "==================================================" -ForegroundColor Cyan
        Write-Host "REPO_PATH       : $RepoPathResolved"
        Write-Host "CURRENT_SHA     : $CurrentSha"
        Write-Host "TARGET_SHA      : $TargetSha"
        Write-Host "TASK_NAME       : $TaskName"
        Write-Host "HEALTH_URL      : $HealthUrl"
        Write-Host "FAST_FORWARD    : COMPATÍVEL"
        Write-Host "BACKUP_STRATEGY : Snapshot SQLite transacional (PRAGMA integrity_check + SHA-256)"
        Write-Host "UPDATE_STRATEGY : Fast-Forward FF-only para $TargetSha (com produção parada)"
        Write-Host "HEALTH_STRATEGY : $HealthUrl (timeout 75s, HTTP 200 + 'ok')"
        Write-Host "ROLLBACK_PLAN   : git switch --detach $CurrentSha (não-destrutivo)"
        Write-Host "STATUS          : PREFLIGHT_PASS"
        Write-Host "==================================================" -ForegroundColor Cyan
        Write-DeployLog "Pre-flight concluído com sucesso: PREFLIGHT_PASS." -Level "SUCCESS"
        exit 0
    }

    # ==============================================================================
    # 5. BACKUP TRANSACIONAL ANTES DE STOP/UPDATE
    # ==============================================================================

    Write-DeployLog "Executando backup transacional consistente do banco SQLite antes de parar produção..."
    $BackupSummary = "NOT_ATTEMPTED"

    $ProcessInfo = New-Object System.Diagnostics.ProcessStartInfo
    $ProcessInfo.FileName = $VenvPython
    $ProcessInfo.Arguments = "-m app.services.production_backup --json"
    $ProcessInfo.WorkingDirectory = $RepoPathResolved
    $ProcessInfo.RedirectStandardOutput = $true
    $ProcessInfo.RedirectStandardError = $true
    $ProcessInfo.UseShellExecute = $false
    $ProcessInfo.CreateNoWindow = $true

    $Process = [System.Diagnostics.Process]::Start($ProcessInfo)
    $BackupStdout = $Process.StandardOutput.ReadToEnd()
    $BackupStderr = $Process.StandardError.ReadToEnd()
    $Process.WaitForExit()
    $BackupExit = $Process.ExitCode

    if ($BackupStderr -and $BackupStderr.Trim() -ne "") {
        foreach ($errLine in ($BackupStderr -split "`r?`n")) {
            if ($errLine.Trim() -ne "") {
                Write-DeployLog "  [BACKUP-LOG] $errLine" -Level "INFO"
            }
        }
    }

    if ($BackupExit -ne 0) {
        $BackupSummary = "FAIL (código de saída $BackupExit)"
        Write-DeployLog "ABORT: Falha na geração do backup SQLite (código $BackupExit): $BackupStderr" -Level "ERROR" -IsError
        throw "Falha ao gerar backup de produção."
    }

    try {
        $BackupData = $BackupStdout | ConvertFrom-Json
    } catch {
        $BackupSummary = "FAIL (erro de decodificação JSON do manifesto)"
        Write-DeployLog "ABORT: Falha ao interpretar manifesto JSON do backup SQLite. Saída stdout: $BackupStdout" -Level "ERROR" -IsError
        throw "Manifesto de backup inválido."
    }

    $PathNotEmpty = (-not [string]::IsNullOrWhiteSpace($BackupData.database_path))
    $ShaNotEmpty = (-not [string]::IsNullOrWhiteSpace($BackupData.sha256))
    $SuccessTrue = ($BackupData.success -eq $true)
    $IntegrityOk = ($BackupData.integrity_check -eq "ok")

    if (-not $SuccessTrue -or -not $IntegrityOk -or -not $PathNotEmpty -or -not $ShaNotEmpty) {
        $BackupSummary = "FAIL (validação de integridade ou metadados)"
        Write-DeployLog "ABORT: Validação dos metadados do backup SQLite falhou: success=$SuccessTrue, integrity=$($BackupData.integrity_check), path_present=$PathNotEmpty, sha_present=$ShaNotEmpty" -Level "ERROR" -IsError
        throw "Integridade ou metadados do backup SQLite violados."
    }

    $BackupPath = $BackupData.database_path
    $BackupSha256 = $BackupData.sha256
    $BackupSummary = "PASS ($BackupPath, sha256=$BackupSha256)"
    Write-DeployLog "Backup SQLite verificado com sucesso. Integridade: OK | SHA256: $BackupSha256" -Level "SUCCESS"

    # ==============================================================================
    # 6. STOP SEGURO DA PRODUÇÃO
    # ==============================================================================

    Write-DeployLog "Parando a Scheduled Task '$TaskName' de forma segura..."
    schtasks /End /TN $TaskName 2>&1 | Out-Null

    $StopTimeoutSeconds = 30
    $StopWatch = [System.Diagnostics.Stopwatch]::StartNew()
    $StoppedSafely = $false

    while ($StopWatch.Elapsed.TotalSeconds -lt $StopTimeoutSeconds) {
        Start-Sleep -Seconds 2
        $TaskQuery = schtasks /Query /TN $TaskName /FO CSV /NH 2>&1
        $IsRunning = ($TaskQuery -match "Running|Em execução")

        $PortOpen = $false
        try {
            $TcpClient = New-Object System.Net.Sockets.TcpClient
            $ConnectTask = $TcpClient.ConnectAsync("127.0.0.1", 8501)
            if ($ConnectTask.Wait(500) -and $TcpClient.Connected) {
                $PortOpen = $true
                $TcpClient.Close()
            }
        } catch {}

        if (-not $IsRunning -and -not $PortOpen) {
            $StoppedSafely = $true
            break
        }
    }
    $StopWatch.Stop()

    if (-not $StoppedSafely) {
        Write-DeployLog "ABORT: Não foi possível confirmar a parada segura da aplicação dentro de $StopTimeoutSeconds s." -Level "ERROR" -IsError
        throw "Timeout ao parar a produção de forma segura."
    }
    Write-DeployLog "Serviço de produção parado com sucesso."

    # ==============================================================================
    # 7. UPDATE (FF-ONLY)
    # ==============================================================================

    Write-DeployLog "Aplicando atualização Fast-Forward para TARGET_SHA ($TargetSha)..."
    $CurrentBranch = (git rev-parse --abbrev-ref HEAD 2>&1).Trim()

    if ($CurrentBranch -eq "HEAD") {
        git checkout $TargetSha 2>&1 | Out-Null
    } else {
        git merge --ff-only $TargetSha 2>&1 | Out-Null
    }

    $NewSha = (git rev-parse HEAD 2>&1).Trim()
    if ($NewSha -ne $TargetSha) {
        Write-DeployLog "ERRO CRÍTICO: HEAD diverge do TARGET_SHA esperado. Obtido: $NewSha | Esperado: $TargetSha" -Level "ERROR" -IsError
        throw "Atualização Git divergiu do TARGET_SHA."
    }
    Write-DeployLog "Atualização Git FF-only aplicada com sucesso. Novo HEAD: $NewSha"

    # ==============================================================================
    # 8. START DA PRODUÇÃO
    # ==============================================================================

    Write-DeployLog "Iniciando a Scheduled Task '$TaskName'..."
    schtasks /Run /TN $TaskName 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) {
        Write-DeployLog "ERRO: Falha ao solicitar início da Scheduled Task '$TaskName'." -Level "ERROR" -IsError
    }

    # ==============================================================================
    # 9. HEALTH CHECK BOUNDED
    # ==============================================================================

    Write-DeployLog "Aguardando startup e executando health check em $HealthUrl (timeout 75s)..."
    $HealthPassed = Test-HealthEndpoint -Url $HealthUrl -TimeoutSeconds 75 -IntervalSeconds 3

    if ($HealthPassed) {
        Write-DeployLog "Health check passou com sucesso (HTTP 200 'ok'). Atualização concluída com êxito!" -Level "SUCCESS"
        Format-Summary -CurrentSha $CurrentSha -TargetSha $TargetSha -BackupResult $BackupSummary -UpdateResult "PASS" -HealthResult "PASS" -RollbackResult "NOT_REQUIRED" -FinalSha $NewSha -Status "DEPLOY_SUCCESS"
        exit 0
    }

    # ==============================================================================
    # 10. ROLLBACK NÃO-DESTRUTIVO SE HEALTH FAIL
    # ==============================================================================

    Write-DeployLog "ALERTA: Health check falhou após atualização. Iniciando procedimento de ROLLBACK não-destrutivo..." -Level "WARN"

    # 10.1 Parar novamente a tarefa
    Write-DeployLog "Parando Scheduled Task '$TaskName' para rollback..."
    schtasks /End /TN $TaskName 2>&1 | Out-Null
    Start-Sleep -Seconds 5

    # 10.2 Retornar ao CURRENT_SHA via git switch --detach (SEM git reset, git restore ou git clean)
    Write-DeployLog "Executando 'git switch --detach $CurrentSha'..."
    git switch --detach $CurrentSha 2>&1 | Out-Null

    $RollbackHead = (git rev-parse HEAD 2>&1).Trim()
    Write-DeployLog "HEAD após rollback: $RollbackHead"

    # 10.3 Reiniciar serviço no commit anterior
    Write-DeployLog "Reiniciando Scheduled Task '$TaskName' após rollback..."
    schtasks /Run /TN $TaskName 2>&1 | Out-Null

    # 10.4 Health check do rollback
    Write-DeployLog "Avaliando saúde do serviço pós-rollback em $HealthUrl (timeout 75s)..."
    $RollbackHealthPassed = Test-HealthEndpoint -Url $HealthUrl -TimeoutSeconds 75 -IntervalSeconds 3

    if ($RollbackHealthPassed) {
        Write-DeployLog "ROLLBACK_SUCCESS: Produção restaurada e saudável em DETACHED HEAD no CURRENT_SHA ($CurrentSha). Branch main preservada." -Level "SUCCESS"
        Format-Summary -CurrentSha $CurrentSha -TargetSha $TargetSha -BackupResult $BackupSummary -UpdateResult "PASS (REVERTED)" -HealthResult "FAIL" -RollbackResult "ROLLBACK_SUCCESS (DETACHED HEAD em $CurrentSha)" -FinalSha $RollbackHead -Status "ROLLBACK_SUCCESS" -FailureReason "Health check inicial falhou; rollback executado com sucesso."
        exit 0
    } else {
        Write-DeployLog "ROLLBACK_FAILED: Aplicação permaneceu instável após rollback. Intervenção humana necessária!" -Level "ERROR" -IsError
        Format-Summary -CurrentSha $CurrentSha -TargetSha $TargetSha -BackupResult $BackupSummary -UpdateResult "PASS (REVERTED)" -HealthResult "FAIL" -RollbackResult "ROLLBACK_FAILED" -FinalSha $RollbackHead -Status "ROLLBACK_FAILED" -FailureReason "Health check falhou após update E após tentativa de rollback. Intervenção humana urgente necessária."
        exit 1
    }

} catch {
    $ExMsg = $_.Exception.Message
    Write-DeployLog "Falha na execução do pipeline de atualização: $ExMsg" -Level "ERROR" -IsError
    $DispCurrent = if ($CurrentSha) { $CurrentSha } else { "UNKNOWN" }
    $DispTarget = if ($TargetSha) { $TargetSha } else { "UNKNOWN" }
    $DispBackup = if ($BackupSummary) { $BackupSummary } else { "NOT_ATTEMPTED" }
    Format-Summary -CurrentSha $DispCurrent -TargetSha $DispTarget -BackupResult $DispBackup -UpdateResult "FAIL" -HealthResult "NOT_ATTEMPTED" -RollbackResult "NOT_REQUIRED" -FinalSha $DispCurrent -Status "DEPLOY_FAILED" -FailureReason $ExMsg
    exit 1
} finally {
    if ($AcquiredLock -and (Test-Path $LockFile)) {
        Remove-Item $LockFile -Force -ErrorAction SilentlyContinue
    }
}
