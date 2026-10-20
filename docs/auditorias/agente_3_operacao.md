# RELATÓRIO DE AUDITORIA MULTIAGENTE — AGENTE 3 (OPERAÇÃO E PUBLICAÇÃO)

**Ambiente Auditado:** `C:\Projetos\MoneyPrinterTurbo-V1`  
**Fase / Gate Vigente:** `V1.5E` / `V1_CONTROLLED_QUIZ_SAFETY_GATE_PACKAGE_PREPARED`  
**Branch:** `fix/v1-quiz-safety-gate` (HEAD: `1c49249`)  
**Modo:** Somente Leitura (Read-Only) — Zero alterações em código, banco, Git ou ambiente de produção.

---

### ESCOPO_ANALISADO

Foram auditados de ponta a ponta os serviços e componentes do ciclo operacional e de publicação:
- `app/services/autonomous_production.py`: Máquina de estados autônoma (`disabled`, `idle`, `planning`, `generating`, `reviewing`, `scheduling`, `waiting_schedule`, `cooldown`, `blocked`, `error`), limites diários (24h), Circuit Breaker e gates de adoção.
- `app/services/scheduler.py`: Motor do Scheduler, planejamento de slots de postagem, cadência anti-burst, janelas móveis de 24h, execução de posts vencidos e reconciliação remota.
- `app/services/publishing_idempotency.py`: Camadas de proteção contra duplicatas (Criação/Agendamento, Scheduler Runtime e JIT Pré-Provider).
- `app/services/operator_console.py`: Governança de nó `PRIMARY`, controle global `RUNNING`/`PAUSED`, cancelamento seguro e telemetria de estoque canônico (`get_canonical_ready_stock`).
- `app/services/quality_recovery.py`: Fila de revisão de qualidade, persistência de decisões humanas em `operator_video_reviews` e overrides editoriais com score < 70.
- `webui/components/channel_factory.py`: Onboarding genérico de canais, vinculação de destinos (Post for Me) e alternância de produção autônoma.
- `webui/components/operator_console.py`: Painel visual de controle da fábrica e monitoramento do loop autônomo.
- `webui/Main.py`: Interface do agendador legado, seletores globais de Growth Mode e alternância de publicação.

---

### ANOMALIAS_COMPROVADAS

#### 1. Anulação de Aprovação Editorial Humana (REVIEW / Score < 70) pelo Scheduler
- **Comprovação no Código:**  
  - `quality_recovery.py` (L1034-1110) permite expressamente que um operador humano aprove um vídeo na faixa de `REVIEW` (score 55–69), registrando a decisão em `operator_video_reviews` com `decision = 'APPROVED'`, `approved_below_threshold = 1` e preservando o score factual em `content_quality_scores`.
  - `autonomous_production.py` (L2004-2021) reconhece essa aprovação em `_recover_waiting_task`:  
    `if not is_auto_quality_approved and not human_review: raise ValueError("waiting_quality_not_approved")`
  - **Porém**, ao planejar a agenda em `scheduler.py` (`plan_schedule`, L1165-1178):
    ```python
    q_row = conn.execute(
        "SELECT quality_score, quality_label FROM content_quality_scores "
        "WHERE task_id = ? ORDER BY created_at DESC, id DESC LIMIT 1", (task_id,)
    ).fetchone()
    if q_row:
        q_score = float(q_row["quality_score"])
        q_label = str(q_row["quality_label"]).upper()
        if (math.isfinite(q_score) and q_score < 70.0) or q_label in ("WEAK", "REVIEW", "REJECTED"):
            continue  # <-- BLOQUEIO CEGO: ignora operator_video_reviews
    ```
- **Impacto:** O agendador consulta **exclusivamente** `content_quality_scores` e ignora `operator_video_reviews`. Todo vídeo aprovado pelo operador abaixo de 70 é silenciosamente descartado pelo `plan_schedule`, anulando a decisão humana e impedindo a publicação.

---

#### 2. Contradição no Teto de Gerações Aprovadas no Modo `WARMUP`
- **Comprovação no Código:**  
  - `autonomous_production.py` (L321-322) documenta: `* WARMUP: approved cap = 2`. O documento canônico `docs/PROJECT_HANDOFF.md` (L73) reafirma: *"Warmup: 2 aprovados / 8 tentativas"*.
  - Contudo, na implementação factual em `autonomous_production.py` (L347-353):
    ```python
    gm = get_profile_growth_mode(clean_p, db_path=db_path)
    if gm == const.GROWTH_MODE_WARMUP:
        mode_cap = 5  # <-- DIVERGÊNCIA: fixado em 5, idêntico ao SCALE
        return min(parsed_stored, mode_cap) if parsed_stored is not None else mode_cap
    elif gm == const.GROWTH_MODE_SCALE:
        mode_cap = 5
    ```
- **Impacto:** Canais em aquecimento (`WARMUP`) podem aprovar até 5 vídeos em 24h em vez do teto seguro de 2, violando a política de proteção contra queima de contas novas.

---

#### 3. Inexistência de Autorização de Publicação Específica por Canal
- **Comprovação no Código:**  
  - Em `scheduler.py` (L1719), há apenas uma chave global `auto_publish_enabled` em `autopilot_settings`.
  - Na `channel_factory.py` (L248, L335), o checkbox `"Ativar produção automática imediatamente"` liga apenas a **geração autônoma de conteúdo** (`autonomous_mode_enabled:<profile_id>`).
  - No banco (`publishing_channels`), o canal possui apenas `is_enabled` (1 ou 0).
  - Em `scheduler.py` (L1739-1780), o `execute_due_posts` dispara qualquer post vencido cujo canal tenha `is_enabled == 1`.
- **Impacto:** Não existe autorização isolada de *auto-publicação* por canal. Se a flag global `auto_publish_enabled` for ativada no Scheduler, **todos** os canais cadastrados com destino conectado publicarão automaticamente, impossibilitando manter um canal apenas em modo "estoque" enquanto outro publica.

---

#### 4. Falta de Escopo por Canal em `publishing_idempotency.py` (Risco de Cancelamento Cruzado)
- **Comprovação no Código:**  
  - O índice único de `scheduled_posts` em `scheduler.py` (L91-95) contempla canal: `(task_id, COALESCE(channel_id, ''), platform)`.
  - No entanto, `publishing_idempotency.py` (L47-49, L98-99, L279-284) executa queries restritas a `task_id = ? AND platform = ?`.
  - Na função `neutralize_duplicate_executable_posts` (L279):
    ```sql
    SELECT id, status, channel_id FROM scheduled_posts
    WHERE task_id = ? AND platform = ? AND id != ?
      AND status IN ('planned', 'ready');
    ```
- **Impacto:** Se o sistema distribuir o mesmo asset para dois canais do YouTube distintos (ex.: canal principal e canal secundário), o segundo agendamento será cancelado compulsoriamente como "duplicata redundante".

---

#### 5. Interface Contraditória de Growth Mode em `Main.py` (Global vs Per-Profile)
- **Comprovação no Código:**  
  - `Main.py` (L8055-8066) expõe seletor que chama `scheduler.set_growth_mode`, alterando apenas a chave global em `autopilot_settings`.
  - No entanto, `scheduler.py` (`get_platform_rate_limits`, L662-668) e `autonomous_production.py` (L221-244) priorizam o Growth Mode persistido no perfil (`content_profiles.growth_mode`).
  - Além disso, `Main.py` (L8071-8072) invoca `get_platform_rate_limits` sem `profile_id`.
- **Impacto:** A tela do Streamlit exibe métricas, slots e limites da baseline global/default, induzindo o operador a erro ao não refletir o estado real de canais configurados em outros modos (ex.: perfil em `SCALE` exibindo dados de `WARMUP`).

---

#### 6. Descarte Sumário de Tarefas em `REVIEW` pelo Loop Autônomo sem Encaminhamento
- **Comprovação no Código:**  
  - Em `autonomous_production.py` (L1505-1513, L2390-2428), vídeos gerados com score entre 55 e 69 são reprovados diretamente por `evaluate_completed_task_gates`.
  - O ciclo incrementa `consecutive_rejections`, grava `gate_status="rejected"` e descarta a tarefa.
- **Impacto:** A tarefa não é direcionada para uma fila explícita de revisão humana no loop autônomo. Rejeições consecutivas de temas promissores somam para o Circuit Breaker (`consecutive_rejections >= 10`), bloqueando a fábrica sem oportunidade de triagem pelo operador.

---

#### 7. Tipagem Inconsistente de Ready Stock entre Módulos
- **Comprovação no Código:**  
  - `operator_console.py` (`get_canonical_ready_stock`, L1505-1535) retorna um `dict` com breakdown.
  - Em `channel_factory.py` (L43-49), o valor é extraído e armazenado como `int`.
  - No renderizador dos cards (L565), o código volta a tratá-lo como `dict`:  
    `ready_val = card["ready_stock"].get("total_ready", 0) if isinstance(card.get("ready_stock"), dict) else (card.get("ready_stock") or 0)`
- **Impacto:** Evidência de código defensivo redundante decorrente da falta de um contrato de dados padronizado entre os serviços e as UIs.

---

### FONTE_DE_VERDADE_CANONICA_PROPOSTA

Para eliminar ambiguidades e decisões conflitantes:

1. **Estado Macro e Lock de Instância:**  
   - `operator_console.py`: tabela `instance_locks` (nó `PRIMARY`) e `autopilot_settings.factory_state` (`RUNNING`/`PAUSED`).
2. **Growth Mode:**  
   - Tabela `content_profiles.growth_mode` (ou `profile_settings.schedule`) por canal. A chave global `growth_mode` em `autopilot_settings` deve ser tratada exclusivamente como fallback para canais sem perfil customizado.
3. **Autorização Efetiva de Publicação (Contrato de 3 Chaves):**  
   - *Chave 1 (Master Switch Global):* `autopilot_settings.auto_publish_enabled == "true"` (trava-geral de segurança da fábrica).  
   - *Chave 2 (Habilitação do Canal):* `publishing_channels.is_enabled == 1`.  
   - *Chave 3 (Autorização Específica de Auto-Publicação):* Nova flag explícita `auto_publish_authorized == 1` no canal/perfil (desacoplada da geração autônoma de estoque).
4. **Soberania de Gates e Overrides:**  
   - `operator_video_reviews` deve prevalecer formalmente sobre `content_quality_scores` quando houver decisão `APPROVED` auditada por operador humano.
5. **Idempotência de Agendamento:**  
   - A tupla soberana de unicidade deve ser obrigatoriamente `(task_id, platform, channel_id)`.

---

### INTERSECOES_COM_OUTROS_AGENTES

- **Com Parâmetros do Agente 1 (Roteirização e Onboarding de Canal):**  
  - O Agente 3 consome: `video_format`, `topic_brief`, `niche`, `voice_name`, `closing_type`, `num_questions`, contas vinculadas (`external_account_id`, `project_id`) e horários (`publish_start_hour`, `publish_end_hour`).  
  - *Gap identificado:* O modelo `ChannelWorkspaceSettings.automation` não possui campo para autorizar publicação individual, configurando apenas a geração (`autonomous_enabled`).
- **Com Resultados do Agente 2 (Geração de Mídia e Quality/Safety Gates):**  
  - O Agente 3 consome: integridade de `final-1.mp4`, `safety_status` de `monetization_safety`, `quality_score` de `content_quality_scores` e `copyright_gate`.  
  - *Gap identificado:* Ruptura no tratamento de `REVIEW`: o Agente 2 classifica tarefas de score 55–69 como elegíveis para revisão, mas o Agente 3 rejeita compulsoriamente no loop autônomo e ignora o override humano no agendamento.

---

### RECOMENDACAO_MINIMA

1. **Reconhecer `operator_video_reviews` em `scheduler.plan_schedule`:**  
   Antes de descartar tarefas com score < 70 em `scheduler.py` (L1165-1178), verificar se há registro `decision = 'APPROVED'` em `operator_video_reviews`.
2. **Corrigir Teto de WARMUP em `autonomous_production.py`:**  
   Ajustar `autonomous_production.py` (L348) de `mode_cap = 5` para `mode_cap = 2`, restaurando a conformidade com a docstring e com o `PROJECT_HANDOFF.md`.
3. **Escopar Idempotência por Canal:**  
   Adicionar `channel_id` às checagens de `publishing_idempotency.py`, alinhando ao índice `idx_active_schedule_v2` do SQLite.
4. **Implementar Autorização Específica de Auto-Publicação por Canal:**  
   Adicionar flag individual no canal/perfil para que a ativação da flag global `auto_publish_enabled` não publique canais criados estritamente para produção de estoque.
5. **Triagem de `REVIEW` no Loop Autônomo:**  
   Encaminhar vídeos de score 55–69 para estado de espera de revisão (`waiting_review`) em vez de penalizar o Circuit Breaker de rejeições consecutivas.

---

**Arquivos alterados:** Nenhum (auditoria estritamente em modo leitura).  
**Testes executados:** Nenhum comando destrutivo ou de geração acionado.  
**Próximo Gate Seguro:** `V1_CONTROLLED_QUIZ_SAFETY_GATE_PACKAGE_PREPARED` (homologação controlada pelo operador humano no PC Forte).
