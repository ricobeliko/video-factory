# Roteiro de Cutover de Produção — V2 Motor Unificado

Este documento estabelece o procedimento operacional padrão (SOP), determinístico e estritamente não-destrutivo, para a transição definitiva da **Video Factory** no **PC Forte (PROD)** da arquitetura V1 (Streamlit na porta 8501) para a **V2 (Motor Unificado FastAPI + Web UI V2 na porta 8080)**.

---

## 1. Princípios Operacionais e Garantias

1. **Instância Única (Zero Concorrência V1/V2):** O Streamlit V1 é desligado completamente. Apenas a V2 roda na porta 8080 servindo a API FastAPI e o frontend React compilado (`webui-v2/dist`) na mesma origem (`same_origin = True`).
2. **Fail-Closed com Carimbo Determinístico (`BUILD_STAMP.json`):** O script `scripts/update_production.ps1` valida no preflight se o bundle `webui-v2/dist` do commit alvo está rigorosamente sincronizado com o código de `webui-v2/src` e `package-lock.json`, sem exigir Node.js na máquina de produção.
3. **Backup Transacional Automático:** Antes de qualquer parada ou alteração, um snapshot íntegro do banco SQLite é gerado com `PRAGMA integrity_check` e verificação SHA-256.
4. **Execução Um Comando por Vez:** Cada etapa a seguir deve ser executada individualmente pelo operador, conferindo o resultado esperado antes de avançar.

---

## 2. Passo a Passo do Cutover (Execução na PC Forte)

Abra um terminal **PowerShell como Administrador** no diretório do projeto (`C:\Projetos\MoneyPrinterTurbo`):

```powershell
Set-Location -Path "C:\Projetos\MoneyPrinterTurbo"
```

---

### Passo 1: Pausar a Fábrica de Vídeos

Impede o início de novos ciclos de roteirização, geração ou publicação pelo scheduler:

```powershell
.\.venv\Scripts\python.exe -c "from app.services import operator_console; operator_console.pause_factory(); print('Estado da Fábrica:', operator_console.get_factory_state())"
```

> **Critério de Aceite:** A saída deve exibir `Estado da Fábrica: PAUSED`.

---

### Passo 2: Confirmar Fábrica Ociosa

Executa a validação de ociosidade garantindo que nenhum vídeo esteja no meio da renderização ou publicação externa:

```powershell
.\.venv\Scripts\python.exe scripts\ocupado.py
```

> **Critério de Aceite:** Código de saída 0 e mensagem:
> `Diagnóstico : OCIOSA`
> `Resultado : SEGURO prosseguir com atualização / cutover.`
> *(Se o diagnóstico for `OCUPADA`, aguarde alguns minutos até a conclusão das tarefas ativas e reexecute).*

---

### Passo 3: Executar Preflight Passivo de Atualização

Audita integridade do repositório, dependências, executáveis de mídia e bundle frontend do commit alvo antes de interromper qualquer serviço:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update_production.ps1 -PreflightOnly -TargetRef origin/v2/base
```

> **Critério de Aceite:**
> - `FAST_FORWARD : COMPATÍVEL`
> - `DEPENDENCIES : PASS`
> - `WEBUI_V2_DIST : PASS`
> - `STATUS : PREFLIGHT_PASS`

---

### Passo 4: Executar Atualização Segura de Produção (FF-Only)

Executa o backup automático do SQLite, para a Scheduled Task, aplica o avanço Git Fast-Forward, sincroniza dependências se necessário, inicia o motor V2 na porta 8080 e valida a saúde:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\update_production.ps1 -TargetRef origin/v2/base
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

### Passo 6: Resetar Voz Específica dos 3 Canais (Herdar Voz Global)

Na V1 legada, as vozes gravadas individualmente nos canais eram ignoradas e a voz global (Brian) era forçada pela UI. Na V2, o canal tem prioridade sobre a global. Para manter estritamente o comportamento homologado de produção, limpamos a voz dos 3 canais para herdarem a voz global:

```powershell
.\.venv\Scripts\python.exe -c "from app.services import profile_manager; target_channels = ['Dose Diária de Internet', 'Dose Diária de GTA VI', 'Dose Diária de Histórias']; profiles = profile_manager.list_profiles(); [profile_manager.update_profile_voice(p['id'], {'voice_name': None}) for p in profiles if p.get('name') in target_channels]; [print(f\"[VOZ_RESET] Canal '{p['name']}' -> voz efetiva: {profile_manager.get_effective_voice_settings(p['id'])['voice_name']['value']} (origem={profile_manager.get_effective_voice_settings(p['id'])['voice_name']['source']})\") for p in profiles if p.get('name') in target_channels]"
```

> **Critério de Aceite:** Os 3 canais devem exibir `origem=GLOBAL_UI` (ou `DEFAULT_APP`), com voz correspondente à configurada globalmente.

---

### Passo 7: Verificar Configuração do Canal Joana (TikTok)

Inspeciona e valida o status operacional e a voz efetiva do canal da Joana:

```powershell
.\.venv\Scripts\python.exe -c "from app.services import profile_manager; joana_profiles = [p for p in profile_manager.list_profiles() if 'joana' in p.get('name','').lower() or 'tiktok' in p.get('name','').lower()]; [print(f\"[JOANA_CHECK] Canal: '{p['name']}' (ID: {p['id']}) | Voz Efetiva: {profile_manager.get_effective_voice_settings(p['id'])['voice_name']['value']} (origem={profile_manager.get_effective_voice_settings(p['id'])['voice_name']['source']})\") for p in joana_profiles]"
```

> **Critério de Aceite:** O canal da Joana é listado com voz válida e identificada.

---

### Passo 8: Retomar a Fábrica de Vídeos

Restaura o estado operacional ativo da fábrica no Motor V2:

```powershell
.\.venv\Scripts\python.exe -c "from app.services import operator_console; operator_console.resume_factory(); print('Estado da Fábrica:', operator_console.get_factory_state())"
```

> **Critério de Aceite:** `Estado da Fábrica: RUNNING`.

---

### Passo 9: Diagnóstico Operacional Consolidado

Verifica a saúde completa do sistema pós-cutover:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\production_status.ps1
```

> **Critério de Aceite:**
> - `Instance Role : PRIMARY`
> - `Factory State : RUNNING`
> - `Readiness : READY`

---

## 3. Procedimento de Rollback Imediato (Contingência)

Caso ocorra qualquer anomalia crítica e seja necessário retornar imediatamente para a V1 (Streamlit 8501):

### Passo R1: Parar a Tarefa Agendada

```powershell
schtasks /End /TN "VideoFactory Production"
```

### Passo R2: Retornar ao Commit Anterior (Não-Destrutivo)

```powershell
git switch --detach <CURRENT_SHA_REGISTRADO_NO_PASSO_4>
```

### Passo R3: Iniciar Produção em Modo Legado V1 (Streamlit 8501)

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\start_production.ps1 -Legacy
```

### Passo R4: Validar Saúde do Streamlit

```powershell
Invoke-RestMethod -Uri "http://127.0.0.1:8501/_stcore/health"
```

> **Critério de Aceite:** Retorno com status 200 e conteúdo `ok`.
