<#
.SYNOPSIS
    Script de Inicialização para Web UI V2 e API V2 (Fase R8).
.DESCRIPTION
    Inicia o servidor FastAPI/Uvicorn que hospeda a Web UI V2 (React/Vite SPA compilado)
    e a API V2 operacional da Video Factory na mesma origem (Same-Origin).
    
    PRINCÍPIOS DE PRODUÇÃO & CONVIVÊNCIA:
    - Roda em porta dedicada (default: 8080) sem interferir no Streamlit (8501)
    - Serve os assets estáticos de 'webui-v2/dist/' diretamente pelo FastAPI
    - Fallback de roteamento SPA transparente para rotas do cliente
    - Respeita o estado canônico do nó (PRIMARY / SECONDARY_VIEW_ONLY)
    - Conecta-se às autoridades canônicas existentes (operator_console, scheduler)
    - Zero duplicação de Worker, Scheduler ou bancos de dados SQLite
#>

[CmdletBinding()]
param(
    [string]$HostAddress = "0.0.0.0",
    [int]$Port = 8080,
    [switch]$BuildIfMissing = $true
)

$ErrorActionPreference = "Stop"

# 1. Resolução Determinística do Diretório Raiz
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Configuração de Logging Operacional
$LogDir = Join-Path $ProjectRoot "storage\logs\webui_v2"
if (-not (Test-Path $LogDir)) {
    New-Item -ItemType Directory -Path $LogDir -Force | Out-Null
}
$StartupLog = Join-Path $LogDir "webui_v2_startup.log"

function Write-WebUiLog {
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
        Add-Content -Path $StartupLog -Value $LogLine -Encoding UTF8
    } catch {}
}

Write-WebUiLog "======================================================"
Write-WebUiLog " Video Factory - Web UI V2 Server Launcher (Fase R8)"
Write-WebUiLog "======================================================"
Write-WebUiLog "Diretório do Projeto : $ProjectRoot"

# 3. Localização do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    $ErrMsg = "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'."
    Write-WebUiLog $ErrMsg -Level "ERROR" -IsError
    exit 1
}

# 4. Verificação dos Arquivos Estáticos (webui-v2/dist)
$WebUiDist = Join-Path $ProjectRoot "webui-v2\dist"
$DistIndex = Join-Path $WebUiDist "index.html"

if (-not (Test-Path $DistIndex)) {
    Write-WebUiLog "AVISO: Build da Web UI V2 não encontrado em '$DistIndex'." -Level "WARN"
    if ($BuildIfMissing) {
        Write-WebUiLog "Executando build reproduzível do frontend (npm run build)..."
        $WebUiDir = Join-Path $ProjectRoot "webui-v2"
        Push-Location $WebUiDir
        try {
            npm run build
            if ($LASTEXITCODE -ne 0 -or -not (Test-Path $DistIndex)) {
                Write-WebUiLog "ERRO: Falha ao compilar frontend. O backend servirá fallback." -Level "ERROR" -IsError
            } else {
                Write-WebUiLog "Frontend compilado com sucesso." -Level "SUCCESS"
            }
        } catch {
            Write-WebUiLog "Exceção ao rodar npm build: $_" -Level "WARN"
        } finally {
            Pop-Location
        }
    }
} else {
    Write-WebUiLog "Build de produção verificado em '$DistIndex'." -Level "SUCCESS"
}

# 5. Configuração de Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-WebUiLog "Runtime Python        : $VenvPython"
Write-WebUiLog "Host de Escuta        : $HostAddress"
Write-WebUiLog "Porta de Serviço      : $Port"
Write-WebUiLog "URL Local             : http://localhost:$Port"
Write-WebUiLog "URL Remota na Rede    : http://<IP_DO_HOST>:$Port"
Write-WebUiLog "Streamlit Fallback    : http://<IP_DO_HOST>:8501 (preservado ativo)"

# 6. Inicialização do Servidor Uvicorn
Write-WebUiLog "Iniciando servidor FastAPI / Uvicorn..."
$UvicornArgs = @(
    "-m", "uvicorn",
    "app.asgi:app",
    "--host", $HostAddress,
    "--port", [string]$Port,
    "--log-level", "warning"
)

& $VenvPython $UvicornArgs
$ExitCode = $LASTEXITCODE

Write-WebUiLog "Servidor Web UI V2 finalizado com código $ExitCode."
exit $ExitCode
