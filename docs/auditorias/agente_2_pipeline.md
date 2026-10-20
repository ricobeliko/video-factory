# RELATÓRIO DE AUDITORIA MULTIAGENTE — AGENTE 2 (PIPELINE E QUALIDADE)

**Projeto:** `C:\Projetos\MoneyPrinterTurbo-V1`  
**Data da Auditoria:** 19/10/2026  
**Fase de Referência:** V1.5E / Q0-R / Q5-B2A.1  
**Diretiva:** Auditoria estritamente analítica (read-only, zero mutação de código, banco, Git ou produção).

---

## 1. ESCOPO ANALISADO

Mapeamento de ponta a ponta desde o preenchimento de `VideoParams` até a entrega final em `READY_STOCK`:
1. **Entrada e Orquestração Geral:** `app/services/task.py` (`_run_pipeline`, `_run_quiz_pipeline`, preflights, checkpoints).
2. **Geração de Roteiro e Encerramentos:** `app/services/quiz_generator.py` (`QuizContentGenerator`, `_apply_channel_closing`, `_generate_fallback_content`, `export_to_quiz_config`, `export_to_paper_quiz_config`).
3. **Integração com LLM:** `app/services/llm.py` (`_generate_response`, prompts de roteiro e governança).
4. **Engines de Renderização:**
   - Quiz Dilema: `scripts/poc_quiz_render.py` (`QuizEngine`, `render_async`, `ensure_images`).
   - Quiz Papel: `scripts/poc_quiz_paper_render.py` (`PaperQuizEngine`, `select_questions_for_target_duration`).
   - Tradicional: `app/services/video.py` e rotinas MoviePy/FFmpeg de `task.py`.
5. **Portais de Segurança (Safety Gates):**
   - `app/services/quiz_safety_gate.py` (`is_quiz_dilemma`, `evaluate_quiz_script_safety`, `evaluate_quiz_duration_safety`, `quiz_safety_history`).
   - `app/services/safety_gate.py` (`evaluate_script_safety`, `monetization_safety`).
6. **Portais de Qualidade e Mídia (Quality Gates):**
   - `app/services/media_quality.py` (`evaluate_final_media_quality`).
   - `app/services/quality_score.py` (`evaluate_quality`, `evaluate_pre_generation_editorial_quality`).
   - `app/services/quality_recovery.py` e consumo operacional em `app/services/autonomous_production.py`.

---

## 2. ANOMALIAS COMPROVADAS

### A. Defeitos Reais (Impacto Funcional / Bloqueios Operacionais)

#### 1. Falso-Bloqueio em Media Quality por Falta de Arquivo de Legenda no Quiz
- **Código:** `app/services/task.py` (linhas 3017-3028) vs `app/services/media_quality.py` (linhas 420-422) vs `app/services/autonomous_production.py` (linhas 1812-1813).
- **Evidência:** No modo autônomo, `VideoParams` recebe `subtitle_required=True` e `final_media_quality_required=True`. O Quiz Engine renderiza cards visuais com Pillow diretamente nos frames do vídeo e **não gera arquivo `subtitle.srt`**. Em `task.py` (linha 3018), `evaluate_final_media_quality` é chamado com `subtitle_path=None`. Em `media_quality.py` (linhas 420-422), a checagem `if not subtitle_path or not os.path.isfile(subtitle_path)` dispara `SUBTITLE_ARTIFACT_MISSING`, retornando `status="BLOCK"` e abortando a tarefa com `_mark_task_failed(..., "final_media_quality")` após renderização completa.

#### 2. Ausência de `is_closing_choice=True` na Cena Religiosa Gerando Colisão no Safety Gate e Bloqueio Fatal no Factual Gate
- **Código:** `app/services/quiz_generator.py` (linhas 431-457), `app/services/quiz_safety_gate.py` (linhas 371-376) e `app/services/task.py` (linhas 2856-2876).
- **Evidência:**
  - Quando `closing_type == "quiz_choice_religious"`, a penúltima pergunta (`questions[-2]`, "Ficar dois dias sem internet... Jesus te ama?") é mutada, mas **não recebe `penult_q["is_closing_choice"] = True`** (apenas a última `questions[-1]` recebe na linha 457).
  - Em `quiz_safety_gate.py` (linhas 371-376), a lista de palavras-chave busca `comentários`, `inscreva`, `pontuação`, `desafio`, `fechamento`, `comente`. A narração contém `"comentar"` e o cabeçalho é `"ESCOLHA RÁPIDO:"`. Logo, `is_closing` resulta `False`. A cena religiosa é contabilizada como dilema ativo de conteúdo em todos os vídeos do canal, inflando artificialmente o índice de similaridade contra vídeos anteriores.
  - Se associada a quiz factual, em `task.py` (linhas 2858-2860), `questions[-2]` não é ignorada por `is_closing_choice` nem possui `verified=True`, caindo em `unverified` e disparando bloqueio compulsório no `Factual Safety Check`.

#### 3. Incompatibilidade da Janela de Duração entre `QuizConfig` e `task.py`
- **Código:** `app/services/quiz_generator.py` (linha 914) e `scripts/poc_quiz_render.py` (linha 69) vs `app/services/task.py` (linhas 2983-2990).
- **Evidência:** `QuizConfig` define como meta editorial `target_duration_range = [62.0, 66.0]`. Em contrapartida, `task.py` (linha 2983) aplica um gate rígido de `[60.0s, 65.0s]`: `if actual_duration < 60.0 or actual_duration > 65.0: return _mark_task_failed(...)`. Um vídeo renderizado com 65.4s (válido perante o QuizConfig) é sumariamente rejeitado pelo Quality Gate em `task.py`.

#### 4. Voz Hardcoded no Quiz Dilema Ignora Perfil e Configuração Global
- **Código:** `app/services/quiz_generator.py` (linhas 923-926) e `app/services/task.py` (linhas 2966-2973).
- **Evidência:** `export_to_quiz_config` não aceita parâmetro de voz e fixa no JSON serializado `"voice_name": "pt-BR-AntonioNeural"`, `"voice_rate": "+12%"`. O parâmetro `params.voice_name` (ou voz configurada no perfil do canal) é completamente ignorado durante a síntese de narração do quiz de dilemas.

#### 5. Limbo Operacional / "Estoque Fantasma" para Tarefas com `SAFETY_STATUS_REVIEW`
- **Código:** `app/services/task.py` (linhas 2844, 3067), `app/services/autonomous_production.py` (linhas 607, 1448) e `app/services/quality_recovery.py` (linhas 535, 1021).
- **Evidência:** `_run_quiz_pipeline` só bloqueia a geração se o Safety Gate retornar `BLOCK`. Se retornar `REVIEW`, o pipeline gera o vídeo MP4 e marca o estágio final como `READY_STOCK` (linha 3071). Porém:
  - `autonomous_production.py` exige `safety_status = 'PASS'` para contar o estoque (linha 607) e rejeita o ciclo (linha 1448).
  - `scheduler.py` (linha 1161) ignora a tarefa para publicação automática.
  - `quality_recovery.py` (linhas 535, 1021) proíbe estritamente a recuperação de vídeos com `safety_status != PASS`.  
  Resultado: O vídeo consome processamento, é marcado como concluído, mas fica retido para sempre sem possibilidade de publicação ou recuperação.

---

### B. Redundâncias Inofensivas e Sobrescritas Sem Dano Crítico

#### 1. Download Redundante de Imagens em `QuizEngine.ensure_images`
- **Código:** `app/services/task.py` (linha 2908) e `scripts/poc_quiz_render.py` (linhas 238-240, 752).
- **Evidência:** `task.py` invoca `QuizAssetManager.process_quiz()`, que baixa ou gera todas as imagens em `task_dir/images`. Dentro de `QuizEngine.render_async()`, a função `self.ensure_images()` é executada novamente. Contudo, `_fetch_or_fallback` verifica `os.path.exists(dest_path) and os.path.getsize(dest_path) > 1000` e retorna imediatamente. Não consome cota do Pexels nem gera I/O destrutivo.

#### 2. Resolução Dupla de `is_quiz_dilemma` no Roteamento
- **Código:** `app/services/task.py` (linhas 3241-3246).
- **Evidência:** `if str(narrative_structure).startswith("quiz") or quiz_safety_gate.is_quiz_dilemma(...)`. Como `is_quiz_dilemma` já contempla variantes `quiz*`, a checagem com `startswith` é redundante, mas preserva a compatibilidade com presets herdados.

#### 3. Injeção da Cena Religiosa no Fallback Estático
- **Código:** `app/services/quiz_generator.py` (linhas 821-841).
- **Evidência:** `_generate_fallback_content` define `q7` estaticamente como dilema religioso. Se o LLM falhar para um quiz onde `closing_type == "engagement_cta"`, a rotina `_apply_channel_closing` sobrescreve apenas `q8`, deixando `q7` com a opção religiosa. Trata-se de uma contaminação de contexto temático quando ocorre fallback total de LLM em nichos neutros.

---

### C. Comprovação Específica: Preservação da Cena Religiosa (`closing_type=quiz_choice_religious`)

| Etapa do Pipeline | Status | Ocorrência no Código |
|---|---|---|
| **1. Resolução do parâmetro** | **Construída** | `autonomous_production.py` (L1629) / `task.py` (L2746-L2750). Se não fornecido em `params`, infere por keywords no nicho (`religi`, `jesus`, etc.). |
| **2. Injeção no roteiro estruturado** | **Construída** | `quiz_generator.py` (L431-L454) aplica em `questions[-2]`: "Ficar dois dias sem internet... Jesus te ama?". |
| **3. Avaliação no Safety Gate** | **Anômala** | `quiz_safety_gate.py` (L371-L376) não identifica a cena como fechamento por falta da tag `is_closing_choice=True`, tratando-a como conteúdo duplicado. |
| **4. Resolução de Ativos / Imagens** | **Preservada** | `quiz_assets.py` (L440-L480) busca imagens no Pexels para queries `"broken wifi..."` e `"jesus christ cross..."` ou cria cards coloridos de fallback. |
| **5. Renderização e Concatenação** | **Preservada** | `poc_quiz_render.py` (L769-L815) sintetiza voz, renderiza o card visual e concatena `narration_q7.mp3` e `video_q7.mp4` no `final-1.mp4`. |
| **6. Checagem Pós-Render (Media Quality)** | **Risco de Descarte** | Se `subtitle_required=True` (padrão autônomo), a task é bloqueada antes de chegar ao disco público/estoque devido à falta de arquivo SRT. |

---

## 3. FONTE DE VERDADE CANÔNICA PROPOSTA

Para eliminar divergências, sobrescritas conflitantes e heurísticas cegas:

```
[Profile Settings (SQLite content_profiles)]
       │
       ▼
[Generation Profile Context (profile_manager.get_generation_profile_context)]
       │
       ▼
[VideoParams (schema.py)] ──(Única fonte durante a execução)──► [Pipeline de Execução (task.py)]
                                                                       │
                                                       ┌───────────────┴───────────────┐
                                                       ▼                               ▼
                                            [Quiz Pipeline]                 [Traditional Pipeline]
                                            - closing_type explícito        - roteiro tradicional
                                            - voice do perfil/global        - safety tradicional
                                            - subtitle_required=False       - subtitle_required=True
                                            - Quiz Safety Gate              - Quality Gate tradicional
```

1. **Precedência de Contrato:** `VideoParams` deve ser preenchido integralmente na entrada com base no contexto canônico do perfil do canal (`profile_manager.get_generation_profile_context`).
2. **Isenção de Subtitle para Renderizadores Procedurais:** Formatos que utilizam renderização nativa de cards no vídeo (`quiz_dilemma`, `quiz_paper`) devem definir formalmente `subtitle_required = False` e `subtitle_enabled = False` em `VideoParams`, impedindo bloqueios indevidos no `Media Quality Gate`.
3. **Encerramentos e Metadados:** Se `closing_type` ou `num_questions` vierem nulos ou `"auto"`, `task.py` deve consultar o perfil do canal antes de recorrer a heurísticas de texto por nicho.
4. **Alinhamento de Duração:** Unificar o teto de duração aceitável de quizzes em `[60.0s, 65.0s]` em todas as pontas (`QuizConfig`, `PaperQuizConfig` e `task.py`).

---

## 4. INTERSEÇÕES COM OUTROS AGENTES

### A. Dependências do AGENTE 1 (Arquitetura, Banco de Dados e Modelos)
- **Persistência de Metadados Editoriais:** Garantir que `profile_manager.py` exporte `closing_type`, `num_questions`, `video_format` e `voice_name` de forma padronizada em `get_generation_profile_context` para que `VideoParams` não sofra lacunas.
- **Isolamento de Tabelas de Segurança:** O Agente 1 deve assegurar coerência entre `monetization_safety` e `quiz_safety_history` no SQLite, garantindo que queries do Scheduler e de Estoque leiam o status correto por canal.

### B. Estados Consumidos pelo AGENTE 3 (Observabilidade, UI e Scheduler)
- **Sinalização Factual de `READY_STOCK`:** O Agente 3 (Web UI V2 / Factory Live / Scheduler) consome o campo `tasks.stage` e `tasks.safety_status`. Se `task.py` emitir `READY_STOCK` com `safety_status="REVIEW"`, a UI exibe o card verde de "Pronto", mas o Scheduler o ignora silenciosamente. O estágio deve ser emitido como `HELD_SAFETY_REVIEW` em vez de `READY_STOCK`.
- **Central de Revisão (QG-V2.2):** O endpoint da Central de Revisão consome o status de segurança. Para permitir a revisão de quizzes, o Agente 3 precisa reconhecer tarefas em revisão por similaridade de dilemas.

---

## 5. RECOMENDAÇÃO MÍNIMA

Ações pontuais recomendadas para a fase de implementação (sem execução imediata):

1. **Ajuste em `app/services/quiz_generator.py` (L454):** Adicionar `penult_q["is_closing_choice"] = True` e `penult_q["verified"] = True` no bloco `closing_type == "quiz_choice_religious"` de `_apply_channel_closing`.
2. **Ajuste em `app/services/task.py` (L2755):** No início de `_run_quiz_pipeline`, forçar `params.subtitle_required = False` (uma vez que os cards visuais dispensam artefato SRT externo) e passar `voice_name=getattr(params, "voice_name", None)` para `export_to_quiz_config`.
3. **Alinhamento de Duração:** Atualizar o `target_duration_range` de `QuizConfig` em `app/services/quiz_generator.py` (L914) para `[60.0, 65.0]`, equalizando-o com o gate de `task.py`.
4. **Governança de `REVIEW`:** Em `_run_quiz_pipeline`, se `assessment.get("safety_status") == const.SAFETY_STATUS_REVIEW`, atualizar o estágio da tarefa para `HELD_REVIEW` em vez de `READY_STOCK`, evitando discrepâncias operacionais no estoque.
