<#
.SYNOPSIS
    Script de Execução de Backup do Banco SQLite de Produção (Fase V12-C).
.DESCRIPTION
    Executa backup transacional e seguro do banco SQLite enquanto o servidor está ativo (WAL).
    - Resolve o diretório raiz do projeto de forma determinística
    - Utiliza estritamente o Python do ambiente virtual (.venv)
    - Gera snapshot íntegro, valida integridade, gera manifesto SHA-256 e aplica retenção
    - Não interrompe a fábrica, não requer parada do serviço
    - Não expõe segredos nem altera credenciais
    - Retorna exit code 0 em sucesso e exit 1 em caso de erro
#>

[CmdletBinding()]
param(
    [string]$BackupDir = "",
    [int]$Retention = 24
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
$BackupArgs = @(
    "-m", "app.services.production_backup",
    "--retention", $Retention
)

if ($BackupDir -ne "") {
    $BackupArgs += @("--backup-dir", $BackupDir)
}

# 5. Execução do Backup
Write-Host "Iniciando backup de banco de dados SQLite..." -ForegroundColor Cyan

& $VenvPython $BackupArgs
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "Backup concluído com sucesso." -ForegroundColor Green
    exit 0
} else {
    Write-Error "Falha na execução do backup de produção (código de saída: $ExitCode)."
    exit $ExitCode
}
