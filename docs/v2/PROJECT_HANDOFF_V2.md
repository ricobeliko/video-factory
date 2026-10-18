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
