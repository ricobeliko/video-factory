<#
.SYNOPSIS
    Registra e gerencia a Scheduled Task 'VideoFactory WebUI V2' no Windows.
.DESCRIPTION
    Configura a inicialização automática e persistente da Web UI V2 no boot do Windows,
    sem exigir login do operador e sem manter janelas interativas do PowerShell abertas.
    
    PRESERVAÇÃO OBRIGATÓRIA DA PRODUÇÃO:
    - Não modifica nem reinicia a tarefa 'VideoFactory Production' (Streamlit na porta 8501)
    - Executa em porta dedicada (8080)
    - Opera em modo SECONDARY_VIEW_ONLY sem disputar o lock PRIMARY
    - Bloqueia instâncias concorrentes (MultipleInstances = IgnoreNew)
    - Política de recuperação automática (RestartCount = 3, RestartInterval = 1 min)
#>

[CmdletBinding()]
param(
    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo",
    [string]$TaskName = "VideoFactory WebUI V2",
    [string]$PrimaryTaskName = "VideoFactory Production",
    [int]$Port = 8080,
    [string]$TaskUser = "NT AUTHORITY\SYSTEM",
    [switch]$StartTask = $true,
    [switch]$Unregister,
    [switch]$StatusOnly
)

$ErrorActionPreference = "Stop"

function Write-Step {
    param([string]$Message, [string]$Level = "INFO")
    $Colors = @{ "INFO" = "Cyan"; "SUCCESS" = "Green"; "WARN" = "Yellow"; "ERROR" = "Red" }
    Write-Host "[$Level] $Message" -ForegroundColor $Colors[$Level]
}

# 1. Resolução do Diretório Raiz
if (-not (Test-Path $RepoPath)) {
    # Tenta resolver relativo ao script se C:\Projetos\MoneyPrinterTurbo não existir localmente
    $ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
    $LocalCandidate = (Resolve-Path (Join-Path $ScriptDir "..")).Path
    if (Test-Path (Join-Path $LocalCandidate "scripts\start_webui_v2.ps1")) {
        $RepoPath = $LocalCandidate
    } else {
        Write-Step "Diretório do repositório '$RepoPath' não encontrado." "ERROR"
        exit 1
    }
}
$RepoPath = (Resolve-Path $RepoPath).Path

Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host " Video Factory - Web UI V2 Scheduled Task Manager" -ForegroundColor Cyan
Write-Host "==========================================================" -ForegroundColor Cyan
Write-Host "Repositório       : $RepoPath"
Write-Host "Tarefa Alvo       : $TaskName"
Write-Host "Tarefa Produção   : $PrimaryTaskName (preservada estritamente)"
Write-Host "Porta de Serviço  : $Port"

# 2. Modo Apenas Status
if ($StatusOnly) {
    Write-Host "`n--- Status das Tarefas Agendadas ---" -ForegroundColor Cyan
    $PrimaryTask = Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction SilentlyContinue
    $WebUiTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

    if ($PrimaryTask) {
        Write-Host "Produção ($PrimaryTaskName) : $($PrimaryTask.State)" -ForegroundColor Green
    } else {
        Write-Host "Produção ($PrimaryTaskName) : NÃO REGISTRADA" -ForegroundColor Yellow
    }

    if ($WebUiTask) {
        Write-Host "Web UI   ($TaskName) : $($WebUiTask.State)" -ForegroundColor Green
    } else {
        Write-Host "Web UI   ($TaskName) : NÃO REGISTRADA" -ForegroundColor Yellow
    }

    # Health check da Web UI V2
    try {
        $Health = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
        Write-Host "Health Web UI V2 (Porta $Port) : HTTP 200 (Role: $($Health.data.role))" -ForegroundColor Green
    } catch {
        Write-Host "Health Web UI V2 (Porta $Port) : INATIVO / INDISPONÍVEL" -ForegroundColor Yellow
    }
    exit 0
}

# 3. Modo Desinstalação (Unregister / Rollback)
if ($Unregister) {
    Write-Step "Solicitada desinstalação da tarefa '$TaskName'..." "WARN"
    $ExistingTask = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
    if ($ExistingTask) {
        if ($ExistingTask.State -eq "Running") {
            Stop-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 2
        }
        Unregister-ScheduledTask -TaskName $TaskName -Confirm:$false
        Write-Step "Tarefa '$TaskName' desregistrada com sucesso." "SUCCESS"
    } else {
        Write-Step "Tarefa '$TaskName' não encontrada para remoção." "INFO"
    }

    # Garante que nenhum processo resíduo fique na porta 8080
    try {
        $PortConns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
        foreach ($Conn in $PortConns) {
            Stop-Process -Id $Conn.OwningProcess -Force -ErrorAction SilentlyContinue
        }
    } catch {}

    Write-Step "Rollback da Scheduled Task concluído. A tarefa de produção '$PrimaryTaskName' permanece intacta." "SUCCESS"
    exit 0
}

# 4. Verificação de Pré-requisitos
Write-Step "Validando pré-requisitos operacionais..." "INFO"

$VenvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
if (-not (Test-Path $VenvPython)) {
    Write-Step "Ambiente virtual Python não encontrado em '$VenvPython'." "ERROR"
    exit 1
}

$StartScript = Join-Path $RepoPath "scripts\start_webui_v2.ps1"
if (-not (Test-Path $StartScript)) {
    Write-Step "Script de inicialização '$StartScript' não encontrado." "ERROR"
    exit 1
}

$DistIndex = Join-Path $RepoPath "webui-v2\dist\index.html"
if (-not (Test-Path $DistIndex)) {
    Write-Step "Build do frontend não encontrado em '$DistIndex'. Descompacte o pacote webui-v2-dist-*.zip antes de registrar a tarefa." "ERROR"
    exit 1
}

# 5. Verificação da Tarefa de Produção Principal (Garantia de Não-Interferência)
$PrimaryTask = Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction SilentlyContinue
if ($PrimaryTask) {
    Write-Step "Tarefa de Produção '$PrimaryTaskName' detectada. Estado atual: $($PrimaryTask.State). Nenhuma alteração será feita nesta tarefa." "SUCCESS"
} else {
    Write-Step "Aviso: Tarefa de produção '$PrimaryTaskName' não localizada. Prosseguindo sem interferir em outros serviços." "WARN"
}

# 6. Tratamento Seguro de Instância Manual Preexistente na Porta 8080
Write-Step "Verificando se há processos manuais em execução na porta $Port..." "INFO"
try {
    $ExistingConns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
    if ($ExistingConns) {
        foreach ($Conn in $ExistingConns) {
            $ProcId = $Conn.OwningProcess
            if ($ProcId -and $ProcId -ne $PID) {
                Write-Step "Processo preexistente (PID $ProcId) detectado na porta $Port. Finalizando para permitir controle via Scheduled Task..." "WARN"
                Stop-Process -Id $ProcId -Force -ErrorAction SilentlyContinue
            }
        }
        Start-Sleep -Seconds 2
    }
} catch {
    Write-Step "Aviso ao inspecionar conexões na porta ${Port}: $_" "WARN"
}

# 7. Definição da Ação da Scheduled Task (Non-Interactive, Hidden Window)
$PwshPath = "$env:SystemRoot\System32\WindowsPowerShell\v1.0\powershell.exe"
$TaskArguments = "-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$StartScript`" -HostAddress `"0.0.0.0`" -Port $Port"

$Action = New-ScheduledTaskAction `
    -Execute $PwshPath `
    -Argument $TaskArguments `
    -WorkingDirectory $RepoPath

# 8. Definição do Gatilho (AtStartup — boot sem exigir login)
$Trigger = New-ScheduledTaskTrigger -AtStartup

# 9. Definição do Principal de Segurança
if ($TaskUser -eq "NT AUTHORITY\SYSTEM") {
    $Principal = New-ScheduledTaskPrincipal `
        -UserId "NT AUTHORITY\SYSTEM" `
        -LogonType ServiceAccount `
        -RunLevel Highest
} else {
    $Principal = New-ScheduledTaskPrincipal `
        -UserId $TaskUser `
        -LogonType S4U `
        -RunLevel Highest
}

# 10. Configuração de Políticas de Execução e Resiliência (Settings)
# - MultipleInstances IgnoreNew: Impede absolutamente processos duplicados
# - RestartCount 3 / RestartInterval 1min: Recuperação automática em caso de encerramento imprevisto
# - ExecutionTimeLimit 0: Execução contínua sem timeout de encerramento
$Settings = New-ScheduledTaskSettingsSet `
    -MultipleInstances IgnoreNew `
    -RestartCount 3 `
    -RestartInterval (New-TimeSpan -Minutes 1) `
    -ExecutionTimeLimit (New-TimeSpan -Days 0) `
    -AllowStartIfOnBatteries `
    -DontStopIfGoingOnBatteries

# 11. Registro Idempotente da Tarefa
Write-Step "Registrando Scheduled Task '$TaskName'..." "INFO"
try {
    Register-ScheduledTask `
        -TaskName $TaskName `
        -Action $Action `
        -Trigger $Trigger `
        -Principal $Principal `
        -Settings $Settings `
        -Description "Video Factory Web UI V2 - Servidor FastAPI/Uvicorn Same-Origin (porta 8080)" `
        -Force | Out-Null
    Write-Step "Tarefa '$TaskName' registrada com sucesso." "SUCCESS"
} catch {
    Write-Step "Falha ao registrar Scheduled Task: $_. Verifique se o PowerShell está em modo Administrador." "ERROR"
    exit 1
}

# 12. Inicialização da Tarefa e Verificação de Saúde
if ($StartTask) {
    Write-Step "Iniciando a Scheduled Task '$TaskName'..." "INFO"
    Start-ScheduledTask -TaskName $TaskName
    
    # Aguarda inicialização com polling limitado a 30s
    $TimeoutSec = 30
    $Elapsed = 0
    $Healthy = $false
    $HealthData = $null

    Write-Host -NoNewline "Aguardando inicialização do servidor Uvicorn na porta $Port"
    while ($Elapsed -lt $TimeoutSec) {
        Start-Sleep -Seconds 2
        $Elapsed += 2
        Write-Host -NoNewline "."
        try {
            $Resp = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/v2/health" -TimeoutSec 3 -ErrorAction SilentlyContinue
            if ($Resp -and $Resp.status -eq 200 -and $Resp.data.status -eq "healthy") {
                $Healthy = $true
                $HealthData = $Resp.data
                break
            }
        } catch {}
    }
    Write-Host ""

    if (-not $Healthy) {
        Write-Step "Aviso: Servidor ainda não respondeu ao health check em $TimeoutSec segundos. Verifique os logs em 'storage\logs\webui_v2\webui_v2_startup.log'." "WARN"
    } else {
        Write-Step "Health check da Web UI V2 passou com sucesso (HTTP 200)!" "SUCCESS"
        Write-Step "Role Operacional : $($HealthData.role)" "SUCCESS"
        Write-Step "Same-Origin Build : $($HealthData.same_origin)" "SUCCESS"
        if ($HealthData.role -eq "SECONDARY_VIEW_ONLY") {
            Write-Step "Conformidade Canônica: O nó opera em SECONDARY_VIEW_ONLY com Streamlit ativo como PRIMARY." "SUCCESS"
        }
    }
}

# 13. Resumo Final do Estado das Duas Tarefas
Write-Host "`n==========================================================" -ForegroundColor Green
Write-Host " INSTALAÇÃO DA SCHEDULED TASK CONCLUÍDA COM SUCESSO" -ForegroundColor Green
Write-Host "==========================================================" -ForegroundColor Green

$FinalPrimary = Get-ScheduledTask -TaskName $PrimaryTaskName -ErrorAction SilentlyContinue
$FinalWebUi = Get-ScheduledTask -TaskName $TaskName -ErrorAction SilentlyContinue

Write-Host "Produção ($PrimaryTaskName) : $(if ($FinalPrimary) { $FinalPrimary.State } else { 'N/A' }) (PRESERVADA INTACTA)" -ForegroundColor Green
Write-Host "Web UI   ($TaskName) : $(if ($FinalWebUi) { $FinalWebUi.State } else { 'N/A' })" -ForegroundColor Green
Write-Host "Porta de Escuta             : $Port"
Write-Host "URL Local                   : http://localhost:$Port"
Write-Host "URL na Rede / Tailscale     : http://<IP_DO_PC_FORTE>:$Port"
Write-Host "Logs Operacionais           : $RepoPath\storage\logs\webui_v2\"
Write-Host "==========================================================`n" -ForegroundColor Green
