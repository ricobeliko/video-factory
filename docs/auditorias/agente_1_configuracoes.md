# RELATÓRIO DE AUDITORIA MULTIAGENTE — AGENTE 1: CONFIGURAÇÕES E CONTRATOS

**Projeto:** `C:\Projetos\MoneyPrinterTurbo-V1`  
**Fase Atual:** `V1.5E` / Hotfix isolado `v1-quiz-safety-gate`  
**Modo:** Somente Leitura / Auditoria Analítica (sem modificações em código, Git ou banco).

---

## 1. ESCOPO_ANALISADO

Auditoria realizada de ponta a ponta no ciclo de configuração, serialização, despacho e herança de parâmetros da Video Factory V1:

1. **Definições e Persistência do Perfil:**
   - Tabela SQLite [`content_profiles`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L153-L195) e coluna `settings_json`.
   - Modelos Pydantic tipados em [`app/services/profile_manager.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L44-L118) ([`EditorialSettings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L44-L50), [`VoiceSettings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L52-L56), [`VisualSettings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L58-L64), [`SubtitleSettings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L66-L69), [`ChannelWorkspaceSettings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L96-L125)).
   - Funções de contexto operacional [`get_generation_profile_context`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L1368-L1463) e vinculação de tarefas [`save_task_profile`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L1465-L1478).
2. **Contrato Canônico de Tarefa:**
   - Modelo Pydantic [`VideoParams`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L92-L205) em [`app/models/schema.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py).
3. **Entradas Operacionais:**
   - **Entrada Manual (WebUI):** [`webui/Main.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/Main.py#L5177-L5310) ([`_render_script_settings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/Main.py#L5177-L5310), [`_render_audio_settings`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/Main.py#L6840-L7130), submissão nas linhas 9756 e 9880) e [`webui/components/channel_factory.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/components/channel_factory.py#L595-L735).
   - **Entrada Autônoma (Autopilot):** [`app/services/autonomous_production.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L1600-L1845) ([`build_autonomous_video_params`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L1600-L1845), submissão na linha 2922).
4. **Despacho e Roteamento:**
   - [`app/services/webui_task.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/webui_task.py#L135-L215) ([`submit_generation`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/webui_task.py#L135-L215) e [`_run_generation`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/webui_task.py#L54-L105)).
   - Roteamento e consumo em [`app/services/task.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L3218-L3255) (start de tarefa, pipeline de quiz e materiais/Flow), [`app/services/llm.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/llm.py#L700-L786), [`app/services/quiz_generator.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/quiz_generator.py#L425-L530) e [`app/services/quiz_safety_gate.py`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/quiz_safety_gate.py#L60-L120).

---

## 2. ANOMALIAS_COMPROVADAS

### 2.1 Defeitos Reais (Quebras Funcionais e Perdas de Contrato)

#### A. Dicotomia `video_format` vs `narrative_structure` e Quebra de Tipos
- **Definição:** `EditorialSettings.video_format` ([`profile_manager.py:47`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L47)) armazena o formato do perfil, aceitando na UI [`channel_factory.py:16`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/components/channel_factory.py#L16) apenas `["traditional", "quiz_dilemma", "quiz_paper"]`.
- **Conflito:** No modelo canônico de execução [`VideoParams`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L181), o campo `video_format` **não existe**. Existe apenas `narrative_structure: Optional[str] = None`.
- **Perda/Comportamento Anômalo:**
  - Em [`webui/Main.py:5275-5290`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/Main.py#L5275-L5290), a interface tenta ler `prof_struct_default = manual_prof_ctx.get("video_format") or "auto"`. Como `"traditional"` não pertence a `const.NARRATIVE_STRUCTURES` ([`const.py:61-69`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/const.py#L61-L69)), o seletor cai forçado em `"auto"`.
  - Se o operador deixa `"auto"`, o objeto é enviado com `params.narrative_structure = None`.
  - Em [`task.py:3229-3238`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L3229-L3238), ao resolver o fallback, o código executa `if p_format not in ("traditional", "standard", "auto", "")`. Resultado: `"traditional"` é descartado e `params.narrative_structure` permanece vazio (`""`), impedindo canais tradicionais de declararem subestruturas narrativas (ex: `investigative_mystery`, `explainer`).

#### B. Amnésia de Configurações do Perfil na Submissão Manual ([`webui_task.py:submit_generation`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/webui_task.py#L165-L195))
- **Ocorrência:** Quando uma tarefa é despachada na WebUI, `submit_generation` consulta `ctx = profile_manager.get_generation_profile_context(assigned_profile_id)`.
- **Conflito:** O método faz a cópia de fallback **somente de 4 campos**: `niche`, `video_language`, `region` e `monetization_preset`.
- **Parâmetros Perdidos:**
  - `visual_director_enabled` (permanece `False` de [`schema.py:191`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L191))
  - `flow_enabled` (permanece `False` de [`schema.py:193`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L193))
  - `visual_style_brief` (permanece `""` de [`schema.py:192`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L192))
  - `flow_scene_count` (permanece `6`)
  - `topic_brief` (permanece `None`)
  - `closing_type` (permanece `None`)
  - `num_questions` (permanece `None`)
  - `subtitle_position` / `font_size` / `music_*`
- **Impacto Comprovado:** Mesmo que um canal tenha `flow_enabled: True` e `visual_director_enabled: True` configurados no banco, ao gerar vídeo manualmente pela WebUI, `task.py:3477` lê `getattr(params, "flow_enabled", False) == False`, ignorando silenciosamente o Google Flow e o Visual Director.

#### C. `topic_brief` Ausente na Geração de Roteiro Traditional/Quiz
- **Ocorrência:** O campo é salvo no perfil ([`profile_manager.py:45`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L45)) e existe em `VideoParams.topic_brief` ([`schema.py:187`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/models/schema.py#L187)).
- **Conflito:** Na entrada autônoma, `topic_brief` é injetado no prompt de ideação de tópicos ([`autopilot.py:73-89`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autopilot.py#L73-L89)). Contudo, na hora de escrever o roteiro:
  - [`task.py:320-335`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L320-L335) (`generate_script`) não repassa `topic_brief` ao LLM.
  - [`llm.py:761-786`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/llm.py#L761-L786) (`generate_script`) e [`llm.py:700-760`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/llm.py#L700-L760) (`build_script_prompt`) **não possuem o parâmetro `topic_brief`**.
- **Impacto:** O brief editorial temático do canal é 100% descartado durante a elaboração do texto do roteiro pelo LLM tradicional e pelo pipeline de Quiz.

#### D. Desalinhamento de `closing_type` e Divergência de `num_questions`
- **Ocorrência em `closing_type`:**
  - [`channel_factory.py:635`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/components/channel_factory.py#L635) e [`webui/Main.py:5302`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/Main.py#L5302) gravam/atribuem `closing_type = "comments"` para `quiz_paper`.
  - Em [`quiz_generator.py:431-525`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/quiz_generator.py#L425-L525) (`_apply_channel_closing`), os únicos valores tratados são `"quiz_choice_religious"`, `"score_challenge"` e `"engagement_cta"`.
  - O valor `"comments"` não existe nos condicionais e cai silenciosamente no `else` ([`quiz_generator.py:497`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/quiz_generator.py#L497)), gerando encerramento com CTA de "seguir o perfil" em vez de incentivo a comentários.
- **Ocorrência em `num_questions`:**
  - [`channel_factory.py:636`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/components/channel_factory.py#L636) fixa `num_questions = 5` para o padrão P1.3 de papel.
  - Em [`task.py:2755`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L2755), se `params.num_questions` for nulo, a linha define `num_questions = 10 if is_paper_quiz else ...`. Há divergência entre o fallback do backend (10) e a regra cadastrada no canal (5).

---

### 2.2 Redundâncias Inofensivas e Código Morto Pontual

1. **Precedência de Voz e Bypass do Perfil:**
   - Em [`profile_manager.py:1388-1398`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L1388-L1398), a voz é resolvida como `global_voice or profile_voice or fallback_voice`.
   - Como `config.ui["voice_name"]` é sempre preenchido via UI ou `config.toml`, `settings.voice.voice_name` de cada perfil no SQLite nunca é utilizado na prática.
   - *Status:* Trata-se de uma redundância decorrente da decisão de arquitetura da "Voz Global da Fábrica" ([`channel_factory.py:438`](file:///c:/Projetos/MoneyPrinterTurbo-V1/webui/components/channel_factory.py#L438)). Não quebra a geração, mas torna os campos `VoiceSettings` do perfil inertes.
2. **Consulta a `video_source` no Contexto do Perfil:**
   - Em [`autonomous_production.py:1633`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L1633), há `raw_source = ctx.get("video_source") or config.app.get("video_source", "pexels")`.
   - Como `profile_manager.py` não armazena nem retorna `video_source` em `ctx`, o primeiro termo é código morto inofensivo; a resolução cai imediatamente em `config.app`.
3. **Persistência Imutável `task_profiles`:**
   - [`profile_manager.save_task_profile`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/profile_manager.py#L1465-L1478) registra `task_id <-> profile_id`. A tabela é redundante com o `profile_id` já armazenado em `sm.state`, mas serve como garantia de isolamento factual nos gates.

---

## 3. FONTE_DE_VERDADE_CANONICA_PROPOSTA

Para eliminar perdas de estado entre UI, perfis e o executor de tarefas, a cadeia de precedência deve ser estrita:

```
[Definição Cadastral do Canal]
content_profiles (SQLite) + settings_json (ChannelWorkspaceSettings)
       │
       ▼
[Provedor de Contexto do Perfil]
profile_manager.get_generation_profile_context(pid)
       │
       ▼
[Contrato de Execução Canônico e Imutável]
VideoParams (schema.py)
       │
       ▼
[Pipeline de Geração & Quality Gates]
task.py (tm.start)
```

### Regras de Precedência Propostas:
1. **Configurações Editoriais e de Formato:**
   - Fonte primária: `content_profiles.settings_json` (via `profile_manager`).
   - Mapeamento direto em `VideoParams`: Unificar `video_format` e `narrative_structure` para eliminar traduções ad-hoc.
2. **Propagação em `webui_task.py:submit_generation`:**
   - Deixar de ser um despachante passivo que só propaga 4 campos. Deve atuar como hidratador contratual:
     $$\text{Valor Efetivo} = \text{Input Explícito da UI} \succ \text{Contexto do Perfil (ctx)} \succ \text{Defaults Seguros Globais}$$
   - Se o operador não alterar parâmetros avançados (Flow, Visual Director, Briefs), esses devem vir obrigatoriamente de `ctx`.

---

## 4. INTERSECOES_COM_OUTROS_AGENTES

### Dependências para o AGENTE 2 (Roteiro, Prompts, LLM e Quiz Content)
1. **Consumo de `topic_brief`:** O Agente 2 depende de que o Agente 1 garanta o tráfego de `topic_brief` até `llm.py:build_script_prompt` para que o roteiro respeite as diretrizes de nicho do canal.
2. **Normalização de `closing_type`:** O Agente 2 deve ser informado de que o gerador de quiz não reconhece `"comments"`. Agente 2 precisa ajustar os prompts e o `QuizContentGenerator` para contemplar essa intenção ou padronizar em `"score_challenge"`.
3. **Resolução de Estrutura:** Agente 2 necessita saber se a chave de governança editorial será `narrative_structure` ou `video_format`.

### Dependências para o AGENTE 3 (Pipeline de Execução, Google Flow, Mídia e Assembly)
1. **Desbloqueio do Google Flow Manual:** O Agente 3 não consegue validar o fluxo integrado do Google Flow na WebUI enquanto `webui_task.py` estiver zerando `flow_enabled` e `visual_director_enabled`.
2. **Propagação de `visual_style_brief`:** A geração visual do Flow depende de `visual_style_brief` (usado em `flow_bridge.py` e `visual_director.py`). A perda desse parâmetro na submissão manual degrada a qualidade do prompt visual para o valor genérico `"cinematic"`.
3. **Estabilidade de `voice_name`:** Agente 3 necessita que a voz canonicalizada chegue limpa até o serviço de áudio/TTS sem discrepâncias entre o canal e a UI.

---

## 5. RECOMENDACAO_MINIMA

1. **Atualizar `webui_task.py:submit_generation`:**
   Incluir o repasse dos campos ausentes de `ctx` para `task_params` (`flow_enabled`, `visual_director_enabled`, `visual_style_brief`, `flow_scene_count`, `topic_brief`, `closing_type`, `num_questions`) caso não tenham sido preenchidos explicitamente na chamada.
2. **Alinhar o Contrato em `VideoParams` (`schema.py`):**
   Adicionar `video_format: Optional[str] = None` em `VideoParams` como alias ou campo de primeira classe para evitar conversões indiretas para `narrative_structure`.
3. **Corrigir o Literal de Encerramento no Quiz:**
   Substituir o literal `"comments"` em `channel_factory.py` e `webui/Main.py` pelo tipo canônico suportado pelo gerador (`"score_challenge"` ou `"engagement_cta"`), ou adicionar a cláusula `elif closing_type == "comments"` em [`quiz_generator.py:431`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/quiz_generator.py#L431).
4. **Repassar `topic_brief` ao Prompt do Roteiro:**
   Adicionar `topic_brief` na assinatura e montagem do prompt em [`llm.py:build_script_prompt`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/llm.py#L700-L760) e em [`task.py:generate_script`](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L320-L335).

---
*Nenhuma modificação de código ou execução invasiva foi realizada.*
