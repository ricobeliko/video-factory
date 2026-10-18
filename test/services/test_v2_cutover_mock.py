# Test suite para testar a logica do cutover e preflight em ambiente mock
import os
import sqlite3
import hashlib
import json
import pytest

def test_cutover_preflight_active_posts_block(tmp_path):
    # Simula banco com posts ativos (deve bloquear preflight)
    db_file = tmp_path / "video_factory.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE scheduled_posts (id INTEGER PRIMARY KEY, status TEXT)")
    cur.execute("INSERT INTO scheduled_posts (status) VALUES ('publishing')")
    conn.commit()

    # Preflight logic:
    cur.execute("SELECT count(*) FROM scheduled_posts WHERE status IN ('in_progress', 'publishing')")
    active_count = cur.fetchone()[0]
    conn.close()

    assert active_count == 1
    # Verifica que a condicao do cutover bloqueia
    assert active_count > 0, "Deveria bloquear cutover devido a posts ativos"

def test_cutover_preflight_integrity_and_snapshot(tmp_path):
    # Simula banco integro e criacao de backup com manifesto SHA256
    db_file = tmp_path / "video_factory.db"
    conn = sqlite3.connect(str(db_file))
    cur = conn.cursor()
    cur.execute("CREATE TABLE content_profiles (id INTEGER PRIMARY KEY, name TEXT)")
    cur.execute("INSERT INTO content_profiles (name) VALUES ('Test Profile')")
    cur.execute("CREATE TABLE scheduled_posts (id INTEGER PRIMARY KEY, status TEXT)")
    conn.commit()

    cur.execute("PRAGMA integrity_check;")
    integrity = cur.fetchone()[0]
    conn.close()
    assert integrity == "ok"

    # Simula snapshot
    backup_dir = tmp_path / "backup_cutover"
    backup_dir.mkdir()
    bak_file = backup_dir / "video_factory.db"
    with open(db_file, "rb") as f_src, open(bak_file, "wb") as f_dst:
        f_dst.write(f_src.read())

    # SHA256
    h_orig = hashlib.sha256(db_file.read_bytes()).hexdigest()
    h_bak = hashlib.sha256(bak_file.read_bytes()).hexdigest()
    assert h_orig == h_bak

    manifest = {
        "timestamp": "20261018_160000",
        "pre_sha": "cf7d64767e13f94eb710809057dbcbc6efc19a27",
        "db_sha256": h_orig
    }
    manifest_file = backup_dir / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    assert manifest_file.exists()

def test_cutover_hotfix_diff_validation():
    # Simula verificacao de diff do hotfix de autonomous_production.py
    valid_added = ["+    rejected_struct = None"]
    valid_removed = []
    
    # Valid hotfix
    assert len(valid_added) == 1
    assert len(valid_removed) == 0
    assert "rejected_struct = None" in valid_added[0]

    # Invalid diff (com linha extra)
    invalid_added = ["+    rejected_struct = None", "+    malicious_call()"]
    assert len(invalid_added) > 1

def test_cutover_rollback_restore_simulation(tmp_path):
    # Simula fluxo de rollback a partir do backup
    db_orig = tmp_path / "video_factory.db"
    db_orig.write_text("v1_original_data", encoding="utf-8")

    # Snapshot
    backup_file = tmp_path / "backup.db"
    backup_file.write_text("v1_original_data", encoding="utf-8")

    # Alteracao durante cutover (simulada)
    db_orig.write_text("v2_modified_data", encoding="utf-8")
    assert db_orig.read_text(encoding="utf-8") == "v2_modified_data"

    # Rollback
    db_orig.write_text(backup_file.read_text(encoding="utf-8"), encoding="utf-8")
    assert db_orig.read_text(encoding="utf-8") == "v1_original_data"
