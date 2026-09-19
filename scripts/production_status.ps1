<#
.SYNOPSIS
    Script de Diagnóstico e Status Operacional de Produção (Fase V12-C).
.DESCRIPTION
    Exibe um snapshot sanitizado e abrangente da saúde do servidor de produção:
    - Estado global de saúde (HEALTHY / DEGRADED / UNHEALTHY)
    - Prontidão técnica (READY / NOT_READY)
    - Papel de instância (PRIMARY / SECONDARY_VIEW_ONLY)
    - Estado do scheduler, workers e storage local
    - Status de backups e integridade do SQLite
    - Presença passiva de credenciais (sem expor segredos)
#>

[CmdletBinding()]
param(
    [switch]$Json = $false,
    [switch]$HealthOnly = $false,
    [switch]$ReadinessOnly = $false
)

$ErrorActionPreference = "Stop"

# 1. Resolução do Diretório Raiz do Projeto
$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = (Resolve-Path (Join-Path $ScriptDir "..")).Path

# 2. Localização e Validação do Ambiente Virtual (.venv)
$VenvPython = Join-Path $ProjectRoot ".venv\Scripts\python.exe"

if (-not (Test-Path $VenvPython)) {
    Write-Error "ERRO CRÍTICO: Ambiente virtual (.venv) não encontrado em '$VenvPython'."
    exit 1
}

# 3. Configuração do Working Directory e Ambiente
Set-Location -Path $ProjectRoot
$env:PYTHONPATH = $ProjectRoot

# 4. Montagem dos Argumentos
$StatusArgs = @(
    "-m", "app.services.production_health"
)

if ($Json) {
    $StatusArgs += "--json"
}
if ($HealthOnly) {
    $StatusArgs += "--health"
}
if ($ReadinessOnly) {
    $StatusArgs += "--readiness"
}

# 5. Execução do Diagnóstico
& $VenvPython $StatusArgs
exit $LASTEXITCODE
