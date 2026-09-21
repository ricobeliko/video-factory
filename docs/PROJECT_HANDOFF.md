# PROJECT_HANDOFF — Video Factory / MoneyPrinterTurbo


## V12-E.2.2 ? Persistent Waiting Schedule Recovery (20/09/2026)

Hotfix validado localmente; deploy de produ??o ainda n?o realizado. V12-E permanece em homologa??o: o gate real PUBLIC no YouTube continua pendente.

Causa raiz confirmada no c?digo: ap?s perda do MemoryState, o retry de WAITING_SCHEDULE enviava apenas `task_id`. `scheduler.plan_schedule()` descartava esse payload por aus?ncia de estado COMPLETE ou `video_file`, antes de resolver os destinos persistidos.

Corre??o: o retry revalida v?deo final existente e n?o vazio via `get_task_final_video()`, Safety PASS expl?cito, ?ltimo Quality finito >= 70 com label GOOD/STRONG, destino YouTube em `task_platforms`, v?nculo em `task_profiles`, perfil ativo e canal YouTube habilitado. Reconstr?i o payload m?nimo quando a mem?ria est? ausente/incompleta; preserva os vetos de estado presentes em mem?ria. Reutiliza o scheduler para Growth Mode e deduplica??o por task/canal. O payload ? restrito a YouTube.

Falha de recupera??o mant?m WAITING_SCHEDULE com `reason=waiting_recovery_failed` e diagn?stico na mensagem. Sem slot, permanece em espera. Sucesso agenda e retorna. Nenhum desses caminhos gera outra task no mesmo ciclo. Auto Publish, TikTok, MPT Auto Upload, schema e thresholds de produ??o n?o foram alterados.

Valida??o: **234 testes + 19 subcasos PASS** nas oito su?tes solicitadas:
`test_autonomous_production.py`, `test_scheduler.py`, `test_scheduler_worker.py`, `test_quality_score.py`, `test_operator_console.py`, `test_single_instance.py`, `test_schedule_cancellation.py`, `test_production_health.py` (todas em `test/services/`).

Os novos testes cobrem mem?ria presente/ausente/incompleta, v?deo ausente/vazio, Safety BLOCK/REVIEW/ausente, Quality ausente/baixo/label inv?lido, perfil/canal/destino inv?lidos, slot WARMUP realmente ocupado, repeti??o e destinos terminais, one_shot com Autonomous OFF, aus?ncia de nova gera??o e Auto Publish OFF. Publica??o ? interceptada por mocks e conex?es externas s?o bloqueadas nos novos retries. Sete testes legados do scheduler passaram a declarar SCALE apenas no SQLite tempor?rio para testar seus tetos t?cnicos, sem modificar Growth Mode de produ??o.

Comando de regress?o:

```powershell
.venv/Scripts/python.exe -m pytest test/services/test_autonomous_production.py test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_quality_score.py test/services/test_operator_console.py test/services/test_single_instance.py test/services/test_schedule_cancellation.py test/services/test_production_health.py -q -p no:cacheprovider
```

---

**Data de referência:** 20/09/2026

**Projeto:** Video Factory baseado em MoneyPrinterTurbo v1.3.7

**Objetivo:** deixar o PC forte operando como fábrica autônoma 24/7 com geração, Safety/Quality Gates, Scheduler, publicação pública no YouTube e feedback por Analytics.

---

## 1. Objetivo operacional

Fluxo desejado:

Trend / Strategy
→ seleção de tema
→ criação da task
→ roteiro
→ TTS
→ materiais
→ render
→ Safety Gate
→ Quality Score
→ Scheduler
→ Growth Mode
→ publicação pública no YouTube
→ Analytics
→ feedback para estratégia
→ manutenção automática de estoque

Princípio do projeto:

**segurança e monetização > volume**

TikTok não deve entrar em produção automática até homologação separada.

---

## 2. Ambientes

### Notebook / desenvolvimento
`D:\Projetos\MoneyPrinterTurbo`

### PC forte / produção
`C:\Projetos\MoneyPrinterTurbo`

### GitHub
`https://github.com/ricobeliko/video-factory.git`

### Upstream
`https://github.com/harry0703/MoneyPrinterTurbo.git`

### Produção
- Windows 10 Pro x64
- Python 3.11
- MoneyPrinterTurbo v1.3.7
- Streamlit na porta `8501`
- bind `0.0.0.0`
- Scheduled Task: `VideoFactory Production`
- Tailscale PC forte: `100.123.12.51`
- LAN: `192.168.1.103`

O PC forte é a autoridade de:
- SQLite
- workers
- scheduler
- geração
- publicação
- Operator Console

Notebook/celular/outros PCs são clientes via navegador.

---

## 3. Single Instance

Papéis:
- `PRIMARY`
- `SECONDARY_VIEW_ONLY`

Lock:
- `PRIMARY_FACTORY`

Heartbeat:
- aproximadamente 15s

Timeout stale:
- aproximadamente 90s

---

## 4. Roadmap atual

- Base MPT v1.3.7 ✅
- Publicação manual ✅
- Batch ✅
- V2.1 Scheduler ✅
- V2.2 Scheduler Execution Engine ✅
- V3 Monetization Presets + Safety Gate ✅
- V3.1 Growth Mode ✅
- V4 Trend Radar ✅
- V5 Analytics + Feedback Loop ✅
- V6 Quality Score ✅
- V7 Content Strategy ✅
- V8 Operator Console ✅
- V8.1 Single Instance / acesso remoto ✅
- V9 Multi-profile / multi-channel ✅
- V10 Analytics Providers ✅
- V11 Clip Mode ✅
- V12 Production Host / Startup / Backup / Recovery ✅
- V12-D cancelamento terminal ✅
- V12-D.1 PRIMARY guard ✅
- V12-D.2 legacy cancellation compatibility ✅
- V12-E Autonomous Production Loop — **em homologação real**
- V12-E.2.1 One-cycle / One-transition hotfix — **deploy concluído e em teste real**

Próximas fases planejadas:
- V13 Headless Remote Deployment / Safe Update
- V14 Virtual Presenter / Character Narrator

---

## 5. Commits importantes

- `46739bf` — preserve legacy terminal cancellations across channel migration
- `866589a` — add autonomous production loop
- `4bbc39a` — harden autonomous production safety and recovery
- `bd6b568` — align autonomous provider and stock eligibility contracts
- `506abb3` — align autonomous generation with persisted production config
- `08c644f` — enforce one autonomous transition per cycle

### Commit atual em produção
`08c644f`

---

## 6. Configuração segura atual

Estado confirmado antes do teste atual:

- Factory: `RUNNING`
- Primary: `ACTIVE`
- Scheduler: `ON`
- Auto Publish: `OFF`
- Dry Run: `OFF`
- Growth Mode: `warmup`
- YouTube: `ON`
- TikTok: `OFF`
- Autonomous Mode: `OFF`
- MPT Auto Upload: `OFF`
- YouTube privacy: `public`
- Autonomous max generations / 24h: `5`

---

## 7. Backup mais recente

Criado antes do deploy do hotfix:

`video_factory_20260920_143053.db`

Path:
`C:\Projetos\MoneyPrinterTurbo\storage\backups\database\video_factory_20260920_143053.db`

Tamanho:
`540672 bytes`

SHA-256:
`ba5c09fbba6391dc5fe499b5db90d99e8a2a575a34358add77a061b8c9ee779c`

Integridade:
`ok`

---

## 8. Testes do hotfix em produção

Após deploy do `08c644f` no PC forte:

```text
197 passed in 76.49s
```

Arquivos cobertos no gate direcionado:
- `test_autonomous_production.py`
- `test_operator_console.py`
- `test_scheduler_worker.py`
- `test_quality_score.py`
- `test_single_instance.py`
- `test_production_health.py`
- `test_schedule_cancellation.py`

---

## 9. Bug real encontrado na V12-E

### Comportamento antigo

Ao revisar uma task rejeitada:

```text
rejeitar A
→ continuar o mesmo ciclo
→ detectar estoque baixo
→ gerar B
```

Também existia fall-through em recovery.

### Causa raiz

Dois caminhos sem `return` em `run_autonomous_cycle()`:

1. rejection path
2. recovery path

### Correção

Nova regra:

**UM CICLO AUTÔNOMO = UMA TRANSIÇÃO OPERACIONAL PRINCIPAL**

Exemplos:

```text
Ciclo 1 → gera A → return
Ciclo 2 → revisa A → approved/rejected/waiting → return
Ciclo 3 → se estoque baixo → gera B → return
```

Commit:
`08c644f`

---

## 10. Primeiro vídeo autônomo real

Task:
`42c06135-d12f-475c-a0b1-16d23000f42c`

Tema:
`A Fazenda 18: conheça Lucas Bissoli, ex-BBB e participante do reality`

Safety:
`PASS`

Quality:
`45.0 / WEAK`

Resultado:
`task_gate_rejected`

Motivos principais:
- alta repetição com conteúdo recente
- aderência moderada ao nicho
- risco alto de repetição
- potencial visual genérico

Nenhum schedule criado.

---

## 11. Segundo vídeo autônomo real

Task:
`26a5ccbf-cf83-40f9-b2fa-748ddfa5d88a`

Tema:
`fran da fazenda`

Safety:
`BLOCK`

Motivo:
`Duração de 59.0s abaixo do mínimo de 60s para YouTube + TikTok Monetization`

Quality:
não executado, porque Safety bloqueou antes.

Resultado:
- rejeitado
- sem schedule
- sem publicação

Esse teste foi executado ainda no código antigo, com limite temporário `2/2`, impedindo uma terceira geração no mesmo ciclo.

---

## 12. Hotfix V12-E.2.1

Commit:
`08c644feb9677c4b3dd7567f50755ce7139da44c`

Mensagem:
`fix: enforce one autonomous transition per cycle`

Resultados:
- 10 novos testes específicos
- regressão total direcionada: `197/197 PASS`
- deploy no PC forte concluído
- worktree clean
- health HTTP 200
- PRIMARY ativo

---

## 13. Teste real atual do hotfix

Após deploy do `08c644f`, foi feito um novo one-shot.

Resultado da primeira transição:

```text
Modo Autônomo: OFF
Estado: GENERATING
Estoque: 0 / 3
Gerados 24h: 3 / 5
```

Nova task:

`fdb20c65-76b2-42cc-9c0f-a1764f7237e0`

Tema:

`Curiosidades para celebrar Dia Internacional do maior roedor do mundo`

Estado atual:
**vídeo em geração**

Não clicar em `Run Cycle` enquanto estiver gerando.

---

## 14. Próximo gate quando a task atual terminar

Depois de confirmar:

```text
final-1.mp4 existe
FFMPEG_RUNNING=False
```

executar **um único** `Run Cycle`.

Com o `08c644f`, o resultado esperado é:

### Se aprovado
```text
Safety PASS
Quality >= 70
→ scheduled ou waiting_schedule
→ return
```

### Se rejeitado
```text
Safety/Quality rejeita
→ status=rejected
→ return
```

### Regra decisiva
**NÃO pode nascer uma quarta task no mesmo clique.**

Esse é o teste real que fecha o hotfix.

---

## 15. Gate final da V12-E

Ainda falta comprovar:

1. uma task com:
   - Safety PASS
   - Quality >= 70
   - GOOD ou STRONG

2. entrada no Scheduler

3. publicação real pelo caminho:

```text
Autonomous
→ Scheduler
→ worker
→ YouTube
```

4. confirmar visualmente no YouTube Studio que o vídeo ficou:

`PUBLIC`

Somente depois disso:

- Auto Publish pode ser ligado
- Autonomous contínuo pode ser ligado

Steady state desejado:

```text
Factory RUNNING
Scheduler ON
Auto Publish ON
Dry Run OFF
Growth Mode WARMUP
YouTube PUBLIC
MPT Auto Upload OFF
Autonomous ON
TikTok OFF
```

---

## 16. Regras importantes

Não usar:
- `git reset`
- `git restore`
- `git clean`

Não instalar Playwright.

Não ativar MPT Auto Upload.

Não ativar TikTok automaticamente.

Não usar API real em testes unitários.

Sempre parar produção antes de `git pull`.

Usar:

`.\.venv\Scripts\python.exe`

porque a ativação PowerShell do venv pode ser bloqueada por ExecutionPolicy.

---

## 17. Publicação

Existem duas rotas:

### Scheduler
`auto_publish_enabled`

### MPT original
`upload_post_auto_upload`

Regra:
**MPT Auto Upload permanece OFF.**

Scheduler é o único caminho automático.

YouTube privacy:
`public`

---

## 18. Growth Mode

Atual:
`warmup`

Historicamente, YouTube warmup:
- 1 publicação / 24h
- intervalo mínimo de 8h

Nunca assumir slot disponível.
Sempre consultar rate limits no momento da publicação.

---

## 19. TikTok

Infra existe, porém teste real anterior retornou HTTP 400 no Upload-Post.

Portanto:
**TikTok ainda não está homologado.**

Permanece OFF.

---

## 20. State / MemoryState

Quando Redis está desabilitado, o MPT usa `MemoryState`.

Portanto um `python.exe` separado não enxerga as tasks em memória do processo Streamlit.

`sm.state.get_task(task_id)` em outro processo pode retornar `TASK_NOT_FOUND` mesmo com task válida.

Para observação entre processos usar:
- arquivos físicos em `storage\tasks\<task_id>`
- settings persistidos em SQLite

---

## 21. Ideia futura — V14 Virtual Presenter

Conceito aprovado:

Adicionar personagem que narra/lê a legenda.

Modos:

- `none`
- `corner`
- `hybrid`
- `full`

Preferência inicial:
**Hybrid Presenter**

Campos possíveis:
- `avatar_provider`
- `avatar_character_id`
- `avatar_position`
- `avatar_scale`
- `avatar_opacity`

Métricas futuras:
- `lip_sync_score`
- `subtitle_sync_score`
- `presenter_visibility_score`
- `presenter_overlap_score`
- `narration_coverage_score`

Default:
`avatar_mode=none`

Não implementar antes de fechar V12-E.

---

## 22. Prioridade imediata

Prioridade atual:

**fechar a homologação real da V12-E**

Ordem:

1. esperar a task `fdb20c65-76b2-42cc-9c0f-a1764f7237e0` terminar
2. confirmar final + FFmpeg encerrado
3. executar um único Run Cycle
4. comprovar que o ciclo apenas revisa e retorna
5. obter um vídeo Safety PASS + Quality >=70
6. Scheduler
7. publicação real PUBLIC no YouTube
8. ativar operação contínua
9. atualizar este handoff novamente

---

## 23. Convenção de documentação

Manter no projeto:

```text
docs/
├── PROJECT_HANDOFF.md
├── ROADMAP.md
├── PRODUCTION_RUNBOOK.md
└── DOCUMENTATION_POLICY.md
```

O `PROJECT_HANDOFF.md` deve ser atualizado ao final de cada fase importante.
