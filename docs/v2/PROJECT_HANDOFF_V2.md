# Video Factory V2 — Manual de Handoff do Projeto
**Documento de Entrega V2.8**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (Worktree: `D:\Projetos\MoneyPrinterTurbo-V2` / Branch: `feat/video-factory-v2`)

---

## 1. Como Iniciar a Video Factory V2 no Notebook DEV

Para testar ou inspecionar a interface e o backend em desenvolvimento:

### Opção A: Execução Integrada (FastAPI servindo a SPA estática na porta 8080)
```powershell
cd D:\Projetos\MoneyPrinterTurbo-V2
.\.venv\Scripts\python.exe main.py
```
*Acesse no navegador: `http://127.0.0.1:8080`*

### Opção B: Desenvolvimento Frontend (com Hot-Reload na porta 5173)
```powershell
# Terminal 1: Backend FastAPI
cd D:\Projetos\MoneyPrinterTurbo-V2
.\.venv\Scripts\python.exe main.py

# Terminal 2: Vite Dev Server
cd D:\Projetos\MoneyPrinterTurbo-V2\webui-v2
npm run dev
```
*Acesse no navegador: `http://127.0.0.1:5173` (as chamadas `/api` são roteadas automaticamente para o backend na 8080).*

---

## 2. Como Parar os Processos de DEV

Basta pressionar `Ctrl + C` no terminal onde o script estiver rodando ou executar no PowerShell:
```powershell
Get-Process python, node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*MoneyPrinterTurbo-V2*" } | Stop-Process -Force
```

---

## 3. Resumo das Funcionalidades Operacionais da V2

1. **Eliminação Completa do Streamlit:** O frontend monolítico de 10.000 linhas foi substituído por uma SPA React moderna, modular e de altíssimo desempenho.
2. **Canal como Centro da Experiência:**
   - Lista unificada de canais com métricas de estoque e badges de formato.
   - Painel individual com 7 abas (Visão Geral, Editorial, Vídeo & Áudio, Publicação, Automação, Estoque e Logs).
   - Modal de criação ágil e sem complexidade de FFmpeg para o operador.
3. **Formulários Inteligentes por Formato:**
   - Tradicional: controles de mídia Pexels e geração dinâmica.
   - Quiz Q0-R: parâmetros congelados (split 50/50, porcentagem de votos).
   - Quiz Papel P1.3: propriedades técnicas rígidas exibidas como somente leitura (60-65s, timer circular, fontes homologadas).
4. **Desempenho Validado por Benchmark:**
   - Listagem de canais: **26.52ms** (meta < 1000ms).
   - Consulta de status: **270.52ms** (meta < 1000ms).
   - Telemetria de tarefas: **32.96ms** (meta < 500ms).
   - Tempo de carregamento do frontend: **4.65s** no build estático com gzip totalizando menos de 150kB.
5. **Segurança de Isolamento Garantida:**
   - Zero modificações no ambiente de Produção (`C:\Projetos\MoneyPrinterTurbo`).
   - Zero modificações no DEV de referência (`D:\Projetos\MoneyPrinterTurbo`).
   - Publicação externa desativada por padrão em DEV.


---

## 4. Integracao do Hotfix Consolidado de Producao Autonoma (18/10/2026)

- **Commits de Origem (main):** `18d21cf`, `91e2e83`, `0479203`
- **Itens Integrados e Validados:**
  1. **Contrato Estruturado de Busy:** tanto a contencao de lock em memoria (`_cycle_lock`) quanto a deteccao de tarefas ativas (`has_active_generation_tasks()`) retornam `status="busy"` com `reason` explicito (`"cycle_in_progress"` ou `"active_tasks_generating"`), `message` descritiva e lista de `active_task_ids`.
  2. **Propagacao pela API V2 (`/api/v2/factory/run-cycle`):** o endpoint FastAPI propaga mensagens especificas de bloqueio acompanhadas de payload completo com `status`, `reason`, `message` e `active_task_ids` sob HTTP 409 Conflict.
  3. **Feedback Visual no Frontend V2:** `FactoryHeader` e `ExecutionDrawer` preservam os detalhes reais de bloqueio (exibindo tarefas ativas em andamento), sem supressao por textos genericos e sem recarregamentos desnecessarios de tela.
  4. **Eliminacao do UnboundLocalError (`rejected_struct`):** inicializacao preventiva `rejected_struct = None` antes da checagem de formato fixo, garantindo operacao continua em canais de Quiz.
  5. **Reconciliacao Nao-Destrutiva de Tarefas Orfas:** `operator_console.reconcile_orphaned_tasks()` na Etapa A2 reconcilia tarefas pos-restart preservando rigorosamente todos os Gates de Qualidade, Seguranca e Copyright.
- **Validacao de Testes na V2:**
  - `test_hotfix_autonomous_cycle_busy.py`: 4/4 PASS (3.75s).
  - `test_v2_isolation.py`: 3/3 PASS (bloqueio estrito de acesso ao PROD e DEV).
  - `test_v2_performance.py`: 3/3 PASS.
  - `test_web_ui_v2_api.py` (run-cycle active tasks & concurrency guards): PASS.

## Estado da Interface Web (Redesign SaaS V2.10)
- **Arquitetura Visual:** SaaS Minimalist Dark (`#0b0f17`, `#111827`, `#1f2937`), accent blue discreto (`#3b82f6`).
- **Navegação (7 Seções Canônicas):** Dashboard, Meus Canais, Produção, Estoque & Revisão, Agendamentos, Analytics, Configurações.
- **Telemetria Técnica e Diagnóstico:** Worker, Scheduler, Dry Run, Auto Publish e o Agent Ops Room estão consolidados em `Configurações > Diagnóstico & Telemetria` e no card compacto de Saúde do Sistema no Dashboard.
- **Homologação:** Validado em 1920x1080 (Desktop), 1366x768 (Notebook) e 390x844 (Mobile) com Playwright/Edge.
- **Performance:** Bundle JS comprimido de 143.39 kB (< 150 kB), tempo de carga ~2.1s, CLS zero.

## Identidade Visual V2.11 (Shadcn Admin Zinc + Microinterações)
- **Tema:** Zinc Dark Neutro (`#09090b` canvas, `#0c0c0e` cards, `#27272a` borders, `#fafafa` typography).
- **Referência:** `satnaing/shadcn-admin`.
- **Microinterações:** Elevações no hover (`translateY(-1.5px)`), scale nos botões (`:active { transform: scale(0.98) }`), modais com fade-in e backdrop blur, anel de foco acessível.
- **Preparação Multicanal:** Plano estruturado com 3 canais sintéticos (Curiosidades do Mundo, Quiz Bíblico Sagrado e Mistérios no Papel) registrado em `docs/v2/ROADMAP_V2.md`.

## 5. Homologação Multicanal Sintética V2.12 (18/10/2026)

- **Status:** CONCLUÍDO E APROVADO PELO OPERADOR
- **Branch:** `feat/video-factory-v2`
- **Ambiente:** DEV_V2 isolado (`D:\Projetos\MoneyPrinterTurbo-V2`)
- **Implementações Concluídas:**
  1. **Dataset Sintético:** 3 canais representativos configurados no SQLite sintético isolado:
     - `dev_test_curiosidades` (Tradicional, YouTube + TikTok, metas: 4 estoque / 4 max gen 24h, voz Antonio)
     - `dev_test_quiz_biblico` (Quiz Q0-R, YouTube, metas: 5 estoque / 5 max gen 24h, voz Francisca)
     - `dev_test_misterios_papel` (Quiz Papel P1.3, YouTube + TikTok, metas: 3 estoque / 3 max gen 24h, voz Antonio)
  2. **API de Atualização de Canais (`operations.py`):** Suporte completo para edição de `name`, `niche`, `voice_name`, `growth_mode`, `quotas` e `autonomous_enabled`.
  3. **Performance de Interface (`App.jsx`):** Polling desacoplado em tarefas paralelas assíncronas não-bloqueantes. Tempo de resposta da listagem de canais: ~50ms.
  4. **Workspace Detalhado (`ChannelDetailView.jsx`):** Edição de metas com persistência reativa, alternância de autonomia operacional, listagem de vídeos em estoque e logs de auditoria.
  5. **Filtro Resiliente (`ChannelListView.jsx`):** Busca e filtro por formato compatíveis com formatos aninhados em `editorial`.
  6. **Reconstituição Determinística do Banco:** Script `scripts/init_v2_synthetic_db.py` para restauração determinística com zero dados de produção.
- **Validação de Testes:**
  - `test_web_ui_v2_api.py`: 43/43 PASS (39.06s).
  - Build Vite de produção: Concluído em 8.98s, bundle gzip 144.98 kB.
- **Próximo Gate:** `NOTEBOOK_TRANSFER_READY` -> Migração para o Novo PC DEV -> Execução da Fase V2.13 (Ensaio de Migração e Compatibilidade de Dados).


---

## 6. Ensaio de Migração e Compatibilidade de Dados V2.13 (18/10/2026)

- **Status:** CONCLUÍDO COM SUCESSO (PASS)
- **Ambiente:** Novo PC DEV (DESKTOP-MU3HR6J) em C:\Projetos\MoneyPrinterTurbo-V2
- **Implementações e Resultados:**
  1. **Compatibilidade de Schemas:** Schema legado mapeado e adaptado aditivamente para inclusão de settings_json em content_profiles, e external_account_id/project_id em publishing_channels.
  2. **Ensaio em Cópia Isolada:** Executado via scripts/rehearse_v2_migration.py sobre storage/video_factory_migration_isolated.db.
  3. **Vínculos Multiprojeto e Canais:** 3 canais e 5 destinos de publicação validados sem inconsistências.
  4. **Idempotência e Integridade:** Integridade SQLite confirmada (ok) e reexecução da migração aprovada com zero duplicações.
  5. **Rollback Sintético:** Restauração a partir do backup pré-migração aprovada sem desvios de schema.
  6. **Testes:** 4/4 testes direcionados PASS em 	est_v2_13_migration_rehearsal.py.
- **Próximo Gate Seguro:** FINAL_CUTOVER_READY / V2.14.


---

## 7. Homologação Final e Readiness de Cutover V2.14 (18/10/2026)

- **Status:** CONCLUÍDO E HOMOLOGADO (CUTOVER_READY = YES)
- **Ambiente:** Novo PC DEV (DESKTOP-MU3HR6J) em C:\Projetos\MoneyPrinterTurbo-V2
- **Resultados e Homologações:**
  1. **Auditoria de Paridade Funcional:** 14/14 operações verificadas com endpoints, serviços Python, persistência e componentes React correspondentes (docs/v2/FUNCTIONAL_PARITY.md).
  2. **Compatibilidade de Dados Reais:** Migração de dados validada sem geração de IDs de projeto arbitrários e com bloqueio de destinos ambíguos.
  3. **Preparação de Produção:** isolation_guard.py adaptado para permitir execução legítima em C:\Projetos\MoneyPrinterTurbo quando MPT_ENVIRONMENT=PRODUCTION, mantendo bloqueio fail-closed em DEV.
  4. **Planejamento de Cutover e Rollback:** Planos de Cutover e Rollback refinados com estimativas de RTO medidas (10-15 min) e rotinas de detecção de divergência pré-restauração.
  5. **Próximo Gate:** PRODUCTION_CUTOVER_EXECUTED (Janela de Transição Programada no PC Forte por Operador Humano).

---

## 8. Preparação Final da Substituição V2.15A (18/10/2026)

- **Status:** CONCLUÍDO (PRE_CUTOVER_READY = PASS)
- **Ambiente:** Novo PC DEV em `C:\Projetos\MoneyPrinterTurbo-V2` (Branch `feat/video-factory-v2`)
- **Implementações e Entregas:**
  1. **Script de Auditoria Passiva Pré-Cutover:** Desenvolvido `scripts/v2_pre_cutover_audit.ps1` — 100% somente leitura, zero escritas, zero paradas de serviço, zero alteração de banco, zero vazamento de chaves ou credenciais. Emite verificação objetiva `STATUS AUDITORIA : PASS / BLOCKED`.
  2. **Documentação Operacional de Cutover:** Criados `docs/v2/V215A_PRE_CUTOVER_AUDIT.md` (manual de auditoria) e `docs/v2/V215_DEPLOY_EXECUTION.md` (passo a passo minucioso para o operador humano no PC Forte).
  3. **Reconciliação Segura do Hotfix Local:** Procedimento documentado para lidar com o hotfix de `app/services/autonomous_production.py` (`rejected_struct = None`) e arquivo `.bak` no PC Forte via backup isolado e `git restore`, proibindo estritamente `git reset --hard` e `git clean`.
  4. **Segurança de Produção & Não-Concorrência:** Garantido que `MPT_ENVIRONMENT=PRODUCTION` não permita acesso fora da raiz, exija PRIMARY e autorização explícita para publicação, e impeça a execução simultânea do Streamlit e da V2 disputando workers.
  5. **Próximo Gate:** Operador executar auditoria passiva no PC Forte (`powershell.exe -ExecutionPolicy Bypass -File scripts\v2_pre_cutover_audit.ps1`).

---

## 9. Preparação de Cutover com Diagnóstico Real do PC Forte V2.15B (18/10/2026)

- **Status:** CONCLUÍDO (CUTOVER_SCRIPT_READY = PASS)
- **Ambiente:** Novo PC DEV em `C:\Projetos\MoneyPrinterTurbo-V2` (Branch `feat/video-factory-v2`)
- **Descobertas e Implementações:**
  1. **Diagnóstico Factual do PC Forte:** Incorporados dados reais de produção: SHA `cf7d64767e13f94eb710809057dbcbc6efc19a27` na `main`, banco real `storage/video_factory.db` (8.65 MB), processos ativos 8080 (Uvicorn) e 8501 (Streamlit PRIMARY).
  2. **Auditoria Passiva Calibrada:** Atualizado `scripts/v2_pre_cutover_audit.ps1` para validar rigorosamente o diff do hotfix (`rejected_struct = None`), reconhecer o arquivo `.bak`, mapear o banco real `video_factory.db` e telemetria de credenciais sem vazamento.
  3. **Script Único de Cutover (`scripts/v2_cutover.ps1`):** Automação em 6 gates sequenciais com preflight estrito, snapshot transacional do SQLite com hash SHA256, parada graciosa das portas 8501 e 8080, desativação da Scheduled Task legada, atualização Git não-destrutiva, migração idempotente e validação de saúde na porta 8080.
  4. **Rollback Automatizado Integrado:** Parâmetro `-Rollback` em `v2_cutover.ps1` permitindo restauração completa em 10-12 minutos sem perda de dados.
  5. **Guia Operacional Detalhado:** Registrado em `docs/v2/V215B_CUTOVER_EXECUTION.md`.
  6. **Próximo Gate:** Revisão humana do plano e autorização prévia para o operador no PC Forte.

---

## 10. Checkpoint de Transferência Git (18/10/2026)
- **Status:** CHECKPOINT_SYNCHRONIZED (Aguardando Retomada no Novo Notebook)
- **Branch Remota:** `origin/feat/video-factory-v2`
- **Último Commit:** `2619d3d5e186e090d44fd8318dfed6fe07018777`
- **Instruções Detalhadas de Setup:** Ver `docs/v2/DEV_MIGRATION_HANDOFF.md` (Seção 5).
- **Produção Real (PC Forte):** Inalterada, segura e com Streamlit e Uvicorn operando normalmente.

---

## 11. Revisão Técnica Final de Segurança do Cutover V2.15C (18/10/2026)

- **Status:** CONCLUÍDO (CUTOVER_SAFETY_HARDENED = PASS / READY_FOR_AUTHORIZED_CUTOVER)
- **Ambiente:** Novo PC DEV em `C:\Projetos\MoneyPrinterTurbo-V2` (Branch `feat/video-factory-v2`)
- **Bloqueadores Identificados e Resolvidos:**
  1. **Rollback Não-Destrutivo:** Implementada avaliação automatizada de divergências antes de qualquer restauração de banco SQLite em `scripts/v2_cutover.ps1` (`divergence_detected`). Se novas publicações ou tarefas existirem no banco atual, a sobrescrita é abortada a menos que `-ForceOverwriteDb` seja explicitamente passado. Criado snapshot de contingência pré-rollback e limpeza preventiva de arquivos transitórios `.db-wal` e `.db-shm`.
  2. **Eliminação de `git reset --hard`:** Removida menção de `git reset --hard` no `docs/v2/ROLLBACK_PLAN.md`, substituída por checkout limpo de branch e restauração não-destrutiva de hotfix.
  3. **Migração Canônica no Banco Real:** Eliminada dependência e erro de importação de funções inexistentes de `scripts/rehearse_v2_migration.py`. A migração de produção agora executa exclusivamente as rotinas canônicas e idempotentes dos serviços oficiais (`profile_manager.init_profile_db`, `scheduler.init_db`, `quality_recovery.init_review_db`, `operator_console.init_operator_db`, `safety_gate.init_safety_db`, `quality_score.init_quality_db`) e inicialização segura de `settings_json` sem inventar IDs ou modificar dados de canais reais.
  4. **Proteção Contra Publicação Automática Inesperada:** `scripts/v2_cutover.ps1` agora persiste compulsoriamente `auto_publish_enabled = false` e `scheduler_enabled = false` no SQLite durante a quiescência e valida no Gate 6 que o auto-publish permanece rigorosamente desativado.
  5. **Quiescência e Liberação de PRIMARY:** Validação de ausência de renderizações FFmpeg ativas e de postagens em processamento (`status = 'processing'`). Encerramento limpo do lock stale de PRIMARY via `operator_console.release_stale_instance_lock` durante o Gate 3, permitindo assunção imediata e inequívoca do novo nó V2 como PRIMARY.
  6. **Correção de Endpoints de Health e Canais:** Corrigido endpoint de canais para `/api/v2/channels` e adicionada validação de autoridade no `/api/v2/health` (`role == 'PRIMARY'` e `is_primary == true`).
  7. **Guarda de Isolamento:** Corrigido caractere de escape vertical tab em `app/services/isolation_guard.py` e validada suíte direcionada (7/7 PASS).
- **Próximo Gate:** Janela de Cutover Programada no PC Forte sob autorização do operador (CUTOVER_READY = YES).
