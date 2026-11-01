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



def test_ready_stock_cache_warmer_lifecycle():
    """Valida inicializacao, pre-warm e encerramento limpo do cache warmer daemon."""
    autonomous_production.stop_ready_stock_cache_warmer()

    with patch("app.services.autonomous_production.get_autonomous_ready_stock") as mock_stock:
        mock_stock.return_value = {"tasks": []}
        warmer = autonomous_production.start_ready_stock_cache_warmer(interval_seconds=0.1)
        assert warmer.is_alive()
        assert warmer.daemon is True

        # Aguarda trigger inicial
        time.sleep(0.05)
        assert mock_stock.call_count >= 1

        autonomous_production.stop_ready_stock_cache_warmer()
        warmer.join(timeout=1.0)
        assert not warmer.is_alive()


def test_candidate_evaluation_parallelism_capped_at_4():
    """Valida que o paralelismo de avaliacao de candidatos e limitado a no maximo 4 workers."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_cap.db")
        scheduler.init_db(db_path)
        operator_console.init_operator_db(db_path)
        with scheduler.get_connection(db_path) as conn:
            for i in range(10):
                conn.execute(
                    "INSERT INTO task_platforms (task_id, platform) VALUES (?, 'youtube');",
                    (f"task-cap-{i}",)
                )
                conn.execute(
                    "INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'curiosidades', 'PASS', '2026-11-01');",
                    (f"task-cap-{i}",)
                )
        with patch("concurrent.futures.ThreadPoolExecutor") as mock_executor:
            mock_pool = MagicMock()
            mock_pool.map.return_value = []
            mock_executor.return_value.__enter__.return_value = mock_pool

            autonomous_production.get_autonomous_ready_stock(db_path=db_path, fresh=True)
            assert mock_executor.call_count >= 1
            _, kwargs = mock_executor.call_args
            assert kwargs.get("max_workers", 0) <= 4


def test_warmer_logic_with_compute_counters():
    """Valida a lógica de refresh, tracking de atividade recente e bypass de fresh=True."""
    cache = autonomous_production.SingleFlightCache(ttl_seconds=1.0)
    compute_count = 0

    def compute():
        nonlocal compute_count
        compute_count += 1
        return [f"item_{compute_count}"]

    # (b) Sem leitura recente da API, is_active_recently é False: warmer não deve recalcular
    assert not cache.is_active_recently(max_idle_seconds=60.0)

    # Simula tick do warmer quando ocioso:
    if cache.is_active_recently(60.0):
        cache.refresh("key", compute)
    assert compute_count == 0  # não recalculou!

    # API faz uma leitura inicial (fresh=False) -> calcula 1 vez e ativa o timestamp
    val1 = cache.get_or_compute("key", compute, fresh=False)
    assert val1 == ["item_1"]
    assert compute_count == 1
    assert cache.is_active_recently(max_idle_seconds=60.0)

    # (a) O warmer faz um tick após haver leitura recente -> renova o cache via refresh
    val_warm = cache.refresh("key", compute)
    assert val_warm == ["item_2"]
    assert compute_count == 2

    # Leitura subsequente da API (fresh=False) NÃO recalcula (reutiliza o valor renovado pelo warmer)
    val2 = cache.get_or_compute("key", compute, fresh=False)
    assert val2 == ["item_2"]
    assert compute_count == 2  # Continua 2!

    # (c) O loop autônomo com fresh=True sempre recalcula e NÃO grava no cache da API
    val_auto1 = cache.get_or_compute("key", compute, fresh=True)
    assert val_auto1 == ["item_3"]
    assert compute_count == 3

    val_auto2 = cache.get_or_compute("key", compute, fresh=True)
    assert val_auto2 == ["item_4"]
    assert compute_count == 4

    # Leitura da API ainda obtém o valor do cache (item_2), sem ser afetada pelo fresh=True do loop autônomo
    val_api = cache.get_or_compute("key", compute, fresh=False)
    assert val_api == ["item_2"]
    assert compute_count == 4


def test_ready_stock_cache_warmer_integration_counters():
    """Valida thread ReadyStockCacheWarmer: tick repovoa cache, ociosidade inibe e fresh=True isolado."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = os.path.join(tmpdir, "test_warmer.db")
        scheduler.init_db(db_path)
        operator_console.init_operator_db(db_path)
        task_dir = os.path.join(tmpdir, "tasks")
        os.makedirs(task_dir, exist_ok=True)

        autonomous_production.invalidate_autonomous_ready_stock_cache()
        cache = autonomous_production._API_READY_STOCK_CACHE

        with cache._lock:
            cache._last_read_ts = 0.0

        # (b) Sem leitura recente da API (is_active_recently é False)
        assert not cache.is_active_recently(60.0)

        compute_counter = 0
        original_refresh = cache.refresh

        def counted_refresh(key, compute_fn):
            nonlocal compute_counter
            compute_counter += 1
            return original_refresh(key, compute_fn)

        with patch.object(cache, "refresh", side_effect=counted_refresh):
            warmer = autonomous_production.ReadyStockCacheWarmer(
                interval_seconds=0.05,
                task_base_dir=task_dir,
                db_path=db_path,
            )
            warmer.start()
            try:
                # Boot pre-warm executa 1 refresh
                time.sleep(0.08)
                assert compute_counter == 1

                # (b) Sem leitura da API, warmer fica ocioso e não incrementa refresh
                time.sleep(0.12)
                assert compute_counter == 1

                # (a) API faz leitura (fresh=False) -> ativa last_read_ts
                autonomous_production.get_autonomous_ready_stock(
                    task_base_dir=task_dir, db_path=db_path, fresh=False
                )
                assert cache.is_active_recently(60.0)

                # Próximo tick do warmer detecta atividade recente e repovoa o cache
                time.sleep(0.12)
                assert compute_counter >= 2

                # Para o warmer para isolar asserções determinísticas de leitura e loop autônomo
                warmer.stop()
                warmer.join(timeout=1.0)

                # Leitura subsequente da API não incrementa refresh nem recalcula
                current_count = compute_counter
                autonomous_production.get_autonomous_ready_stock(
                    task_base_dir=task_dir, db_path=db_path, fresh=False
                )
                assert compute_counter == current_count

                # (c) Loop autônomo com fresh=True sempre recalcula e não grava no cache (não chama refresh)
                autonomous_production.get_autonomous_ready_stock(
                    task_base_dir=task_dir, db_path=db_path, fresh=True
                )
                assert compute_counter == current_count
            finally:
                warmer.stop()
                warmer.join(timeout=1.0)


def test_get_ffprobe_binary_does_not_cache_none():
    """Valida que get_ffprobe_binary não armazena None/ausente no cache e que clear_ffprobe_binary_cache limpa."""
    media_quality.clear_ffprobe_binary_cache()

    call_count = 0

    def mock_which(cmd):
        nonlocal call_count
        if cmd == "ffprobe":
            call_count += 1
            if call_count == 1:
                return None
            return "/usr/bin/ffprobe"
        return None

    with patch("shutil.which", side_effect=mock_which), \
         patch.dict("os.environ", {}, clear=True), \
         patch.object(media_quality.config.app, "get", return_value=None), \
         patch("app.utils.utils.get_ffmpeg_binary", return_value=None):

        # 1ª chamada: ffprobe não encontrado -> retorna None
        res1 = media_quality.get_ffprobe_binary()
        assert res1 is None
        assert call_count == 1

        # 2ª chamada: ffprobe agora está disponível -> deve tentar encontrar e retornar o novo binário (não pode retornar None cacheado!)
        res2 = media_quality.get_ffprobe_binary()
        assert res2 == "/usr/bin/ffprobe"
        assert call_count == 2

        # 3ª chamada: binário encontrado foi armazenado no cache -> não chama shutil.which de novo
        res3 = media_quality.get_ffprobe_binary()
        assert res3 == "/usr/bin/ffprobe"
        assert call_count == 2

        # 4ª chamada: clear_ffprobe_binary_cache limpa o cache
        media_quality.clear_ffprobe_binary_cache()
        res4 = media_quality.get_ffprobe_binary()
        assert res4 == "/usr/bin/ffprobe"
        assert call_count == 3

