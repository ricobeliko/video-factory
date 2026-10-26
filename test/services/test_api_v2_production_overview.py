"""Testes do Endpoint de Produção V2 (Missão P1 / P1b — GET /api/v2/production/overview).

Valida:
1. Rota /api/v2/production/overview registrada no FastAPI e no OpenAPI;
2. Estoque de vídeos prontos respeita as regras canônicas (mp4 físico, safety PASS, quality >= 70, canal YouTube ativo e não publicado);
3. Posts agendados (scheduled_posts);
4. Tarefas recentes (recent_runs) nas últimas 24h com status (SUCCESS, FAILED, REJECTED, RUNNING, UNKNOWN);
5. Filtro por profile_id;
6. Limite por seção (limit_per_section);
7. Campos ausentes serializados como null (nunca inventados):
   - copyright ausente -> null
   - estado desconhecido -> UNKNOWN
   - reprovado sem etapa -> failure_stage é null (sem inferir SAFETY/QUALITY)
   - gate_status não inferido de safety PASS -> null
8. Totais únicos sem duplicatas: total_ready, total_scheduled, total_runs_24h, success_24h, failed_24h, rejected_24h, running_24h, unknown_24h;
9. Banco/canal vazio retorna listas vazias;
10. Desempenho com banco sintético grande (20.000 task_profiles, 5.000 tasks em 6 perfis): frio < 1.5s, em cache < 50ms.
"""
from __future__ import annotations

import json
import os
import sqlite3
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
                "bgm": {
                    "enabled": False,
                    "filename": None,
                    "source": "none",
                    "license_type": "none",
                    "provenance_status": "SAFE_NO_BGM",
                },
                "visual_clips": [
                    {"provider": "pexels", "asset_id": "999", "local_file": "v1.mp4", "duration": 5}
                ],
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
        """2. Quando não há tarefas nem posts, retorna estrutura completa com listas vazias e totais únicos."""
        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            payload = data.get("data", {})

            self.assertIn("totals", payload)
            self.assertIn("channels", payload)
            expected_totals = {
                "total_ready": 0,
                "total_scheduled": 0,
                "total_runs_24h": 0,
                "success_24h": 0,
                "failed_24h": 0,
                "rejected_24h": 0,
                "running_24h": 0,
                "unknown_24h": 0,
            }
            self.assertEqual(payload["totals"], expected_totals)

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
            # gate_status não é inferido de safety_status
            self.assertIsNone(item["gate_status"])
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

            # Valida Totais Únicos do Resumo
            totals = payload["totals"]
            self.assertEqual(totals["success_24h"], 1)
            self.assertEqual(totals["failed_24h"], 1)
            self.assertEqual(totals["rejected_24h"], 1)
            self.assertEqual(totals["running_24h"], 1)
            self.assertEqual(totals["unknown_24h"], 0)
            self.assertEqual(totals["total_runs_24h"], 4)

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
            self.assertEqual(data_none["totals"]["total_ready"], 0)

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
        """8. Campos ausentes são estritamente null (nunca inventados):
        - copyright ausente -> null
        - estado desconhecido -> UNKNOWN
        - reprovado sem etapa -> failure_stage é null (não inventar SAFETY/QUALITY)
        - gate_status não inferido de safety PASS -> null
        """
        now = datetime.now(timezone.utc)
        now_iso = now.isoformat()

        # 1. Task sem campos opcionais (topic, duration, error, failure_stage, gate_reason)
        tid1 = "task-null-fields"
        sm.state.update_task(
            tid1,
            state=const.TASK_STATE_COMPLETE,
            created_at=now_iso,
            profile_id="default",
        )

        # 2. Task com estado desconhecido (state não reconhecido) -> deve retornar UNKNOWN
        tid_unknown = "task-unknown-state"
        sm.state.update_task(
            tid_unknown,
            state="some_unrecognized_state",
            video_subject="Vídeo Estado Estranho",
            created_at=now_iso,
            profile_id="default",
        )

        # 3. Task rejeitada sem etapa de falha informada -> failure_stage deve ser null (não SAFETY/QUALITY)
        tid_rej_no_stage = "task-rej-no-stage"
        sm.state.update_task(
            tid_rej_no_stage,
            state=const.TASK_STATE_COMPLETE,
            video_subject="Rejeitado Sem Etapa",
            created_at=now_iso,
            profile_id="default",
        )

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (tid1, now_iso))
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (tid_unknown, now_iso))
            conn.execute("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, 'default', ?);", (tid_rej_no_stage, now_iso))
            # Injeta safety FAIL sem informar failure_stage
            conn.execute(
                "INSERT INTO monetization_safety (task_id, preset, safety_status, safety_reasons, checked_at) VALUES (?, 'tech', 'FAIL', 'Motivo x', ?);",
                (tid_rej_no_stage, now_iso),
            )

        with patch.object(scheduler, "get_db_path", return_value=self.db_path):
            client = TestClient(asgi.app)
            resp = client.get("/api/v2/production/overview?profile_id=default")
            self.assertEqual(resp.status_code, 200)
            payload = resp.json()["data"]

            runs = payload["channels"][0]["recent_runs"]["items"]
            runs_by_id = {r["task_id"]: r for r in runs}

            # Caso 1: campos ausentes são null
            t1 = runs_by_id[tid1]
            self.assertIsNone(t1["topic"])
            self.assertIsNone(t1["failure_stage"])
            self.assertIsNone(t1["gate_reason"])
            self.assertIsNone(t1["error"])
            self.assertEqual(t1["status"], "SUCCESS")

            # Caso 2: estado desconhecido -> UNKNOWN
            t_unk = runs_by_id[tid_unknown]
            self.assertEqual(t_unk["status"], "UNKNOWN")

            # Caso 3: reprovado sem etapa -> failure_stage é estritamente null (não SAFETY nem QUALITY)
            t_rej = runs_by_id[tid_rej_no_stage]
            self.assertEqual(t_rej["status"], "REJECTED")
            self.assertIsNone(t_rej["failure_stage"])
            self.assertEqual(t_rej["gate_reason"], "Motivo x")

            # Valida totais com unknown_24h incrementado
            self.assertEqual(payload["totals"]["unknown_24h"], 1)

    def test_performance_under_two_seconds_and_caching(self):
        """9. Resposta executa em menos de 2s e cache efêmero funciona."""
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

    def test_performance_large_synthetic_database(self):
        """10. Desempenho com banco sintético grande (20.000 task_profiles, 5.000 tasks em 6 perfis):
        - Frio < 1.5s
        - Em cache < 50ms
        """
        temp_dir = tempfile.TemporaryDirectory()
        synth_db = os.path.join(temp_dir.name, "synthetic_large.db")

        try:
            scheduler.init_db(synth_db)
            profile_manager.init_profile_db(synth_db)

            conn = sqlite3.connect(synth_db)
            profiles = [f"prof-{i}" for i in range(1, 7)]
            for pid in profiles:
                conn.execute(
                    """
                    INSERT INTO content_profiles (id, name, slug, niche, default_preset, growth_mode, is_active, settings_json, created_at, updated_at)
                    VALUES (?, ?, ?, 'tech', 'traditional', 'SCALE', 1, '{"editorial": {"video_format": "traditional"}}', '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');
                    """,
                    (pid, f"Channel {pid}", pid),
                )
                conn.execute(
                    """
                    INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
                    VALUES (?, ?, 'youtube', ?, 1, '2026-10-01T00:00:00Z', '2026-10-01T00:00:00Z');
                    """,
                    (f"chan-{pid}", pid, f"YT {pid}"),
                )

            now = datetime.now(timezone.utc)
            old_time = (now - timedelta(days=5)).isoformat()
            recent_time = (now - timedelta(hours=2)).isoformat()

            # 20.000 task_profiles
            tp_data = [(f"task-{i}", profiles[i % 6], recent_time if i < 1000 else old_time) for i in range(20000)]
            conn.executemany("INSERT INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);", tp_data)

            # 5.000 tasks
            conn.execute("CREATE TABLE IF NOT EXISTS tasks (task_id TEXT PRIMARY KEY, video_subject TEXT, state TEXT, created_at TEXT, updated_at TEXT);")
            t_data = [(f"task-{i}", f"Topic {i}", "complete", recent_time if i < 300 else old_time, recent_time if i < 300 else old_time) for i in range(5000)]
            conn.executemany("INSERT INTO tasks (task_id, video_subject, state, created_at, updated_at) VALUES (?, ?, ?, ?, ?);", t_data)

            # 100 scheduled posts
            sp_data = [(f"task-sched-{i}", "youtube", recent_time, "planned", recent_time, profiles[i % 6]) for i in range(100)]
            conn.executemany("INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at, profile_id) VALUES (?, ?, ?, ?, ?, ?);", sp_data)

            conn.commit()
            conn.close()

            production_overview.clear_production_overview_cache()

            # 1. Execução Fria (sem cache)
            t0 = time.perf_counter()
            res_cold = production_overview.get_production_overview(db_path=synth_db, use_cache=True)
            t_cold = time.perf_counter() - t0

            self.assertLess(t_cold, 1.5, f"Tempo frio excedeu a meta de 1.5s: {t_cold:.4f}s")
            self.assertEqual(len(res_cold["channels"]), 6)
            self.assertEqual(res_cold["totals"]["total_runs_24h"], 1000)

            # 2. Execução com Cache
            t1 = time.perf_counter()
            res_cached = production_overview.get_production_overview(db_path=synth_db, use_cache=True)
            t_cached = time.perf_counter() - t1

            self.assertLess(t_cached, 0.05, f"Tempo em cache excedeu 50ms: {t_cached*1000:.2f}ms")
            self.assertEqual(res_cold["totals"], res_cached["totals"])

        finally:
            temp_dir.cleanup()
