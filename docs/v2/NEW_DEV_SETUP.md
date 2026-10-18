# Video Factory V2 — Guia de Configuração no Novo PC DEV

> [!IMPORTANT]
> **REGRAS INEGOCIÁVEIS DE SEGURANÇA E ISOLAMENTO:**
> 1. O novo PC DEV destina-se **exclusivamente a desenvolvimento e testes da V2**.
> 2. **NUNCA** copiar bancos de dados reais de produção (`C:\Projetos\MoneyPrinterTurbo`) para o ambiente DEV.
> 3. **NUNCA** utilizar tokens de autenticação ou credenciais reais de produção nas redes sociais.
> 4. Manter o Scheduler inativo (`scheduler_enabled = False`) e publicação externa desligada (`auto_publish_enabled = False`).
> 5. A branch de trabalho é `feat/video-factory-v2`, isolada via Worktree ou clone dedicado.

---

## 1. Pré-Requisitos de Ambiente no Novo PC

| Componente | Versão Homologada | Comando de Verificação |
| :--- | :--- | :--- |
| **Sistema Operacional** | Windows 10 / 11 (64-bit) | `systeminfo` |
| **Git** | >= 2.40 (Windows) | `git --version` |
| **Python** | 3.11.x (Recomendado 3.11.16) | `python --version` |
| **Node.js** | >= 20.x (Homologado v24.19.0) | `node --version` |
| **npm** | >= 10.x (Homologado 11.17.0) | `npm --version` |
| **FFmpeg / FFprobe** | >= 6.x (com codecs AAC/H.264) | `ffmpeg -version` |

*Nota: FFmpeg deve estar configurado na variável de ambiente `PATH` do sistema.*

---

## 2. Estrutura de Diretórios Recomendada

Recomenda-se manter a mesma organização hierárquica do notebook:
- **Repositório Principal (main):** `D:\Projetos\MoneyPrinterTurbo` (ou `C:\Projetos\MoneyPrinterTurbo` caso o PC novo tenha somente unidade C)
- **Worktree Isolado da V2:** `D:\Projetos\MoneyPrinterTurbo-V2`

---

## 3. Procedimento Passo a Passo de Instalação

### Passo 1: Clonar o Repositório Git
Abra o PowerShell no diretório raiz de projetos (ex: `D:\Projetos`):
```powershell
cd D:\Projetos
git clone https://github.com/ricobeliko/video-factory.git MoneyPrinterTurbo
cd MoneyPrinterTurbo
git fetch origin
```

### Passo 2: Criar o Worktree Isolado para a V2
```powershell
git worktree add D:\Projetos\MoneyPrinterTurbo-V2 feat/video-factory-v2
cd D:\Projetos\MoneyPrinterTurbo-V2
```

### Passo 3: Configurar o Ambiente Virtual Python (.venv)
No diretório `D:\Projetos\MoneyPrinterTurbo-V2`:
```powershell
# Criação do venv com Python 3.11
python -m venv .venv

# Ativação do ambiente
.\.venv\Scripts\Activate.ps1

# Atualização de ferramentas de build
python -m pip install --upgrade pip setuptools wheel

# Instalação das dependências
pip install -r requirements.txt
```

### Passo 4: Instalar Dependências do Frontend React + Vite
No diretório `D:\Projetos\MoneyPrinterTurbo-V2\webui-v2`:
```powershell
cd webui-v2
npm install
npm run build
cd ..
```

### Passo 5: Inicializar o Banco SQLite Sintético da V2
Execute o script determinístico que recria o schema e o dataset homologado da V2.12:
```powershell
.\.venv\Scripts\python.exe scripts\init_v2_synthetic_db.py
```
*Saída esperada: `[SUCCESS] Banco sintetico V2 inicializado com sucesso em: ...\storage\video_factory.db`*

---

## 4. Como Executar a Video Factory V2

### Modo 1: Execução Integrada (Produção Local / FastAPI na porta 8080)
```powershell
cd D:\Projetos\MoneyPrinterTurbo-V2
.\.venv\Scripts\python.exe main.py
```
- Acesse no navegador: **`http://127.0.0.1:8080`**
- O backend FastAPI serve automaticamente o build estático do Vite (`webui-v2/dist`).

### Modo 2: Desenvolvimento Frontend com Hot-Reload (Vite na porta 5173)
```powershell
# Terminal 1: Backend FastAPI
cd D:\Projetos\MoneyPrinterTurbo-V2
.\.venv\Scripts\python.exe main.py

# Terminal 2: Vite Dev Server
cd D:\Projetos\MoneyPrinterTurbo-V2\webui-v2
npm run dev
```
- Acesse no navegador: **`http://127.0.0.1:5173`**

---

## 5. Como Parar os Serviços

No terminal, pressione `Ctrl + C` ou execute no PowerShell:
```powershell
Get-Process python, node -ErrorAction SilentlyContinue | Where-Object { $_.Path -like "*MoneyPrinterTurbo-V2*" } | Stop-Process -Force
```

---

## 6. Teste Rápido de Fumaça (Smoke Test)

Para validar a integridade da instalação no novo PC antes de prosseguir:
```powershell
cd D:\Projetos\MoneyPrinterTurbo-V2
.\.venv\Scripts\python.exe -m pytest test/services/test_web_ui_v2_api.py -q
```
*Critério de aprovação:* 43 passed.

---

## 7. Próxima Etapa no Novo PC

Com o ambiente restaurado e aprovado (`NEW_DEV_READY = PASS`), iniciar a **Fase V2.13 — Ensaio de Migração e Compatibilidade de Dados**.
