# ROADMAP — Video Factory / MoneyPrinterTurbo


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

**Atualizado em:** 20/09/2026

**Projeto:** Video Factory

**Base:** MoneyPrinterTurbo v1.3.7

---

## Visão do produto

Objetivo final: operar uma fábrica de vídeos curtos 24/7 no PC forte, com seleção de temas, geração, validação, agendamento, publicação pública no YouTube, coleta de analytics e realimentação da estratégia.

Princípio central:

> Segurança, qualidade e monetização têm prioridade sobre volume.

---

## Fases concluídas

- Base / Fundação ✅
- Publicação manual ✅
- Batch controlado ✅
- V2.1 Scheduler ✅
- V2.2 Scheduler Execution Engine ✅
- V3 Monetization Presets + Safety Gate ✅
- V3.1 Account Warm-Up / Growth Mode ✅
- V4 Trend Radar ✅
- V5 Analytics + Feedback Loop ✅
- V6 Quality Score ✅
- V7 Content Strategy / Optimization Engine ✅
- V8 Production Readiness / Operator Console ✅
- V8.1 Remote Operation & Single-Instance Safety ✅
- V9 Multi-Profile / Multi-Channel Management ✅
- V10 Automatic Analytics Providers ✅
- V11 Clip Mode / Long-form Repurposing ✅
- V12-A Production Host ✅
- V12-B Production Startup ✅
- V12-C Backup / Recovery ✅
- V12-D Schedule Cancellation Safety ✅
- V12-D.1 PRIMARY Guard ✅
- V12-D.2 Legacy Cancellation Compatibility ✅

---

# V12-E — Autonomous Production Loop

**Status:** 🟡 homologação real em produção

Objetivo:
- detectar déficit de estoque
- selecionar tema
- gerar vídeo
- aplicar Safety Gate
- aplicar Quality Score
- abastecer Scheduler
- respeitar Growth Mode
- nunca publicar diretamente
- operar fail-closed

Regras atuais:
- Autonomous Mode default OFF
- máximo de 1 nova geração por ciclo
- máximo de 5 gerações / 24h
- intervalo normal de 15 min
- estoque-alvo: 3
- Quality mínimo: 70
- apenas GOOD / STRONG
- Safety precisa ser PASS explícito
- fontes autônomas permitidas: Pexels, Pixabay, Coverr
- TikTok bloqueado nesta fase

### V12-E.1 — Hardening
Status: ✅ concluído

### V12-E.1.1 — Provider / Stock Contract
Status: ✅ concluído

### V12-E.1.2 — Generation Config Contract
Status: ✅ concluído

### V12-E.2 — Homologação real
Status: 🟡 em andamento

### V12-E.2.1 — One-cycle / One-transition Hotfix

Commit:
`08c644feb9677c4b3dd7567f50755ce7139da44c`

Status:
- ✅ implementado
- ✅ 197/197 testes PASS no PC forte
- ✅ deploy realizado
- 🟡 teste real final em andamento

Regra consolidada:

> Um ciclo autônomo deve executar apenas uma transição operacional principal.

---

## Teste real atual

Task em geração:

`fdb20c65-76b2-42cc-9c0f-a1764f7237e0`

Tema:

`Curiosidades para celebrar Dia Internacional do maior roedor do mundo`

Estado:
`GENERATING`

Generated 24h:
`3 / 5`

Autonomous Mode:
`OFF`

Auto Publish:
`OFF`

TikTok:
`OFF`

Próximo gate:
1. esperar geração finalizar
2. confirmar `final-1.mp4`
3. confirmar FFmpeg encerrado
4. executar 1 Run Cycle
5. comprovar que o ciclo apenas revisa e retorna
6. garantir que não nasce uma quarta task no mesmo clique

---

## Gate final da V12-E

Para declarar V12-E homologada:

1. Task real com Safety PASS
2. Quality >= 70
3. Label GOOD ou STRONG
4. Entrada correta no Scheduler
5. Publicação real pelo Scheduler
6. Confirmar no YouTube Studio que o vídeo está PUBLIC
7. Confirmar que MPT Auto Upload permanece OFF
8. Confirmar TikTok OFF
9. Ativar Autonomous contínuo
10. Observar pelo menos um ciclo automático completo sem intervenção

Steady state esperado:

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

# V13 — Headless Remote Deployment / Safe Update

**Status:** 🔵 planejado

Objetivo:
- atualizar produção sem monitor físico
- deploy remoto controlado
- backup antes de update
- stop seguro
- pull `--ff-only`
- regressão direcionada
- start
- health checks
- rollback seguro
- zero interação física no PC forte

Possíveis entregáveis:
- `scripts/update_production.ps1`
- gate de worktree clean
- backup automático
- validação do commit alvo
- teste pós-deploy
- rollback documentado

Não iniciar antes de fechar V12-E.

---

# V14 — Virtual Presenter / Character Narrator

**Status:** 🔵 planejado

Objetivo:
adicionar personagem/apresentador virtual sincronizado com a narração.

Modos previstos:

```text
none
corner
hybrid
full
```

Preferência inicial:
`hybrid`

Campos previstos:

```text
avatar_mode
avatar_provider
avatar_character_id
avatar_position
avatar_scale
avatar_opacity
```

Métricas previstas:

```text
lip_sync_score
subtitle_sync_score
presenter_visibility_score
presenter_overlap_score
narration_coverage_score
```

Default:
`avatar_mode=none`

Requisito:
não quebrar o pipeline atual quando Presenter estiver desativado.

---

## Regra de evolução

Toda nova fase deve:
- ter escopo fechado
- ter critérios de aceite
- ter testes
- passar regressão adequada
- atualizar `PROJECT_HANDOFF.md`
- atualizar este `ROADMAP.md`
- atualizar `PRODUCTION_RUNBOOK.md` se alterar operação
- não ativar produção automaticamente
- não mudar TikTok sem homologação explícita
- não enfraquecer Safety / Quality / Growth Mode
