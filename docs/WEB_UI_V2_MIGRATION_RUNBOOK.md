# RUNBOOK — Migração e Operação da Web UI V2 no PC Forte (Fase R8)

Este documento especifica o procedimento operacional canônico para instalar, inicializar, validar e operar a **Web UI V2** no **PC Forte** (`C:\Projetos\MoneyPrinterTurbo`), preservando integralmente o Streamlit legado como fallback.

---

## 1. Arquitetura em Modo de Produção

Na Fase R8, a Web UI V2 foi consolidada para operar em modo de produção integrada ao backend FastAPI existente:

- **Mesma Origem (Same-Origin):** O backend FastAPI (`main.py` / `app.asgi:app`) serve tanto os arquivos estáticos compilados do frontend (`webui-v2/dist/`) quanto as rotas da API V2 (`/api/v2/...`). Não é necessário executar o servidor Vite (`npm run dev`) em produção.
- **Porta Dedicada (8080):** O FastAPI roda em `http://0.0.0.0:8080`.
- **Streamlit Preservado (8501):** O Streamlit continua operando na porta 8501 via `scripts/start_production.ps1` sem qualquer interferência ou alteração.
- **Roteamento SPA:** Rotas do cliente sem extensão (ex.: `/agent-ops`) recebem fallback transparente para `index.html` via `SPAStaticFiles`. Assets estáticos inexistentes retornam HTTP 404 estrito.
- **Autoridade Operacional:** O frontend é puramente camada de apresentação e telemetria. As mutações continuam protegidas por `require_primary_instance` (HTTP 403) e autenticação `verify_token` (HTTP 401).

---

## 2. Pré-requisitos no PC Forte

1. **Repositório Atualizado:** Branch `main` sincronizada via avanço fast-forward (`git pull --ff-only origin main`).
2. **Python:** Ambiente virtual `.venv` existente (`.venv\Scripts\python.exe`) com Python 3.11.x e dependências instaladas.
3. **Node.js / npm:** **NÃO NECESSÁRIOS NO PC FORTE**. O frontend é compilado no ambiente DEV e transferido via pacote ZIP pré-validado (`releases/webui-v2-dist-c64e9bf.zip`).
4. **Streamlit Ativo:** O serviço de produção `VideoFactory Production` (Streamlit na porta 8501) permanece em execução normal durante todo o processo.

---

## 3. Procedimento de Instalação Sem Node.js (Pacote Pré-Compilado)

O pacote de distribuição oficial é gerado no ambiente DEV através de `scripts/package_webui_v2.ps1` e disponibilizado em `releases/`:
- **Arquivo ZIP:** `releases/webui-v2-dist-c64e9bf.zip` (139.13 KB / 142.473 bytes)
- **SHA-256:** `0db1af19c0a0abd54c8d5fc821110f3828609eb5e2fe15b9d785659c9b76d0d2`
- **Conteúdo:** `dist/index.html`, `dist/assets/*.js`, `dist/assets/*.css`, `manifest.json`, `INSTALL.md`

### 3.1 Procedimento no PC Forte (PowerShell):

```powershell
# 1. Atualizar o código backend via fast-forward (sem mexer na main)
cd C:\Projetos\MoneyPrinterTurbo
git pull --ff-only origin main

# 2. Copiar o arquivo webui-v2-dist-c64e9bf.zip para C:\Projetos\MoneyPrinterTurbo\webui-v2
# Validar o checksum SHA-256 do pacote:
$ExpectedHash = "0db1af19c0a0abd54c8d5fc821110f3828609eb5e2fe15b9d785659c9b76d0d2"
$ActualHash = (Get-FileHash -Path ".\webui-v2\webui-v2-dist-c64e9bf.zip" -Algorithm SHA256).Hash.ToLowerInvariant()
if ($ActualHash -ne $ExpectedHash) {
    Write-Error "FALHA DE INTEGRIDADE: SHA-256 divergente do pacote!"
    exit 1
}
Write-Host "Integridade do pacote verificada com sucesso (PASS)." -ForegroundColor Green

# 3. Descompactar os artefatos compilados em webui-v2\dist
$WebUiDist = "C:\Projetos\MoneyPrinterTurbo\webui-v2\dist"
if (Test-Path $WebUiDist) {
    Remove-Item -Path $WebUiDist -Recurse -Force
}
New-Item -ItemType Directory -Path $WebUiDist -Force | Out-Null

Expand-Archive -Path ".\webui-v2\webui-v2-dist-c64e9bf.zip" -DestinationPath ".\webui-v2\temp_extract" -Force
Copy-Item -Path ".\webui-v2\temp_extract\dist\*" -Destination $WebUiDist -Recurse -Force
Remove-Item -Path ".\webui-v2\temp_extract" -Recurse -Force

# 4. Validar os artefatos instalados
Test-Path "$WebUiDist\index.html"
Test-Path "$WebUiDist\assets"
```

---

## 4. Procedimento de Inicialização

### Opção A — Execução via Script Operacional Canônico (Recomendada):

```powershell
.\scripts\start_webui_v2.ps1 -HostAddress "0.0.0.0" -Port 8080
```

O script:
1. Valida o runtime Python `.venv`.
2. Verifica a existência de `webui-v2\dist\index.html` (e compila se ausente).
3. Registra logs operacionais em `storage\logs\webui_v2\webui_v2_startup.log`.
4. Inicia o Uvicorn servindo a Web UI V2 e a API V2 no endereço e porta especificados.

### Opção B — Execução Direta:

```powershell
& .venv\Scripts\python.exe -m uvicorn app.asgi:app --host 0.0.0.0 --port 8080 --log-level info
```

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

1. **Desativação Imediata (Sem impacto em Git ou dados):**
   - Encerre o processo do Uvicorn na porta 8080 (CTRL+C ou encerre o PID registrado em `storage\logs\webui_v2\webui_v2_startup.log`).
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

