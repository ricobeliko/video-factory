# ROADMAP — Video Factory / MoneyPrinterTurbo

## Política atual de validação

- Testes massivos registrados em fases antigas são EVIDÊNCIA HISTÓRICA, não obrigação futura.
- Menções antigas a "regressão de 22 suítes", centenas de testes ou full regression NÃO são gates automáticos.
- Validação padrão atual = teste direcionado mínimo.
- Full regression exige autorização humana explícita.
- Esta política prevalece sobre registros históricos de validação de fases anteriores.

---

# Estado Atual Canônico — 23/09/2026

> [!IMPORTANT]
> **Precedência Canônica:** Esta seção reflete o estado real, auditado e vigente da fábrica de vídeos. Ela prevalece formalmente sobre quaisquer menções, metas pendentes ou notas de snapshots históricos mantidos nas seções inferiores para rastreabilidade de engenharia.

## Status Consolidado por Componente

- **V12-E Autonomous Production** = PRODUCTION HOMOLOGATED
- **V12-F.1 Analytics Auto Collection** = PRODUCTION HOMOLOGATED
- **V12-F.2 Closed Feedback Loop** = IMPLEMENTED / ACTIVE / PRODUCTION HOMOLOGATED
- **V12-F.3 Per-Channel Learning Isolation** = IMPLEMENTED / ACTIVE
- **V12-F.4 Second Channel Warm-Up** = PRODUCTION HOMOLOGATED
- **V12-F.5 Multi-Channel Capacity** = IMPLEMENTED / ACTIVE
- **V13-A Safe Update Foundation** = MERGED
- **V13-A.1 Backup JSON Capture Hotfix** = MERGED
- **V13-B Safe Production Update** = PRODUCTION HOMOLOGATED
- **V14-A Copyright Audit** = COMPLETED
- **V14-B Copyright Baseline Hardening** = PRODUCTION HOMOLOGATED
- **V14-B.1 Legacy Stock Quarantine** = PRODUCTION HOMOLOGATED
- **V14-B.2 Copyright Status + Closed Feedback Loop Exclusion** = PRODUCTION HOMOLOGATED
- **V14-B.2.1 Copyright UI Feedback** = PRODUCTION HOMOLOGATED
- **V14-C Presenter Framework** = MERGED BUT DORMANT
- **V14-C.1 / C.2 Presenter Expression Framework** = MERGED BUT DORMANT
- **V14-C.3 Nox Foundation** = EXPERIMENT ARCHIVED / DORMANT
- **Presenter autonomous**: OFF
- **avatar_mode**: `none`
- **TikTok**: OFF / NOT HOMOLOGATED

## Produção Atual (Estado Operacional Consolidado)

- **PC forte** = autoridade de produção (`C:\Projetos\MoneyPrinterTurbo`)
- **Scheduler** = ON
- **Auto Publish** = ON
- **Dry Run** = OFF
- **YouTube** = ON
- **TikTok** = OFF
- **Autonomous Production** = ON
- **Analytics Auto** = ON
- **Closed Feedback Loop** = ON
- **Growth Mode** = WARMUP
- **MPT Auto Upload** = OFF
- **Presenter/Nox** = OFF
- **Multi-profile autonomous worker** = ACTIVE
- **Copyright provenance gate** = ACTIVE
- **Copyright status exclusion** = ACTIVE
- **Safe updater** = ACTIVE

**Safe updater oficial:**
`scripts/update_production.ps1`
Fluxo mandatário: Preflight → Backup SQLite → integrity_check → Stop → Fast-Forward Update → Start → Health Check → Rollback automático se necessário. Proibido git pull manual como fluxo padrão.

**Última homologação real de produção (V13-B):**
- **TARGET/FINAL_SHA:** `46e44c2495a8fe38484977ad1aa7cff439e26679`
- **BACKUP:** PASS (`storage/backups/database/video_factory_20260923_061728.db`, SHA-256: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`)
- **SQLITE_INTEGRITY:** OK
- **STOP:** PASS
- **FF UPDATE:** PASS
- **START:** PASS
- **HEALTH:** PASS — HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`
- **ROLLBACK:** NOT_REQUIRED
- **DEPLOY:** SUCCESS
- **Documentação posterior:** main `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`

---

# V15 — Production Observation & Optimization

**Status:** OPEN / OBSERVATION FIRST

## Objetivo
Observar a fábrica completa em funcionamento real no PC forte antes de adicionar grandes features.

A V15 deve medir se o sistema atual está:
- produzindo de forma autônoma e sustentável
- aprovando dentro dos critérios de Safety, Quality e Copyright
- estocando adequadamente por perfil
- agendando dentro das janelas operacionais
- publicando com sucesso no YouTube
- coletando métricas de analytics pontualmente
- aprendendo com o Closed Feedback Loop sem sobreajuste
- mantendo isolamento estrito por canal
- respeitando direitos autorais e políticas de conteúdo
- respeitando limites de custo e volume (Cost Guard)

## Princípio Fundamental da V15
A V15 **NÃO** deve começar criando novas features ou alterando parâmetros de forma especulativa.

Fluxo metodológico:
> **OBSERVAR → MEDIR → IDENTIFICAR GARGALO REAL → PRIORIZAR → OTIMIZAR**

Evitar rigorosamente:
- Otimização prematura
- Adição de novos provedores sem necessidade
- Novo avatar ou insistência no Nox neste ciclo
- Criação de novos canais
- Ativação ou dependência de TikTok
- Aumento forçado de volume
- Alteração de thresholds sem evidência empírica coletada

---

## V15-A — Production Observability Baseline

**Status:** OPEN (Próxima fase ativa)

### Objetivo
Criar um diagnóstico PASSIVO e estruturado do comportamento real dos dois canais em produção contínua:
- **Canal Principal:** `profile_id = default`
- **Canal Secundário:** `profile_id = profile-historias-misterio`

### 9 Dimensões de Observação Passiva:
1. **Autonomous Production:** Estado, último ciclo, geração atual, waiting task, estoque pronto por perfil.
2. **Scheduler:** Contagem de posts agendados, publicados, com falha, em retry e próximos slots por canal.
3. **Gates:** Telemetria de aprovação e rejeição nos gates de Safety, Quality e Copyright Provenance.
4. **Produção 24h:** Tentativas (attempts), aprovações, rejeições e principais motivos agregados e por perfil.
5. **Publicações:** Sucessos, falhas, visibilidade (público comprovado) e status de direitos autorais (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`).
6. **Analytics:** Snapshots coletados, idade do último fetch, provider utilizado e erros de coleta.
7. **Closed Feedback Loop:** Modo atual (baseline/adaptive), quantidade de amostras elegíveis, decisões recentes de tema/estrutura narrativa, razões de fallback e garantia de isolamento por canal.
8. **Multi-Channel:** Confirmação de que a seleção visual da UI no Operator Console NÃO controla nem interfere no worker em background, e confirmação de atividade independente dos perfis.
9. **Cost Guard:** Validação do cumprimento dos limites por perfil (WARMUP / SCALE) e do limite mestre global, garantindo ausência de explosão de chamadas ou gastos descontrolados.

### Critérios de Aceite para V15-A:
V15-A será considerada concluída com sucesso quando conseguirmos obter, de forma estritamente passiva e sem alterar o estado da produção:
- Status operacional dos dois perfis
- Estoque de cada perfil
- Estado do scheduler
- Histórico das últimas publicações
- Últimas métricas de analytics
- Status de copyright das publicações ativas
- Estado do Closed Feedback Loop por perfil
- Contadores de produção em 24h
- Principais problemas e rejeições recentes identificados

*Preferência técnica:* Reutilizar o Operator Console e serviços de diagnóstico existentes (`production_health.py`, `operator_console.py`). Zero adições de tabelas ou alterações de schema no SQLite sem necessidade comprovada.

### Próximas Decisões (Pós V15-A):
Somente após a consolidação da observação real e identificação de gargalos empíricos serão priorizadas as frentes de evolução:
- Otimização de geração
- Melhoria de hooks e roteiros
- Diversidade visual
- Qualidade de assets
- Frequência de publicação
- Estratégia dedicada por canal
- Monetização
- Revisão de fornecedores de stock/áudio
- Melhorias na UI/UX do Operator Console

*Não antecipar decisões nem escolher caminhos prioritários antes das medições da V15-A.*

---

## V13-B — Production Homologation / Safe Remote Deployment Active — 23/09/2026

Homologação real executada com sucesso no PC forte de produção (`C:\Projetos\MoneyPrinterTurbo`) utilizando `scripts/update_production.ps1` com o hotfix de captura de JSON (V13-A.1).
Status: **PRODUCTION HOMOLOGATED**.

- **Evidência Operacional Real:**
  - `CURRENT_SHA`: `e3f024938c5338c197a1f1654775686227f3eb05`
  - `TARGET/FINAL_SHA`: `46e44c2495a8fe38484977ad1aa7cff439e26679`
  - `BACKUP`: PASS
  - `BACKUP_FILE`: `storage/backups/database/video_factory_20260923_061728.db`
  - `BACKUP_SHA256`: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`
  - `SQLITE_INTEGRITY`: OK
  - `SAFE_STOP`: PASS (`schtasks /End /TN "VideoFactory Production"`)
  - `FAST_FORWARD_UPDATE`: PASS (`git merge --ff-only 46e44c2495a8fe38484977ad1aa7cff439e26679`)
  - `SAFE_START`: PASS (`schtasks /Run /TN "VideoFactory Production"`)
  - `HEALTH`: PASS — HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`
  - `ROLLBACK`: NOT_REQUIRED
  - `DEPLOY_STATUS`: DEPLOY_SUCCESS
- **Histórico e Status Consolidado dos Componentes:**
  - `V13-A` = MERGED
  - `V13-A.1` = MERGED (hotfix de separação de stdout e stderr no backup)
  - `V13-B` = PRODUCTION HOMOLOGATED
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT / OFF (`avatar_mode="none"`)
- **Novo Contrato Operacional Obrigatório:**
  - Todas as atualizações futuras da produção devem usar estritamente `scripts/update_production.ps1`.
  - Fluxo oficial obrigatório: Preflight -> Backup SQLite -> integrity_check -> Stop -> Fast-Forward Update -> Start -> Health Check -> Rollback automático se necessário.
  - Proibido uso de git pull manual ou intervenção destrutiva como fluxo padrão.


## V13-A — Safe Update Foundation — 23/09/2026

Implementação concluída em desenvolvimento: fundação para atualização remota e headless segura da produção via `scripts/update_production.ps1`.
Status nesta fase: **MERGED** (V13-A e V13-A.1 homologados na V13-B).

- **Pipeline Seguro:** `PRE-FLIGHT -> BACKUP -> STOP -> UPDATE FF-ONLY -> START -> HEALTH CHECK -> SUCCESS`.
- **Pre-flight Fail-Closed:** Valida repo Git, working tree limpa (sem alterações não commitadas ou arquivos críticos untracked), ambiente virtual (.venv), existência e resolução de `CURRENT_SHA` e `TARGET_SHA`. Flag `-PreflightOnly` executa apenas diagnósticos e exibe o plano sem mutações.
- **Fast-Forward Only:** Validação prévia estrita via `git merge-base --is-ancestor`. Zero merges ou rebases automáticos.
- **Backup Transacional Pré-Stop:** Criação de snapshot do SQLite via `app.services.production_backup` com `PRAGMA integrity_check` obrigatório e hash SHA-256 registrado antes de parar o serviço.
- **Parada e Inicialização Seguras:** Controle exclusivo via Scheduled Task do Windows (`schtasks /End` e `schtasks /Run`), aguardando encerramento sem matar processos aleatórios.
- **Health Check Delimitado:** Verificação com timeout finito (75s) em `http://127.0.0.1:8501/_stcore/health` aguardando HTTP 200 e corpo contendo `ok`.
- **Rollback Não-Destrutivo:** Se o health check pós-update falhar, a Scheduled Task é parada, a working tree é retornada para `CURRENT_SHA` via `git switch --detach CURRENT_SHA` (zero `git reset`, `git restore` ou `git clean`, preservando a branch `main`), e a aplicação é reiniciada. Se o health check pós-rollback passar: `ROLLBACK_SUCCESS`; se falhar: `ROLLBACK_FAILED` exigindo intervenção humana.
- **Lock e Logging Local Sanitizado:** Lock exclusivo em `storage/locks/update_production.lock` com limpeza em bloco `finally`. Logs timestampados em `logs/deploy/` sem exposição de credenciais, tokens ou dumps de configuração.
- **Ambientes e Status Vigentes:**
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT
  - Produção física (`C:\Projetos\MoneyPrinterTurbo`) homologada no commit `46e44c2`.
- **Próxima Fase Global:** V15 — Production Observation & Optimization.


## V14-B.2 — Manual Copyright Status + Closed Feedback Loop Exclusion — 23/09/2026

Implementação concluída em desenvolvimento: rastreamento persistente e auditável de status de direitos autorais por publicação/tarefa (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`), com fail-closed para o Closed Feedback Loop.

- **Status de Direitos Autorais Auditáveis:** `set_publication_copyright_status_op` e `get_publication_copyright_status` persistidos em `operational_events` com metadata estruturado completo (`task_id`, `publication_event_id`, `platform`, `external_id`, `copyright_status`, `source='operator'`, `timestamp`, `note`).
- **Zero Schema Change:** Reutiliza `operational_events` existente sem migrações ou tabelas novas. Idempotente quando o mesmo status e nota são reaplicados.
- **Regra Crítica do Closed Feedback Loop:**
  - `clean_manual`: elegível do ponto de vista de copyright (pode compor amostras de aprendizado).
  - `claimed`, `blocked`, `strike`: SEMPRE EXCLUÍDOS.
  - `unknown` (incluindo publicações legadas sem status): FAIL CLOSED (EXCLUÍDOS).
  - Razões explícitas de auditoria registradas: `copyright_unknown`, `copyright_claimed`, `copyright_blocked`, `copyright_strike`.
- **Preservação de Dados:** Nenhum evento de publicação, métrica de analytics ou histórico de tarefas é apagado ou modificado.
- **Operator Console:** Exibição clara no card Copyright / Assets com badges de status, source e elegibilidade do loop, além de formulário auditável não-destrutivo para o operador marcar status manualmente (PRIMARY only).
- **Vídeo Bloqueado Conhecido:** Fluxo preparado para marcação manual pós-deploy da task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) como `blocked`.
- **Presenter:** DORMANT (experimento arquivado em branch separada, produção e main mantidas com `avatar_mode="none"`).
- **Próxima fase subsequente:** V13 (concluída e homologada na V13-B); Fase global atual: V15.


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

## [HISTORICAL SNAPSHOT / SUPERSEDED] Estado vigente — 21/09/2026

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o estado histórico em 21/09/2026. As fases V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Isolation), V12-F.4 (Second Channel Warm-Up), V12-F.5 (Multi-Channel Capacity), V13-A/A.1/B (Safe Production Update) e V14-A/B/B.1/B.2/B.2.1 (Copyright Hardening) foram posteriormente implementadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece.

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
- V12-F.1 Analytics Auto Collection ✅ — homologada em produção
- V12-F.2 Closed Feedback Loop ✅ — homologada em produção
- V12-F.3 Per-Channel Learning Isolation ✅ — implementada / ativa
- V12-F.4 Second Channel Warm-Up ✅ — homologada em produção
- V12-F.5 Multi-Channel Capacity ✅ — implementada / ativa
- V13-A Safe Update Foundation ✅ — merged
- V13-A.1 Backup JSON Capture Hotfix ✅ — merged
- V13-B Safe Production Update ✅ — homologada em produção
- V14-A Copyright Audit ✅ — concluída
- V14-B Copyright Baseline Hardening ✅ — homologada em produção
- V14-B.1 Legacy Stock Quarantine ✅ — homologada em produção
- V14-B.2 Copyright Status + Closed Feedback Loop Exclusion ✅ — homologada em produção
- V14-B.2.1 Copyright UI Feedback Hotfix ✅ — homologada em produção
- V14-C Presenter Framework ✅ — merged (dormant)
- V14-C.1 / C.2 Presenter Expression Framework ✅ — merged (dormant)
- V14-C.3 Nox Foundation ⏸️ — experiment archived / dormant

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

Próxima fase (à época da homologação V12-E): **V12-F — Adaptive Learning + Multi-Channel Warm-Up**. *(Nota histórica: As fases V12-F, V13 e V14 foram subsequentemente homologadas em produção. O Estado Atual Canônico no topo prevalece).*

---

# [HISTORICAL SNAPSHOT / SUPERSEDED] V12-F — Adaptive Learning + Multi-Channel Warm-Up

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o planejamento inicial histórico da V12-F em 21/09/2026. As subfases V12-F.1 (Analytics Auto Collection), V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Learning Isolation), V12-F.4 (Second Channel Warm-Up) e V12-F.5 (Multi-Channel Capacity) foram subsequentemente implementadas, ativadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece formalmente sobre este registro.

Objetivo original: transformar o feedback de desempenho em um ciclo fechado de otimização, sem treinamento de pesos do modelo e sem sacrificar segurança, diversidade ou controle por canal.

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

**Status: ✅ IMPLEMENTED / ACTIVE / PRODUCTION HOMOLOGATED (22/09/2026)**

> [!NOTE]
> *(Nota de atualização: O Closed Feedback Loop foi implementado, integrado à estratégia de conteúdo autônoma e homologado com exclusão fail-closed de copyright na V14-B.2. O Estado Atual Canônico no topo prevalece).*

Fluxo implementado: YouTube publication → automatic analytics collection → performance history → content strategy → próximas decisões de tema/hook/estrutura/duração → novos vídeos → nova medição.

A infraestrutura em `analytics.py`, `analytics_scheduler.py`, `content_strategy.py` e `quality_score.py` oferece feedback parcial; o closed loop automático ainda precisa ser homologado.

Regras:
- Não é fine-tuning/retraining de pesos; usar memória persistida de performance.
- Exigir mínimo de amostras antes de adaptação.
- Manter diversidade, evitar perseguir viral isolado e evitar overfitting em poucos vídeos.
- Preservar Safety e Quality Gates.
- Decisão determinística/auditável sempre que possível.

Gate futuro: demonstrar que métricas persistidas influenciam decisões futuras de forma rastreável, com amostras suficientes e diversidade preservada.

## V12-F.3 — Per-Channel Learning Isolation

**Status: ✅ IMPLEMENTED / ACTIVE (22/09/2026)**

> [!NOTE]
> *(Nota de atualização: O isolamento de aprendizado por canal está implementado e ativo no Content Strategy e Analytics, garantindo aprendizado independente entre perfis sem contaminação cruzada de métricas. O Estado Atual Canônico no topo prevalece).*

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

# [HISTORICAL SNAPSHOT / SUPERSEDED] V13 — Headless Remote Deployment / Safe Update

**Status: ✅ HOMOLOGADA EM PRODUÇÃO — 23/09/2026 (V13-A / V13-A.1 / V13-B)**

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o planejamento original da V13. A fundação de atualização remota e headless segura (`scripts/update_production.ps1`) foi integralmente desenvolvida, testada (V13-A e V13-A.1) e homologada com sucesso no PC forte de produção (V13-B, commit `46e44c2`). O **Estado Atual Canônico** no topo prevalece sobre este registro histórico.

Objetivo original (concluído e homologado):
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

Entregáveis homologados:
- `scripts/update_production.ps1`
- gate de worktree clean
- backup automático com SQLite integrity check e sidecar SHA-256
- validação Fast-Forward estrita do commit alvo
- health check delimitado (HTTP 200 / ok)
- rollback não-destrutivo via git switch detach

---

# V14 — Virtual Presenter & Copyright Hardening

## V14-A — Auditoria e Plano Técnico
- **Status:** ✅ AUDIT COMPLETED
- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` publicado com sucesso, porém posteriormente bloqueado mundialmente por Content ID (conteúdo reivindicado; sem evidência de strike).
- **Causa Raiz Identificada:** Faixas padrão de `resource/songs/*.mp3` originadas de vídeos do YouTube conforme aviso do README upstream, associadas ao sorteio `bgm_type="random"`.
- **Arquitetura Recomendada:** Character Overlay Transparente Local (WebM VP9 alfa / PNG) + Copyright Baseline Hardening.

## V14-B — Copyright Baseline Hardening
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Escopo:**
  1. Bloqueio estrito de faixas legadas (`resource/songs/`) em novas gerações autônomas (`resolve_autonomous_bgm` com `bgm_type="none"`, `volume=0.0`, `SAFE_NO_BGM`).
  2. Uso manual legado preservado sem exclusão física dos arquivos.
  3. Rastreabilidade auditável (`asset_provenance` com BGM e clips visuais persistidos em `script.json` e memória).
  4. Copyright Provenance Gate no pipeline autônomo (fail-closed antes da aprovação da tarefa).
  5. Nenhum mecanismo local de evasão de Content ID; resposta formal `COPYRIGHT_PROVENANCE_GATE = PASS` (sem falsas promessas de `CONTENT_ID_SAFE`).
  6. Preparação conceitual de status futuro (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`) e fontes (`operator`, `future_provider`).
  7. Backlog: exclusão no Closed Feedback Loop de publicações com reivindicação comprovada.
  8. Card "Copyright / Assets" no Operator Console.

## V14-B.1 — Legacy Stock Copyright Quarantine (Hotfix)
- **Status:** ✅ PRODUCTION HOMOLOGATED
- **Causa Raiz:** Vídeos antigos já renderizados (23 assets não publicados) possuíam `bgm_type="random"` ou `bgm_type="custom"` e ausência de `asset_provenance`. O loop autônomo recuperava esses vídeos no `get_autonomous_ready_stock()` e `_recover_waiting_task()`. Além disso, `build_asset_provenance` não lia corretamente parâmetros quando em formato `dict`.
- **Correções:**
  1. Suporte universal a `dict` e objetos em `build_asset_provenance()` via `_get_param()`.
  2. Tarefas antigas com `bgm_type="random"` e `bgm_type="custom"` sem proveniência avaliam estritamente como `COPYRIGHT_PROVENANCE_GATE = FAIL`.
  3. `_recover_waiting_task()` e `get_autonomous_ready_stock()` agora exigem `evaluate_copyright_provenance_gate == PASS`, excluindo automaticamente os 23 vídeos legados do estoque autônomo e do agendamento autônomo.
  4. Preservação física e histórica: nenhum arquivo apagado, nenhum registro cancelado. Fluxo manual legado preservado.

## V14-C — Hybrid Character Overlay MVP
- **Status:** ✅ MERGED
- **Arquitetura Selecionada:** Character Overlay Transparente Local (WebM VP9 alfa / PNG transparente).
- **Custo e Dependências:** R$ 0,00; sem chamadas pagas, 100% offline via MoviePy 2.x existente.
- **Implementação:**
  1. Suporte completo em `VideoParams` (`avatar_mode`, `avatar_provider`, `avatar_character_id`, `avatar_asset_path`, `avatar_position`, `avatar_scale`, `avatar_opacity`).
  2. Módulo dedicado `app/services/presenter.py` com validação de config, bloqueio de traversal, layout seguro (safe margins para Shorts) e timeline híbrida determinística (`build_hybrid_presenter_segments`).
  3. Composição Z-Order no `video.generate_video()` com legendas renderizadas no topo (`source_video_clip` -> `presenter_clips` -> `text_clips`).
  4. Proveniência de presenter integrada a `build_asset_provenance()` em `copyright_gate.py`.
  5. Telemetria no Operator Console: Mode, Character ID, Provider e Asset Status.
  6. Modo autônomo estritamente mantido em `avatar_mode="none"`.

## V14-C.1 — Cartoon Character Asset Pack + Preview
- **Status:** ✅ MERGED
- **Personagem:** **Nox** (`nox_v1` / `misterio_host_v1`), estilo cartoon / semi-cartoon, definido como personagem-base unificado para todos os canais (`SINGLE_CHARACTER_ALL_CHANNELS = YES`).
- **Implementação:**
  1. Especificação completa do personagem documentada em `docs/CHARACTER_PRESENTER_SPEC.md` (direção visual, paleta de cores sóbrias, vestimenta grafite/vinho, enquadramento waist-up e lista de poses).
  2. Contrato de Asset Pack local estabelecido em `storage/presenter_assets/<character_id>/` e `resource/presenter_assets/<character_id>/` com catálogo de poses (`neutral`, `talking_1`, `talking_2`, `surprised`, `serious`, `thinking`, `pointing_left`, `pointing_right`, `cta`) e `config.json`.
  3. Resolução de Character Pack por `character_id` em `presenter.py` (`resolve_character_pack`) com fail-closed para poses obrigatórias ausentes.
  4. Pose Controller determinístico (`select_presenter_pose`) selecionando poses por segmento narrativo (hook, return, cta, corner).
  5. Suporte a Preview controlado (`render_presenter_preview` e `generate_presenter_preview_frame`) para validação estática e render sem tocar produção.
  6. Produção autônoma estritamente preservada com `avatar_mode="none"`.

## V14-C.2 — Expressive Presenter + Subtitle Interaction
- **Status:** ✅ MERGED
- **Implementação:**
  1. Parser determinístico e tolerante a falhas de SRT (`parse_srt_timeline`), convertendo legendas para estrutura temporal unificada.
  2. Classificador prioritário de legendas (`classify_subtitle_reaction`) com categorias PT-BR: SURPRISE, THINKING, SERIOUS, CTA e DEFAULT com precedência estrita (`CTA > SERIOUS > SURPRISE > THINKING > TALKING > NEUTRAL`).
  3. Alternância determinística de fala (`talking_1` e `talking_2` em intervalos de 0.35s) sem requerer lip-sync neural.
  4. Interação de apontamento (`pointing_left` para `bottom_right`, `pointing_right` para `bottom_left`).
  5. Tom de canal respeitado: `profile-historias-misterio` utiliza reações sóbrias e contidas (`mystery_contained_reaction`).
  6. Construção da timeline de expressões (`build_presenter_expression_timeline`) respeitando estritamente os segmentos do presenter e sem sobreposição temporal inválida.
  7. Performance otimizada no MoviePy via cache único de clips de pose no ExitStack.
  8. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).

## V14-C.3 — Nox Canonical Visual Asset Pack + Real Local Preview
- **Status: ⏸️ EXPERIMENT ARCHIVED / DORMANT**
- **Observação Crítica:** O experimento visual estático com Nox não atingiu o resultado desejado de qualidade e dinamismo para operação em produção. Por este motivo, **V14-C.4 NÃO é a próxima fase ativa**.
- **Presenter/Nox DORMANT:** Os frameworks de apresentador e expressões (V14-C, V14-C.1, V14-C.2) permanecem no código, mas o modo autônomo está estritamente fixado em `avatar_mode="none"` (OFF).
- **Branch de Arquivamento:** Todos os assets experimentais e tuning visual de Nox foram preservados na branch de arquivo: `archive/v14-c3-nox-presenter-experiment`. Não há novos trabalhos de desenvolvimento planejados para Nox nesta etapa.
- **Implementação Realizada (Histórico):**
  1. Estrutura canônica de diretórios criada em `assets/presenter/nox_v1/` com `manifest.json`, `reference/`, `poses/` e `previews/`.
  2. Manifest declarativo versionado com metadados de identidade visual canônica (idade 20-30 anos, pele morena clara, cabelo preto com reflexos roxos, olhos castanhos, roupa jaqueta/moletom preto).
  3. Contrato estrito de Core Poses (9 poses obrigatórias) e catálogo de Extended Motion Pack (13 poses opcionais).
  4. Fallback Graph determinístico implementado para poses estendidas (`EXTENDED_POSE_FALLBACKS`).
  5. Validação rigorosa de consistência de assets (`validate_character_pack_assets`) checando formato PNG, canal alfa real e uniformidade de dimensões entre poses.
  6. Gerador local de Contact Sheet (`generate_contact_sheet`) para inspeção de layout e coerência visual pelo operador.
  7. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).
- **Próxima Fase Global:** V15-A — Production Observability Baseline (V15 — Production Observation & Optimization).

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
