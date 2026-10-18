# -*- coding: utf-8 -*-
"""
Fase V2.13 — Ensaio de Migração e Compatibilidade de Dados (Migration Rehearsal)
Este script executa o ensaio completo de migração a partir de um schema legado
com dados sintéticos sanitizados, validando integridade, idempotência,
vínculos multiprojeto e ensaio de rollback.
"""

import os
import sys
import shutil
import sqlite3
import json
from datetime import datetime, timezone

# Garantir importações do projeto
BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BASE_DIR not in sys.path:
    sys.path.insert(0, BASE_DIR)

from app.services import (
    profile_manager,
    scheduler,
    quality_recovery,
    operator_console,
    safety_gate,
    quality_score,
    isolation_guard,
)

def create_legacy_synthetic_db(db_path: str):
    """Cria um banco SQLite com o schema legado (pré-V2) e dados sintéticos representativos."""
    if os.path.exists(db_path):
        os.remove(db_path)
    os.makedirs(os.path.dirname(db_path), exist_ok=True)
    
    conn = sqlite3.connect(db_path)
    cur = conn.cursor()
    
    # 1. content_profiles legado (sem settings_json)
    cur.execute("""
    CREATE TABLE content_profiles (
        id TEXT PRIMARY KEY,
        name TEXT NOT NULL,
        slug TEXT UNIQUE NOT NULL,
        niche TEXT,
        language TEXT,
        region TEXT,
        default_preset TEXT,
        growth_mode TEXT,
        is_active INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    
    # 2. publishing_channels legado (sem external_account_id, project_id)
    cur.execute("""
    CREATE TABLE publishing_channels (
        id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        display_name TEXT NOT NULL,
        external_profile_name TEXT,
        is_enabled INTEGER NOT NULL DEFAULT 1,
        created_at TEXT NOT NULL,
        updated_at TEXT NOT NULL
    );
    """)
    
    # 3. task_profiles
    cur.execute("""
    CREATE TABLE task_profiles (
        task_id TEXT PRIMARY KEY,
        profile_id TEXT NOT NULL,
        created_at TEXT NOT NULL
    );
    """)
    
    # 4. task_platforms
    cur.execute("""
    CREATE TABLE task_platforms (
        task_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        PRIMARY KEY (task_id, platform)
    );
    """)
    
    # 5. scheduled_posts legado
    cur.execute("""
    CREATE TABLE scheduled_posts (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        scheduled_at TEXT NOT NULL,
        status TEXT NOT NULL DEFAULT 'planned',
        created_at TEXT NOT NULL,
        profile_id TEXT,
        channel_id TEXT
    );
    """)
    
    # 6. publication_events legado
    cur.execute("""
    CREATE TABLE publication_events (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        task_id TEXT NOT NULL,
        platform TEXT NOT NULL,
        published_at TEXT NOT NULL,
        status TEXT NOT NULL,
        external_id TEXT,
        error_code TEXT,
        provider_request_id TEXT,
        profile_id TEXT,
        channel_id TEXT
    );
    """)
    
    # 7. autopilot_settings
    cur.execute("""
    CREATE TABLE autopilot_settings (
        key TEXT PRIMARY KEY,
        value TEXT NOT NULL
    );
    """)
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Inserir canais legados sintéticos
    profiles = [
        ('legacy_curiosidades', 'Curiosidades Legado', 'curiosidades-legado', 'Ciência', 'pt-BR', 'BR', 'fatos_curiosos', 'WARMUP', 1, now, now),
        ('legacy_quiz_biblico', 'Quiz Bíblico Legado', 'quiz-biblico-legado', 'Bíblia', 'pt-BR', 'BR', 'quiz_dilemma', 'WARMUP', 1, now, now),
        ('legacy_misterios', 'Mistérios no Papel Legado', 'misterios-papel-legado', 'Mistério', 'pt-BR', 'BR', 'quiz_paper', 'WARMUP', 1, now, now),
    ]
    cur.executemany("""
        INSERT INTO content_profiles (id, name, slug, niche, language, region, default_preset, growth_mode, is_active, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
    """, profiles)
    
    # Inserir canais de publicação legados
    channels = [
        ('ch_leg_yt_01', 'legacy_curiosidades', 'youtube', 'Curiosidades (YT)', 'CuriosidadesOficial', 1, now, now),
        ('ch_leg_tk_01', 'legacy_curiosidades', 'tiktok', 'Curiosidades (TK)', 'curiosidades_tiktok', 1, now, now),
        ('ch_leg_yt_02', 'legacy_quiz_biblico', 'youtube', 'Quiz Bíblico (YT)', 'QuizBiblicoOficial', 1, now, now),
        ('ch_leg_yt_03', 'legacy_misterios', 'youtube', 'Mistérios (YT)', 'MisteriosPapelOficial', 1, now, now),
        ('ch_leg_tk_02', 'legacy_misterios', 'tiktok', 'Mistérios (TK)', 'misterios_papel_tk', 1, now, now),
    ]
    cur.executemany("""
        INSERT INTO publishing_channels (id, profile_id, platform, display_name, external_profile_name, is_enabled, created_at, updated_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?);
    """, channels)
    
    # Inserir tarefas e agendamentos legados
    tasks = [
        ('task_leg_01', 'legacy_curiosidades', now),
        ('task_leg_02', 'legacy_curiosidades', now),
        ('task_leg_03', 'legacy_quiz_biblico', now),
        ('task_leg_04', 'legacy_misterios', now),
    ]
    cur.executemany("INSERT INTO task_profiles VALUES (?, ?, ?);", tasks)
    
    task_plats = [
        ('task_leg_01', 'youtube'),
        ('task_leg_01', 'tiktok'),
        ('task_leg_02', 'youtube'),
        ('task_leg_03', 'youtube'),
        ('task_leg_04', 'youtube'),
        ('task_leg_04', 'tiktok'),
    ]
    cur.executemany("INSERT INTO task_platforms VALUES (?, ?);", task_plats)
    
    sched = [
        (1, 'task_leg_01', 'youtube', '2026-10-19T10:00:00Z', 'planned', now, 'legacy_curiosidades', 'ch_leg_yt_01'),
        (2, 'task_leg_01', 'tiktok', '2026-10-19T10:00:00Z', 'planned', now, 'legacy_curiosidades', 'ch_leg_tk_01'),
        (3, 'task_leg_03', 'youtube', '2026-10-19T14:00:00Z', 'ready', now, 'legacy_quiz_biblico', 'ch_leg_yt_02'),
    ]
    cur.executemany("INSERT INTO scheduled_posts VALUES (?, ?, ?, ?, ?, ?, ?, ?);", sched)
    
    pubs = [
        (1, 'task_leg_02', 'youtube', '2026-10-18T10:00:00Z', 'published', 'yt_ext_123', None, 'req_001', 'legacy_curiosidades', 'ch_leg_yt_01'),
    ]
    cur.executemany("INSERT INTO publication_events VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?);", pubs)
    
    conn.commit()
    conn.close()
    return db_path

def run_migration_rehearsal(source_db: str, target_db: str, backup_db: str):
    """Simula o ensaio completo de migração em cópia isolada."""
    # 1. Copiar base legada para alvo
    if os.path.exists(target_db):
        os.remove(target_db)
    shutil.copyfile(source_db, target_db)
    
    # 2. Criar backup pré-migração
    if os.path.exists(backup_db):
        os.remove(backup_db)
    shutil.copyfile(target_db, backup_db)
    
    # 3. Executar migrações dos serviços V2
    profile_manager.init_profile_db(db_path=target_db)
    scheduler.init_db(db_path=target_db)
    quality_recovery.init_review_db(db_path=target_db)
    operator_console.init_operator_db(db_path=target_db)
    safety_gate.init_safety_db(db_path=target_db)
    quality_score.init_quality_db(db_path=target_db)
    
    # 4. Migração e enriquecimento inteligente de metadados legados
    with sqlite3.connect(target_db) as conn:
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        
        # Preservar dados legados reais: NUNCA inventar IDs de projeto ou contas.
        # Canais sem project_id permanecem NULL, respeitando compatibilidade existente
        # e exigindo reconciliação explícita se houver destinos ambíguos.
        
        # Mapear perfis para suas configurações tipadas no formato JSON canônico
        profiles = cur.execute("SELECT * FROM content_profiles").fetchall()
        for p in profiles:
            pid = p['id']
            preset = p['default_preset'] or ''
            
            # Construir modelo tipado ChannelWorkspaceSettings
            settings = profile_manager.ChannelWorkspaceSettings()
            if preset == 'quiz_dilemma' or 'quiz' in pid:
                settings.editorial.video_format = 'quiz_dilemma'
                settings.voice.voice_name = 'pt-BR-FranciscaNeural'
                settings.automation.target_ready_stock = 5
                settings.automation.max_generations_24h = 5
            elif preset == 'quiz_paper' or 'papel' in pid or 'misterios' in pid:
                settings.editorial.video_format = 'quiz_paper'
                settings.voice.voice_name = 'pt-BR-AntonioNeural'
                settings.automation.target_ready_stock = 3
                settings.automation.max_generations_24h = 3
            else:
                settings.editorial.video_format = 'traditional'
                settings.voice.voice_name = 'pt-BR-AntonioNeural'
                settings.automation.target_ready_stock = 4
                settings.automation.max_generations_24h = 4
                
            cur.execute(
                "UPDATE content_profiles SET settings_json = ? WHERE id = ?;",
                (settings.to_json(), pid)
            )
        conn.commit()

    # 5. Validações Pós-Migração
    profiles_after = profile_manager.list_profiles(db_path=target_db)
    channels_after = profile_manager.list_channels(db_path=target_db)
    
    # Verificar cada perfil e configurações
    for p in profiles_after:
        pid = p['id']
        st = profile_manager.get_profile_settings(pid, db_path=target_db)
        assert st.editorial.video_format in ('traditional', 'quiz_dilemma', 'quiz_paper'), f'Formato inválido: {st.editorial.video_format}'
        assert st.voice.voice_name in ('pt-BR-AntonioNeural', 'pt-BR-FranciscaNeural'), f'Voz inválida: {st.voice.voice_name}'
        assert st.automation.target_ready_stock > 0, f'Target stock inválido: {st.automation.target_ready_stock}'

        # Verificar canais e preservação de vínculos multiprojeto reais
    for ch in channels_after:
        # Canais legados preservam project_id como None (zero invenção de IDs arbitrários)
        assert ch.get('project_id') is None, f"Canal legado {ch.get('id')} não deveria ter project_id inventado"

    # 6. Validação de Integridade SQLite
    with sqlite3.connect(target_db) as conn:
        integrity = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        if integrity != 'ok':
            raise RuntimeError(f'Integrity check falhou: {integrity}')
            
    # 7. Idempotência: rodar procedimentos novamente e checar integridade e semântica
    profile_manager.init_profile_db(db_path=target_db)
    scheduler.init_db(db_path=target_db)
    quality_recovery.init_review_db(db_path=target_db)
    operator_console.init_operator_db(db_path=target_db)
    safety_gate.init_safety_db(db_path=target_db)
    quality_score.init_quality_db(db_path=target_db)
    
    with sqlite3.connect(target_db) as conn:
        integrity_2 = conn.execute("PRAGMA integrity_check;").fetchone()[0]
        if integrity_2 != 'ok':
            raise RuntimeError(f'Integrity check pós-idempotência falhou: {integrity_2}')
            
        # Contagem pós idempotência idêntica
        count_profiles = conn.execute("SELECT COUNT(*) FROM content_profiles").fetchone()[0]
        count_channels = conn.execute("SELECT COUNT(*) FROM publishing_channels").fetchone()[0]
        assert count_profiles == len(profiles_after), 'Idempotência alterou contagem de perfis'
        assert count_channels == len(channels_after), 'Idempotência alterou contagem de canais'

    # 8. Teste de Rollback Sintético
    rollback_db = target_db + '.rollback_test.db'
    shutil.copyfile(backup_db, rollback_db)
    conn_rb = sqlite3.connect(rollback_db)
    try:
        rb_integrity = conn_rb.execute("PRAGMA integrity_check;").fetchone()[0]
        cols = {r[1] for r in conn_rb.execute("PRAGMA table_info(content_profiles);").fetchall()}
        if rb_integrity != 'ok' or 'settings_json' in cols:
            raise RuntimeError('Rollback sintético falhou ou não restaurou estado legado')
    finally:
        conn_rb.close()
    if os.path.exists(rollback_db):
        try:
            os.remove(rollback_db)
        except OSError:
            pass
        
    return {
        'status': 'PASS',
        'profiles_count': len(profiles_after),
        'channels_count': len(channels_after),
        'integrity': integrity,
        'idempotency': 'PASS',
        'rollback': 'PASS'
    }

if __name__ == '__main__':
    src = os.path.join(BASE_DIR, 'storage', 'legacy_synthetic_source.db')
    tgt = os.path.join(BASE_DIR, 'storage', 'video_factory_migration_isolated.db')
    bak = os.path.join(BASE_DIR, 'storage', 'video_factory_migration_pre.db')
    
    print('[1/3] Criando base legada sintética...')
    create_legacy_synthetic_db(src)
    print(f'Base legada criada em: {src}')
    
    print('[2/3] Executando simulação de migração e rollback...')
    res = run_migration_rehearsal(src, tgt, bak)
    print(f'[3/3] Resultado do Ensaio: {json.dumps(res, indent=2)}')
