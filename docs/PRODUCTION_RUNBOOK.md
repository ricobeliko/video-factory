# PRODUCTION_RUNBOOK — Video Factory


## V12-E.2.2 — Persistent Waiting Schedule Recovery (20/09/2026)

Hotfix validado localmente; deploy de produção não realizado. V12-E permanece em homologação e o gate real PUBLIC no YouTube continua pendente.

Causa raiz confirmada: após perda do MemoryState, WAITING_SCHEDULE enviava apenas `task_id`. O scheduler descartava o payload sem COMPLETE ou `video_file`, antes de resolver os destinos persistidos.

Correção: o retry verifica vídeo final existente e não vazio via `get_task_final_video()`, Safety PASS explícito, último Quality finito >= 70 com label GOOD/STRONG, YouTube em `task_platforms`, vínculo em `task_profiles`, perfil ativo e canal YouTube habilitado. Reconstrói o payload quando a memória está ausente/incompleta e preserva vetos de estado presentes em memória. Reutiliza o scheduler para Growth Mode e deduplicação por task/canal; envia somente YouTube.

Recuperação inválida mantém WAITING_SCHEDULE com `reason=waiting_recovery_failed` e diagnóstico na mensagem. Sem slot, permanece em espera; sucesso agenda e retorna. Nenhum desses caminhos gera outra task no mesmo ciclo. Auto Publish, TikTok, MPT Auto Upload, schema e thresholds de produção permanecem inalterados.

Validação: **234 testes + 19 subcasos PASS** nas oito suítes abaixo. Cenários novos: memória presente/ausente/incompleta, vídeo ausente/vazio, Safety BLOCK/REVIEW/ausente, Quality ausente/baixo/label inválido, perfil/canal/destino inválidos, slot WARMUP ocupado, idempotência e destinos terminais, one_shot com Autonomous OFF, nenhuma nova geração, Auto Publish OFF e exclusão de TikTok. Publicação é interceptada por mocks e conexões externas são bloqueadas nos novos retries. Sete testes legados do scheduler agora declaram SCALE apenas no SQLite temporário para verificar tetos técnicos; Growth Mode de produção não mudou.

```powershell
.venv/Scripts/python.exe -m pytest test/services/test_autonomous_production.py test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_quality_score.py test/services/test_operator_console.py test/services/test_single_instance.py test/services/test_schedule_cancellation.py test/services/test_production_health.py -q -p no:cacheprovider
```

Próximo passo seguro: no PC de produção, seguir stop/backup/update/test/start com uma única instância PRIMARY. Manter Auto Publish OFF durante a verificação. Executar um ciclo supervisionado para a waiting task `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`; conferir um único destino por canal, nenhuma nova geração e gates preservados. Sem slot, aguardar Growth Mode. Em `waiting_recovery_failed`, inspecionar o diagnóstico e corrigir a evidência pela operação normal, sem forçar COMPLETE nem limpar o waiting ID. PUBLIC segue como gate posterior de homologação supervisionada.

---

**Atualizado em:** 20/09/2026

**Host de produção:** PC forte

**Projeto:** `C:\Projetos\MoneyPrinterTurbo`

---

## 1. Princípios operacionais

Produção é autoridade única para:
- SQLite
- workers
- scheduler
- geração
- publicação
- Operator Console

Nunca:
- rodar duas instâncias PRIMARY
- atualizar código com backend ativo
- usar `git reset`, `git restore` ou `git clean`
- ativar MPT Auto Upload
- ativar TikTok sem homologação
- fazer publicação real durante testes unitários

---

## 2. Estado seguro antes de deploy

Esperado:

```text
Factory RUNNING
Scheduler ON
Auto Publish OFF
Dry Run OFF
Growth Mode warmup
YouTube ON
TikTok OFF
Autonomous OFF
MPT Auto Upload OFF
```

---

## 3. Backup manual seguro

Executar com backend ativo:

```powershell
cd C:\Projetos\MoneyPrinterTurbo
powershell -ExecutionPolicy Bypass -File .\scripts\backup_production.ps1
```

Validar:
- exit code 0
- integridade `ok`
- SHA-256 registrado
- arquivo criado em `storage\backups\database`

---

## 4. Parar produção antes de update

```powershell
Stop-ScheduledTask -TaskName "VideoFactory Production"

Start-Sleep -Seconds 5

Get-ScheduledTask -TaskName "VideoFactory Production" |
    Select-Object TaskName,State

$port = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue

if ($port) {
    Write-Host "PORT_8501_FREE= NO"
} else {
    Write-Host "PORT_8501_FREE= YES"
}
```

Só continuar se:

```text
State = Ready
PORT_8501_FREE = YES
```

---

## 5. Atualizar código

```powershell
cd C:\Projetos\MoneyPrinterTurbo

git status
git fetch origin
git pull --ff-only origin main

git log -1 --oneline
git status --porcelain
```

Critérios:
- fast-forward
- HEAD esperado
- worktree clean

---

## 6. Regressão direcionada da V12-E

```powershell
.\.venv\Scripts\python.exe -m pytest `
  test/services/test_autonomous_production.py `
  test/services/test_operator_console.py `
  test/services/test_scheduler_worker.py `
  test/services/test_quality_score.py `
  test/services/test_single_instance.py `
  test/services/test_production_health.py `
  test/services/test_schedule_cancellation.py `
  -q
```

Baseline atual:

```text
197 passed
```

---

## 7. Iniciar produção

```powershell
Start-ScheduledTask -TaskName "VideoFactory Production"

Start-Sleep -Seconds 10

Get-ScheduledTask -TaskName "VideoFactory Production" |
    Select-Object TaskName,State
```

---

## 8. Health check

```powershell
$port = Get-NetTCPConnection -LocalPort 8501 -State Listen -ErrorAction SilentlyContinue

if ($port) {
    Write-Host "PORT_8501_LISTENING= YES"
} else {
    Write-Host "PORT_8501_LISTENING= NO"
}

try {
    $r = Invoke-WebRequest `
        -Uri "http://127.0.0.1:8501/_stcore/health" `
        -UseBasicParsing `
        -TimeoutSec 10

    Write-Host "HTTP=" $r.StatusCode
    Write-Host "BODY=" $r.Content
}
catch {
    Write-Host "HEALTH_ERROR=" $_.Exception.Message
}
```

Esperado:

```text
Running
PORT_8501_LISTENING= YES
HTTP= 200
BODY= ok
```

---

## 9. Confirmar PRIMARY

Consultar SQLite:

```powershell
cd C:\Projetos\MoneyPrinterTurbo

@'
import sqlite3
from pathlib import Path

db = Path(r"C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db")

with sqlite3.connect(f"file:{db}?mode=ro", uri=True) as conn:
    conn.row_factory = sqlite3.Row
    row = conn.execute(
        "SELECT * FROM instance_locks WHERE lock_key = 'PRIMARY_FACTORY'"
    ).fetchone()

    if row:
        d = dict(row)
        print("ROLE=", d.get("role"))
        print("STATUS=", d.get("status"))
        print("NODE=", d.get("node_name"))
        print("PID=", d.get("pid"))
        print("HEARTBEAT=", d.get("last_heartbeat"))
'@ | .\.venv\Scripts\python.exe -
```

Esperado:

```text
ROLE= PRIMARY
STATUS= ACTIVE
```

---

## 10. Verificar settings críticos

```powershell
cd C:\Projetos\MoneyPrinterTurbo

@'
from app.services import scheduler, autonomous_production

s = scheduler.get_all_settings()
a = autonomous_production.get_autonomous_status()

print("AUTONOMOUS=", a["autonomous_mode_enabled"])
print("CURRENT_TASK=", a["current_task_id"])
print("WAITING_TASK=", a["waiting_task_id"])
print("MAX_24H=", a["max_generations_24h"])

print("SCHEDULER=", s["scheduler_enabled"])
print("AUTO_PUBLISH=", s["auto_publish_enabled"])
print("DRY_RUN=", s["dry_run"])
print("YOUTUBE=", s["youtube_enabled"])
print("TIKTOK=", s["tiktok_enabled"])
print("GROWTH=", s["growth_mode"])
'@ | .\.venv\Scripts\python.exe -
```

---

## 11. Verificar se vídeo terminou

```powershell
cd C:\Projetos\MoneyPrinterTurbo

$taskId = "<TASK_ID>"
$taskDir = "C:\Projetos\MoneyPrinterTurbo\storage\tasks\$taskId"

$final = Get-ChildItem $taskDir -Filter "final-*.mp4" -File -ErrorAction SilentlyContinue
$ffmpeg = Get-Process -ErrorAction SilentlyContinue |
    Where-Object { $_.ProcessName -like "*ffmpeg*" }

if ($final) {
    $final | Select-Object Name,Length,LastWriteTime
} else {
    Write-Host "FINAL_VIDEO= NO"
}

Write-Host "FFMPEG_RUNNING=" ([bool]$ffmpeg)
```

Considerar finalizado apenas quando:
- `final-1.mp4` existe
- tamanho estabilizou
- `FFMPEG_RUNNING=False`

---

## 12. Regras do Autonomous

One-shot:
- pode executar com Autonomous Mode OFF
- deve fazer uma única transição operacional principal

Exemplos válidos:

```text
gerar → return
revisar → return
agendar → return
recovery → return
```

Nunca:

```text
rejeitar A
→ gerar B
no mesmo ciclo
```

---

## 13. Safety Gate

Autonomous aceita somente:

```text
PASS
```

Bloqueia:
- REVIEW
- BLOCK
- missing
- unknown
- error

---

## 14. Quality Gate

Mínimo:

```text
70
```

Labels permitidos:
- GOOD
- STRONG

Bloqueados:
- REVIEW
- WEAK

---

## 15. Scheduler / publicação

Scheduler é o único caminho automático.

MPT original:

```text
upload_post_auto_upload = OFF
```

Auto Publish do Scheduler é controlado por:

```text
auto_publish_enabled
```

Antes do gate final:
`False`

Após homologação PUBLIC:
pode ser `True`.

---

## 16. YouTube

Privacy esperada:
`public`

Gate final:
confirmar visualmente no YouTube Studio que uma publicação real do Scheduler ficou PUBLIC.

---

## 17. TikTok

Status:
NÃO homologado.

Config produção:
`False`

Motivo:
teste real anterior via Upload-Post retornou HTTP 400.

---

## 18. Growth Mode

Atual:
`warmup`

Nunca assumir slot disponível.

Consultar rate limits no momento da publicação.

---

## 19. Scheduled Tasks

Produção:
`VideoFactory Production`

Backup:
`VideoFactory Backup`

Backup agendado:
- 00:15
- 06:15
- 12:15
- 18:15

Retenção:
24 backups

---

## 20. Recovery

Nunca restaurar backup com backend ativo.

Fluxo seguro:

```text
stop produção
→ confirmar 8501 livre
→ validar backup
→ restaurar
→ iniciar produção
→ health
→ PRIMARY
```

---

## 21. MemoryState

Sem Redis:
- task state é process-local
- CLI Python separado não enxerga MemoryState do Streamlit

Não interpretar `TASK_NOT_FOUND` em processo externo como falha automática.

Usar:
- `storage\tasks\<task_id>`
- SQLite
- logs persistidos

---

## 22. Regra de documentação

Após qualquer deploy, hotfix, mudança de arquitetura, nova fase, alteração de gate ou mudança operacional, atualizar:

- `PROJECT_HANDOFF.md`
- `ROADMAP.md`
- `PRODUCTION_RUNBOOK.md`

Nunca salvar secrets, API keys, tokens ou conteúdo sensível de `config.toml`.
