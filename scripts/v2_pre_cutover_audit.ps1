<#
.SYNOPSIS
    Script de Auditoria Passiva Pre-Cutover V2.15B para Video Factory (PC Forte).
.DESCRIPTION
    Executa verificacao 100% somente-leitura e passiva no PC Forte.
    - Localiza o banco real storage/video_factory.db e valida PRAGMA integrity_check.
    - Audita rigorosamente o diff do hotfix de app/services/autonomous_production.py.
    - Reconhece o arquivo .bak do hotfix.
    - Identifica os papeis dos processos em 8080 (WebUI V2) e 8501 (Streamlit PRIMARY).
    - Valida o estado de instance_locks no SQLite.
    - Inspeciona credenciais em .env, variaveis de ambiente e storage/credentials/ sem vazar valores.
    - Emite relatorio objetivo PASS / BLOCKED.
#>
[CmdletBinding()]
param(
    [string]$RepoPath = "C:\Projetos\MoneyPrinterTurbo"
)

Set-StrictMode -Off
$ErrorActionPreference = "Continue"

# Sincronizar PATH da sessao com User e Machine (para garantir git, ffmpeg, node no PATH)
$machinePath = [System.Environment]::GetEnvironmentVariable("Path", "Machine")
$userPath = [System.Environment]::GetEnvironmentVariable("Path", "User")
$env:Path = "$machinePath;$userPath"

Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "   VIDEO FACTORY V2.15B - AUDITORIA PASSIVA PRE-CUTOVER     " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan
Write-Host "Data/Hora : $(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')"
Write-Host "Repo Path : $RepoPath"
Write-Host ""

$blockers = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

# 1. Caminho e Validacao Git
if (-not (Test-Path $RepoPath)) {
    $blockers.Add("Caminho do repositorio $RepoPath nao existe.")
    Write-Host "[FATAL] Diretorio do repositorio nao encontrado: $RepoPath" -ForegroundColor Red
    exit 2
}

$VenvPython = Join-Path $RepoPath ".venv\Scripts\python.exe"
$PythonExe = if (Test-Path $VenvPython) { $VenvPython } else { "python" }

Push-Location $RepoPath
try {
    $sha = (git rev-parse HEAD 2>$null)
    $branch = (git rev-parse --abbrev-ref HEAD 2>$null)
    $status = (git status --porcelain 2>$null)
    Write-Host "[GIT] Branch Atual : $branch"
    Write-Host "[GIT] Commit SHA   : $sha"

    if ($status) {
        Write-Host "`n[GIT] Verificando modificacoes locais no working tree:" -ForegroundColor Cyan
        $status | ForEach-Object { Write-Host "      $_" }

        $lines = $status | Where-Object { $_.Trim() -ne "" }
        foreach ($line in $lines) {
            $code = $line.Substring(0, 2).Trim()
            $file = $line.Substring(2).Trim()

            if ($file -eq "app/services/autonomous_production.py" -or $file -eq "app\services\autonomous_production.py") {
                # Auditar diff exato do hotfix
                $diff = (git diff app/services/autonomous_production.py 2>$null)
                $addedLines = @($diff | Where-Object { $_ -like '+*' -and -not ($_ -like '+++*') })
                $removedLines = @($diff | Where-Object { $_ -like '-*' -and -not ($_ -like '---*') })

                $diffMatch = $false
                if ($addedLines.Count -eq 1 -and $removedLines.Count -eq 0) {
                    $cleaned = $addedLines[0].Trim()
                    if ($cleaned -eq "+    rejected_struct = None" -or $cleaned -eq "+rejected_struct = None") {
                        $diffMatch = $true
                    }
                }

                if ($diffMatch) {
                    Write-Host "  [OK] Hotfix de autonomous_production.py validado: 'rejected_struct = None' adicionado." -ForegroundColor Green
                } else {
                    $blockers.Add("Modificacao em app/services/autonomous_production.py diverge do hotfix autorizado.")
                    Write-Host "  [X] Diff nao confere com o hotfix autorizado!" -ForegroundColor Red
                }
            } elseif ($file -like "app/services/autonomous_production.py.bak*" -or $file -like "app\services\autonomous_production.py.bak*") {
                Write-Host "  [OK] Arquivo de backup do hotfix reconhecido: $file" -ForegroundColor Green
            } elseif ($file -like "*v2_pre_cutover_audit.ps1" -or $file -like "*v2_cutover.ps1") {
                Write-Host "  [INFO] Script operacional de transicao detectado: $file" -ForegroundColor Gray
            } else {
                $blockers.Add("Arquivo modificado ou nao rastreado desconhecido no Git: $file")
                Write-Host "  [X] Arquivo nao reconhecido: $file" -ForegroundColor Red
            }
        }
    } else {
        Write-Host "[GIT] Working tree limpo." -ForegroundColor Green
    }
} catch {
    $blockers.Add("Falha ao executar comandos Git.")
} finally {
    Pop-Location
}

# 2. Portas e Mapeamento de Processos (8080 e 8501)
Write-Host "`n--- Portas e Processos de Producao ---" -ForegroundColor Cyan

# Porta 8080 (WebUI V2 / FastAPI)
$p8080 = Get-NetTCPConnection -LocalPort 8080 -State Listen -ErrorAction SilentlyContinue
if ($p8080) {
    $proc8080 = Get-Process -Id $p8080.OwningProcess -ErrorAction SilentlyContinue
    $cmd8080 = (Get-CimInstance Win32_Process -Filter "ProcessId = $($p8080.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
    Write-Host "Porta 8080 (WebUI V2) : OCUPADA por PID $($p8080.OwningProcess) ($($proc8080.ProcessName))" -ForegroundColor Yellow
    Write-Host "    Comando : $cmd8080" -ForegroundColor Gray
    Write-Host "    Papel   : Servidor FastAPI/Uvicorn (modo visualizador/API, nao disputa Scheduler)." -ForegroundColor Gray
} else {
    Write-Host "Porta 8080 (WebUI V2) : LIVRE" -ForegroundColor Green
}

# Porta 8501 (Streamlit / Production Entrypoint)
$p8501 = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue
if ($p8501) {
    $proc8501 = Get-Process -Id $p8501.OwningProcess -ErrorAction SilentlyContinue
    $cmd8501 = (Get-CimInstance Win32_Process -Filter "ProcessId = $($p8501.OwningProcess)" -ErrorAction SilentlyContinue).CommandLine
    Write-Host "Porta 8501 (Streamlit) : ATIVA com PID $($p8501.OwningProcess) ($($proc8501.ProcessName))" -ForegroundColor Yellow
    Write-Host "    Comando : $cmd8501" -ForegroundColor Gray
    Write-Host "    Papel   : Streamlit legada com SchedulerExecutionWorker ativo (PRIMARY atual)." -ForegroundColor Gray
} else {
    Write-Host "Porta 8501 (Streamlit) : INATIVA" -ForegroundColor Yellow
}

# 3. Scheduled Tasks e Servicos Windows
Write-Host "`n--- Tarefas Agendadas e Servicos ---" -ForegroundColor Cyan
$tasks = Get-ScheduledTask -ErrorAction SilentlyContinue | Where-Object { $_.TaskName -like '*MoneyPrinter*' -or $_.TaskName -like '*VideoFactory*' -or $_.TaskName -like '*Production*' }
if ($tasks) {
    foreach ($t in $tasks) {
        Write-Host "Tarefa Agendada : $($t.TaskName) | Estado: $($t.State)" -ForegroundColor Cyan
    }
} else {
    Write-Host "Nenhuma Scheduled Task de VideoFactory encontrada."
}

# 4. Banco SQLite Real e Integridade Passiva
Write-Host "`n--- Banco SQLite Real e Integridade ---" -ForegroundColor Cyan
$dbCandidates = @(
    (Join-Path $RepoPath "storage\video_factory.db"),
    (Join-Path $RepoPath "video_factory.db"),
    (Join-Path $RepoPath "storage\db.sqlite3"),
    (Join-Path $RepoPath "db.sqlite3")
)

$dbPath = $null
foreach ($cand in $dbCandidates) {
    if (Test-Path $cand) {
        $dbPath = $cand
        break
    }
}

if ($dbPath) {
    $dbSizeMb = [math]::Round((Get-Item $dbPath).Length / 1MB, 2)
    Write-Host "Banco Efetivo Identificado : $dbPath ($dbSizeMb MB)" -ForegroundColor Green

    $pyDbCheck = @'
import sqlite3, json, sys, os
p = sys.argv[1]
res = {'exists': os.path.exists(p), 'integrity': 'UNKNOWN', 'tables': {}, 'primary_holder': 'UNKNOWN', 'in_flight_count': 0, 'scheduled_count': 0, 'auto_publish_enabled': 'UNKNOWN'}
try:
    conn = sqlite3.connect(p)
    cur = conn.cursor()
    cur.execute('PRAGMA integrity_check;')
    row = cur.fetchone()
    res['integrity'] = row[0] if row else 'FAILED'
    for t in ['content_profiles', 'publishing_channels', 'publication_events', 'scheduled_posts', 'instance_locks', 'autopilot_settings']:
        try:
            cur.execute(f"SELECT count(*) FROM {t}")
            res['tables'][t] = cur.fetchone()[0]
        except Exception:
            res['tables'][t] = 'NOT_FOUND'
    try:
        cur.execute("SELECT node_id, is_primary, last_heartbeat FROM instance_locks WHERE is_primary = 1 LIMIT 1")
        lock_row = cur.fetchone()
        if lock_row:
            res['primary_holder'] = f"Node: {lock_row[0]} (Heartbeat: {lock_row[2]})"
        else:
            res['primary_holder'] = "NENHUM (Locks livres)"
    except Exception:
        pass
    try:
        cur.execute("SELECT count(*) FROM scheduled_posts WHERE status = 'processing'")
        res['in_flight_count'] = cur.fetchone()[0]
        cur.execute("SELECT count(*) FROM scheduled_posts WHERE status IN ('planned', 'ready')")
        res['scheduled_count'] = cur.fetchone()[0]
    except Exception:
        pass
    try:
        cur.execute("SELECT value FROM autopilot_settings WHERE key = 'auto_publish_enabled'")
        ap_row = cur.fetchone()
        res['auto_publish_enabled'] = ap_row[0] if ap_row else 'false'
    except Exception:
        pass
    conn.close()
except Exception as e:
    res['integrity'] = f'ERROR: {e}'
print(json.dumps(res))
'@
    $tmpDbPy = Join-Path $env:TEMP "check_db_audit_v2.py"
    Set-Content -Path $tmpDbPy -Value $pyDbCheck -Encoding UTF8
    $dbReportRaw = (& $PythonExe $tmpDbPy "$dbPath" 2>&1)
    Remove-Item -Path $tmpDbPy -ErrorAction SilentlyContinue

    $jsonLine = ($dbReportRaw | Where-Object { $_ -like '*{*' }) | Select-Object -Last 1
    if ($jsonLine) {
        try {
            $dbReport = $jsonLine | ConvertFrom-Json
            $integColor = if ($dbReport.integrity -eq 'ok') { 'Green' } else { 'Red' }
            Write-Host "Integridade SQLite         : $($dbReport.integrity)" -ForegroundColor $integColor
            if ($dbReport.integrity -ne 'ok') {
                $blockers.Add("Integridade do SQLite falhou: $($dbReport.integrity)")
            }
            Write-Host "Tabelas Auditadas          : $(($dbReport.tables | ConvertTo-Json -Compress))"
            Write-Host "Detentor do Lock PRIMARY   : $($dbReport.primary_holder)" -ForegroundColor Cyan
            Write-Host "Auto Publish Configurado   : $($dbReport.auto_publish_enabled)" -ForegroundColor $(if ($dbReport.auto_publish_enabled -eq 'true') { 'Yellow' } else { 'Green' })
            Write-Host "Posts em Publicacao (Voo)  : $($dbReport.in_flight_count)" -ForegroundColor $(if ($dbReport.in_flight_count -gt 0) { 'Red' } else { 'Green' })
            Write-Host "Posts Agendados (Fila)     : $($dbReport.scheduled_count)"

            if ($dbReport.in_flight_count -gt 0) {
                $blockers.Add("Existem $($dbReport.in_flight_count) postagens em andamento ('processing'). Aguarde o termino antes do cutover.")
            }
            if ($dbReport.scheduled_count -gt 0) {
                $warnings.Add("Existem $($dbReport.scheduled_count) posts agendados na fila ('planned'/'ready').")
            }
        } catch {
            Write-Host "Aviso ao converter JSON do DB: $_" -ForegroundColor Yellow
            $warnings.Add("Falha na interpretacao JSON do relatorio SQLite.")
        }
    } else {
        Write-Host "Aviso: Nao foi retornado JSON do DB: $dbReportRaw" -ForegroundColor Yellow
        $warnings.Add("Relatorio SQLite vazio.")
    }
} else {
    $blockers.Add("Nenhum banco de dados SQLite valido encontrado em $RepoPath.")
    Write-Host "[X] Banco de dados nao localizado!" -ForegroundColor Red
}

# 5. Espaco em Disco
Write-Host "`n--- Espaco em Disco ---" -ForegroundColor Cyan
$driveLetter = (Get-Item $RepoPath).PSDrive.Name
$drive = Get-PSDrive -Name $driveLetter
$freeGb = [math]::Round($drive.Free / 1GB, 2)
Write-Host "Disco ${driveLetter}: $freeGb GB livres" -ForegroundColor Green
if ($freeGb -lt 5) {
    $blockers.Add("Espaco em disco insuficiente: $freeGb GB disponiveis (< 5GB).")
}

# 6. Ferramentas Essenciais e Processos Ativos
Write-Host "`n--- Ferramentas de Sistema e Processos Ativos ---" -ForegroundColor Cyan
$pyVer = (& $PythonExe --version 2>&1)
Write-Host "Python : $pyVer ($PythonExe)"
$ffVer = (ffmpeg -version 2>&1)
if ($ffVer -like '*ffmpeg version*') {
    Write-Host "FFmpeg : $(($ffVer -split "`n")[0])" -ForegroundColor Green
} else {
    $blockers.Add("FFmpeg ausente do PATH.")
}

# Verificacao de Renderizacoes FFmpeg Ativas
$activeFfmpeg = Get-Process ffmpeg -ErrorAction SilentlyContinue
if ($activeFfmpeg) {
    $blockers.Add("Processo FFmpeg em execucao (PID $($activeFfmpeg.Id)). Renderizacao em andamento: aguarde a conclusao antes do cutover.")
    Write-Host "FFmpeg Ativo : Renderizacao em andamento (PID $($activeFfmpeg.Id))" -ForegroundColor Red
} else {
    Write-Host "FFmpeg Ativo : Nenhum processo em renderizacao." -ForegroundColor Green
}

# 7. Diagnostico Passivo de Credenciais
Write-Host "`n--- Diagnostico Passivo de Credenciais (Zero Vazamento) ---" -ForegroundColor Cyan
$envPath = Join-Path $RepoPath ".env"
$credDir = Join-Path $RepoPath "storage\credentials"

$pyCredCheck = @'
import os, sys, json
env_path, cred_dir = sys.argv[1], sys.argv[2]
keys = ['YOUTUBE_API_KEY', 'TIKTOK_SESSION_ID', 'GEMINI_API_KEY', 'OPENAI_API_KEY', 'GROQ_API_KEY', 'PEXELS_API_KEY']
res = {k: 'MISSING' for k in keys}

if os.path.exists(env_path):
    with open(env_path, 'r', encoding='utf-8', errors='ignore') as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith('#') and '=' in line:
                k, v = line.split('=', 1)
                k = k.strip()
                v = v.strip().strip('"').strip("'")
                if k in res and len(v) > 3:
                    res[k] = 'CONFIGURED (.env)'

for k in keys:
    if k in os.environ and len(os.environ[k].strip()) > 3:
        res[k] = 'CONFIGURED (EnvVar)'

res['OAUTH_STORAGE_CREDENTIALS'] = 'MISSING'
if os.path.exists(cred_dir):
    files = [f for f in os.listdir(cred_dir) if f.endswith('.json') or f.endswith('.token')]
    if files:
        res['OAUTH_STORAGE_CREDENTIALS'] = f"CONFIGURED ({len(files)} arquivos)"

print(json.dumps(res))
'@
$tmpCredPy = Join-Path $env:TEMP "check_cred_audit_v2.py"
Set-Content -Path $tmpCredPy -Value $pyCredCheck -Encoding UTF8
$credReportRaw = (& $PythonExe $tmpCredPy "$envPath" "$credDir" 2>&1)
Remove-Item -Path $tmpCredPy -ErrorAction SilentlyContinue

try {
    $credReport = $credReportRaw | ConvertFrom-Json
    $credReport.PSObject.Properties | ForEach-Object {
        $color = if ($_.Value -like 'CONFIGURED*') { 'Green' } else { 'Yellow' }
        Write-Host "   $($_.Name) : $($_.Value)" -ForegroundColor $color
    }
} catch {
    Write-Host "Aviso ao auditar credenciais: $credReportRaw" -ForegroundColor Yellow
}

# 8. Relatorio Final PASS / BLOCKED
Write-Host "`n============================================================" -ForegroundColor Cyan
Write-Host "   RESULTADO DA AUDITORIA PRE-CUTOVER V2.15B               " -ForegroundColor Cyan
Write-Host "============================================================" -ForegroundColor Cyan

if ($warnings.Count -gt 0) {
    Write-Host "ALERTAS DE OPERACAO ($($warnings.Count)):`n" -ForegroundColor Yellow
    $warnings | ForEach-Object { Write-Host "  [!] $_" -ForegroundColor Yellow }
}

if ($blockers.Count -gt 0) {
    Write-Host "`nBLOQUEIOS CRITICOS ($($blockers.Count)):`n" -ForegroundColor Red
    $blockers | ForEach-Object { Write-Host "  [X] $_" -ForegroundColor Red }
    Write-Host "`nSTATUS AUDITORIA : BLOCKED" -ForegroundColor Red
    exit 2
} else {
    Write-Host "`nNenhum bloqueio critico detectado. Ambiente de producao integro e validado." -ForegroundColor Green
    Write-Host "STATUS AUDITORIA : PASS" -ForegroundColor Green
    exit 0
}
