# PRODUCTION_RUNBOOK — Video Factory

## V12-E.3 — contrato DEV, sem rollout autorizado

Esta etapa não acessou produção e não autoriza deploy, commit ou push.
Após eventual revisão e autorização separada, o comportamento esperado é:

- Uma task aprovada sem slot WARMUP conta no estoque e não impede reposição.
- Abaixo de 3, um ciclo elegível pode iniciar uma geração; com 3, não gera.
- Ciclo que revisa, recupera indicação inválida ou tenta agendar encerra nessa ação.
- Estoque é revalidado a partir de dados persistidos e vídeos locais; publicação,
  cancelamento, gates inválidos, perfil/canal inválido ou vídeo ausente excluem a task.
- `waiting_task_id` é apenas uma indicação; limpar/perder essa chave não perde a fila.
- Retry de agendamento sem resultado espera 15 minutos; falta de slot é verificada
  antes da tentativa e não bloqueia reposição. Eventos Growth repetidos da mesma
  task/perfil/plataforma/modo são limitados a um por 15 minutos, após restart também.
- Growth Mode, Auto Publish, Scheduler único publicador e TikTok OFF permanecem
  com o contrato anterior. Nenhuma migração nova ou alteração de configuração operacional.

Validação concluída exclusivamente DEV/offline: 600 testes + 32 subtestes passaram
em 23 suítes, zero falhas (246,12s). Comando reproduzível no handoff.
Próximo gate seguro: revisão do diff V12-E.3. Não misturar aprovação desta etapa
com ativação da V12-F.2; produção ainda não homologada para E.3.



## V12-F.1C — Publication Privacy Persistence (21/09/2026)

Implementação concluída **somente em desenvolvimento** (`D:\Projetos\MoneyPrinterTurbo`); nenhuma mudança em produção (`C:\Projetos\MoneyPrinterTurbo`) nesta tarefa; nenhum deploy realizado; nenhuma API real executada. Analytics Auto Collection permanece `OFF`.

Nova coluna `publication_events.privacy_status` (migração aditiva/idempotente) passa a ser a fonte primária de privacidade do YouTube para o Analytics automático e para a coleta manual (`fetch_real_metrics_for_publication`), com fallback legado para `task.json`. Nova operação auditável `confirm_publication_privacy_op` no Operator Console permite homologar eventos legados sem SQL manual — **não executada em produção nesta tarefa**. Regressão das suítes exigidas: 329 passed, 19 subtests passed, 0 failed. Detalhes em `PROJECT_HANDOFF.md` e `ROADMAP.md`.

---

## V12-F.1B — Headless Worker Bootstrap (21/09/2026)

**Status: ✅ HOMOLOGADA EM PRODUÇÃO. Headless gate PASS**, conforme evidências fornecidas pelo operador: Scheduled Task Running, HTTP 200/ok, heartbeat do PRIMARY avançou sem navegador, `executor_last_tick` avançou sem navegador. Estado operacional confirmado no gate: Autonomous OFF, Auto Publish OFF, Analytics Auto OFF. Produção em `d1a8677`. Backup pré-deploy: `video_factory_20260921_044508.db`, SHA-256 `2f20ae0e7814f5b8745b5025d8ba6b49073e1cfb50e042d7d631f934506a1e52`, integridade `ok`.

`scripts/start_production.ps1` agora invoca `scripts/production_entrypoint.py` em vez de `python -m streamlit run` diretamente. O entrypoint garante, no MESMO processo que hospedará o Streamlit: inicialização do PRIMARY guard (`operator_console.ensure_instance_initialized`) e, se PRIMARY, início do `SchedulerExecutionWorker` — antes de qualquer navegador conectar. Isso corrige o bloqueador registrado na V12-F.1A (worker dependente de sessão Streamlit ativa). Parâmetros operacionais (address, port, headless, CORS, toolbar, usage stats) preservados. Regressão: 349 passed, 19 subtests passed, 0 failed. Detalhes em `PROJECT_HANDOFF.md` e `ROADMAP.md`.

---

## V12-F.1A — Analytics Activation Hardening (21/09/2026)

Implementação concluída **somente em desenvolvimento** (`D:\Projetos\MoneyPrinterTurbo`); nenhuma mudança em produção (`C:\Projetos\MoneyPrinterTurbo`) nesta tarefa. Analytics Auto Collection permanece `OFF`. Regressão: 338 passed, 19 subtests passed, 0 failed. Detalhes em `PROJECT_HANDOFF.md` e `ROADMAP.md`.

Bloqueador identificado (corrigido pela V12-F.1B, ver seção acima): o worker do scheduler dependia de uma sessão Streamlit ativa; após reboot sem navegador conectado, nada iniciava automaticamente.

---

## Steady-state homologado — 21/09/2026

V12-E HOMOLOGADA EM PRODUÇÃO; PUBLIC GATE PASS. Produção em `d1a8677` (atualizada após homologação da V12-F.1B); `de62a4b` é governança de agentes e não foi necessário ao deploy de homologação. Evidências completas no [PROJECT_HANDOFF](PROJECT_HANDOFF.md).

```text
Factory RUNNING
Autonomous ON
Scheduler ON
Auto Publish ON
Dry Run OFF
YouTube ON
TikTok OFF
Growth Mode WARMUP
MPT Auto Upload OFF
```

O operador confirmou PUBLIC no YouTube Studio para `fTrkUqSnYqs` (task `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`; scheduled post 15; publication event 16/success). Operação contínua habilitada. Esta tarefa somente registra o estado informado; não executa deploy nem altera settings.

### Retornar ao modo supervisionado

Em intervenção autorizada, usar os controles existentes no Operator Console da instância PRIMARY para desativar **Autonomous Production** e **Auto Publish**. Confirmar ambos persistidos como OFF pela verificação de settings da seção 10.

```text
Autonomous OFF
Auto Publish OFF
```

Não presumir cancelamento de geração ou publicação já em andamento: verificar tarefas/worker antes de manutenção. Manter TikTok OFF, MPT Auto Upload OFF, Safety/Quality Gates, WARMUP e Single PRIMARY. One-shot pode ser usado com Autonomous OFF, respeitando uma transição por ciclo; publicação real exige autorização explícita. Para update, seguir backup e parada abaixo. Retomada contínua exige decisão operacional explícita após verificações.

V12-F aberta somente para planejamento. Não ativar Analytics, conectar o segundo canal ou iniciar sua operação automática por conta desta atualização documental.

---

## V12-E.2.2 — Persistent Waiting Schedule Recovery (20/09/2026)

Hotfix V12-E.2.2 deployado e homologado em produção em 21/09/2026 com a aplicação em `66f92a4`. V12-E concluída; PUBLIC GATE = PASS, conforme evidências fornecidas pelo operador.

Causa raiz confirmada: após perda do MemoryState, WAITING_SCHEDULE enviava apenas `task_id`. O scheduler descartava o payload sem COMPLETE ou `video_file`, antes de resolver os destinos persistidos.

Correção: o retry verifica vídeo final existente e não vazio via `get_task_final_video()`, Safety PASS explícito, último Quality finito >= 70 com label GOOD/STRONG, YouTube em `task_platforms`, vínculo em `task_profiles`, perfil ativo e canal YouTube habilitado. Reconstrói o payload quando a memória está ausente/incompleta e preserva vetos de estado presentes em memória. Reutiliza o scheduler para Growth Mode e deduplicação por task/canal; envia somente YouTube.

Recuperação inválida mantém WAITING_SCHEDULE com `reason=waiting_recovery_failed` e diagnóstico na mensagem. Sem slot, permanece em espera; sucesso agenda e retorna. Nenhum desses caminhos gera outra task no mesmo ciclo. Auto Publish, TikTok, MPT Auto Upload, schema e thresholds de produção permanecem inalterados.

Validação: **234 testes + 19 subcasos PASS** nas oito suítes abaixo. Cenários novos: memória presente/ausente/incompleta, vídeo ausente/vazio, Safety BLOCK/REVIEW/ausente, Quality ausente/baixo/label inválido, perfil/canal/destino inválidos, slot WARMUP ocupado, idempotência e destinos terminais, one_shot com Autonomous OFF, nenhuma nova geração, Auto Publish OFF e exclusão de TikTok. Publicação é interceptada por mocks e conexões externas são bloqueadas nos novos retries. Sete testes legados do scheduler agora declaram SCALE apenas no SQLite temporário para verificar tetos técnicos; Growth Mode de produção não mudou.

```powershell
.venv/Scripts/python.exe -m pytest test/services/test_autonomous_production.py test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_quality_score.py test/services/test_operator_console.py test/services/test_single_instance.py test/services/test_schedule_cancellation.py test/services/test_production_health.py -q -p no:cacheprovider
```

Recuperação persistida homologada com publicação PUBLIC. Em futuros casos sem slot, aguardar Growth Mode; em `waiting_recovery_failed`, inspecionar o diagnóstico sem forçar COMPLETE nem limpar o waiting ID. Próximo passo: planejar a auditoria V12-F.1, sem alterar produção nesta tarefa.

---

**Atualizado em:** 21/09/2026

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
  test/services/test_scheduler.py `
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
234 passed
19 subtests passed
0 failed
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

Steady-state homologado: `True` (ON).

Modo supervisionado/manutenção: `False` (OFF), junto de Autonomous OFF.

---

## 16. YouTube

Privacy esperada:
`public`

Gate final da V12-E: PASS, com visibilidade PÚBLICO confirmada no YouTube Studio para `fTrkUqSnYqs`. O segundo canal exige nova publicação supervisionada e confirmação PUBLIC antes de operação contínua.

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
