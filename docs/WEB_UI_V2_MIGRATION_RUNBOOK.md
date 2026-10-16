# RUNBOOK — Migração e Operação da Web UI V2 no PC Forte (Release Consolidada R10)

Este documento especifica o procedimento operacional canônico para instalar, inicializar, validar e operar a **Web UI V2** no **PC Forte** (`C:\Projetos\MoneyPrinterTurbo`), consolidando as frentes **R9.1 (Live Pipeline Real)**, **R9.2 (Operação Multicanal & UX)** e **R9.3 (Homologação Integrada)**, preservando integralmente o Streamlit legado na porta 8501 como fallback operacional.

---

## 1. Arquitetura em Modo de Produção

Na Release Consolidada R10, a Web UI V2 opera integrada ao backend FastAPI existente:

- **Mesma Origem (Same-Origin):** O backend FastAPI (`main.py` / `app.asgi:app`) serve tanto os arquivos estáticos compilados do frontend (`webui-v2/dist/`) quanto as rotas da API V2 (`/api/v2/...`). Não é necessário executar o servidor Vite (`npm run dev`) em produção.
- **Porta Dedicada (8080):** O FastAPI roda em `http://0.0.0.0:8080`.
- **Streamlit Preservado (8501):** O Streamlit continua operando na porta 8501 via `scripts/start_production.ps1` sem qualquer interferência ou alteração.
- **Roteamento SPA:** Rotas do cliente sem extensão (ex.: `/agent-ops`) recebem fallback transparente para `index.html` via `SPAStaticFiles`. Assets estáticos inexistentes retornam HTTP 404 estrito.
- **Autoridade Operacional:** O frontend é puramente camada de apresentação e telemetria. As mutações continuam protegidas por `require_primary_instance` (HTTP 403) e autenticação `verify_token` (HTTP 401).

---

## 2. Pré-requisitos no PC Forte

1. **Repositório Atualizado:** Branch `main` sincronizada via avanço fast-forward (`git pull --ff-only origin main`).
2. **Python:** Ambiente virtual `.venv` existente (`.venv\Scripts\python.exe`) com Python 3.11.x e dependências instaladas.
3. **Node.js / npm:** **NÃO NECESSÁRIOS NO PC FORTE**. O frontend é compilado no ambiente DEV e transferido via pacote ZIP pré-validado (`releases/webui-v2-dist-96b9c11.zip`).
4. **Streamlit Ativo:** O serviço de produção `VideoFactory Production` (Streamlit na porta 8501) permanece em execução normal durante todo o processo.

---

## 3. Procedimento de Instalação Sem Node.js (Pacote Pré-Compilado)

O pacote de distribuição oficial é gerado no ambiente DEV através de `scripts/package_webui_v2.ps1` e disponibilizado em `releases/`:
- **Arquivo ZIP:** `releases/webui-v2-dist-96b9c11.zip` (140.17 KB / 143.535 bytes)
- **SHA-256:** `3bebaf3b5307cf1becd07e4b97a61c42b38a924d2bf242b75fd54e5ff9213b4e`
- **Target Git SHA:** `96b9c112bcd912c95ac0ca05de19a6e057059585`
- **Conteúdo:** `dist/index.html`, `dist/assets/*.js`, `dist/assets/*.css`, `manifest.json`, `INSTALL.md`

### 3.1 Procedimento Unificado e Seguro no PC Forte (PowerShell):

```powershell
# 1. Preflight sem mutação: verificar integridade do repositório
cd C:\Projetos\MoneyPrinterTurbo
git status
git branch --show-current

# 2. Checagem de atividade: certificar-se de que não há tarefa em geração ativa
.venv\Scripts\python.exe -c "from app.services import operator_console; st = operator_console.get_live_execution_overview(); running = [c['profile_name'] for c in st['channels'] if c['status'] == 'RUNNING']; print('TAREFAS ATIVAS:', running if running else 'NENHUMA (LIVRE)')"

# 3. Atualizar o código backend via fast-forward estrito
git pull --ff-only origin main

# 4. Validar SHA instalado
$InstalledSha = (git rev-parse HEAD).Trim()
Write-Host "SHA Instalado: $InstalledSha" -ForegroundColor Green
if ($InstalledSha -ne "96b9c112bcd912c95ac0ca05de19a6e057059585") {
    Write-Warning "Aviso: SHA instalado ($InstalledSha) difere do release candidate esperado."
}

# 5. Copiar e validar o checksum SHA-256 do pacote pré-compilado:
$ExpectedHash = "3bebaf3b5307cf1becd07e4b97a61c42b38a924d2bf242b75fd54e5ff9213b4e"
$ActualHash = (Get-FileHash -Path ".\releases\webui-v2-dist-96b9c11.zip" -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash) {
    Write-Error "FALHA DE INTEGRIDADE: SHA-256 divergente do pacote!"
    exit 1
}
Write-Host "Integridade do pacote verificada com sucesso (PASS)." -ForegroundColor Green

# 6. Descompactar os artefatos compilados em webui-v2\dist
$WebUiDist = "C:\Projetos\MoneyPrinterTurbo\webui-v2\dist"
if (Test-Path $WebUiDist) {
    Remove-Item -Path $WebUiDist -Recurse -Force
}
New-Item -ItemType Directory -Path $WebUiDist -Force | Out-Null

Expand-Archive -Path ".\releases\webui-v2-dist-96b9c11.zip" -DestinationPath ".\webui-v2\temp_extract" -Force
Copy-Item -Path ".\webui-v2\temp_extract\dist\*" -Destination $WebUiDist -Recurse -Force
Remove-Item -Path ".\webui-v2\temp_extract" -Recurse -Force

# 7. Validar presença dos artefatos estáticos
Test-Path "$WebUiDist\index.html"
Test-Path "$WebUiDist\assets"
```

---

## 4. Procedimento de Inicialização

### Opção A — Execução Automática e Persistente via Scheduled Task (Recomendada para Produção):

Para que a Web UI V2 inicie automaticamente no boot do Windows, sem depender de janelas abertas do PowerShell e sem exigir login do operador:

Abra o PowerShell como Administrador no PC Forte (`C:\Projetos\MoneyPrinterTurbo`):

```powershell
.\scripts\register_webui_v2_task.ps1
```

O script automatiza todo o ciclo com garantias de segurança:
1. **Verificação de Pré-condições:** Valida o `.venv` e a presença do build compilado em `webui-v2\dist\index.html`.
2. **Preservação Estrita da Produção:** Detecta e mantém 100% intacta a tarefa `VideoFactory Production` (Streamlit na 8501).
3. **Tratamento de Instância Manual Preexistente:** Se uma janela PowerShell ou processo manual já estiver ocupando a porta 8080, o script encerra o processo anterior de forma limpa antes de acionar a Scheduled Task.
4. **Registro Idempotente:** Registra a tarefa `VideoFactory WebUI V2` com:
   - **Gatilho:** No boot do Windows (`AtStartup`), sem exigir login.
   - **Execução:** Invisível / sem janela (`-WindowStyle Hidden`).
   - **Prevenção de Duplicatas:** `MultipleInstances = IgnoreNew` (impede processos concorrentes).
   - **Recuperação Automática:** `RestartCount = 3`, `RestartInterval = 1 minuto`.
   - **Tempo Limite:** `ExecutionTimeLimit = 0` (execução contínua).
5. **Inicialização e Validação:** Inicia a tarefa e confirma via polling:
   - HTTP 200 em `http://127.0.0.1:8080/health`.
   - HTTP 200 em `http://127.0.0.1:8080/api/v2/health` confirmando `role = SECONDARY_VIEW_ONLY`.
   - Exibe o status consolidado de ambas as tarefas no encerramento.

### Opção B — Execução Manual para Testes Rápidos:

Caso prefira rodar temporariamente em uma janela visível:

```powershell
.\scripts\start_webui_v2.ps1 -HostAddress "0.0.0.0" -Port 8080
```

O launcher detecta se outra instância já estiver ouvindo na porta 8080 e encerra com sucesso sem duplicar processos.

---

## 5. Verificação de Saúde e Conectividade

Execute localmente ou a partir de outro terminal no PC Forte:

### 5.1 Health Check Básico (Não autenticado):
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/health"
```
**Resposta Esperada:**
```json
{
  "status": "healthy",
  "app": "MoneyPrinterTurbo",
  "version": "1.3.7",
  "webui_v2_available": true,
  "same_origin": true
}
```

### 5.2 Health Check Operacional V2:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
```
**Resposta Esperada:**
```json
{
  "status": 200,
  "data": {
    "status": "healthy",
    "app": "MoneyPrinterTurbo",
    "version": "1.3.7",
    "role": "PRIMARY",
    "is_primary": true,
    "webui_v2_available": true,
    "same_origin": true
  }
}
```

### 5.3 Verificação da Interface no Navegador:
- Abra `http://127.0.0.1:8080/` no navegador.
- Confirme o carregamento do título "Video Factory — Factory Live".
- Verifique que os canais reais monitorados aparecem no Top Channels Deck.
- Verifique a telemetria do pool de contas do Google Flow.
- Abra o Execution Drawer em um canal e teste a aba de Quotas e Janela de Publicação.

---

## 6. Orientações para Acesso Remoto

Se o operador acessar a interface de outro computador na rede local ou via VPN:

1. **URL de Acesso:** `http://<IP_DO_PC_FORTE>:8080/`
2. **Autenticação com API Key (Sem Exposição em URL):**
   Se uma chave de API estiver configurada em `config.toml` (`[app] api_key = "..."`):
   - Ao acessar `http://<IP_DO_PC_FORTE>:8080/`, caso a API exija autenticação (HTTP 401), a interface solicitará a API Key através de um prompt nativo seguro no navegador.
   - A credencial informada é armazenada estritamente em `sessionStorage` (volátil, restrita à aba/sessão atual, sem persistir em disco, sem aparecer na barra de endereços e sem vazar em logs de tráfego/histórico).
   - O operador também pode configurar a chave diretamente no console do navegador via `sessionStorage.setItem('api_key', 'SUA_CHAVE')`.
   - Se porventura a URL for aberta com `?api_key=...`, a interface captura a chave para o `sessionStorage` e **remove imediatamente o parâmetro da barra de endereços** através de `history.replaceState()`, eliminando o vazamento no histórico do navegador.
3. **Firewall do Windows:**
   Caso o acesso remoto seja bloqueado, autorize a porta TCP 8080 no Firewall do Windows:
   ```powershell
   New-NetFirewallRule -DisplayName "VideoFactory Web UI V2 (Port 8080)" -Direction Inbound -LocalPort 8080 -Protocol TCP -Action Allow
   ```

---

## 7. Estratégia de Coexistência e Fallback para Streamlit

- **Zero Downtime:** A Web UI V2 na porta 8080 opera de forma independente do Streamlit na porta 8501.
- **Fallback Imediato:** Se qualquer problema visual ou operacional for identificado na Web UI V2, o operador pode acessar imediatamente `http://<IP_DO_PC_FORTE>:8501` para continuar operando pelo Streamlit legado.
- **Nenhum arquivo ou dependência do Streamlit foi removido.**

---

## 8. Procedimento de Rollback Seguro

Caso seja necessário desativar ou reverter a Web UI V2:

1. **Desativação Imediata da Scheduled Task / Processo:**
   - Para desativar e remover a tarefa agendada sem afetar outros serviços:
     ```powershell
     .\scripts\register_webui_v2_task.ps1 -Unregister
     ```
   - Ou simplesmente interrompa a tarefa via PowerShell:
     ```powershell
     Stop-ScheduledTask -TaskName "VideoFactory WebUI V2"
     ```
   - A Web UI V2 fica imediatamente inativa.
   - O Streamlit na porta 8501 continua operando normalmente como autoridade primária ou interface ativa.

2. **Preservação Obrigatória da Branch `main` (Sem Detached HEAD):**
   - **NUNCA** execute `git switch --detach` ou `git checkout <SHA>` no PC Forte. O repositório operacional deve permanecer estritamente na branch `main`.
   - Como todas as alterações da R8 são aditivas e não alteram tabelas de banco de dados nem o runtime do Streamlit, parar o serviço da porta 8080 é 100% suficiente para o rollback operacional.
   - Caso seja necessário reverter alterações no histórico do Git, realize a reversão no ambiente DEV através de commit limpo (ex.: `git revert`), envie ao repositório remoto via PR/push autorizado e puxe no PC Forte estritamente via avanço fast-forward:
     ```powershell
     git pull --ff-only origin main
     ```
     mantendo a branch `main` limpa, sincronizada e íntegra.

