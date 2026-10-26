"""Testes do Endpoint de Produção V2 (Missão P1 — GET /api/v2/production/overview).

Valida:
1. Rota /api/v2/production/overview registrada no FastAPI e no OpenAPI;
2. Estoque de vídeos prontos respeita as regras canônicas (mp4 físico, safety PASS, quality >= 70, canal YouTube ativo e não publicado);
3. Posts agendados (scheduled_posts);
4. Tarefas recentes (recent_runs) nas últimas 24h com status (SUCCESS, FAILED, REJECTED, RUNNING), estágios e motivos (gate_reason/error);
5. Filtro por profile_id;
6. Limite por seção (limit_per_section);
7. Campos ausentes serializados como null (nunca inventados);
8. Banco/canal vazio retorna listas vazias;
9. Medição de tempo de resposta e cache efêmero.
"""
from __future__ import annotations

import json
import os
import tempfile
import time
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from fastapi.testclient import TestClient

from app import asgi
from app.config import config
from app.models import const
from app.utils import utils
from app.services import (
    autonomous_production,
    operator_console,
    production_overview,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
)
from app.services import state as sm


class TestApiV2ProductionOverview(unittest.TestCase):
    def setUp(self):
        self.original_app_config = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_production.db")
        self.task_dir = os.path.join(self.temp_dir.name, "tasks")
        os.makedirs(self.task_dir, exist_ok=True)
        config.app["api_key"] = ""

        # Limpa cache do overview antes de cada teste
        production_overview.clear_production_overview_cache()

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        # Limpa tarefas em memória
        if hasattr(sm, "state") and hasattr(sm.state, "_tasks"):
            sm.state._tasks.clear()

        # Configura canais / perfis de teste
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE content_profiles
                SET name = 'Canal Principal',
                    slug = 'default',
                    niche = 'tech',
                    growth_mode = 'SCALE',
                    is_active = 1,
                    settings_json = ?
                WHERE id = 'default';
                """,
                (
                    json.dumps({
                        "editorial": {"video_format": "traditional"},
                        "schedule": {"posts_per_day": 2},
                        "automation": {"target_ready_stock": 5, "autonomous_enabled": True},
                    }),
                ),
            )

            conn.execute(
                """
                INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, settings_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?, 1, ?, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
                """,
                (
                    "prof-quiz",
                    "Canal de Quizzes",
                    "canal-quizzes",
                    "quiz",
                    "quiz_paper",
                    "SCALE",
                    json.dumps({
                        "editorial": {"video_format": "quiz_paper"},
                        "schedule": {"posts_per_day": 3},
                        "automation": {"target_ready_stock": 5, "autonomous_enabled": True},
                    }),
                ),
            )

            # Canal YouTube ativo para default
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
                VALUES ('chan-yt-default', 'default', 'youtube', 'Canal Principal YT', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
                """
            )
            # Canal YouTube ativo para prof-quiz
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
                VALUES ('chan-yt-quiz', 'prof-quiz', 'youtube', 'Quiz Channel YT', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
                """
            )

    def tearDown(self):
        config.app.clear()
        config.app.update(self.original_app_config)
        self.temp_dir.cleanup()
        production_overview.clear_production_overview_cache()

    def _create_physical_video(self, task_id: str, topic: str = "Vídeo") -> str:
        t_dir = os.path.join(self.task_dir, task_id)
        os.makedirs(t_dir, exist_ok=True)
        v_path = os.path.join(t_dir, "final-1.mp4")
        with open(v_path, "wb") as f:
            f.write(b"\x00" * 1024)

        script_payload = {
            "params": {
                "video_subject": topic,
                "bgm_type": "none",
                "bgm_volume": 0.0,
                "bgm_file": "",
            },
            "material_sources": [
                {"provider": "pexels", "asset_id": "999", "local_file": "v1.mp4", "duration": 5}
            ],
            "asset_provenance": {
                "bgm": {"enabled": False, "filename": None, "source": "none", "license_type": "none", "provenance_status": "SAFE_NO_BGM"},
                "visual_clips": [{"provider": "pexels", "asset_id": "999", "local_file": "v1.mp4", "duration": 5}],
                "presenter": {"enabled": False, "mode": "none"},
                "provenance_status": "SAFE_NO_BGM",
            },
        }
        with open(os.path.join(t_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script_payload, f)

        return v_path

    def test_route_registered_in_fastapi_and_openapi(self):
        """1. Rota /api/v2/production/overview está registrada no app e no OpenAPI."""
        client = TestClient(asgi.app)
        openapi_resp = client.get("/openapi.json")
        self.assertEqual(openapi_resp.status_code, 200)
        paths = openapi_resp.json().get("paths", {})
        self.assertIn("/api/v2/production/overview", paths)

    def test_empty_database_returns_empty_lists(self):
        """2. Quando não há tarefas nem posts, retorna estrutura completa com listas vazias."""
        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            payload = data.get("data", {})

            self.assertIn("totals", payload)
            self.assertIn("channels", payload)
            self.assertEqual(payload["totals"]["ready_stock"], 0)
            self.assertEqual(payload["totals"]["scheduled"], 0)
            self.assertEqual(payload["totals"]["success_24h"], 0)
            self.assertEqual(payload["totals"]["failed_24h"], 0)
            self.assertEqual(payload["totals"]["rejected_24h"], 0)

            self.assertEqual(len(payload["channels"]), 2)
            ch0 = payload["channels"][0]
            self.assertEqual(ch0["ready_stock"]["total"], 0)
            self.assertEqual(ch0["ready_stock"]["items"], [])
            self.assertEqual(ch0["scheduled"]["total"], 0)
            self.assertEqual(ch0["scheduled"]["items"], [])
            self.assertEqual(ch0["recent_runs"]["total"], 0)
            self.assertEqual(ch0["recent_runs"]["items"], [])

    def test_ready_stock_respects_canonical_rules(self):
        """3. Estoque respeita regras canônicas: vídeo físico, safety PASS, quality >= 70, não publicado."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Task 1: Canônica e Elegível
        t1_id = "task-canon-ready-1"
        self._create_physical_video(t1_id)
        sm.state.update_task(
            t1_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Vídeo Elegível de Curiosidades",
            created_at=now_iso,
            profile_id="default",
            video_duration=42.5,
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);",
                (t1_id, "default", now_iso),
            )
            conn.execute(
                "INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'tech', 'PASS', ?);",
                (t1_id, now_iso),
            )
            conn.execute(
                "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'Curiosidades', 88.5, 'GOOD', ?);",
                (t1_id, now_iso),
            )
            conn.execute(
                "INSERT INTO task_platforms (task_id, platform) VALUES (?, 'youtube');",
                (t1_id,),
            )

        # Task 2: Sem arquivo físico de vídeo -> Não elegível
        t2_id = "task-missing-mp4"
        sm.state.update_task(
            t2_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Vídeo sem MP4",
            created_at=now_iso,
            profile_id="default",
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (t2_id, now_iso))
            conn.execute("INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'tech', 'PASS', ?);", (t2_id, now_iso))
            conn.execute("INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'Curiosidades', 90.0, 'GOOD', ?);", (t2_id, now_iso))

        # Task 3: Safety FAIL -> Não elegível
        t3_id = "task-safety-fail"
        self._create_physical_video(t3_id)
        sm.state.update_task(
            t3_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Vídeo com Safety Fail",
            created_at=now_iso,
            profile_id="default",
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (t3_id, now_iso))
            conn.execute("INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'tech', 'FAIL', ?);", (t3_id, now_iso))
            conn.execute("INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'Curiosidades', 90.0, 'GOOD', ?);", (t3_id, now_iso))

        # Task 4: Quality < 70 -> Não elegível
        t4_id = "task-low-quality"
        self._create_physical_video(t4_id)
        sm.state.update_task(
            t4_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Vídeo Baixa Qualidade",
            created_at=now_iso,
            profile_id="default",
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (t4_id, now_iso))
            conn.execute("INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'tech', 'PASS', ?);", (t4_id, now_iso))
            conn.execute("INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'Curiosidades', 55.0, 'WEAK', ?);", (t4_id, now_iso))

        # Task 5: Já publicado no YouTube -> Não elegível
        t5_id = "task-already-published"
        self._create_physical_video(t5_id)
        sm.state.update_task(
            t5_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject="Vídeo Já Publicado",
            created_at=now_iso,
            profile_id="default",
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (t5_id, now_iso))
            conn.execute("INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'tech', 'PASS', ?);", (t5_id, now_iso))
            conn.execute("INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, 'Curiosidades', 85.0, 'GOOD', ?);", (t5_id, now_iso))
            conn.execute("INSERT INTO publication_events (task_id, platform, status, published_at) VALUES (?, 'youtube', 'success', ?);", (t5_id, now_iso))

        with patch.object(scheduler, "get_db_path", return_value=self.db_path), \
             patch.object(utils, "task_dir", return_value=self.task_dir):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            ch_default = payload["channels"][0]
            stock = ch_default["ready_stock"]
            self.assertEqual(stock["total"], 1)
            self.assertEqual(len(stock["items"]), 1)

            item = stock["items"][0]
            self.assertEqual(item["task_id"], t1_id)
            self.assertEqual(item["topic"], "Vídeo Elegível de Curiosidades")
            self.assertEqual(item["quality_score"], 88.5)
            self.assertEqual(item["safety_status"], "PASS")
            self.assertEqual(item["copyright_status"], "PASS")
            self.assertEqual(item["gate_status"], "APPROVED")
            self.assertIsNotNone(item["created_at"])
            self.assertIsNotNone(item["age_hours"])
            self.assertEqual(item["duration"], 42.5)

    def test_scheduled_posts_listing(self):
        """4. Posts agendados são listados corretamente por canal."""
        sched_time_1 = (datetime.now(timezone.utc) + timedelta(hours=2)).isoformat()
        sched_time_2 = (datetime.now(timezone.utc) + timedelta(hours=6)).isoformat()

        # Cria tasks para os tópicos
        sm.state.update_task("t-sched-1", video_subject="Tópico Agendado 1")
        sm.state.update_task("t-sched-2", video_subject="Tópico Agendado 2")

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES ('t-sched-1', 'youtube', ?, 'planned', '2026-10-26T00:00:00Z', 'default');
                """,
                (sched_time_1,),
            )
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES ('t-sched-2', 'youtube', ?, 'ready', '2026-10-26T00:00:00Z', 'default');
                """,
                (sched_time_2,),
            )
            # Post publicado não deve aparecer na fila
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                VALUES ('t-sched-old', 'youtube', '2026-10-25T00:00:00Z', 'published', '2026-10-25T00:00:00Z', 'default');
                """
            )

        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            ch_default = payload["channels"][0]
            sched = ch_default["scheduled"]
            self.assertEqual(sched["total"], 2)
            self.assertEqual(len(sched["items"]), 2)
            self.assertEqual(sched["items"][0]["task_id"], "t-sched-1")
            self.assertEqual(sched["items"][0]["topic"], "Tópico Agendado 1")
            self.assertEqual(sched["items"][0]["status"], "planned")
            self.assertEqual(sched["items"][1]["task_id"], "t-sched-2")
            self.assertEqual(sched["items"][1]["topic"], "Tópico Agendado 2")
            self.assertEqual(sched["items"][1]["status"], "ready")

    def test_recent_runs_with_failures_and_reasons(self):
        """5. Tarefas recentes das últimas 24h reportam status, estágios de falha e motivos gate_reason/error."""
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()
        two_hours_ago = (now - timedelta(hours=2)).isoformat()
        three_hours_ago = (now - timedelta(hours=3)).isoformat()

        # Run 1: SUCCESS
        t_succ = "task-run-success"
        sm.state.update_task(
            t_succ,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Sucesso Absoluto",
            created_at=three_hours_ago,
            finished_at=two_hours_ago,
            profile_id="default",
        )

        # Run 2: FAILED com erro e failed_stage
        t_fail = "task-run-failed"
        sm.state.update_task(
            t_fail,
            state=const.TASK_STATE_FAILED,
            video_subject="Falha de Render",
            failed_stage="RENDER",
            error="CUDA Out of Memory",
            created_at=two_hours_ago,
            finished_at=now_iso,
            profile_id="default",
        )

        # Run 3: REJECTED pelo safety gate com motivo
        t_rej = "task-run-rejected"
        sm.state.update_task(
            t_rej,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Rejeitado por Segurança",
            failed_stage="SAFETY",
            gate_reason="Conteúdo sensível detectado",
            created_at=two_hours_ago,
            finished_at=now_iso,
            profile_id="default",
        )

        # Run 4: RUNNING (em andamento)
        t_run = "task-run-running"
        sm.state.update_task(
            t_run,
            state=const.TASK_STATE_PROCESSING,
            video_subject="Em Produção Agora",
            progress=45,
            created_at=now_iso,
            profile_id="default",
        )

        # Run 5: Mais antigo que 24h -> Não deve aparecer
        t_old = "task-run-ancient"
        ancient_time = (now - timedelta(hours=36)).isoformat()
        sm.state.update_task(
            t_old,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Tarefa Antiga",
            created_at=ancient_time,
            finished_at=ancient_time,
            profile_id="default",
        )

        with scheduler.get_connection(self.db_path) as conn:
            for tid in (t_succ, t_fail, t_rej, t_run):
                conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (tid, now_iso))
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (t_old, ancient_time))

            # Atualiza safety table para a rejeição
            conn.execute(
                "INSERT INTO monetization_safety (task_id, preset, safety_status, safety_reasons, checked_at) VALUES (?, 'tech', 'FAIL', 'Conteúdo sensível detectado', ?);",
                (t_rej, now_iso),
            )

        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            runs = payload["channels"][0]["recent_runs"]
            self.assertEqual(runs["total"], 4)
            self.assertEqual(len(runs["items"]), 4)

            runs_by_id = {r["task_id"]: r for r in runs["items"]}

            # Valida SUCCESS
            self.assertEqual(runs_by_id[t_succ]["status"], "SUCCESS")
            self.assertIsNone(runs_by_id[t_succ]["failure_stage"])
            self.assertIsNone(runs_by_id[t_succ]["gate_reason"])
            self.assertIsNone(runs_by_id[t_succ]["error"])

            # Valida FAILED
            self.assertEqual(runs_by_id[t_fail]["status"], "FAILED")
            self.assertEqual(runs_by_id[t_fail]["failure_stage"], "RENDER")
            self.assertEqual(runs_by_id[t_fail]["error"], "CUDA Out of Memory")

            # Valida REJECTED
            self.assertEqual(runs_by_id[t_rej]["status"], "REJECTED")
            self.assertEqual(runs_by_id[t_rej]["failure_stage"], "SAFETY")
            self.assertEqual(runs_by_id[t_rej]["gate_reason"], "Conteúdo sensível detectado")

            # Valida RUNNING
            self.assertEqual(runs_by_id[t_run]["status"], "RUNNING")
            self.assertIsNone(runs_by_id[t_run]["finished_at"])

            # Valida Totais do Resumo
            totals = payload["totals"]
            self.assertEqual(totals["success_24h"], 1)
            self.assertEqual(totals["failed_24h"], 1)
            self.assertEqual(totals["rejected_24h"], 1)

    def test_filter_by_profile_id(self):
        """6. Parâmetro profile_id filtra exatamente o canal solicitado."""
        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)

            # Filtra por prof-quiz
            resp_quiz = client.get("/api/v2/production/overview?profile_id=prof-quiz")
            self.assertEqual(resp_quiz.status_code, 200)
            chans = resp_quiz.json()["data"]["channels"]
            self.assertEqual(len(chans), 1)
            self.assertEqual(chans[0]["profile_id"], "prof-quiz")
            self.assertEqual(chans[0]["profile_name"], "Canal de Quizzes")
            self.assertEqual(chans[0]["channel_name"], "Quiz Channel YT")
            self.assertEqual(chans[0]["video_format"], "quiz_paper")

            # Filtra por perfil inexistente -> retorna vazio
            resp_none = client.get("/api/v2/production/overview?profile_id=inexistente")
            self.assertEqual(resp_none.status_code, 200)
            data_none = resp_none.json()["data"]
            self.assertEqual(len(data_none["channels"]), 0)
            self.assertEqual(data_none["totals"]["ready_stock"], 0)

    def test_limit_per_section(self):
        """7. limit_per_section limita o número de itens retornados em items preservando total."""
        now_iso = datetime.now(timezone.utc).isoformat()

        # Cria 5 posts agendados
        with scheduler.get_connection(self.db_path) as conn:
            for i in range(5):
                t_sched = (datetime.now(timezone.utc) + timedelta(hours=i + 1)).isoformat()
                conn.execute(
                    """
                    INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id)
                    VALUES (?, 'youtube', ?, 'planned', ?, 'default');
                    """,
                    (f"task-batch-{i}", t_sched, now_iso),
                )

        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default&limit_per_section=2")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            sched = payload["channels"][0]["scheduled"]
            self.assertEqual(sched["total"], 5)
            self.assertEqual(len(sched["items"]), 2)

    def test_missing_fields_are_null_never_invented(self):
        """8. Campos ausentes são estritamente null (nunca inventados)."""
        now_iso = datetime.now(timezone.utc).isoformat()
        tid = "task-null-fields"
        sm.state.update_task(
            tid,
            state=const.TASK_STATE_COMPLETE,
            # Sem duration, sem topic, sem error
            created_at=now_iso,
            profile_id="default",
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (tid, now_iso))

        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            runs = payload["channels"][0]["recent_runs"]["items"]
            target = next(r for r in runs if r["task_id"] == tid)
            self.assertIsNone(target["topic"])
            self.assertIsNone(target["failure_stage"])
            self.assertIsNone(target["gate_reason"])
            self.assertIsNone(target["error"])

    def test_performance_under_two_seconds_and_caching(self):
        """9. Resposta executa em menos de 2s (performance sub-segundo) e cache efêmero funciona."""
        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)

            # 1. Medição de tempo fresh (sem cache)
            t0 = time.perf_counter()
            resp1 = client.get("/api/v2/production/overview")
            t_fresh = time.perf_counter() - t0

            self.assertEqual(resp1.status_code, 200)
            self.assertLess(t_fresh, 2.0, f"Tempo de resposta excedeu 2s: {t_fresh:.4f}s")

            # 2. Medição com cache quente
            t1 = time.perf_counter()
            resp2 = client.get("/api/v2/production/overview")
            t_cached = time.perf_counter() - t1

            self.assertEqual(resp2.status_code, 200)
            self.assertLess(t_cached, 0.1, f"Cache efêmero deveria responder em <100ms: {t_cached:.4f}s")
