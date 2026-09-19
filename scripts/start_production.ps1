<#
.SYNOPSIS
    Script de Inicialização para Servidor de Produção (Fase V12-A).
.DESCRIPTION
    Inicia o MoneyPrinterTurbo como PRIMARY FACTORY em modo servidor contínuo.
    - Resolve o diretório raiz do projeto de forma determinística
    - Utiliza estritamente o Python do ambiente virtual (.venv)
    - Executa Streamlit com bind em 0.0.0.0 na porta 8501
    - Modo headless ativo (não abre navegador localmente no host)
    - Não modifica firewall, registro nem instala dependências
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8501
)

$ErrorActionPreference = "Stop"

# 1. Resolução do Diretório Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Configuração de Logging Operacional Persistente (V12-C)
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
Write-OperationalLog " MoneyPrinterTurbo - Servidor de Produção (V12-C)"
Write-OperationalLog "======================================================"
Write-OperationalLog "Diretório do Projeto : $ProjectRoot"

# 3. Localização e Validação do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    $ErrMsg = "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'. Execute 'uv sync' ou crie o .venv antes de iniciar em produção."
    Write-OperationalLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 4. Validação do Entrypoint da Aplicação
$Entrypoint = Join-Path $ProjectRoot "webui\Main.py"
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
Write-OperationalLog "Modo Headless         : Ativo (navegador local não será aberto)"

# 6. Execução do Streamlit em Modo Servidor
$StreamlitArgs = @(
    "-m", "streamlit", "run", $Entrypoint,
    "--server.address=$HostAddress",
    "--server.port=$Port",
    "--server.headless=true",
    "--browser.gatherUsageStats=false",
    "--client.toolbarMode=minimal",
    "--logger.hideWelcomeMessage=true",
    "--server.showEmailPrompt=false",
    "--server.enableCORS=true"
)

Write-OperationalLog "Iniciando processo Streamlit..."
& $VenvPython $StreamlitArgs
$ExitCode = $LASTEXITCODE

Write-OperationalLog "Processo do servidor encerrado com código de saída $ExitCode."
exit $ExitCode
