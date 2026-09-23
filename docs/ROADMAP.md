# ROADMAP — Video Factory / MoneyPrinterTurbo

## Política atual de validação

- Testes massivos registrados em fases antigas são EVIDÊNCIA HISTÓRICA, não obrigação futura.
- Menções antigas a "regressão de 22 suítes", centenas de testes ou full regression NÃO são gates automáticos.
- Validação padrão atual = teste direcionado mínimo.
- Full regression exige autorização humana explícita.
- Esta política prevalece sobre registros históricos de validação de fases anteriores.

## V12-E.3 — gate DEV controlado — 21/09/2026

Hardening independente da V12-F.2: estoque YouTube recuperável por persistência,
fila de múltiplas aprovações e seleção de uma ação por ciclo. WARMUP sem slot
permite reposição até a meta 3, mantendo uma geração/ciclo e cinco/24h.
Deduplicação persistente de eventos Growth e cooldown de retry de 15 minutos.
Sem mudança de schema, Growth Mode, Auto Publish, publicação direta ou TikTok.

Implementação e validação DEV concluídas: **600 testes + 32 subtestes passaram**
em 23 suítes (246,12s), com geração fake e rede bloqueada; 16 testes novos E.3.
Próximo gate: revisão do diff E.3 isolado.
Sem commit/push/deploy e sem acesso à produção. A fase V12-F.2 permanece separada.

## Estado vigente — 21/09/2026

V12-E e V12-F.1A/B/C HOMOLOGADAS EM PRODUÇÃO na baseline `54875c6`, conforme
evidências do operador. YouTube Data API, fetch e persistência real homologados.
Factory/PRIMARY headless/Scheduler ativos; Autonomous ON, Auto Publish ON,
Analytics Auto ON (1 fetch/ciclo, 300s), Dry Run OFF, YouTube ON, TikTok OFF,
Growth Mode WARMUP e MPT Auto Upload OFF. Produção não acessada nesta implementação.

V12-F.2: implementação DEV em validação; sem deploy/homologação de produção.
Escopo MVP: tema/cluster e narrative_structure. Flag default OFF.
Reutiliza Analytics → evidência isolada → Content Strategy → Autonomous → VideoParams;
12 publicações, cinco por grupo, dois grupos; coorte 72–96h, histórico 60 dias;
medianas, estabilidade leave-one-out, bônus máximo cinco, diversidade persistida e
auditoria transacional. Não usa performance_score legado para eleger vencedores.
Schema NONE. Rollback funcional pela flag; nenhum histórico é removido.

Aceite DEV: testes de elegibilidade/privacidade/scope, gate, outlier, replay,
diversidade/restart, equivalência OFF, fail-safe e integração com submissão fake;
regressão das 22 suítes requeridas com rede bloqueada. Resultado final pendente da execução.
Próximos gates: revisão → autorização de deploy com flag OFF → homologação separada
→ autorização explícita de ativação. V12-F.3 mantém isolamento multicanal como fase formal;
V12-F.4/segundo canal e TikTok não são ativados por esta entrega.

Os marcos abaixo preservam histórico; snapshots OFF e baselines antigas não substituem
o estado vigente desta seção.


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
- V12-E Autonomous Production Loop ✅ — homologada em produção; PUBLIC GATE PASS

---

# V12-E — Autonomous Production Loop

**Status:** ✅ HOMOLOGADA EM PRODUÇÃO — 21/09/2026

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
Status: ✅ homologada em produção

### V12-E.2.1 — One-cycle / One-transition Hotfix

Commit:
`08c644feb9677c4b3dd7567f50755ce7139da44c`

Status:
- ✅ implementado
- ✅ 197/197 testes PASS no PC forte
- ✅ deploy realizado
- ✅ homologação real concluída

Regra consolidada:

> Um ciclo autônomo deve executar apenas uma transição operacional principal.

---

## Homologação V12-E em produção — 21/09/2026

**V12-E HOMOLOGADA EM PRODUÇÃO. PUBLIC GATE = PASS.** Registro baseado nas evidências fornecidas pelo operador; nenhuma consulta ou alteração de produção nesta tarefa documental.

Produção atualizada para `66f92a4` antes da homologação. Commits: `fd57f84` (hotfix funcional V12-E.2.2), `66f92a4` (documentação/encoding), `de62a4b` (governança de agentes, sem necessidade de deploy para validar a aplicação).

Backup pré-deploy: `video_factory_20260921_014133.db`.
SHA-256: `79313b694f54000b57d704eadfc8a6e5b1871ac5198e95006ef4890cd82f44a5`.
Integridade: `ok`. Regressão em produção: **234 passed; 19 subtests passed; 0 failed**.

Task: `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`; Safety PASS; Quality 78.3; label GOOD.
Sem slot, permaneceu corretamente em WAITING_SCHEDULE. Após abertura de slot e deploy do hotfix, a task foi recuperada, sem geração indevida; `waiting_task_id` foi limpo e a task entrou no Scheduler.

| Evidência | Resultado |
| --- | --- |
| Scheduled Post | id=15; platform=youtube; profile_id=default; channel_id=channel-default-youtube |
| Estado final | published; attempts=0; last_error=None |
| Publication Event | id=16; status=success; platform=youtube |
| external_id | fTrkUqSnYqs |
| provider_request_id | 9f5c57e089314532a686492a47a74690 |
| external_url | https://www.youtube.com/watch?v=fTrkUqSnYqs |
| Gate visual | YouTube Studio confirmou VISIBILIDADE = PÚBLICO |

Fluxo real validado: Autonomous Production → geração → Safety Gate → Quality Gate → WAITING_SCHEDULE → recuperação persistida → Scheduler → Worker → Upload-Post → YouTube → PUBLIC.

Estado operacional atual: Factory RUNNING; Scheduler ON; Auto Publish ON; Dry Run OFF; YouTube ON; TikTok OFF; Growth Mode WARMUP; Autonomous Production ON; MPT Auto Upload OFF. Produção em modo autônomo contínuo.

Próxima fase: **V12-F — Adaptive Learning + Multi-Channel Warm-Up**, somente planejamento nesta tarefa. Existe feedback parcial; o closed loop automático ainda precisa ser homologado. V13 e V14 permanecem posteriores.

---

# V12-F — Adaptive Learning + Multi-Channel Warm-Up

**Status: planejamento formal aberto; nenhuma implementação nesta tarefa.**

Objetivo: transformar o feedback de desempenho em um ciclo fechado de otimização, sem treinamento de pesos do modelo e sem sacrificar segurança, diversidade ou controle por canal.

## V12-F.1 — Analytics Auto-Collection Audit & Activation

**Status: HOMOLOGADA EM PRODUÇÃO.** V12-F.1A/B/C, fetch e persistência real homologados pelo operador em 21/09/2026; Analytics Auto ON na baseline `54875c6`.

Objetivo concluído: coleta automática de Analytics auditada, ativada e homologada.

Contratos da homologação:
- `analytics_scheduler.py`, integração do worker e settings atuais;
- `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED`;
- persistência de métricas e cooldowns por idade do vídeo;
- comportamento após reboot e nenhuma chamada duplicada;
- nenhuma coleta de vídeos privados;
- isolamento por profile/channel.

Gate F.1: PASS conforme evidências do operador. A implementação F.2 não altera essa ativação.

### V12-F.1A — Analytics Activation Hardening

**Status: ✅ HOMOLOGADA EM PRODUÇÃO (21/09/2026), baseline `54875c6`. Analytics Auto ON.**

Endureceu sete contratos em `analytics_scheduler.py` e `analytics_providers/*`: coleta automática restrita a YouTube; privacidade fail-closed (PUBLIC comprovado exigido; PRIVATE/UNKNOWN bloqueiam); deduplicação/revalidação de elegibilidade antes de cada chamada ao provider; exclusão mútua entre ciclo manual e automático via lock persistido; revalidação de backoff por publicação antes de cada fetch; sanitização de erros de rede/HTTP para nunca expor API key/token/query; `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED` como fonte real do default. Regressão: 338 passed, 19 subtests passed, 0 failed. Detalhes completos em `PROJECT_HANDOFF.md`.

### V12-F.1B — Headless Worker Bootstrap

**Status: ✅ implementada e HOMOLOGADA em produção (21/09/2026). Headless gate PASS.**

Bloqueador identificado durante V12-F.1A corrigido: `scripts/production_entrypoint.py` agora inicializa `operator_console.ensure_instance_initialized()` e, se PRIMARY, `scheduler.start_scheduler_worker(interval_seconds=30)` no MESMO processo que hospedará o Streamlit (`streamlit.web.bootstrap.load_config_options` + `.run`), antes de qualquer sessão de navegador conectar. `scripts/start_production.ps1` passou a chamar esse entrypoint em vez de `streamlit run` diretamente, preservando os mesmos parâmetros operacionais. SECONDARY nunca inicia o worker; shutdown libera worker e lock de forma idempotente. Regressão: 349 passed, 19 subtests passed, 0 failed. Gate headless homologado com evidências do operador: Scheduled Task Running, HTTP 200/ok, heartbeat do PRIMARY e `executor_last_tick` avançando sem navegador. Produção em `d1a8677`. Detalhes completos em `PROJECT_HANDOFF.md`.

### V12-F.1C — Publication Privacy Persistence

**Status: ✅ HOMOLOGADA EM PRODUÇÃO (21/09/2026), baseline `54875c6`. Analytics Auto ON.**

Cria fonte persistente e auditável de `privacy_status` em `publication_events` (migração aditiva/idempotente) e faz todos os caminhos de Analytics YouTube respeitarem essa evidência: publicação futura persiste o `privacyStatus` efetivamente usado; elegibilidade do Analytics automático prioriza o valor persistido com fallback legado para `task.json`, mantendo fail-closed (PRIVATE/UNLISTED/UNKNOWN bloqueiam); coleta manual (`fetch_real_metrics_for_publication`) agora exige PUBLIC comprovado antes de qualquer requisição real, para `persist=False` e `persist=True`; nova operação auditável `confirm_publication_privacy_op` no Operator Console permite homologar eventos legados (ex.: evento real 16) sem SQL manual, exigindo PRIMARY e validação exata do evento. Regressão das suítes exigidas: 329 passed, 19 subtests passed, 0 failed. Detalhes completos em `PROJECT_HANDOFF.md`.

## V12-F.2 — Closed Feedback Loop

Fluxo desejado: YouTube publication → automatic analytics collection → performance history → content strategy → próximas decisões de tema/hook/estrutura/duração → novos vídeos → nova medição.

A infraestrutura em `analytics.py`, `analytics_scheduler.py`, `content_strategy.py` e `quality_score.py` oferece feedback parcial; o closed loop automático ainda precisa ser homologado.

Regras:
- Não é fine-tuning/retraining de pesos; usar memória persistida de performance.
- Exigir mínimo de amostras antes de adaptação.
- Manter diversidade, evitar perseguir viral isolado e evitar overfitting em poucos vídeos.
- Preservar Safety e Quality Gates.
- Decisão determinística/auditável sempre que possível.

Gate futuro: demonstrar que métricas persistidas influenciam decisões futuras de forma rastreável, com amostras suficientes e diversidade preservada.

## V12-F.3 — Per-Channel Learning Isolation

Cada canal deve aprender separadamente. Não misturar automaticamente métricas, performance histórica, nicho, hooks vencedores, estruturas narrativas, duração ótima ou frequência entre canais/perfis.

Canal principal: manter perfil `default` já homologado.
Segundo canal criado manualmente: **Dose Diária de Histórias e Mistério**.
Handle: **@DoseDiáriadeHistóriasemistério**.

Planejar integração futura pela infraestrutura V9 Multi-Profile/Multi-Channel como perfil/canal separado. Não conectar nem publicar automaticamente nesta tarefa.

Gate futuro: confirmar métricas e decisões associadas ao profile/channel correto, sem contaminação automática entre canais.

## V12-F.4 — Second Channel Warm-Up

**Status: ✅ COMPLETED / PRODUCTION HOMOLOGATED (22/09/2026).**

Homologação do segundo canal concluída em produção com sucesso. Evidências reais registradas:
- **Segundo perfil isolado:** `profile-historias-misterio` ("Dose Diária de Histórias e Mistério", nicho `historias_misterio`).
- **Canal YouTube isolado:** `channel-historias-misterio-youtube` (handle `@DoseDiáriadeHistóriasemistério`, Upload-Post `dose-diaria-misterio`).
- **Geração real em produção:** task_id `815b0958-b94e-457b-932d-b10dfb0e8dba`.
- **Safety Gate:** PASS.
- **Quality Gate:** 79.2 (Strong Quality, limiar >= 70).
- **Scheduler:** Adoção e agendamento automático para YouTube.
- **Publicação pública real:** Vídeo `XVy8MbpJFqw` publicado com visibilidade pública no YouTube.
- **Analytics youtube_api:** Coleta e métricas isoladas por canal via YouTube Data API.
- **PR #9 Recovery:** Recuperação de tasks aprovadas mesmo após reinicialização de processos sem dependência de MemoryState volátil.
- **Autonomous secondary ON:** Produção autônoma do perfil secundário ativada e operacional em produção.
- **Canal principal preservado:** Perfil `default` 100% isolado e inalterado.

## V12-F.5 — Multi-Channel Capacity & True Multi-Profile Autonomous Worker

**Status: ✅ COMPLETED / IMPLEMENTED (22/09/2026).**

> [!IMPORTANT]
> **UI PROFILE SELECTION IS NOT A BACKGROUND EXECUTION SELECTOR.**
> A seleção de perfil na UI do Operator Console serve exclusivamente para inspeção visual, telemetria, controles manuais e disparos supervisionados pontuais daquele perfil. O worker em segundo plano processa de forma determinística e independente todos os perfis ativos e habilitados (`run_enabled_profiles_autonomous_cycle`).

Capacidade multi-canal e governança de custos implementada:
- **True Multi-Profile Background Worker:** Loop do scheduler worker desacoplado de `get_active_profile_id()`. O worker itera de forma determinística sobre todos os perfis ativos com `autonomous_mode_enabled=True`, executando no máximo 1 transição por perfil por ciclo com isolamento de falha (falha em um canal não aborta os demais).
- **Ready Stock por perfil:** Configuração `autonomous_target_ready_stock:<profile_id>` (WARMUP default 3, SCALE default 5; intervalo configurável [3, 6]). Fallback backward-compatible para a chave legada no perfil `default`.
- **Limites de produção por perfil (24h):**
  - WARMUP: 2 gerações aprovadas / 24h; 8 tentativas / 24h.
  - SCALE: 5 gerações aprovadas / 24h; 15 tentativas / 24h.
  - Configurações isoladas: `autonomous_max_generations_24h:<profile_id>` e `autonomous_max_attempts_24h:<profile_id>`.
- **Global Cost Guard:** Freio mestre agregado somando todos os perfis (`autonomous_global_max_generations_24h = 10`, `autonomous_global_max_attempts_24h = 25`). Contadores agregados explícitos (`count_all_profiles_generations_24h`, `count_all_profiles_attempts_24h`). Protege o início de novas gerações sem bloquear agendamento, recuperação de vídeos já prontos ou publicação.
- **Elegibilidade de destinos multi-plataforma:** Conceito arquitetural `check_asset_eligibility_for_destination` permitindo futuro reuso de 1 asset aprovado para múltiplos destinos sem re-renderização.
- **TikTok estritamente OFF:** Nenhuma publicação, chamada de API ou credencial criada para TikTok.
- **Ponteiros e estado isolados:** `current_task_id`, `waiting_task_id`, `autonomous_state` e mensagens 100% isolados por perfil.

### Pendência Futura: Copyright / Content ID Hardening + Character Narrator

- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` publicado com sucesso porém bloqueado mundialmente por Content ID / direitos autorais reivindicados.
- **Backlog Futuro:**
  - Identificar mídia e faixa musical (BGM) causadora da reivindicação.
  - Personagem / apresentador narrador virtual (V14 Hybrid Presenter) para enriquecer teor transformativo.
  - Composição visual e de áudio mais original, revisando fontes e licenças.
  - Gate preventivo de verificação de copyright.
  - Vídeos bloqueados/reivindicados não devem alimentar o Closed Feedback Loop.
- **Observação:** Nenhum filtro ou mitigação implementado na V12-F.5 (pendência estritamente documentada).

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

V12-E homologada; V13 permanece posterior à V12-F, com escopo e autorização próprios.

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
