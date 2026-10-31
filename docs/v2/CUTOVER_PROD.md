# Roteiro de Cutover de Produção — V2 Motor Unificado

Este documento estabelece o procedimento operacional padrão (SOP), determinístico e estritamente não-destrutivo, para a transição definitiva da **Video Factory** no **PC Forte (PROD)** da arquitetura V1 (Streamlit na porta 8501) para a **V2 (Motor Unificado FastAPI + Web UI V2 na porta 8080)**.

---

## 1. Princípios Operacionais e Garantias

1. **Instância Única (Zero Concorrência V1/V2):** O Streamlit V1 é desligado completamente. Apenas a V2 roda na porta 8080 servindo a API FastAPI e o frontend React compilado (`webui-v2/dist`) na mesma origem (`same_origin = True`).
2. **Fail-Closed com Carimbo Determinístico (`BUILD_STAMP.json`):** O script `scripts/update_production.ps1` valida no preflight se o bundle `webui-v2/dist` do commit alvo está rigorosamente sincronizado com o código de `webui-v2/src` e `package-lock.json`, sem exigir Node.js na máquina de produção.
3. **Backup Transacional Automático:** Antes de qualquer parada ou alteração, um snapshot íntegro do banco SQLite é gerado com `PRAGMA integrity_check` e verificação SHA-256.
4. **Zero Escrita via `python -c`:** Nenhuma escrita no banco de produção é feita por `python -c`. A pausa inicial é feita pela tela da V1, as configurações e retomada são feitas via API REST ou interface da V2 (já rodando como PRIMARY).
5. **Execução Um Comando por Vez:** Cada etapa a seguir deve ser executada individualmente pelo operador, conferindo o resultado esperado antes de avançar.

---

## 2. Passo a Passo do Cutover (Execução na PC Forte)

Abra um terminal **PowerShell como Administrador** no diretório do projeto (`C:\Projetos\MoneyPrinterTurbo`):

```powershell
Set-Location -Path "C:\Projetos\MoneyPrinterTurbo"
```

---

### Passo 0: Anotar o SHA Atual de Produção (Segurança de Rollback)

Antes de qualquer ação, anote o commit atual em que a produção está rodando:

```powershell
git rev-parse HEAD
```

> **Critério de Aceite:** Anote o hash retornado (40 caracteres) como `<SHA_ANTERIOR>` para uso exclusivo caso o rollback seja necessário.

---

### Passo 1: Pausar a Fábrica de Vídeos (Pela Tela da V1)

Acesse a interface da V1 no navegador em **`http://127.0.0.1:8501`** e clique no botão de **Pausa da Fábrica** no painel de controle operacional do Streamlit.

---

### Passo 2: Confirmar Fábrica Ociosa (Somente Leitura)

Executa a validação de ociosidade garantindo que a fábrica está pausada e nenhum vídeo está no meio de renderização ou publicação, utilizando o script `C:\Temp\ocupado.py` já disponível na PC Forte:

```powershell
.\.venv\Scripts\python.exe C:\Temp\ocupado.py
```

> **Critério de Aceite:** Código de saída 0 e mensagem:
> `Pausa Operacional : PAUSADA`
> `Diagnóstico       : OCIOSA`
> `Resultado         : SEGURO prosseguir com atualização / cutover.`
> *(Se o diagnóstico for `OCUPADA`, aguarde até a conclusão das tarefas ativas e reexecute).*

---

### Passo 3: Extrair Script Novo e Executar Preflight Passivo de Atualização

> [!NOTE]
> **Definição de `<ALVO>` e Bootstrap do Script:**
> Como o repositório atual de produção está na versão V1 (`main`), o script de atualização novo (`update_production.ps1`) ainda não existe no working tree. Portanto, ele deve ser extraído do commit alvo para `C:\Temp\update_production_v2.ps1` e executado de fora do repositório apontando `-RepoPath C:\Projetos\MoneyPrinterTurbo`.
> O parâmetro `<ALVO>` será `origin/main` ou `origin/v2/base` conforme a decisão na missão de merge.

1. Baixe os metadados remotos e extraia o script atualizado para `C:\Temp`:

```powershell
git fetch origin
git show origin/v2/base:scripts/update_production.ps1 | Out-File -Encoding utf8 C:\Temp\update_production_v2.ps1
```

2. Execute o preflight passivo a partir de `C:\Temp`:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Temp\update_production_v2.ps1 -PreflightOnly -TargetRef <ALVO> -RepoPath C:\Projetos\MoneyPrinterTurbo
```

> **Critério de Aceite:**
> - `FAST_FORWARD : COMPATÍVEL`
> - `DEPENDENCIES : PASS`
> - `WEBUI_V2_DIST : PASS`
> - `STATUS : PREFLIGHT_PASS`

---

### Passo 4: Executar Atualização Segura de Produção (FF-Only)

Aplica o avanço Fast-Forward, gera o backup transacional, para a Scheduled Task, confere a liberação das portas 8501 e 8080, valida dependências e carimbo de build, e inicia o Motor V2 na porta 8080:

```powershell
powershell -ExecutionPolicy Bypass -File C:\Temp\update_production_v2.ps1 -TargetRef <ALVO> -RepoPath C:\Projetos\MoneyPrinterTurbo -RollbackHealthUrl "http://127.0.0.1:8501/_stcore/health"
```

> **Critério de Aceite:**
> - `BACKUP = PASS`
> - `UPDATE = PASS`
> - `WEBUI_V2_DIST = PASS`
> - `HEALTH = PASS`
> - `STATUS = DEPLOY_SUCCESS`

---

### Passo 5: Validar Endpoints de Saúde e Frontend da V2

Confirma se o Motor V2 subiu como PRIMARY e se o SPA React está sendo servido na porta 8080:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
```

> **Critério de Aceite:**
> - `status`: `"healthy"`
> - `role`: `"PRIMARY"`
> - `is_primary`: `true`
> - `webui_v2_available`: `true`
> - `same_origin`: `true`

Para validar a entrega do HTML no navegador ou via curl:

```powershell
curl.exe -I http://127.0.0.1:8080/
```

> **Critério de Aceite:** `HTTP/1.1 200 OK` com `content-type: text/html; charset=utf-8`.

---

### Passo 6: Resetar Voz dos 3 Canais (Herdar Voz Global na V2 PRIMARY)

Na V1 legada, as vozes gravadas individualmente nos canais eram ignoradas e a voz global (Brian) era forçada. Na V2, a voz do canal tem prioridade sobre a global. Para manter o comportamento homologado, limpamos a voz de canal para que ela herde a voz global (`origem=GLOBAL_UI`).

#### 6.1 Listar canais para obter os IDs exatos:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/channels" | Select-Object -ExpandProperty data | Where-Object { $_.name -in @('Dose Diária de Internet', 'Dose Diária de GTA VI', 'Dose Diária de Histórias') } | Select-Object id, name
```

> **Critério de Aceite:** Retorna a tabela com os IDs dos 3 canais (ex: `profile-4d18bf9a5d94`, etc.).

#### 6.2 Resetar a voz para herdar a global (via tela ou via API):

Para cada ID obtido acima (`<ID_INTERNET>`, `<ID_GTA>`, `<ID_HISTORIAS>`), execute o PATCH com `voice_name` vazio (`""`):

```powershell
Invoke-RestMethod -Method Patch -Uri "http://127.0.0.1:8080/api/v2/channels/<ID>/voice" -ContentType "application/json" -Body '{"voice_name": ""}'
```

*(Alternativa via curl.exe)*:
```powershell
curl.exe -X PATCH http://127.0.0.1:8080/api/v2/channels/<ID>/voice -H "Content-Type: application/json" -d "{\"voice_name\": \"\"}"
```

#### 6.3 Conferir configurações pós-reset:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/channels/<ID>/settings" | Select-Object -ExpandProperty data | Select-Object profile_name, @{N='Voz';E={$_.effective_voice.voice_name.value}}, @{N='Origem';E={$_.effective_voice.voice_name.source}}
```

> **Critério de Aceite:** O campo `Origem` deve exibir `GLOBAL_UI` (ou `DEFAULT_APP`), herdando a voz global configurada no sistema.

---

### Passo 7: Verificar Configuração do Canal Joana (TikTok)

Inspeciona o status operacional e a voz efetiva do canal da Joana estritamente via consulta GET da API V2:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/channels" | Select-Object -ExpandProperty data | Where-Object { $_.name -match "joana|tiktok" } | ForEach-Object { $id = $_.id; Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/channels/$id/settings" } | Select-Object -ExpandProperty data | Select-Object profile_name, growth_mode, autonomous_enabled, @{N='Voz';E={$_.effective_voice.voice_name.value}}, @{N='Origem';E={$_.effective_voice.voice_name.source}}
```

> **Critério de Aceite:** O canal da Joana é exibido com sua voz efetiva identificada e configurações operacionais intactas.

---

### Passo 8: Retomar a Fábrica de Vídeos (Pela V2 PRIMARY)

Pela interface em **`http://127.0.0.1:8080/`** (aba **Sistema**, botão **Retomar Fábrica**) OU via requisição REST:

```powershell
Invoke-RestMethod -Method Post -Uri "http://127.0.0.1:8080/api/v2/factory/resume"
```

*(Alternativa via curl.exe)*:
```powershell
curl.exe -X POST http://127.0.0.1:8080/api/v2/factory/resume
```

Conferir retorno da saúde e estado da fábrica:
```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8080/api/v2/health"
```

> **Critério de Aceite:** Status `healthy`, `role = PRIMARY` e fábrica retomada com sucesso.

---

### Passo 9: Diagnóstico Operacional Consolidado

Verifica a saúde completa do sistema pós-cutover:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\production_status.ps1
```

> **Critério de Aceite:**
> - `Instance Role : PRIMARY`
> - `Factory State : RUNNING`
> - `Readiness     : READY`

---

## 3. Procedimento de Rollback Imediato (Contingência)

Caso ocorra qualquer anomalia crítica e seja necessário retornar imediatamente para a V1 (Streamlit 8501):

### Passo R0: Localizar o SHA Anterior

Recupere o `<SHA_ANTERIOR>` que foi anotado no **Passo 0** antes do início da atualização.

### Passo R1: Parar a Tarefa Agendada

```powershell
schtasks /End /TN "VideoFactory Production"
```

### Passo R2: Retornar ao Commit Anterior (Não-Destrutivo)

```powershell
git switch --detach <SHA_ANTERIOR>
```

### Passo R3: Iniciar a Tarefa Agendada no Commit Anterior

O script `start_production.ps1` no commit anterior da V1 não possui a flag `-Legacy` e sobe diretamente o Streamlit 8501. Inicie a tarefa agendada:

```powershell
schtasks /Run /TN "VideoFactory Production"
```

### Passo R4: Validar Saúde do Streamlit

Aguarde 15 segundos e valide a saúde da V1 na porta 8501:

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8501/_stcore/health"
```

> **Critério de Aceite:** Retorno com status HTTP 200 e conteúdo `ok`.
