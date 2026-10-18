# Video Factory V2 — Plano de Rollback e Recuperação
**Documento Operacional V2.8**
**Data de Criação:** 2026-10-18
**Ambiente Alvo:** `C:\Projetos\MoneyPrinterTurbo` (PC Forte)

---

## 1. Gatilhos de Rollback

O rollback imediato deve ser acionado se qualquer um dos seguintes cenários for detectado após a implantação:
1. Erro crítico de inicialização no serviço Windows da fábrica.
2. Impossibilidade de carregar a lista de canais existentes.
3. Falhas sistemáticas na renderização de vídeos homologados (Tradicional, Quiz Q0-R ou Quiz Paper P1.3).
4. Corrupção ou incompatibilidade no schema do banco SQLite.

---

## 2. Procedimento de Rollback Imediato (RTO &lt; 5 minutos)

1. **Parar o Serviço Windows:**
   ```powershell
   Stop-Service -Name "VideoFactory" -Force
   ```
2. **Restaurar Código para o Commit Anterior Homologado:**
   ```powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git checkout <COMMIT_SHA_ANTERIOR>
   ```
3. **Restaurar Banco de Dados SQLite a partir do Backup Pré-V2:**
   ```powershell
   Copy-Item "C:\Projetos\MoneyPrinterTurbo\storage\video_factory_backup_pre_v2_*.db" `
             "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" -Force
   ```
4. **Remover Build Estático da V2 (se necessário reverter para Streamlit puro):**
   ```powershell
   Remove-Item "C:\Projetos\MoneyPrinterTurbo\webui-v2\dist" -Recurse -Force -ErrorAction SilentlyContinue
   ```
5. **Reiniciar Serviço:**
   ```powershell
   Start-Service -Name "VideoFactory"
   ```
6. **Verificação de Integridade Pós-Rollback:**
   Confirmar que o Streamlit ou a versão anterior responde normalmente e os canais voltam a operar.
