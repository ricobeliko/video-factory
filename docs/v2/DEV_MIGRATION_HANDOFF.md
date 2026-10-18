# Video Factory — Handoff de Migração de Ambiente DEV (Notebook -> Novo PC)

> [!NOTE]
> Este documento registra o estado exato do desenvolvimento da Video Factory V2 no momento da migração definitiva do notebook para o novo PC DEV.

---

## 1. Identificação dos Ambientes e Commits Canônicos

- **Data da Migração:** 18/10/2026
- **Repositório Remoto (Origin):** `https://github.com/ricobeliko/video-factory.git`
- **Branch Original:** `main`
- **Branch V2:** `feat/video-factory-v2`
- **Ambiente DEV Original (Notebook):** `D:\Projetos\MoneyPrinterTurbo`
- **Ambiente V2 Isolado (Notebook):** `D:\Projetos\MoneyPrinterTurbo-V2`
- **PC Forte (Produção Real):** `C:\Projetos\MoneyPrinterTurbo` (INTACTO / NÃO MODIFICADO)

### SHAs Canônicos de Checkpoint:
- **MAIN_HEAD_SHA:** `047920307b3004cb3797fb90867c4405f8a9a4a6` (fix(webui-v2): hotfix consolidado de busy/orfas/rejected_struct)
- **V2_CHECKPOINT_SHA:** 45519ce1c1ceaa0d6ab6475b3e44c3174b185764
- **CHECKPOINT_TAG:** `checkpoint-v2.12`

---

## 2. Inventário de Dados Não-Versionados e Classificação

| Item / Caminho | Descrição | Classificação | Procedimento no Novo PC |
| :--- | :--- | :--- | :--- |
| `storage/video_factory.db` (DEV_V2) | Banco SQLite sintético com 3 canais homologados | **B** | Recriar via `python scripts/init_v2_synthetic_db.py` |
| `storage/video_factory.db` (DEV Original) | Banco SQLite de testes históricos do notebook | **D** | Descartável (não necessário para a V2) |
| `storage/flow_browser_profile/` | Sessão e cookies de autenticação Google/Edge | **C** | Não transferir via Git. Login humano isolado quando necessário |
| `storage/flow_browser_profiles/` | Perfis adicionais multi-conta Flow | **C** | Cópia privada manual ou recriação humana se for operar Flow em DEV |
| `storage/credentials/` | Chaves/tokens OAuth locais | **C** | Cópia privada segura fora do Git |
| `.venv/` | Ambiente virtual Python | **B** | Recriar com `python -m venv .venv` e `pip install -r requirements.txt` |
| `webui-v2/node_modules/` | Dependências Node do frontend | **B** | Recriar com `npm install` no diretório `webui-v2` |
| `webui-v2/dist/` | Build estático compilado pelo Vite | **B** | Recriar com `npm run build` |
| `temp/`, `_import/`, `runs/` | Áudios de teste, capturas e logs temporários | **D** | Descartável |
| Configurações locais MCP | Configurações locais de ferramentas | **B / D** | Reconfigurar no IDE do novo computador |

---

## 3. Estado de Homologação das Fases

- **V2.0 a V2.9:** Concluídas e integradas com testes de isolamento e hotfix de produção autônoma.
- **V2.10:** Redesign SaaS Minimalista Dark concluído e validado em 3 resoluções.
- **V2.11:** Paleta Shadcn Admin Zinc e microinterações CSS nativas homologadas.
- **V2.12:** Homologação multicanal sintética aprovada pelo operador:
  - 3 canais sintéticos nos formatos Tradicional, Quiz Q0-R e Quiz Papel P1.3.
  - Edição de cotas (Estoque Alvo e Teto 24h) com persistência via FastAPI.
  - Alternância de autonomia operacional no Channel Workspace.
  - Polling reativo e não-bloqueante no frontend React.
  - Script determinístico de reconstrução do banco: `scripts/init_v2_synthetic_db.py`.
  - 43/43 testes direcionados PASS em `test_web_ui_v2_api.py`.
  - Vite build concluído em 8.98s (< 150 kB gzip).

---

## 4. Procedimento de Retomada no Novo PC DEV

Ao iniciar o Antigravity no novo PC DEV:
1. Seguir as instruções detalhadas em `docs/v2/NEW_DEV_SETUP.md`.
2. Executar o Smoke Test:
   ```powershell
   .\.venv\Scripts\python.exe -m pytest test/services/test_web_ui_v2_api.py -q
   ```
3. Confirmar o gate de recuperação: `NEW_DEV_READY = PASS`.
4. Iniciar imediatamente a **Etapa C — Fase V2.13 (Ensaio de Migração e Compatibilidade de Dados)**.

---

## 5. Próxima Fase do Roadmap: V2.13

A Fase V2.13 tem como objetivo provar que a V2 recebe e opera dados compatíveis com a fábrica atual, utilizando uma cópia do schema legado alimentada com dados sintéticos sanitizados (cenários A..F, Quiz, múltiplos destinos Post for Me e estados de estoque/publicação), com validação na interface e ensaio de rollback.

---

## 5. Checkpoint de Transferência para Novo Notebook (Noite de 18/10/2026)

### 5.1 Estado do Checkpoint
- **Branch Canônica V2:** `feat/video-factory-v2`
- **Último Commit:** `2619d3d5e186e090d44fd8318dfed6fe07018777`
- **Mensagem:** `feat(v2): V2.15B preparacao de cutover com diagnostico real do PC Forte e script sequencial`
- **Repositório Remoto:** `https://github.com/ricobeliko/video-factory.git`

### 5.2 Diagnóstico Factual do PC Forte (Produção Real)
- **Branch:** `main` | **SHA:** `cf7d64767e13f94eb710809057dbcbc6efc19a27`
- **Hotfix Local:** `app/services/autonomous_production.py` (linha `rejected_struct = None`) e `.bak_20261018_110834`.
- **Banco de Dados Real:** `C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db` (~8.65 MB).
- **Processos Ativos:**
  - Porta 8080 (PID 9280): `python.exe -m uvicorn app.asgi:app` (via Scheduled Task `VideoFactory WebUI V2`).
  - Porta 8501 (PID 13056): `python.exe scripts/production_entrypoint.py` (via Scheduled Task `VideoFactory Production` - detém `PRIMARY`).
- **Espaço Livre em C:** ~335 GB.
- **Produção:** Rigorosamente intacta e sem alterações nesta fase.

### 5.3 Arquivos Relevantes da V2.15B Versionados no GitHub
- `scripts/v2_cutover.ps1` (Script sequencial de 6 gates com rollback integrado).
- `scripts/v2_pre_cutover_audit.ps1` (Auditoria passiva 100% somente-leitura adaptada ao banco real e diff do hotfix).
- `docs/v2/V215B_CUTOVER_EXECUTION.md` (Manual detalhado de cutover e rollback).
- `docs/v2/PRODUCTION_CUTOVER_PLAN.md` e `docs/v2/ROLLBACK_PLAN.md` (Planos canônicos atualizados).
- `test/services/test_v2_cutover_mock.py` (Suíte direcionada de testes unitários dos gates de cutover - 4/4 PASS).

### 5.4 Roteiro Rápido de Retomada no Novo Notebook
1. **Inspecionar ambiente:** Escolha um diretório de trabalho adequado (ex: `C:\Projetos` ou `D:\Projetos` ou seu workspace de preferência).
2. **Validar ferramentas:**
   ```powershell
   git --version; python --version; node --version; ffmpeg -version
   ```
3. **Clonar e checkout da branch V2:**
   ```powershell
   git clone https://github.com/ricobeliko/video-factory.git
   cd video-factory
   git checkout feat/video-factory-v2
   git log -1 --oneline
   # Confirmar SHA: 2619d3d ou superior
   ```
4. **Criar venv e instalar dependências Python:**
   ```powershell
   python -m venv .venv
   .\.venv\Scripts\Activate.ps1
   pip install -r requirements.txt
   ```
5. **Frontend (opcional se dist já estiver versionado):**
   ```powershell
   cd webui-v2
   npm ci
   cd ..
   ```
6. **Reconstruir SQLite sintético de desenvolvimento:**
   ```powershell
   python scripts/init_v2_synthetic_db.py
   ```
7. **Executar smoke tests direcionados:**
   ```powershell
   .\.venv\Scripts\pytest.exe test/services/test_v2_cutover_mock.py
   .\.venv\Scripts\pytest.exe test/services/test_v2_13_migration_rehearsal.py
   ```
8. **Iniciar a V2 em localhost:**
   ```powershell
   python main.py
   # Acessar: http://localhost:8080
   ```
9. **Próxima Ação:** Revisão humana do plano de cutover e posterior execução assistida no PC Forte.
