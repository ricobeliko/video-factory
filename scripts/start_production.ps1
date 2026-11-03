<#
.SYNOPSIS
    Script de Inicializacao para Servidor de Producao (Fase V2 / Cutover).
.DESCRIPTION
    Inicia o MoneyPrinterTurbo como PRIMARY FACTORY em modo servidor continuo.
    - Padrao (V2): Executa o Motor Unificado V2 (FastAPI + webui-v2/dist) sob supervisor resiliente.
    - Modo Legado (-Legacy): Executa o Streamlit V1 na porta 8501 para rollback controlado (sem supervisor).
    - Resolve o diretorio raiz do projeto de forma deterministica
    - Utiliza estritamente o Python do ambiente virtual (.venv)
    - Modo headless ativo (nao abre navegador localmente no host)
    - Nao modifica firewall, registro nem instala dependencias
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 0,
    [switch]$Legacy = $false,
    [switch]$NoWorker = $false,
    [int]$LockWaitSeconds = 120,
    [int]$SupervisorRestartDelaySeconds = 15,
    [int]$SupervisorMaxRestarts = 5,
    [int]$SupervisorWindowMinutes = 10,
    [string]$SupervisorLogFile = "",
    [string]$CustomExecutable = "",
    [string[]]$CustomExecutableArgs = @()
)

$ErrorActionPreference = "Stop"

# 1. Resolucao do Diretorio Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Definicao da Porta e Entrypoint conforme o Modo (V2 Padrao vs V1 Legado)
if ($Legacy) {
    if ($Port -eq 0) { $Port = 8501 }
    $EntrypointRel = "scripts\production_entrypoint.py"
    $ModeDescription = "V1 Legado (Streamlit, porta $Port)"
} else {
    if ($Port -eq 0) { $Port = 8080 }
    $EntrypointRel = "scripts\engine_entrypoint.py"
    $ModeDescription = "V2 Unificado (FastAPI + React SPA, porta $Port)"
}

# 3. Configuracao de Logging Operacional Persistente
$LogDir = Join-Path $ProjectRoot "storage\logs\production"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StartupLog = Join-Path $LogDir "production_startup.log"
$ErrorLog = Join-Path $LogDir "production_error.log"

$SupervisorLogPath = if ($SupervisorLogFile) {
    if ([System.IO.Path]::IsPathRooted($SupervisorLogFile)) { $SupervisorLogFile } else { Join-Path $ProjectRoot $SupervisorLogFile }
} else {
    Join-Path $ProjectRoot "storage\logs\supervisor.log"
}
$SupervisorLogDir = Split-Path -Parent $SupervisorLogPath
if (-not (Test-Path $SupervisorLogDir)) {
    New-Item -ItemType Directory -Path $SupervisorLogDir -Force | Out-Null
}

function Write-OperationalLog {
    param(
        [string]$Message,
        [string]$Level = "INFO",
        [switch]$IsError = $false
    )
    $Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $LogLine = "[$Timestamp][$Level][PID $PID] $Message"

    if ($IsError) {
        Write-Host $LogLine -ForegroundColor Red
    } else {
        Write-Host $LogLine -ForegroundColor Cyan
    }

    try {
        $TargetLog = if ($IsError) { $ErrorLog } else { $StartupLog }
        if (Test-Path $TargetLog) {
            $Item = Get-Item $TargetLog
            if ($Item.Length -gt 5MB) {
                $OldLog = "$TargetLog.old"
                if (Test-Path $OldLog) { Remove-Item $OldLog -Force }
                Move-Item $TargetLog $OldLog -Force
            }
        }
        Add-Content -Path $TargetLog -Value $LogLine -Encoding UTF8
    } catch {
        # Evita travar launcher se gravacao de log em disco falhar
    }
}

function Write-SupervisorLog {
    param(
        [string]$Message,
        [string]$Level = "INFO",
        [int]$Code = 0,
        [int]$RestartsCount = 0
    )
    $Timestamp = (Get-Date).ToUniversalTime().ToString("yyyy-MM-ddTHH:mm:ssZ")
    $LogLine = "[$Timestamp][$Level][PID $PID][ExitCode $Code][Restarts $RestartsCount] $Message"

    if ($Level -eq "ERROR") {
        Write-Host $LogLine -ForegroundColor Red
    } elseif ($Level -eq "WARN") {
        Write-Host $LogLine -ForegroundColor Yellow
    } else {
        Write-Host $LogLine -ForegroundColor Green
    }

    try {
        Add-Content -Path $SupervisorLogPath -Value $LogLine -Encoding UTF8
    } catch {
        # Evita travar launcher se gravacao de log em disco falhar
    }
}

Write-OperationalLog "======================================================"
Write-OperationalLog " MoneyPrinterTurbo - Servidor de Producao ($ModeDescription)"
Write-OperationalLog "======================================================"
Write-OperationalLog "Diretorio do Projeto : $ProjectRoot"

# 4. Localizacao e Validacao do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not $CustomExecutable -and -not (Test-Path $VenvPython)) {
    $ErrMsg = "ERRO CRITICO: Ambiente virtual (.venv) nao encontrado em '$VenvPython'. Execute 'uv sync' ou crie o .venv antes de iniciar em producao."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 5. Validacao do Entrypoint da Aplicacao
$Entrypoint = Join-Path $ProjectRoot $EntrypointRel
if (-not $CustomExecutable -and -not (Test-Path $Entrypoint)) {
    $ErrMsg = "ERRO CRITICO: Entrypoint '$Entrypoint' nao encontrado."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 6. Validacao do Bundle Frontend para Modo V2
if (-not $Legacy -and -not $CustomExecutable) {
    $DistDir = Join-Path $ProjectRoot "webui-v2\dist"
    $IndexHtml = Join-Path $DistDir "index.html"
    if (-not (Test-Path $IndexHtml)) {
        $ErrMsg = "ERRO CRITICO: Assets compilados da V2 nao encontrados em '$DistDir'. Execute 'npm run build' ou sincronize webui-v2/dist antes de iniciar."
        Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
        exit 1
    }
}

# 7. Configuracao do Working Directory e Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-OperationalLog "Python Runtime        : $(if ($CustomExecutable) { $CustomExecutable } else { $VenvPython })"
Write-OperationalLog "Entrypoint            : $Entrypoint"
Write-OperationalLog "Endereco de Escuta    : $HostAddress"
Write-OperationalLog "Porta de Servico      : $Port"
Write-OperationalLog "Modo Operacional      : $ModeDescription"
Write-OperationalLog "Modo Headless         : Ativo"

# 8. Montagem de Argumentos e Execucao
if ($Legacy) {
    # Modo V1 Legado: production_entrypoint.py com flags Streamlit (sem supervisor)
    $EntrypointArgs = @(
        $Entrypoint,
        "--server.address=$HostAddress",
        "--server.port=$Port",
        "--server.headless=true",
        "--browser.gatherUsageStats=false",
        "--client.toolbarMode=minimal",
        "--logger.hideWelcomeMessage=true",
        "--server.showEmailPrompt=false",
        "--server.enableCORS=true"
    )

    Write-OperationalLog "Iniciando processo de producao V1 Legado ($Entrypoint)..."
    & $VenvPython $EntrypointArgs
    $ExitCode = $LASTEXITCODE

    Write-OperationalLog "Processo do servidor legado encerrado com codigo de saida $ExitCode."
    exit $ExitCode
} else {
    # Modo V2 Padrao: engine_entrypoint.py (Motor FastAPI + Uvicorn) sob Supervisor Resiliente
    $EntrypointArgs = @(
        $Entrypoint,
        "--host", $HostAddress,
        "--port", [string]$Port,
        "--lock-wait-seconds", [string]$LockWaitSeconds
    )
    if ($NoWorker) {
        $EntrypointArgs += "--no-worker"
    }

    $ExeToRun = if ($CustomExecutable) { $CustomExecutable } else { $VenvPython }
    $ArgsToRun = if ($CustomExecutable) { $CustomExecutableArgs } else { $EntrypointArgs }

    $RestartTimestamps = [System.Collections.Generic.List[datetime]]::new()
    $TotalRestarts = 0

    Write-OperationalLog "Iniciando supervisor do Motor V2 (Delay=${SupervisorRestartDelaySeconds}s, MaxRestarts=${SupervisorMaxRestarts} em ${SupervisorWindowMinutes}m)..."
    Write-SupervisorLog -Message "Supervisor iniciado para motor V2 ($ExeToRun)" -Level "INFO" -Code 0 -RestartsCount 0

    while ($true) {
        Write-OperationalLog "Iniciando processo do motor V2 ($ExeToRun)..."
        Write-SupervisorLog -Message "Iniciando processo do motor V2" -Level "INFO" -Code 0 -RestartsCount $TotalRestarts

        & $ExeToRun $ArgsToRun
        $ExitCode = $LASTEXITCODE

        Write-OperationalLog "Processo do motor V2 encerrado com codigo de saida $ExitCode."

        if ($ExitCode -eq 0) {
            Write-OperationalLog "Motor V2 encerrou com codigo 0 (saida limpa / parada deliberada). Encerrando supervisor."
            Write-SupervisorLog -Message "Motor V2 encerrou com codigo 0 (saida limpa / parada deliberada). Supervisor finalizado." -Level "INFO" -Code 0 -RestartsCount $TotalRestarts
            exit 0
        }

        $Now = [datetime]::UtcNow
        $TotalRestarts++
        $RestartTimestamps.Add($Now)

        # Janela deslizante de reinicios
        $WindowStart = $Now.AddMinutes(-$SupervisorWindowMinutes)
        $ActiveRestarts = [System.Collections.Generic.List[datetime]]::new()
        foreach ($ts in $RestartTimestamps) {
            if ($ts -ge $WindowStart) {
                $ActiveRestarts.Add($ts)
            }
        }
        $RestartTimestamps = $ActiveRestarts

        Write-OperationalLog "Motor V2 encerrou inesperadamente com codigo $ExitCode. Falhas na janela (${SupervisorWindowMinutes}m): $($RestartTimestamps.Count)/$SupervisorMaxRestarts (Total: $TotalRestarts)." -Level "WARN"
        Write-SupervisorLog -Message "Motor V2 encerrou inesperadamente com codigo $ExitCode. Falhas na janela (${SupervisorWindowMinutes}m): $($RestartTimestamps.Count)/$SupervisorMaxRestarts (Total: $TotalRestarts)." -Level "WARN" -Code $ExitCode -RestartsCount $TotalRestarts

        if ($RestartTimestamps.Count -gt $SupervisorMaxRestarts) {
            $ErrMsg = "ERRO CRITICO: Limite de relancamentos do supervisor excedido ($($RestartTimestamps.Count) falhas na janela de ${SupervisorWindowMinutes} minutos). Encerrando supervisor com codigo $ExitCode para evitar laco infinito."
            Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
            Write-SupervisorLog -Message $ErrMsg -Level "ERROR" -Code $ExitCode -RestartsCount $TotalRestarts
            exit $ExitCode
        }

        Write-OperationalLog "Aguardando ${SupervisorRestartDelaySeconds}s antes de relancar o motor V2..."
        Write-SupervisorLog -Message "Aguardando ${SupervisorRestartDelaySeconds}s antes de relancar o motor V2..." -Level "INFO" -Code $ExitCode -RestartsCount $TotalRestarts
        Start-Sleep -Seconds $SupervisorRestartDelaySeconds
    }
}
