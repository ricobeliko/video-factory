"""Script de medição e benchmark de endpoints da Web UI V2.

Mede latência (p50 e p95) em 5 iterações para:
1. Ambiente DEV Real (via HTTP no motor em execução http://127.0.0.1:8080)
2. Ambiente de Carga Sintética em DB Temporário (20 canais, 50.000 operational_events, centenas de tarefas)
"""

import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Tuple
from unittest.mock import patch

# Garante project_root no sys.path
PROJECT_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)


ENDPOINTS_TO_MEASURE = [
    ("Sistema", "GET", "/api/v2/system/status", None),
    ("Sistema", "GET", "/api/v2/providers/health", None),
    ("Sistema", "GET", "/api/v2/system/provider-health", None),
    ("Sistema", "GET", "/api/v2/health", None),
    ("Sistema", "GET", "/api/v2/channels/overview", None),
    ("Sistema", "GET", "/api/v2/voices", None),
    ("Sistema", "GET", "/api/v2/settings/providers", None),
    ("Sistema", "GET", "/api/v2/publishing/accounts", None),
    ("Sistema", "GET", "/api/v2/channels/default/settings", None),
    ("Sistema", "PATCH", "/api/v2/scheduler/settings", {"dry_run": True}),
    ("Frota", "GET", "/api/v2/fleet/summary", None),
    ("Produção", "GET", "/api/v2/production/overview", None),
    ("Diagnóstico", "GET", "/api/v2/diagnostics/overview", None),
    ("Factory Live", "GET", "/api/v2/executions/live", None),
]


def calc_percentiles(times: List[float]) -> Tuple[float, float, float, float]:
    """Retorna (min, p50, p95, max) em milissegundos."""
    if not times:
        return 0.0, 0.0, 0.0, 0.0
    s = sorted(times)
    n = len(s)
    if n % 2 == 1:
        p50 = s[n // 2]
    else:
        p50 = (s[n // 2 - 1] + s[n // 2]) / 2.0
    idx95 = min(int(round(0.95 * (n - 1))), n - 1)
    p95 = s[idx95]
    return s[0], p50, p95, s[-1]


def measure_http_dev(base_url: str = "http://127.0.0.1:8080", iterations: int = 5) -> List[Dict[str, Any]]:
    print(f"\n--- Medindo Ambiente DEV Real via HTTP ({base_url}) [{iterations} iterações] ---", flush=True)
    results = []

    for screen, method, path, payload in ENDPOINTS_TO_MEASURE:
        times = []
        statuses = []
        url = base_url + path
        data_bytes = json.dumps(payload).encode("utf-8") if payload else None
        headers = {"Content-Type": "application/json"} if payload else {}

        print(f"[{screen:12s}] {method:5s} {path:35s} ... ", end="", flush=True)
        for i in range(iterations):
            req = urllib.request.Request(url, data=data_bytes, headers=headers, method=method)
            t0 = time.perf_counter()
            try:
                with urllib.request.urlopen(req, timeout=15) as resp:
                    resp.read()
                    dt_ms = (time.perf_counter() - t0) * 1000
                    times.append(dt_ms)
                    statuses.append(resp.status)
            except urllib.error.HTTPError as e:
                dt_ms = (time.perf_counter() - t0) * 1000
                times.append(dt_ms)
                statuses.append(e.code)
            except Exception as exc:
                dt_ms = (time.perf_counter() - t0) * 1000
                times.append(dt_ms)
                statuses.append(f"ERR:{type(exc).__name__}")

        min_t, p50, p95, max_t = calc_percentiles(times)
        status_rep = statuses[-1] if statuses else "-"
        results.append({
            "screen": screen,
            "method": method,
            "path": path,
            "p50_ms": p50,
            "p95_ms": p95,
            "min_ms": min_t,
            "max_ms": max_t,
            "status": status_rep,
            "times": times,
        })
        print(f"p50: {p50:7.1f}ms | p95: {p95:7.1f}ms | status: {status_rep}", flush=True)

    return results


def populate_synthetic_db(db_path: str, num_channels: int = 20, num_events: int = 50000, num_tasks: int = 300) -> None:
    """Preenche um banco temporário com carga sintética proporcional/superior à PROD."""
    from app.services import scheduler, profile_manager, operator_console, quality_score, safety_gate

    print(f"\nInicializando banco sintético em {db_path}...", flush=True)
    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)
    operator_console.init_operator_db(db_path)
    quality_score.init_quality_db(db_path)
    safety_gate.init_safety_db(db_path)

    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    conn = sqlite3.connect(db_path)
    cur = conn.cursor()

    try:
        cur.execute("PRAGMA synchronous = OFF;")
        cur.execute("PRAGMA journal_mode = MEMORY;")

        # 1. Configurações Globais em autopilot_settings
        cur.execute("""
            INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES
            ('scheduler_enabled', 'true'),
            ('auto_publish_enabled', 'true'),
            ('dry_run', 'false'),
            ('growth_mode', 'NORMAL'),
            ('autonomous_mode_enabled', 'true'),
            ('autonomous_state', 'IDLE'),
            ('youtube_enabled', 'true'),
            ('tiktok_enabled', 'true'),
            ('daily_generations_cap', '10');
        """)

        # 2. Criar canais / perfis
        print(f"Gerando {num_channels} canais sintéticos...", flush=True)
        channel_ids = []
        for i in range(num_channels):
            pid = "default" if i == 0 else f"channel-synth-{i:02d}"
            channel_ids.append(pid)
            name = f"Canal Sintético {i}" if i > 0 else "Canal Default"
            slug = pid
            niche = "Curiosidades" if i % 2 == 0 else "Finanças"
            fmt = "traditional" if i % 3 == 0 else ("quiz_dilemma" if i % 3 == 1 else "quiz_paper")

            settings_json = json.dumps({"video_format": fmt, "automation": {"posts_per_day": 1}})
            cur.execute("""
                INSERT OR REPLACE INTO content_profiles
                (id, name, slug, niche, language, region, default_preset, growth_mode, is_active, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, 'pt-BR', 'BR', ?, 'NORMAL', 1, ?, ?, ?);
            """, (pid, name, slug, niche, fmt, settings_json, now_iso, now_iso))

            cur.execute("""
                INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES
                (?, 'true'),
                (?, '3'),
                (?, '10');
            """, (f"autonomous_mode_enabled:{pid}", f"autonomous_target_ready_stock:{pid}", f"max_generations_24h:{pid}"))

            # Destinos de publicação (YouTube e/ou TikTok)
            cur.execute("""
                INSERT OR REPLACE INTO publishing_channels
                (id, profile_id, platform, display_name, external_account_id, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', ?, ?, 1, 1, ?, ?);
            """, (f"pub-{pid}-yt", pid, f"{name} YT", f"UCsynth{i:018d}", now_iso, now_iso))

            if i % 2 == 1:
                cur.execute("""
                    INSERT OR REPLACE INTO publishing_channels
                    (id, profile_id, platform, display_name, external_account_id, is_enabled, auto_publish_authorized, created_at, updated_at)
                    VALUES (?, ?, 'tiktok', ?, ?, 1, 1, ?, ?);
                """, (f"pub-{pid}-tt", pid, f"{name} TT", f"tt_user_{i}", now_iso, now_iso))

        # 3. Criar tarefas e histórico (scheduled_posts, tasks, quality_scores, safety)
        print(f"Gerando {num_tasks} tarefas e agendamentos sintéticos...", flush=True)
        task_ids = []
        for j in range(num_tasks):
            tid = f"task-synth-{j:04d}"
            task_ids.append(tid)
            pid = channel_ids[j % num_channels]
            t_offset = now - timedelta(hours=j % 72)
            t_iso = t_offset.isoformat()

            cur.execute("""
                INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at)
                VALUES (?, ?, ?);
            """, (tid, pid, t_iso))

            # Scheduled posts
            status = "published" if j % 4 == 0 else ("ready" if j % 4 == 1 else ("planned" if j % 4 == 2 else "failed"))
            cur.execute("""
                INSERT OR REPLACE INTO scheduled_posts
                (task_id, platform, scheduled_at, status, created_at, profile_id, attempts)
                VALUES (?, 'youtube', ?, ?, ?, ?, 1);
            """, (tid, t_iso, status, t_iso, pid))

            # Publication events
            if status == "published":
                cur.execute("""
                    INSERT OR REPLACE INTO publication_events
                    (task_id, platform, published_at, status, profile_id)
                    VALUES (?, 'youtube', ?, 'success', ?);
                """, (tid, t_iso, pid))

            # Safety e Quality
            cur.execute("""
                INSERT OR REPLACE INTO monetization_safety
                (task_id, preset, safety_status, checked_at)
                VALUES (?, 'traditional', 'PASS', ?);
            """, (tid, t_iso))

            cur.execute("""
                INSERT OR REPLACE INTO content_quality_scores
                (task_id, topic, quality_score, quality_label, created_at)
                VALUES (?, 'Topico Sintetico', 85, 'GOOD', ?);
            """, (tid, t_iso))

        # 4. Criar 50.000 eventos operacionais
        print(f"Gerando {num_events} operational_events em lote...", flush=True)
        event_types = [
            ("autonomous_production", "INFO", "generation_started"),
            ("autonomous_production", "INFO", "task_approved_and_scheduled"),
            ("autonomous_production", "INFO", "cycle_completed"),
            ("scheduler", "INFO", "post_published"),
            ("scheduler", "WARNING", "rate_limit_cooldown"),
            ("autonomous_production", "WARNING", "quality_held"),
        ]

        batch = []
        base_time = now - timedelta(days=7)
        for k in range(num_events):
            comp, sev, ev_type = event_types[k % len(event_types)]
            ev_time = (base_time + timedelta(seconds=k * 12)).isoformat()
            pid = channel_ids[k % num_channels]
            tid = task_ids[k % num_tasks] if k % 3 == 0 else None
            meta = json.dumps({"profile_id": pid, "event_idx": k})
            batch.append((ev_time, comp, sev, ev_type, tid, f"Evento operacional {k}", meta))

            if len(batch) >= 5000:
                cur.executemany("""
                    INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?);
                """, batch)
                batch = []

        if batch:
            cur.executemany("""
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
            """, batch)

        conn.commit()
        print(f"Banco sintético preenchido com sucesso ({num_events} eventos, {num_channels} canais, {num_tasks} tarefas).", flush=True)
    finally:
        conn.close()


def measure_synthetic_load(db_path: str, iterations: int = 5) -> List[Dict[str, Any]]:
    from fastapi.testclient import TestClient
    from app import asgi

    import concurrent.futures

    print(f"\n--- Medindo Ambiente com Carga Sintética via TestClient [{iterations} iterações] ---", flush=True)
    client = TestClient(asgi.app)
    results = []

    # Patch do DB path para usar o temporário em todos os serviços
    with patch("app.services.operator_console.get_db_path", return_value=db_path), \
         patch("app.services.scheduler.get_db_path", return_value=db_path), \
         patch("app.services.profile_manager.get_db_path", return_value=db_path), \
         patch("app.services.operator_console.require_primary_instance", return_value=None), \
         patch("app.services.operator_console.is_primary_instance", return_value=True):

        for screen, method, path, payload in ENDPOINTS_TO_MEASURE:
            times = []
            statuses = []

            print(f"[{screen:12s}] {method:5s} {path:35s} ... ", end="", flush=True)
            for i in range(iterations):
                t0 = time.perf_counter()
                res_box = []
                err_box = []

                def run_req():
                    try:
                        if method == "GET":
                            res_box.append(client.get(path))
                        elif method == "PATCH":
                            res_box.append(client.patch(path, json=payload))
                        else:
                            res_box.append(client.request(method, path, json=payload))
                    except Exception as exc:
                        err_box.append(exc)

                t = threading.Thread(target=run_req, daemon=True)
                t.start()
                t.join(timeout=10.0)

                if t.is_alive():
                    dt_ms = 10000.0
                    times.append(dt_ms)
                    statuses.append("ERR:Timeout (>10s)")
                    # Se deu timeout na primeira iteração, preenche o restante com timeout para não travar o benchmark
                    while len(times) < iterations:
                        times.append(dt_ms)
                        statuses.append("ERR:Timeout (>10s)")
                    break
                elif err_box:
                    dt_ms = (time.perf_counter() - t0) * 1000
                    times.append(dt_ms)
                    statuses.append(f"ERR:{type(err_box[0]).__name__}")
                else:
                    dt_ms = (time.perf_counter() - t0) * 1000
                    times.append(dt_ms)
                    statuses.append(res_box[0].status_code)

            min_t, p50, p95, max_t = calc_percentiles(times)
            status_rep = statuses[-1] if statuses else "-"
            results.append({
                "screen": screen,
                "method": method,
                "path": path,
                "p50_ms": p50,
                "p95_ms": p95,
                "min_ms": min_t,
                "max_ms": max_t,
                "status": status_rep,
                "times": times,
            })
            print(f"p50: {p50:7.1f}ms | p95: {p95:7.1f}ms | status: {status_rep}", flush=True)

    return results


def print_markdown_table(title: str, results: List[Dict[str, Any]]) -> None:
    print(f"\n### {title}\n", flush=True)
    print("| Tela | Método | Endpoint | p50 (ms) | p95 (ms) | Status |", flush=True)
    print("|---|---|---|---|---|---|", flush=True)
    for r in results:
        print(f"| {r['screen']} | `{r['method']}` | `{r['path']}` | {r['p50_ms']:.1f} | {r['p95_ms']:.1f} | {r['status']} |", flush=True)


def main():
    print("=" * 70, flush=True)
    print("BENCHMARK DE ENDPOINTS V2 — MEDIÇÃO DE LATÊNCIA (ANTES)", flush=True)
    print("=" * 70, flush=True)

    skip_dev = "--only-synth" in sys.argv
    dev_results_file = os.path.join(os.path.dirname(__file__), ".dev_results_cache.json")

    if skip_dev and os.path.exists(dev_results_file):
        with open(dev_results_file, "r", encoding="utf-8") as f:
            dev_results = json.load(f)
    else:
        dev_results = measure_http_dev(iterations=5)
        try:
            with open(dev_results_file, "w", encoding="utf-8") as f:
                json.dump(dev_results, f, indent=2)
        except Exception:
            pass

    # 2. Carga Sintética em DB Temporário
    synth_results = []
    tmp_dir = tempfile.mkdtemp()
    try:
        synth_db = os.path.join(tmp_dir, "synthetic_prod_scale.db")
        populate_synthetic_db(synth_db, num_channels=20, num_events=50000, num_tasks=300)
        synth_results = measure_synthetic_load(synth_db, iterations=5)
        synth_results_file = os.path.join(os.path.dirname(__file__), ".synth_results_cache.json")
        try:
            with open(synth_results_file, "w", encoding="utf-8") as f:
                json.dump(synth_results, f, indent=2)
        except Exception:
            pass
    finally:
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)

    print("\n" + "=" * 70, flush=True)
    print("TABELAS CONSOLIDADAS (ANTES)", flush=True)
    print("=" * 70, flush=True)

    print_markdown_table("Tabela 1: Ambiente DEV Real (5 iterações via HTTP)", dev_results)
    print_markdown_table("Tabela 2: Carga Sintética (20 canais, 50k eventos, 300 tarefas)", synth_results)


if __name__ == "__main__":
    main()
