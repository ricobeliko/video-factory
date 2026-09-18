# Acesso Remoto Seguro e Governança de Instância Única (V8.1)

Este documento descreve a arquitetura de operação remota da **Video Factory**, permitindo acessar o sistema a partir de outros computadores, notebooks ou celulares de forma segura, garantindo que **apenas um único computador (o PC Forte)** execute tarefas pesadas, workers e publicações.

---

## 1. Arquitetura Operacional Centralizada

```
[ Notebook / Celular / Tablet ] (Apenas Navegador Web)
             │
             │ HTTP / WebSocket seguro (Porta 8501)
             │ (Via LAN ou Tailscale VPN WireGuard)
             ▼
┌────────────────────────────────────────────────────────┐
│ PC FORTE (Nó PRIMARY)                                   │
│  - Streamlit WebUI (ligado em 0.0.0.0:8501)             │
│  - Banco Oficial SQLite (storage/video_factory.db)      │
│  - Generation Worker (LLM, TTS, FFmpeg Render)          │
│  - Scheduler Worker & Auto-Publish                      │
│  - Trend Radar & Analytics                              │
│  - Armazenamento local de vídeos gerados                │
└────────────────────────────────────────────────────────┘
```

### Princípios de Segurança Fundamentais:
1. **Zero Exposição Direta de Banco de Dados:** Clientes remotos **nunca** acessam o SQLite diretamente. A comunicação ocorre exclusivamente através da camada de apresentação do Streamlit (HTTP/WebSocket).
2. **Sem Port Forwarding no Roteador / Sem UPnP:** Nenhuma porta do roteador residencial/empresarial deve ser aberta para a Internet pública.
3. **Sem Credenciais em Trânsito Aberto:** Todo acesso fora da rede local é recomendado via VPN ponto-a-ponto (Tailscale).

---

## 2. Configuração de Rede

### 2.1 Servidor Streamlit (`webui/.streamlit/config.toml`)
A configuração da WebUI está configurada para aceitar conexões das interfaces de rede da máquina:

```toml
[server]
address = "0.0.0.0"
port = 8501
headless = true
enableCORS = false
enableXsrfProtection = true
```

> **Aviso de Segurança:** Configurar `address = "0.0.0.0"` apenas instrui o processo Python a escutar em todas as interfaces de rede locais (Loopback, Ethernet/Wi-Fi local e interface virtual do Tailscale). Isso **não** abre portas no seu roteador, **não** usa UPnP e **não** altera regras de firewall externo.

---

## 3. Modos de Acesso Remoto

### Modo A: Acesso na Rede Local (LAN / Wi-Fi de Casa ou Escritório)
Ideal quando o notebook/celular está conectado na mesma rede Wi-Fi que o PC Forte.

1. No **PC Forte**, abra o PowerShell ou Prompt de Comando e descubra o IP local:
   ```powershell
   ipconfig
   ```
   Localize o campo `Endereço IPv4` (exemplo: `192.168.1.105`).

2. No **dispositivo remoto** (notebook, tablet ou celular), abra o navegador:
   ```text
   http://192.168.1.105:8501
   ```

3. Pronto! A interface da Video Factory carregará diretamente no navegador do dispositivo remoto.

---

### Modo B: Acesso Externo Seguro via Tailscale (Recomendado)
Ideal para acessar a fábrica de qualquer lugar (cafés, viagens, 4G/5G) sem abrir portas no roteador nem configurar IP dinâmico/DDNS.

#### O que é o Tailscale?
O [Tailscale](https://tailscale.com/) cria uma rede privada virtual (VPN mesh) criptografada de ponta a ponta com o protocolo WireGuard. Seus dispositivos recebem IPs virtuais seguros (ex: `100.x.y.z`) acessíveis apenas por você.

#### Passo a Passo de Uso:
1. **No PC Forte:**
   - Instale o aplicativo oficial do Tailscale (Windows).
   - Faça login com sua conta (Google, GitHub ou Microsoft).
   - O Tailscale atribuirá um IP virtual à máquina (exemplo: `100.85.120.35`).

2. **No seu Notebook / Celular:**
   - Instale o Tailscale (disponível para Windows, macOS, Linux, iOS e Android).
   - Faça login com **a mesma conta**.

3. **Conexão:**
   - No dispositivo remoto, acesse no navegador:
     ```text
     http://100.85.120.35:8501
     ```
   - O tráfego trafega 100% criptografado de ponta a ponta, sem intermediários e sem tocar em portas públicas da Internet.

---

## 4. Governança de Instância Única & Proteção contra Split-Brain

Para impedir acidentes operacionais (como dois processos executando workers ao mesmo tempo sobre a mesma pasta ou banco):

### Papéis do Nó
- **PRIMARY:**
  - Adquire o lock oficial na tabela `instance_locks` do SQLite (`lock_key = 'PRIMARY_FACTORY'`).
  - Executa o heartbeat daemon a cada 15 segundos.
  - Executa workers de geração, ciclos do Scheduler e publicações automáticas/manuais.
  - Permite controle total na WebUI (pausa, retomada, parada de emergência, cancelamento e reexecução).

- **SECONDARY_VIEW_ONLY:**
  - Se um segundo processo da Video Factory for iniciado enquanto o PRIMARY estiver ativo e saudável, ele detecta o lock existente e entra automaticamente no modo **VIEW ONLY**.
  - **Bloqueio no Backend:** Qualquer tentativa de chamar `submit_generation()`, `publish_task()`, `pause_factory()`, `resume_factory()`, `request_task_cancel()`, `reexecute_task()` ou `reconcile_orphaned_tasks()` é interceptada pelo guard `require_primary_instance()` e bloqueada com `PermissionError`.
  - **Interface Informativa:** Exibe banner persistente de aviso e o **Node Bar** no Operator Console, com botões de mutação visualmente desabilitados.
  - Permite consulta em tempo real: acompanhamento de filas, estoque pronto, saúde de provedores, telemetrias e timeline operacional.

### Atomicidade no SQLite (Takeover Concorrente Seguro)
Se o nó primário sofrer uma queda abrupta (queda de energia ou encerramento forçado do processo):
- O heartbeat expira após o timeout de 90 segundos.
- Se duas instâncias secundárias detectarem o lock stale simultaneamente, o takeover ocorre via **UPDATE condicional atômico** no SQLite:
  ```sql
  UPDATE instance_locks
  SET node_id = ?, hostname = ?, pid = ?, last_heartbeat = ?, role = 'ROLE_PRIMARY', status = 'ACTIVE'
  WHERE lock_key = 'PRIMARY_FACTORY' AND last_heartbeat = ?;
  ```
- **Apenas a primeira transação a comitar afeta 1 linha (`rowcount == 1`) e vira PRIMARY.**
- A instância perdedora da corrida obtém `rowcount == 0` e entra imediatamente em `SECONDARY_VIEW_ONLY`, eliminando completamente a chance de duas instâncias disputarem o comando.

### Sessões Streamlit vs Estado de Processo
- Abrir novas abas, novas janelas de navegador ou múltiplos clientes conectados à mesma WebUI **não** reinicia locks nem duplica threads de background.
- O estado da instância é governado por um singleton de módulo protegido por `threading.RLock()` e refletido no SQLite.
