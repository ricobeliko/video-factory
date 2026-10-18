<#
.SYNOPSIS
    Script de Auditoria Passiva Pre-Cutover para Video Factory V2 (PC Forte).
.DESCRIPTION
    Executa verificacao 100% somente-leitura no PC Forte.
    Zero escritas, zero paradas de servico, zero alteracoes em banco, zero vazamento de secrets.
    Emite relatorio objetivo PASS / BLOCKED.
#>
[CmdletBinding()]
param(
    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo"
)

Set-StrictMode -Off
$ErrorActionPreference = "Continue"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   VIDEO FACTORY V2.15A - AUDITORIA PASSIVA PRE-CUTOVER     " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Data/Hora : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Repo Path : $RepoPath"
Write-Host ""

$blockers = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

# 1. Caminho e Git
if (-not (Test-Path $RepoPath)) {
    $blockers.Add("Caminho do repositorio $RepoPath nao existe.")
    Write-Host "[FATAL] Diretorio do repositorio nao encontrado: $RepoPath" -ForegroundColor Red
    exit 1
}

Push-Location $RepoPath
try {
    $sha = (git rev-parse HEAD 2>$null)
    $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
    $status = (git status --porcelain 2>$null)
    Write-Host "[GIT] Branch Atual : $branch"
    Write-Host "[GIT] Commit SHA   : $sha"
    if ($status) {
        Write-Host "[GIT] Arquivos modificados nao commitados:" -ForegroundColor Yellow
        $status | ForEach-Object { Write-Host "      $_" -ForegroundColor Yellow }
        $modifiedFiles = $status | ForEach-Object { ($_ -split '\s+')[-1] }
        $safeHotfixOnly = $true
        foreach ($f in $modifiedFiles) {
            if ($f -ne 'app/services/autonomous_production.py' -and -not $f.EndsWith('.bak') -and $f -ne 'scripts/v2_pre_cutover_audit.ps1') {
                $safeHotfixOnly = $false
            }
        }
        if (-not $safeHotfixOnly) {
            $blockers.Add("Ha arquivos modificados alem do hotfix conhecido (app/services/autonomous_production.py ou .bak).")
        } else {
            Write-Host "[GIT] Apenas hotfix pontual de production/autonomous_production detectado (elegivel para reconciliacao segura)." -ForegroundColor Cyan
        }
    } else {
        Write-Host "[GIT] Working tree limpo." -ForegroundColor Green
    }
} catch {
    $blockers.Add("Falha ao executar comandos Git.")
} finally {
    Pop-Location
}

# 2. Portas e Processos (8080 e 8501)
Write-Host "`n--- Portas e Processos ---" -ForegroundColor Cyan
$p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($p8080) {
    $proc8080 = Get-Process -Id $p8080.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "Porta 8080 : OCUPADA por PID $($p8080.OwningProcess) ($($proc8080.ProcessName))" -ForegroundColor Yellow
    $warnings.Add("Porta 8080 em uso por PID $($p8080.OwningProcess). Necessario parada graciosa no cutover.")
} else {
    Write-Host "Porta 8080 : LIVRE" -ForegroundColor Green
}

$p8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if ($p8501) {
    $proc8501 = Get-Process -Id $p8501.OwningProcess -ErrorAction SilentlyContinue
    Write-Host "Porta 8501 (Streamlit) : ATIVA com PID $($p8501.OwningProcess) ($($proc8501.ProcessName))" -ForegroundColor Green
} else {
    Write-Host "Porta 8501 (Streamlit) : INATIVA" -ForegroundColor Yellow
}

# Processos Python
$pyProcs = Get-CimInstance Win32_Process -Filter "name = 'python.exe'" -ErrorAction SilentlyContinue |
           Select-Object ProcessId, CommandLine
$streamlits = @($pyProcs | Where-Object { $_.CommandLine -like '*streamlit*' })
$uvicorns = @($pyProcs | Where-Object { $_.CommandLine -like '*uvicorn*' -or $_.CommandLine -like '*production_entrypoint*' })
Write-Host "Processos Streamlit detectados: $($streamlits.Count)"
Write-Host "Processos Uvicorn/FastAPI detectados: $($uvicorns.Count)"

# 3. Servicos Windows e Tarefas Agendadas
Write-Host "`n--- Tarefas Agendadas e Servicos ---" -ForegroundColor Cyan
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like '*MoneyPrinter*' -or $_.TaskName -like '*VideoFactory*' -or $_.TaskName -like '*Production*' }
if ($tasks) {
    foreach ($t in $tasks) {
        Write-Host "Tarefa: $($t.TaskName) | Estado: $($t.State)" -ForegroundColor Cyan
    }
} else {
    Write-Host "Nenhuma Scheduled Task de VideoFactory/MoneyPrinter encontrada."
}

$services = Get-Service -ErrorAction SilentlyContinue | Where-Object { $_.Name -like '*MoneyPrinter*' -or $_.Name -like '*VideoFactory*' }
if ($services) {
    foreach ($s in $services) {
        Write-Host "Servico: $($s.Name) | Status: $($s.Status)" -ForegroundColor Cyan
    }
} else {
    Write-Host "Nenhum Windows Service dedicado registrado."
}

# 4. Ferramentas (Python, Node, FFmpeg)
Write-Host "`n--- Ferramentas de Sistema ---" -ForegroundColor Cyan
$pyVer = (python --version 2>&1)
Write-Host "Python: $pyVer"
if (-not ($pyVer -like '*3.1*')) {
    $warnings.Add("Python nao e 3.10+: $pyVer")
}

$nodeVer = (node --version 2>&1)
if ($nodeVer -like 'v*') {
    Write-Host "Node.js: $nodeVer" -ForegroundColor Green
} else {
    Write-Host "Node.js: NAO ENCONTRADO" -ForegroundColor Yellow
    $warnings.Add("Node.js ausente no PATH (necessario se for gerar build frontend no host).")
}

$ffVer = (ffmpeg -version 2>&1)
if ($ffVer -like '*ffmpeg version*') {
    $firstLine = ($ffVer -split "`n")[0]
    Write-Host "FFmpeg: $firstLine" -ForegroundColor Green
} else {
    Write-Host "FFmpeg: NAO ENCONTRADO" -ForegroundColor Red
    $blockers.Add("FFmpeg nao esta no PATH do sistema.")
}

# 5. Banco SQLite e Integridade
Write-Host "`n--- Banco SQLite e Integridade ---" -ForegroundColor Cyan
$dbPath = Join-Path $RepoPath "db.sqlite3"
if (-not (Test-Path $dbPath)) {
    $dbPath = Join-Path $RepoPath "storage\db.sqlite3"
}

if (Test-Path $dbPath) {
    $pyDbCheck = @'
import sqlite3, json, sys, os
p = sys.argv[1]
res = {'exists': os.path.exists(p), 'integrity': 'UNKNOWN', 'tables': {}, 'active_tasks': 0, 'interrupted_tasks': 0}
try:
    conn = sqlite3.connect(p)
    cur = conn.cursor()
    cur.execute('PRAGMA integrity_check;')
    row = cur.fetchone()
    res['integrity'] = row[0] if row else 'FAILED'
    for t in ['channels', 'posts', 'publication_logs', 'tasks', 'materials']:
        try:
            cur.execute(f'SELECT count(*) FROM {t}')
            res['tables'][t] = cur.fetchone()[0]
        except Exception:
            res['tables'][t] = 'NOT_FOUND'
    try:
        cur.execute("SELECT count(*) FROM tasks WHERE status IN ('processing', 'running', 'in_progress')")
        res['active_tasks'] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM tasks WHERE status = 'interrupted'")
        res['interrupted_tasks'] = cur.fetchone()[0]
    except Exception:
        pass
    conn.close()
except Exception as e:
    res['integrity'] = f'ERROR: {e}'
print(json.dumps(res))
'@
    $tmpDbPy = Join-Path $env:TEMP "check_db_audit.py"
    Set-Content -Path $tmpDbPy -Value $pyDbCheck -Encoding UTF8
    $dbReportRaw = (python $tmpDbPy "$dbPath" 2>&1)
    Remove-Item -Path $tmpDbPy -ErrorAction SilentlyContinue

    try {
        $dbReport = $dbReportRaw | ConvertFrom-Json
        Write-Host "Caminho do DB : $dbPath"
        Write-Host "Existe        : $($dbReport.exists)"
        Write-Host "Integridade   : $($dbReport.integrity)"
        if ($dbReport.integrity -ne 'ok' -and $dbReport.exists) {
            $blockers.Add("Integridade do SQLite falhou: $($dbReport.integrity)")
        }
        Write-Host "Tabelas       : $(($dbReport.tables | ConvertTo-Json -Compress))"
        Write-Host "Tarefas Ativas: $($dbReport.active_tasks)"
        if ($dbReport.active_tasks -gt 0) {
            $warnings.Add("Existem $($dbReport.active_tasks) tarefas ativas no banco. Aguardar conclusao antes do corte.")
        }
    } catch {
        Write-Host "Erro ao analisar DB: $dbReportRaw" -ForegroundColor Yellow
        $warnings.Add("Nao foi possivel analisar DB via script Python.")
    }
} else {
    Write-Host "Banco db.sqlite3 nao localizado em $dbPath (novo ambiente ou caminho customizado)." -ForegroundColor Yellow
    $warnings.Add("Banco db.sqlite3 nao encontrado no caminho padrao.")
}

# 6. Espaco em Disco
Write-Host "`n--- Espaco em Disco ---" -ForegroundColor Cyan
$driveLetter = (Get-Item $RepoPath).PSDrive.Name
$drive = Get-PSDrive -Name $driveLetter
$freeGb = [math]::Round($drive.Free / 1GB, 2)
Write-Host "Disco ${driveLetter}: $freeGb GB livres"
if ($freeGb -lt 5) {
    $blockers.Add("Espaco em disco inferior a 5GB ($freeGb GB disponiveis).")
} elseif ($freeGb -lt 15) {
    $warnings.Add("Espaco em disco baixo ($freeGb GB disponiveis).")
}

# 7. Disponibilidade de Credenciais (Apenas Presenca - Sem Revelar Segredos)
Write-Host "`n--- Verificacao Passiva de Credenciais (Apenas Presenca) ---" -ForegroundColor Cyan
$envPath = Join-Path $RepoPath ".env"
$pyCredCheck = @'
import os, sys, json
env_file = sys.argv[1]
keys = ['YOUTUBE_API_KEY', 'TIKTOK_SESSION_ID', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'GROQ_API_KEY', 'PEXELS_API_KEY']
res = {k: 'MISSING' for k in keys}
if os.path.exists(env_file):
    with open(env_file, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('\"').strip('\'')
                if k in res:
                    res[k] = 'CONFIGURED' if len(v) > 3 else 'EMPTY'
for k in keys:
    if k in os.environ and len(os.environ[k].strip()) > 3:
        res[k] = 'CONFIGURED'
print(json.dumps(res))
'@
$tmpCredPy = Join-Path $env:TEMP "check_cred_audit.py"
Set-Content -Path $tmpCredPy -Value $pyCredCheck -Encoding UTF8
$credReportRaw = (python $tmpCredPy "$envPath" 2>&1)
Remove-Item -Path $tmpCredPy -ErrorAction SilentlyContinue

try {
    $credReport = $credReportRaw | ConvertFrom-Json
    $credReport.PSObject.Properties | ForEach-Object {
        $statusColor = if ($_.Value -eq 'CONFIGURED') { 'Green' } else { 'Yellow' }
        Write-Host "   $($_.Name) : $($_.Value)" -ForegroundColor $statusColor
    }
} catch {
    Write-Host "Aviso ao verificar credenciais: $credReportRaw" -ForegroundColor Yellow
}

# 8. Relatorio Final PASS / BLOCKED
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "   RESULTADO DA AUDITORIA PRE-CUTOVER                      " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if ($warnings.Count -gt 0) {
    Write-Host "ALERTAS / ATENCAO ($($warnings.Count)):`n" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host "  [!] $_" -ForegroundColor Yellow }
}

if ($blockers.Count -gt 0) {
    Write-Host "`nBLOQUEIOS CRITICOS ($($blockers.Count)):`n" -ForegroundColor Red
    $blockers | ForEach-Object { Write-Host "  [X] $_" -ForegroundColor Red }
    Write-Host "`nSTATUS AUDITORIA : BLOCKED" -ForegroundColor Red
    exit 2
} else {
    Write-Host "`nNenhum bloqueio critico encontrado." -ForegroundColor Green
    Write-Host "STATUS AUDITORIA : PASS" -ForegroundColor Green
    exit 0
}
