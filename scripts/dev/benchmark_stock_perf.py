"""
Benchmark sintético de performance para endpoints de estoque/operações V2.
Cria fixture equivalente à carga da PROD:
- 130 tarefas com safety PASS
- 50 tarefas com clipes de Flow reais (gerados via ffmpeg para custo real de ffprobe)
- 323 scheduled_posts
- 22.000 operational_events
- 6 perfis (2 TikTok-only, 4 YouTube+TikTok)

Mede latências p50 e p95 em 5 iterações via TestClient(asgi.app).
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
            assigned_prof = profiles_cfg[i % len(profiles_cfg)][0]
            tdir = os.path.join(task_base_dir, tid)
            os.makedirs(tdir, exist_ok=True)

            # Arquivo final-1.mp4
            shutil.copyfile(template_mp4, os.path.join(tdir, "final-1.mp4"))

            is_flow = (i < 50)
            if is_flow:
                flow_dir = os.path.join(tdir, "flow")
                flow_clips_dir = os.path.join(flow_dir, "clips")
                os.makedirs(flow_clips_dir, exist_ok=True)
                clip_path = os.path.join(flow_clips_dir, "clip_0.mp4")
                shutil.copyfile(template_mp4, clip_path)

                manifest = {
                    "flow_generation": {
                        "status": "COMPLETE",
                        "completed_scenes": [0],
                    },
                    "scenes": [
                        {
                            "scene_index": 0,
                            "expected_clip": "clip_0.mp4",
                            "is_flow_premium": True,
                        }
                    ],
                }
                with open(os.path.join(flow_dir, "manifest.json"), "w", encoding="utf-8") as mf:
                    json.dump(manifest, mf)

                script = {
                    "task_id": tid,
                    "profile_id": assigned_prof,
                    "state": "COMPLETE",
                    "video_file": os.path.join(tdir, "final-1.mp4"),
                    "duration": 15.0,
                    "flow_generation": {
                        "status": "COMPLETE",
                        "completed_scenes": [0],
                    },
                    "params": {"bgm_type": "none", "bgm_volume": 0.0},
                    "material_sources": [
                        {
                            "provider": "google_flow",
                            "asset_id": "clip_0.mp4",
                            "local_file": "flow/clips/clip_0.mp4",
                            "scene_index": 0,
                        }
                    ],
                }
            else:
                script = {
                    "task_id": tid,
                    "profile_id": assigned_prof,
                    "state": "COMPLETE",
                    "video_file": os.path.join(tdir, "final-1.mp4"),
                    "duration": 15.0,
                    "params": {"bgm_type": "none", "bgm_volume": 0.0},
                    "material_sources": [
                        {
                            "provider": "pexels",
                            "asset_id": f"px_{i}",
                            "local_file": "final-1.mp4",
                            "source_url": f"https://pexels.com/{i}",
                        }
                    ],
                }

            with open(os.path.join(tdir, "script.json"), "w", encoding="utf-8") as sf:
                json.dump(script, sf)

            # DB records
            conn.execute(
                """
                INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at)
                VALUES (?, 'monetized_fast', 'PASS', ?);
                """,
                (tid, now_iso),
            )
            conn.execute(
                """
                INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
                VALUES (?, 'Tema Sintético', 82.5, 'GOOD', ?);
                """,
                (tid, now_iso),
            )
            conn.execute(
                """
                INSERT INTO task_profiles (task_id, profile_id, created_at)
                VALUES (?, ?, ?);
                """,
                (tid, assigned_prof, now_iso),
            )
            for plat in profiles_cfg[i % len(profiles_cfg)][2]:
                conn.execute(
                    """
                    INSERT OR IGNORE INTO task_platforms (task_id, platform)
                    VALUES (?, ?);
                    """,
                    (tid, plat),
                )

        # 3. 323 scheduled_posts
        for i in range(323):
            tid = f"task-sched-{i:03d}"
            pid = profiles_cfg[i % len(profiles_cfg)][0]
            st = "planned" if i % 4 != 0 else "published"
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES (?, 'youtube', ?, ?, ?, ?);
                """,
                (tid, now_iso, st, now_iso, pid),
            )

        # 4. 22.000 operational_events
        print("Inserindo 22.000 operational_events...")
        batch_events = []
        for i in range(22000):
            ev_type = "TASK_PROGRESS" if i % 500 != 0 else "PUBLICATION_COPYRIGHT_STATUS_SET"
            meta = json.dumps({"step": i})
            batch_events.append((now_iso, "autonomous_production", "info", ev_type, f"task-{i%130}", f"Event {i}", meta))
            if len(batch_events) >= 2000:
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


def run_benchmark(db_path: str, task_base_dir: str, num_iterations: int = 5):
    # Patch scheduler default db and task_dir
    os.environ["STORAGE_DIR"] = os.path.dirname(task_base_dir)

    from unittest.mock import patch
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

        # Reset caches
        operator_console.reset_initialized_operator_dbs()
        scheduler.reset_initialized_dbs()

        for label, url in endpoints:
            latencies = []
            for it in range(num_iterations):
                t0 = time.perf_counter()
                resp = client.get(url)
                elapsed = time.perf_counter() - t0
                print(f"[{label}] iter {it+1}/{num_iterations}: {elapsed:.3f}s", flush=True)
                if resp.status_code != 200:
                    print(f"Error {resp.status_code} on {url}: {resp.text[:200]}")
                latencies.append(elapsed)

                if label == "GET /fleet/summary" and it == 0:
                    data = resp.json().get("data", {})
                    channels = data.get("channels", [])
                    for ch in channels:
                        pid = ch.get("profile_id") or ch.get("channel_id")
                        channel_stocks[pid] = ch.get("ready_stock")

            p50 = percentile(latencies, 50)
            p95 = percentile(latencies, 95)
            cold = latencies[0]
            results[label] = {
                "cold_s": round(cold, 3),
                "p50_s": round(p50, 3),
                "p95_s": round(p95, 3),
                "raw": [round(x, 3) for x in latencies],
            }

    return results, channel_stocks


if __name__ == "__main__":
    temp_dir = tempfile.mkdtemp(prefix="perf_bench_")
    print(f"Criando fixture sintética em {temp_dir}...")
    try:
        db_path, task_dir = build_synthetic_fixture(temp_dir)
        print("Fixture criada com sucesso. Executando benchmark (5 iterações)...")
        results, channel_stocks = run_benchmark(db_path, task_dir, num_iterations=5)
        print("\n--- RESULTADOS DO BENCHMARK ---")
        print(json.dumps({"results": results, "channel_stocks": channel_stocks}, indent=2))
    finally:
        shutil.rmtree(temp_dir, ignore_errors=True)
