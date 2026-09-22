# PROJECT_HANDOFF — Video Factory / MoneyPrinterTurbo

## V12-E.3 — gate DEV controlado — 21/09/2026

Baseline de código `54875c6`; sem commit, push, deploy ou acesso à produção.
Esta entrega resolve a recuperação e reposição do buffer autônomo de estoque YouTube
de forma desacoplada da V12-F.2.

Principais contratos implementados:
- Estoque YouTube persistente: `get_autonomous_ready_stock` reconstrói tarefas aprovadas
  a partir de `monetization_safety` (PASS explícito), `content_quality_scores` (>= 70,
  GOOD/STRONG), `task_profiles` e arquivo de vídeo existente em disco.
- Recuperação sem `MemoryState`: `_recover_waiting_task` não depende do estado em memória
  para revalidar ou agendar tarefas aprovadas pós-restart.
- Buffer 0→3 em WARMUP: tarefas aprovadas sem slot disponível são retidas no estoque
  sem impedir novas gerações caso o total pronto esteja abaixo da meta (3).
- Exatamente uma ação por ciclo: cada execução do loop autônomo executa no máximo uma
  transição (revisão de conclusão, agendamento de 1 task aprovada ou início de 1 geração).
- Limite de gerações: 1 geração por ciclo e teto estrito de 5 gerações nas últimas 24h.
- Retry e deduplicação de 15 minutos: falha de agendamento sem slot impõe cooldown de 15 min
  por task via `autonomous_schedule_retry:<task_id>`. Eventos `PROFILE_GROWTH_LIMIT_BLOCK`
  são deduplicados transacionalmente em `scheduler.log_growth_limit_block` a cada 15 min.
- Scheduler como único publicador: nenhuma publicação direta; Growth Mode preservado; TikTok OFF.
- Sem migrações de schema: utiliza tabelas e colunas já existentes.

Validação DEV concluída: **600 testes e 32 subtestes passaram, zero falhas**, em
246,12s, nas 23 suítes; 16 testes novos são da V12-E.3. SQLite, vídeos e
configuração sintéticos em diretórios temporários; rede bloqueada. `git diff --check`
aprovado. Fixtures antigas foram atualizadas para aprovações persistidas e para
permitir reposição sem slot. Próximo gate seguro: revisar exclusivamente o diff V12-E.3;
qualquer homologação/deploy em produção exige autorização separada.
Arquivos desta etapa: `app/services/autonomous_production.py`,
`app/services/scheduler.py`, `test/services/test_autonomous_production.py`,
`test/services/test_autonomous_stock_buffer.py` e os três documentos canônicos
de handoff, roadmap e runbook.



## V12-F.1C — Publication Privacy Persistence (21/09/2026)

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`), sem deploy em produção. Analytics Auto Collection continua `OFF`. Nenhuma API real executada; nenhum secret acessado ou exposto.

**Causa raiz:** a privacidade do YouTube nunca era persistida de forma própria em `publication_events` — o único sinal disponível era um fallback legado (`storage/tasks/<task_id>/task.json`), que não existe para o evento real homologado (`publication_event id=16`, task `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`, external_id `fTrkUqSnYqs`), apesar do operador ter confirmado visualmente PUBLIC no YouTube Studio. Isso fazia `get_known_publication_privacy_status()` retornar `unknown`, bloqueando corretamente a coleta automática (fail-closed), mas sem nenhuma forma auditável de registrar a evidência real. Também foi identificado que `fetch_real_metrics_for_publication()` (coleta manual) não verificava privacidade antes da chamada real — uma coleta manual poderia ter contornado o mesmo contrato fail-closed do Analytics automático.

**Mudanças implementadas (aditivas, mínimas, backward-compatible):**

- **Schema:** nova coluna `publication_events.privacy_status TEXT NULL`, adicionada via migração idempotente do scheduler (`_run_migrations`) e presente no `CREATE TABLE` para bancos novos. Nenhum histórico existente é reescrito.
- **Persistência:** `scheduler.record_publication_event()` aceita `privacy_status: Optional[str] = None`, normalizado para `public`/`private`/`unlisted` (ou `NULL` para valores não reconhecidos ou plataformas que não sejam YouTube).
- **Publicação futura:** `task.py` (ambos os caminhos, síncrono e assíncrono de `publish_task`) agora persiste exatamente o `privacyStatus` efetivamente enviado ao Upload-Post (`effective_youtube_privacy` / `youtube_privacy_status`), em vez de inferir depois pela configuração atual.
- **Elegibilidade do Analytics automático:** `get_known_publication_privacy_status()` prioriza `publication_events.privacy_status` persistido, com fallback legado para `task.json`, e retorna `unknown` se nada resolver. `PRIVATE`, `UNLISTED` e `UNKNOWN` continuam bloqueando (fail-closed); somente `PUBLIC` comprovado é elegível.
- **Coleta manual (`fetch_real_metrics_for_publication`):** agora exige `PUBLIC` comprovado para YouTube **antes** de qualquer requisição HTTP real, para `persist=False` e `persist=True`. Bloqueio usa o novo código de erro `ERR_PRIVACY_BLOCKED`, sem expor segredos.
- **Confirmação operacional auditável:** nova `operator_console.confirm_publication_privacy_op(publication_event_id, expected_task_id, expected_external_id, privacy_status)` — exige PRIMARY, valida exatamente o evento (status=success, platform=youtube, task_id e external_id esperados), aceita apenas valores reconhecidos, atualiza SOMENTE `privacy_status`, registra `operational_event` auditável sem secrets, não altera `scheduled_posts` nem publica nada. **Não executada em produção nesta tarefa** — permite futuramente homologar o evento real 16 (task `f9b3e05f-...`, external_id `fTrkUqSnYqs`, privacy `public`) sem SQL manual.

Regressão direcionada: suítes exigidas 100% PASS (`test_analytics_scheduler.py`, `test_analytics_ingestion.py`, `test_analytics_providers.py`, `test_analytics_real_fetch.py`, `test_scheduler.py`, `test_scheduler_worker.py`, `test_operator_console.py`, `test_autonomous_production.py`, `test_single_instance.py`, `test_production_health.py`, `test_production_entrypoint.py`, `test_publication_persistence.py`): **329 passed, 19 subtests passed, 0 failed**. Verificação adicional do publish path revelou 7 falhas pré-existentes e não relacionadas (Growth Mode/warmup de TikTok e ordenação de plataformas em `test_scheduler_execution.py`, `test_scheduler_timezone.py`, `test_publish_task.py`), confirmadas por reprodução em isolamento total sem qualquer mudança desta tarefa — não corrigidas aqui por estarem fora do escopo da V12-F.1C.

**Não marcar V12-F.1 como concluída.** V12-F.1A e V12-F.1C endureceram contratos de segurança do Analytics; V12-F.1B corrigiu o bootstrap headless. A ativação real do Analytics Auto Collection em produção continua exigindo decisão e homologação próprias.

---

## V12-F.1B — Headless Worker Bootstrap (21/09/2026)

**Status: ✅ implementada e HOMOLOGADA em produção.** Gate headless PASS, conforme evidências fornecidas pelo operador: Scheduled Task Running, HTTP 200/ok, heartbeat do PRIMARY avançou sem navegador, `executor_last_tick` avançou sem navegador. Estado operacional confirmado: Autonomous OFF, Auto Publish OFF, Analytics Auto OFF. Produção em `d1a8677`. Backup pré-deploy: `video_factory_20260921_044508.db`, SHA-256 `2f20ae0e7814f5b8745b5025d8ba6b49073e1cfb50e042d7d631f934506a1e52`, integridade `ok`.

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`) antes do deploy. Nenhuma ativação de Analytics; nenhuma regra de publicação/Growth Mode/Safety/Quality Gate alterada.

**Causa raiz:** `scheduler.start_scheduler_worker()` só era chamado dentro do fragmento Streamlit `_render_publication_schedule()` em `webui/Main.py`, que só executa quando uma sessão de navegador conecta. Em modo headless (`--server.headless=true`), após reboot da Scheduled Task sem navegador, o script nunca era executado por nenhuma sessão e o worker (scheduler, analytics automático, produção autônoma) nunca iniciava.

**Arquitetura implementada:** um novo `scripts/production_entrypoint.py` roda no MESMO processo/interpretador que hospedará o Streamlit:

1. `operator_console.ensure_instance_initialized()` — reaproveita exatamente o mecanismo de Single PRIMARY já existente (mesmo lock SQLite, mesmos papéis PRIMARY/SECONDARY_VIEW_ONLY).
2. Se PRIMARY: `scheduler.start_scheduler_worker(interval_seconds=30)` e confirma `is_worker_alive()` antes de prosseguir (fail-closed: erro aqui aborta o processo com código de saída != 0 e o Streamlit nunca sobe).
3. Se SECONDARY_VIEW_ONLY: worker intencionalmente não iniciado.
4. Streamlit iniciado no MESMO processo via `streamlit.web.bootstrap.load_config_options()` + `streamlit.web.bootstrap.run(...)` — as duas únicas funções públicas usadas internamente por `streamlit run`, evitando subprocess e evitando depender de API privada instável (`cli._main_run`).
5. Ao encerrar (sinal, exceção do servidor ou saída normal): `scheduler.stop_scheduler_worker()` e `operator_console.release_instance_lock()` são chamados em `finally`, de forma idempotente.

`scripts/start_production.ps1` foi ajustado para chamar `production_entrypoint.py` em vez de `python -m streamlit run webui/Main.py` diretamente, preservando os mesmos parâmetros operacionais (`address`, `port`, `headless`, CORS, toolbar, usage stats etc.). Nenhum segundo processo de worker, nenhuma segunda Scheduled Task, nenhum "acordar" via navegador/WebSocket falso. A chamada existente da UI a `start_scheduler_worker()` permanece como fallback idempotente (singleton já garantido pelo código existente), sem necessidade de alteração em `webui/Main.py`.

Regressão direcionada: **349 passed; 19 subtests passed; 0 failed** (single-instance, scheduler worker, production health, autonomous production, analytics scheduler + 11 novos testes do entrypoint).

---

## V12-F.1A — Analytics Activation Hardening (21/09/2026)

Implementação concluída **localmente** (`D:\Projetos\MoneyPrinterTurbo`), sem deploy em produção. Analytics Auto Collection permanece `OFF` por default; nenhum setting de produção foi alterado.

Regressão direcionada: **338 passed; 19 subtests passed; 0 failed** (baseline V12-E de 234+19 preservado, mais as suítes de analytics/providers estendidas).

Sete contratos endurecidos em `app/services/analytics_scheduler.py` e `app/services/analytics_providers/*`:

- Coleta automática restrita a YouTube (`SUPPORTED_ANALYTICS_PLATFORMS = ("youtube",)`).
- Privacidade do YouTube fail-closed: PUBLIC comprovado é exigido; PRIVATE e UNKNOWN bloqueiam.
- Deduplicação/revalidação de elegibilidade imediatamente antes de cada chamada ao provider.
- Exclusão mútua entre ciclo manual (`force=True`) e ciclo automático via lock persistido com expiração (stale).
- Revalidação de backoff por publicação antes de cada fetch dentro do mesmo ciclo.
- Sanitização de mensagens de erro de rede/HTTP para nunca expor API key/token/query sensível.
- `DEFAULT_ANALYTICS_AUTO_COLLECTION_ENABLED` passou a ser a fonte real do valor default (antes um literal `"False"` divergente da constante).

**V12-F.1 (auditoria e ativação completa) NÃO está concluída.** O bloqueador de lifecycle/startup identificado aqui foi corrigido pela V12-F.1B (ver seção acima). Ativação real do Analytics Auto Collection em produção continua exigindo decisão e homologação próprias, não incluídas nesta tarefa.

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

**Data de referência:** 21/09/2026

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
- V12-E Autonomous Production Loop — **✅ homologada em produção**
- V12-E.2.1 One-cycle / One-transition hotfix — **homologado**
- V12-E.2.2 Persistent Waiting Schedule Recovery — **homologado**
- V12-F Adaptive Learning + Multi-Channel Warm-Up — **planejamento aberto**
- V12-F.1A Analytics Activation Hardening — **implementado localmente, não deployado; Analytics OFF**
- V12-F.1B Headless Worker Bootstrap — **✅ homologada em produção; Headless gate PASS**
- V12-F.1C Publication Privacy Persistence — **implementado localmente, não deployado; Analytics OFF**

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
`d1a8677`

`de62a4b` é governança de agentes, sem necessidade de deploy para validar a aplicação. `d1a8677` corresponde à V12-F.1B (Headless Worker Bootstrap), homologada em produção com Headless gate PASS.

---

## 6. Configuração segura atual

Estado confirmado após homologação:

- Factory: `RUNNING`
- Primary: `ACTIVE`
- Scheduler: `ON`
- Auto Publish: `ON`
- Dry Run: `OFF`
- Growth Mode: `warmup`
- YouTube: `ON`
- TikTok: `OFF`
- Autonomous Mode: `ON`
- MPT Auto Upload: `OFF`
- YouTube privacy: `public`
- Autonomous max generations / 24h: `5`

---

## 7. Backup mais recente

Backup pré-deploy: `video_factory_20260921_014133.db`.
SHA-256: `79313b694f54000b57d704eadfc8a6e5b1871ac5198e95006ef4890cd82f44a5`.
Integridade: `ok`.

---

## 8. Testes do hotfix em produção

Após atualização para `66f92a4`: **234 passed, 19 subtests passed, 0 failed**, nas oito suítes registradas na seção V12-E.2.2.
Histórico: `08c644f` teve 197 testes PASS em produção.

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

## 13. Histórico do teste V12-E.2.1

Após deploy de `08c644f`, um one-shot criou a task `fdb20c65-76b2-42cc-9c0f-a1764f7237e0`, sobre curiosidades do maior roedor do mundo. O registro anterior capturava GENERATING, Autonomous OFF e 3/5 gerações em 24h. É um snapshot histórico, não uma tarefa atualmente aguardando ação neste handoff.

---

## 14. Regra homologada de transição

Um ciclo autônomo executa uma transição operacional principal e retorna: geração, revisão, agendamento ou recuperação. Rejeitar uma task ou falhar na recuperação não pode gerar outra no mesmo ciclo. A recuperação persistida real ocorreu sem geração indevida.

---

## 15. Gate final da V12-E — PASS

Safety PASS, Quality 78.3/GOOD, Scheduler, Worker/Upload-Post e visibilidade PÚBLICO no YouTube Studio confirmados para `f9b3e05f-a8ce-4c5a-8f6d-e65c46e117ef`. Evidências completas no início deste documento.

Auto Publish e Autonomous contínuo estão ON; TikTok e MPT Auto Upload permanecem OFF.

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

V12-E está fechada; V14 permanece posterior à V12-F e V13, sem implementação nesta tarefa.

---

## 22. Prioridade imediata — V12-F

Planejar V12-F.1: auditar a coleta automática de Analytics existente antes de qualquer ativação. A V12-F inclui coleta automática, closed feedback loop, aprendizado isolado por canal e warm-up controlado do segundo canal; escopo e gates no ROADMAP.

Canal principal: perfil `default` homologado. Segundo canal criado manualmente: **Dose Diária de Histórias e Mistério**, handle **@DoseDiáriadeHistóriasemistério**. Ainda não conectar nem publicar automaticamente. Integração futura pela infraestrutura V9, com perfil/canal, Analytics, histórico e WARMUP separados.

Nenhum código V12-F, schema, configuração, secret ou ambiente de produção foi alterado nesta atualização documental.

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
