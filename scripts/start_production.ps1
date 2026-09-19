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

Write-Host "======================================================" -ForegroundColor Cyan
Write-Host " MoneyPrinterTurbo - Servidor de Produção (V12-A)" -ForegroundColor Cyan
Write-Host "======================================================" -ForegroundColor Cyan
Write-Host "Diretório do Projeto : $ProjectRoot"

# 2. Localização e Validação do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'. Execute 'uv sync' ou crie o .venv antes de iniciar em produção."
    exit 1
}

# 3. Validação do Entrypoint da Aplicação
$Entrypoint = Join-Path $ProjectRoot "webui\Main.py"
if (-not (Test-Path $Entrypoint)) {
    Write-Error "ERRO CRÍTICO: Entrypoint '$Entrypoint' não encontrado."
    exit 1
}

# 4. Configuração do Working Directory e Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

Write-Host "Python Runtime        : $VenvPython" -ForegroundColor Green
Write-Host "Entrypoint            : $Entrypoint" -ForegroundColor Green
Write-Host "Endereço de Escuta    : $HostAddress" -ForegroundColor Green
Write-Host "Porta de Serviço      : $Port" -ForegroundColor Green
Write-Host "Modo Headless         : Ativo (navegador local não será aberto)" -ForegroundColor Yellow
Write-Host "------------------------------------------------------"

# 5. Execução do Streamlit em Modo Servidor
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

Write-Host "Iniciando processo Streamlit..." -ForegroundColor Cyan
& $VenvPython $StreamlitArgs
