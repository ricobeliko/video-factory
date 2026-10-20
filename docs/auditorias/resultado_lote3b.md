# Relatório de Execução — Lote 3B | Regras Operacionais V1 (Correções Cirúrgicas CF-3B)

- **Data**: 2026-10-20
- **Agente**: Agente 3 — Operação e Publicação
- **Worktree**: `C:\Projetos\MoneyPrinterTurbo-V1\.worktrees\lote3b-regras-negocio`
- **Branch**: `feat/v1-lote3b-regras-negocio`
- **Baseline de Integração**: `e10ea7bd2f019947c4bf042b6b884dd178458e71` (`feat/v1-integracao-lotes-1-2-3a`)
- **Status**: CONCLUÍDO (Correções Cirúrgicas CF-3B-01, CF-3B-02 e CF-3B-03 Aplicadas e Homologadas)

---

## 1. Correções Cirúrgicas Implementadas

### CF-3B-01 — RN-02 / Segurança da Aprovação Humana
1. **Centralização Canônica de Gates**:
   - Criada a função `scheduler.validate_candidate_technical_and_safety_gates(task_id, task_data, db_path, task_base_dir)`.
   - Consumida de forma idêntica e sem divergências por:
     - `scheduler.plan_schedule`
     - `autonomous_production._recover_waiting_task`
     - `quality_recovery.apply_human_review_decision`
2. **Qualidade Técnica e Integridade Física**:
   - Rejeição de `final_media_quality` em estado `BLOCK`, duração `<= 0`, tarefas em `TASK_STATE_FAILED`/`CANCELLED` ou com `failed_stage`. Arquivo MP4 com tamanho > 0 não é mais considerado suficiente isoladamente.
3. **Faixa Numérica Estrita**:
   - Aprovação humana estritamente restrita à faixa numérica finita `55.0 <= q_score < 70.0`, sem exceção por label `REVIEW`.
   - Scores finitos `< 55.0` (ex: 40.0) são bloqueados de forma irredutível contra aprovação humana e classificados como rejeição definitiva.
4. **Prevalência Estrita de Registros de Segurança**:
   - Validação combinada de `monetization_safety`, `quiz_safety_history` e `is_task_held_for_safety_review`.
   - Registros persistidos em estado `REVIEW` ou `BLOCK` no banco jamais são sobrescritos por status em memória.

### CF-3B-02 — RN-01 / Contagem Canônica por Canal
1. **Métricas Persistidas**:
   - `profile_id` e `channel_id` agora são obrigatoriamente persistidos nas métricas de `generation_approved` em `evaluate_completed_task_gates`.
2. **Consulta SQLite com `json_extract`**:
   - Substituída a comparação textual frágil por `json_extract(metadata_json, '$.channel_id') = ?`.
3. **Fallback Legado Restrito**:
   - Fallback por `profile_id` para registros legados sem canal identificado é restrito estritamente a perfis com exatamente um único canal YouTube ativo (`count(*) = 1`), eliminando contaminações cruzadas entre canais do mesmo perfil.
4. **Alinhamento da Telemetria**:
   - `get_autonomous_status` atualizado para repassar `target_channel` ao `count_generations_in_last_24h`.

### CF-3B-03 — RN-03 / Fronteira e Persistência
1. **Fronteira Sub-55**:
   - Tarefas com `q_score` finito `< 55.0` são rejeições definitivas mesmo que `q_label` seja `REVIEW`.
2. **Incremento Correto do Circuit Breaker**:
   - Tarefas com score `< 55.0` não entram em retenção (salvo pendência de safety review) e incrementam o contador `consecutive_rejections`.
3. **Persistência Dupla em Disco**:
   - Retenções em `REVIEW` persistem atômica e simultaneamente em `sm.state` e em `script.json` via `task_artifacts.patch_script_data`.
4. **Sobrevivência Pós-Restart**:
   - `HELD_SAFETY_REVIEW` e retenções `REVIEW` são respeitados após reinício, mantendo o fail-closed ativo contra publicação indevida.

---

## 2. Arquivos Alterados

1. `app/services/scheduler.py`:
   - Adicionada função centralizada `validate_candidate_technical_and_safety_gates`.
   - `plan_schedule` refatorado para consumir a validação centralizada e aplicar o teto numérico `55.0 <= q_score < 70.0`.
2. `app/services/autonomous_production.py`:
   - `_recover_waiting_task` refatorado com restrição numérica e consumo de `validate_candidate_technical_and_safety_gates`.
   - `evaluate_completed_task_gates` inclui `profile_id` e `channel_id` em `metrics`.
   - `count_generations_in_last_24h` utiliza `json_extract(metadata_json, '$.channel_id') = ?` e restringe fallback por perfil a `count(*) = 1`.
   - `get_autonomous_status` repassa `target_channel`.
   - `run_autonomous_cycle` trata `< 55.0` como rejeição definitiva e persiste retenções em `script.json` via `task_artifacts.patch_script_data`.
3. `app/services/quality_recovery.py`:
   - `apply_human_review_decision` bloqueia aprovações de scores `< 55.0` e consome `validate_candidate_technical_and_safety_gates`.
4. `test/services/test_lote3b_operational_rules.py`:
   - 19 testes automatizados (14 iniciais + 5 testes de fronteira obrigatórios).

---

## 3. Testes Executados (Conforme TEST POLICY)

- **Comando direcionado**:
  ```powershell
  .\.venv\Scripts\python.exe -m pytest .worktrees/lote3b-regras-negocio/test/services/test_lote3b_operational_rules.py -q -p no:cacheprovider
  ```
- **Resultado**:
  `19 passed in 39.09s`
- **Testes de Fronteira Obrigatórios Validados**:
  - `test_cf3b01_final_media_quality_block_blocks_scheduling_even_with_valid_mp4`: **PASS**
  - `test_cf3b03_score_40_with_review_label_is_hard_rejection`: **PASS**
  - `test_cf3b02_two_channels_same_profile_without_scheduled_posts_independent_counting`: **PASS**
  - `test_cf3b01_human_approval_cannot_bypass_safety_or_copyright_post_restart`: **PASS**
  - `test_cf3b03_held_safety_review_persisted_in_script_json_and_respected_post_restart`: **PASS**

---

## 4. Riscos Pendentes e Recomendações

- Zero alteração DDL ou migração de banco.
- Zero chamada a provedores externos de publicação ou geração real.
- Branch isolada e worktree exclusivo prontos para homologação final do Arquiteto-Chefe.
