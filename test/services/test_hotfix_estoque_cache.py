"""Teste de regressão do Hotfix: Falha de cache UnboundLocalError plats_by_prof no estoque canônico.

Verifica que dentro de um único render_pass_scope, chamadas sucessivas a
get_canonical_ready_stock para múltiplos perfis (incluindo TikTok-only)
não levantam UnboundLocalError e retornam contagens idênticas às chamadas fora de escopo.
"""

import json
import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models import const
from app.services import (
    autonomous_production,
    operator_console,
    profile_manager,
    quality_score,
    safety_gate,
    scheduler,
    state as sm,
)


class TestHotfixEstoqueCache(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_cache_hotfix.db")
        self.task_base_dir = os.path.join(self.temp_dir.name, "tasks")
        os.makedirs(self.task_base_dir, exist_ok=True)

        self.task_dir_patcher = patch("app.utils.utils.task_dir", return_value=self.task_base_dir)
        self.task_dir_patcher.start()
        self.addCleanup(self.task_dir_patcher.stop)

        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        safety_gate.init_safety_db(self.db_path)
        quality_score.init_quality_db(self.db_path)

        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._instance_initialized = True
            operator_console._current_role = operator_console.ROLE_PRIMARY
        operator_console.resume_factory(db_path=self.db_path)

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.temp_dir.cleanup()

    def _create_dummy_task(
        self,
        task_id: str,
        profile_id: str,
        safety_status: str = "PASS",
        quality_score_val: float = 85.0,
        quality_label: str = "GOOD",
        duration: float = 40.0,
    ):
        video_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, "final-1.mp4")

        with open(video_path, "wb") as f:
            f.write(b"dummy_mp4_bytes_test_content")
        script_path = os.path.join(video_dir, "script.json")
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
            video_subject=f"Tema da task {task_id}",
            video_file=video_path,
            safety_status=safety_status,
            profile_id=profile_id,
            audio_duration=duration,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);",
                (task_id, profile_id, now_iso),
            )
            conn.execute(
                """
                INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (task_id, f"Tema da task {task_id}", quality_score_val, quality_label, now_iso),
            )

        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "topic": f"Tema da task {task_id}",
                "safety_status": safety_status,
                "safety_reasons": [] if safety_status == "PASS" else ["failed"],
                "checked_at": now_iso,
            },
            db_path=self.db_path,
        )

    def test_canonical_ready_stock_multiple_profiles_inside_render_pass_scope(self):
        """Dentro de um único render_pass_scope, chamadas sucessivas para múltiplos perfis

        (incluindo TikTok-only) não levantam UnboundLocalError e os totais batem
        com as chamadas feitas fora do escopo.
        """
        # 1. Configurar 3 perfis: YouTube-only, TikTok-only, Cross-platform
        prof_yt = profile_manager.create_profile(
            name="Canal YouTube", slug="canal-yt", niche="tech", db_path=self.db_path
        )
        prof_tt = profile_manager.create_profile(
            name="Canal TikTok Only", slug="canal-tt", niche="curiosidades", db_path=self.db_path
        )
        prof_both = profile_manager.create_profile(
            name="Canal Hibrido", slug="canal-both", niche="fatos", db_path=self.db_path
        )

        yt_id = prof_yt["id"]
        tt_id = prof_tt["id"]
        both_id = prof_both["id"]

        with scheduler.get_connection(self.db_path) as conn:
            # YouTube-only
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-yt-1', ?, 'youtube', 'YT Channel', 1, 1, datetime('now'), datetime('now'));
                """,
                (yt_id,),
            )
            # TikTok-only
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-tt-1', ?, 'tiktok', 'TT Channel', 1, 0, datetime('now'), datetime('now'));
                """,
                (tt_id,),
            )
            # Both
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-both-yt', ?, 'youtube', 'Both YT', 1, 1, datetime('now'), datetime('now')),
                       ('ch-both-tt', ?, 'tiktok', 'Both TT', 1, 1, datetime('now'), datetime('now'));
                """,
                (both_id, both_id),
            )

        # 2. Criar tarefas prontas: 2 para YT, 2 para TT, 1 para Both
        self._create_dummy_task("task-yt-1", yt_id)
        self._create_dummy_task("task-yt-2", yt_id)

        self._create_dummy_task("task-tt-1", tt_id)
        self._create_dummy_task("task-tt-2", tt_id)

        self._create_dummy_task("task-both-1", both_id)

        # 3. Chamadas de referência FORA de render_pass_scope
        out_yt = operator_console.get_canonical_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=yt_id
        )
        out_tt = operator_console.get_canonical_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=tt_id
        )
        out_both = operator_console.get_canonical_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=both_id
        )

        self.assertEqual(out_yt["total_ready"], 2)
        self.assertEqual(out_yt["youtube_count"], 2)
        self.assertEqual(out_yt["tiktok_count"], 0)

        self.assertEqual(out_tt["total_ready"], 2)
        self.assertEqual(out_tt["youtube_count"], 0)
        self.assertEqual(out_tt["tiktok_count"], 2)

        self.assertEqual(out_both["total_ready"], 1)
        self.assertEqual(out_both["youtube_count"], 1)
        self.assertEqual(out_both["tiktok_count"], 1)

        # 4. Chamadas DENTRO de um único render_pass_scope
        # Antes da correção, a 2ª chamada (tt_id) falha com UnboundLocalError:
        # cannot access local variable 'plats_by_prof' where it is not associated with a value
        with operator_console.render_pass_scope():
            in_yt = operator_console.get_canonical_ready_stock(
                task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=yt_id
            )
            in_tt = operator_console.get_canonical_ready_stock(
                task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=tt_id
            )
            in_both = operator_console.get_canonical_ready_stock(
                task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=both_id
            )

        # Provar que nenhum levantou e que os dados batem exatamente com as chamadas fora do escopo
        self.assertEqual(in_yt["total_ready"], out_yt["total_ready"])
        self.assertEqual(in_yt["youtube_count"], out_yt["youtube_count"])
        self.assertEqual(in_yt["tiktok_count"], out_yt["tiktok_count"])

        self.assertEqual(in_tt["total_ready"], out_tt["total_ready"])
        self.assertEqual(in_tt["youtube_count"], out_tt["youtube_count"])
        self.assertEqual(in_tt["tiktok_count"], out_tt["tiktok_count"])

        self.assertEqual(in_both["total_ready"], out_both["total_ready"])
        self.assertEqual(in_both["youtube_count"], out_both["youtube_count"])
        self.assertEqual(in_both["tiktok_count"], out_both["tiktok_count"])

        # 5. Provar que fleet_summary e profile_operations_overview não deixam ready_stock como None
        fleet = operator_console.get_fleet_summary(db_path=self.db_path)
        fleet_map = {c["profile_id"]: c for c in fleet.get("channels", [])}
        self.assertEqual(fleet_map[yt_id]["ready_stock"], 2)
        self.assertEqual(fleet_map[tt_id]["ready_stock"], 2)
        self.assertEqual(fleet_map[both_id]["ready_stock"], 1)

        overview = operator_console.get_profile_operations_overview(
            db_path=self.db_path, task_base_dir=self.task_base_dir
        )
        overview_map = {p["profile_id"]: p for p in overview}
        self.assertEqual(overview_map[yt_id]["ready_stock"], 2)
        self.assertEqual(overview_map[tt_id]["ready_stock"], 2)
        self.assertEqual(overview_map[both_id]["ready_stock"], 1)
