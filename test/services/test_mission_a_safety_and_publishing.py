"""
test/services/test_mission_a_safety_and_publishing.py
======================================================
TESTES DIRECIONADOS — MISSÃO A: SEGURANÇA E PUBLICAÇÃO V1

Validações obrigatórias:
1. Quiz reprovado não retorna ao estoque (invalidação em monetization_safety e quiz_safety_history).
2. Falha de duração não produz READY_STOCK.
3. Quality score alto não ignora bloqueio de segurança/copyright.
4. Falha do SQLite não promove PASS obsoleto em script.json.
5. Publicação manual respeita HELD_SAFETY_REVIEW.
6. Post for Me não troca de conta por fallback de banco.
"""

import json
import math
import os
import shutil
import sqlite3
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import (
    autonomous_production,
    post_for_me,
    profile_manager,
    quality_score,
    quiz_safety_gate,
    safety_gate,
    scheduler,
    task as tm,
)
from app.services import state as sm


class TestMissionASafetyAndPublishing(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_mission_a_")
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        profile_manager.init_profile_db(self.db_path)
        quality_score.init_quality_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quiz_safety_gate.init_quiz_safety_db(self.db_path)
        scheduler.init_db(self.db_path)

        # Configura perfil padrão ativo
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO content_profiles (id, name, slug, is_active, created_at, updated_at) "
                "VALUES ('default', 'Default Profile', 'default', 1, '2026-10-22T00:00:00Z', '2026-10-22T00:00:00Z');"
            )
            conn.execute(
                "INSERT OR REPLACE INTO content_profiles (id, name, slug, is_active, created_at, updated_at) "
                "VALUES ('profile-quiz', 'Quiz Profile', 'profile-quiz', 1, '2026-10-22T00:00:00Z', '2026-10-22T00:00:00Z');"
            )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_video_task(self, task_id, profile_id="default"):
        tdir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(tdir, exist_ok=True)
        vpath = os.path.join(tdir, "final-1.mp4")
        with open(vpath, "wb") as f:
            f.write(b"\x00" * 1024)
        script_file = os.path.join(tdir, "script.json")
        with open(script_file, "w", encoding="utf-8") as f:
            json.dump({
                "task_id": task_id,
                "video_file": vpath,
                "video_files": [vpath],
                "stage": "READY_STOCK",
                "safety_status": "PASS",
                "profile_id": profile_id,
            }, f)
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, '2026-10-22T00:00:00Z');",
                (task_id, profile_id),
            )
        return tdir, vpath

    # =========================================================================
    # 1. Quiz reprovado não retorna ao estoque
    # =========================================================================
    def test_quiz_failed_does_not_return_to_stock(self):
        task_id = "quiz-fail-stock-01"
        self._create_mock_video_task(task_id, profile_id="profile-quiz")

        # Insere aprovação inicial pré-render em ambas as tabelas
        now_iso = "2026-10-22T01:00:00Z"
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) VALUES (?, 'standard_shorts', 'PASS', ?);",
                (task_id, now_iso),
            )
            conn.execute(
                "INSERT INTO quiz_safety_history (task_id, profile_id, channel_id, topic, dilemmas_json, dilemma_count, safety_status, checked_at) "
                "VALUES (?, 'profile-quiz', 'ch-quiz', 'Dilemas', '[]', 8, 'PASS', ?);",
                (task_id, now_iso),
            )

        # Simula falha pós-render de duração chamando a invalidação
        quiz_safety_gate.invalidate_quiz_safety_record(
            task_id=task_id,
            stage="duration_safety",
            error="Duração 75.3s fora de [60.0s, 70.0s]",
            db_path=self.db_path,
        )

        # 1.1 Ambas as tabelas no SQLite devem registrar 'FAILED'
        with sqlite3.connect(self.db_path) as conn:
            conn.row_factory = sqlite3.Row
            row_qsh = conn.execute("SELECT safety_status, safety_reasons FROM quiz_safety_history WHERE task_id = ?;", (task_id,)).fetchone()
            row_ms = conn.execute("SELECT safety_status, safety_reasons FROM monetization_safety WHERE task_id = ?;", (task_id,)).fetchone()

        self.assertEqual(row_qsh["safety_status"], "FAILED")
        self.assertIn("duration_safety", row_qsh["safety_reasons"])
        self.assertEqual(row_ms["safety_status"], "FAILED")
        self.assertIn("duration_safety", row_ms["safety_reasons"])

        # 1.2 is_task_held_for_safety_review deve barrar imediatamente
        is_held, hold_reason = scheduler.is_task_held_for_safety_review(task_id, db_path=self.db_path, task_base_dir=self.task_base_dir)
        self.assertTrue(is_held)
        self.assertEqual(hold_reason, "FAILED")

        # 1.3 get_autonomous_ready_stock não deve incluir o vídeo
        ready_res = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id="profile-quiz",
        )
        ready_ids = [t["task_id"] for t in ready_res.get("youtube_ready", [])]
        self.assertNotIn(task_id, ready_ids)

    # =========================================================================
    # 2. Falha de duração não produz READY_STOCK
    # =========================================================================
    def test_duration_failure_does_not_produce_ready_stock(self):
        task_id = "dur-fail-not-ready"
        tdir, vpath = self._create_mock_video_task(task_id, profile_id="profile-quiz")

        params = VideoParams(
            video_subject="Quiz Dilemas",
            narrative_structure="quiz_dilemma",
            monetization_preset="standard_shorts",
        )

        mock_quiz = {
            "questions": [
                {
                    "id": "q1",
                    "header": "DILEMA 1",
                    "narration": "Você prefere ter asas ou respirar debaixo dágua?",
                    "top": {"text": "Asas", "image_query": "wings"},
                    "bottom": {"text": "Respirar água", "image_query": "underwater"},
                }
            ]
        }

        # 1. Duração editorial fora do intervalo [60.0s, 70.0s] (ex: 82.0s)
        mock_engine_over = MagicMock()
        mock_engine_over.render.return_value = {"duration": 82.0}
        with patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure", return_value=mock_quiz), \
             patch("app.services.quiz_generator.QuizContentGenerator.export_to_quiz_config", return_value=MagicMock()), \
             patch("app.services.quiz_assets.QuizAssetManager.process_quiz", return_value=mock_quiz), \
             patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": "PASS", "safety_reasons": []}), \
             patch("scripts.poc_quiz_render.QuizEngine", return_value=mock_engine_over):
            res = tm._run_quiz_pipeline(task_id=task_id, params=params)

        self.assertEqual(res["state"], const.TASK_STATE_FAILED)
        self.assertEqual(res["failed_stage"], "duration_safety")
        self.assertNotEqual(res.get("stage"), "READY_STOCK")

        # 2. Exceção inesperada na checagem pós-render: deve falhar fail-closed com duration_safety
        mock_engine_ok = MagicMock()
        mock_engine_ok.render.return_value = {"duration": 65.0}
        with patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure", return_value=mock_quiz), \
             patch("app.services.quiz_generator.QuizContentGenerator.export_to_quiz_config", return_value=MagicMock()), \
             patch("app.services.quiz_assets.QuizAssetManager.process_quiz", return_value=mock_quiz), \
             patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": "PASS", "safety_reasons": []}), \
             patch("scripts.poc_quiz_render.QuizEngine", return_value=mock_engine_ok), \
             patch("app.services.quiz_safety_gate.evaluate_quiz_duration_safety", side_effect=RuntimeError("FFprobe crash")):
            res_exc = tm._run_quiz_pipeline(task_id=task_id + "-exc", params=params)

        self.assertEqual(res_exc["state"], const.TASK_STATE_FAILED)
        self.assertEqual(res_exc["failed_stage"], "duration_safety")
        self.assertIn("Duration evaluation failed", res_exc["error"])

    # =========================================================================
    # 3. Quality score alto não ignora bloqueio de segurança
    # =========================================================================
    def test_high_quality_score_does_not_bypass_safety_block(self):
        task_id = "high-q-safety-block"
        self._create_mock_video_task(task_id, profile_id="profile-quiz")

        # Insere score alto (88.0, STRONG) mas segurança bloqueada em monetization_safety
        with sqlite3.connect(self.db_path) as conn:
            conn.execute(
                "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) "
                "VALUES (?, 'Quiz Topic', 88.0, 'STRONG', '2026-10-22T01:00:00Z');",
                (task_id,),
            )
            conn.execute(
                "INSERT INTO monetization_safety (task_id, preset, safety_status, checked_at) "
                "VALUES (?, 'standard_shorts', 'BLOCK', '2026-10-22T01:00:00Z');",
                (task_id,),
            )

        # 3.1 _recover_waiting_task deve rejeitar com erro técnico/safety mesmo com score 88.0
        with self.assertRaises(ValueError) as ctx:
            autonomous_production._recover_waiting_task(
                task_id=task_id,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
        self.assertIn("waiting_", str(ctx.exception))

        # 3.2 plan_schedule deve rejeitar a inclusão na agenda
        candidate_tasks = [{
            "task_id": task_id,
            "profile_id": "profile-quiz",
            "state": const.TASK_STATE_COMPLETE,
            "video_file": os.path.join(self.task_base_dir, task_id, "final-1.mp4"),
            "planned_platforms": ["youtube"],
        }]
        with patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.operator_console.is_factory_paused", return_value=False):
            scheduled = scheduler.plan_schedule(
                tasks=candidate_tasks,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            scheduled_ids = [p.get("task_id") for p in scheduled]
            self.assertNotIn(task_id, scheduled_ids)

    # =========================================================================
    # 4. Falha do SQLite não promove PASS obsoleto
    # =========================================================================
    def test_sqlite_read_failure_does_not_promote_stale_pass(self):
        task_id = "stale-pass-sqlite-err"
        self._create_mock_video_task(task_id, profile_id="profile-quiz")

        # Força erro de SQLite durante a checagem de retenção
        with patch("app.services.safety_gate.get_safety_assessment", side_effect=sqlite3.OperationalError("database is locked")):
            is_held, hold_reason = scheduler.is_task_held_for_safety_review(
                task_id=task_id,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            # Deve falhar fechado com retenção defensiva
            self.assertTrue(is_held)
            self.assertIn("DATABASE_UNAVAILABLE_HOLD", hold_reason)

        # Em validate_candidate_technical_and_safety_gates também deve falhar fechado
        with patch("app.services.safety_gate.get_safety_assessment", side_effect=sqlite3.OperationalError("database is locked")):
            ts_ok, ts_reason, _ = scheduler.validate_candidate_technical_and_safety_gates(
                task_id=task_id,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            self.assertFalse(ts_ok)
            self.assertTrue("SAFETY_GATE_DB_ERROR" in ts_reason or "DATABASE_UNAVAILABLE_HOLD" in ts_reason)

    # =========================================================================
    # 5. Publicação manual respeita HELD_SAFETY_REVIEW
    # =========================================================================
    def test_manual_publish_respects_held_safety_review(self):
        task_id = "manual-pub-held-block"
        tdir, vpath = self._create_mock_video_task(task_id, profile_id="default")

        # Cria canal válido no banco
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO publishing_channels (id, profile_id, platform, display_name, external_account_id, is_enabled, created_at, updated_at) "
                "VALUES ('channel-def-yt', 'default', 'youtube', 'Default YouTube', 'UCss-ng7mkGuB2v-5KKtIN9A', 1, '2026-10-22T00:00:00Z', '2026-10-22T00:00:00Z');"
            )

        # Define tarefa como COMPLETE mas com retenção em HELD_SAFETY_REVIEW
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            stage="HELD_SAFETY_REVIEW",
            safety_status=const.SAFETY_STATUS_REVIEW,
            videos=[vpath],
        )

        with patch("app.services.operator_console.is_primary_instance", return_value=True), \
             patch("app.services.operator_console.is_factory_paused", return_value=False), \
             patch("app.utils.utils.task_dir", return_value=self.task_base_dir):

            success, msg = tm.publish_task(
                task_id=task_id,
                platforms=["youtube"],
                channel_id="channel-def-yt",
                db_path=self.db_path,
            )

        self.assertFalse(success)
        self.assertIn("held for safety review", msg.lower())

    # =========================================================================
    # 6. Post for Me não troca de conta por fallback de banco
    # =========================================================================
    def test_post_for_me_does_not_switch_account_on_db_fallback(self):
        # 6.1 Canal customizado específico que não existe no banco com profile_id='default'
        # NÃO deve cair no fallback para CHANNEL_DEFAULT_YT_ID; deve retornar None (Fail Closed)
        resolved_unknown = post_for_me.resolve_target_youtube_channel_id(
            channel_id="channel-custom-inexistente",
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertIsNone(resolved_unknown)

        # 6.2 Erro de leitura do SQLite com channel_id específico também NÃO deve ir para default
        with patch("app.services.profile_manager.get_connection", side_effect=sqlite3.OperationalError("disk I/O error")):
            resolved_err = post_for_me.resolve_target_youtube_channel_id(
                channel_id="channel-custom-qualquer",
                profile_id="default",
                db_path=self.db_path,
            )
            self.assertIsNone(resolved_err)

        # 6.3 Legítimo fallback quando channel_id não foi informado continua funcionando normalmente
        resolved_legit_def = post_for_me.resolve_target_youtube_channel_id(
            channel_id=None,
            profile_id="default",
            db_path=self.db_path,
        )
        self.assertEqual(resolved_legit_def, post_for_me.CHANNEL_DEFAULT_YT_ID)


if __name__ == "__main__":
    unittest.main()
