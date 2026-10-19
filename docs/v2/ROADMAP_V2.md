# ROADMAP — VIDEO FACTORY V2
## Reconstrução Organizada da Interface & Desacoplamento do Streamlit

**Versão da Arquitetura:** Video Factory V2  
**Ambiente:** `D:\Projetos\MoneyPrinterTurbo-V2`  
**Branch:** `feat/video-factory-v2`  
**Origem:** `cf7d647`  

---

## 1. Fases e Status dos Gates

| Fase | Descrição | Gate de Saída | Status |
| :--- | :--- | :--- | :--- |
| **V2.0** | Isolamento e Baseline do Ambiente | `ISOLATION_PASS` | **CONCLUÍDO (6/6 PASS)** |
| **V2.1** | Auditoria Funcional Completa & Mapeamento de Duplicações | `AUDIT_COMPLETE` | **CONCLUÍDO** |
| **V2.2** | Arquitetura Mínima, Fonte de Verdade e Contratos de API | `ARCHITECTURE_READY` | **CONCLUÍDO** |
| **V2.3** | Design System Moderno, Navegação e Layout Base | `UI_FOUNDATION_READY` | **CONCLUÍDO** |
| **V2.4** | Canal como Centro da Aplicação (Channel Workspace) | `CHANNEL_WORKSPACE_READY` | **CONCLUÍDO** |
| **V2.5** | Formulários Inteligentes por Formato (Tradicional/Quiz) | `FORMAT_AWARE_UI_READY` | **CONCLUÍDO** |
| **V2.6** | Migração das Demais Funcionalidades & Matriz de Paridade | `FUNCTIONAL_PARITY_PASS` | **CONCLUÍDO (13/13 100%)** |
| **V2.7** | Otimização de Desempenho e Tempos de Resposta | `PERFORMANCE_PASS` | **CONCLUÍDO (3/3 PASS)** |
| **V2.8** | Homologação Integrada, Testes de Migração e Cutover Plan | `V2_DEV_HOMOLOGATED` | **CONCLUÍDO** |
| **V2.9** | Integração do Hotfix Autônomo (`busy` contract, órfãs, `rejected_struct`) | `HOTFIX_INTEGRATED` | **CONCLUÍDO (4/4 PASS)** |
| **V2.10** | Redesign Visual e Arquitetura de Interface SaaS Minimalista Dark | `SAAS_REDESIGN_READY` | **CONCLUÍDO** |
| **V2.11** | Paleta Shadcn Admin Zinc & Microinterações CSS Nativas | `SHADCN_ZINC_READY` | **CONCLUÍDO** |
| **V2.12** | Homologação Multicanal Sintética & Ajustes Operacionais do Workspace | `MULTICHANNEL_SYNTHETIC_HOMOLOGATED` | **CONCLUÍDO (43/43 PASS)** |
| **V2.13** | Ensaio de Migração e Compatibilidade de Dados | MIGRATION_REHEARSAL_PASS | **CONCLUÍDO (4/4 PASS)** |
| **V2.14** | Homologação Final e Readiness de Cutover | FINAL_CUTOVER_READY | **CONCLUÍDO (PASS)** |
| **V2.15** | Preparação e Auditoria do Cutover no PC Forte | CUTOVER_READY = YES | **CONCLUÍDO (PASS)** |
| **V2.16** | Janela de Cutover Autorizada no PC Forte | PRODUCTION_CUTOVER_EXECUTED | **PRÓXIMO GATE (OPERAÇÃO HUMANA)** |


---

## 2. Princípios de Execução Autônoma

1. **Reaproveitamento Máximo:** Preservar intactos os motores Python homologados (FFmpeg, Quiz Engine, Telemetria, TTS, Idempotência).
2. **Fonte Única de Verdade:** Nenhuma configuração duplicada entre telas ou persistências conflitantes.
3. **Canal Centralizado:** Toda informação, destino, voz, formato, estoque e automação gerenciada a partir do canal.
4. **Proteção Absoluta da Produção:** Zero impacto em `C:\Projetos\MoneyPrinterTurbo` e no DEV original `D:\Projetos\MoneyPrinterTurbo`.
5. **Zero Publicações Reais em DEV:** Publicação externa sempre simulada ou protegida por guarda de isolamento.

## Fase 10 — Redesign Visual e Arquitetura de Interface SaaS (Concluída)
- **Status:** CONCLUÍDO (Homologado em DEV_V2)
- **Objetivo:** Substituir a estética crua/desenvolvedor por uma interface SaaS Minimalista Dark, organizada em 7 seções canônicas.
- **Entregas:**
  - Redesign do Dashboard executivo com 4 KPIs Tremor, lista compacta de canais, produção em tempo real e saúde do sistema.
  - Eliminação de cabeçalhos poluídos, remoção do Agent Ops da navegação principal do operador (realocado para Configurações > Diagnóstico).
  - Meus Canais com busca, filtros de formatos congelados e abertura de workspace com 7 abas canônicas.
  - Esteira de Produção com foco em canal, grafo de renderização interativo e pool Flow contextual.
  - Estoque & Revisão (Central de Curadoria Humana / Quality Gate) e Agendamentos integrados.
  - Design System padronizado (`--v2-` CSS variables), alta legibilidade e compatibilidade total em 1920x1080, 1366x768 e 390x844.
  - Documentação canônica em `UI_REDESIGN_REFERENCES.md`, `UI_DESIGN_SYSTEM.md` e `UI_REDESIGN_VALIDATION.md`.

## Fase 11 — Paleta Shadcn Admin Zinc & Microinterações (Concluída)
- **Status:** CONCLUÍDO (Homologado em DEV_V2)
- **Objetivo:** Adequar a identidade visual da Video Factory V2 à estética autêntica do `satnaing/shadcn-admin`, eliminando o tom azul-escuro prévio em favor do Zinc Dark neutro e refinando microinterações CSS.
- **Entregas:**
  - Tokens de superfície Zinc-950 (`#09090b`), Zinc-900 (`#0c0c0e`), Zinc-800 (`#27272a`) e Zinc-50 (`#fafafa`).
  - Botões com padrão Shadcn (primário branco de alto contraste, secundário outline e ações contextuais táteis).
  - Elevação dinâmica em cards interativos com transição suave e sem layout shifts.
  - Modais com animação de escala e fade, além de backdrop blur.
  - Sidebar canônica com item ativo Zinc-800 e hover discreto.
  - Suporte completo a `@media (prefers-reduced-motion: reduce)` e anel de foco acessível.

## Plano de Homologação Multicanal Sintética (Fase Seguinte)
Para viabilizar a avaliação completa das 7 abas do Workspace de Canais sem expor dados reais de produção:
1. **Canal Sintético 1 — Curiosidades do Mundo:**
   - Nicho: Ciência e Fatos Curiosos
   - Formato: Tradicional (Montagem com clipes e narração)
   - Plataformas Vinculadas: YouTube Shorts + TikTok
   - Estoque Alvo: 4 vídeos | Estoque Inicial Simulado: 2 vídeos prontos
   - Voz Padrão: pt-BR-AntonioNeural
   - Autonomia: Ativa
2. **Canal Sintético 2 — Quiz Bíblico Sagrado:**
   - Nicho: Perguntas e Respostas Bíblicas
   - Formato: Quiz Q0-R (Escolhas Impossíveis 50/50)
   - Plataformas Vinculadas: YouTube Shorts
   - Estoque Alvo: 5 vídeos | Estoque Inicial Simulado: 0 vídeos
   - Voz Padrão: pt-BR-FranciscaNeural
   - Autonomia: Ativa
3. **Canal Sintético 3 — Mistérios no Papel:**
   - Nicho: Enigmas & Investigação
   - Formato: Quiz de Papel P1.3 (Estilo rústico, 4 alternativas em bloco)
   - Plataformas Vinculadas: YouTube Shorts + Instagram Reels
   - Estoque Alvo: 3 vídeos | Estoque Inicial Simulado: 1 vídeo em revisão
   - Voz Padrão: pt-BR-AntonioNeural
   - Autonomia: Manual (Operador aciona renderizações pontuais)

## Fase 12 — Homologação Multicanal Sintética & Ajustes Operacionais do Workspace (Concluída)
- **Status:** CONCLUÍDO (Homologado em DEV_V2 pelo Operador)
- **Objetivo:** Validação integral das 7 abas do Workspace de Canais com dataset sintético multicanal, sem expor dados reais de produção.
- **Entregas e Implementações:**
  - **Dataset Sintético Homologado:** 3 perfis/canais sintéticos criados e validados (`Curiosidades do Mundo`, `Quiz Bíblico Sagrado`, `Mistérios no Papel`) cobrindo integralmente os formatos Tradicional, Quiz Q0-R e Quiz Papel P1.3, com 5 canais de publicação vinculados (YouTube e TikTok simulados).
  - **Extensão da API de Canais (`/api/v2/channels/{id}/settings`):** suporte bidirecional para atualização de `name`, `niche`, `voice_name`, `growth_mode`, `quotas` e `autonomous_enabled`.
  - **Decoupling de Polling no Frontend:** chamadas paralelas assíncronas não-bloqueantes no `App.jsx`, reduzindo o tempo de renderização inicial da lista de canais para ~50ms sem aguardar telemetrias mais lentas.
  - **Workspace Detalhado do Canal:** `ChannelDetailView` refinado com edição reativa de Estoque Alvo e Teto 24h, alternância de autonomia operacional, listagem factual de itens prontos no buffer de estoque e console de auditoria de logs.
  - **Filtro e Busca Inteligente:** `ChannelListView` com busca insensível a maiúsculas/minúsculas e filtro por formato resiliente a metadados legados ou aninhados em `editorial`.
  - **Procedimento Determinístico de Banco Sintético:** criação de `scripts/init_v2_synthetic_db.py`, permitindo a inicialização instantânea do banco `storage/video_factory.db` em novos ambientes DEV sem dependência de produção.
  - **Testes e Build:** 43/43 testes direcionados PASS em `test_web_ui_v2_api.py` e build de produção Vite concluído em 8.98s (< 150 kB gzip).

## Fase 13 — Ensaio de Migração e Compatibilidade de Dados (Concluída)
- **Status:** CONCLUÍDO (4/4 PASS em 	est_v2_13_migration_rehearsal.py)
- **Objetivo:** Comprovar no novo computador de desenvolvimento que a V2 recebe e opera dados compatíveis com a fábrica atual sem qualquer risco para a produção.
- **Entregas:**
  - Script determinístico de ensaio: scripts/rehearse_v2_migration.py.
  - Mapeamento completo entre schemas legados e contratos tipados V2 (ChannelWorkspaceSettings).
  - Suíte de validação: 	est/services/test_v2_13_migration_rehearsal.py cobrindo schema legado, migração aditiva, integridade SQLite, idempotência e rollback sintético.
  - Relatório canônico detalhado em docs/v2/MIGRATION_REHEARSAL_REPORT.md.


## Fase 14 — Homologação Final e Readiness de Cutover (Concluída)
- **Status:** CONCLUÍDO (Auditoria e Readiness Aprovados: CUTOVER_READY = YES)
- **Objetivo:** Preparar a Video Factory V2 para a substituição futura do Streamlit, realizando auditoria final de paridade, segurança, dados e operação.
- **Entregas:**
  - Matriz de Paridade Real com 14/14 operações homologadas em docs/v2/FUNCTIONAL_PARITY.md.
  - Atualização do Guarda de Isolamento (isolation_guard.py) com suporte seguro a MPT_ENVIRONMENT=PRODUCTION no PC Forte.
  - Ensaio de migração de dados estrito sem IDs de projeto inventados e com proteção contra destinos ambíguos em 
ehearse_v2_migration.py.
  - Refinamento do RTO medido e procedimento de avaliação de divergências em PRODUCTION_CUTOVER_PLAN.md e ROLLBACK_PLAN.md.
  - Relatório Canônico Mestre de Readiness registrado em docs/v2/V214_CUTOVER_READINESS.md.

## Fase 15A — Preparação Final da Substituição (Concluída)
- **Status:** CONCLUÍDO (Auditoria Passiva e Roteiro de Execução Homologados)
- **Objetivo:** Preparar uma substituição única, segura e reversível da interface Streamlit pela Video Factory V2 React/FastAPI sem qualquer intervenção no PC Forte durante a fase de dev.
- **Entregas:**
  - Script oficial de auditoria passiva no PC Forte: `scripts/v2_pre_cutover_audit.ps1`.
  - Manual de auditoria passiva: `docs/v2/V215A_PRE_CUTOVER_AUDIT.md`.
  - Roteiro operacional de execução do deploy: `docs/v2/V215_DEPLOY_EXECUTION.md`.
  - Atualização dos planos de cutover e rollback (`PRODUCTION_CUTOVER_PLAN.md` e `ROLLBACK_PLAN.md`).
  - Estratégia de reconciliação do hotfix pontual de `autonomous_production.py` com preservação em backup isolado e sem comandos destrutivos.
  - Validação estrita de isolamento e bloqueio de publicação externa não autorizada.

## Fase 15B — Preparação de Cutover com Diagnóstico Real do PC Forte (Concluída)
- **Status:** CONCLUÍDO (Scripts de Cutover e Auditoria Homologados)
- **Objetivo:** Preparar a substituição definitiva, segura e reversível do Streamlit pelo React/FastAPI baseando-se nos dados reais levantados no PC Forte.
- **Entregas:**
  - Script único de cutover sequencial com gates: `scripts/v2_cutover.ps1`.
  - Auditoria passiva calibrada para o banco real `storage/video_factory.db`: `scripts/v2_pre_cutover_audit.ps1`.
  - Manual de execução detalhado: `docs/v2/V215B_CUTOVER_EXECUTION.md`.
  - Atualização dos planos de cutover e rollback para refletir processos 8080/8501, tarefas Windows e reconciliação do hotfix.
  - Testes e validações de preflight, backup e idempotência aprovados.

## Fase 15C — Homologação de Segurança e Preparação para Operação Paralela (Concluída)
- **Status:** CONCLUÍDO (PARALLEL_TEST_READY = YES / PRODUCTION_TAKEOVER_READY = NO)
- **Objetivo:** Auditar a segurança operacional da Video Factory V2 e estruturar a nova estratégia arquitetural de Operação Paralela Isolada (Estágio A / Estágio B), preservando a fábrica antiga (Streamlit na porta 8501) em execução ininterrupta.
- **Entregas:**
  - `scripts/v2_cutover.ps1` protegido contra execução acidental: inclusão do switch mandatório `-AuthorizeDirectCutover`, abortando por padrão qualquer tentativa de corte direto não autorizado (`[V2.15C_ABORT]`).
  - Suíte de Homologação Técnica: `test/services/test_v2_15c_parallel_homologation.py` com 8/8 garantias aprovadas cobrindo isolamento de caminhos, bloqueio contra usurpação de PRIMARY, imunidade da fila real, bloqueio de publicações externas, atomicidade em falhas, proteção de divergência no rollback, concorrência atômica de locks e proteção de execução do script legado.
  - Atualização dos planos operacionais em `PROJECT_HANDOFF_V2.md`, `ROADMAP_V2.md`, `PRODUCTION_CUTOVER_PLAN.md` e `ROLLBACK_PLAN.md`.
  - Total de 31 testes direcionados aprovados sem tocar em produção.

## Fase 16 — Resgate Funcional + Nova Identidade Visual (Concluída)
- **Status:** CONCLUÍDO (Paridade Funcional e Nova Identidade Visual Homologadas)
- **Objetivo:** Superar as limitações da interface inicial da V2, resgatando a densidade, elegância e paridade funcional com a fábrica real, estabelecendo um design system *Modern Command Deck* e eliminando lacunas de layout e formulários.
- **Entregas:**
  - Documentos canônicos de arquitetura visual e paridade: `docs/v2/AUDIT_UI_PARITY.md` e `docs/v2/UI_IDENTITY_SYSTEM_V2.md`.
  - Fatia A — Design System e App Shell: Paleta semântica dark de central de comando (`#090d16`, `#0f172a`, `#1e293b`), tokens de acento e estado, Sidebar refinada e FactoryHeader contextual.
  - Fatia B — Meus Canais e Gerenciamento: Cards ricos com chips de destinos conectados (YouTube/TikTok), badges de formato, tag Google Flow, barra de estoque e autonomia. Painel detalhado com abas para edição e persistência bidirecional no SQLite.
  - Fatia C — Novo Canal (Wizard 5 Etapas): Formulário transformado em Wizard modular e guiado (Identidade, Formato Homologado com Quiz Dilema Q0-R, Destinos Sociais Post for Me, Vozes Azure pt-BR e Google Flow, Quotas e Lançamento Seguro).
  - Fatia D — Esteira de Produção (Master-Detail Command Center): Fim do empilhamento vertical e do vazio lateral. Painel Master lateral com lista e indicadores de atividade em tempo real; Command Deck com pipeline stepper horizontal de 5 estágios, telemetria de tarefa ativa e grafo causal interativo de 12 estágios.
  - Fatia E — Unificação das Demais Telas: Dashboard, Estoque, Agendamentos e Configurações integrados à nova identidade.
  - Backend FastAPI V2: Endpoints `GET /api/v2/publishing-accounts` e `GET /api/v2/voices` implementados; expansão de `CreateChannelRequest` e `UpdateProfileSettingsRequest` com validação e persistência total.
  - Testes e Build: 100% de sucesso na compilação do frontend Vite e nos testes unitários direcionados.

