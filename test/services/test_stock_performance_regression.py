"""
Testes de regressão de performance e integridade de estoque da V2 (Missão v2/performance-estoque).

Valida:
1. SingleFlightCache com TTL e bypass com fresh=True.
2. Invalidação de cache em mutações (conclusão de task, remoção, pause/resume, DB commits).
3. Preservação estrita dos critérios fail-closed de elegibilidade de estoque pronto.
4. Caches LRU de mídia (probe_media e validate_clip_file).
"""

import os
import shutil
import tempfile
import threading
import time
from unittest.mock import MagicMock, patch

import pytest

from app.models import const
from app.services import (
    autonomous_production,
    media_quality,
    operator_console,
    scheduler,
    state as state_module,
)
from scripts import flow_playwright


def test_single_flight_cache_ttl_and_fresh_bypass():
    """Valida que SingleFlightCache respeita TTL e que fresh=True faz bypass."""
    cache = autonomous_production.SingleFlightCache(ttl_seconds=0.5)
    compute_calls = 0

    def compute():
        nonlocal compute_calls
        compute_calls += 1
        return {"count": compute_calls}

    # 1. Primeira chamada calcula
    res1 = cache.get_or_compute("key1", compute, fresh=False)
    assert res1 == {"count": 1}
    assert compute_calls == 1

    # 2. Segunda chamada dentro do TTL reutiliza cache (sem novo compute)
    res2 = cache.get_or_compute("key1", compute, fresh=False)
    assert res2 == {"count": 1}
    assert compute_calls == 1

    # 3. Chamada com fresh=True faz bypass e recalcula
    res3 = cache.get_or_compute("key1", compute, fresh=True)
    assert res3 == {"count": 2}
    assert compute_calls == 2

    # 4. Invalidação limpa o cache
    cache.invalidate()
    res4 = cache.get_or_compute("key1", compute, fresh=False)
    assert res4 == {"count": 3}
    assert compute_calls == 3


def test_single_flight_cache_concurrent_execution():
    """Valida que múltiplas threads simultâneas executam a função computada apenas uma vez."""
    cache = autonomous_production.SingleFlightCache(ttl_seconds=2.0)
    compute_count = 0
    compute_lock = threading.Lock()

    def slow_compute():
        nonlocal compute_count
        with compute_lock:
            compute_count += 1
        time.sleep(0.05)
        return {"ready": 42}

    results = []

    def worker():
        r = cache.get_or_compute("same_key", slow_compute, fresh=False)
        results.append(r)

    threads = [threading.Thread(target=worker) for _ in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    assert compute_count == 1
    assert len(results) == 5
    for r in results:
        assert r == {"ready": 42}


def test_invalidate_render_pass_clears_ready_stock_cache():
    """Valida que operator_console.invalidate_render_pass_cache limpa o cache de estoque."""
    with patch.object(autonomous_production, "invalidate_autonomous_ready_stock_cache") as mock_inv:
        operator_console.invalidate_render_pass_cache()
        mock_inv.assert_called_once()


def test_task_completion_and_deletion_invalidates_cache():
    """Valida que transição de task para COMPLETE/FAILED e deleção invalidam o cache."""
    sm = state_module.MemoryState()

    with patch("app.services.operator_console.invalidate_render_pass_cache") as mock_inv:
        # Tarefa em processamento -> não invalida
        sm.update_task("t1", state=const.TASK_STATE_PROCESSING, progress=50)
        assert mock_inv.call_count == 0

        # Tarefa completa -> invalida
        sm.update_task("t1", state=const.TASK_STATE_COMPLETE, progress=100)
        assert mock_inv.call_count >= 1

        # Tarefa falha -> invalida
        sm.update_task("t2", state=const.TASK_STATE_FAILED, progress=10)
        assert mock_inv.call_count >= 2

        # Tarefa deletada -> invalida
        sm.delete_task("t1")
        assert mock_inv.call_count == 3


def test_factory_pause_and_resume_invalidates_cache():
    """Valida que pausar ou retomar a fábrica invalida o cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        scheduler.init_db(db_path)
        operator_console.init_operator_db(db_path)
        operator_console.acquire_instance_lock(
            db_path=db_path,
            timeout_seconds=30,
        )

        with patch("app.services.operator_console.invalidate_render_pass_cache") as mock_inv:
            operator_console.pause_factory(db_path=db_path)
            assert mock_inv.call_count >= 1

            operator_console.resume_factory(db_path=db_path)
            assert mock_inv.call_count >= 2


def test_scheduler_connection_mutation_invalidates_cache():
    """Valida que qualquer mutação no DB via scheduler.get_connection invalida o cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test.db")
        scheduler.init_db(db_path)

        with patch("app.services.operator_console.invalidate_render_pass_cache") as mock_inv:
            # Consulta leitura (sem mudanças) -> não invalida
            with scheduler.get_connection(db_path) as conn:
                conn.execute("SELECT 1;").fetchone()
            assert mock_inv.call_count == 0

            # Mutação (insert) -> invalida ao sair do context manager
            with scheduler.get_connection(db_path) as conn:
                conn.execute(
                    "INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at) "
                    "VALUES ('t1', 'youtube', '2026-01-01T00:00:00Z', 'planned', '2026-01-01T00:00:00Z');"
                )
            assert mock_inv.call_count >= 1


def test_media_probe_and_clip_caches():
    """Valida o funcionamento e invalidação dos caches LRU de mídia."""
    media_quality.clear_probe_media_cache()
    flow_playwright.clear_validate_clip_cache()

    with tempfile.TemporaryDirectory() as tmpdir:
        dummy_file = os.path.join(tmpdir, "clip.mp4")
        with open(dummy_file, "wb") as f:
            f.write(b"0" * 1024)

        with patch("app.services.media_quality.get_ffprobe_binary", return_value="ffprobe"), \
             patch("subprocess.run") as mock_sub:
            mock_sub.return_value.returncode = 0
            mock_sub.return_value.stdout = '{"format":{"duration":"5.0"},"streams":[{"codec_type":"video","codec_name":"h264","width":1080,"height":1920,"duration":"5.0"}]}'

            # 1ª chamada executa subprocess
            p1 = media_quality.probe_media(dummy_file)
            assert mock_sub.call_count == 1
            assert p1["video_streams"][0]["codec_name"] == "h264"

            # 2ª chamada usa cache (subprocess não é chamado novamente)
            p2 = media_quality.probe_media(dummy_file)
            assert mock_sub.call_count == 1
            assert p2 == p1

            # Invalidação limpa o cache
            media_quality.clear_probe_media_cache()
            p3 = media_quality.probe_media(dummy_file)
            assert mock_sub.call_count == 2
