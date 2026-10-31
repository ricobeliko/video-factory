<#
.SYNOPSIS
    Script de Inicialização para Servidor de Produção (Fase V2 / Cutover).
.DESCRIPTION
    Inicia o MoneyPrinterTurbo como PRIMARY FACTORY em modo servidor contínuo.
    - Padrão (V2): Executa o Motor Unificado V2 (FastAPI + webui-v2/dist) na porta 8080.
    - Modo Legado (-Legacy): Executa o Streamlit V1 na porta 8501 para rollback controlado.
    - Resolve o diretório raiz do projeto de forma determinística
    - Utiliza estritamente o Python do ambiente virtual (.venv)
    - Modo headless ativo (não abre navegador localmente no host)
    - Não modifica firewall, registro nem instala dependências
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 0,
    [switch]$Legacy = $false,
    [switch]$NoWorker = $false,
    [int]$LockWaitSeconds = 120
)

$ErrorActionPreference = "Stop"

# 1. Resolução do Diretório Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Definição da Porta e Entrypoint conforme o Modo (V2 Padrão vs V1 Legado)
if ($Legacy) {
    if ($Port -eq 0) { $Port = 8501 }
    $EntrypointRel = "scripts\production_entrypoint.py"
    $ModeDescription = "V1 Legado (Streamlit, porta $Port)"
} else {
    if ($Port -eq 0) { $Port = 8080 }
    $EntrypointRel = "scripts\engine_entrypoint.py"
    $ModeDescription = "V2 Unificado (FastAPI + React SPA, porta $Port)"
}

# 3. Configuração de Logging Operacional Persistente
$LogDir = Join-Path $ProjectRoot "storage\logs\production"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StartupLog = Join-Path $LogDir "production_startup.log"
$ErrorLog = Join-Path $LogDir "production_error.log"

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
        # Evita travar launcher se gravação de log em disco falhar
    }
}

Write-OperationalLog "======================================================"
Write-OperationalLog " MoneyPrinterTurbo - Servidor de Produção ($ModeDescription)"
Write-OperationalLog "======================================================"
Write-OperationalLog "Diretório do Projeto : $ProjectRoot"

# 4. Localização e Validação do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $ErrMsg = "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'. Execute 'uv sync' ou crie o .venv antes de iniciar em produção."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 5. Validação do Entrypoint da Aplicação
$Entrypoint = Join-Path $ProjectRoot $EntrypointRel
if (-not (Test-Path $Entrypoint)) {
    $ErrMsg = "ERRO CRÍTICO: Entrypoint '$Entrypoint' não encontrado."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 6. Validação do Bundle Frontend para Modo V2
if (-not $Legacy) {
    $DistDir = Join-Path $ProjectRoot "webui-v2\dist"
    $IndexHtml = Join-Path $DistDir "index.html"
    if (-not (Test-Path $IndexHtml)) {
        $ErrMsg = "ERRO CRÍTICO: Assets compilados da V2 não encontrados em '$DistDir'. Execute 'npm run build' ou sincronize webui-v2/dist antes de iniciar."
        Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
        exit 1
    }
}

# 7. Configuração do Working Directory e Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-OperationalLog "Python Runtime        : $VenvPython"
Write-OperationalLog "Entrypoint            : $Entrypoint"
Write-OperationalLog "Endereço de Escuta    : $HostAddress"
Write-OperationalLog "Porta de Serviço      : $Port"
Write-OperationalLog "Modo Operacional      : $ModeDescription"
Write-OperationalLog "Modo Headless         : Ativo"

# 8. Montagem de Argumentos e Execução
if ($Legacy) {
    # Modo V1 Legado: production_entrypoint.py com flags Streamlit
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
} else {
    # Modo V2 Padrão: engine_entrypoint.py (Motor FastAPI + Uvicorn)
    $EntrypointArgs = @(
        $Entrypoint,
        "--host", $HostAddress,
        "--port", [string]$Port,
        "--lock-wait-seconds", [string]$LockWaitSeconds
    )
    if ($NoWorker) {
        $EntrypointArgs += "--no-worker"
    }
}

Write-OperationalLog "Iniciando processo de produção ($Entrypoint)..."
& $VenvPython $EntrypointArgs
$ExitCode = $LASTEXITCODE

Write-OperationalLog "Processo do servidor encerrado com código de saída $ExitCode."
exit $ExitCode
