# PROJECT_HANDOFF — Video Factory / MoneyPrinterTurbo

> [!IMPORTANT]
> **INSTRUÇÃO OBRIGATÓRIA PARA NOVOS AGENTES / CHATS:**
> Leia este arquivo inteiro antes de sugerir mudanças. Apresente primeiro um **RELATÓRIO DE ALINHAMENTO** contendo:
> - **Fase atual** e **ambientes** (DEV: `D:\Projetos\MoneyPrinterTurbo` / PROD: `C:\Projetos\MoneyPrinterTurbo`);
> - **Último commit/deploy** e **última homologação real**;
> - **Gate atual** e **próximo passo exato**;
> - **Pendências conhecidas** e itens adiados.
>
> Se houver divergência entre este documento e o Git atual, **informe a divergência antes de agir**.

---

## START HERE — ESTADO ATUAL

- **LAST_UPDATED:** `16/10/2026`
- **CURRENT_PHASE:** `V1.5E` (Autonomous Production & Publication Loop) / `WEB_UI_V2`
- **CURRENT_FOCUS:** `R10 RELEASE CONSOLIDADA WEB UI V2 — PACOTE DE DEPLOY CONTROLADO PRONTO`
- **AUTONOMOUS_PILOT_CHANNEL:** `Dose Diária De Internet`
- **FLOW_TRACK:** `ACTIVE (FLOW-MA1: pool multi-contas implementado em DEV; pendente setup PROD)`
- **PROJECT_STATUS:** `ACTIVE_DEV / R10_RELEASE_CANDIDATE_READY`
- **DEV_PATH:** `D:\Projetos\MoneyPrinterTurbo` (Notebook de desenvolvimento — onde alterações de código são feitas com o agente)
- **CURRENT_MAIN_SHA:** `3040278b00c3087ebb9556d25c7cd8b3e2898156` (origin/main)
- **DEV_BRANCH_HEAD_SHA:** `96b9c112bcd912c95ac0ca05de19a6e057059585` (HEAD local em DEV com R9.1 + R9.2 + R9.3 + R10)
- **LAST_PRODUCTION_DEPLOY_SHA:** `c8b14446d008e28c2c006f3e9e140441d9678324` (deployado no PC Forte em 14/10/2026; TTS real confirmado funcionando com edge-tts 7.3.1)
- **CURRENT_GATE:** `R10 CONTROLLED PRODUCTION ROLLOUT PACKAGE (PROD)`
- **R9_1_STATUS:** `DEV VALIDATED (Live Pipeline Telemetry Consolidation: checkpoints em task.py, provedor factual Google Flow/FFmpeg/Voice, progressão no Live Graph desacoplada de aprovação cega de Gates, estado IDLE consistente)`
- **R9_2_STATUS:** `DEV VALIDATED (Multi-Channel Operations & UX: foco manual persistente com toggle dinâmico, sanitização anti-HTML bruto via sanitizeDisplayText, cards factuais de gates no drawer, estados SCHEDULED/RETRY)`
- **R9_3_STATUS:** `COMPLETED / DEV VALIDATED (Homologação Integrada R9.3: Cenários A..F aprovados, correção da precedência de profile_id na descoberta de tarefas ativas multicanal, eliminação de defaults sintéticos em gates completos, 27 testes direcionados PASS, build Vite 7.22s PASS)`
- **R10_STATUS:** `READY_FOR_CONTROLLED_PRODUCTION_DEPLOY (Release Consolidada R10: pacote releases/webui-v2-dist-96b9c11.zip gerado e verificado, runbook atualizado docs/WEB_UI_V2_MIGRATION_RUNBOOK.md, zero migrações de banco, autostart via Task Scheduler porta 8080, Streamlit 8501 preservado)`
- **QG_V2_STATUS:** `DEV VALIDATED (Hotfix QG-V2: Qualidade Inteligente, Duração por Plataforma e Proteção de Créditos; portão editorial prévio antes do despacho Flow, desacoplamento de duração YouTube Shorts [15s-180s] vs TikTok Rewards [>60s], calibração lexical/visual sem redução do threshold 70.0 [REVIEW nunca auto-aprovado], tool read-only scripts/inspect_held_quality_videos.py, 9 testes direcionados PASS)`
- **LAST_REAL_PRODUCTION_VALIDATION:**
  - **Recuperação de Estoque Legado Flow Concluída (11/10/2026):**
    - 4 tarefas legadas foram reavaliadas em produção após deploy do PR #96 com aprovação manual auditável de Copyright (`approve_legacy_task_copyright_op`, vinculada criptograficamente ao SHA-256 de `final-1.mp4`).
    - **Resultados Canônicos dos Gates:**
      1. `1bc4bbbe-fcf5-4e02-a3e3-59b55c4d1f1f` (*"A verdade sobre o orçamento de desenvolvimento de GTA VI revelada pela Rockstar"*, perfil `profile-2095da4fbe23` / *Dose Diária de GTA VI*): Quality 74.6 GOOD, Safety PASS, Copyright PASS (`approval_mode: MANUAL_LEGACY_FINAL_ARTIFACT`) -> **PUBLICADO COM SUCESSO NO YOUTUBE**.
      2. `6f945c8c-4f84-4d3b-b41f-7c4d12f3d8d0` (*"Por que esta cidade na Sibéria obriga todo mundo a ficar dentro de casa às 18h?"*, perfil `profile-historias-misterio` / *Dose Diária de Histórias e Mistério*): Quality 72.7 GOOD, Safety PASS, Copyright PASS (`approval_mode: MANUAL_LEGACY_FINAL_ARTIFACT`) -> **PUBLICADO COM SUCESSO NO YOUTUBE**.
      3. `d8777a50-c18d-4a5d-9c71-9196210cbbd9` (*"Por que a Rockstar demorou mais de 10 anos exatos para anunciar a sequência de GTA V?"*, perfil `profile-2095da4fbe23` / *Dose Diária de GTA VI*): Quality 77.2 GOOD, Safety PASS, Copyright PASS (`approval_mode: MANUAL_LEGACY_FINAL_ARTIFACT`) -> **PUBLICADO COM SUCESSO NO YOUTUBE**.
      4. `807cd444-5cbc-44e7-a597-c28b45b69f05` (*"3 animais que poderiam sobreviver ao apocalipse nuclear"*): Quality 67.8 REVIEW, Safety PASS, Copyright PASS -> **REJEITADO PELO QUALITY GATE** (Não publicado; sem override, sem redução de threshold, sem recolocar no Scheduler).
    - **Ready Stock Confirmado Antes da Publicação:**
      - *Dose Diária de GTA VI*: READY_COUNT = 2 (`d8777a50...`, `1bc4bbbe...`)
      - *Dose Diária de Histórias e Mistério*: READY_COUNT = 1 (`6f945c8c...`)
    - **Scheduler & Reutilização Sem Regeneração:**
      - Os 3 vídeos foram reaproveitados via `Run Cycle` sem regeneração de vídeo (zero desperdício de GPU/créditos).
      - Publicação TikTok permaneceu OFF (`tiktok = OFF`).
      - Os 3 vídeos foram agendados e publicados com sucesso no YouTube via Post For Me (`publication_events status=success`, `scheduled_posts status=published`).
    - **Growth Mode:**
      - Durante a recuperação, os dois perfis foram temporariamente colocados em `SCALE` para remover limitação de slots e permitir a drenagem do estoque existente.
      - Após as publicações: *Dose Diária de Histórias e Mistério* retornou para `WARMUP`.
      - *Dose Diária de GTA VI* permanece temporariamente em `SCALE` aguardando publicação já agendada para 11/10/2026 às 22:11 (ver `TEMPORARY_PRODUCTION_EXCEPTION` abaixo).
- **TEMPORARY_PRODUCTION_EXCEPTION:**
  - **Perfil:** `profile-2095da4fbe23` (*Dose Diária de GTA VI*)
  - **Estado Operacional Vigente:** `growth_mode = SCALE` (TEMPORÁRIO)
  - **Motivo:** Publicação já agendada para **11/10/2026 às 22:11** horário local (a menção anterior a 12/10 às 10:11 estava incorreta).
  - **Decisão Operacional Obrigatória:**
    1. Manter GTA VI em `SCALE` até a publicação das 22:11 ser confirmada em produção no YouTube via Post For Me;
- **CURRENT_GATE:** `WEB_UI_V2_PRE_DEPLOY_GATE_APPROVED / READY_FOR_CONTROLLED_PROD_DEPLOY` (Pendente autorização humana de push para origin/main)
- **FLOW_MA1_STATUS:** `MERGED / READY_FOR_PRODUCTION_DEPLOY` (Pool multi-contas do Google Flow com perfis isolados, failover pré-dispatch, stickiness de tarefa e telemetria de créditos UI-verified + local-estimate)
- **FLOW_UI_001_STATUS:** `DEV VALIDATED` (Telemetria do Google Flow Multi-Account Pool integrada ao Factory Live da Web UI V2; cards compactos, status semântico, saldos verified/estimated/unknown, polling compartilhado, zero mutação)
- **FLOW_CREDIT_002_STATUS:** `DEV VALIDATED` (Extração factual do saldo real de créditos via menu do Google Flow no verify sem consumir créditos nem gerar vídeos)
- **LIVE_PIPELINE_STATUS:** `DEV VALIDATED` (Integração de telemetria real do pipeline na Web UI V2; checkpoints em task.py, fallback de tarefas ativas por canal, provedor factual e progressão viva no Factory Live Graph)
- **R6A_5_STATUS:** `COMPLETED / HUMAN APPROVED` (Checkpoint `14387b021943d1c14b6a8972839a4be31556de8b` aprovado pelo humano; Visual Identity System, single-focus detailed pipeline para escalabilidade, 12 personas, preenchimento tonal, AI Compute Vault do Flow)
- **R6A_6_STATUS:** `COMPLETED / DEV IMPLEMENTED` (Organic Factory Live / Motion Language + 10+ Channel Scalability; rail horizontal responsiva com cards confortáveis 320-430px e scroll-snap, latching de foco imune a polling, componente tech-factory AgentAvatar para as 12 personas consistente entre node e drawer, nodes orgânicos com profundidade tonal e auras localizadas, motion language orientada a estado com FactoryEdge e packets de energia SVG <animateMotion>, hero do pipeline contextualizado com agente ativo factual, superfície elevada do Google Flow e prefers-reduced-motion)
- **AGENT_OPS_V1_1_STATUS:** `COMPLETED / DEV VALIDATED` (Aba independente Agent Ops no Web UI V2 desacoplada do Factory Live. Navegação no header `Factory Live` | `Agent Ops` com URL hash sync, central de operações com 4 papéis visuais, Current Mission Card com elapsed e metadados factuais, feed cronológico sanitizado sem segredos ou prompts, endpoint read-only `GET /api/v2/agent-ops` resolvendo `AGENT_BRIDGE_ROOT`, polling 2s restrito à aba ativa, 13 testes direcionados PASS em `test/services/test_agent_ops.py`)
- **AGENT_OPS_HOTFIX_STATUS:** `COMPLETED (commit b20878c)` — Hotfix de projeção de telemetria refinando unwrapping de `step_update`, eliminação de ruídos, mapeamento de ferramentas do AGY para EXECUTOR, resolução de branch e cálculo factual de `elapsed`.
- **AGENT_BRIDGE_INTEGRATION_STATUS:** `VERIFIED / MVP A10 FROZEN (3586364)` — Primeira missão real delegada com sucesso à fábrica (`doc-sync-handoff-agent-ops`).
- **AUTONOMOUS_PILOT_STATUS:** `PAUSED_PENDING_FLOW_MULTI_ACCOUNT_PRODUCTION_SETUP`
  - **Motivo da Pausa:** Piloto autônomo do canal *Dose Diária de Internet* pausado pelo operador em produção. O hotfix de contrato e fail-safe foi concluído (`READY_FOR_PRODUCTION_DEPLOY`) e a infraestrutura FLOW-MA1 foi implementada em DEV.
  - **Hotfix Autonomous Safety Contract & Precedência de Voz:** `MERGED / READY_FOR_PRODUCTION_DEPLOY`
    - Precedência de voz canônica alinhada à Channel Factory: Global UI (Voz Global da Fábrica salva pelo operador) -> Profile Settings -> Global App -> Safe Default (com canonicalização mantida);
    - Fail-safe cap no getter: Growth Mode define teto máximo inultrapassável (Warmup: 2 aprovados / 8 tentativas; Scale: 5 aprovados / 15 tentativas; override armazenado só pode reduzir, nunca aumentar).
  - **Preservações Obrigatórias em Produção (Zero Manipulação / Zero Reset):**
    - Vídeos aprovados existentes em produção permanecem 100% intactos:
      - `1439ab1b-7dd1-4d76-a507-e3e5416ea5a5` (Quality 75.3, Safety PASS, Copyright PASS, `final-1.mp4` íntegro);
      - `cdc09729-22df-466c-b6d2-50f816d20060` (Quality 71.2, Safety PASS, Copyright PASS, `final-1.mp4` íntegro);
    - Scheduler, `publication_events`, `scheduled_posts` e histórico de publicações preservados.
    - Autonomous do profile default permanece PAUSADO após o deploy.
  - **Diagnóstico TTS e Correção de Streaming Edge TTS (14/10/2026):**
    - **Sintoma:** 5 falhas consecutivas de síntese no canal *Dose Diária de Internet* (`0c8bd081...`, `efa0d660...`, `b6581830...`, `38a61195...`, `d80578f7...`) com erro mascarado em ~2 minutos por tarefa.
    - **Causa Raiz Comprovada:** `edge_tts.Communicate.stream_sync()` na versão 7.2.7 sofre deadlock permanente quando o stream assíncrono lança exceção (ex.: handshake WebSocket HTTP 403 da Microsoft). O wrapper de 30s do MPT convertia qualquer erro real em `TimeoutError`, acumulando 90,05s em 3 tentativas e ocultando a resposta real do provedor.
    - **Correção Implementada (`c5841b4`):** Consumo nativo da API assíncrona `communicate.stream()` em `app/services/voice.py` com loop isolado e timeout determinístico. Falhas de handshake/conexão agora propagam instantaneamente (< 0.05s) com sanitização de tokens e limpeza de arquivos vazios.
    - **Validação Factual em Produção (HEAD `c8b1444`):**
      - `edge-tts 7.2.7`: Falha imediata reportando HTTP 403 Forbidden em 3 tentativas sem travamento de 90s (comprovando o fim do deadlock de streaming).
      - `edge-tts 7.3.1`: **SUCESSO CONFIRMADO na 1ª tentativa** (tempo: 2,16 segundos, arquivo MP3 gerado com 30.096 bytes).
      - Conclusão: a síntese de voz está plenamente operacional em produção com `edge-tts==7.3.1` aliado ao streaming assíncrono nativo (`c5841b4`).
  - **Hotfix de Precedência da Voz Global da Fábrica (14/10/2026):**
    - **Sintoma:** Geração completa do canal *Dose Diária de GTA VI* funcionou e foi aprovada, mas a voz utilizada no vídeo não correspondeu à voz selecionada e salva pelo operador no painel Channel Factory.
    - **Causa Raiz:** A Channel Factory expõe "Voz Global da Fábrica" com a garantia de ser a voz TTS única para todos os canais da fábrica (`config.ui["voice_name"]`). Porém, o onboarding gravava uma cópia da voz no `settings_json` do perfil e `get_generation_profile_context()` avaliava `profile_voice or global_voice`, fazendo com que a voz congelada na criação do canal sobrescrevesse a Voz Global selecionada e salva pelo operador.
    - **Correção:** Em `profile_manager.get_generation_profile_context()`, a precedência foi corrigida para `global_voice or profile_voice or fallback_voice`, garantindo que a Voz Global selecionada e salva em `config.ui['voice_name']` seja soberana para todas as próximas gerações da fábrica, com fallback gracioso para o perfil apenas quando a global estiver vazia. Teste direcionado com duas vozes diferentes confirmou a alternância imediata. Tarefas e vídeos já gerados preservados intactos.
- **CURRENT_PRIORITY:** `WEB_UI_V2 CONTROLLED FIRST DEPLOY (PROD)` / `FLOW-MA1 ONBOARDING (PROD)`
- **WEB_UI_V2_STATUS:** `GATE FINAL PRÉ-DEPLOY APROVADO / READY FOR CONTROLLED PRODUCTION DEPLOY`
- **BLOCKERS:** `NONE` (em DEV); Push autorizado para origin/main e deploy controlado no PC Forte
- **DEFERRED_ITEMS:**
  - `CFG-005 — YouTube-only destination using cross_platform preset`:
    - **Descrição:** O destino operacional atual é YouTube-only, porém o preset `cross_platform` mantinha restrições de TikTok Rewards e causava rejeições desnecessárias (ex.: task de 48s rejeitada pelo Safety Gate porque Cross Platform exigia >= 60s).
    - **Status:** `RESOLVIDO EM DEV (HOTFIX QG-V2)`. Desacoplada a duração de YouTube Shorts (15s a 180s permitidos com nota informativa) das restrições de TikTok Rewards (>60s). Vídeos de YouTube Shorts < 60s agora recebem PASS no Safety Gate e pontuação adequada no Quality Score quando TikTok está OFF.
  - `GLOBAL_VS_PROFILE_GROWTH_MODE_UI_CONFUSION`: Existe seletor global de Growth Mode no Streamlit que pode mudar o estado visual exibido, mas não altera efetivamente o Growth Mode operacional dos perfis. A fonte operacional canônica real é o Growth Mode configurado por perfil/canal (`profile growth_mode`). Exemplo confirmado em produção: *Dose Diária de GTA VI* com perfil em `SCALE` é considerado como `SCALE` pelo Scheduler e Autonomous loop. Portanto: `GLOBAL GROWTH MODE UI != FONTE OPERACIONAL CANÔNICA`.
    - **Decisão:** `DEFERRED / NÃO BLOQUEIA PRODUÇÃO`. Não corrigir agora, não remover agora, não alterar backend agora. Mapeado no checklist de migração como `UI-001` e `UI-002`.
  - `WEB_UI_V2 / STREAMLIT_REPLACEMENT_EVALUATION`: Streamlit atualmente apresenta lentidão operacional perceptível devido ao crescimento da aplicação e reruns amplos da interface.
    - **Decisão:** `DEFERRED / BACKLOG FUTURO`. Mapeado no checklist de migração como `UI-003`.
- **MIGRATION_CHECKLIST_STATUS:** ATIVO em [docs/ROADMAP.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/ROADMAP.md#web-ui-v2--code-consolidation--migration-checklist) e especificado detalhadamente em [docs/WEB_UI_V2.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/WEB_UI_V2.md). Contém os itens `UI-001`, `UI-002`, `UI-003`, `UI-004`, `UI-005`, `CFG-004` e `CFG-005`.
- **R4A_WEB_UI_V2_DISCOVERY_STATUS:** Concluído documentalmente em paralelo ([docs/WEB_UI_V2.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/WEB_UI_V2.md)), mapeando o monólito Streamlit (14.315 linhas, 34 funções operacionais e proposta de API fina FastAPI preservando backend), com ZERO alteração funcional, ZERO impacto no banco operacional e ZERO interferência no piloto autônomo em andamento.
- **R5B_LIVE_EXECUTION_CONTRACT_STATUS:** Concluído em DEV (`feat/web-ui-v2-read-api`), contrato read-only e causal para tela Factory Live (UI-005) com 2 novos endpoints GET (`/api/v2/executions/live` e `/api/v2/executions/{task_id}`), grafo de 12 estágios, zero inferência, UI-004 resolvido canonicamente, teste direcionado 15/15 PASS.
- **R6A_WEB_UI_V2_FACTORY_LIVE_STATUS:** Concluído em DEV (`feat/web-ui-v2-read-api`), primeira interface desacoplada Web UI V2 em `webui-v2/` (React 18, Vite 6, `@xyflow/react` v12, Vanilla CSS) com tela Factory Live (cards de canal dinâmicos, grafo em lanes horizontais dos 12 estágios, trace causal e drawer de execução com terminal YouTube state, polling 3s, build PASS 112 kB gzip; zero alteração no backend ou Streamlit). NEXT_GATE de produção permanece estritamente `AUTONOMOUS_CYCLE_E2E_HOMOLOGATION` no PC Forte.
- **R6B_OPERATIONAL_CONTROLS_STATUS:** `COMPLETED / DEV VALIDATED` — Controles operacionais e de despacho entregues: endpoints `GET /api/v2/channels`, `POST /api/v2/factory/pause`, `POST /api/v2/factory/resume`, `POST /api/v2/factory/run-cycle` com 19/19 testes unitários direcionados PASS em `test/services/test_web_ui_v2_api.py`; integração frontend completa em `webui-v2/` (`api.js`, `FactoryHeader.jsx` e `ExecutionDrawer.jsx`) com despacho global e por canal, diálogos de confirmação inline e feedback de erro/sucesso.
- **R7_PHASE_1_STATUS:** `COMPLETED / DEV VALIDATED` — Migração dos controles canônicos de Growth Mode (`WARMUP` / `SCALE`) e Autonomia (`AUTO` / `MANUAL`) por perfil/canal. Endpoints backend canônicos: `PATCH /api/v2/channels/{profile_id}/growth-mode`, `PATCH /api/v2/channels/{profile_id}/autonomous` (com aliases `/profiles/{profile_id}` e `POST .../enable`, `.../disable`) respeitando estritamente a autoridade de produção (`require_primary_instance` 403), autenticação (401), validação de payload (400) e checagem de perfil (404). Suíte direcionada `test/services/test_web_ui_v2_api.py` expandida para 28 testes (100% PASS em 12.93s). Frontend `webui-v2/` integrado: `api.js` (`updateProfileGrowthMode`, `updateProfileAutonomousMode`), `ExecutionDrawer.jsx` (painel de controle operacional de Growth Mode e Autonomia com feedback inline) e `ChannelCard.jsx` (badges AUTO/MANUAL e GROWTH MODE interativos com jump direto ao drawer). Build Vite 6 100% PASS (dist limpo, zero erros).
- **R7_PHASE_2_STATUS:** `COMPLETED / DEV VALIDATED` — Migração das configurações de agendamento, janelas de publicação e quotas por perfil. Endpoints backend canônicos implementados em `operations.py`: `GET /api/v2/channels/{profile_id}/settings`, `PATCH /api/v2/channels/{profile_id}/settings`, `PATCH /api/v2/channels/{profile_id}/quotas`, `PATCH /api/v2/channels/{profile_id}/schedule` (todos com alias `/profiles/{profile_id}/...`). Validação estrita de limites de estoque (`target_ready_stock` 3..6), gerações diárias (1..5), tentativas de geração (1..15), posts por dia e horários de início/fim de publicação (0..23, com end >= start). Planejador de `scheduler.py` atualizado para respeitar deterministicamente a janela de publicação de cada perfil, ajustando slots fora da janela para o horário inicial permitido. Suíte de testes direcionados `test/services/test_web_ui_v2_api.py` expandida de 28 para 36 testes (100% PASS em 17.37s). Frontend `webui-v2/` integrado: `api.js` (métodos `getProfileSettings`, `updateProfileSettings`, `updateProfileQuotas`, `updateProfileSchedule`), `ExecutionDrawer.jsx` (subcards interativos para Quotas e Janela de Publicação com dropdowns, botões numéricos rápidos e botão de salvar com feedback em tempo real). Build Vite 6 100% PASS (dist limpo, zero erros). Verificação DEV ativa em `http://127.0.0.1:5173/` (frontend) e `http://127.0.0.1:8080` (backend).
- **R8_STATUS:** `COMPLETED / DEV VALIDATED` — Consolidação da Web UI V2 e preparação segura para execução em produção no PC Forte.
  - **Servidor Same-Origin:** FastAPI (`app.asgi:app`) integrado para servir estáticos do Vite (`webui-v2/dist/`) via `SPAStaticFiles` na mesma origem das rotas `/api/v2/...`, com fallback limpo para `index.html` em rotas client-side sem extensão (ex.: `/agent-ops`) e HTTP 404 estrito para assets ausentes. Fallback gracioso para `resource/public` se o build não existir.
  - **Verificação de Saúde (Health Check):** Dois endpoints dedicados implementados: `GET /health` (infraestrutura/não-autenticado reportando status healthy, versão e disponibilidade do build) e `GET /api/v2/health` (operacional reportando papel PRIMARY/SECONDARY, `same_origin=True` e integridade da fábrica).
  - **Script de Inicialização de Produção:** Criado `scripts/start_webui_v2.ps1` com bind 0.0.0.0 na porta 8080, logging operacional em `storage/logs/webui_v2/`, verificação automática de build e convivência pacífica com o Streamlit legado na porta 8501.
  - **Runbook Operacional de Migração:** Criado `docs/WEB_UI_V2_MIGRATION_RUNBOOK.md` detalhando build, inicialização, verificação, segurança, coexistência e rollback seguro no PC Forte sem tocar na produção durante o desenvolvimento.
  - **Validação de Testes:** Suíte direcionada `test/services/test_web_ui_v2_api.py` com 42 testes (100% PASS em 25.92s). Smoke test live via HTTP 200 confirmado no endpoint `/`, assets JS/CSS e rotas `/api/v2/...`.

- **WEB_UI_V2_PRE_DEPLOY_GATE (15/10/2026):** `STATUS = READY`
  - **1. Auth Safety (Sem Exposição de Credenciais na URL):**
    - Se `?api_key=...` for fornecido na URL, a Web UI V2 armazena a chave em `sessionStorage` e **remove imediatamente o parâmetro da barra de endereços** através de `window.history.replaceState()`, eliminando o risco de vazamento em logs de proxy, tráfego ou histórico do navegador.
    - Se a API retornar HTTP 401 Unauthorized no browser, um prompt nativo interativo (`window.prompt`) solicita a API Key ao operador, grava em `sessionStorage` e refaz a requisição de forma transparente, sem credenciais na URL.
  - **2. Dual-Process Safety (Coexistência Segura FastAPI 8080 & Streamlit 8501):**
    - O processo FastAPI (`main.py` -> `app.asgi:app`) não inicializa workers de scheduler (`scheduler.start_scheduler_worker()` nunca é chamado). O scheduler continua exclusivo da instância PRIMARY (Streamlit).
    - Se o Streamlit na porta 8501 possuir o lock de instância SQLite (`ROLE_PRIMARY`), o FastAPI entra compulsoriamente em `_enter_view_only()` (`ROLE_SECONDARY_VIEW_ONLY`).
    - Todas as rotas de mutação (`POST /api/v2/factory/pause`, `POST /api/v2/factory/resume`, `POST /api/v2/factory/run-cycle`, `PATCH /api/v2/channels/...`) exigem estritamente `require_primary_instance()` e são rejeitadas com HTTP 403 `PermissionError` em modo secundário. Leituras (`GET`) continuam 100% ativas e funcionais.
    - É estritamente impossível existirem duas autoridades PRIMARY ou mutações concorrentes descontroladas.
  - **3. Rollback Seguro (Sem Detached HEAD):**
    - Procedimento de rollback atualizado em `docs/WEB_UI_V2_MIGRATION_RUNBOOK.md`. Proibido categoricamente o uso de `git switch --detach` ou `git checkout <SHA>` no PC Forte.
    - Como a R8 é puramente aditiva (sem alteração de banco SQLite nem impacto no runtime do Streamlit), o rollback operacional consiste unicamente em parar o processo na porta 8080 (CTRL+C ou encerramento do PID registrado em `storage/logs/webui_v2/webui_v2_startup.log`). O Streamlit permanece 100% operacional.
    - Rollback de código, se necessário no futuro, deve ser feito via commit/revert em DEV e puxado via `git pull --ff-only origin main` no PC Forte.
  - **4. Deploy Source Availability:**
    - Branch `main` remota (`origin/main`) está 100% sincronizada com `c64e9bf9fa390794a53e50017c68f9e7456da4f0`.
    - **Pacote de Distribuição Sem Node.js Gerado em DEV:**
      - Arquivo: `releases/webui-v2-dist-c64e9bf.zip` (139.13 KB / 142.473 bytes)
      - SHA-256: `0db1af19c0a0abd54c8d5fc821110f3828609eb5e2fe15b9d785659c9b76d0d2`
      - Checksum: `releases/webui-v2-dist-c64e9bf.zip.sha256`
      - Script gerador/validador: `scripts/package_webui_v2.ps1`
      - Conteúdo: `dist/index.html`, `dist/assets/*.js`, `dist/assets/*.css`, `manifest.json`, `INSTALL.md`

### Comandos Canônicos de Deploy Sem Node.js (PC Forte):

Executar no PC Forte (`C:\Projetos\MoneyPrinterTurbo`) com o Streamlit em execução na porta 8501:

```powershell
# 1. Puxar as atualizações da main de forma limpa (sem detached HEAD)
cd C:\Projetos\MoneyPrinterTurbo
git pull --ff-only origin main

# 2. Copiar webui-v2-dist-c64e9bf.zip para C:\Projetos\MoneyPrinterTurbo\webui-v2
# Validar o checksum SHA-256 do pacote:
$ExpectedHash = "0db1af19c0a0abd54c8d5fc821110f3828609eb5e2fe15b9d785659c9b76d0d2"
$ActualHash = (Get-FileHash -Path ".\webui-v2\webui-v2-dist-c64e9bf.zip" -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash) {
    Write-Error "FALHA DE INTEGRIDADE: SHA-256 divergente do pacote!"
    exit 1
}
Write-Host "Integridade do pacote verificada com sucesso (PASS)." -ForegroundColor Green

# 3. Descompactar os artefatos compilados em webui-v2\dist (sem Node.js em produção)
$WebUiDist = "C:\Projetos\MoneyPrinterTurbo\webui-v2\dist"
if (Test-Path $WebUiDist) {
    Remove-Item -Path $WebUiDist -Recurse -Force
}
New-Item -ItemType Directory -Path $WebUiDist -Force | Out-Null

Expand-Archive -Path ".\webui-v2\webui-v2-dist-c64e9bf.zip" -DestinationPath ".\webui-v2\temp_extract" -Force
Copy-Item -Path ".\webui-v2\temp_extract\dist\*" -Destination $WebUiDist -Recurse -Force
Remove-Item -Path ".\webui-v2\temp_extract" -Recurse -Force

# 4. Validar os artefatos instalados
Test-Path "$WebUiDist\index.html"
Test-Path "$WebUiDist\assets"

# 5. Registrar e iniciar a Scheduled Task persistente (inicia no boot, sem janela interativa):
.\scripts\register_webui_v2_task.ps1

# 6. Validar os endpoints de saúde e conformidade SECONDARY_VIEW_ONLY
Invoke-RestMethod -Uri "http://127.0.0.1:8080/health"
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
```

#### Procedimento de Rollback no PC Forte:
Caso seja necessário desativar e desregistrar a Web UI V2:
```powershell
# Desregistra a Scheduled Task e encerra processos na porta 8080 de forma limpa:
.\scripts\register_webui_v2_task.ps1 -Unregister

# O serviço principal VideoFactory Production (Streamlit na porta 8501) permanece 100% intacto e operacional.
# NUNCA execute git switch --detach ou git checkout no PC Forte.
```



### Recuperação de Tarefas Google Flow Legadas (CONCLUÍDA):
- **Causa Raiz & Contexto de Produção:** O PR #95 implementou fallback automático a partir do `flow/manifest.json`, mas a validação real em produção revelou que as 4 tarefas candidatas eram **HÍBRIDAS** (6 clipes Google Flow premium + cenas stock legadas cujos arquivos e provedores não foram persistidos). Sem evidência suficiente para reconstrução determinística sem inventar dados, o operador revisou e aprovou manualmente os 4 artefatos finais completos via PR #96 (`approve_legacy_task_copyright_op`), vinculados ao SHA-256 do `final-1.mp4`.
- **Resultado Operacional Final:**
  - 3 tarefas aprovadas em todos os gates e **PUBLICADAS COM SUCESSO NO YOUTUBE** (`1bc4bbbe...`, `6f945c8c...`, `d8777a50...`).
  - 1 tarefa (`807cd444...`) **REJEITADA PELO QUALITY GATE** (Quality 67.8 < 70) — sem override manual, sem alteração de thresholds e sem recolocação no Scheduler (fail-closed respeitado).
  - Ready Stock das tarefas legadas completamente drenado/publicado.
  - Perfis restaurados para **Growth Mode = WARMUP**.
### FLOW-MA1 — Multi-Account Provider Pool & Telemetria de Créditos (CONCLUÍDO):
- **Implementação:** `app/services/flow_account_pool.py`, `scripts/flow_playwright.py`, `test/services/test_flow_account_pool.py`.
- **Princípios Canônicos:**
  - **user_data_dir separado por conta:** Cada conta cadastrada possui seu próprio diretório de perfil persistente (`storage/flow_browser_profiles/<account_id>/`). A conta primária legada (`flow-primary`) preserva estritamente `storage/flow_browser_profile` (sessão atualmente homologada).
  - **Onboarding Canônico de Novas Contas (FLOW-MA1-HOTFIX):**
    - Fluxo obrigatório: `ADD` → `LOGIN VIA EDGE NORMAL` → `FECHAR EDGE` → `VERIFY HEADLESS` → `AUTHENTICATED`
    - 1. Adicionar: `python -m app.services.flow_account_pool add --account-id <id> --display-name "..."`
    - 2. Login humano: `python -m app.services.flow_account_pool login --account-id <id>` (abre Microsoft Edge NORMAL com `--user-data-dir` isolado; zero Playwright; login manual pelo operador)
    - 3. Fechar completamente a janela do Microsoft Edge após o login
    - 4. Validar: `python -m app.services.flow_account_pool verify --account-id <id>` (valida sessão persistida via Playwright HEADLESS; zero manifest, zero geração, zero consumo de crédito)
    - **Regra Explícita de Segurança Google:** O login Google inicial NÃO deve ser executado pelo Playwright (evita bloqueio do Google por navegador potencialmente inseguro).
  - **Zero senhas/segredos no projeto:** Nenhuma senha, token, chave de API ou cookie do Google é armazenado no repositório, em arquivos JSON ou no banco de dados. Os cookies e sessões residem exclusivamente dentro do perfil local do Microsoft Edge.
  - **Task stickiness:** Uma tarefa/projeto do Flow fica vinculada estritamente à conta atribuída no `manifest.json` (`flow_account_id`). Após criação do projeto (`flow_project_url`), conclusão de qualquer cena ou confirmação de início de geração/aprovação de créditos, a conta é imutável.
  - **Failover seguro somente pré-dispatch:** Failover automático para a próxima conta elegível no pool só é permitido antes do consumo ou início de geração (máximo 1 tentativa automática de failover por cena).
  - **Flow permanece single-flight:** Concorrência global mantida em 1 através de `FLOW_CONCURRENCY_LOCK`. Zero paralelismo de navegadores ou consumo simultâneo.
  - **Telemetria de créditos confiável:**
    - `FLOW_UI_VERIFIED` quando o saldo restante é lido diretamente da interface do Flow (menu da conta / UI);
    - `LOCAL_ESTIMATE` após consumo confirmado de créditos até a próxima leitura na UI;
    - `UNKNOWN` quando não houver evidência textual inequívoca;
    - **Regra de Ouro:** NUNCA inventar créditos, nunca assumir 1000, nunca tratar UNKNOWN como erro fatal.
  - **Detecção conservadora de esgotamento:** Se houver evidência visível e inequívoca de créditos insuficientes no DOM antes do dispatch, a conta é marcada como `EXHAUSTED` com zero aprovação e zero clique no Generate.
  - **CLI Operacional Mínimo:** Suporte a `python -m app.services.flow_account_pool` com comandos `list`, `add`, `login`, `verify`, `disable`, `enable`, `status`.
- **FLOW-UI-001 (CONCLUÍDO EM DEV):**
  - **Status:** `DEV VALIDATED` (Commit `8bc7b3d`).
  - **Entrega:** Telemetria de contas Google Flow integrada ao Factory Live via snapshot compartilhado de `executions/live` (display name, status operacional, créditos verified/estimated, última verificação).
- **FLOW-CREDIT-002 (CONCLUÍDO EM DEV):**
  - **Status:** `DEV VALIDATED` (Commit `7687f1f`).
  - **Entrega:** Extração factual de créditos no verify sem consumir créditos nem gerar vídeos.

### Histórico Recente de Merges no Main:
- **`fix(voice): enforce global ui voice precedence over stored profile settings`**: Hotfix alinhando a precedência em `get_generation_profile_context` para que a Voz Global da Fábrica selecionada e salva pelo operador em `config.ui['voice_name']` prevaleça sobre a voz legada/congelada do perfil (ex: GTA VI).
- **`5bdb1ec` (`fix(deps): update edge-tts to 7.3.1`)**: Fix definitivo da dependência alinhando pyproject.toml, requirements.txt e uv.lock com a versão 7.3.1 confirmada funcional em produção (2,16s / 30.096 bytes).
- **`c8b1444`:** `docs: record edge-tts streaming hotfix in PROJECT_HANDOFF`
- **`c5841b4`:** `fix(voice): consume native edge-tts async stream to prevent sync deadlock and propagate errors` — Elimina deadlock upstream de `edge_tts.Communicate.stream_sync()` ao consumir nativamente `communicate.stream()` assíncrono em loop dedicado com timeout, propagação imediata de erros de rede/handshake (<0.05s) e cleanup de áudio vazio.
- **`050ba86`:** `fix(voice): expose sanitized tts failure diagnostics and persist in task state` — Sanitização de URLs/tokens no diagnóstico TTS e persistência no estado da tarefa (deployado no PC Forte em 14/10/2026).
- **`a44f2d3`:** `fix(autonomous): allow up to 5 approved generations in 24h for warmup replenishment` — Permite até 5 gerações aprovadas em 24h para reposição no warmup (deployado no PC Forte).
- **`c07ab33` / `aa8ae8c` / `663bb1f`:** Web UI V2 endpoints de controle da fábrica (pause, resume, run-cycle) integrados na main.
- **`3f8b096`:** `docs: record flow-ma1 merged and autonomous pilot paused pending production setup`
- **`b8c0904`:** `fix: use native edge for flow account onboarding` — Login humano inicial Google via Edge nativo, sem automação Playwright.
- **`3426271`:** `feat: add flow multi-account provider pool` — Pool multi-contas do Google Flow (`app/services/flow_account_pool.py`).
- **`b75f488`:** `fix: enforce autonomous profile safety contract` — Fail-safe cap no getter e precedência de voz estrita.
- **PR #96 (`1702e8b`):** `fix(copyright-gate): manual audit approval bound to final artifact SHA-256 for legacy hybrid tasks` — Deployado e homologado no PC Forte em 11/10/2026.

### Histórico Recente de Entregas em DEV (`feat/web-ui-v2-read-api`):
- **`R6B_FRONTEND_DISPATCH`:** `feat(webui-v2): integrate factory run-cycle operational dispatch controls` — Integração completa no frontend Web UI V2 em `webui-v2/src/api.js`, `FactoryHeader.jsx` e `ExecutionDrawer.jsx` com disparo global e por canal, diálogos de confirmação inline e feedback de erro/sucesso.
- **`c07ab33`:** `feat(api-v2): add factory run-cycle endpoint for supervised operations` — Endpoint `POST /api/v2/factory/run-cycle` com suporte a profile/channel scoping, validações de lock e concorrência 409/403.
- **`aa8ae8c`:** `feat(webui-v2): integrate factory pause and resume controls in header` — Botão Pause/Resume integrado ao header com confirmação inline.
- **`663bb1f`:** `feat(api-v2): add factory pause and resume endpoints for web ui v2` — Endpoints `POST /api/v2/factory/pause` e `/resume`.
- **`6f68f71`:** `feat(api-v2): add read-only channels overview endpoint for web ui v2` — Endpoint `GET /api/v2/channels` consolidado.
- **`b20878c`:** `fix(webui): improve agent ops telemetry projection` — Hotfix na projeção read-only da telemetria Agent Ops: unwrapping do stream-json (`step_update`), mapeamento de ferramentas para EXECUTOR, eliminação de ruídos (collapse ACTIVE/DONE), derivação factual de elapsed (zero 00:00 falso), resolução de branch por payload e 13 testes unitários PASS em `test/services/test_agent_ops.py`.
- **`4fbbd2f`:** `feat(webui): add agent ops live telemetry view` — Tela desacoplada Agent Ops com feed em tempo real, 4 agentes operacionais e endpoint `GET /api/v2/agent-ops`.
- **`40ed659`:** `feat(webui): evolve factory live motion and channel scalability` (R6A.6) — Motion language orgânica com SVG `<animateMotion>`, rail horizontal responsiva e cards 320-430px.
- **`aed67c9`:** `feat(webui): R6A.5 visual identity system, personas, and single-focus pipeline` — Single-focus pipeline, 12 personas tech-factory e AI Compute Vault.
- **`2caa0c2`:** `feat(webui): R6A.3 visual identity, real metrics, and multi-channel live rendering` — Layout dinâmico multicanal e métricas factuais sem denomidador falso.

### PC Forte Production Runtime Contract:
- **Python via .venv**: Operação e pacotes restritos ao ambiente virtual do projeto;
- **Dependências sincronizadas**: Safe updater detecta divergências de dependências obrigatórias e sincroniza determinísticamente no `.venv`;
- **Playwright obrigatório**: Exigido no readiness check correspondendo exatamente ao requisito declarado em `requirements.txt` (`playwright==1.63.0`) quando Flow estiver habilitado;
- **Edge msedge obrigatório**: Canal Microsoft Edge (`msedge`) validado passivamente no host Windows;
- **Flow headless canônico**: Automação padrão opera estritamente com `headless=True` em produção; modo `headless=False` disponível para diagnóstico DEV;
- **Perfil Flow persistente**: Sessão Google autenticada preservada em `storage/flow_browser_profile`;
- **Execução Windows e Scheduled Task (`VideoFactory Production`):**
  - **VALIDADO:** `User = DESKTOP-21KQ4RJ\bob`, `LogonType = Interactive`, `headless=True`, `Flow AUTHENTICATED` = **PASS**;
  - **TARGET PENDENTE DE HOMOLOGAÇÃO:** `User = DESKTOP-21KQ4RJ\bob`, *Run whether user is logged on or not*, `LogonType = Password` (credencial protegida pelo Windows Task Scheduler, zero senhas em arquivos/scripts/repositório), `Flow headless=True`. Autonomia pós-reboot permanece pendente de homologação;
- **Políticas de publicação**: Auto Publish permanece OFF, Scheduler permanece OFF durante homologação, TikTok permanece OFF.

### Destaque da Frente Google Flow / Qualidade Visual:
- **V1.4_FLOW_AUTOMATION** = CONCLUÍDA / HOMOLOGADA
  - Engine Flow: `Playwright Python 1.63.0` + Edge `msedge`.
  - Capacidades: single-flight sequencial, idempotência estrita com zero browser em clipes válidos, resume de cenas pendentes, checkpoints atômicos (`atomic_write_json`), recovery pós-consumo (`FLOW_GENERATION_NEEDS_RECOVERY`), isolamento multi-tile com identificador seguro ASB hash SHA-256, pipeline source-aware Flow/stock, fallback configurável (strict por padrão / fallback_stock).
- **V1.3_AGENT_DIRECTOR** = CONCLUÍDA
  - Vídeo real validado: `storage/manual_media/terra_parou_5s/final/terra_parou_5s_final.mp4` (69s, 25.28 MB).
  - Nicho `curiosidades_ciencia` validado com sucesso (expansão multi-nicho).
  - 4 clipes Google Flow Premium preservados + 4 cenas stock filler resolvidas contextualmente via Coverr.
  - Novo padrão visual estabelecido: `DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT = 6` (6 cenas Flow por Short para produções futuras).
- **V1.2_MANUAL_FLOW_OPTIMIZATION** = CONCLUÍDA
- **Runner Padronizado:** `scripts/flow_workflow.py`
- **Validação Direcionada:** 4 PASS (`test/services/test_flow_workflow.py`)
- **Fricções Eliminadas:**
  - Preparação automatizada de prompts visuais para Google Flow (9:16 portrait em `prompts_for_flow.md`).
  - Divisão de cenas temporizada e alinhamento com narração via `scene_planner`.
  - Padronização de estrutura de diretório e nomenclatura (`manifest.json`, `clips/flow_scene_XX.mp4`).
  - Ingestão simplificada e montagem em comando único (`render` com suporte a `--dry-run` e fallback contextual via Coverr).
  - Suporte resiliente a credenciais de ambiente e registro de usuário sem expor segredos.
- **V1.1_FIRST_REAL_VIDEO** = CONCLUÍDA / HOMOLOGADA (Commit `65ff981`, 90.50s)
- **QUALITY_BASELINE** = APROVADA
- **PUBLICÁVEL** = SIM
- **DURATION** = 90.50s
- **Próxima Fase:** `V1.5_VISUAL_DIRECTOR`
  - Direção visual contextual e planejamento autônomo de cenas Flow.
- **Visão Futura:**
  - `FUTURE_MULTI_CHANNEL_MULTI_NICHE = planned` (uma única Video Factory atendendo múltiplos canais/nichos, sem forks por canal).
  - `FUTURE_LONG_FORM_VIDEO = planned`
  - `FUTURE_FLOW_API_AUTOMATION = evaluate_later`
  - `FUTURE_LOCAL_VIDEO_AI = evaluate_after_hardware_upgrade`

> [!IMPORTANT]
> **Precedência Canônica:** Esta seção reflete o estado consolidado e auditado da fábrica de vídeos em produção no PC forte (`C:\Projetos\MoneyPrinterTurbo`). Ela prevalece formalmente sobre quaisquer menções ou snapshots históricos contidos nas seções inferiores deste documento.

### Status Consolidado dos Componentes:
- **Google Flow / External Video Quality Track** = ACTIVE (CURRENT_FOCUS)
- **V1.1 First Real Video Workflow** = CONCLUÍDA / HOMOLOGADA (Commit `65ff981`, 90.50s)
- **V1.2 Manual Flow Optimization** = CONCLUÍDA / HOMOLOGADA (`scripts/flow_workflow.py`)
- **V1.3 Agent Director Assistance** = CONCLUÍDA / HOMOLOGADA (vídeo `terra_parou_5s_final.mp4` gerado no nicho `curiosidades_ciencia`; padrão de 6 cenas Flow por Short estabelecido)
- **V1.4 Autonomous Flow Pipeline** = CONCLUÍDA / HOMOLOGADA (Playwright 1.63.0 + Edge `msedge`)
- **V1.5 Visual Director** = PLANNED (NEXT_PHASE)
- **V16.0 Quality Audit** = DONE
- **V16.1 Brazilian Content Contract** = PRODUCTION HOMOLOGATED (Deploy SHA: `3983d37a29d1f169e513f19bd7186348a74ad5e9`)
- **V16.2 Subtitle Reliability Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `0744fd2b8593fa276a2d3117d88b270475b5b05c`)
- **V16.3 Final Media Quality Gate** = PRODUCTION HOMOLOGATED (Deploy SHA: `9e3fde0b35e28781aab67117d5ff33c182b337ef`)
- **V16.4 Scene-Based Video Generation** = PRODUCTION HOMOLOGATED
- **V16.4.1A Scene Render Performance Hardening** = PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **V16.4.1B Final Render Performance** = PRODUCTION HOMOLOGATED (Deploy SHA: `e7f40ed6f4b7df45e5868cd7de03495239d103ec`, Task Homologada: `f9a9608b-512d-43c4-92f4-f864a0424512`)
- **V16.4.1C Render Pipeline Gap Instrumentation** = PRODUCTION HOMOLOGATED (Deploy SHA: `d231e3900bbbace180c0c71e60e9fb08c2d713e0`, Task Homologada: `337639bb-1740-4398-a923-c5f75b1f236a`)
- **V16.4.1D Post-Encode Performance Investigation** = MERGED (Deploy SHA: `d13d9347fc96c6a967561821552bbb19452eb281`, PR #45)
- **V16.4.2R Pre-Repair Publishing Reset** = PRODUCTION HOMOLOGATED (Deploy SHA: `83be45cb95fc5c8b74c43844621ebf9c6d328b9c`, PR #48)
- **V16.4.2A Publishing State Reconciliation** = PRODUCTION HOMOLOGATED (PC Forte Reconciled)
- **V16.4.2B Publishing Idempotency / Duplicate Protection** = MERGED (PR #50)
- **V16.4.2C Retry Metadata Cleanup** = MERGED (PR #51)
- **V16.5 Visual Matching v2** = MERGED (PR #53, SHA `b6e900ed93edb6e0e59c00600532f7ca2afeb6bd`)
- **V16.5.1 Subtitle & Narration Quality Recovery** = MERGED (PR #54, SHA `4823a799d3030982d27e0eeccea1ab3f73a065f7`)
- **V16.6 Hybrid Visual Generation Foundation** = MERGED (PR #55)
- **V16.6.1 Open Source Video Benchmark Preparation** = DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS
- **V16.6.2 Contextual Image-to-Video Foundation** = MERGED (PR #56, SHA `0264fb7daaf327e1677cc209cd20308a9af6c8ce`)
- **V16.7 Hybrid Scene Director** = MERGED (PR #57, SHA `ae6738821516d3310493060654d4a8776bc74548`)
- **V16.8 Controlled Hybrid Render Validation** = DEV_VALIDATED / STRUCTURAL_AND_PROXY_PASS (PR #58, SHA `fd205f24275a43ab67486e9261cd6b45cfbfd4d8`)
- **V16.8.1 Real Generated Image Quality Gate** = REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED
- **V16.8.2 Alternative Visual Sources Evaluation** = DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)
- **V16.9 Final Hybrid Pipeline Foundation** = DEV_COMPLETE / CONSOLIDATED
- **V16.10 Single Full DEV Render** = DEV_HOMOLOGATED / READY_FOR_PRODUCTION_DEPLOY
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
- **Presenter autonomous**: OFF (`avatar_mode="none"`)
- **TikTok**: OFF / NOT HOMOLOGATED
- **V15-A Production Observability Baseline** = DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET
- **V15-E.1 YouTube Direct Foundation** = HOMOLOGATED (POC Validada nos 2 Canais)
- **V15-E.2 Post for Me YouTube Publisher** = DEV IMPLEMENTED / READY FOR POC HOMOLOGATION

### Produção Atual (Estado Operacional Consolidado):
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
- **Safe updater** = ACTIVE (`scripts/update_production.ps1`)

**Última homologação real de produção (V13-B):**
- TARGET/FINAL_SHA: `46e44c2495a8fe38484977ad1aa7cff439e26679`
- BACKUP: PASS (`storage/backups/database/video_factory_20260923_061728.db`, SHA-256: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`)
- SQLITE_INTEGRITY: OK
- STOP: PASS
- FF UPDATE: PASS
- START: PASS
- HEALTH: PASS (HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`)
- ROLLBACK: NOT_REQUIRED
- DEPLOY: SUCCESS
- Documentação posterior: main `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`

---

## V15 — Production Observation & Optimization — OPEN / OBSERVATION FIRST

- **Baseline Main:** `d88578d5131b41c7b56e435e7d6a3e3a87b27fbc`
- **Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
- **Status da Fase:** OPEN / OBSERVATION FIRST
- **Princípio Operacional:** Observar a fábrica completa em funcionamento real no PC forte antes de adicionar novas features.
  - Metodologia: `OBSERVAR → MEDIR → IDENTIFICAR GARGALO REAL → PRIORIZAR → OTIMIZAR`
  - Evitar rigorosamente: otimização prematura, novos providers, novos avatares, novos canais, TikTok ou aumento de volume sem evidências.
- **Subfase Ativa:** **V15-A — Production Observability Baseline**
  - **Status:** DEV IMPLEMENTED / NOT PRODUCTION OBSERVED YET
  - **Implementação Realizada:**
    1. Serviço read-only criado: `app/services/production_observability.py` com função `get_production_observability_snapshot()`.
    2. Coleta passiva completa das 9 dimensões operacionais para os dois canais (`default` e `profile-historias-misterio`).
    3. Alertas factuais observáveis sem score arbitrário: `READY_STOCK_EMPTY`, `COPYRIGHT_BLOCKED`, `SCHEDULER_FAILURES_PRESENT`, `CLOSED_LOOP_BASELINE`, `ANALYTICS_STALE`, `GLOBAL_COST_GUARD_NEAR_LIMIT`.
    4. CLI read-only com saída estritamente JSON em stdout e logs silenciados: `python -m app.services.production_observability --json`.
    5. Seção no Operator Console: `"📊 Production Observability — V15"` com visualização lado a lado.
    6. Fail-safe por seção (`status="unavailable"` sem derrubar snapshot) e distinção estrita entre 0, "unknown" e "unavailable".
    7. Validação direcionada: 7 testes PASS (`test/services/test_production_observability.py`) cobrindo isolamento, zero mutações, zero network, e serialização JSON.
  - **Próximo Gate:** Deploy seguro via `scripts/update_production.ps1` e execução read-only no PC forte.

---

## V13-B — Production Homologation / Safe Remote Deployment Active — HOMOLOGATED

- **Baseline:** `46e44c2495a8fe38484977ad1aa7cff439e26679`
- **Contexto Operacional e Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
  - Status dos Componentes:
    - `V13-A` = MERGED
    - `V13-A.1` = MERGED (hotfix de separação stdout/stderr no backup)
    - `V13-B` = PRODUCTION HOMOLOGATED
    - `V14-B.2` = PRODUCTION HOMOLOGATED
    - `V14-B.2.1` = PRODUCTION HOMOLOGATED
    - `Presenter/Nox` = DORMANT / OFF (`avatar_mode="none"`)
- **Evidência Operacional Real da Homologação:**
  - `CURRENT_SHA`: `e3f024938c5338c197a1f1654775686227f3eb05`
  - `TARGET/FINAL_SHA`: `46e44c2495a8fe38484977ad1aa7cff439e26679`
  - `BACKUP`: PASS
  - `BACKUP_FILE`: `storage/backups/database/video_factory_20260923_061728.db`
  - `BACKUP_SHA256`: `c87539c365193b09a41bfdf44f44afd55a78f6ab085b5c8ead8df7eb457429be`
  - `SQLITE_INTEGRITY`: OK
  - `SAFE_STOP`: PASS (`schtasks /End /TN "VideoFactory Production"`)
  - `FAST_FORWARD_UPDATE`: PASS (`git merge --ff-only 46e44c2495a8fe38484977ad1aa7cff439e26679`)
  - `SAFE_START`: PASS (`schtasks /Run /TN "VideoFactory Production"`)
  - `HEALTH`: PASS (HTTP 200 / ok em `http://127.0.0.1:8501/_stcore/health`)
  - `ROLLBACK`: NOT_REQUIRED
  - `DEPLOY_STATUS`: DEPLOY_SUCCESS
- **Novo Contrato Operacional de Produção:**
  - Atualizações futuras da produção devem obrigatoriamente utilizar `scripts/update_production.ps1`.
  - Fluxo oficial obrigatório: Preflight -> Backup SQLite -> integrity_check -> Stop -> Fast-Forward Update -> Start -> Health Check -> Rollback automático se necessário.
  - Proibido pull manual como fluxo padrão.

## V13-A — Headless Remote Deployment / Safe Update Foundation — MERGED

- **Baseline:** `ee32d801bfd8a5b9b6f7ecbb57c556aa803327f5`
- **Contexto Operacional e Ambientes:**
  - DEV / Notebook: `D:\Projetos\MoneyPrinterTurbo`
  - PRODUÇÃO / PC Forte: `C:\Projetos\MoneyPrinterTurbo`
  - Scheduled Task de Produção: `VideoFactory Production`
  - Status desta fase: **MERGED** (homologada em produção na V13-B)
  - `V14-B.2` = PRODUCTION HOMOLOGATED
  - `V14-B.2.1` = PRODUCTION HOMOLOGATED
  - `Presenter/Nox` = DORMANT (experimento arquivado em branch separada, produção e main com `avatar_mode="none"`)
- **Implementação Realizada:**
  1. Script de atualização criado em `scripts/update_production.ps1` aceitando `-TargetRef` (default `origin/main`), `-RepoPath` (default `C:\Projetos\MoneyPrinterTurbo`), `-TaskName` (default `VideoFactory Production`), `-HealthUrl` (default `http://127.0.0.1:8501/_stcore/health`) e `-PreflightOnly`.
  2. **Pipeline de Execução Completo:**
     - `PRE-FLIGHT`: Verificação fail-closed de working tree limpa (rejeita alterações não commitadas ou arquivos untracked críticos), branch/HEAD válida, .venv existente, resolução de commits e verificação de Fast-Forward (`git merge-base --is-ancestor`).
     - `BACKUP`: Snapshot transacional SQLite pré-stop via `app.services.production_backup` com `PRAGMA integrity_check` e manifesto sidecar com SHA-256. Se integridade != ok, aborta antes de qualquer mutação.
     - `STOP`: Parada controlada e delimitada via `schtasks /End /TN "VideoFactory Production"`, aguardando encerramento sem matar processos aleatórios.
     - `UPDATE`: Atualização estritamente Fast-Forward (`git merge --ff-only TARGET_SHA`) com validação de `git rev-parse HEAD == TARGET_SHA`.
     - `START`: Inicialização segura via `schtasks /Run /TN "VideoFactory Production"`.
     - `HEALTH CHECK`: Avaliação delimitada em `http://127.0.0.1:8501/_stcore/health` (timeout 75s, HTTP 200 + corpo contendo `ok`).
     - `ROLLBACK`: Se o health check falhar pós-update, para a Scheduled Task, retorna para `CURRENT_SHA` via `git switch --detach CURRENT_SHA` (zero `git reset`, `git restore` ou `git clean`, preservando a branch `main`), reinicia a tarefa e repete o health check. Se passar: `ROLLBACK_SUCCESS`; se falhar: `ROLLBACK_FAILED` com parada e exigência de intervenção humana.
  3. **Lock e Logging Local:** Lock exclusivo em `storage/locks/update_production.lock` com limpeza garantida em bloco `finally`. Logs timestampados em `logs/deploy/` estritamente sanitizados (sem API keys, tokens ou secrets).
- **Validação:**
  - Teste direcionado único criado em `test/services/test_safe_production_update.py` cobrindo 13 verificações estáticas e funcionais em repositório temporário isolado (13 passed in 6.68s).
- **Próximo Passo:** V13-B = Primeira instalação e homologação real no PC forte.

## V14-B.2 — Manual Copyright Status + Closed Feedback Loop Exclusion — MERGED

- **Baseline:** `150056215fcbd8296fcdeac56abac0d37f787cc8`
- **Contexto Operacional:** Produção parada após homologação da V14-B e V14-B.1. Evidência real conhecida: task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) publicada com sucesso e posteriormente bloqueada mundialmente via Content ID no YouTube Studio. O YouTube Data API não fornece status detalhado de Content ID, exigindo status manual/auditável do operador.
- **Implementação Realizada:**
  1. Status de copyright suportados: `unknown`, `clean_manual`, `claimed`, `blocked`, `strike` (com source `operator` e espaço futuro para `future_provider`).
  2. Persistência auditável em `operational_events` com `metadata_json` completo (`task_id`, `publication_event_id`, `platform`, `external_id`, `copyright_status`, `source`, `timestamp`, `note`) sem migrações ou tabelas novas no SQLite.
  3. Operações no Console do Operador:
     - `set_publication_copyright_status_op(...)`: PRIMARY only, valida status permitido, valida publicação existente no YouTube em status `success`, idempotente quando o mesmo status é reaplicado, nunca chama rede.
     - `get_publication_copyright_status(...)`: leitura do status mais recente (read-only), retornando `unknown` para publicações sem registro.
  4. Regra crítica no Closed Feedback Loop (`analytics.get_learning_evidence`):
     - `clean_manual` => elegível de copyright para compor amostras de aprendizado.
     - `claimed`, `blocked`, `strike` => SEMPRE EXCLUÍDOS.
     - `unknown` (inclusive publicações legadas sem status) => FAIL CLOSED (EXCLUÍDOS).
     - Auditoria explícita em `excluded_counts_by_reason`: `copyright_unknown`, `copyright_claimed`, `copyright_blocked`, `copyright_strike`.
  5. Preservação integral de histórico: métricas e registros de publicação nunca são apagados.
  6. Operator Console UI: card Copyright / Assets atualizado com badges de status, source e elegibilidade do loop, e formulário auditável não-destrutivo para marcação manual.
  7. Preparação para o vídeo bloqueado conhecido: task `815b0958-b94e-457b-932d-b10dfb0e8dba` (YouTube `XVy8MbpJFqw`) pronta para marcação como `blocked` pós-deploy.
  8. Presenter: DORMANT (experimento arquivado em branch separada, produção e main mantidas com `avatar_mode="none"`).
- **Próximo Passo:** Homologação concluída com sucesso em produção na V13-B. Próxima fase global: V15.

## V14-C.3 — Nox Canonical Visual Asset Pack + Real Local Preview — EXPERIMENT ARCHIVED / DORMANT

- **Baseline:** `447a36789850857a66422ad06f1800f18cccd96a`
- **Contexto Operacional:** Experimento visual de Nox não atingiu os requisitos de qualidade e dinamismo.
- **Presenter / Nox DORMANT:**
  - V14-C.4 NÃO é a próxima fase ativa.
  - O experimento visual foi formalmente descontinuado e arquivado na branch: `archive/v14-c3-nox-presenter-experiment`.
  - Frameworks V14-C, V14-C.1 e V14-C.2 permanecem no código, mas o modo autônomo está estritamente desligado (`avatar_mode="none"`).
- **Implementação Realizada (Histórico):**
  1. Estrutura canônica de diretórios criada em `assets/presenter/nox_v1/` (`manifest.json`, `reference/`, `poses/`, `previews/`).
  2. Manifest canônico estruturado com metadados de identidade visual (pele morena clara, cabelo preto com reflexos roxos, olhos castanhos, roupa jaqueta/moletom preto).
  3. Contrato de 9 Core Poses obrigatórias e catálogo de 13 Extended Motion Poses opcionais.
  4. Fallback Graph determinístico implementado para poses estendidas ausentes (`EXTENDED_POSE_FALLBACKS`).
  5. Validação rigorosa de integridade e consistência gráfica (`validate_character_pack_assets`) verificando PNG, canal alfa real e conformidade dimensional.
  6. Gerador local de Contact Sheet (`generate_contact_sheet`) renderizando grid com Core Poses e Extended Poses rotuladas.
  7. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).
- **Próximo Passo:** V15-A — Production Observability Baseline (V15 — Production Observation & Optimization).

## V14-C.2 — Expressive Presenter + Subtitle Interaction — MERGED

- **Baseline:** `def541870a598ee8984a6a2b98bed39688434691`
- **Contexto Operacional:** Produção parada. Objetivo: dotar o Nox de capacidade expressiva sincronizada com legendas e narração (SRT), alternância de fala, reações semânticas e apontamentos geométricos sem lip-sync neural.
- **Implementação Realizada:**
  1. Parser determinístico e tolerante a falhas de SRT (`parse_srt_timeline`), convertendo legendas para estrutura temporal unificada.
  2. Classificador prioritário de legendas (`classify_subtitle_reaction`) com categorias PT-BR (SURPRISE, THINKING, SERIOUS, CTA, DEFAULT) e precedência estrita (`CTA > SERIOUS > SURPRISE > THINKING > TALKING > NEUTRAL`).
  3. Alternância determinística de fala (`talking_1` e `talking_2` em fatias de 0.35s) ativa somente durante trechos falados e visíveis.
  4. Interação de apontamento (`pointing_left` para `bottom_right`, `pointing_right` para `bottom_left`) para direcionar o espectador para a legenda.
  5. Tom de canal respeitado: `profile-historias-misterio` utiliza reações sóbrias e contidas (`mystery_contained_reaction`).
  6. Construção da timeline de expressões (`build_presenter_expression_timeline`) respeitando estritamente os segmentos do presenter e sem sobreposição temporal inválida.
  7. Performance otimizada no MoviePy via cache único de clips de pose no ExitStack.
  8. Autonomous Presenter mantido estritamente desligado (`avatar_mode="none"`).

## V14-C.1 — Cartoon Character Asset Pack + Preview — MERGED

- **Baseline:** `b9e73e2a98f020e54be304396749e5c86e67cbb1`
- **Contexto Operacional:** Produção parada após entrega da infraestrutura básica do presenter (V14-C). Objetivo: criar especificação do personagem unificado **Nox** (`nox_v1` / `misterio_host_v1`, `SINGLE_CHARACTER_ALL_CHANNELS = YES`), estruturar contrato de asset pack local, controller de poses e modo de preview controlado.
- **Implementação Realizada:**
  1. Especificação completa do personagem documentada em `docs/CHARACTER_PRESENTER_SPEC.md` (Nox `nox_v1`, estilo cartoon/semi-cartoon, paleta sóbria grafite/vinho, proporções waist-up).
  2. Contrato de Asset Pack local estabelecido em `storage/presenter_assets/<character_id>/` e `resource/presenter_assets/<character_id>/` com catálogo de poses (`neutral`, `talking_1`, `talking_2`, `surprised`, `serious`, `thinking`, `pointing_left`, `pointing_right`, `cta`) e `config.json`.
  3. Resolução de Character Pack por `character_id` em `presenter.py` (`resolve_character_pack`) com fail-closed para poses obrigatórias ausentes.
  4. Pose Controller determinístico (`select_presenter_pose`) selecionando poses por segmento narrativo (hook, return, cta, corner).
  5. Suporte a Preview controlado (`render_presenter_preview` e `generate_presenter_preview_frame`) para validação estática e render sem tocar produção.
  6. Produção autônoma estritamente preservada com `avatar_mode="none"`.

## V14-C — Hybrid Character Overlay MVP — MERGED

- **Baseline:** `4ba4a8db0314bdd8ace5c54072f1b69b5c11a791`
- **Contexto Operacional:** Produção parada após homologação da V14-B e V14-B.1. Objetivo: habilitar infraestrutura técnica para personagem/apresentador virtual sobre o vídeo final sem dependências pagas nem lip-sync neural.
- **Implementação Realizada:**
  1. `VideoParams` expandido com campos: `avatar_mode` (`none`, `corner`, `hybrid`, `full`), `avatar_provider` (`local`), `avatar_character_id`, `avatar_asset_path`, `avatar_position` (`bottom_right`, `bottom_left`, `bottom_center`), `avatar_scale` (0.1 a 1.0), `avatar_opacity` (0.0 a 1.0) com validações robustas.
  2. Serviço dedicado `app/services/presenter.py` com validação de config, bloqueio de path traversal, cálculo determinístico de timeline (`build_hybrid_presenter_segments`) e layout com safe margins para Shorts.
  3. Composição Z-Order em `video.generate_video()` com suporte a MoviePy 2.x: B-roll (base) -> Presenter Overlay -> Subtitles (topo), evitando render duplo.
  4. Proveniência de Presenter integrada em `build_asset_provenance()` e `get_copyright_provenance_summary()` em `copyright_gate.py`.
  5. Telemetria no Operator Console: Mode, Character ID, Provider e Asset Status.
  6. Modo autônomo estritamente fixado em `avatar_mode="none"`.

## V14-B.1 — Legacy Stock Copyright Quarantine (Hotfix) — PRODUCTION HOMOLOGATED

- **Baseline:** `2e285cf43bfd01dc10e04a74a35572ee6f2fab19`
- **Contexto Operacional:** Produção parada após identificação de 23 vídeos legados não publicados contendo `bgm_type="random"` ou `bgm_type="custom"` e sem `asset_provenance`.
- **Implementação Realizada:**
  1. `_get_param()` implementado em `copyright_gate.py` para suportar uniformemente parâmetros em formato `dict` e instâncias de objeto (`VideoParams`).
  2. Tarefas antigas com `bgm_type="random"` ou `bgm_type="custom"` sem proveniência avaliam estritamente como `COPYRIGHT_PROVENANCE_GATE = FAIL`.
  3. `_recover_waiting_task()` e `get_autonomous_ready_stock()` passam a validar `evaluate_copyright_provenance_gate == PASS`, excluindo automaticamente os 23 vídeos legados do estoque autônomo e impedindo sua adoção/recuperação no Scheduler pelo Autonomous.
  4. Preservação física e histórica completa: nenhum arquivo apagado, nenhum registro SQLite destruído. Caminho manual legado preservado.

## V14-B — Copyright Baseline Hardening — PRODUCTION HOMOLOGATED

- **Baseline:** `ceb64fa441f68f722d7cc2c21b986997c5cd2177`
- **Evidência Real:** Task `815b0958-b94e-457b-932d-b10dfb0e8dba`, vídeo YouTube `XVy8MbpJFqw` (publicação tecnicamente correta, posteriormente bloqueada mundialmente por conteúdo reivindicado; sem evidência de strike).
- **Causa Raiz:** Músicas padrão de `resource/songs/*.mp3` originadas de vídeos do YouTube e selecionadas por `bgm_type="random"`.
- **Implementação Realizada:**
  1. Bloqueio fail-closed de faixas legadas em novas gerações autônomas via `resolve_autonomous_bgm(...)` (`bgm_type="none"`, `volume=0.0`, `SAFE_NO_BGM`).
  2. Preservação do uso manual legado (sem deleção de `resource/songs/`).
  3. `asset_provenance` persistido em `script.json` e memória (`bgm` e `visual_clips` com provedor, ID externo se disponível, URL, arquivo local e termo de busca).
  4. Copyright Provenance Gate no pipeline autônomo (fail-closed antes da aprovação da tarefa; valida BGM segura e lista de provedores permitidos: Pexels, Pixabay, Coverr).
  5. Sem promessa de ausência de claim (`COPYRIGHT_PROVENANCE_GATE = PASS`, jamais `CONTENT_ID_SAFE`).
  6. Preparação conceitual de status futuro (`unknown`, `clean_manual`, `claimed`, `blocked`, `strike`) e fontes (`operator`, `future_provider`).
  7. Backlog: exclusão no Closed Feedback Loop de publicações com reivindicação comprovada.
  8. Card "Copyright / Assets" no Operator Console.

## V12-E.3 — Autonomous Stock Buffer Hardening — DEV controlado


Implementação separada da V12-F.2, sobre o worktree existente em `54875c6`.
Produção não acessada; sem deploy, commit ou push. Os registros de produção abaixo
continuam sendo informações fornecidas pelo operador, não uma verificação nova.

O Autonomous reconstrói o estoque YouTube a partir de `monetization_safety`,
`content_quality_scores`, `task_profiles`, `task_platforms`, perfis/canais e
registros de publicação/agendamento. Revalida vídeo físico não vazio, Safety PASS,
último Quality finito >=70 e GOOD/STRONG, perfil ativo e canal YouTube habilitado.
Publicadas e canceladas são excluídas. Tasks já agendadas contam no estoque,
mas não voltam à fila de agendamento; estados ativos/inválidos em memória vetam
a recuperação. MemoryState vazio e ausência de `waiting_task_id` não apagam a fila.

Prioridade por ciclo: guards → geração ativa/revisão → recuperação de indicação
inválida → uma tentativa de agendamento com slot → reposição se abaixo da meta.
Sem slot, não chama `plan_schedule`; o bloqueio de publicação não bloqueia geração.
Cada revisão, recuperação ou tentativa de agendamento encerra seu ciclo. Geração
mantém cooldown existente e tetos efetivos de uma/ciclo e cinco/24h; falha na
contagem diária bloqueia novas gerações. Lock local impede ciclos manuais/worker
simultâneos, preservando o requisito de um único PRIMARY entre processos.

`waiting_task_id` é indicação de uma task da fila, não trava global. Retry após
tentativa sem resultado usa `autonomous_schedule_retry:<task_id>` por 15 minutos
na tabela existente `autopilot_settings`. Eventos `PROFILE_GROWTH_LIMIT_BLOCK`
têm deduplicação transacional por task/perfil/plataforma/Growth Mode durante
15 minutos, compartilhada por Autonomous, planner e executor, inclusive após restart.
Nenhuma mudança de schema, Growth Mode, Auto Publish ou integração TikTok.
Scheduler continua sendo o único publicador; elegibilidade não publica conteúdo.

Validação DEV concluída: **600 testes e 32 subtestes passaram, zero falhas**, em
246,12s, nas 23 suítes abaixo; 16 testes novos são da V12-E.3. SQLite, vídeos e
configuração sintéticos em diretórios temporários; rede bloqueada. `git diff --check`
aprovado. Fixtures antigas foram atualizadas para aprovações persistidas e para
permitir reposição sem slot; duas falhas de fixtures novas foram corrigidas antes
da execução final verde. Próximo gate seguro: revisar exclusivamente o diff V12-E.3;
qualquer homologação/deploy em produção exige autorização separada.
Arquivos desta etapa: `app/services/autonomous_production.py`,
`app/services/scheduler.py`, `test/services/test_autonomous_production.py`,
`test/services/test_autonomous_stock_buffer.py` e os três documentos canônicos
de handoff, roadmap e runbook. Alterações anteriores da V12-F.2 preservadas.

Comando de regressão isolada (23 suítes; o runner existente cria configuração
sintética, bloqueia sockets e usa somente diretórios temporários):

```powershell
.venv/Scripts/python.exe -B scripts/run_closed_loop_tests.py `
  test/services/test_analytics.py test/services/test_analytics_scheduler.py test/services/test_analytics_ingestion.py test/services/test_analytics_providers.py test/services/test_analytics_real_fetch.py `
  test/services/test_content_strategy.py test/services/test_quality_score.py test/services/test_autonomous_production.py test/services/test_autonomous_stock_buffer.py `
  test/services/test_scheduler.py test/services/test_scheduler_worker.py test/services/test_operator_console.py test/services/test_publication_persistence.py `
  test/services/test_single_instance.py test/services/test_production_health.py test/services/test_profile_manager.py test/services/test_profile_generation.py test/services/test_profile_scheduler.py `
  test/services/test_growth_mode.py test/services/test_trend_radar.py test/services/test_schedule_cancellation.py test/test_production_entrypoint.py test/services/test_closed_feedback_loop.py -q --tb=short
```

## [HISTORICAL SNAPSHOT / SUPERSEDED] Estado vigente — 21/09/2026 — V12-F.2 em validação DEV

> [!NOTE]
> **SUPERSEDED:** Este bloco registra o estado histórico em 21/09/2026. As fases V12-F.2 (Closed Feedback Loop), V12-F.3 (Per-Channel Learning Isolation), V12-F.4 (Second Channel Warm-Up), V12-F.5 (Multi-Channel Capacity), V13-A/A.1/B (Safe Production Update) e V14-A/B/B.1/B.2/B.2.1 (Copyright Hardening) foram posteriormente implementadas e homologadas em produção. O **Estado Atual Canônico** no topo prevalece formalmente.

Esta seção substitui as descrições de estado atual dos registros históricos abaixo.
Produção informada e homologada pelo operador em `54875c6`: Factory RUNNING,
PRIMARY headless ativo, Scheduler ON, Auto Publish ON, Dry Run OFF, YouTube ON,
TikTok OFF, Growth Mode WARMUP, Autonomous ON, Analytics Auto ON e MPT Auto Upload OFF.
Nenhuma consulta ao host, SQLite, configuração ou credencial de produção foi realizada nesta implementação.

V12-E e V12-F.1A/B/C estão HOMOLOGADAS EM PRODUÇÃO. YouTube Data API v3,
fetch real e persistência real homologados. Evidências fornecidas: publication event 16,
external ID `fTrkUqSnYqs`, privacy `public`, confirmação operacional 200;
snapshot 3 em `2026-09-21T07:52:50.719666+00:00`; ativação Analytics Auto no evento 211,
`2026-09-21T07:56:48.285854+00:00`. Snapshot 2, de 18/09, é anterior ao rollout atual.
Valores zero não significam erro do provider. Limites preservados: 1 fetch/ciclo, 300s;
estoque 3, uma geração/ciclo, cinco gerações/24h móveis, intervalo 15 min.

### V12-F.2 — implementação DEV controlada

Baseline de código `54875c6`; sem commit, push, deploy ou ativação nesta entrega.
Flag `closed_feedback_loop_enabled` em `autopilot_settings`, default ausente/False.
OFF preserva o caminho anterior. ON tenta adaptar somente tema/cluster e estrutura;
preset, duração, fonte, voz, CTA, ritmo, transições, legendas e música permanecem baseline.

API nova `analytics.get_learning_evidence(platform, profile_id, channel_id, cutoff_time, db_path)`:
leitura SQLite read-only consistente; scope obrigatório antes da agregação;
PUBLIC/success, identidade exata, profile persistido, Safety PASS e Quality >=70 GOOD/STRONG.
Origem `youtube_api`, metadata `dry_run=false` e `item_id` correspondente são exigidas;
dados sem procedência suficiente são excluídos. Sem uso ou reescrita do performance_score legado.

Política `v12-f2.1`: 12 publicações distintas, cinco por grupo, dois grupos comparáveis,
janela histórica 60 dias. Uma observação por external ID no scope; idade 72–96h,
mais próxima de 72h, menor ID em empate. Mediana de views é o sinal primário;
mediana de engagement é auxiliar descritiva, sem desempatar views. Leave-one-out
do vencedor precisa manter vantagem estrita. Política de rollout, não significância estatística.

Ranking recebe no máximo cinco pontos. Estruturas restritas às oficiais e às alternativas
temáticas da heurística. No máximo uma adaptação por três submissões; cluster limitado
a dois usos na janela resultante de cinco; repetição imediata de estrutura veta adaptação.
Veto ou falha retorna ao baseline, sem relaxar Safety/Quality.

`CLOSED_LOOP_DECISION` persiste evidência, candidatos/ranks, scope, baseline, escolha e
parâmetros antes da submissão. Reserva transacional revalida flag e histórico concorrente.
`CLOSED_LOOP_SUBMITTED` registra sucesso real da submissão ao pipeline. Reserva adaptada
sem confirmação após crash/falha de auditoria mantém adaptação suspensa conservadoramente;
geração baseline continua. Não excluir histórico para liberar adaptação automaticamente.

Schema changes: NONE. Reutiliza tabelas existentes. Testes executados via
`scripts/run_closed_loop_tests.py`, cópia temporária de fontes com config sintética e rede bloqueada.
Resultados finais de validação serão registrados após a regressão.
Próximo gate: revisão DEV; deploy e ativação em produção exigem autorizações separadas.

Comando de regressão isolada (somente DEV; mocks/fakes, sem rede):

```powershell
.venv/Scripts/python.exe -B scripts/run_closed_loop_tests.py `
  test/services/test_analytics.py test/services/test_analytics_scheduler.py `
  test/services/test_analytics_ingestion.py test/services/test_analytics_providers.py `
  test/services/test_analytics_real_fetch.py test/services/test_content_strategy.py `
  test/services/test_quality_score.py test/services/test_autonomous_production.py `
  test/services/test_scheduler.py test/services/test_scheduler_worker.py `
  test/services/test_operator_console.py test/services/test_publication_persistence.py `
  test/services/test_single_instance.py test/services/test_production_health.py `
  test/services/test_profile_manager.py test/services/test_profile_generation.py `
  test/services/test_profile_scheduler.py test/services/test_growth_mode.py `
  test/services/test_trend_radar.py test/services/test_schedule_cancellation.py `
  test/test_production_entrypoint.py test/services/test_closed_feedback_loop.py -q --tb=short
```

## Registros históricos anteriores ao rollout atual

Menções abaixo a Analytics OFF, Autonomous OFF, Auto Publish OFF, produção em `d1a8677`
ou F.1 incompleta descrevem etapas anteriores e não o estado vigente acima.


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

**Gate histórico posteriormente concluído:** V12-F.1A/B/C e ativação real do Analytics Auto foram homologadas pelo operador em 21/09/2026, baseline `54875c6`; ver estado vigente acima.

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
- V12-F.1A Analytics Activation Hardening — **homologada em produção; Analytics ON**
- V12-F.1B Headless Worker Bootstrap — **✅ homologada em produção; Headless gate PASS**
- V12-F.1C Publication Privacy Persistence — **homologada em produção; Analytics ON**

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
`54875c6` (homologação informada pelo operador)

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

## 22. V12-F.4 — Segundo canal homologado em produção

**Status: ✅ COMPLETED / PRODUCTION HOMOLOGATED (22/09/2026).**

Segundo canal configurado, isolado e homologado em produção real. Evidências comprovadas:
- **Segundo perfil isolado:** `profile-historias-misterio` ("Dose Diária de Histórias e Mistério", nicho `historias_misterio`).
- **Canal YouTube isolado:** `channel-historias-misterio-youtube` (handle `@DoseDiáriadeHistóriasemistério`).
- **Upload-Post profile:** `dose-diaria-misterio` conectado e autenticado.
- **Geração real:** task_id `815b0958-b94e-457b-932d-b10dfb0e8dba`.
- **Safety Gate:** PASS.
- **Quality Gate:** 79.2 (Strong Quality).
- **Scheduler:** Adoção e agendamento automático para YouTube.
- **Publicação pública:** Vídeo `XVy8MbpJFqw` publicado no YouTube.
- **Analytics youtube_api:** Coleta e métricas isoladas via YouTube Data API.
- **PR #9 Recovery:** Recuperação de tarefas aprovadas sem dependência de MemoryState volátil.
- **Autonomous secondary ON:** Produção autônoma do perfil secundário ativada e operacional.
- **Canal principal:** Perfil `default` 100% preservado e isolado.

---

## 23. V12-F.5 — Multi-Channel Capacity & True Multi-Profile Autonomous Worker

**Status: ✅ COMPLETED / IMPLEMENTED (22/09/2026).**

> [!IMPORTANT]
> **UI PROFILE SELECTION IS NOT A BACKGROUND EXECUTION SELECTOR.**
> A seleção de perfil na interface gráfica do Operator Console serve exclusivamente para controle do operador (visualização, edição, acionamento supervisionado manual). A execução em segundo plano do Scheduler Worker opera de maneira totalmente desacoplada, iterando de forma determinística por todos os canais/perfis que possuem modo autônomo ativado (`run_enabled_profiles_autonomous_cycle`).

Entregas da Fase V12-F.5:
1. **Background Worker Multi-Perfil Desacoplado:** Loop do worker em segundo plano executa `run_enabled_profiles_autonomous_cycle()`, eliminando qualquer dependência de `get_active_profile_id()`. O worker processa sequencialmente os perfis ativos habilitados com isolamento total de falhas.
2. **Ready Stock por Perfil:** Configuração isolada `autonomous_target_ready_stock:<profile_id>` (WARMUP default 3, SCALE default 5, configurável de 3 a 6). O perfil default mantém retrocompatibilidade com a chave legada.
3. **Limites Operacionais por Perfil (24h):**
   - WARMUP: 2 gerações aprovadas / 24h, 8 tentativas / 24h.
   - SCALE: 5 gerações aprovadas / 24h, 15 tentativas / 24h.
   - Chaves isoladas: `autonomous_max_generations_24h:<profile_id>` e `autonomous_max_attempts_24h:<profile_id>`.
4. **Global Cost Guard:** Freio mestre agregado somando todos os perfis (`autonomous_global_max_generations_24h = 10`, `autonomous_global_max_attempts_24h = 25`). Contadores agregados explícitos (`count_all_profiles_generations_24h`, `count_all_profiles_attempts_24h`). Protege apenas novas gerações, preservando agendamentos e publicação de estoques prontos.
5. **Multi-Destino / Elegibilidade de Assets:** Conceito `check_asset_eligibility_for_destination` implementado para suporte futuro de 1 asset atendendo YouTube + TikTok sem re-renderização obrigatória.
6. **TikTok Estritamente OFF:** TikTok permanece desativado, sem credenciais, posts ou chamadas de API.
7. **Operator Console Integrado:** Exibição de estoque alvo, estoque pronto, limites de 24h e contadores do Global Cost Guard.

---

## 24. Pendência Futura: Copyright / Content ID Hardening + Character Narrator

- **Problema Real Registrado:** Vídeo `XVy8MbpJFqw` (task `815b0958-b94e-457b-932d-b10dfb0e8dba`) publicado no YouTube recebeu bloqueio/reivindicação mundial por Content ID.
- **Investigação Necessária:** Identificação precisa da mídia visual (Pexels/Pixabay) e trilha BGM causadoras da reivindicação.
- **Narrador Virtual:** Introdução de apresentador/personagem virtual (V14 Hybrid Presenter) para enriquecer teor transformativo e originalidade do canal.
- **Gate Preventivo:** Análise de pré-verificação ou filtragem preventiva contra faixas sujeitas a Content ID.
- **Isolamento de Feedback:** Vídeos com Content ID reivindicado não devem alimentar o Closed Feedback Loop.
- **Observação:** Não implementado na V12-F.5 (apenas registrado em backlog).

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

---

## 25. V16.1 — Brazilian Content Contract

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Deploy SHA:** `3983d37a29d1f169e513f19bd7186348a74ad5e9`
- **Evidências de Homologação Real:**
  - A UI persistida em produção ainda continha `af-ZA-AdriNeural-Female`, `subtitle_enabled=False`, `text_fore_color=#000000`.
  - A produção autônoma bloqueou corretamente a voz estrangeira de forma fail-closed sem gerar falha silenciosa.
  - Nenhum vídeo/API/publicação espúria ocorreu no teste.

Entregas da Fase V16.1:
1. **Contrato Brasileiro Canônico Fail-Closed:**
   - `video_language = "pt-BR"` e `region = "BR"` impostos na produção autônoma independentemente de configurações de UI.
   - `subtitle_enabled = True` forçado para todas as gerações autônomas.
   - `text_fore_color = "#FFFFFF"`, `stroke_color = "#000000"` e `stroke_width >= 1.5` (default autônomo 2.0).
   - `match_materials_to_script = True` e `video_concat_mode = sequential` como default autônomo.
2. **Validação Estrita de Locales de Voz:**
   - `is_valid_pt_br_voice(voice_name)` aceita somente vozes comprovadamente `pt-BR` (ex: `pt-BR-AntonioNeural`, `pt-BR-FranciscaNeural`, `pt-BR-ThalitaMultilingualNeural`).
   - Vozes estrangeiras (`af-ZA-*`, `en-*`, `zh-*`, `pt-PT-*`) ou vazias provocam `AutonomousConfigError` (FAIL CLOSED), sem fallback silencioso para línguas estrangeiras.
3. **Validador Reutilizável de Contrato:**
   - `validate_autonomous_brazilian_content_contract(params)` avalia e retorna relatório estruturado (`PASS` ou `BLOCK`).
4. **Preservação de Geração Manual:**
   - Chamadas diretas de `VideoParams` pela WebUI continuam livres para experimentação manual pelo operador, sem impacto inadvertido.

---

## 26. V16.2 — Subtitle Reliability Gate

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Deploy SHA:** `0744fd2b8593fa276a2d3117d88b270475b5b05c`
- **Regra Fundamental:** `AUTONOMOUS_VIDEO_WITHOUT_VALID_CAPTIONS = FORBIDDEN`

Entregas da Fase V16.2:
1. **Validador Reutilizável de SRT (`validate_subtitle_file` / `validate_srt`):**
   - Valida existência, integridade física (> 0 bytes, não apenas whitespace), leitura em UTF-8 / UTF-8-SIG (com BOM).
   - Valida parsing rigoroso de cues, formato e faixas de timestamps (hour >= 0, 0 <= m < 60, 0 <= s < 60, 0 <= ms <= 999), ordenação temporal (`start < end`), detecção de timestamps zerados (`all_timestamps_zero`) e texto não vazio por cue.
   - Validação heurística de coerência com o roteiro (cobertura proporcional mínima e sobreposição lexical sem acentos) que impede legendas vazias ou desconexas.
   - Retorno estruturado fail-closed sem lançar exceções.
2. **Arquitetura de Geração com Fallback Automático:**
   - **Primary:** Edge Subtitles (`voice.create_subtitle`). Se gerar SRT válido -> aceito imediatamente.
   - **Fallback:** Whisper Subtitles (`subtitle.create` + `subtitle.correct`). Acionado automaticamente se Edge falhar, não gerar arquivo, gerar arquivo vazio ou inválido.
   - **Stale SRT Protection:** Remoção preventiva de arquivos parciais/inválidos e geração temporária atômica (`os.replace`) para evitar falsos positivos por arquivos residuais.
3. **Fail-Closed Gate:**
   - Se ambos Edge e Whisper falharem ou produzirem SRT inválido: o pipeline é interrompido imediatamente em `stage="subtitle"`, marcando a tarefa como `TASK_STATE_FAILED` com `error="subtitle_required_but_unavailable..."`.
   - Impede o avanço para download de materiais (`get_video_materials`) e renderização final (`generate_final_videos`).
   - Nenhuma publicação ou agendamento é disparado sem legenda válida.
4. **Preservação de Compatibilidade Manual:**
   - Quando `subtitle_required=False` (modo manual/WebUI), o fluxo preserva estritamente o comportamento anterior (não executa fallback inesperado nem download inadvertido de modelos Whisper).
   - `subtitle_enabled=False` manual continua 100% suportado.
   - Provedor explícito `subtitle_provider="whisper"` e `custom_audio_file` continuam plenamente funcionais.
5. **Ambiente Whisper:**
   - Nenhuma chamada real de rede ou download de modelo Whisper foi executada nesta fase (testes unitários isolados com mocks). Recomendação oficial de produção: `large-v3-turbo`.

---

## 27. V16.3 — Final Media Quality Gate

**Status: ✅ PRODUCTION HOMOLOGATED (Deploy SHA: `9e3fde0b35e28781aab67117d5ff33c182b337ef`)**

Regra Fundamental: `AUTONOMOUS_FINAL_MEDIA_WITH_CRITICAL_DEFECT = FORBIDDEN`

Entregas da Fase V16.3:
1. **Módulo Centralizado de Qualidade de Mídia (`app/services/media_quality.py`):**
   - Helper seguro `probe_media(file_path)` utilizando `ffprobe` com subprocess sem shell, timeout rígido, captura estruturada em JSON e validação defensiva da estrutura do payload (dict, streams list, format dict).
   - Evaluator de qualidade `evaluate_final_media_quality(video_path, params, ...)` que retorna status padronizado (`PASS` ou `BLOCK`), lista de `reasons` padronizadas e `metrics` consolidadas (duração, resolução, aspect ratio, codec, fps, tamanho em bytes).
2. **Critical Gates Fail-Closed:**
   - **Arquivo:** Rejeita arquivos inexistentes, diretórios, 0 bytes ou truncados (< 10KB, `MIN_VALID_MEDIA_FILE_BYTES`).
   - **Probe:** Falha de ffprobe (indisponível, timeout, retorno não-zero ou JSON inválido) bloqueia a produção autônoma.
   - **Vídeo:** Rejeita vídeos sem stream de vídeo, com dimensões inválidas (width/height <= 0), com resolução abaixo do mínimo ou aspect ratio incompatível com a orientação esperada (ex: `portrait` 9:16).
   - **Duração:** Rejeita vídeos com duração <= 0 ou que apresentem divergência extrema em relação ao áudio gerado (`AUDIO_VIDEO_DURATION_MISMATCH`).
   - **Áudio:** Para produção autônoma com locução, exige presença de stream de áudio com duração válida (duration inválida/não-numérica/NaN/inf/<=0 bloqueia; ausência tolerada).
   - **Contrato de Legenda:** Valida que o artefato SRT obrigatório existe e foi mantido no pipeline.
3. **Pipeline Gate Pré-Publicação:**
   - Integrado diretamente em `app/services/task.py` logo após a geração de `final_video_paths`.
   - Se qualquer vídeo final do lote falhar no gate, a tarefa é imediatamente interrompida como `TASK_STATE_FAILED` com `stage="final_media_quality"`.
   - O agendamento de cross-post (`_schedule_cross_post`) e a chamada de publicadores externos são bloqueados preventivamente.
   - Diagnóstico estruturado é persistido em `script_data` (`task_artifacts.patch_script_data`) tanto no fluxo de sucesso quanto no fluxo de BLOCK.
4. **Preservação do Modo Manual:**
   - A imposição fail-closed é governada pelo flag `final_media_quality_required=True` (imposta automaticamente na produção autônoma), preservando geração manual e testes pontuais.
5. **Limites do Escopo:**
   - Não realiza OCR visual de legendas, análise de black/freeze frames, nem avaliação semântica subjetiva.

---

## 28. V16.4 — Scene-Based Video Generation (PRODUCTION HOMOLOGATED)

**Status: ✅ PRODUCTION HOMOLOGATED (02/10/2026)**
- **Validação:** 20 testes PASS em `test/services/test_v16_4_scene_based_video_generation.py`
- **Regra Fundamental:** `AUTONOMOUS_SCENE_VISUALS_MUST_FOLLOW_SCRIPT_ORDER = REQUIRED`

Objetivo da Fase V16.4:
Garantir que vídeos autônomos possuam coerência visual narrativa, dividindo o roteiro em cenas estruturadas, associando termos visuais específicos para cada cena, resolvendo materiais sequenciais com fallback observável e montando a timeline de vídeo na ordem exata da narração.

Arquitetura e Contratos:
1. **Modelagem de Cenas (`ScenePlanItem`, `ScenePlan`, `SceneMaterialSelection`, `SceneClipInstruction`):**
   - Indexação determinística 1-based (`scene_index: 1, 2, ...`).
   - Narração não-vazia por cena.
   - Lista ordenada de termos visuais (`search_terms`) por cena.
   - Durations estimadas coerentes com a fala/narração.
2. **Planner Determinístico Baseline (`app/services/scene_planner.py`):**
   - Segmentação do roteiro por pontuação, limites narrativos e estimativa temporal (target 4-8s por cena).
   - Extração local de termos visuais específicos por cena sem necessidade de chamada externa ou LLM no baseline.
   - Suporte completo ao português brasileiro (pt-BR) com preservação de acentuação e stopwords filtradas.
3. **Scene Material Resolver (`app/services/scene_material.py`):**
   - Busca materiais para cada cena usando os termos específicos da cena.
   - Política de fallback observável: termo 1 -> termo 2 -> termo 3 -> termo visual derivado -> falha estruturada se não houver material.
   - Evita repetição visual consecutiva quando existirem alternativas.
   - Rastreabilidade completa de provedor, asset ID e termo utilizado, preservando o gate de proveniência (`asset_provenance`).
4. **Scene Assembly (`app/services/scene_assembly.py`):**
   - Orquestra e valida a sequência exata de clips antes da renderização.
   - Fail-closed em caso de índices duplicados, cenas ausentes ou durações inválidas.
5. **Compatibilidade e Preservação:**
   - Modo autônomo define `scene_based_generation_enabled=True`.
   - Modo manual preserva `scene_based_generation_enabled=False` por padrão.
   - Não altera pipelines de legendas (V16.2) nem o Final Media Quality Gate (V16.3).

## 29. V16.4.1 — Scene Render Performance Hardening

### V16.4.1A — Scene Render Performance Hardening
- **Status:** 🟢 PRODUCTION HOMOLOGATED (Deploy SHA: `8ea3fe225eef709ed7915d99ddf21b507a44c4d1`)
- **Branch:** `perf/v16-4-1-scene-render-performance` (PR #41)
- **Validação:** 10 testes PASS em `test/services/test_v16_4_1_scene_render_performance.py`

Entregas V16.4.1A:
1. **Instrumentação com `perf_counter`:**
   - `SCENE_RENDER_PREP_SECONDS`, `SCENE_RENDER_CLIPS_SECONDS`, `CONCAT_SECONDS`, `FINAL_RENDER_SECONDS` e `TOTAL_RENDER_SECONDS`.
2. **Concatenação Stream-Copy:**
   - Tentativa automática com `-c copy` para clipes scene-based normalizados.
   - Validação de saída com fallback determinístico para transcode (`-c:v libx264`).
   - Logs explícitos: `CONCAT_MODE=STREAM_COPY` ou `CONCAT_MODE=TRANSCODE_FALLBACK`.
3. **Propagação de `threads`:**
   - Parâmetro `threads` propagado corretamente para as escritas de vídeo em `combine_videos`.

### V16.4.1B — Final Render Performance (Homologada em Produção)
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `e7f40ed6f4b7df45e5868cd7de03495239d103ec` (PR #43)
- **Evidência de Produção:** Task `f9a9608b-512d-43c4-92f4-f864a0424512`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Entregas V16.4.1B:**
  1. Subtitle burn-in nativo acelerado via FFmpeg libass (`FINAL_RENDER_MODE=FFMPEG_NATIVE`).
  2. Stream-copy direto via FFmpeg (`FINAL_RENDER_MODE=FFMPEG_STREAM_COPY`) quando legendas estão ausentes.
  3. Preservação integral do fallback MoviePy legado (`FINAL_RENDER_MODE=MOVIEPY_FALLBACK`).
  4. Preservação de resolução, fps, qualidade, áudio, BGM e Final Media Quality Gate.
  5. Hardening de métricas: `FINAL_RENDER_SECONDS` interno canônico preservado e `FINAL_RENDER_CALL_SECONDS` externo registrado.

### V16.4.1C — Render Pipeline Gap Instrumentation
- **Status:** 🟢 PRODUCTION HOMOLOGATED (04/10/2026)
- **Deploy SHA:** `d231e3900bbbace180c0c71e60e9fb08c2d713e0` (PR #44)
- **Evidência de Produção:** Task `337639bb-1740-4398-a923-c5f75b1f236a`, Modo `FFMPEG_NATIVE`, Final Media Quality PASS, sem regressão funcional.
- **Resultados de Produção Homologados:**
  - `FINAL_RENDER_UNACCOUNTED_SECONDS = 0.0000273` (gaps internos eliminados).
  - `TOTAL_RENDER_UNACCOUNTED_SECONDS = 0.0033855` (gaps macro eliminados).
  - `COMBINE_VIDEOS_UNACCOUNTED_SECONDS = 0.0028849`.
  - Ponto de anomalia remanescente identificado: `FINAL_RENDER_POST_ENCODE_SECONDS = 111.4239390` (~1m51s).

### V16.4.1D — Post-Encode Performance Investigation
- **Status:** 🟢 MERGED (04/10/2026)
- **Deploy SHA:** `d13d9347fc96c6a967561821552bbb19452eb281` (PR #45)
- **Validação:** 34 testes PASS (`test_v16_4_1_scene_render_performance.py`, `test_v16_4_1b_final_render_performance.py`, `test_v16_4_1c_render_gap_instrumentation.py`, `test_v16_4_1d_post_encode_performance.py`).
- **Objetivo:** Mapear rigorosamente todas as operações dentro de `FINAL_RENDER_POST_ENCODE_SECONDS`, sub-instrumentar a região de forma contígua e identificar causas de retenção pós-encode.
- **Mapeamento do Código em Post-Encode:**
  - `t_encode_start` a `t_val_start`: Encode nativo (`305.55s`).
  - `t_val_start` a `t_post_start`: Validação de integridade do arquivo final (`_validate_final_render_output`, `0.15s`).
  - `t_post_start` a `post_encode_seconds`: Bloco pós-encode avaliando flags de modo (`native_rendered`, `final_render_mode`) e emitindo `logger.info("FINAL_RENDER_MODE=...")`.
- **Classificação de Evidências:**
  - **CONFIRMED:**
    - Não existem operações pesadas de disco, probes adicionais, cópias ou reaberturas de arquivo MoviePy dentro de `FINAL_RENDER_POST_ENCODE_SECONDS`.
    - `FINAL_RENDER_POST_ENCODE_SECONDS` mede estritamente: (1) atribuição das variáveis de estado `native_rendered` e `final_render_mode`, e (2) a chamada síncrona `logger.info("FINAL_RENDER_MODE=...")`.
    - As sub-métricas foram criadas e persistidas: `FINAL_RENDER_POST_ENCODE_STATE_SECONDS`, `FINAL_RENDER_POST_ENCODE_NOTIFY_SECONDS` e `FINAL_RENDER_POST_ENCODE_UNACCOUNTED_SECONDS`.
    - Invariante validado: `POST_ENCODE_SECONDS = STATE + NOTIFY + UNACCOUNTED`.
  - **INFERRED:**
    - A latência anômala de ~111.42s em produção ocorreu devido a pausa síncrona do terminal Windows conhost (QuickEdit Mode ativado com seleção de texto ou foco de clique pelo operador durante os 5 minutos de encode sem logs), ou contenção de lock no stream síncrono de stderr.
  - **NOT_YET_VALIDATED_IN_PRODUCTION:**
    - Decomposição exata sob execução autônoma/não assistida no PC forte (`C:\Projetos\MoneyPrinterTurbo`).

### V16.4.2R / V16.4.2R.1 / V16.4.2R.2 — Pre-Repair Publishing Reset & Stale Lock Recovery (Fase Ativa Atual)
- **Status:** 🚀 ACTIVE / DEV IMPLEMENTED (04/10/2026)
- **Branch:** `fix/v16-4-2r2-stale-primary-recovery`
- **Validação:** 16 testes PASS (8 em `test_v16_4_2r_pre_repair_publishing_reset.py` + 8 em `test_stale_primary_lock_recovery.py`), Dry-run e Reset real validados com backup físico íntegro e zero deleção de arquivos de mídia.
- **Objetivo:** Estabelecer um baseline seguro, limpo e auditado no subsistema de publicação antes das correções V16.4.2A/B/C, neutralizando todas as publicações antigas pendentes (`planned`, `ready`, `queued`), stale processing e retries armados (`next_attempt_at = NULL`), fornecendo operação administrativa fail-closed para liberação de lock stale de `PRIMARY_FACTORY`.
- **Política de Preservação e Recuperação de Lock (V16.4.2R.2):**
  - **Recuperação de Lock Primário Stale:** Quando o processo encerra de forma abrupta sem disparar `release_instance_lock()`, `operator_console.release_stale_instance_lock()` e `scripts/reset_pending_publications.py --release-stale-primary` realizam a verificação temporal conservadora (heartbeat > 90s), confirmam que o PID local não está em execução e atualizam `ACTIVE -> STOPPED`, registrando `STALE_PRIMARY_LOCK_RELEASED` em `operational_events` com zero deleção de registros.
  - **Preservação de Published:** Registros com `scheduled_posts.status = 'published'` NUNCA são convertidos em `cancelled`. Caso possuam `next_attempt_at` armado (residual), este é limpo (`NULL`), desarmando retries e mantendo `status = 'published'` e `attempts` intactos (`RETRY_DISARMED_AFTER_SUCCESS`).
  - **Inconsistência Failed com Sucesso:** Registros com `scheduled_posts.status = 'failed'` que já possuem `publication_events(status='success')` NÃO são cancelados cegamente; seus retries são desarmados (`next_attempt_at = NULL`), o status é mantido como `failed` e são preservados para reconciliação determinística na V16.4.2A (`FAILED_WITH_SUCCESS_INCONSISTENCY_DISARMED`).
  - `publication_events` com `status = 'success'` 100% preservados (zero deleções).
  - Identidade de publicações, `external_id`, `external_url` e histórico preservados.
  - Vídeos e diretórios em `storage/tasks/` 100% preservados (`media_files_deleted = 0`).
  - Scheduled posts pendentes neutralizados para `status = 'cancelled'` e `next_attempt_at = NULL`.
  - Pré-condição de segurança fail-closed (`scheduler_enabled = False`, `auto_publish_enabled = False` e `active_primary = False`).
  - Registro de auditoria detalhado em `operational_events` sob os tipos `PRE_REPAIR_PUBLICATION_RESET` e `STALE_PRIMARY_LOCK_RELEASED`.
  - Auditoria pós-reset: `EXECUTABLE_PENDING_PUBLICATIONS = 0`, `ARMED_RETRIES = 0`, `STALE_PROCESSING = 0`, `PUBLISHED_SUCCESS_RECORDS_PRESERVED = YES`.

### V16.4.2A — Publishing State Reconciliation (Fase Ativa Atual)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2a-publishing-state-reconciliation`
- **Validação:** 8 testes PASS em `test/services/test_publication_reconciliation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Estabelecer uma reconciliação determinística entre `publication_events` e `scheduled_posts`, tratando `publication_events.status = 'success'` como evidência canônica de publicação concluída.
- **Regras Canônicas Implementadas:**
  - Se existir `publication_event.status = 'success'` para `(task_id, platform)`: nunca chamar provider novamente, nunca republicar, post torna-se não executável, retry desarmado (`next_attempt_at = NULL`), mantendo metadados canônicos (`external_id`, `external_url`, `published_at`) e histórico.
  - `failed + success`: reconciliado para `published`, preservando histórico de erro e tentativas.
  - `processing + success`: reconciliado para `published`, gerando `STALE_PROCESSING_DETECTED` e `PUBLICATION_RECONCILED_SUCCESS`.
  - `published + retry residual`: mantém `published` e desarma retry residual (`next_attempt_at = NULL`), emitindo `RETRY_DISARMED_AFTER_SUCCESS`.
  - Duplicatas para a mesma tupla `(task_id, platform)`: um post canônico torna-se `published` e os demais são neutralizados para `cancelled` com retry desarmado, emitindo `DUPLICATE_SCHEDULE_DETECTED`.
  - Sucessos sem post agendado correspondente (órfãos históricos): auditados no console operacional (`HISTORICAL_ORPHAN_SUCCESS_RECONCILED`), sem inventar chamadas ao provider.
  - Nenhuma linha de `publication_events` ou `scheduled_posts` é deletada; nenhum arquivo de mídia é deletado.
- **Guard em Tempo de Execução:** `scheduler.run_scheduler_cycle` e `scheduler.has_existing_or_terminal_destination` contam com guard canônico antecipado: antes de qualquer checagem de perfil/vídeo ou tentativa de publicação externa, se houver evento de publicação prévio com sucesso, o post é marcado `published`, retries são zerados e a execução retorna `skipped: already_published` sem acionar provider.
- **Serviço e CLI:** Implementados em `app/services/publication_reconciliation.py` e `scripts/reconcile_publication_state.py` com suporte a `--dry-run` e execução real via confirmação `--execute --confirm RECONCILE_PUBLICATION_STATE`, com backup automático pré-mutação.

### V16.4.2B — Publishing Idempotency / Duplicate Protection (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2b-publishing-idempotency-duplicate-protection`
- **Validação:** 10 testes PASS em `test/services/test_publishing_idempotency.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Impedir definitivamente que o sistema crie, agende, processe ou envie mais de uma publicação externa para a mesma tupla canônica `(task_id, platform)` quando já existir sucesso registrado ou fluxo executável equivalente.
- **Modelo de Idempotência e Camadas de Proteção:**
  - **Camada 1 — Criação e Agendamento (`app.services.publishing_idempotency.can_schedule_task` / `scheduler.plan_schedule`):**
    - Bloqueia criação de novos agendamentos se já houver: sucesso canônico (`already_published`), post executável (`already_scheduled`), processamento ativo (`already_processing`) ou post publicado (`already_published`).
  - **Camada 2 — Scheduler Runtime / Seleção de Candidatos (`can_execute_scheduled_post` em `run_scheduler_cycle`):**
    - Detecta sucesso canônico antes do ciclo, desarma retries (`next_attempt_at = NULL`), marca o post como `published` e neutraliza agendamentos duplicados concorrentes como `cancelled`.
  - **Camada 3 — Just-In-Time Idempotency Gate Imediatamente Pré-Provider (`jit_provider_idempotency_guard`):**
    - Executado imediatamente antes do envio em `scheduler`, `task.publish_task`, `youtube_publisher.publish_youtube_video` e `post_for_me` client (`publish_video` / `publish_tiktok_video`).
    - Se sucesso canônico for registrado entre o início do ciclo e a chamada (race condition mitigada), aborta fail-safe e não chama o provider externo.
- **Preservação Auditável:** Duplicatas históricas canceladas não interferem com posts elegíveis; zero deleção de registros em `publication_events` ou `scheduled_posts`; zero deleção de mídia.

### V16.4.2C — Retry Metadata Cleanup (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / TARGETED TESTS PASSED (04/10/2026)
- **Branch:** `feat/v16-4-2c-retry-metadata-cleanup`
- **Validação:** 12 testes PASS em `test/services/test_publishing_retry_cleanup.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Eliminar estados residuais e regras inconsistentes de retry que possam rearmar publicações já concluídas, canceladas, reconciliadas ou terminalmente falhadas.
- **Regras da Política Canônica de Retry:**
  - `published`: Estado terminal imutável, `next_attempt_at = NULL`.
  - `cancelled`: Estado terminal imutável, `next_attempt_at = NULL`.
  - `failed` permanente ou esgotado (`attempts >= 3`): Estado terminal, `next_attempt_at = NULL`.
  - `success canônico` em `publication_events`: Desarma imediatamente qualquer retry correspondente em `scheduled_posts`.
  - `processing ativo`: Não rearma durante processamento.
  - `failed retryable`: Reagendamento permitido apenas para erros transitórios (`429`, quota 24h, 5xx, timeout, socket) dentro do limite de 3 tentativas com backoff progressivo.
- **Entregas Técnicas:**
  - `app/services/retry_policy.py`: centralização canônica de `evaluate_retry_decision` e `cleanup_residual_retries`.
  - `app/services/scheduler.py`: integração de limpeza preventiva no início de cada ciclo (`run_scheduler_cycle`) e aplicação de `next_attempt_at = NULL` em todas as transições de terminal/falha.
  - `app/services/post_for_me.py`: desarmamento de retry na reconciliação de sucesso remoto.
  - `scripts/cleanup_retry_metadata.py`: CLI de auditoria (`--dry-run`) e execução controlada (`--execute --confirm CLEANUP_RETRY_METADATA`).
- **Próximo Passo:** `V16.4.2H_FINAL_PUBLISHING_HEALTH_AUDIT`.

### V16.4.2H — Final Publishing Health Audit (Fase Concluída em DEV)
- **Status:** 🚀 DEV AUDITED / INTEGRATED SUITE PASSED (05/10/2026)
- **Branch:** `feat/v16-4-2h-final-publishing-health-audit`
- **Validação:** 10 testes PASS em `test/services/test_publishing_health_audit.py`, 8 testes PASS não-regressão V16.4.2A, 10 testes PASS não-regressão V16.4.2B, 12 testes PASS não-regressão V16.4.2C, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Realizar a auditoria final do subsistema de publicação e provar que o conjunto consolidado A+B+C está seguro para deploy em produção.
- **Auditoria de Código Conduzida:**
  - JIT Idempotency Guard integrado ao caminho de fallback Upload-Post em `task._execute_cross_post_process`.
  - Transições para estados terminais (`status = 'failed'` e `status = 'published'`) em `scheduler.py` reforçadas com `next_attempt_at = NULL` incondicional.
  - Zero pontos de escape de idempotência ou rearmamento indevido detectados.
- **Garantias Comprovadas:**
  - Idempotência canônica: exatamente 1 chamada ao provedor para publicação nova; 0 chamadas adicionais em reexecuções, restarts ou simulações.
  - Retries: falha transitória agenda retry com backoff; falha permanente e tentativas esgotadas tornam-se terminais (`next_attempt_at = NULL`).
  - Reconciliação e concorrência: JIT guard aborta envio se sucesso ocorrer antes da chamada externa.
  - Preservação estrita: zero DELETE em `publication_events` ou `scheduled_posts`; zero mídia deletada.
- **Próximo Passo:** `CONSOLIDATED_PRODUCTION_DEPLOY_AND_CONTROLLED_PUBLICATION_TEST`.

### V16.5 — Visual Matching v2 (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)
- **Branch:** `feat/v16-5-visual-matching-v2`
- **Validação:** 9 testes PASS em `test/services/test_visual_matching.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Melhorar significativamente a aderência visual dos clipes de vídeo selecionados à narração e intenção das cenas, evitando clipes genéricos ou semanticamente fracos.
- **Arquitetura Implementada:**
  - `app/services/visual_matching.py`: motor determinístico de intenção visual (`SceneVisualIntent`), queries v2 em tiers de especificidade, e pontuação de candidatos (0 a 100) baseada em termos semânticos (título, tags, slug), casamento da query, aspect ratio, duração útil e penalidades de repetição (-50 para adjacente, -35 para reutilização global no vídeo).
  - Enriquecimento de metadados em `app/services/material.py`: extração de título/slug e tags para Pexels, Pixabay e Coverr.
  - Planejamento de cenas em `app/services/scene_planner.py`: geração de intenção estruturada v2 e queries priorizadas por cena.
  - Resolução em `app/services/scene_material.py`: busca em cascata, ordenação determinística por score, diversidade global de ativos e persistência de auditoria em `script_data` (`visual_intent`, `match_score`, `selection_reason`, `queries_tried`, `fallback_tier`).
- **Próximo Passo:** PR / Merge em DEV main e validação de CI contra baseline.

### V16.6 — Hybrid Visual Generation Foundation (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026, PR #55)
- **Branch:** `feat/v16-6-hybrid-visual-generation`
- **Validação:** 12 testes PASS em `test/services/test_hybrid_visual_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Estabelecer a infraestrutura desacoplada para geração visual híbrida (Stock, Nano Banana Image, ComfyUI Video).
- **Arquitetura Implementada:**
  - `app/services/hybrid_visual.py`: Interfaces base e contratos desacoplados (`VisualProvider`, `StockVisualProvider`, `NanoBananaImageAdapter`, `ComfyUIVisualProvider`, `HybridVisualDirector`).
  - `scripts/benchmark_video_models.py`: Script de benchmark para avaliar performance e viabilidade de modelos abertos.

### V16.6.1 — Hardware-Aware Open Source Benchmark (Fase Concluída em DEV)
- **Status:** 🚀 DEV COMPLETE / CURRENT PC FORTE NOT RECOMMENDED FOR LOCAL VIDEO MODELS (05/10/2026)
- **Objetivo:** Criar probe e relatório de capacidades de hardware (GPU vendor, VRAM, CUDA/ROCm/DirectML) sem dependência obrigatória de torch e classificar o host localmente.
- **Classificação Registrada:**
  - `LOCAL_GENERATIVE_VIDEO_GPU_STATUS = "NOT_RECOMMENDED_ON_CURRENT_HARDWARE"`
  - Hardware PC Forte: AMD Radeon RX 580 2048SP (~4GB VRAM visível, sem NVIDIA/CUDA).
  - Modelos locais pesados (Wan 2.2, LTX-Video, FramePack) classificados como NOT_RECOMMENDED.
  - Recomendação canônica: Provedor remoto, keyframe generation contextual e stock fallback.

### V16.6.2 — Contextual Image-to-Video Foundation (Fase Concluída em DEV)
- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)
- **Branch:** `feat/v16-6-2-contextual-image-to-video`
- **Validação:** 20 testes PASS em `test/services/test_hybrid_visual_generation.py`, ruff 0 erros nos arquivos alterados.
- **Entregas Técnicas:**
  - Decisão Híbrida Inteligente: `HybridDecision` (`STOCK_HIGH_CONFIDENCE`, `GENERATED_IMAGE_PREFERRED`, `GENERATED_VIDEO_PREFERRED`, `FALLBACK_STOCK`) orientada pelo score de `SceneVisualIntent` do Visual Matching v2.
  - Síntese Contextual de Prompts: geração determinística de prompt fotorealista e cinematic a partir do `SceneVisualIntent` com negative prompt e aspect ratio.
  - Adapter Nano Banana Configurado: interface abstrata, modo mock com dimensões e aspecto válidos para DEV, zero chamadas pagas e fallback seguro para stock.
  - Image Quality Gate: avaliação leve de keyframes (existência do arquivo, dimensões mínimas, aspecto/orientação 9:16 ou 16:9, metadados do provedor).
  - Motion from Still Foundation: suporte a Ken Burns / Pan / Zoom paramétrico (`StillMotionMode`, `StillMotionParams`, `generate_still_motion_instructions`).
  - Observabilidade Completa: persistência de auditoria em `SceneMaterialSelection` (`visual_source_type`, `stock_match_score`, `generation_provider`, `generation_model`, `generation_prompt`, `generation_status`, `fallback_reason`, `generated_asset_path`, `motion_mode`).
- **Próximo Passo:** `V16.7_HYBRID_SCENE_DIRECTOR`.


### V16.7 — Hybrid Scene Director (Fase Concluída em DEV)

- **Status:** 🚀 DEV IMPLEMENTED / VALIDATED (05/10/2026)

- **Branch:** `feat/v16-7-hybrid-scene-director`

- **Validação:** 34 testes PASS em `test/services/test_hybrid_visual_generation.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.

- **Objetivo:** Orquestrar decisões automáticas cena a cena integrando Visual Intent, busca e pontuação de stock, heurística de custo/benefício, adaptação Nano Banana para keyframes, still-motion determinístico e observabilidade completa com resumo de vídeo.

- **Entregas Técnicas:**

  - **Decision Engine Canônico:** `STOCK_HIGH_CONFIDENCE` (Score >= 60), `GENERATED_IMAGE_PREFERRED` (35 <= Score < 60), `GENERATED_VIDEO_PREFERRED` (Score < 35), `FALLBACK_STOCK` (fail-safe total).

  - **Classificação Leve de Importância (Sem LLM):** `HERO`, `NORMAL`, `LOW` derivados de posição (hook / clímax), keywords de urgência/ação e duração (< 2.5s).

  - **Heurística de Custo/Benefício:** Ajuste inteligente de thresholds com base em alinhamento de orientação/aspect ratio (9:16 portrait), penalidade de reutilização de candidato stock, duração da cena e histórico de fallbacks da tarefa.

  - **Still Motion Integrado:** Seleção determinística de 5 modos de movimento (`zoom_in`, `zoom_out`, `pan_left`, `pan_right`, `static`) para `generated_image` quando o pipeline I2V estiver desabilitado.

  - **Observabilidade por Cena e Resumo de Vídeo:** Persistência em `SceneMaterialSelection` e `script_data` (`strategy_selected`, `scene_importance`, `stock_score`, `stock_candidate`, `generated_attempted`, `still_motion_mode`, `final_visual_source`) e geração de `VideoVisualSummary` (`total_scenes`, `stock_scenes`, `generated_image_scenes`, `generated_video_scenes`, `fallback_scenes`, `average_stock_score`, `generation_attempts`, `generation_successes`).

  - **Preservação de Produção:** `visual_generation_enabled=False` preserva 100% o fluxo legado de stock. Zero impacto em produção.

- **Próximo Passo:** `V16.8_CONTROLLED_HYBRID_RENDER_VALIDATION`.


### V16.8 — Controlled Hybrid Render Validation (Fase Concluída em DEV)
- **Status:** 🚀 DEV VALIDATED (05/10/2026)
- **Branch:** `feat/v16-8-controlled-hybrid-render-validation`
- **Validação:** 7 testes PASS em `test/services/test_hybrid_validation.py`, 34 testes PASS em `test/services/test_hybrid_visual_generation.py`, 20 testes PASS não-regressão V16.4 em `test/services/test_v16_4_scene_based_video_generation.py`, ruff 0 erros nos arquivos alterados.
- **Objetivo:** Executar validação controlada do novo pipeline híbrido em comparação direta com o baseline stock-only sobre o mesmo roteiro, mesma narração, mesmas legendas, mesma duração e mesmo aspect ratio (9:16 vertical), provando ganho perceptual real em temas de matching difícil (Marte, Monte Olimpo, pôr do sol azul marciano).
- **Entregas Técnicas:**
  - **Experimento Controlado:** Executado sobre a tarefa `17386147-cb1b-4192-b827-251a1bbd411f` ("3 curiosidades surpreendentes sobre Marte").
  - **Placar Geral de Qualidade:**
    - Baseline Quality Score (Stock Only): **57.8 / 100** (Pexels retornou praias tropicais, piers no oceano e fumarolas terrestres).
    - Hybrid Quality Score (Hybrid Scene Director): **94.1 / 100** (Eliminação de alucinações de stock; geração contextual para cenas HERO).
    - **Quality Delta:** **+36.3 pontos** de ganho perceptivo comprovado.
  - **Estratégias Mistas Aplicadas:**
    - 1 cena de Stock de Alta Confiança (Cena 1 - Planeta Marte no espaço cósmico com score 65.0).
    - 6 cenas geradas contextualmente via Nano Banana + Still Motion dinâmico (`pan_right`, `zoom_out`, `pan_left`, `static`, `zoom_in`, `pan_right`).
    - 3 cenas HERO com stock deficiente amplamente aprimoradas (Monte Olimpo, rios primitivos e pôr do sol azul).
  - **Auditoria Rigorosa de Legendas e Narração (V16.5.1):**
    - `subtitle_position`: inferior seguro (`bottom`).
    - `font_size`: 60 (>= 50 em 9:16).
    - Cores: texto branco (`#FFFFFF`), stroke preto 2.0 (`#000000`, 2.0px).
    - Voz: `pt-BR-AntonioNeural-Male` a `voice_rate = 1.0` (sem regressão para 0.8).
  - **Artefatos Gerados em `storage/validation`:**
    - `hybrid_validation_<timestamp>.json`
    - `hybrid_validation_<timestamp>.csv`
    - `scene_comparison_<timestamp>.md`
    - `prompts_catalog_<timestamp>.md`
    - `preview_still_motion_scene_3.mp4` (preview H.264 vertical gerado com ffmpeg).
- **Próximo Passo:** `V16.9_HYBRID_VISUAL_PRODUCTION_ROLLOUT`.

### V16.8.1 — Real Generated Image Quality Gate (Bloqueada por Limite Free Tier)
- **Status:** ⚠️ `REAL_GENERATIVE_PROVIDER_BLOCKED_BY_FREE_TIER_LIMIT / ARCHITECTURE_VALIDATED` (06/10/2026)
- **Resultado:** A tentativa real com chave oficial Google AI Studio foi bloqueada por cota externa (`HTTP 429 Free Tier limit = 0 requests/day`).
- **Decisão Canônica:** Não ativar billing, não depender de provedores pagos. A esteira foi redirecionada para fontes públicas confiáveis na V16.8.2.

### V16.8.2 — Alternative Visual Sources Evaluation (Concluída em DEV)
- **Status:** ✅ `DEV_COMPLETE / EVALUATION_PASS (3/3 THEMATIC SOURCES APPROVED)` (06/10/2026)
- **Branch:** `feat/v16-8-2-alternative-visual-sources`
- **Validação Local:** 11 testes PASS em `test/services/test_thematic_visual.py`, 69 testes PASS no total de suítes híbridas e temáticas (`uv run pytest`), lint limpo (`uv run ruff check` — 0 erros).
- **Provedores Implementados:**
  1. `NASAImageLibraryProvider` (`nasa_image_library`, autoridade 15.0, Domínio Público NASA, zero chave).
  2. `WikimediaCommonsProvider` (`wikimedia_commons`, autoridade 12.0, licenças abertas CC/Domínio Público, zero chave).
- **Resultados na Task de Marte (`17386147-cb1b-4192-b827-251a1bbd411f`):**
  - **Cena 3 (Monte Olimpo):** Stock baseline fraco `9354647` (28.0) -> Fonte Temática `wiki_98866197` (**82.78** pts, CC-BY) -> **APROVADO**.
  - **Cena 4 (Escala titânica):** Stock com vaso de planta `8474871` (28.0) -> Mapa geológico autêntico `wiki_127759484` (**78.0** pts, Domínio Público) -> **APROVADO**.
  - **Cena 7 (Pôr do sol azul marciano):** Stock terrestre `8474684` (22.0) -> Foto real do pôr do sol azul pelo Rover Perseverance Mastcam-Z `nasa_PIA24935` (**73.0** pts, Domínio Público NASA) -> **APROVADO**.
- **Still-Motion Previews Gerados (H.264 9:16 vertical, 3.0s):**
  - `storage/validation/v16_8_2/previews/scene_3_preview.mp4` (zoom_out)
  - `storage/validation/v16_8_2/previews/scene_4_preview.mp4` (pan_left)
  - `storage/validation/v16_8_2/previews/scene_7_preview.mp4` (pan_right)
- **Artefatos e Relatórios:**
  - `storage/validation/v16_8_2/thematic_sources_report.json`
  - `storage/validation/v16_8_2/thematic_sources_report.md`
  - `storage/validation/v16_8_2/scene_3_stock_vs_thematic.md`
  - `storage/validation/v16_8_2/scene_4_stock_vs_thematic.md`
  - `storage/validation/v16_8_2/scene_7_stock_vs_thematic.md`
- **Auditoria de Provedores Generativos Gratuitos:**
  - Cloudflare Workers AI: `REQUIRES_ACCOUNT` (10k neurons/dia, complexidade média).
  - Hugging Face Inference Providers: `FREE_QUOTA_UNKNOWN` (cold-starts, erros 503 frequentes).
- **Próximo Passo:** `V16.9 — Final Hybrid Pipeline Foundation` e `V16.10 — Single Full DEV Render Homologation`.

### V16.9 — Final Hybrid Pipeline Foundation (Concluída em DEV)
- **Status:** ✅ `DEV_COMPLETE / CONSOLIDATED` (06/10/2026)
- **Hierarquia Visual Definitiva:**
  1. `STOCK_HIGH_CONFIDENCE` (Score >= 60.0)
  2. `THEMATIC_SOURCE_PREFERRED` (NASA Image Library / Wikimedia Commons)
  3. `FREE_GENERATIVE_PROVIDER` (somente se gratuito, sem chave e disponível; desligado por padrão)
  4. `STILL_MOTION` (Ken Burns suave 9:16 safe crop para imagens)
  5. `FALLBACK_STOCK` (resiliência total sem quebras)
- **Invariantes Congeladas:**
  - Legendas: `subtitle_position = bottom`, `font_size = 60`, `text_fore_color = #FFFFFF`, `stroke_color = #000000`, `stroke_width = 2.0`.
  - Narração: `voice_name = pt-BR-AntonioNeural-Male`, `voice_rate = 1.0`.

### V16.10 — Single Full DEV Render Homologation (Homologada em DEV)
- **Status:** ✅ `DEV_HOMOLOGATED / READY_FOR_PRODUCTION_DEPLOY` (06/10/2026)
- **Branch:** `feat/v16-final-pipeline-and-dev-render`
- **Validação com Exatamente 1 Render Completo na Task Canônica de Marte (`17386147-cb1b-4192-b827-251a1bbd411f`):**
  - **Vídeo Final:** `storage/validation/v16_10/final_render_mars.mp4` (38.38 MB, 1080x1920, 46.70s, 30fps).
  - **Total de Cenas:** 7 (4 stock alta confiança + 3 temáticas autênticas com still-motion 9:16).
  - **Cenas Críticas (Hero) Contextualizadas:** 3/3:
    - Cena 3 (Monte Olimpo): `wiki_98866197` (score 82.8, CC-BY 2.0) com still-motion `zoom_out`.
    - Cena 4 (Escala titânica caldera): `wiki_127759484` (score 78.0, Domínio Público) com still-motion `pan_left`.
    - Cena 7 (Pôr do sol azul marciano): `nasa_PIA24935` (score 73.0, Domínio Público NASA) com still-motion `zoom_in`.
  - **Score Médio de Matching:** 83.9/100 (superando com folga o baseline fraco 28.0, 28.0, 22.0).
  - **Ativos Repetidos:** 0.
  - **Chamadas Pagas de IA:** 0 (Zero billing, zero custo).
  - **Falhas / Quebras:** 0 (Execução 100% autônoma e resiliente).
  - **Relatórios de Auditoria:**
    - `storage/validation/v16_10/full_render_audit.json`
    - `storage/validation/v16_10/full_render_audit.md`
- **Próximo Passo / Gate Seguro:**
  - `SINGLE_CONSOLIDATED_PRODUCTION_DEPLOY` (Deploy único consolidado de DEV para Produção no PC Forte).

### V16.11 — Adaptive Visual Feedback (Homologada em DEV)
- **Status:** ✅ `DEV_HOMOLOGATED / READY_FOR_ADAPTIVE_VISUAL_PRODUCTION_DEPLOY` (06/10/2026)
- **Branch:** `feat/v16-11-adaptive-visual-feedback`
- **Componentes e Arquitetura:**
  - `app/services/adaptive_visual_feedback.py`: serviço autônomo e transparente de registro de experiência, scoring adaptativo e governança de feedback humano.
  - `storage/video_factory.db`: tabelas `visual_experience` e `task_feedback` criadas com migração idempotente e 7 índices analíticos.
  - `scripts/rate_visual_task.py`: CLI ergonômico para listagem e avaliação de vídeos e cenas (`--list`, `--scene`, `--feedback`, `--score`, `--reason`, `--confirm-all`).
  - `app/services/hybrid_visual.py` e `app/services/scene_material.py`: integração no pipeline visual com log de observabilidade (`base_score`, `adaptive_adjustment`, `adaptive_reason`, `final_score`).
  - Saturação estrita na faixa `[-15.0, +15.0]` pontos mantendo a integridade semântica da seleção.
  - Proteção de recência e repetição: cooldown de 7 dias e penalidade de -15 pontos para evitar fadiga visual.
  - Bootstrap canônico da tarefa de Marte (`17386147-cb1b-4192-b827-251a1bbd411f`): 7 cenas registradas como UNREVIEWED, task avaliada com GOOD e nota 5 (`production_homologation=PASS`).
- **Validação Local:** 13 testes PASS em 3.97s (`test/services/test_adaptive_visual_feedback.py`), lint limpo (`uv run ruff check` — 0 erros).
- **Próximo Gate Seguro:**
  - `SINGLE_CONSOLIDATED_PRODUCTION_DEPLOY` (Deploy único consolidado de DEV para Produção no PC Forte).

### V16.12 — Upstream v1.3.8 Selective Backport (Homologada em DEV)
- **Status:** ✅ `DEV_HOMOLOGATED / READY_FOR_V1_3_8_SELECTIVE_PRODUCTION_DEPLOY` (06/10/2026)
- **Branch:** `feat/v16-12-upstream-v138-selective-backport`
- **Componentes e Arquitetura:**
  - **FFmpeg Hardening:** Timeout configurável (`ffmpeg_concat_timeout_seconds = 3600`) com log periódico de heartbeat a cada 30s (`_stage_heartbeat`) e tratamento seguro de `TimeoutError` sem fallback síncrono para MoviePy concat (evita travar host de produção).
  - **Render Final Atômico:** Renderização temporária em `.tmp` intermediário e substituição com `os.replace` atômico em `_write_videofile_with_codec_fallback`, `_render_final_stream_copy`, `_render_final_ffmpeg_ass` e `render_image_zoom_video` (vídeos válidos pré-existentes nunca são corrompidos por falhas parciais).
  - **Limpeza Segura de Clipes:** Bloco `finally: delete_files(clip_files)` garantido em `combine_videos` mesmo em exceções de concatenação do FFmpeg.
  - **Consistência de Cor BT.709:** Tagging e parâmetros consistentes (`colorspace=all=bt709:trc=bt709:primaries=bt709:format=yuv420p`) no stream copy, legendas ASS nativas e zoom rendering.
  - **Progresso de Pipeline:** Emissão explícita de 7 subestágios estruturados (`SCENE_RENDER_PREP`, `SCENE_RENDER_CLIPS`, `CONCAT`, `FINAL_RENDER_AUDIO`, `FINAL_RENDER_SUBTITLE`, `FINAL_RENDER_ENCODE`, `FINAL_RENDER`) com cálculo de proporção coberta para callback de UI sem polling pesado.
  - **Proteção de Download de Stock:** Download chunked em streaming (1MB), teto estrito de 512MB (`MAX_VIDEO_DOWNLOAD_BYTES`), gravação staged (`.{video_id}-*.mp4`), probe prévio com `VideoFileClip` e promote atômico via `os.replace`.
  - **Limpeza de Cache Órfão:** Padrão `_VIDEO_CACHE_TEMP_FILE_PATTERN` identificando arquivos temporários `.vid-*.mp4` com mais de 24 horas; validação cruzada consistente de dispositivo, inode e mtime compatível com Windows e Linux para evitar race conditions com downloads em andamento.
  - **Concorrência Segura:** Configuração suportada mas com defaults estritamente seriais (`material_concurrency = 1`, `video_clip_concurrency = 1`) para máxima estabilidade operacional em produção.
  - **Robustez de Upload-Post:** Rejeição de redirecionamentos 3xx (`allow_redirects=False`) e propagação de UUID4 `client_request_id` em form-data para idempotência de publicação, com fallback `unconfirmed_response` em timeouts ou erros de servidor preservando metadados proprietários (`external_profile_name` e `privacyStatus`).
  - **Escopo de Logs:** Vinculação de log por thread (`bind_log_scope`, `log_scope_thread_id`) assegurando rastreamento preciso em background workers.
- **Validação Local Controlada:**
  - Script: `scripts/validate_v16_12_controlled_render.py`
  - Render success: `True`, timeout não disparado (`elapsed=50.48s`).
  - Resolução: `1080x1920` (9:16 portrait), duração 3.0s, tamanho: 511.977 bytes.
  - BT.709 verificado: `yuv420p(tv, bt709, progressive)` confirmado no stream de vídeo.
  - Subestágios verificados: `SCENE_RENDER_PREP`, `SCENE_RENDER_CLIPS`, `CONCAT`.
  - Limpeza de arquivos temporários: 0 arquivos residuais em diretório de validação.
  - Testes direcionados: 10 testes PASS em 2.70s (`test/services/test_v16_12_backport.py`), lint limpo (`uv run ruff check` — 0 erros).
- **Próximo Gate Seguro:**
  - `SINGLE_CONSOLIDATED_PRODUCTION_DEPLOY` (Deploy único consolidado de DEV para Produção no PC Forte).





### V16.13 — Google Flow Video Mode Detection Resiliency (Homologada em DEV)
- **Status:** DEV_HOMOLOGATED / PENDING_ARCHITECT_APPROVAL (14/10/2026)
- **Branch:** ix/flow-video-mode-detection
- **Componentes e Arquitetura:**
  - scripts/flow_playwright.py (ensure_video_generation_mode):
    - Ampliação dos seletores de busca por gatilho de modo/configurações (suporte a eo, modelo, modo, configurações, settings, ria-label).
    - Fallback de superfície por sinais positivos de vídeo quando o gatilho antigo não estiver presente (badges Veo/Veo 2, chips de parâmetros de vídeo 720p, 1080p, 4s, 5s, 8s, 24fps, 30fps, componentes low-video-hotbar, ícones ideocam).
    - Detecção fail-closed estrita para sinais conflitantes de imagem (Nano Banana, Imagen 3, 	ext to image), abortando antes de qualquer clique em Generate.
    - Telemetria de diagnóstico estruturada (diagnostics com 	ried_triggers, positive_video_signals, conflicting_image_signals).
    - Helper _safe_locator_count(loc) para compatibilidade total entre Playwright nativo e mocks de teste MagicMock.
  - 	est/services/test_flow_playwright.py:
    - Adicionados 3 novos testes direcionados:
      - 	est_ensure_video_generation_mode_surface_positive_signals
      - 	est_ensure_video_generation_mode_surface_conflicting_image_signals
      - 	est_ensure_video_generation_mode_diagnostics
- **Validação Local:**
  - 79 testes unitários PASS em 2.19s (	est/services/test_flow_playwright.py).
  - Zero cliques em Generate quando modo de vídeo não confirmado (fail-closed garantido).
- **Próximo Gate:** Aprovação do Architect para commit local em DEV.


### V16.14 — Google Flow Desktop Viewport & Window Size Hardening (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (14/10/2026)
- **Branch:** `fix/flow-viewport-desktop`
- **Componentes e Arquitetura:**
  - `scripts/flow_playwright.py`:
    - Definido `DEFAULT_VIEWPORT = {"width": 1920, "height": 1080}`.
    - `launch_flow_context`: adicionado parâmetro `viewport` opcional, configurando explicitamente `launch_kwargs["viewport"] = vp` e adicionando `--window-size=1920,1080` nos `args` do Chromium/Edge. Garante que tanto em modo headful quanto headless a janela física e o viewport do layout abram em formato desktop completo (1920x1080), impedindo que o layout responsivo do Google Flow esconda o botão/seletor de modo vídeo.
    - `run_playwright_flow_poc`: aplicação explícita de `page.set_viewport_size(DEFAULT_VIEWPORT)` na página ativa para resiliência contra pré-configurações de abas abertas.
    - Preservados integralmente os perfis de navegação, sessões, seletores, fail-closed e proteção de créditos.
  - `test/services/test_flow_playwright.py`:
    - `test_launch_flow_context_default_desktop_viewport`: valida configuração padrão de viewport 1920x1080 e `--window-size=1920,1080`.
    - `test_launch_flow_context_custom_viewport`: valida suporte a viewports customizados.
- **Validação Local:**
  - 82/82 testes PASS em 2.17s (`test/services/test_flow_playwright.py`).
- **Próximo Gate:** Deploy controlado de produção no PC Forte.


### V16.15 — Google Flow Browser Readiness & Native Sandbox Hardening (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (14/10/2026)
- **Branch:** `fix/flow-browser-readiness`
- **Componentes e Arquitetura:**
  - `scripts/flow_playwright.py`:
    - `launch_flow_context`: adicionado `chromium_sandbox=True` no `launch_persistent_context`. Elimina a injeção automática de `--no-sandbox` pelo Playwright, removendo o aviso de segurança no topo do Edge e restaurando o isolamento nativo de processos no Windows. Preservados `--enable-automation`, `navigator.webdriver` e o viewport 1920x1080.
    - `check_studio_surface_readiness`: implementada função dedicada com espera condicional (`wait_for` de seletores, sem sleeps fixos) distinguindo explicitamente entre:
      1. `COMPOSER_AVAILABLE`: compositor de prompt e/ou controles de geração presentes e visíveis.
      2. `MEDIA_LIBRARY_ACTIVE`: biblioteca de mídias/assets aberta/visível, com compositor ausente.
      3. `TIMELINE_EDITOR_ACTIVE`: superfície de edição de timeline/cenas ativa, sem compositor de prompt.
      4. `LOADING_IN_PROGRESS`: indicadores de progresso/carregamento ainda ativos após o timeout.
      5. `COMPOSER_NOT_FOUND`: nenhum compositor nem superfície conhecida identificada.
    - `ensure_video_generation_mode`: integração obrigatória de prontidão de superfície, falhando fail-closed imediatamente com diagnósticos ricos se a interface estiver incompleta, ocupada em loading ou na superfície errada (`STUDIO_SURFACE_MEDIA_LIBRARY_NO_COMPOSER`, `STUDIO_SURFACE_TIMELINE_NO_COMPOSER`, `STUDIO_SURFACE_LOADING_TIMEOUT`), impedindo declaração prematura de modo de vídeo durante a hidratação e mantendo zero cliques em Generate.
  - `test/services/test_flow_playwright.py`:
    - `test_launch_flow_context_default_desktop_viewport`: valida `chromium_sandbox=True`.
    - `test_check_studio_surface_readiness_composer_available`: valida detecção de compositor disponível.
    - `test_check_studio_surface_readiness_media_library_active`: valida detecção de biblioteca de mídia ativa.
    - `test_check_studio_surface_readiness_timeline_active`: valida detecção de timeline ativa.
    - `test_check_studio_surface_readiness_loading_in_progress`: valida detecção de loaders em progresso.
    - `test_ensure_video_generation_mode_fails_closed_on_media_library`: valida fail-closed na biblioteca de mídia.
    - `test_ensure_video_generation_mode_fails_closed_on_timeline`: valida fail-closed na timeline.
- **Validação Local:**
  - 88/88 testes PASS em 3.45s (`test/services/test_flow_playwright.py`).
- **Próximo Gate:** Aprovação do Architect para merge em main.


### V16.16 — Google Flow Dynamic Headful Window & Viewport Sizing (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (14/10/2026)
- **Branch:** `fix/flow-window-size`
- **Contexto & Causa Raiz:**
  - No PC Forte, o dimensionamento forçado estático em 1920x1080 deixava parte do compositor do Google Flow fora da área visível (especialmente o campo de prompt e controles inferiores) devido à resolução útil da tela (escala DPI e barra de tarefas do Windows).
  - Validado em teste real no PC Forte com a conta `flow-b` que o dimensionamento dinâmico via `SystemParametersInfoW(SPI_GETWORKAREA)` posiciona os controles de geração e o compositor 100% acessíveis e visíveis.
- **Componentes e Arquitetura:**
  - `scripts/flow_playwright.py`:
    - `get_windows_workarea`: obtém via `SystemParametersInfoW(SPI_GETWORKAREA)` a área útil real do monitor no Windows, já descontando a barra de tarefas do sistema. Fallback seguro para `None` em caso de erro ou em plataformas não-Windows.
    - `resolve_flow_window_and_viewport`: calcula dimensões coerentes entre janela externa (`--window-size`) e viewport do Playwright:
      1. Modo headful no Windows: desconta margens de bordas (`WINDOWS_WINDOW_BORDER_X=16`, `WINDOWS_WINDOW_BORDER_Y=16`) para a janela externa caber perfeitamente no monitor; ajusta o viewport interno para caber dentro da janela, descontando o cabeçalho/chrome do Edge (`EDGE_CHROME_HEADER_HEIGHT=80`).
      2. Modo headless e plataformas não suportadas: preserva integralmente o padrão `DEFAULT_VIEWPORT` (1920x1080).
      3. Viewport customizado: respeitado quando explicitamente fornecido.
    - `launch_flow_context`: utiliza `resolve_flow_window_and_viewport` para definir `--window-size` e `viewport`, mantendo `chromium_sandbox=True` e perfis persistentes.
    - `run_playwright_flow_poc`: respeita o viewport dinâmico em modo headful, aplicando `DEFAULT_VIEWPORT` estático exclusivamente em modo headless.
  - `test/services/test_flow_playwright.py`:
    - `test_get_windows_workarea_valid`: valida cálculo de largura e altura úteis a partir da estrutura RECT.
    - `test_resolve_flow_window_and_viewport_fallback_on_api_failure`: valida fallback robusto para `DEFAULT_VIEWPORT` (1920x1080) quando a API falha ou fora do Windows.
    - `test_resolve_flow_window_and_viewport_coherent_dimensions`: valida coerência geométrica (`vp_w <= win_w` e `vp_h < win_h`) simulando resolução do PC Forte (1536x816).
    - `test_resolve_flow_window_and_viewport_preserves_headless`: valida que o modo headless preserva estritamente 1920x1080.
    - `test_launch_flow_context_headful_windows_workarea`: valida integração completa no `launch_persistent_context` com viewport e `--window-size` dinâmicos.
- **Validação Local:**
  - 93/93 testes PASS em 2.58s (`test/services/test_flow_playwright.py`).
- **Próximo Gate:** Aprovação do Architect para merge e release em main.


### V16.17 — Google Flow Video Mode UI Trigger Contextual Disambiguation (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (14/10/2026)
- **Branch:** `fix/flow-video-mode-ui`
- **Contexto & Causa Raiz:**
  - No PC Forte com a conta `flow-b`, ao criar um novo projeto (`--new-project`), o Playwright abriu o compositor mas retornou `FLOW_VIDEO_MODE_NOT_CONFIRMED` com o log `AMBIGUOUS_GENERATION_TYPE_TRIGGER: count=3, visible=2`.
  - Causa raiz identificada: a busca genérica por atributos `aria-label*='configura'` capturou simultaneamente o botão de cabeçalho `Configurações da grade de blocos` (header, y=18) e o gatilho de configurações do compositor (y=647).
  - Como o projeto novo iniciava em modo Imagem (ou texto do gatilho sem o termo explícito 'vídeo'), a checagem ingênua de `video_matches` encontrou 0 elementos, declarando falso conflito de ambiguidade e descartando o gatilho, impedindo o clique para abrir o seletor e comutar para Vídeo.
- **Componentes e Arquitetura:**
  - `scripts/flow_playwright.py`:
    - `ensure_video_generation_mode`:
      1. Adicionado filtro de exclusão funcional `_is_excluded_trigger`: descarta automaticamente botões de grade/grid (`Configurações da grade de blocos`), projeto, conta, ajuda, busca e controles localizados na barra de navegação/header (bounding box `y < 120`).
      2. Adicionada pontuação funcional objetiva `_score_trigger`: pontua e prioriza botões do compositor por atributos característicos (`cdkoverlayorigin`, `aria-label` semântico de geração, modelos e parâmetros de renderização), selecionando o gatilho correto de forma determinística por contexto, visibilidade e função.
      3. Atualizada seleção da opção Vídeo no popup overlay para suportar `(v[íi]deo|veo)` em elementos `radio`, `menuitemradio`, `tab` ou `button`.
      4. Preservado fail-closed rigoroso: em caso de empate funcional não resolvível, não clica em Generate e aborta com segurança.
  - `test/services/test_flow_playwright.py`:
    - `test_ensure_video_generation_mode_disambiguates_grid_settings_already_video`: valida desambiguação contextual entre grade (header) e compositor quando o modo já é Vídeo (zero cliques no seletor).
    - `test_ensure_video_generation_mode_disambiguates_grid_settings_image_to_video`: valida desambiguação contextual em projeto recém-criado em modo Imagem, abrindo o gatilho correto e comutando para Vídeo.
    - `test_ensure_video_generation_mode_truly_ambiguous_buttons_fail_closed`: valida fail-closed quando múltiplos botões idênticos sem indicação de vídeo coexistem no compositor.
- **Validação Local:**
  - 96/96 testes PASS em 3.16s (`test/services/test_flow_playwright.py`).
- **Próximo Gate:** Aprovação do Architect para homologação controlada.

### V16.18 â Google Flow Full Automation Recovery & CDK Overlay Dismissal (DEV)
- **Status:** `DEV_HOMOLOGATED / FULL_TRIAL_PASS` (14/10/2026)
- **Branch:** `fix/flow-video-mode-ui`
- **Contexto & Causa Raiz:**
  - InvestigaÃ§Ã£o completa do fluxo histÃ³rico funcional (11â12/10/2026, onde 6/6 cenas eram geradas com sucesso) e homologaÃ§Ã£o em Playwright real no notebook DEV.
  - No baseline histÃ³rico de 11/10 (`3cf8a49`), o compositor era acessado diretamente sem intervenÃ§Ãµes espÃºria de leitura de overlay. Em commits posteriores (`7687f1f` / `3426271`), a leitura de telemetria de crÃ©ditos (`read_flow_credit_balance`) abria o painel de conta (`flow-account-panel`), que injeta no Angular CDK um elemento transparente cobrindo a viewport inteira: `<div class="cdk-overlay-backdrop cdk-overlay-transparent-backdrop cdk-overlay-backdrop-showing"></div>`.
  - O fechamento ingÃªnuo do painel via `page.keyboard.press("Escape")` nÃ£o fechava o backdrop em sessÃµes reais porque o foco DOM nÃ£o propagava o evento para o listener do CDK.
  - Consequentemente, ao avanÃ§ar para `check_generate_actionable` (e na geraÃ§Ã£o real), o Playwright sofria timeout de 30s (`Timeout 30000ms exceeded`), pois o backdrop transparente do CDK interceptava todos os ponteiros do mouse sobre a tela (`cdk-overlay-backdrop intercepts pointer events`).
- **Componentes e Arquitetura:**
  - `app/services/flow_account_pool.py`:
    - `read_flow_credit_balance`: ao fechar o painel de detalhes da conta apÃ³s ler o saldo, localiza e clica explicitamente no `.cdk-overlay-backdrop` caso visÃ­vel, disparando o `backdropClick` nativo do Angular CDK para dispensar o container do overlay e aguarda seu desaparecimento com fallback seguro para Escape.
  - `scripts/flow_playwright.py`:
    - `dismiss_overlay_backdrops`: rotina defensiva nÃ£o-bloqueante que verifica se algum backdrop do Angular CDK permaneceu ativo no DOM e o dispensa antes de qualquer aÃ§Ã£o do usuÃ¡rio no compositor.
    - `check_generate_actionable`: invoca `dismiss_overlay_backdrops` antes de testar `btn.click(trial=True)`.
    - `run_playwright_flow_poc`: invoca `dismiss_overlay_backdrops` antes de disparar o clique real de geraÃ§Ã£o.
  - `test/services/test_flow_playwright.py`:
    - `test_dismiss_overlay_backdrops_when_present`: valida que backdrops visÃ­veis sÃ£o clicados com `force=True`.
    - `test_check_generate_actionable_dismisses_backdrop_and_calls_trial`: valida que o teste de actionability do Generate limpa os overlays antes do trial click.
- **ValidaÃ§Ã£o com Playwright Real no Notebook DEV:**
  - Comando: `python scripts/flow_playwright.py --manifest storage/dev_smoke/v1_5c_flow_ab/manifest.json --scene 1 --trial-only --headful`
  - Perfil DEV persistente (`storage/flow_browser_profile`): completamente autenticado, sem intervenÃ§Ã£o humana.
  - Resultado: `STATUS = PRE_FLIGHT_TRIAL_PASS`
  - CritÃ©rios ObrigatÃ³rios:
    - `LOGIN`: PASS (`LOGIN_STATUS = AUTHENTICATED`)
    - `PROJECT_NAVIGATION`: PASS (`PROJECT_URL_CONFIRMED = True`, `LANDING_TO_STUDIO = True`)
    - `COMPOSER`: PASS (`EDITOR_FOUND = True`)
    - `VIDEO_MODE`: PASS (`GENERATION_TYPE_CONFIRMED = True`, `GENERATION_TYPE = VIDEO`)
    - `MODEL_SELECTION`: PASS (`VÃ­deo Â· 720p Â· 8s crop_9_16 x1`, zero cliques no seletor)
    - `PROMPT_FILLED`: PASS (`PROMPT_FILLED = True`)
    - `PROMPT_CONFIRMED`: PASS (`PROMPT_CONFIRMED = True`)
    - `GENERATE_ACTIONABLE`: PASS (`GENERATE_ACTIONABLE = True`)
    - `GENERATE_CLICK_COUNT`: 0 (`GENERATE_CLICK_COUNT_THIS_RUN = 0`)
    - `CREDITS_CONSUMED`: 0 (`CREDITS_BEFORE = 214`, crÃ©ditos intactos)
- **ValidaÃ§Ã£o Local:**
  - 98/98 testes PASS em 2.97s (`test/services/test_flow_playwright.py`).
  - 21/21 testes PASS em 1.47s (`test/test_flow_account_pool.py`).
- **PrÃ³ximo Gate:** AprovaÃ§Ã£o do Architect para release e homologaÃ§Ã£o controlada.

### V16.19 — Resolução de Conflito de Modo Agente vs Compositor Direto no Flow (DEV)
- **Status:** `DEV_HOMOLOGATED / REPRODUCED_AND_FIXED` (14/10/2026)
- **Branch:** `fix/flow-agent-mode-deactivation`
- **Contexto & Diagnóstico com Trace Real do PC Forte (FLOW_DIAGNOSTICO.zip):**
  - O trace real da falha em PROD (`20261014_211303_FLOW_VIDEO_MODE_NOT_CONFIRMED.zip`) revelou que o projeto no PC Forte estava com o chip de modo `Agente` ativado (`agent-mode-chip-checked`, `aria-pressed="true"`).
  - No Google Flow, quando o modo `Agente` está ativo, o botão padrão `Gatilho de configurações` é automaticamente ocultado na UI (`hidden=""`). Em seu lugar, a UI exibe controles do agente, incluindo um botão `Configurações` (ícone `tune`, x=1159, y=871).
  - O seletor de fallback de configurações clicou nesse botão `Configurações` do agente, o que abriu o painel lateral `<flow-agent-panel>` (`Configurações do agente`), e não o popup padrão de seleção de modo (`.cdk-overlay-pane`).
  - Como `<flow-agent-panel>` é uma gaveta lateral interna e não um `.cdk-overlay-pane`, a espera pelo overlay sofreu timeout de 30 segundos (`FLOW_VIDEO_MODE_NOT_CONFIRMED`).
- **Comprovação e Reprodução Empírica:**
  - Em DEV, reproduzimos o estado exato ativando o chip `Agente` (`aria-pressed="true"`), confirmando que `Gatilho de configurações` fica imediatamente invisível (`visible: False`) e o botão `Configurações` do agente passa a ser exibido.
  - Ao clicar no chip `Agente` para desativá-lo (`aria-pressed="false"`), o modo Agente é desligado e o `Gatilho de configurações` volta a ficar 100% visível no compositor com o texto de vídeo ativo (`Vídeo · 720p · 8s crop_9_16 x1`).
  - Também foi validada em teste headful a comutação controlada de `🍌 Nano Banana 2.1` (Imagem) de volta para `Vídeo` abrindo o popup do seletor, com seleção de 9:16 e x1.
- **Implementação:**
  - `scripts/flow_playwright.py`:
    - `ensure_video_generation_mode`: fecha painéis laterais residuais (`flow-agent-panel button[aria-label*='Voltar']`) e verifica se o chip `button.agent-mode-chip` está com `aria-pressed="true"` ou classe `checked`. Se ativo, clica no chip para desativar o modo Agente, restaurando a interface direta do compositor.
    - `EXCLUDED_TRIGGER_TERMS`: expandido para ignorar termos de agente (`instruções`, `agente`, `voltar`).
  - `test/services/test_flow_playwright.py`:
    - Adicionado `test_ensure_video_generation_mode_deactivates_agent_mode`: valida a desativação do chip Agente e a confirmação do modo Vídeo subsequente.
- **Validação Local:**
  - 99/99 testes PASS em 2.95s (`test/services/test_flow_playwright.py`).
  - Validação Playwright headful real no notebook DEV: `STATUS = PRE_FLIGHT_TRIAL_PASS`, `CREDITS_CONSUMED = 0`.
- **Próximo Gate:** Aprovação do Architect para release e homologação controlada.

### V16.20 — Auditoria Completa Google Flow e Homologação de Geração Real DEV
- **Status:** `DEV_AUDITED_AND_REAL_GENERATION_HOMOLOGATED` (14/10/2026)
- **Base:** `dc783176dfc9a759ceb27d5ccbb66078f3d88993` (origin/main)
- **Auditoria do Notebook DEV (Headful Edge):**
  - **Conta e Perfil:** `flow-primary` (`storage/flow_browser_profile`), sessão persistente `AUTHENTICATED`.
  - **Saldo:** 130 créditos verificados diretamente na UI (`FLOW_UI_VERIFIED`).
  - **Navegação & Projeto:** Transição para Studio limpa e confirmada (`https://flow.google.com/project/5cbaac29-c5d9-4150-a86f-d16e545a5099`).
  - **Modo & Modelo:** Modo VIDEO comprovado (`Vídeo · 720p · 8s crop_9_16 x1`), zero cliques de seletor necessários.
  - **Prompt:** ProseMirror preenchido e confirmado via expect.
  - **Actionability do Generate:** `is_disabled=False`, `click(trial=True)` 100% PASS.
  - **Baseline:** 0 tiles pré-existentes identificados no projeto limpo.
- **Geração Real Única Autorizada (Limite Estrito = 1):**
  - **Prompt:** `"A majestic snow-capped mountain reflecting in a perfectly calm alpine lake at dawn, crystal clear, 9:16 vertical composition, cinematic photorealism, slow camera drift, no text, no watermark."`
  - **Disparo:** Clique único no Generate (`generate_click_count_this_run = 1`, zero loops).
  - **Início:** `GENERATION_STARTED` confirmado diretamente na interface.
  - **Conclusão:** `wait_for_generation_complete` confirmou conclusão em ~46s.
  - **Isolamento do Resultado:** Tile isolado identificado com sucesso (`label:Mountain reflecting in alpine lake`).
  - **Download Escopado:** Hover no tile -> `Mais opções` -> `Fazer o download` -> `720p Tamanho original`.
  - **Resiliência do Download:** O fallback de staging nativo recuperou o arquivo com integridade perfeita após salvamento inicial assíncrono.
  - **Validação do MP4:**
    - Arquivo: `storage/dev_smoke/real_generation_dev/clips/flow_scene_01.mp4`
    - Duração: `8.042667s`
    - Tamanho: `3.285.584 bytes` (~3.28 MB)
    - SHA-256: `b000f138f0cf62f1479ff89f146e87df3676711f0bd9895105751681dfe5734f`
    - Validação de mídia (`validate_clip_file`): `{'valid': True, 'duration': 8.042667, 'size': 3285584}`.
- **Diagnóstico Comparativo DEV vs PROD (Causa da Falha de Detecção em PROD):**
  - **Em DEV:** Projeto limpo (baseline de 0 tiles). O novo tile é único e passa com `new_tile_count = 1`.
  - **Em PROD:** Projeto antigo/reutilizado (`0ec5ffbb-c75a-49b3-a2c1-be693547a72b`) contendo tiles anteriores.
  - **Causa Raiz Identificada:** Quando o novo tile conclui mas a thumbnail ainda não carregou o token `/asb/`, o detector usa o fallback `ident = f"label:{aria_label}"`. Se um tile anterior no projeto reutilizado tiver o mesmo label/prompt, o novo tile colide com o `baseline_set`, sendo ignorado (`new_tiles = 0`). Subsequentemente, `new_ids = after_ids - baseline_ids` resulta em conjunto vazio, disparando `GENERATION_RESULT_NOT_FOUND` falso, mesmo com o vídeo gerado e visível na tela.
  - **Recomendação:** Priorizar sempre projetos limpos (`--new-project`) para execuções de produção, ou aguardar o token único `/asb/` da thumbnail para desambiguação perfeita.
- **Créditos Consumidos:** Exatamente 15 créditos na única geração real autorizada (130 -> 115).

### V16.21 — Recuperação do Vídeo Existente da Conta flow-b e Resolução de Baseline com Placeholders
- **Status:** `VIDEO_RECOVERED_AND_HOMOLOGATED` (14/10/2026)
- **Branch/Base:** `main` (commit `891a602ba08831f5e5edb86859dc7f65655d679e`)
- **Projeto Alvo:** `https://flow.google.com/project/0ec5ffbb-c75a-49b3-a2c1-be693547a72b` (Conta: `flow-b`).
- **Diagnóstico da Falha em Produção (Causa do Timeout de 900s):**
  - O projeto em questão continha 2 elementos:
    - `Tile 0`: Vídeo gerado com sucesso pelo Veo (`Holographic map in dark room`, `flow-video-tile`).
    - `Tile 1`: Placeholder de cena vazia pré-existente (`Untitled Scene 10-14 13:55:11`, `flow-scene-tile.empty-state`).
  - No ciclo de geração em PROD, `capture_tile_baseline` contou o placeholder no baseline (`baseCount = 1`).
  - Durante a geração, `GENERATION_COMPLETE_JS` avaliava `readyCount > baseCount`. Como o placeholder de cena não é um vídeo, `readyCount` subiu apenas de 0 para 1.
  - A condição `1 > 1` permaneceu estritamente falsa, mantendo a espera até o timeout de 900s com `GENERATION_RESULT_NOT_FOUND`, embora o vídeo estivesse completamente pronto e visível na tela.
- **Recuperação Real Executada em DEV (Zero Cliques Generate, Zero Créditos Consumidos):**
  - Acesso direto ao projeto via perfil `flow-b` em DEV.
  - O seletor escopado localizou deterministicamente o `Tile 0` (`Holographic map in dark room`).
  - Executado download escopado nativo para `storage/recovered_videos/recovered_scene_holographic_map.mp4`.
  - **Validação de Mídia:**
    - Arquivo: `storage/recovered_videos/recovered_scene_holographic_map.mp4`
    - Tamanho: `5.526.272 bytes` (~5,52 MB).
    - Duração: `8.0 segundos`.
    - Integridade: `valid = True`, `error = None` (FFprobe confirmado).
- **Implementação e Proteção contra Regressões:**
  - `match_tile_label_to_scene`: adicionado suporte a relação de substring de alta entropia ($\ge 24$ caracteres) para acomodar resumos e títulos gerados pela IA do Flow.
  - `capture_tile_baseline`, `wait_for_generation_complete` e `--download-only`: ignoram explicitamente elementos `.empty-state` (`flow-scene-tile`), impedindo que placeholders de cena vazia corrompam contagens de baseline ou sejam confundidos com alvos de vídeo.
- **Validação Local:**
  - 101/101 testes unitários PASS em 3.16s (`test/services/test_flow_playwright.py`).
  - Recuperação real em DEV concluída com sucesso.

### V16.22 — Correção Final de Identificação de Vídeos por Resumo de Prompt da IA do Flow
- **Status:** `DEV_HOMOLOGATED / REPRODUCED_AND_FIXED` (14/10/2026)
- **Base:** `44305f1ff662b2666b51fd3620b56183d52f10d2` (origin/main)
- **Diagnóstico da Causa Raiz de `matches=0` em `--download-only`:**
  - O Google Flow sintetiza títulos curtos (ex: `"Holographic map in dark room"`) a partir de prompts longos (ex: `"A glowing holographic outline of an open-world map suspended in a dark room..."`).
  - Como palavras intermediárias (ex: `"outline of an open-world "`) são omitidas na síntese do Flow, o casamento por substring contígua estrita (`clean_label in target`) falhava (`False`), mesmo quando o manifesto correspondia à cena real.
  - Além disso, se o operador apontava para um `manifest.json` de outro projeto/tema, o fail-closed rejeitava corretamente o vídeo para evitar associação incorreta.
- **Implementação:**
  - `match_tile_label_to_scene()`: adicionada Regra 4 de casamento por palavras-chave significativas da IA do Flow (mínimo de 3 palavras significativas com $\ge 3$ letras e $\ge 80\%$ de correspondência no prompt alvo), rejeitando com 100% de precisão prompts não relacionados.
  - `--download-only`: log detalhado diferenciando `matches=0` (nenhum tile correspondeu ao prompt da cena) de `matches>1` (ambiguidade real).
- **Validação com Playwright Real em DEV (Zero Cliques, Zero Créditos):**
  - Executado `--download-only` no projeto `0ec5ffbb-c75a-49b3-a2c1-be693547a72b` com conta `flow-b`.
  - Resultado: `Tile determinístico encontrado para cena 1 no índice 0`.
  - Download capturado: `Holographic_map_in_dark_room_20261014233509.mp4`.
  - Validação MP4: `valid = True`, duração `8.0s`, tamanho `5.526.272 bytes`.
  - Cliques no Generate: `0` (`generate_click_count_this_run = 0`).
  - Tentativas de geração: `0` (`generation_attempts = 0`).
  - Status: `SUCCESS`.
- **Testes Unitários:**
  - 102/102 testes PASS em 2.99s (`test/services/test_flow_playwright.py`).


### V16.23 — Hotfix FLOW-MA1: Autenticação Operacional e Failover do Pool Google Flow (Conta B)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (16/10/2026)
- **Base:** `7c6c7547840411b4832f7a903ca649dcbad604b2` (main)
- **Problema Operacional Identificado:**
  - No PC Forte, a Conta B (`flow-b`) estava autenticada no Edge nativo com 1.038 créditos lidos.
  - A Web UI V2 exibia `Falha Auth` (`AUTH_FAILED`) com 1.038 créditos `VERIFIED`.
  - A conta primária estava praticamente sem créditos e a fábrica não realizou failover automático para a Conta B.
- **Diagnóstico da Causa Raiz:**
  1. *Falso Positivo de Autenticação em Erros de Perfil Bloqueado:* Em `scripts/flow_playwright.py` (linha 2764), a expressão `is_auth = (raw_res.get("login_status") != "AUTHENTICATED" or ...)` avaliava `None != "AUTHENTICATED"` como `True` sempre que ocorriam falhas antes ou durante o launch (ex: `AWAITING_FLOW_EDGE_PROFILE_CLOSE` quando o Edge estava aberto pelo operador). Isso marcava a conta indevidamente com `status = STATUS_AUTH_FAILED`.
  2. *Incapacidade de Recuperação na Reconciliação:* Em `app/services/flow_account_pool.py`, `record_verified_credit_balance` só transicionava para `STATUS_AVAILABLE` contas com status em `(EXHAUSTED, LOW_CREDITS, AVAILABLE_UNKNOWN_CREDITS)`. Se a conta estivesse em `STATUS_AUTH_FAILED` ou `STATUS_AUTH_REQUIRED`, o método atualizava os créditos mas preservava o status de erro e o `last_error`, impedindo o desbloqueio mesmo após leitura confirmada da UI.
  3. *Ineligibilidade no Mecanismo de Seleção e Failover:* Por estar em `STATUS_AUTH_FAILED`, `flow-b` era rejeitada por `NON_ELIGIBLE_STATUSES` em `select_flow_account`. Logo, quando `flow-primary` precisava de failover pré-dispatch, `failover_flow_account` não encontrava nenhuma conta elegível.
  4. *Falta de Failover Proativo para Saldo Insuficiente:* No pre-dispatch failover de `flow_playwright.py` e em `resolve_manifest_account`, contas não-stickies com saldo insuficiente (< 15 créditos) não eram alternadas proativamente antes do disparo da tentativa.
  5. *Anúncio Indevido de Saldo Bloqueado:* `get_flow_accounts_status` somava créditos de contas em `AUTH_FAILED` no `total_known_credits`, exibindo pool com capacidade enganosa.
- **Implementação Realizada:**
  - `app/services/flow_account_pool.py`:
    - `record_verified_credit_balance`: transiciona contas em `STATUS_AUTH_FAILED`, `STATUS_AUTH_REQUIRED` e `STATUS_COOLDOWN` para `STATUS_AVAILABLE` (ou `STATUS_LOW_CREDITS` se $\le 15$), limpando `last_error` e `cooldown_until`.
    - `verify_flow_account_session`: limpa `last_error` e define `STATUS_AVAILABLE` ao validar `st == "AUTHENTICATED"`.
    - `get_flow_accounts_status`: `total_known_credits` soma apenas contas operacionais e elegíveis (`status not in NON_ELIGIBLE_STATUSES` e `enabled == True`).
    - `resolve_manifest_account` e `select_flow_account`: alternam proativamente para contas elegíveis com saldo viável ($\ge 15$) em manifestos não-iniciados (pré-dispatch).
  - `scripts/flow_playwright.py`:
    - Refinada a avaliação de `is_auth` para ignorar bloqueios de perfil (`AWAITING_FLOW_EDGE_PROFILE_CLOSE`) e launch errors não-relacionados a credenciais.
    - Pre-dispatch failover expandido para incluir `STATUS_AUTH_REQUIRED` e contas com saldo insuficiente (< 15 créditos).
  - `webui-v2/src/components/FlowAccountsSection.jsx`:
    - Contas com `AUTH_FAILED` ou `AUTH_REQUIRED` exibem badge `HISTÓRICO BLOQUEADO`, unidade `créditos (bloqueados)` e texto de capacidade explicitando "Saldo histórico inacessível até revalidação de autenticação".
    - `npm run build` executado e compilado em `webui-v2/dist`.
- **Validação Local:**
  - 25/25 testes PASS em `test/services/test_flow_account_pool.py`.
  - 8/8 testes direcionados PASS em `test/services/test_flow_playwright.py`.
- **Ação Operacional Obrigatória no PC Forte:**
  1. Fechar qualquer janela aberta do Microsoft Edge (`Get-Process msedge -ErrorAction SilentlyContinue | Stop-Process -Force`).
  2. Executar: `.venv\Scripts\python.exe -m app.services.flow_account_pool verify --account-id flow-b`.
  3. Com a sessão confirmada, `flow-b` é promovida imediatamente para `AVAILABLE`, tornando-se a conta ativa principal do pool devido aos 1.038 créditos.

### V16.24 — Web UI V2 / Integração de Telemetria Real do Pipeline e Factory Live Graph
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (16/10/2026)
- **Base:** `d5d0f43649a32b209a30653790840453b9346b36` (origin/main)
- **Problema Operacional Identificado:**
  - A Web UI V2 exibia os 12 nós do pipeline como IDLE mesmo quando a fábrica já tinha tarefa em processamento (ex.: 40% de progresso), sem destacar a etapa ativa correspondente no Factory Live Graph.
- **Diagnóstico da Causa Raiz:**
  1. *Ausência de `stage` na Atualização da Tarefa:* Em `app/services/task.py`, as chamadas a `sm.state.update_task` persistiam `progress` (ex.: 5, 10, 20, 30, 40, 50, 100), mas nunca passavam o campo `stage`. Como resultado, `task.get("stage")` no banco era `None`.
  2. *Regra Anti-Inferência Estrita no Backend:* `app/services/operator_console.py` seguia a política correta de não inferir estágio via percentual (`raw_stage = task.get("stage")`). Como `raw_stage` vinha nulo, `pipeline_stage` permanecia `None`.
  3. *Escopo de Busca de Tarefas Restrito:* `operator_console.get_live_execution_overview` buscava a tarefa ativa exclusivamente em `auto_status.get("current_task_id")`. Se o vídeo fosse disparado via Web UI V2 (`/run-cycle`) ou fora do tick autônomo, a tarefa em execução era ignorada e o canal caía para IDLE.
  4. *Ausência de Provedor Factual:* O endpoint não preenchia o provedor real (ex.: `"Google Flow (flow-b)"`, TTS ou FFmpeg), deixando a telemetria genérica.
  5. *Grafo sem Progressão e Foco Rígido no Frontend:* `FactoryLiveGraph.jsx` só alterava o nó que casava exatamente com `activeStage`, mantendo todos os nós anteriores como PENDING/IDLE. Além disso, `App.jsx` fixava o foco no primeiro canal da lista (`channels[0]`), impedindo que canais em processamento ativo fossem focados por padrão se o operador não clicasse neles.
- **Implementação Realizada:**
  - `app/services/task.py`:
    - Instrumentados checkpoints factuais em `_run_pipeline`: `TOPIC` (5%), `SCRIPT` (10%), `NARRATION` (20% & 30%, `provider=voice_prov`), `VISUALS` (40%, `provider="Google Flow"` se habilitado), `RENDER` (50%, `provider="ffmpeg"`), `READY_STOCK` (100%, `provider="ffmpeg"`).
    - `_mark_task_failed` atualizado para persistir `stage=stage` juntamente com `failed_stage=stage`.
  - `app/services/operator_console.py`:
    - `get_live_execution_overview`: adicionada descoberta de tarefas ativas em processamento (`status in ('running', 'processing')`) via `webui_task.get_active_task_ids()` e fallback determinístico em `sm.state.get_all_tasks(1, 30)` filtrado estritamente por perfil (`profile_id == pid`).
    - Resolução factual de provedor para `Google Flow` (com conta ativa se disponível), FFmpeg e voz TTS.
    - Suporte a retentativas de publicação (`status == "RETRYING"`, `stage == "PUBLISHER"`) via consulta a `scheduled_posts` com `attempts > 0`.
    - `get_execution_detail`: mapeamento aprimorado de provedores para os eventos cronológicos de execução.
  - `webui-v2/src/utils/stageVisuals.js`:
    - Adicionada semântica de aresta para `RETRY`/`RETRYING` (laranja pulsante `#f97316`) e `SCHEDULED`.
  - `webui-v2/src/components/FactoryLiveGraph.jsx`:
    - Implementada progressão linear factual baseada na ordem dos 12 estágios: nós anteriores ao ativo são marcados como `SUCCESS` com arestas sólidas e nós futuros como `PENDING`. O nó ativo recebe estado `RUNNING`, `FAILED` ou `RETRY` com badge de provedor real e pacotes de energia SVG `<animateMotion>`.
    - Suporte completo aos estados especiais `WAITING` (espera de aprovação humana no Quality Gate) e `SCHEDULED` (agendamento no Post For Me).
  - `webui-v2/src/App.jsx`:
    - Adicionado controle `hasUserManuallySelected` para que o grafo acompanhe dinamicamente canais com processamento ativo, preservando a seleção manual explícita caso o operador clique em um canal.
- **Validação Local:**
  - 17/17 testes PASS em `test/services/test_api_v2_readonly.py` (incluindo validação de fallback de tarefas ativas, atribuição de provedor Google Flow e detecção de status de retry).
  - 3/3 testes direcionados PASS em `test/services/test_task.py`.
  - Build Vite frontend: `npm run build` PASS (406 kB bundle, 128 kB gzip, zero erros).

### V16.25 — R9.1 + R9.2: Consolidação do Live Pipeline e Operação Multicanal (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (16/10/2026)
- **Base:** `3040278b00c3087ebb9556d25c7cd8b3e2898156` (HEAD local em DEV)
- **Problemas Operacionais Identificados:**
  1. *Acoplamento Indevido de Gates:* O grafo marcava etapas de Gate (Safety, Quality, Copyright) como SUCCESS simplesmente porque a tarefa passou para a etapa seguinte, sem validação factual de veredito.
  2. *Estado IDLE Enganoso:* Canais sem tarefa em execução exibiam nós como concluídos (falsa impressão de progresso), quando deveriam estar em IDLE com apenas o Ready Stock exibindo o inventário real disponível.
  3. *Inconsistência de Foco Multicanal:* Durante o polling periódico (3s), a UI perdia a seleção manual do operador ou não permitia alternar entre foco dinâmico no canal ativo e fixação manual explícita.
  4. *Exibição de HTML Bruto:* Mensagens de erro ou logs com tags HTML/XML renderizavam código bruto na interface (`<br>`, `<div...`) em painéis de operações, drawers e títulos de cards.
  5. *Associação Factual do Provedor Google Flow:* Ausência de persistência explícita do `flow_account_id` da conta ativa utilizada durante o estágio `VISUALS` no `_run_pipeline`.
- **Implementação Realizada:**
  - `app/services/operator_console.py`:
    - Adicionado objeto factual `gates` no payload de `execution` (`safety_status`, `quality_score`, `copyright_status`, `gate_status`, `gate_reason`).
    - Enriquecida a resolução do provedor para `VISUALS` recuperando a conta Flow factual vinculada à tarefa ou pool ativo.
  - `app/services/task.py`:
    - No estágio `VISUALS` de `_run_pipeline`, registra explicitamente o `flow_account_id` e atribui o provedor `Google Flow (<account_id>)` quando habilitado.
  - `webui-v2/src/utils/stageVisuals.js`:
    - Criado helper universal `sanitizeDisplayText(str)` que remove tags HTML brutas via regex segura antes da renderização.
  - `webui-v2/src/components/FactoryLiveGraph.jsx`:
    - Desacoplada a progressão: etapas 1..5 (`TOPIC`..`RENDER`) avançam com `activeStep`, enquanto Gates 6, 7 e 8 (`SAFETY`, `QUALITY`, `COPYRIGHT`) exigem veredito factual em `execution.gates`.
    - No estado IDLE, todos os nós 1..8 e 10..12 permanecem em `IDLE`, e `completedCount` é rigidamente 0 (eliminando falsa percepção de progresso).
  - `webui-v2/src/components/ExecutionDrawer.jsx`:
    - Adicionada seção de "Verificação de Gates" com cards dedicados para Safety Gate, Quality Score (threshold >= 70.0) e Copyright Gate.
    - Sanitização aplicada em mensagens de erro, timeline e descrições.
  - `webui-v2/src/components/ChannelCard.jsx` e `LaneHeaderNode.jsx`:
    - Sanitização aplicada a títulos e tópicos de tarefas.
  - `webui-v2/src/components/AgentOps/AgentOpsView.jsx`:
    - Sanitização aplicada a mensagens e ações de ferramentas.
  - `webui-v2/src/App.jsx`:
    - Adicionado seletor/toggle no header do Factory Live permitindo alternar explicitamente entre "Foco Manual" e "Rastreamento Dinâmico Ativo".
- **Validação Local:**
  - 17/17 testes PASS em `test/services/test_api_v2_readonly.py`.
  - 3/3 testes direcionados PASS em `test/services/test_task.py`.
  - Build Vite frontend: `npm run build` PASS (409 kB bundle, 128 kB gzip, zero erros).

### V16.26 — R9.3: Homologação Integrada e Estabilidade da Web UI V2 (DEV)
- **Status:** `DEV_HOMOLOGATED / COMMITTED_DEV` (16/10/2026)
- **Base:** `48b48d9d3468075defdf59613ac99939e1898fd2` (HEAD local em DEV)
- **Objetivo da Homologação:**
  - Validação integrada dos 6 cenários críticos da missão (Cenários A..F) sem chamadas externas tarifadas, sem geração pesada e sem alteração em produção.
- **Defeitos Identificados e Corrigidos na R9.3:**
  1. *Precedência Incorreta de Profile na Descoberta de Tarefas Ativas:* Em `app/services/operator_console.py:get_live_execution_overview`, o loop de tarefas ativas chamava `profile_manager.get_task_profile_id(aid)` antes de checar `t_obj.get("profile_id")`. Como a função auxiliar recorre por padrão a `"default"` para tarefas ainda não persistidas em `task_profiles`, tarefas ativas de perfis secundários (ex: Canal B) eram mascaradas como pertencentes a `"default"`, fazendo o canal B aparecer incorretamente como `IDLE`. Corrigido priorizando `t_obj.get("profile_id")`.
  2. *Defaults Sintéticos de Aprovação em Gates:* Em `operator_console.py`, tarefas em `TASK_STATE_COMPLETE` aplicavam `"APPROVED"` e `"PASS"` sintéticos quando os campos de `safety_status` ou `copyright_status` estavam nulos. Corrigido para reportar estritamente o veredito real gravado (ou consulta ao `safety_gate`), preservando integridade factual.
  3. *Padronização do Código da Etapa 10:* Alinhado o código canônico de estágio para `SCHEDULER` em sincronia com `STAGE_DEFINITIONS` e contratos FastAPI.
  4. *Consolidação da Avaliação de Gates no Grafo:* Refatorado `webui-v2/src/components/FactoryLiveGraph.jsx` com o helper `evaluateCompletedStage(sDef, gates)`, garantindo que etapas 6..8 permaneçam `PENDING` durante a esteira de geração (1..5) e só avancem com scores/vereditos factuais.
- **Cenários Validados:**
  - **Cenário A (Geração Sequencial):** TOPIC (5%) -> SCRIPT (10%) -> NARRATION (30%) -> VISUALS (40%) -> RENDER (50%). Nós ativos RUNNING com provedor factual e gates PENDING.
  - **Cenário B (Dois Canais Simultâneos):** Canal A em VISUALS (Google Flow flow-b) e Canal B em RENDER (ffmpeg) simultâneos sem contaminação cruzada de dados, progresso ou tópicos.
  - **Cenário C (Gates Factuais):** Quality Gate rejeitado (67.8 < 70) reporta falha no nó exato com score e motivo factual sem promoção indevida.
  - **Cenário D (Google Flow Multi-Account):** Atribuição factual da conta `flow-b`; contas em `AUTH_FAILED` e com saldo insuficiente não são anunciadas indevidamente.
  - **Cenário E (Ciclo de Publicação):** Suporte estrito a READY_STOCK, SCHEDULED, RETRYING (attempts > 0) e SUCCESS terminal.
  - **Cenário F (Estados Especiais):** Canais IDLE exibem 0% de progresso concluído; erros com tags HTML/scripts são sanitizados universalmente via `sanitizeDisplayText`.
- **Validação Local:**
  - 6/6 testes de homologação integrados PASS em `test/services/test_webui_v2_r9_3_homologation.py`.
  - 17/17 testes de contrato read-only PASS em `test/services/test_api_v2_readonly.py`.
  - 4/4 testes de lógica e apresentação frontend PASS em `webui-v2/src/tests/r9_3_frontend_logic.test.js`.
  - Build Vite frontend: `npm run build` PASS (408.87 kB JS, 70.86 kB CSS, 0 erros, tempo: 7.22s).
- **Limitações Registradas:**
  - Binários do browser headless Playwright não instalados no host Windows (conforme instrução, ferramentas pesadas não foram instaladas e a validação foi realizada via testes de componentes e contratos de API com fidelidade integral).

### V16.27 — R10: Pacote Consolidado de Release da Web UI V2 (DEV)
- **Status:** `RELEASE_CANDIDATE_READY / READY_FOR_CONTROLLED_PRODUCTION_DEPLOY` (16/10/2026)
- **Base:** `96b9c112bcd912c95ac0ca05de19a6e057059585` (HEAD local em DEV)
- **Pacote Oficial Gerado:**
  - **Arquivo:** `releases/webui-v2-dist-96b9c11.zip`
  - **Tamanho:** 140.17 KB (143.535 bytes)
  - **SHA-256:** `3bebaf3b5307cf1becd07e4b97a61c42b38a924d2bf242b75fd54e5ff9213b4e`
  - **Checksum:** `releases/webui-v2-dist-96b9c11.zip.sha256`
  - **Validação de Integridade:** 100% VERIFICADO E APROVADO via `scripts/package_webui_v2.ps1`
- **Frentes Incorporadas no Pacote Único:**
  - **R9.1:** Live Pipeline real com 12 nós, checkpoints em `task.py`, resolução de provedores e gates factuais sem aprovação sintética.
  - **R9.2:** Operações multicanal, foco manual persistente contra polling de 3s, rastreamento dinâmico ativo, cards de verificação de gates no drawer e sanitização universal contra HTML bruto (`sanitizeDisplayText`).
  - **R9.3:** Homologação integrada dos 6 cenários (A..F), correção de precedência de profile em tarefas ativas e padronização da etapa `SCHEDULER`.
- **Garantias Operacionais para o PC Forte:**
  - **Zero Downtime / Zero Quebra:** O serviço principal `VideoFactory Production` (Streamlit na porta 8501) permanece em execução ininterrupta.
  - **FastAPI Same-Origin na Porta 8080:** Servindo os arquivos estáticos de `webui-v2/dist/` e rotas `/api/v2/*` em modo `SECONDARY_VIEW_ONLY` (sem disputar lock `PRIMARY`).
  - **Autostart Persistente:** Instalação idempotente via `.\scripts\register_webui_v2_task.ps1` criando a tarefa `VideoFactory WebUI V2` no Windows Task Scheduler.
  - **Zero Migração de Banco:** Nenhum schema SQLite ou tabela alterada.
  - **Rollback Seguro:** Reversão imediata parando a porta 8080 ou via `register_webui_v2_task.ps1 -Unregister` sem sobrescrever dados do banco.
- **Runbook Atualizado:** [docs/WEB_UI_V2_MIGRATION_RUNBOOK.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/WEB_UI_V2_MIGRATION_RUNBOOK.md) atualizado com instruções passo a passo seguras para execução no PowerShell do PC Forte.

### V16.28 — HOTFIX QG-V2: Qualidade Inteligente, Duração por Plataforma e Proteção de Créditos (DEV)
- **Status:** `DEV_VALIDATED / COMMITTED_DEV` (16/10/2026)
- **Base:** `96b9c112bcd912c95ac0ca05de19a6e057059585`
- **Contexto Operacional e Problema:**
  - Vídeos reais de alta qualidade visual gerados com consumo de créditos Google Flow foram retidos pelo Quality Gate (< 70.0) ou Safety Gate após o render completo (ex.: *"GTA 5 vs GTA 6"* 63.3 REVIEW; *"Elevador despencando"* 69.2 REVIEW retido por 0.8 ponto).
  - Investigação de causa raiz comprovou dois gargalos:
    1. *Descompasso de plataforma na duração:* Restrições de TikTok Creator Rewards (>60s) eram aplicadas globalmente, inclusive em presets cruzados ou destinos YouTube-only (`CFG-005`), penalizando vídeos de 40-58s com `SAFETY_STATUS_BLOCK` e `duration_fit = 30.0`.
    2. *Desperdício de créditos pré-render:* Roteiros editoriais fracos eram enviados ao Google Flow sem triagem preliminar de viabilidade, consumindo créditos reais antes de serem reprovados no final da esteira.
    3. *Vocabulário visual e distância léxica subcalibrados:* Roteiros altamente descritivos ("elevador", "queda", "prédio", "carro", "reflexo", "velocidade", "abelha", "game") sofriam penalizações severas por vocabulário concreto ausente e distância léxica artificialmente deprimida por palavras-chave do nicho.
- **Implementação Realizada:**
  - `app/services/quality_score.py`:
    - Adicionado filtro pré-render `evaluate_pre_generation_editorial_quality(topic, script_text, hook_text)` que avalia a viabilidade editorial antes de qualquer chamada ao Google Flow ou síntese pesada.
    - Desacoplamento da dimensão `calculate_duration_fit`: suporte à plataforma `youtube` (Shorts: 15s a 180s, faixa ideal 45s a 90s pontuando 100.0) vs `tiktok` (>60s para Rewards).
    - Expansão do vocabulário concreto (`CONCRETE_VISUAL_KEYWORDS`) com 40+ substantivos e entidades físicas reais (ações, objetos, ambientes, física, games).
    - Calibração de `calculate_originality` e `calculate_repetition_risk` prevenindo depressão artificial decorrente de termos-chave do nicho do canal.
    - Adicionado helper factual `is_borderline_review_candidate` identificando tarefas com score 65.0..69.9 e MP4 íntegro para inspeção humana, **sem nunca auto-aprovar REVIEW (< 70.0)**.
    - Limiar mínimo de aprovação autônoma mantido estritamente em **70.0** (`GOOD`/`STRONG`).
  - `app/services/safety_gate.py`:
    - Adicionado parâmetro `platform` em `evaluate_duration_safety` e `evaluate_script_safety`.
    - Quando o destino é YouTube (ou resolvido como YouTube com TikTok OFF), durações < 60s (15s a 180s) recebem status `PASS` com nota informativa, eliminando o falso bloqueio `SAFETY_STATUS_BLOCK`.
  - `app/services/task.py`:
    - Implementada checagem pré-materiais / pré-Flow no `_run_pipeline`:
      1. Se o roteiro sofrer `SAFETY_STATUS_BLOCK` antes do TTS/materiais, a tarefa falha de imediato sem gastar créditos.
      2. Se `evaluate_pre_generation_editorial_quality` retornar `viable == False` (`WEAK`), a geração é cancelada imediatamente com `_mark_task_failed(..., 'Roteiro reprovado no gate editorial pré-geração')`.
  - `app/services/autonomous_production.py`:
    - Atualizado `check_asset_eligibility_for_destination` com regras de duração por plataforma: YouTube Shorts 15s a 180s; TikTok normal vs TikTok Rewards (>60s).
    - Em `evaluate_completed_task_gates`: repasse correto de `hook_text`, `script_text`, `actual_duration` e `platform="youtube"` para `evaluate_quality`. Mantida a rejeição estrita (fail-closed) para scores < 70.0.
  - `scripts/inspect_held_quality_videos.py`:
    - Criado script CLI operacional e estritamente read-only para auditoria e recuperação de tarefas retidas por Quality Gate com MP4 íntegro no disco.
    - Exibe tabela formatada com Task ID, Tópico, Duração, Score, Status e caminho do arquivo de vídeo.
- **Validação Local:**
  - 9/9 testes unitários e de integração direcionados PASS em `test/services/test_quality_gate_v2.py`:
    - `test_youtube_shorts_accepts_under_60s` (PASS)
    - `test_tiktok_creator_rewards_requires_gt_60s` (PASS)
    - `test_quality_score_below_70_is_rejected_never_auto_pass` (PASS - fail-closed < 70)
    - `test_safety_and_copyright_remain_strictly_blocking` (PASS - fail-closed)
    - `test_pre_generation_editorial_gate_stops_weak_script` (PASS - zero desperdício)
    - `test_inspect_held_quality_videos_identifies_intact_mp4` (PASS)
    - `test_flow_idempotency_preserves_valid_scenes` (PASS - reuso sem regeneração)
    - `test_ready_stock_receives_only_eligible_content` (PASS)
    - `test_calibrated_audit_cases` (PASS - 4 casos reais da auditoria avaliados com sucesso)





