# Video Factory V2 — Plano de Migração e Cutover para Produção (PC Forte)
**Documento Operacional V2.8**
**Data de Criação:** 2026-10-18
**Ambiente Alvo Futuro:** `C:\Projetos\MoneyPrinterTurbo` (PC Forte)
**Ambiente Homologado:** `D:\Projetos\MoneyPrinterTurbo-V2` (`feat/video-factory-v2`)

---

> [!CRITICAL]
> **ESTA MISSÃO NÃO EXECUTA DEPLOY EM PRODUÇÃO.**
> Este documento é o plano rigoroso e homologado a ser executado exclusivamente em janela de manutenção programada pelo operador humano no PC Forte.

---

## 1. Pré-Requisitos Mandatórios de Cutover

Antes de iniciar qualquer intervenção no PC Forte:
1. **Verificação de Tarefas:** Confirmar via terminal ou logs que nenhuma renderização FFmpeg ou upload de vídeo está em andamento.
2. **Pausa do Scheduler:** Executar `operator_console.pause_factory()` para evitar novas tarefas automáticas.
3. **Backup Físico do Banco SQLite:**
   ```powershell
   Copy-Item "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" `
             "C:\Projetos\MoneyPrinterTurbo\storage\video_factory_backup_pre_v2_$(Get-Date -Format 'yyyyMMdd_HHmmss').db"
   ```
4. **Preservação de Mídia e Configurações:** As pastas `storage/tasks/`, `resource/` e o arquivo `config.toml` jamais devem ser sobrescritos.

---

## 2. Passo a Passo do Procedimento de Instalação no PC Forte

1. **Parar Serviços Windows:**
   ```powershell
   Stop-Service -Name "VideoFactory" -Force -ErrorAction SilentlyContinue
   ```
2. **Atualização do Código (Fast-Forward Git):**
   ```powershell
   cd C:\Projetos\MoneyPrinterTurbo
   git checkout main
   git merge feat/video-factory-v2 --ff-only
   ```
3. **Atualização das Dependências Python:**
   ```powershell
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```
4. **Compilação e Entrega do Frontend Estático:**
   ```powershell
   cd C:\Projetos\MoneyPrinterTurbo\webui-v2
   npm install
   npm run build
   ```
   *O build estático gerado em `webui-v2/dist/` será servido automaticamente pelo FastAPI através de `SPAStaticFiles` sem necessidade de processo Node.js em background.*
5. **Reiniciar Serviço:**
   ```powershell
   Start-Service -Name "VideoFactory"
   ```
6. **Smoke Test de Produção (Verificação Imediata):**
   ```powershell
   Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
   ```
   Confirmar: `status: healthy` e `webui_v2_available: true`.

---

## 3. Critérios de Homologação Pós-Cutover

- Interface web carregando instantaneamente em `http://127.0.0.1:8080`.
- Listagem dos canais existentes intacta (zero perda de canais ou credenciais).
- Central de Revisão exibindo vídeos do estoque normalmente.
- Retomar a fábrica (`operator_console.resume_factory()`) após validação visual do operador.
