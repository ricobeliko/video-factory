# Relatório de Ensaio de Migração e Compatibilidade de Dados — Fase V2.13

> **Status:** CONCLUÍDO COM SUCESSO (PASS)  
> **Data:** 18/10/2026  
> **Ambiente:** Novo PC DEV (DESKTOP-MU3HR6J) — Isolado (C:\Projetos\MoneyPrinterTurbo-V2)  
> **Branch:** eat/video-factory-v2  
> **Script de Reprodução:** scripts/rehearse_v2_migration.py  
> **Suíte de Teste:** 	est/services/test_v2_13_migration_rehearsal.py (4/4 PASS)  

---

## 1. Mapeamento de Schemas (Legado vs V2)

### Schema Legado (Pré-V2 / Produção Atual):
- content_profiles: sem campo settings_json (configurações residiam dispersas em presets ou stream session state).
- publishing_channels: sem campos external_account_id e project_id (necessários para vínculos multiprojeto no Post for Me).
- Tabelas de controle: 	ask_profiles, 	ask_platforms, scheduled_posts, publication_events, utopilot_settings.

### Schema V2 (Alvo):
- content_profiles: coluna settings_json TEXT NOT NULL DEFAULT '{}' adicionada com tipagem Pydantic ChannelWorkspaceSettings.
- publishing_channels: colunas external_account_id TEXT e project_id TEXT adicionadas de forma aditiva.
- Novas tabelas operacionais: operator_video_reviews, operator_review_commands para Curadoria Humana.
- Índices otimizados: idx_active_schedule_v2 para controle de agendamento reativo sem starvation.

---

## 2. Preparação dos Dados Sintéticos Representativos

O dataset de teste sintético sanitizado (storage/legacy_synthetic_source.db) contemplou:
1. **Canal Tradicional (legacy_curiosidades):** Fatos e curiosidades gerais, narração pt-BR-AntonioNeural, 4 vídeos como meta de estoque.
2. **Canal Quiz Q0-R (legacy_quiz_biblico):** Perguntas bíblicas 50/50, narração pt-BR-FranciscaNeural, 5 vídeos como meta de estoque.
3. **Canal Quiz Papel P1.3 (legacy_misterios):** Enigmas visuais rústicos, narração pt-BR-AntonioNeural, 3 vídeos como meta de estoque.
4. **Vínculos Multiprojeto:** 5 destinos de publicação simulados (YouTube e TikTok) com project_id e external_account_id.
5. **Histórico e Filas:** Tarefas associadas em 	ask_profiles, 	ask_platforms, agendamentos em scheduled_posts (planned/ready) e eventos de publicação em publication_events.

---

## 3. Simulação de Migração em Cópia Isolada

A migração foi executada sobre cópia isolada (storage/video_factory_migration_isolated.db):
- profile_manager.init_profile_db() executou com sucesso as migrações aditivas ALTER TABLE ... ADD COLUMN para settings_json, external_account_id e project_id.
- scheduler.init_db(), quality_recovery.init_review_db(), operator_console.init_operator_db() e safety_gate.init_safety_db() provisionaram as tabelas complementares sem colisão.
- Mapeamento de metadados converteu presets legados nas estruturas canônicas V2 com validação Pydantic.

---

## 4. Verificações de Integridade, Idempotência e Rollback

1. **Integridade SQLite:** PRAGMA integrity_check retornou estritamente ok.
2. **Idempotência:** A reexecução completa de todos os inicializadores V2 sobre a base já migrada manteve o schema inalterado, não duplicou registros e manteve contagens idênticas (3 perfis e 5 canais).
3. **Ensaio de Rollback Sintético:** A restauração a partir do backup pré-migração (storage/video_factory_migration_pre.db) foi testada, comprovando integridade ok e restauração fiel do schema legado.

---

## 5. Próximo Gate Seguro

- **Gate V2.13:** MIGRATION_REHEARSAL_PASS atingido.
- **Próxima Etapa:** Preparação de Cutover de Homologação / Janela de Transição Controlada (sem push ou deploy nesta fase).
