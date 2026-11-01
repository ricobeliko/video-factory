"""
Benchmark sintético de performance para endpoints de estoque/operações V2.
Cria fixture equivalente à carga da PROD:
- 130 tarefas com safety PASS
- 50 tarefas com clipes de Flow reais (gerados via ffmpeg para custo real de ffprobe)
- 323 scheduled_posts
- 22.000 operational_events
- 6 perfis (2 TikTok-only, 4 YouTube+TikTok)

Mede latências fria (primeira chamada) e em regime estacionário (polling frontend a cada 15s durante 2 minutos com warmer ativo).
Meta: p95 em regime estacionário < 1.5s.
"""

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone

# Ensure project root is in sys.path
ROOT_DIR = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from fastapi.testclient import TestClient
from app import asgi
from app.config import config
from app.services import operator_console, profile_manager, quality_score, safety_gate, scheduler, quality_recovery


def generate_tiny_mp4(dest_path: str):
    """Gera um vídeo MP4 minúsculo (0.2s) e válido com ffmpeg."""
    os.makedirs(os.path.dirname(dest_path), exist_ok=True)
    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=blue:s=320x240:d=0.2",
        "-c:v", "libx264", "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        dest_path,
    ]
    subprocess.run(cmd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)


def build_synthetic_fixture(fixture_dir: str):
    storage_dir = os.path.join(fixture_dir, "storage")
    os.makedirs(storage_dir, exist_ok=True)
    db_path = os.path.join(storage_dir, "video_factory.db")
    task_base_dir = os.path.join(storage_dir, "tasks")
    os.makedirs(task_base_dir, exist_ok=True)

    # Inicializa bancos
    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)
    operator_console.init_operator_db(db_path)
    safety_gate.init_safety_db(db_path)
    quality_score.init_quality_db(db_path)
    quality_recovery.init_review_db(db_path)

    # Gera um template mp4 minúsculo para duplicar rapidamente
    template_mp4 = os.path.join(fixture_dir, "template.mp4")
    generate_tiny_mp4(template_mp4)

    now_iso = datetime.now(timezone.utc).isoformat()

    # 1. Cria 6 perfis:
    # 4 YouTube + TikTok
    # 2 TikTok-only
    profiles_cfg = [
        ("default", "Canal Principal", ["youtube", "tiktok"]),
        ("prof-curiosidades", "Curiosidades Rápidas", ["youtube", "tiktok"]),
        ("prof-historias", "Histórias Misteriosas", ["youtube", "tiktok"]),
        ("prof-quiz", "Quiz Diário", ["youtube", "tiktok"]),
        ("prof-dicas-tiktok", "Dicas Rápidas TikTok", ["tiktok"]),
        ("prof-fatos-tiktok", "Fatos em 30s TikTok", ["tiktok"]),
    ]

    with scheduler.get_connection(db_path) as conn:
        for pid, pname, plats in profiles_cfg:
            conn.execute(
                """
                INSERT OR REPLACE INTO content_profiles (id, name, slug, language, region, is_active, created_at, updated_at)
                VALUES (?, ?, ?, 'pt-BR', 'BR', 1, ?, ?);
                """,
                (pid, pname, pid, now_iso, now_iso),
            )
            for plat in plats:
                cid = f"chan-{pid}-{plat}"
                conn.execute(
                    """
                    INSERT OR REPLACE INTO publishing_channels
                    (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                    VALUES (?, ?, ?, ?, 1, 1, ?, ?);
                    """,
                    (cid, pid, plat, f"{pname} ({plat.capitalize()})", now_iso, now_iso),
                )

        # 2. Cria 130 tarefas safety PASS com arquivos válidos
        for i in range(130):
            tid = f"task-synth-{i:03d}"
            pid, _, plats = profiles_cfg[i % len(profiles_cfg)]
            task_dir = os.path.join(task_base_dir, tid)
            os.makedirs(task_dir, exist_ok=True)
            video_file = os.path.join(task_dir, "final-video.mp4")
            shutil.copyfile(template_mp4, video_file)

            # Metadata da task
            task_manifest = {
                "task_id": tid,
                "profile_id": pid,
                "video_file": video_file,
                "title": f"Vídeo Sintético {i}",
                "state": 2,  # COMPLETE
                "created_at": now_iso,
                "updated_at": now_iso,
            }
            if i < 50:
                # Flow clips para simular custo de proveniência de copyright e ffprobe
                clip_path = os.path.join(task_dir, "flow_clip_1.mp4")
                shutil.copyfile(template_mp4, clip_path)
                task_manifest["video_terms"] = [
                    {"flow_url": "https://flow.google.com/test1", "clip_file": clip_path}
                ]

            with open(os.path.join(task_dir, "task.json"), "w", encoding="utf-8") as f:
                json.dump(task_manifest, f)

            # DB insertions
            conn.execute(
                """
                INSERT INTO monetization_safety (task_id, preset, safety_status, safety_reasons, checked_at)
                VALUES (?, 'curiosidades', 'PASS', 'all checks passed', ?);
                """,
                (tid, now_iso),
            )
            conn.execute(
                """
                INSERT INTO content_quality_scores (task_id, quality_score, quality_label, topic, created_at)
                VALUES (?, 85.0, 'STRONG', 'Curiosidades', ?);
                """,
                (tid, now_iso),
            )
            conn.execute(
                """
                INSERT INTO task_profiles (task_id, profile_id, created_at)
                VALUES (?, ?, ?);
                """,
                (tid, pid, now_iso),
            )
            for plat in plats:
                conn.execute(
                    """
                    INSERT INTO task_platforms (task_id, platform)
                    VALUES (?, ?);
                    """,
                    (tid, plat),
                )

        # 3. Cria 323 scheduled_posts
        for i in range(323):
            tid = f"task-sched-{i:03d}"
            pid, _, plats = profiles_cfg[i % len(profiles_cfg)]
            plat = plats[i % len(plats)]
            cid = f"chan-{pid}-{plat}"
            status = "planned" if i % 2 == 0 else "ready"
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, profile_id, channel_id, platform, scheduled_at, status, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                (tid, pid, cid, plat, now_iso, status, now_iso),
            )

        # 4. Insere 22.000 operational_events em lotes
        print("Inserindo 22.000 operational_events...")
        batch_events = []
        for i in range(22000):
            tid = f"task-synth-{i % 130:03d}"
            ev_type = "safety_evaluated" if i % 3 == 0 else "task_scheduled"
            batch_events.append((
                now_iso,
                "autonomous_production",
                "INFO",
                ev_type,
                tid,
                f"Synthetic event {i}",
                json.dumps({"synthetic": True, "idx": i}),
            ))
            if len(batch_events) >= 1000:
                conn.executemany(
                    """
                    INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    batch_events,
                )
                batch_events = []
        if batch_events:
            conn.executemany(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                batch_events,
            )

    return db_path, task_base_dir


def percentile(values, p):
    if not values:
        return 0.0
    sorted_vals = sorted(values)
    k = (len(sorted_vals) - 1) * (p / 100.0)
    f = int(k)
    c = f + 1
    if c < len(sorted_vals):
        return sorted_vals[f] + (sorted_vals[c] - sorted_vals[f]) * (k - f)
    return sorted_vals[f]


def run_benchmark(db_path: str, task_base_dir: str):
    os.environ["STORAGE_DIR"] = os.path.dirname(task_base_dir)

    from unittest.mock import patch
    from app.services import media_quality, autonomous_production
    from scripts import flow_playwright

    endpoints = [
        ("GET /fleet/summary", "/api/v2/fleet/summary"),
        ("GET /channels", "/api/v2/channels"),
        ("GET /system/status", "/api/v2/system/status"),
        ("GET /production/overview", "/api/v2/production/overview"),
        ("GET /diagnostics/overview", "/api/v2/diagnostics/overview"),
        ("GET /executions/live", "/api/v2/executions/live"),
    ]

    client = TestClient(asgi.app)
    results = {}
    channel_stocks = {}

    with patch("app.services.scheduler.get_db_path", return_value=db_path), \
         patch("app.services.safety_gate.get_safety_db_path", return_value=db_path), \
         patch("app.utils.utils.storage_dir", return_value=os.path.dirname(task_base_dir)), \
         patch("app.utils.utils.task_dir", return_value=task_base_dir):

        print("\n=== ETAPA 1: MEDICAO FRIA (caches vazios) ===")
        cold_latencies = {}
        for label, url in endpoints:
            # Limpa todos os caches (ffprobe, clipes, ready stock)
            media_quality.clear_probe_media_cache()
            flow_playwright.clear_validate_clip_cache()
            autonomous_production.invalidate_autonomous_ready_stock_cache()
            operator_console.reset_initialized_operator_dbs()
            scheduler.reset_initialized_dbs()

            t0 = time.perf_counter()
            resp = client.get(url)
            elapsed = time.perf_counter() - t0
            print(f"[FRIA] [{label}]: {elapsed:.3f}s", flush=True)
            if resp.status_code != 200:
                print(f"Error {resp.status_code} on {url}: {resp.text[:200]}")
            cold_latencies[label] = elapsed

            if label == "GET /fleet/summary" and not channel_stocks:
                data = resp.json().get("data", {})
                channels = data.get("channels", [])
                for ch in channels:
                    pid = ch.get("profile_id") or ch.get("channel_id")
                    channel_stocks[pid] = ch.get("ready_stock")

        print("\n=== ETAPA 2: REGIME ESTACIONARIO COM WARMER ATIVO (2 minutos, polling a cada 15s) ===")
        warmer = autonomous_production.ReadyStockCacheWarmer(
            interval_seconds=8.0,
            task_base_dir=task_base_dir,
            db_path=db_path,
        )
        warmer.start()
        try:
            # Polling a cada 15s durante 2 minutos (8 rodadas = 120s)
            rounds_count = 8
            steady_rounds = {label: [] for label, _ in endpoints}
            for round_idx in range(rounds_count):
                print(f"\nAguardando 15s (ciclo {round_idx+1}/{rounds_count}, t={(round_idx+1)*15}s)...", flush=True)
                time.sleep(15)

                for label, url in endpoints:
                    t0 = time.perf_counter()
                    resp = client.get(url)
                    elapsed = time.perf_counter() - t0
                    print(f"[ESTACIONARIO r{round_idx+1}] [{label}]: {elapsed:.3f}s", flush=True)
                    if resp.status_code != 200:
                        print(f"Error {resp.status_code} on {url}: {resp.text[:200]}")
                    steady_rounds[label].append(elapsed)

            for label, _ in endpoints:
                latencies = steady_rounds[label]
                p50 = percentile(latencies, 50)
                p95 = percentile(latencies, 95)
                cold = cold_latencies[label]
                results[label] = {
                    "cold_s": round(cold, 3),
                    "steady_p50_s": round(p50, 3),
                    "steady_p95_s": round(p95, 3),
                    "raw_steady": [round(x, 3) for x in latencies],
                }
        finally:
            warmer.stop()
            warmer.join(timeout=2.0)

        print("\n| Endpoint | Fria (Cold) | Regime p50 | Regime p95 | Meta (< 1.5s) | Status |")
        print("|---|---|---|---|---|---|")
        for label, _ in endpoints:
            c = results[label]["cold_s"]
            p50 = results[label]["steady_p50_s"]
            p95 = results[label]["steady_p95_s"]
            status = "PASS" if p95 < 1.5 else "FAIL"
            print(f"| `{label}` | {c:.3f} s | {p50:.3f} s | {p95:.3f} s | < 1.500 s | **{status}** |")

    return results, channel_stocks


if __name__ == "__main__":
    temp_dir = tempfile.mkdtemp(prefix="perf_bench_")
    print(f"Criando fixture sintética em {temp_dir}...")
    try:
        db_path, task_dir = build_synthetic_fixture(temp_dir)
        print("Fixture criada com sucesso. Executando benchmark...")
        results, channel_stocks = run_benchmark(db_path, task_dir)
        print("\n--- RESULTADOS FINAIS DO BENCHMARK ---")
        print(json.dumps({"results": results, "channel_stocks": channel_stocks}, indent=2))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
