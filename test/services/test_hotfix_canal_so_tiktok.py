"""Testes de homologação do Hotfix: Suporte a canais com destino exclusivo TikTok.

Verifica:
1. Canal só TikTok (reproduzindo JOANA com 10 vídeos aprovados) conta estoque pronto 10/10 SEM regerar;
2. Canal só YouTube idêntico ao comportamento anterior (sem regressão);
3. Canal YouTube+TikTok idêntico ao comportamento anterior;
4. Canal sem destinos habilitados bloqueia fail-closed no ciclo e no status canônico (NO_PUBLISH_DESTINATION);
5. Vídeo já publicado no TikTok é devidamente excluído do estoque;
6. Safety/qualidade reprovados não contam no estoque;
7. Isolamento estrito entre perfis (sem vazamento de estoque).
"""

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
from app.services.channel_status import evaluate_canonical_channel_status


class TestHotfixCanalSoTikTok(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_hotfix.db")
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

        # Configura instância como PRIMARY
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
        quality_score_val: float = 80.0,
        quality_label: str = "GOOD",
        duration: float = 45.0,
        create_video_file: bool = True,
    ):
        """Cria ambiente persistente completo para uma task no SQLite e disco."""
        video_dir = os.path.join(self.task_base_dir, task_id)
        os.makedirs(video_dir, exist_ok=True)
        video_path = os.path.join(video_dir, "final-1.mp4")

        if create_video_file:
            with open(video_path, "wb") as f:
                f.write(b"dummy_mp4_bytes_content_for_test")
            script_path = os.path.join(video_dir, "script.json")
            import json
            with open(script_path, "w", encoding="utf-8") as f:
                json.dump({
                    "params": {"bgm_type": "none"},
                    "asset_provenance": {
                        "bgm": {"enabled": False, "source": "none"},
                        "visual_clips": [{"provider": "pexels", "local_file": video_path}]
                    }
                }, f)

        # Estado em memória
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            video_subject=f"Tema da task {task_id}",
            video_file=video_path if create_video_file else None,
            safety_status=safety_status,
            profile_id=profile_id,
            audio_duration=duration,
        )

        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            # task_profiles
            conn.execute(
                "INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at) VALUES (?, ?, ?);",
                (task_id, profile_id, now_iso),
            )
            # content_quality_scores
            conn.execute(
                """
                INSERT OR REPLACE INTO content_quality_scores (task_id, topic, quality_score, quality_label, created_at)
                VALUES (?, ?, ?, ?, ?);
                """,
                (task_id, f"Tema da task {task_id}", quality_score_val, quality_label, now_iso),
            )

        # monetization_safety
        safety_gate.save_safety_assessment(
            {
                "task_id": task_id,
                "topic": f"Tema da task {task_id}",
                "safety_status": safety_status,
                "safety_reasons": [] if safety_status == "PASS" else ["safety_failed"],
                "checked_at": now_iso,
            },
            db_path=self.db_path,
        )

    def test_1_joana_reconciliation_10_approved_videos_tiktok_only_counts_stock(self):
        """Item 3 & 7: Perfil JOANA (só TikTok) com 10 vídeos aprovados conta 10/10 no estoque e ciclo fica IDLE."""
        joana_profile_id = "profile-fedbb1f8fd20"
        joana_channel_id = "channel-3b60996bfc4f"

        # Cria perfil JOANA
        profile_manager.create_profile(
            name="Joana TikTok",
            slug="joana-tiktok",
            niche="curiosidades",
            db_path=self.db_path,
        )
        # Atualiza o ID para o ID real da PROD
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "UPDATE content_profiles SET id = ? WHERE slug = 'joana-tiktok';",
                (joana_profile_id,),
            )
            # Cria APENAS canal TikTok (auto_publish_authorized = 0, exatamente como na PROD)
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'tiktok', 'Joana Curiosidades', 1, 0, datetime('now'), datetime('now'));
                """,
                (joana_channel_id, joana_profile_id),
            )

        # Meta de estoque = 10
        autonomous_production.set_target_ready_stock(10, profile_id=joana_profile_id, db_path=self.db_path)
        autonomous_production.set_profile_autonomous_mode_enabled(joana_profile_id, True, db_path=self.db_path)

        # Cria os 10 vídeos aprovados (Safety PASS, Quality 78-83 GOOD, arquivos existentes)
        for i in range(1, 11):
            tid = f"task-joana-{i:02d}"
            self._create_dummy_task(
                task_id=tid,
                profile_id=joana_profile_id,
                safety_status="PASS",
                quality_score_val=78.0 + (i % 6),
                quality_label="GOOD",
                duration=45.0,
            )

        # 1. Valida get_autonomous_ready_stock
        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=joana_profile_id,
        )
        self.assertEqual(stock["ready_count"], 10, "Estoque pronto de JOANA deve contar 10 vídeos")
        self.assertEqual(stock["tiktok_count"], 10, "Contagem TikTok de JOANA deve ser 10")
        self.assertEqual(stock["youtube_count"], 0, "Contagem YouTube de JOANA deve ser 0 (canal sem YouTube)")
        self.assertEqual(stock["target_stock"], 10)
        self.assertFalse(stock["is_below_target"], "Estoque 10/10 não deve estar abaixo da meta")

        # 2. Valida operator_console.get_canonical_ready_stock
        canon_stock = operator_console.get_canonical_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=joana_profile_id,
        )
        self.assertEqual(canon_stock["total_ready"], 10)
        self.assertEqual(canon_stock["tiktok_count"], 10)
        self.assertEqual(canon_stock["youtube_count"], 0)
        self.assertFalse(canon_stock["is_below_minimum"])

        # 3. Valida que o loop autônomo NÃO gera vídeos adicionais quando estoque pronto >= meta
        cycle_res = autonomous_production.run_autonomous_cycle(
            profile_id=joana_profile_id,
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )
        self.assertEqual(cycle_res["status"], "idle")
        self.assertEqual(cycle_res["ready_stock"], 10)
        self.assertIn("Estoque pronto suficiente", cycle_res["message"])

    def test_2_profile_youtube_only_identical_to_previous_behavior(self):
        """Item 7: Canal só YouTube funciona exatamente como antes (sem regressão)."""
        yt_prof_id = "profile-youtube-only"
        yt_chan_id = "channel-youtube-only"

        profile_manager.create_profile(name="YT Only", slug="yt-only", niche="fatos", db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'yt-only';", (yt_prof_id,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', 'YT Fatos', 1, 1, datetime('now'), datetime('now'));
                """,
                (yt_chan_id, yt_prof_id),
            )

        autonomous_production.set_target_ready_stock(3, profile_id=yt_prof_id, db_path=self.db_path)

        for i in range(1, 3):
            self._create_dummy_task(
                task_id=f"task-yt-{i}",
                profile_id=yt_prof_id,
                safety_status="PASS",
                quality_score_val=85.0,
                quality_label="STRONG",
            )

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=yt_prof_id,
        )
        self.assertEqual(stock["ready_count"], 2)
        self.assertEqual(stock["youtube_count"], 2)
        self.assertEqual(stock["tiktok_count"], 0)
        self.assertTrue(stock["is_below_target"])

    def test_3_profile_youtube_and_tiktok_identical_to_previous_behavior(self):
        """Item 7: Canal YouTube+TikTok mantém comportamento anterior (ambos ativos)."""
        multi_prof_id = "profile-multi-dest"
        profile_manager.create_profile(name="Multi", slug="multi", niche="historia", db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'multi';", (multi_prof_id,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-yt-m', ?, 'youtube', 'Multi YT', 1, 1, datetime('now'), datetime('now')),
                       ('ch-tt-m', ?, 'tiktok', 'Multi TT', 1, 0, datetime('now'), datetime('now'));
                """,
                (multi_prof_id, multi_prof_id),
            )

        plats = autonomous_production.get_channel_active_platforms(multi_prof_id, db_path=self.db_path)
        self.assertEqual(plats, ["youtube", "tiktok"])

        self._create_dummy_task(
            task_id="task-multi-1",
            profile_id=multi_prof_id,
            safety_status="PASS",
            quality_score_val=80.0,
            quality_label="GOOD",
            duration=50.0,
        )

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=multi_prof_id,
        )
        self.assertEqual(stock["ready_count"], 1)
        self.assertEqual(stock["youtube_count"], 1)
        self.assertEqual(stock["tiktok_count"], 1)

    def test_4_profile_no_destinations_fail_closed_blocked(self):
        """Item 5 & 7: Perfil sem destinos habilitados bloqueia no ciclo e status canônico retorna NO_PUBLISH_DESTINATION."""
        no_dest_prof_id = "profile-sem-destinos"
        profile_manager.create_profile(name="Sem Destinos", slug="sem-destinos", niche="teste", db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'sem-destinos';", (no_dest_prof_id,))

        autonomous_production.set_profile_autonomous_mode_enabled(no_dest_prof_id, True, db_path=self.db_path)

        # 1. get_channel_active_platforms retorna []
        plats = autonomous_production.get_channel_active_platforms(no_dest_prof_id, db_path=self.db_path)
        self.assertEqual(plats, [])

        # 2. Ciclo autônomo bloqueia fail-closed sem gerar nada
        res = autonomous_production.run_autonomous_cycle(
            profile_id=no_dest_prof_id,
            db_path=self.db_path,
            task_base_dir=self.task_base_dir,
        )
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["reason"], "no_publish_destination")
        self.assertIn("Nenhum canal/destino de publicação habilitado", res["message"])

        # 3. Status canônico do canal mostra Bloqueado com reason_code NO_PUBLISH_DESTINATION
        status_info = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            has_publish_destination=bool(plats),
            auto_state=res.get("status", ""),
            auto_message=res.get("message"),
        )
        self.assertEqual(status_info["status"], "blocked")
        self.assertEqual(status_info["label"], "Bloqueado")
        self.assertEqual(status_info["reason_code"], "NO_PUBLISH_DESTINATION")
        self.assertIn("Nenhum canal/destino de publicação habilitado", status_info["reason"])

    def test_5_tiktok_already_published_task_excluded_from_stock(self):
        """Item 7: Vídeo já publicado no TikTok não conta no estoque pronto do perfil TikTok."""
        prof_id = "profile-tt-published"
        profile_manager.create_profile(name="TT Pub", slug="tt-pub", niche="humor", db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'tt-pub';", (prof_id,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-tt-pub', ?, 'tiktok', 'TT Humor', 1, 0, datetime('now'), datetime('now'));
                """,
                (prof_id,),
            )

        # Cria task completa
        self._create_dummy_task(
            task_id="task-tt-already-pub",
            profile_id=prof_id,
            safety_status="PASS",
            quality_score_val=82.0,
            quality_label="GOOD",
        )

        # Antes de publicar: estoque = 1
        stock_before = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=prof_id,
        )
        self.assertEqual(stock_before["ready_count"], 1)

        # Registra publicação com sucesso no TikTok
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO publication_events (task_id, platform, status, published_at, external_url)
                VALUES ('task-tt-already-pub', 'tiktok', 'success', datetime('now'), 'https://tiktok.com/@post/123');
                """,
            )

        # Depois de publicar: estoque = 0
        stock_after = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=prof_id,
        )
        self.assertEqual(stock_after["ready_count"], 0, "Task publicada no TikTok não deve contar no estoque")

    def test_6_safety_or_quality_rejected_excluded_from_stock(self):
        """Item 7: Tarefas com Safety FAIL ou qualidade baixa/reprovada não entram no estoque TikTok."""
        prof_id = "profile-tt-rejections"
        profile_manager.create_profile(name="TT Rej", slug="tt-rej", niche="ciencia", db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'tt-rej';", (prof_id,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-tt-rej', ?, 'tiktok', 'TT Ciencia', 1, 0, datetime('now'), datetime('now'));
                """,
                (prof_id,),
            )

        # 1. Safety FAIL
        self._create_dummy_task("task-safety-fail", prof_id, safety_status="FAIL", quality_score_val=85.0)
        # 2. Qualidade < 70
        self._create_dummy_task("task-low-qual", prof_id, safety_status="PASS", quality_score_val=62.0, quality_label="FAIR")
        # 3. Qualidade com label POOR
        self._create_dummy_task("task-poor-qual", prof_id, safety_status="PASS", quality_score_val=75.0, quality_label="POOR")
        # 4. Arquivo de vídeo final inexistente
        self._create_dummy_task("task-no-video", prof_id, safety_status="PASS", quality_score_val=85.0, quality_label="GOOD", create_video_file=False)

        stock = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir,
            db_path=self.db_path,
            profile_id=prof_id,
        )
        self.assertEqual(stock["ready_count"], 0, "Nenhuma tarefa reprovada deve entrar no estoque pronto")

    def test_7_strict_profile_isolation(self):
        """Item 7: Isolamento estrito entre perfis — estoque de JOANA não vaza para outro perfil."""
        prof_a = "profile-joana-iso"
        prof_b = "profile-outro-iso"

        profile_manager.create_profile(name="Joana Iso", slug="joana-iso", niche="fatos", db_path=self.db_path)
        profile_manager.create_profile(name="Outro Iso", slug="outro-iso", niche="jogos", db_path=self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'joana-iso';", (prof_a,))
            conn.execute("UPDATE content_profiles SET id = ? WHERE slug = 'outro-iso';", (prof_b,))
            conn.execute(
                """
                INSERT INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES ('ch-joana-iso', ?, 'tiktok', 'Joana', 1, 0, datetime('now'), datetime('now')),
                       ('ch-outro-iso', ?, 'youtube', 'Outro', 1, 1, datetime('now'), datetime('now'));
                """,
                (prof_a, prof_b),
            )

        # 3 tarefas para o Perfil A (JOANA)
        for i in range(1, 4):
            self._create_dummy_task(f"task-iso-a-{i}", prof_a, safety_status="PASS", quality_score_val=80.0, quality_label="GOOD")

        # Estoque de A deve ser 3
        stock_a = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=prof_a
        )
        self.assertEqual(stock_a["ready_count"], 3)
        self.assertEqual(stock_a["tiktok_count"], 3)
        self.assertEqual(stock_a["youtube_count"], 0)

        # Estoque de B deve ser 0 (não vaza nada de A)
        stock_b = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=self.task_base_dir, db_path=self.db_path, profile_id=prof_b
        )
        self.assertEqual(stock_b["ready_count"], 0)
        self.assertEqual(stock_b["tiktok_count"], 0)
        self.assertEqual(stock_b["youtube_count"], 0)


if __name__ == "__main__":
    unittest.main()
