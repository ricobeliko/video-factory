<#
.SYNOPSIS
    Script de Inicialização para o Motor Unificado V2 (Fase V2 / Missão D).
.DESCRIPTION
    Inicia o MoneyPrinterTurbo como PRIMARY ENGINE em modo servidor contínuo sem Streamlit.
    - Serve a API V2 e os assets compilados da Web UI V2 (webui-v2/dist) via FastAPI/Uvicorn
    - Inicializa o SchedulerExecutionWorker e o Watchdog no mesmo processo
    - Protege contra concorrência de portas e múltiplas instâncias
    - Respeita rigorosamente o Single PRIMARY Guard
    - Não modifica firewall nem registra tarefa agendada do Windows
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8080,
    [switch]$NoWorker,
    [switch]$KillExisting,
    [int]$LockWaitSeconds = 120
)

$ErrorActionPreference = "Stop"

# 1. Resolução do Diretório Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Configuração de Logging Operacional Persistente
$LogDir = Join-Path $ProjectRoot "storage\logs\engine"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StartupLog = Join-Path $LogDir "engine_startup.log"
$ErrorLog = Join-Path $LogDir "engine_error.log"

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
    } elseif ($Level -eq "WARN") {
        Write-Host $LogLine -ForegroundColor Yellow
    } elseif ($Level -eq "SUCCESS") {
        Write-Host $LogLine -ForegroundColor Green
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
    } catch {}
}

Write-OperationalLog "======================================================"
Write-OperationalLog " MoneyPrinterTurbo - Motor Unificado V2 (Sem Streamlit)"
Write-OperationalLog "======================================================"
Write-OperationalLog "Diretório do Projeto : $ProjectRoot"

# 3. Localização e Validação do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $ErrMsg = "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'. Execute 'uv sync' ou crie o .venv antes de iniciar."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 4. Validação do Entrypoint da Aplicação
$Entrypoint = Join-Path $ProjectRoot "scripts\engine_entrypoint.py"
if (-not (Test-Path $Entrypoint)) {
    $ErrMsg = "ERRO CRÍTICO: Entrypoint '$Entrypoint' não encontrado."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 5. Configuração do Working Directory e Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-OperationalLog "Python Runtime        : $VenvPython"
Write-OperationalLog "Entrypoint            : $Entrypoint"
Write-OperationalLog "Endereço de Escuta    : $HostAddress"
Write-OperationalLog "Porta de Serviço      : $Port"
Write-OperationalLog "Espera de Lock        : $LockWaitSeconds segundos"
Write-OperationalLog "Modo NoWorker         : $(if ($NoWorker) { 'ATIVO (Worker e Watchdog desligados)' } else { 'INATIVO (Worker e Watchdog ativos)' })"
Write-OperationalLog "Bootstrap Motor V2    : PRIMARY + SchedulerExecutionWorker + Watchdog no mesmo processo"

# 6. Verificação de Porta e Proteção Contra Processos Conflitantes
$PortInUse = $false
try {
    $TcpClient = New-Object System.Net.Sockets.TcpClient
    $ConnectTask = $TcpClient.ConnectAsync("127.0.0.1", $Port)
    if ($ConnectTask.Wait(800) -and $TcpClient.Connected) {
        $PortInUse = $true
        $TcpClient.Close()
    }
} catch {}

if ($PortInUse) {
    if ($KillExisting) {
        Write-OperationalLog "Porta $Port ocupada. Encerrando processo anterior (-KillExisting)..." -Level "WARN"
        try {
            $ExistingConns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
            if ($ExistingConns) {
                foreach ($Conn in $ExistingConns) {
                    if ($Conn.OwningProcess -and $Conn.OwningProcess -ne $PID) {
                        Stop-Process -Id $Conn.OwningProcess -Force -ErrorAction SilentlyContinue
                    }
                }
                Start-Sleep -Seconds 1
            }
        } catch {
            Write-OperationalLog "Aviso ao tentar encerrar processo na porta ${Port}: $_" -Level "WARN"
        }
    } else {
        $ErrMsg = "CONFLITO: A porta $Port já está em uso por outro processo. Encerre o processo conflitante ou utilize -KillExisting."
        Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
        exit 1
    }
}

# 7. Gravação de Arquivo PID
$PidFile = Join-Path $LogDir "engine.pid"
try {
    Set-Content -Path $PidFile -Value $PID -Encoding ASCII -Force
} catch {}

# 8. Execução do Entrypoint do Motor V2
$EntrypointArgs = @(
    $Entrypoint,
    "--host", $HostAddress,
    "--port", [string]$Port,
    "--lock-wait-seconds", [string]$LockWaitSeconds
)
if ($NoWorker) {
    $EntrypointArgs += "--no-worker"
}

Write-OperationalLog "Iniciando processo do Motor V2 (FastAPI + Worker no mesmo processo)..."
try {
    & $VenvPython $EntrypointArgs
    $ExitCode = $LASTEXITCODE
} finally {
    try {
        if (Test-Path $PidFile) {
            Remove-Item -Path $PidFile -Force -ErrorAction SilentlyContinue
        }
    } catch {}
}

Write-OperationalLog "Processo do motor encerrado com código de saída $ExitCode."
exit $ExitCode
