"""Testes direcionados do Lote 3B: Regras Operacionais V1 (RN-01, RN-02, RN-03).

Ambiente isolado: feat/v1-lote3b-regras-negocio
Cobertura:
- RN-01: Limite de 2 aprovados em 24h em WARMUP, preservação dos demais modos e função única canônica de contagem.
- RN-02: Aprovação humana de score 55-69 liberada apenas com gates técnico, safety e copyright PASS; persistência pós-reinício.
- RN-03: Retenção de tarefas em REVIEW (HELD_FOR_REVIEW / HELD_SAFETY_REVIEW) sem incrementar consecutive_rejections nem inflar Circuit Breaker; isolamento de ready stock.
"""

import os
import sys

# Garante que o worktree do Lote 3B tenha precedência absoluta no sys.path
WORKTREE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if WORKTREE_ROOT not in sys.path:
    sys.path.insert(0, WORKTREE_ROOT)

import json
import math
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

from app.config import config
from app.models import const
from app.services import (
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    quality_recovery,
    quality_score,
    safety_gate,
    scheduler,
)


class TestLote3BOperationalRules(unittest.TestCase):
    def setUp(self):
        self.llm_patcher = patch.dict(config.app, {"llm_provider": "gemini"})
        self.llm_patcher.start()
        self.addCleanup(self.llm_patcher.stop)

        self.test_dir = tempfile.mkdtemp(prefix="test_lote3b_")
        self.db_path = os.path.join(self.test_dir, "test_turbo.db")
        self.task_base_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.task_dir_patcher = patch("app.utils.utils.task_dir", return_value=self.task_base_dir)
        self.task_dir_patcher.start()
        self.addCleanup(self.task_dir_patcher.stop)

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        operator_console.init_operator_db(self.db_path)
        quality_recovery.init_review_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        # Configura instância de teste como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        operator_console.resume_factory(db_path=self.db_path)
        scheduler.set_setting("scheduler_enabled", "true", db_path=self.db_path)
        scheduler.set_setting("auto_publish_enabled", "true", db_path=self.db_path)

        # Habilita modo autônomo para o perfil default nos testes
        autonomous_production.set_autonomous_mode_enabled(True, db_path=self.db_path)
        autonomous_production.set_profile_autonomous_mode_enabled(profile_manager.DEFAULT_PROFILE_ID, True, db_path=self.db_path)

        self.now = datetime(2026, 9, 19, 14, 0, 0, tzinfo=timezone.utc)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_mock_video(self, task_id: str, size: int = 1024) -> str:
        task_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        video_path = os.path.join(task_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"MOCK_MP4_DATA" * (size // 13 + 1))
        return video_path

    # =========================================================================
    # RN-01: WARMUP Limits & Canonical Counting
    # =========================================================================

    def test_rn01_warmup_max_generations_cap_is_two(self):
        """RN-01: Teto diário de gerações aprovadas em WARMUP deve ser estritamente 2."""
        with patch("app.services.autonomous_production.get_profile_growth_mode", return_value=const.GROWTH_MODE_WARMUP):
            cap = autonomous_production.get_max_generations_24h(profile_id="chan-warmup", db_path=self.db_path)
            self.assertEqual(cap, 2, "WARMUP deve limitar gerações aprovadas a 2 em 24h")

    def test_rn01_warmup_override_cannot_exceed_cap(self):
        """RN-01: Override persistido pode reduzir (ex: 1), mas não ultrapassar 2 em WARMUP."""
        with patch("app.services.autonomous_production.get_profile_growth_mode", return_value=const.GROWTH_MODE_WARMUP):
            autonomous_production.set_max_generations_24h(5, profile_id="chan-warmup", db_path=self.db_path)
            cap = autonomous_production.get_max_generations_24h(profile_id="chan-warmup", db_path=self.db_path)
            self.assertEqual(cap, 2, "Override de 5 deve ser limitado ao cap 2 de WARMUP")

            autonomous_production.set_max_generations_24h(1, profile_id="chan-warmup", db_path=self.db_path)
            cap = autonomous_production.get_max_generations_24h(profile_id="chan-warmup", db_path=self.db_path)
            self.assertEqual(cap, 1, "Override de 1 deve ser respeitado")

    def test_rn01_other_growth_modes_preserved(self):
        """RN-01: Demais modos operacionais preservados (SCALE=5, CONSERVATIVE/NORMAL mantidos)."""
        with patch("app.services.autonomous_production.get_profile_growth_mode", return_value=const.GROWTH_MODE_SCALE):
            cap_scale = autonomous_production.get_max_generations_24h(profile_id="chan-scale", db_path=self.db_path)
            self.assertEqual(cap_scale, 5, "SCALE deve ter teto de 5 gerações em 24h")

    def test_rn01_canonical_counting_by_channel(self):
        """RN-01: Função única count_generations_in_last_24h isola contagem por canal."""
        now = self.now
        iso_2h = (now - timedelta(hours=2)).isoformat()
        iso_5h = (now - timedelta(hours=5)).isoformat()
        iso_3h = (now - timedelta(hours=3)).isoformat()

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-chanA-1', 'Aprovado', ?);
                """,
                (iso_2h, json.dumps({"channel_id": "ch-A"})),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-chanA-2', 'Aprovado', ?);
                """,
                (iso_5h, json.dumps({"channel_id": "ch-A"})),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-chanB-1', 'Aprovado', ?);
                """,
                (iso_3h, json.dumps({"channel_id": "ch-B"})),
            )

        count_a = autonomous_production.count_generations_in_last_24h(now=now, db_path=self.db_path, channel_id="ch-A")
        count_b = autonomous_production.count_generations_in_last_24h(now=now, db_path=self.db_path, channel_id="ch-B")
        count_all = autonomous_production.count_generations_in_last_24h(now=now, db_path=self.db_path)

        self.assertEqual(count_a, 2, "Canal A deve ter exatamente 2 aprovações em 24h")
        self.assertEqual(count_b, 1, "Canal B deve ter exatamente 1 aprovação em 24h")
        self.assertEqual(count_all, 3, "Total global deve somar 3 aprovações")

    # =========================================================================
    # RN-02: Human Approval Sovereignty (Score 55-69)
    # =========================================================================

    def _setup_task_with_gates(
        self,
        task_id: str,
        quality_score_val: float,
        quality_label: str,
        safety_status: str,
        copyright_pass: bool = True,
        human_decision: str = None,
        operator_id: str = "operator_1",
        create_video: bool = True,
    ):
        v_path = self._create_mock_video(task_id) if create_video else None

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (task_id, f"Topic {task_id}", quality_score_val, quality_label, self.now.isoformat()),
            )

            conn.execute(
                """
                INSERT INTO monetization_safety (task_id, topic, preset, safety_status, safety_reasons, checked_at)
                VALUES (?, ?, 'quiz', ?, '[]', ?);
                """,
                (task_id, f"Topic {task_id}", safety_status, self.now.isoformat()),
            )

            if human_decision:
                conn.execute(
                    """
                    INSERT INTO operator_video_reviews (
                        task_id, decision, operator_id, note, original_score, recalculated_score,
                        approved_below_threshold, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        task_id,
                        human_decision,
                        operator_id,
                        "Aprovação humana RN-02",
                        quality_score_val,
                        quality_score_val,
                        1 if quality_score_val < 70 else 0,
                        self.now.isoformat(),
                        self.now.isoformat(),
                    ),
                )

        profile_id = f"prof_{task_id}"
        channel_id = f"chan_{task_id}"
        profile_manager.save_task_profile(task_id, profile_id, db_path=self.db_path)
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, is_active, created_at, updated_at) VALUES (?, ?, ?, 1, ?, ?);",
                (profile_id, f"Profile {profile_id}", profile_id, self.now.isoformat(), self.now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (
                    id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at
                ) VALUES (?, ?, 'youtube', 'Main Chan', 1, 1, ?, ?);
                """,
                (channel_id, profile_id, self.now.isoformat(), self.now.isoformat()),
            )

        return v_path

    def test_rn02_human_approval_enables_scheduling_for_score_55_to_69(self):
        """RN-02: Vídeo com score 62.5 / REVIEW com aprovação humana válida e gates PASS deve ser agendado."""
        task_id = "rn02-approved-62"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=62.5,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision="APPROVED",
            operator_id="senior_editor",
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 1, "Vídeo aprovado pelo operador deve ser agendado com sucesso")
        self.assertEqual(scheduled[0]["task_id"], task_id)
        self.assertEqual(scheduled[0]["platform"], "youtube")

    def test_rn02_unapproved_score_55_to_69_is_blocked(self):
        """RN-02: Vídeo com score 62.5 / REVIEW SEM aprovação humana deve ser ignorado pelo Scheduler."""
        task_id = "rn02-unapproved-62"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=62.5,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision=None,
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 0, "Vídeo sem aprovação humana deve ser bloqueado")

    def test_rn02_human_approval_cannot_bypass_safety_failure(self):
        """RN-02: Aprovação humana com Safety REVIEW ou BLOCK NÃO deve permitir agendamento."""
        task_id = "rn02-safety-block"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=65.0,
            quality_label="REVIEW",
            safety_status="BLOCK",
            copyright_pass=True,
            human_decision="APPROVED",
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "BLOCK",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 0, "Falha de Safety não pode ser ignorada por aprovação humana")

    def test_rn02_human_approval_cannot_bypass_copyright_failure(self):
        """RN-02: Aprovação humana com Copyright FAIL NÃO deve permitir agendamento."""
        task_id = "rn02-cp-fail"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=66.0,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=False,
            human_decision="APPROVED",
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(False, "AUDIO_STRIKE", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 0, "Falha de Copyright deve bloquear mesmo com aprovação humana")

    def test_rn02_human_approval_cannot_bypass_missing_or_corrupt_mp4(self):
        """RN-02: Aprovação humana sem arquivo MP4 íntegro NÃO deve permitir agendamento."""
        task_id = "rn02-missing-mp4"
        self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=68.0,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision="APPROVED",
            create_video=False,
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": os.path.join(self.task_base_dir, task_id, "non_existent.mp4"),
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 0, "Falta de MP4 íntegro deve bloquear agendamento")

    def test_rn02_human_approval_persists_across_restart_and_cycles(self):
        """RN-02: Decisão humana persiste no SQLite; ciclos posteriores do Scheduler preservam o agendamento."""
        task_id = "rn02-restart-test"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=63.0,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision="APPROVED",
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            sched1 = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            self.assertEqual(len(sched1), 1)

            scheduler.init_db(self.db_path)

            sched2 = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now + timedelta(minutes=5),
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
            self.assertEqual(len(sched2), 0, "Idempotência impede agendamento duplicado")

            with scheduler.get_connection(self.db_path) as conn:
                post = conn.execute(
                    "SELECT status, channel_id FROM scheduled_posts WHERE task_id = ? AND platform = 'youtube';",
                    (task_id,),
                ).fetchone()
                self.assertIsNotNone(post)
                self.assertIn(post["status"], ("planned", "ready"))

    # =========================================================================
    # RN-03: Review Retention & Circuit Breaker Protection
    # =========================================================================

    def test_rn03_review_retention_does_not_increment_consecutive_rejections(self):
        """RN-03: Tarefas retidas em REVIEW não devem incrementar consecutive_rejections nem inflar Circuit Breaker."""
        task_id = "rn03-review-hold-1"
        v_path = self._create_mock_video(task_id)

        profile_id = "default"
        self.assertEqual(autonomous_production.get_consecutive_rejections(self.db_path, profile_id), 0)

        from app.services import state as sm
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            video_file=v_path,
            video_subject="Dilema Épico",
            profile_id=profile_id,
            safety_status="PASS",
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, task_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.quality_score.evaluate_quality", return_value={
                 "quality_score": 64.0,
                 "quality_label": quality_score.LABEL_REVIEW,
                 "reasons": ["Borderline quality score"],
             }), \
             patch("app.services.webui_task.submit_generation") as mock_sub:

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)

            self.assertEqual(res.get("status"), "rejected")
            self.assertTrue(res.get("held_for_review"))
            self.assertEqual(res.get("stage"), "HELD_FOR_REVIEW")
            mock_sub.assert_not_called()

            consec = autonomous_production.get_consecutive_rejections(self.db_path, profile_id)
            self.assertEqual(consec, 0, "consecutive_rejections deve permanecer 0 após retenção em REVIEW")

    def test_rn03_repeated_reviews_do_not_trip_circuit_breaker(self):
        """RN-03: Múltiplas retenções em REVIEW consecutivas NÃO bloqueiam a fábrica por Circuit Breaker."""
        profile_id = "default"
        from app.services import state as sm

        for i in range(12):
            t_id = f"rn03-series-rev-{i}"
            v_path = self._create_mock_video(t_id)

            sm.state.update_task(
                t_id,
                state=const.TASK_STATE_COMPLETE,
                video_file=v_path,
                video_subject=f"Tema {i}",
                profile_id=profile_id,
                safety_status="PASS",
            )
            autonomous_production.set_autonomous_setting(
                autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, t_id, db_path=self.db_path
            )

            with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
                 patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
                 patch("app.services.quality_score.evaluate_quality", return_value={
                     "quality_score": 62.0,
                     "quality_label": quality_score.LABEL_REVIEW,
                 }), \
                 patch("app.services.webui_task.submit_generation"):

                res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
                self.assertTrue(res.get("held_for_review"))

        consec = autonomous_production.get_consecutive_rejections(self.db_path, profile_id)
        self.assertEqual(consec, 0, "Múltiplas revisões não inflam o contador de rejeições")

        state = autonomous_production.get_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_STATE, "unknown", db_path=self.db_path
        )
        self.assertNotEqual(state, autonomous_production.STATE_BLOCKED, "Fábrica não deve ser bloqueada por REVIEWs")

    def test_rn03_real_rejections_increment_circuit_breaker(self):
        """RN-03: Rejeições definitivas reais (ex: Safety BLOCK ou score < 55) continuam incrementando o contador."""
        profile_id = "default"
        from app.services import state as sm

        t_id = "rn03-real-block-1"
        v_path = self._create_mock_video(t_id)

        sm.state.update_task(
            t_id,
            state=const.TASK_STATE_COMPLETE,
            video_file=v_path,
            video_subject="Conteúdo Perigoso",
            profile_id=profile_id,
            safety_status="BLOCK",
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, t_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation"):

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "rejected")
            self.assertFalse(res.get("held_for_review", False))

        consec = autonomous_production.get_consecutive_rejections(self.db_path, profile_id)
        self.assertEqual(consec, 1, "Rejeição definitiva real deve incrementar consecutive_rejections")

    def test_rn03_review_tasks_excluded_from_autonomous_ready_stock(self):
        """RN-03: Vídeos em REVIEW não são promovidos a READY_STOCK nem contam no estoque pronto."""
        task_id = "rn03-stock-test"
        v_path = self._create_mock_video(task_id)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monetization_safety (task_id, topic, preset, safety_status, safety_reasons, checked_at) VALUES (?, ?, 'quiz', 'PASS', '[]', ?);",
                (task_id, f"Topic {task_id}", self.now.isoformat()),
            )
            conn.execute(
                "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, ?, 65.0, 'REVIEW', ?);",
                (task_id, f"Topic {task_id}", self.now.isoformat()),
            )

        from app.services import state as sm
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            video_file=v_path,
            stage="HELD_FOR_REVIEW",
            profile_id="default",
        )

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
        )
        ready_ids = [item.get("task_id") for item in stock.get("youtube_ready", [])]
        self.assertNotIn(task_id, ready_ids, "Tarefa retida em REVIEW não deve constar no estoque autônomo pronto")
# =========================================================================
    # CF-3B-01, CF-3B-02, CF-3B-03: Testes de Fronteira Obrigatórios
    # =========================================================================

    def test_cf3b01_final_media_quality_block_blocks_scheduling_even_with_valid_mp4(self):
        """CF-3B-01: final_media_quality = BLOCK com MP4 existente e não vazio: publicação bloqueada."""
        task_id = "cf3b01-fmq-block"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=65.0,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision="APPROVED",
        )

        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
            "final_media_quality_status": "BLOCK",
            "final_media_quality_reasons": ["AUDIO_SILENT", "CORRUPTED_FRAMES"],
        }

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            scheduled = scheduler.plan_schedule(
                tasks=[task_payload],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )

        self.assertEqual(len(scheduled), 0, "final_media_quality=BLOCK deve bloquear o agendamento mesmo com MP4 valido e aprovacao humana")

    def test_cf3b03_score_40_with_review_label_is_hard_rejection(self):
        """CF-3B-03: Score 40 com label REVIEW: não elegível para aprovação humana e contado como rejeição definitiva."""
        profile_id = "default"
        from app.services import state as sm

        t_id = "cf3b03-score40-review"
        v_path = self._create_mock_video(t_id)

        # Configura task com score 40 e label REVIEW
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO monetization_safety (task_id, topic, preset, safety_status, safety_reasons, checked_at) VALUES (?, ?, 'quiz', 'PASS', '[]', ?);",
                (t_id, f"Topic {t_id}", self.now.isoformat()),
            )
            conn.execute(
                "INSERT INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at) VALUES (?, ?, 40.0, 'REVIEW', ?);",
                (t_id, f"Topic {t_id}", self.now.isoformat()),
            )

        sm.state.update_task(
            t_id,
            state=const.TASK_STATE_COMPLETE,
            video_file=v_path,
            video_subject="Topico Baixa Qualidade",
            profile_id=profile_id,
            safety_status="PASS",
        )
        autonomous_production.set_autonomous_setting(
            autonomous_production.KEY_AUTONOMOUS_CURRENT_TASK_ID, t_id, db_path=self.db_path
        )

        with patch("app.services.webui_task.has_active_generation_tasks", return_value=False), \
             patch("app.services.scheduler.get_task_final_video", return_value=v_path), \
             patch("app.services.webui_task.submit_generation"), \
             patch("app.services.quality_score.evaluate_quality", return_value={"quality_score": 40.0, "quality_label": "REVIEW", "reasons": ["LOW_SCORE"]}):

            res = autonomous_production.run_autonomous_cycle(force=True, db_path=self.db_path, now=self.now)
            self.assertEqual(res.get("status"), "rejected")
            self.assertFalse(res.get("held_for_review", False), "Score 40 < 55 NÃO deve ficar retido para revisão humana")

        consec = autonomous_production.get_consecutive_rejections(self.db_path, profile_id)
        self.assertEqual(consec, 1, "Score 40 com label REVIEW deve contar como rejeição definitiva e incrementar consecutive_rejections")

    def test_cf3b02_two_channels_same_profile_without_scheduled_posts_independent_counting(self):
        """CF-3B-02: Dois canais no mesmo perfil sem scheduled_posts devem ter contagens estritamente independentes."""
        now = self.now
        iso_2h = (now - timedelta(hours=2)).isoformat()
        iso_4h = (now - timedelta(hours=4)).isoformat()
        profile_id = "prof-shared"
        channel_1 = "chan-shared-1"
        channel_2 = "chan-shared-2"

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT INTO content_profiles (id, name, slug, is_active, created_at, updated_at) VALUES (?, 'Shared Prof', 'shared', 1, ?, ?);",
                (profile_id, now.isoformat(), now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', 'Chan 1', 1, 1, ?, ?);
                """,
                (channel_1, profile_id, now.isoformat(), now.isoformat()),
            )
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', 'Chan 2', 1, 1, ?, ?);
                """,
                (channel_2, profile_id, now.isoformat(), now.isoformat()),
            )

            # Insere eventos de aprovação para chan-shared-1
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-sh1-1', 'Aprovado 1', ?);
                """,
                (iso_2h, json.dumps({"channel_id": channel_1, "profile_id": profile_id})),
            )
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-sh1-2', 'Aprovado 2', ?);
                """,
                (iso_4h, json.dumps({"channel_id": channel_1, "profile_id": profile_id})),
            )

            # Insere 1 evento de aprovação para chan-shared-2
            conn.execute(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, 'autonomous_production', 'INFO', 'generation_approved', 't-sh2-1', 'Aprovado 1', ?);
                """,
                (iso_2h, json.dumps({"channel_id": channel_2, "profile_id": profile_id})),
            )

        count_ch1 = autonomous_production.count_generations_in_last_24h(now=now, db_path=self.db_path, channel_id=channel_1)
        count_ch2 = autonomous_production.count_generations_in_last_24h(now=now, db_path=self.db_path, channel_id=channel_2)

        self.assertEqual(count_ch1, 2, "Canal 1 deve ter exatamente 2 aprovações")
        self.assertEqual(count_ch2, 1, "Canal 2 deve ter exatamente 1 aprovação, sem contaminação do Canal 1")

    def test_cf3b01_human_approval_cannot_bypass_safety_or_copyright_post_restart(self):
        """CF-3B-01: Aprovação humana persistente após reinício, sem contornar Safety/Copyright."""
        task_id = "cf3b01-post-restart"
        v_path = self._setup_task_with_gates(
            task_id=task_id,
            quality_score_val=60.0,
            quality_label="REVIEW",
            safety_status="PASS",
            copyright_pass=True,
            human_decision="APPROVED",
        )

        # Forja reinício da aplicação
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # 1. Com gates PASS, aprovação persiste após reinício e é agendada
        task_payload_clean = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "safety_status": "PASS",
            "profile_id": f"prof_{task_id}",
            "planned_platforms": ["youtube"],
        }
        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            sched_clean = scheduler.plan_schedule(
                tasks=[task_payload_clean],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
        self.assertEqual(len(sched_clean), 1, "Aprovação humana válida deve ser agendada após reinício")

        # 2. Agora simula falha persistida de Safety no banco: aprovação humana NÃO deve contornar
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE monetization_safety SET safety_status = 'BLOCK' WHERE task_id = ?;",
                (task_id,),
            )

        with patch("app.services.copyright_gate.evaluate_copyright_provenance_gate", return_value=(True, "CLEAN", {})):
            sched_blocked = scheduler.plan_schedule(
                tasks=[task_payload_clean],
                now=self.now,
                db_path=self.db_path,
                task_base_dir=self.task_base_dir,
            )
        self.assertEqual(len(sched_blocked), 0, "Safety BLOCK persistido deve bloquear mesmo com aprovação humana")

    def test_cf3b03_held_safety_review_persisted_in_script_json_and_respected_post_restart(self):
        """CF-3B-03: HELD_SAFETY_REVIEW persistido em script.json e respeitado após reinício."""
        task_id = "cf3b03-held-safety-persist"
        v_path = self._create_mock_video(task_id)

        # Cria script.json com HELD_SAFETY_REVIEW persistido em disco
        task_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        script_path = os.path.join(task_dir, "script.json")
        with open(script_path, "w", encoding="utf-8") as sf:
            json.dump({
                "task_id": task_id,
                "stage": "HELD_SAFETY_REVIEW",
                "gate_status": "held_for_review",
                "safety_status": "REVIEW",
                "video_file": v_path,
            }, sf)

        # Simula reinício da aplicação
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # is_task_held_for_safety_review deve detectar retenção a partir de script.json
        is_held, hold_reason = scheduler.is_task_held_for_safety_review(
            task_id=task_id,
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )
        self.assertTrue(is_held, "HELD_SAFETY_REVIEW deve ser detectado a partir de script.json após reinício")

        # plan_schedule deve bloquear agendamento
        task_payload = {
            "task_id": task_id,
            "state": const.TASK_STATE_COMPLETE,
            "video_file": v_path,
            "profile_id": "default",
            "planned_platforms": ["youtube"],
        }
        scheduled = scheduler.plan_schedule(
            tasks=[task_payload],
            now=self.now,
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )
        self.assertEqual(len(scheduled), 0, "Tarefa HELD_SAFETY_REVIEW em script.json deve ser bloqueada no agendamento")

if __name__ == "__main__":
    unittest.main()
