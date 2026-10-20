# RELATÓRIO DE EXECUÇÃO — LOTE 3A | SEGURANÇA DE PUBLICAÇÃO V1

**Data:** 2026-10-20  
**Agente Responsável:** Agente 3 — Operação e Publicação  
**Worktree:** `C:\Projetos\MoneyPrinterTurbo-V1\.worktrees\lote3a-operacao`  
**Branch:** `feat/v1-lote3a-operacao`  
**Baseline Inicial:** `db42ae4`  
**Commit de Entrega:** `43309d6`  

---

## STATUS
**CONCLUÍDO COM SUCESSO.**  
Todos os 10 objetivos da missão foram implementados e validados por suítes de testes direcionados, sem efeitos colaterais em outros lotes.

---

## BRANCH_SHA
`43309d6 feat(publishing): autorizacao individual fail-closed por canal e idempotencia multicanal (Lote 3A)`

---

## ARQUIVOS_ALTERADOS
1. `app/services/publishing_idempotency.py`  
   - Escopo multicanal adicionado a todas as 6 funções canônicas: `(task_id, platform, COALESCE(channel_id, ''))`.
   - Isolamento estrito de verificação de sucesso e estado de agendamentos entre canais distintos.
   - Neutralização de duplicatas (`neutralize_duplicate_executable_posts`) restrita ao mesmo canal.

2. `app/services/scheduler.py`  
   - Migração aditiva em `_run_migrations`: adiciona coluna `auto_publish_authorized INTEGER NOT NULL DEFAULT 0` em `publishing_channels` (se a tabela existir) e índice único com auto-reconciliação de integridade.
   - Índice otimizado `idx_pub_events_task_plat_chan` em `publication_events(task_id, platform, COALESCE(channel_id, ''))`.
   - Adicionada função canônica `is_channel_auto_publish_authorized(...)` com política Fail-Closed e bloqueio irrestrito de "Dose Diária de Escolhas".
   - Adicionada função de governança `set_channel_auto_publish_authorized(...)` com auditoria via `operational_events`.
   - Adicionada função de migração controlada `migrate_channel_auto_publish_authorizations(...)` com `dry_run=True` por padrão.
   - `has_existing_or_terminal_destination`: eliminada a checagem wildcard global `pub_any` / `active_any` quando um `channel_id` específico é fornecido, preservando tombstones legados sem channel_id.
   - `plan_schedule`: inclusão da verificação canônica Fail-Closed de autorização por canal e passagem do `channel_id` para `can_schedule_task`.
   - `run_scheduler_cycle`: inclusão da revalidação de canal autorizado antes da execução (postergando com segurança em 30 min se não autorizado), e passagem de `channel_id` para `can_execute_scheduled_post`, `neutralize_duplicate_executable_posts` e `jit_provider_idempotency_guard`.

3. `test/services/test_publishing_idempotency.py`  
   - Atualizados testes de processamento e neutralização de duplicatas para refletir o isolamento multicanal e a autorização de canais.

4. `test/services/test_lote3a_publishing_security.py`  
   - Suíte dedicada de 6 testes direcionados para o Lote 3A cobrindo fail-closed, bloqueio estrito de Escolhas, migração dry-run/execução, independência multicanal, neutralização de duplicatas e ciclo do scheduler.

---

## AUTORIZACAO_CANONICA
A regra de autorização canônica é estritamente **Fail-Closed** e depende da tripla chave:
1. `autopilot_settings.auto_publish_enabled == "true"` (Chave Global)
2. `publishing_channels.is_enabled == 1` (Chave de Ativação do Destino)
3. `publishing_channels.auto_publish_authorized == 1` (Chave Específica de Publicação Automática)

### Regras Implementadas em `is_channel_auto_publish_authorized`:
- Se `channel_id` for ausente/inválido: `False`.
- Se canal não existir em `publishing_channels`: `False`.
- Se `is_enabled != 1`: `False`.
- Se `auto_publish_authorized != 1`: `False`.
- Se o perfil vinculado (`content_profiles`) estiver inativo (`is_active != 1`): `False`.
- **REGRA RÍGIDA DE SEGURANÇA (Hardcoded Safeguard):** Se `display_name`, `channel_id` ou `profile_id` contiver `"escolhas"`, a função retorna **`False` incondicionalmente**, impedindo publicação automática para *Dose Diária de Escolhas* mesmo diante de manipulações manuais no banco de dados.
- Tentativas de habilitar via `set_channel_auto_publish_authorized` para canais com `"escolhas"` disparam `PermissionError`.

---

## MIGRACAO_PROPOSTA
Para respeitar o princípio de que mudanças em produção devem ser explícitas e auditáveis:
- A adição da coluna no SQLite define `DEFAULT 0` (nenhum canal ganha permissão automaticamente na inicialização).
- Foi criada a função canônica auditável `migrate_channel_auto_publish_authorizations(db_path=None, allow_channels=None, dry_run=True)`:
  - **`dry_run=True` (Comportamento Padrão):** Realiza a varredura e retorna relatório detalhado (`eligible_channels`, `blocked_channels`, `already_authorized`) sem modificar registros.
  - **Critério de Elegibilidade:**
    - Canal com `is_enabled == 1`.
    - Histórico comprovado de sucesso prévio em `publication_events` (prova de publicação legítima prévia) OU presença em lista explícita `allow_channels`.
    - Bloqueio estrito e permanente para qualquer canal relacionado a "Dose Diária de Escolhas".
  - **`dry_run=False`:** Grava `auto_publish_authorized = 1` apenas nos canais elegíveis e registra o evento `CHANNEL_MIGRATION_EXECUTED` na tabela `operational_events`.

---

## IDEMPOTENCIA_VALIDADA
- **Escopo Canônico:** A tupla de proteção contra publicações duplicadas foi expandida de `(task_id, platform)` para `(task_id, platform, COALESCE(channel_id, ''))`.
- **Isolamento Multicanal Comprovado:**
  - A mesma tarefa `T` direcionada para `Canal A (YouTube)` e `Canal B (YouTube)` pode ser agendada e executada de forma 100% independente.
  - O sucesso de publicação no `Canal A` não bloqueia o agendamento, execução ou Just-In-Time Guard no `Canal B`.
  - A neutralização de duplicatas (`neutralize_duplicate_executable_posts`) neutraliza apenas posts redundantes direcionados para o mesmo canal, preservando agendamentos de outros canais da mesma plataforma.
- **Tombstones Legados:** Mantida compatibilidade estrita com cancelamentos históricos sem `channel_id` (onde atuam como wildcard preventivo).

---

## TESTES
Executados testes unitários e de integração locais direcionados via pytest:
1. `test/services/test_lote3a_publishing_security.py` (6 testes) -> **6 PASSED** (100%)
   - `test_canonical_authorization_fail_closed`: PASS
   - `test_dose_escolhas_strictly_forbidden`: PASS
   - `test_migration_dry_run_and_execution`: PASS
   - `test_multichannel_idempotency_isolation`: PASS
   - `test_duplicate_neutralization_scoped_to_same_channel`: PASS
   - `test_run_scheduler_cycle_blocks_unauthorized_channel`: PASS
2. `test/services/test_publishing_idempotency.py` (10 testes) -> **10 PASSED** (100%)
   - Suíte completa de idempotência de 3 camadas validada em ambiente multicanal.

**Total:** 16 testes direcionados executados, 16 aprovados (100% PASS).  
Seguindo estritamente a política de testes: após aprovação da suíte direcionada, a execução de testes foi encerrada.

---

## RISCOS_PENDENTES
1. **Ativação em Produção (Gate Humano Necessário):** Como a migração de schema aplica `DEFAULT 0`, os canais existentes em produção não publicarão automaticamente até que `scheduler.migrate_channel_auto_publish_authorizations(dry_run=False)` seja executado pelo operador na implantação.
2. **Integração com Lote 3B:** O Lote 3B implementará as regras de negócio aprovadas (`RN-01`, `RN-02`, `RN-03`), incluindo o teto de 2 vídeos em `WARMUP` e a aprovação humana de score 55–69 no scheduler.
