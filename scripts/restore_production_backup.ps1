<#
.SYNOPSIS
    Script de Restauração Segura de Backup do SQLite (Fase V12-C).
.DESCRIPTION
    Restaura um snapshot de backup oficial sobre o banco de dados de produção.

    REGRA DE SEGURANÇA OBRIGATÓRIA:
    O servidor de produção e a fábrica DEVEM estar completamente parados antes da restauração.
    Este script NÃO finaliza processos automaticamente por segurança; o operador deve
    parar o serviço/tarefa manualmente.
#>

[CmdletBinding()]
param(
    [Parameter(Position=0)]
    [string]$BackupFile = ""
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

# 4. Se nenhum arquivo foi passado, lista os backups existentes e orienta o operador
if ($BackupFile -eq "") {
    Write-Host "======================================================" -ForegroundColor Cyan
    Write-Host " Backups Disponíveis para Restauração (storage/backups/database)" -ForegroundColor Cyan
    Write-Host "======================================================" -ForegroundColor Cyan

    $ListPy = @"
import json
from app.services import production_backup
backups = production_backup.list_database_backups()
if not backups:
    print('Nenhum backup encontrado.')
else:
    for i, b in enumerate(backups[:10]):
        size_kb = b['size_bytes'] / 1024
        print(f"[{i+1}] {b['filename']} ({size_kb:.1f} KB) - Criado em: {b.get('created_at', 'Desconhecido')}")
"@
    & $VenvPython -c $ListPy

    Write-Host ""
    Write-Host "Uso: .\scripts\restore_production_backup.ps1 -BackupFile <caminho_do_arquivo.db>" -ForegroundColor Yellow
    exit 0
}

# 5. Validação de Arquivo
if (-not (Test-Path $BackupFile)) {
    Write-Error "ERRO: Arquivo de backup não encontrado em '$BackupFile'."
    exit 1
}

# 6. Verificação de Backend Ativo (Porta 8501)
$PortOpen = $false
try {
    $TcpClient = New-Object System.Net.Sockets.TcpClient
    $ConnectTask = $TcpClient.ConnectAsync("127.0.0.1", 8501)
    if ($ConnectTask.Wait(800) -and $TcpClient.Connected) {
        $PortOpen = $true
        $TcpClient.Close()
    }
} catch {
    # Conexão recusada = porta fechada = seguro
}

if ($PortOpen) {
    Write-Error "RESTAURAÇÃO BLOQUEADA: A porta 8501 está ativa. O backend do MoneyPrinterTurbo está em execução.`nPor segurança, encerre a tarefa/serviço no Windows Task Scheduler antes de restaurar o banco."
    exit 1
}

# 7. Confirmação Obrigatória do Operador
Write-Host "ATENÇÃO: Você está prestes a restaurar o banco de dados de produção." -ForegroundColor Yellow
Write-Host "Arquivo de Origem: $BackupFile" -ForegroundColor Cyan
Write-Host "Uma safety copy do banco atual será criada automaticamente antes da substituição."
$Confirmation = Read-Host "Deseja continuar com a restauração? (digite 'SIM' para confirmar)"
if ($Confirmation -ne "SIM") {
    Write-Host "Operação de restauração cancelada pelo operador." -ForegroundColor Yellow
    exit 0
}

# 8. Execução da Restauração Segura
$RestoreArgs = @(
    "-m", "app.services.production_recovery",
    $BackupFile
)

Write-Host "Executando restauração controlada..." -ForegroundColor Cyan
& $VenvPython $RestoreArgs
$ExitCode = $LASTEXITCODE

if ($ExitCode -eq 0) {
    Write-Host "Banco de dados restaurado com sucesso. Você pode reiniciar o servidor agora." -ForegroundColor Green
    exit 0
} else {
    Write-Error "Falha na restauração do banco de produção (código de saída: $ExitCode)."
    exit $ExitCode
}
