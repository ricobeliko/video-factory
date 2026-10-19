# Video Factory V2 — Plano de Rollback e Recuperação
**Documento Operacional V2.15B**
**Data de Atualização:** 18/10/2026
**Ambiente Alvo:** C:\Projetos\MoneyPrinterTurbo (PC Forte)

---

> [!IMPORTANT]
> **REVISÃO ARQUITETURAL V2.15C — RECUPERAÇÃO E ROLLBACK EM DOIS ESTÁGIOS:**
> - **No Estágio A (Operação Paralela Isolada):** A fábrica antiga continua operando normalmente. O "rollback" consiste unicamente em finalizar os processos da V2 no diretório isolado (`C:\Projetos\MoneyPrinterTurbo-V2`). O impacto sobre a produção real é **ZERO**, pois nenhuma porta, fila ou banco legado foi alterado.
> - **No Estágio B (Transferência de Autoridade):** Caso haja qualquer anomalia após a futura transferência autorizada, a fábrica antiga permanece preservada no disco e pode reassumir a autoridade PRIMARY imediatamente mediante reativação do seu scheduler.

---

## 1. Gatilhos de Rollback

O procedimento de rollback deve ser acionado caso ocorra algum dos seguintes eventos:
1. Conflito operacional ou anomalia durante testes paralelos no PC Forte.
2. Falha de integridade SQLite ou divergência não reconciliável.
3. Perda de acesso a canais ou configurações operacionais.
4. Falha na aquisição ou sustentação da autoridade PRIMARY.

---

## 2. Princípio Mandatório de Não-Regressão de Dados

> [!CAUTION]
> **NÃO RESTAURAR BACKUP ANTIGO SOBRE DADOS NOVOS SEM AVALIAR DIVERGÊNCIAS.**
> Se qualquer tarefa tiver sido concluída ou qualquer evento registrado durante a janela operacional, a restauração cega do backup anterior apagará esses eventos do histórico. O `scripts/v2_cutover.ps1` bloqueia automaticamente restaurações divergentes, exigindo avaliação e contingência.

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
   # Reverter para main de forma estritamente segura (proibido git reset --hard ou git clean)
   git checkout main
   Copy-Item "storage\backups\cutover_<TIMESTAMP>\hotfix\autonomous_production.py" "app\services\autonomous_production.py" -Force
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


### Procedimento Automatizado de Rollback V2.15B
Em caso de falha durante ou após a janela de cutover, execute o parâmetro `-Rollback` no script oficial:
```powershell
powershell.exe -ExecutionPolicy Bypass -File C:\Projetos\v2_cutover.ps1 -RepoPath C:\Projetos\MoneyPrinterTurbo -Rollback -BackupDirToRestore "C:\Projetos\MoneyPrinterTurbo\storage\backups\cutover_<TIMESTAMP>"
```
Isso garante a recomposição exata do SHA `cf7d64767e13f94eb710809057dbcbc6efc19a27`, restaura o banco de dados e reativa o Streamlit na porta 8501.
