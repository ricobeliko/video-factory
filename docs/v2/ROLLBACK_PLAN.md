# Video Factory V2 — Plano de Rollback e Recuperação
**Documento Operacional V2.15A**
**Data de Atualização:** 18/10/2026
**Ambiente Alvo:** C:\Projetos\MoneyPrinterTurbo (PC Forte)

---

## 1. Gatilhos de Rollback

O procedimento de rollback deve ser acionado caso ocorra algum dos seguintes eventos durante ou imediatamente após a janela de cutover:
1. Falha crítica na inicialização do serviço FastAPI na porta 8080 (ex: conflito irrecuperável de porta ou dependência).
2. Erro de schema ou integridade SQLite (PRAGMA integrity_check diferente de ok).
3. Perda de acesso aos canais ou metadados de produção.
4. Falha na aquisição da autoridade PRIMARY pelo novo processo.

---

## 2. Princípio Mandatório de Não-Regressão de Dados

> [!CAUTION]
> **NÃO RESTAURAR BACKUP ANTIGO SOBRE DADOS NOVOS SEM AVALIAR DIVERGÊNCIAS.**
> Se qualquer tarefa tiver sido concluída ou qualquer post tiver sido publicado durante o teste da V2, a restauração cega do backup anterior apagará esses eventos do histórico. Deve-se avaliar as divergências com o script de auditoria antes da substituição de arquivos.

---

## 3. Procedimento Operacional de Rollback (Estimativa Medida: ~10 a 12 minutos)

1. **Parar a Aplicação V2:**
   `powershell
   Stop-ScheduledTask -TaskName "VideoFactory WebUI V2" -ErrorAction SilentlyContinue
   Get-Process python -ErrorAction SilentlyContinue | Where-Object { .Path -like "*MoneyPrinterTurbo*" } | Stop-Process -Force
   `

2. **Avaliação de Divergência de Dados:**
   Comparar a base atual com o backup pré-cutover:
   `powershell
   python -c "import sqlite3; c1 = sqlite3.connect('storage/video_factory.db'); c2 = sqlite3.connect('storage/video_factory_backup_pre_v2_<TIMESTAMP>.db'); print('Posts atuais:', c1.execute('SELECT COUNT(*) FROM publication_events').fetchone()[0], 'Posts backup:', c2.execute('SELECT COUNT(*) FROM publication_events').fetchone()[0])"
   `
   Se houver novas publicações registradas, extrair esses registros antes de restaurar o backup.

3. **Restaurar Banco de Dados SQLite a partir do Backup Pré-V2:**
   `powershell
   Copy-Item "C:\Projetos\MoneyPrinterTurbo\storage\video_factory_backup_pre_v2_*.db" 
             "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" -Force
   `

4. **Reverter o Código Git para o Commit Anterior:**
   `powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git checkout main
   git reset --hard 047920307b3004cb3797fb90867c4405f8a9a4a6
   `

5. **Restaurar Variável de Ambiente e Tarefa do Streamlit:**
   `powershell
   [System.Environment]::SetEnvironmentVariable("MPT_ENVIRONMENT", , "Machine")
   Start-ScheduledTask -TaskName "VideoFactory Production"
   `

6. **Validação de Integridade Pós-Rollback:**
   `powershell
   Invoke-WebRequest -Uri "http://127.0.0.1:8501/_stcore/health" -UseBasicParsing
   `
   Confirmar: Streamlit online na 8501 com status 200 e integridade SQLite ok.
