# Video Factory V2 — Plano de Migração e Cutover para Produção (PC Forte)
**Documento Operacional V2.14**
**Data de Atualização:** 18/10/2026
**Ambiente Alvo Futuro:** C:\Projetos\MoneyPrinterTurbo (PC Forte)
**Ambiente Homologado:** C:\Projetos\MoneyPrinterTurbo-V2 (eat/video-factory-v2)

---

> [!CRITICAL]
> **ESTA MISSÃO NÃO EXECUTA DEPLOY EM PRODUÇÃO.**
> Este documento é o plano rigoroso e homologado a ser executado exclusivamente em janela de manutenção programada pelo operador humano no PC Forte.

---

## 1. Princípios de Segurança e Não-Concorrência

1. **Substituição Definitiva do Streamlit:** A nova interface V2 (FastAPI na porta 8080 servindo a SPA React) **substitui** o Streamlit. Ela NÃO deve rodar concorrentemente como segunda instância operacional disputando tarefas.
2. **Autoridade PRIMARY Única:** Apenas um processo deterá o instance_lock e executará o SchedulerExecutionWorker.
3. **Guarda de Isolamento para Produção:** No PC Forte, definir a variável de ambiente MPT_ENVIRONMENT=PRODUCTION para desativar as travas exclusivas de DEV_V2 e habilitar o caminho canônico C:\Projetos\MoneyPrinterTurbo.
4. **Preservação Absoluta de Dados:** Credenciais OAuth em storage/credentials/, perfis de navegador em storage/flow_browser_profiles/, vídeos em storage/tasks/ e config.toml jamais serão sobrescritos ou excluídos.
5. **Estimativa Realista de Janela:** O tempo total estimado de cutover (RTO) medido em ensaio é de **10 a 15 minutos**, incluindo checagens de integridade e divergência.

---

## 2. Passo a Passo do Procedimento de Instalação no PC Forte

### Fase 1: Quiescência e Backup
1. **Verificar Tarefas Ativas:** Confirmar que nenhuma renderização FFmpeg ou upload está em andamento.
2. **Pausar Despachos:**
   `powershell
   python -c "from app.services import operator_console; operator_console.pause_factory()"
   `
3. **Parar a Tarefa / Serviço Streamlit Legado:**
   `powershell
   Stop-ScheduledTask -TaskName "VideoFactory Production" -ErrorAction SilentlyContinue
   # Confirmar que a porta 8501 foi liberada e o processo python foi finalizado
   Get-NetTCPConnection -LocalPort 8501 -ErrorAction SilentlyContinue
   `
4. **Backup Consistente Físico (Banco e Configurações):**
   `powershell
    = Get-Date -Format 'yyyyMMdd_HHmmss'
   Copy-Item "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" 
             "C:\Projetos\MoneyPrinterTurbo\storage\video_factory_backup_pre_v2_.db"
   Copy-Item "C:\Projetos\MoneyPrinterTurbo\config.toml" 
             "C:\Projetos\MoneyPrinterTurbo\config_backup_pre_v2_.toml"
   `

### Fase 2: Atualização do Código e Dependências
1. **Atualização do Git (Fast-Forward):**
   `powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git checkout main
   git merge feat/video-factory-v2 --ff-only
   `
2. **Atualização das Dependências Python:**
   `powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   `
3. **Compilação do Frontend Estático (Vite):**
   `powershell
   cd C:\Projetos\MoneyPrinterTurbo\webui-v2
   npm ci
   npm run build
   cd ..
   `

### Fase 3: Migração Aditiva do Banco de Dados
1. **Executar Migrações com Preservação de Dados:**
   `powershell
   .\.venv\Scripts\python.exe -c "from app.services import profile_manager, scheduler, quality_recovery, operator_console, safety_gate; profile_manager.init_profile_db(); scheduler.init_db(); quality_recovery.init_review_db(); operator_console.init_operator_db(); safety_gate.init_safety_db()"
   `
2. **Validação de Integridade SQLite:**
   `powershell
   .\.venv\Scripts\python.exe -c "import sqlite3; conn = sqlite3.connect('storage/video_factory.db'); print('INTEGRITY:', conn.execute('PRAGMA integrity_check').fetchone()[0])"
   `
   *Critério de aprovação:* INTEGRITY: ok.

### Fase 4: Inicialização da V2 e Transição
1. **Configurar Ambiente de Produção:**
   `powershell
   [System.Environment]::SetEnvironmentVariable("MPT_ENVIRONMENT", "PRODUCTION", "Machine")
    = "PRODUCTION"
   `
2. **Registrar e Iniciar a Tarefa Unificada V2:**
   `powershell
   .\scripts\register_webui_v2_task.ps1 -RepoPath "C:\Projetos\MoneyPrinterTurbo" -Port 8080
   Start-ScheduledTask -TaskName "VideoFactory WebUI V2"
   `
3. **Health Check Imediato:**
   `powershell
   Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/system/status"
   `
   Confirmar: actory_state operacional, local_role: PRIMARY, zero erros críticos.

### Fase 5: Validação Humana e Liberação Gradual
1. Acessar http://127.0.0.1:8080 no navegador.
2. Validar que todos os canais e vídeos em estoque carregam com perfeição.
3. Executar operator_console.resume_factory() somente após aprovação humana formal.
