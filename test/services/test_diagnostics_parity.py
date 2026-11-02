"""test/services/test_diagnostics_parity.py
=========================================
Teste de paridade estrita do serviço de Diagnósticos de Produção:
Compara a saída COMPLETA de get_diagnostics_overview entre:
- main (commit 333f883)
- branch atual (v2/performance-estoque)

Verifica que para todos os canais (incluindo canal só-TikTok e canal YouTube+TikTok):
- approvals_24h é idêntico
- ready_stock é idêntico
- status é idêntico
- diagnoses (códigos, severidades, evidências e textos) são idênticos
- A saída completa de get_diagnostics_overview tem diff rigorosamente VAZIO.
"""
from __future__ import annotations

import importlib.util
import json
import os
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    production_diagnostics as branch_diagnostics,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
)


def _has_commit(commit_ref: str = "333f883^{commit}") -> bool:
    """Verifica se um commit existe no repositório local via git cat-file."""
    try:
        res = subprocess.run(
            ["git", "cat-file", "-e", commit_ref],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return res.returncode == 0
    except Exception:
        return False


def _load_main_diagnostics_module():
    """Carrega dinamicamente a versão de production_diagnostics de main (333f883)."""
    if not _has_commit("333f883^{commit}"):
        return None
    try:
        main_code = subprocess.check_output(
            ["git", "show", "333f883:app/services/production_diagnostics.py"],
            text=True,
            encoding="utf-8",
            stderr=subprocess.DEVNULL,
        )
        spec = importlib.util.spec_from_loader("production_diagnostics_main", loader=None)
        main_mod = importlib.util.module_from_spec(spec)
        exec(main_code, main_mod.__dict__)
        return main_mod
    except Exception:
        return None


MAIN_DIAGNOSTICS = _load_main_diagnostics_module()


class TestDiagnosticsParity(unittest.TestCase):
    def setUp(self):
        if not _has_commit("333f883^{commit}") or MAIN_DIAGNOSTICS is None:
            self.skipTest(
                "Commit 333f883 não encontrado no repositório local "
                "(git cat-file -e 333f883^{commit} falhou). Pulando teste de paridade."
            )
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "parity_test.db")
        self.task_base_dir = os.path.join(self.temp_dir.name, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.task_dir_patcher = patch("app.utils.utils.task_dir", return_value=self.task_base_dir)
        self.task_dir_patcher.start()
        self.addCleanup(self.task_dir_patcher.stop)

        # Inicializa tabelas
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        # Configura papel PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY
        operator_console.resume_factory(db_path=self.db_path)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.temp_dir.cleanup()

    def _create_task(
        self,
        task_id: str,
        profile_id: str,
        safety_status: str = "PASS",
        quality_score_val: float = 85.0,
        create_final_video: bool = True,
        started_at: datetime | None = None,
    ) -> str:
        task_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(task_dir, exist_ok=True)
        video_path = os.path.join(task_dir, "final-1.mp4")

        if create_final_video:
            with open(video_path, "wb") as f:
                f.write(b"mp4_sample_video_bytes_for_testing")
            script_path = os.path.join(task_dir, "script.json")
            with open(script_path, "w", encoding="utf-8") as f:
                json.dump({
                    "params": {"bgm_type": "none"},
                    "asset_provenance": {
                        "bgm": {"enabled": False, "source": "none"},
                        "visual_clips": [{"provider": "pexels", "local_file": video_path}]
                    }
                }, f)

        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject=f"Tema da tarefa {task_id}",
            video_file=video_path if create_final_video else None,
            safety_status=safety_status,
            profile_id=profile_id,
            audio_duration=45.0,
        )

        ts_iso = (started_at or datetime.now(timezone.utc)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);",
                (task_id, profile_id, ts_iso),
            )
            if quality_score_val is not None:
                conn.execute(
                    """
                    INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
                    VALUES (?, ?, ?, ?, ?);
                    """,
                    (task_id, f"Tema da tarefa {task_id}", quality_score_val, "GOOD", ts_iso),
                )

        if safety_status:
            safety_gate.save_safety_assessment(
                {
                    "task_id": task_id,
                    "topic": f"Tema da tarefa {task_id}",
                    "safety_status": safety_status,
                    "safety_reasons": [] if safety_status == "PASS" else ["safety_failure"],
                    "checked_at": ts_iso,
                },
                db_path=self.db_path,
            )

        return video_path

    @unittest.skipUnless(
        _has_commit("333f883^{commit}"),
        "Commit 333f883 não encontrado no repositório local (git cat-file -e 333f883^{commit} falhou).",
    )
    def test_parity_full_diagnostics_overview_main_vs_branch(self):
        """Compara a saída completa de get_diagnostics_overview entre main e branch."""
        now_fixed = datetime(2026, 11, 1, 12, 0, 0, tzinfo=timezone.utc)
        h24_ago = now_fixed - timedelta(hours=24)
        t_recent = now_fixed - timedelta(hours=2)
        t_stuck = now_fixed - timedelta(hours=3)

        # 1. Configura Canais no banco
        # Canal A: Só TikTok (ex.: Joana)
        pid_tiktok = "prof-tiktok-only"
        chid_tiktok = "chan-tiktok-01"
        profile_manager.create_profile(
            name="Joana TikTok",
            slug="joana-tiktok",
            niche="curiosidades",
            db_path=self.db_path,
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'joana-tiktok';", (pid_tiktok,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'tiktok', 'Joana Curiosidades', 1, 0, ?, ?);
                """,
                (chid_tiktok, pid_tiktok, h24_ago.isoformat(), h24_ago.isoformat()),
            )

        # Canal B: YouTube + TikTok (Canal Duplo)
        pid_dual = "prof-dual-channel"
        chid_yt_dual = "chan-yt-dual-02"
        chid_tt_dual = "chan-tt-dual-02"
        profile_manager.create_profile(
            name="Canal Duplo YT e TT",
            slug="canal-duplo",
            niche="tecnologia",
            db_path=self.db_path,
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'canal-duplo';", (pid_dual,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', 'Tech Tube', 1, 1, ?, ?),
                       (?, ?, 'tiktok', 'Tech TikTok', 1, 0, ?, ?);
                """,
                (chid_yt_dual, pid_dual, h24_ago.isoformat(), h24_ago.isoformat(),
                 chid_tt_dual, pid_dual, h24_ago.isoformat(), h24_ago.isoformat()),
            )

        # Canal C: Só YouTube
        pid_yt = "prof-youtube-only"
        chid_yt_only = "chan-yt-only-03"
        profile_manager.create_profile(
            name="Canal Apenas YouTube",
            slug="canal-yt-only",
            niche="financas",
            db_path=self.db_path,
        )
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'canal-yt-only';", (pid_yt,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', 'Financas Tube', 1, 1, ?, ?);
                """,
                (chid_yt_only, pid_yt, h24_ago.isoformat(), h24_ago.isoformat()),
            )

        # 2. Popula Tarefas e Estoque
        # Para prof-tiktok-only: 2 tarefas prontas em estoque, 1 tarefa aprovada há 2h
        self._create_task("task_tt_1", pid_tiktok, safety_status="PASS", quality_score_val=88.0, started_at=t_recent)
        self._create_task("task_tt_2", pid_tiktok, safety_status="PASS", quality_score_val=92.0, started_at=t_recent)

        # Para prof-dual-channel:
        # - task_dual_1: em estoque
        self._create_task("task_dual_1", pid_dual, safety_status="PASS", quality_score_val=80.0, started_at=t_recent)
        # - task_dual_stuck: renderizada e segura, mas sem qualidade ou agendamento iniciada há 3h -> diagnostico de travada
        self._create_task("task_dual_stuck", pid_dual, safety_status="PASS", quality_score_val=None, create_final_video=True, started_at=t_stuck)

        # Para prof-youtube-only: 1 tarefa em estoque
        self._create_task("task_yt_1", pid_yt, safety_status="PASS", quality_score_val=85.0, started_at=t_recent)

        # 3. Popula Eventos Operacionais (operational_events)
        with scheduler.get_connection(self.db_path) as conn:
            # Eventos de geração iniciada e aprovada nas últimas 24h
            events_data = [
                # TikTok: 1 aprovada
                (t_recent.isoformat(), "autonomous_production", "info", "generation_started", "task_tt_1", "Started", json.dumps({"profile_id": pid_tiktok})),
                (t_recent.isoformat(), "autonomous_production", "info", "generation_approved", "task_tt_1", "Approved", json.dumps({"profile_id": pid_tiktok})),
                # Dual Channel: 2 aprovadas (associadas a chid_yt_dual)
                (t_recent.isoformat(), "autonomous_production", "info", "generation_started", "task_dual_1", "Started", json.dumps({"profile_id": pid_dual, "channel_id": chid_yt_dual})),
                (t_recent.isoformat(), "autonomous_production", "info", "generation_approved", "task_dual_1", "Approved", json.dumps({"profile_id": pid_dual, "channel_id": chid_yt_dual})),
                (t_recent.isoformat(), "autonomous_production", "info", "generation_started", "task_dual_stuck", "Started", json.dumps({"profile_id": pid_dual, "channel_id": chid_yt_dual})),
                # YouTube only: 1 aprovada (associada a chid_yt_only)
                (t_recent.isoformat(), "autonomous_production", "info", "generation_started", "task_yt_1", "Started", json.dumps({"profile_id": pid_yt, "channel_id": chid_yt_only})),
                (t_recent.isoformat(), "autonomous_production", "info", "generation_approved", "task_yt_1", "Approved", json.dumps({"profile_id": pid_yt, "channel_id": chid_yt_only})),
            ]
            conn.executemany(
                """
                INSERT INTO operational_events (timestamp, component, severity, event_type, task_id, message, metadata_json)
                VALUES (?, ?, ?, ?, ?, ?, ?);
                """,
                events_data,
            )

        # 4. Executa get_diagnostics_overview em MAIN e em BRANCH
        main_result = MAIN_DIAGNOSTICS.get_diagnostics_overview(
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
            now=now_fixed,
        )

        branch_result = branch_diagnostics.get_diagnostics_overview(
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
            now=now_fixed,
        )

        # 5. Asserções por canal:
        # Extrai dicionários por canal
        main_channels_by_pid = {c["profile_id"]: c for c in main_result["channels"]}
        branch_channels_by_pid = {c["profile_id"]: c for c in branch_result["channels"]}

        self.assertEqual(set(main_channels_by_pid.keys()), set(branch_channels_by_pid.keys()))

        # A) Canal só-TikTok:
        ch_tt_main = main_channels_by_pid[pid_tiktok]
        ch_tt_branch = branch_channels_by_pid[pid_tiktok]
        self.assertEqual(ch_tt_main["limits"]["approved_24h"], ch_tt_branch["limits"]["approved_24h"])
        self.assertEqual(ch_tt_main["counts_24h"], ch_tt_branch["counts_24h"])
        self.assertEqual(ch_tt_main["ready_stock"], ch_tt_branch["ready_stock"])
        self.assertEqual(ch_tt_main["status"], ch_tt_branch["status"])
        self.assertEqual(ch_tt_main["diagnoses"], ch_tt_branch["diagnoses"])
        self.assertEqual(ch_tt_main["ready_stock"]["count"], 2)

        # B) Canal YouTube+TikTok:
        ch_dual_main = main_channels_by_pid[pid_dual]
        ch_dual_branch = branch_channels_by_pid[pid_dual]
        self.assertEqual(ch_dual_main["limits"]["approved_24h"], ch_dual_branch["limits"]["approved_24h"])
        self.assertEqual(ch_dual_main["counts_24h"], ch_dual_branch["counts_24h"])
        self.assertEqual(ch_dual_main["ready_stock"], ch_dual_branch["ready_stock"])
        self.assertEqual(ch_dual_main["status"], ch_dual_branch["status"])
        self.assertEqual(ch_dual_main["diagnoses"], ch_dual_branch["diagnoses"])

        # C) Canal só-YouTube:
        ch_yt_main = main_channels_by_pid[pid_yt]
        ch_yt_branch = branch_channels_by_pid[pid_yt]
        self.assertEqual(ch_yt_main["limits"]["approved_24h"], ch_yt_branch["limits"]["approved_24h"])
        self.assertEqual(ch_yt_main["counts_24h"], ch_yt_branch["counts_24h"])
        self.assertEqual(ch_yt_main["ready_stock"], ch_yt_branch["ready_stock"])
        self.assertEqual(ch_yt_main["status"], ch_yt_branch["status"])
        self.assertEqual(ch_yt_main["diagnoses"], ch_yt_branch["diagnoses"])

        # 6. Asserção global de Paridade Total: o diff completo tem que ser VAZIO
        # Compara JSON serializado para garantir paridade estrutural total
        main_json = json.dumps(main_result, sort_keys=True, indent=2, ensure_ascii=False)
        branch_json = json.dumps(branch_result, sort_keys=True, indent=2, ensure_ascii=False)

        if main_json != branch_json:
            import difflib
            diff = difflib.unified_diff(
                main_json.splitlines(keepends=True),
                branch_json.splitlines(keepends=True),
                fromfile="main_333f883",
                tofile="branch_v2_performance_estoque",
            )
            diff_text = "".join(diff)
            self.fail(f"Divergência detectada entre main e branch:\n{diff_text}")

        # Se chegou aqui, diff é VAZIO!
        self.assertEqual(main_result, branch_result)
