import os
import shutil
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.models import const
from app.services import scheduler
from app.services import task as task_module
from app.services import state as sm


from app.utils import utils


class TestPublicationPersistence(unittest.TestCase):
    """Testes para validação da separação entre platform_post_id (external_id) e provider_request_id."""

    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_pub.db")
        scheduler.init_db(self.db_path)
        self.now = datetime(2026, 9, 16, 21, 0, 0, tzinfo=timezone.utc)
        self.created_task_dirs = []

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)
        for td in self.created_task_dirs:
            shutil.rmtree(td, ignore_errors=True)

    def _create_task(self, task_id: str) -> str:
        t_dir = utils.task_dir(task_id)
        os.makedirs(t_dir, exist_ok=True)
        self.created_task_dirs.append(t_dir)
        v_path = os.path.join(t_dir, "final-1.mp4")
        with open(v_path, "wb") as f:
            f.write(b"video_data")
        scheduler.save_task_platforms(task_id, ["youtube"], db_path=self.db_path)
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, scheduled_at, status, created_at)
                VALUES (?, 'youtube', ?, 'ready', ?);
                """,
                (task_id, scheduler._to_iso(self.now), scheduler._to_iso(self.now)),
            )
        sm.state.update_task(
            task_id,
            state=const.TASK_STATE_COMPLETE,
            progress=100,
            videos=[v_path],
            video_subject="Teste de Persistencia",
        )
        return v_path

    # 1. YouTube post_id vai para o campo correto (external_id) e provider_request_id separado
    def test_01_youtube_post_id_stored_in_external_id_and_request_id_in_provider_request_id(self):
        task_id = "task_pub_yt_ids"
        self._create_task(task_id)

        mock_response = {
            "success": True,
            "results": {
                "youtube": {
                    "success": True,
                    "post_id": "SMRl-CWMRTQ",
                    "url": "Post uploaded as Private.",
                }
            },
            "request_id": "575e369eee38400f82c5cd0d81bd57b5",
        }

        with patch("app.services.upload_post.cross_post_video", return_value=mock_response):
            success, err = task_module.publish_task(
                task_id,
                platforms=["youtube"],
                synchronous=True,
                db_path=self.db_path,
            )

        self.assertTrue(success)
        self.assertEqual(err, "")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ev = conn.execute("SELECT * FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()
        conn.close()

        self.assertIsNotNone(ev)
        self.assertEqual(ev["platform"], "youtube")
        self.assertEqual(ev["status"], "success")
        self.assertEqual(ev["external_id"], "SMRl-CWMRTQ")
        self.assertEqual(ev["provider_request_id"], "575e369eee38400f82c5cd0d81bd57b5")

    # 2. provider request_id é preservado separadamente
    def test_02_provider_request_id_preserved_separately_in_record_publication_event(self):
        task_id = "task_direct_event"
        scheduler.record_publication_event(
            task_id=task_id,
            platform="youtube",
            status="success",
            external_id="yt_custom_999",
            provider_request_id="req_up_888",
            db_path=self.db_path,
        )

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ev = conn.execute("SELECT * FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()
        conn.close()

        self.assertIsNotNone(ev)
        self.assertEqual(ev["external_id"], "yt_custom_999")
        self.assertEqual(ev["provider_request_id"], "req_up_888")

    # 3. ausência de post_id não quebra publicação
    def test_03_absence_of_post_id_does_not_break_publication(self):
        task_id = "task_no_post_id"
        self._create_task(task_id)

        # Resposta sem post_id dentro de youtube (ex.: plataforma retornou apenas status)
        mock_response = {
            "success": True,
            "results": {
                "youtube": {
                    "success": True,
                }
            },
            "request_id": "req_provider_only_123",
        }

        with patch("app.services.upload_post.cross_post_video", return_value=mock_response):
            success, err = task_module.publish_task(
                task_id,
                platforms=["youtube"],
                synchronous=True,
                db_path=self.db_path,
            )

        self.assertTrue(success)
        self.assertEqual(err, "")

        conn = sqlite3.connect(self.db_path)
        conn.row_factory = sqlite3.Row
        ev = conn.execute("SELECT * FROM publication_events WHERE task_id = ?;", (task_id,)).fetchone()
        conn.close()

        self.assertIsNotNone(ev)
        self.assertIsNone(ev["external_id"])
        self.assertEqual(ev["provider_request_id"], "req_provider_only_123")

    # 4. migração preserva registros existentes
    def test_04_migration_preserves_existing_records(self):
        legacy_db_path = os.path.join(self.test_dir, "legacy.db")
        conn = sqlite3.connect(legacy_db_path)
        # Cria tabela antiga SEM provider_request_id
        conn.execute(
            """
            CREATE TABLE publication_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                published_at TEXT NOT NULL,
                status TEXT NOT NULL,
                external_id TEXT,
                error_code TEXT
            );
            """
        )
        conn.execute(
            """
            INSERT INTO publication_events (task_id, platform, published_at, status, external_id)
            VALUES ('legacy_task', 'youtube', '2026-09-16T12:00:00+00:00', 'success', 'legacy_ext_123');
            """
        )
        conn.commit()
        conn.close()

        # Executa init_db que chama _run_migrations
        scheduler.init_db(legacy_db_path)

        conn = sqlite3.connect(legacy_db_path)
        conn.row_factory = sqlite3.Row
        # Verifica se a nova coluna foi adicionada
        cols = [r["name"] for r in conn.execute("PRAGMA table_info(publication_events);").fetchall()]
        self.assertIn("provider_request_id", cols)

        # Verifica que o registro antigo permaneceu inalterado
        row = conn.execute("SELECT * FROM publication_events WHERE task_id = 'legacy_task';").fetchone()
        conn.close()

        self.assertIsNotNone(row)
        self.assertEqual(row["external_id"], "legacy_ext_123")
        self.assertIsNone(row["provider_request_id"])

    # 5. override de privacyStatus para unlisted na chamada de publicação
    def test_05_youtube_privacy_status_override_unlisted(self):
        task_id = "task_pub_yt_unlisted"
        self._create_task(task_id)

        captured_extra = {}

        def fake_cross_post(*args, **kwargs):
            nonlocal captured_extra
            captured_extra = kwargs.get("youtube_extra") or {}
            return {
                "success": True,
                "results": {
                    "youtube": {
                        "success": True,
                        "post_id": "yt_unlisted_123",
                        "url": "https://www.youtube.com/watch?v=yt_unlisted_123",
                    }
                },
                "request_id": "req_unlisted_456",
            }

        with patch("app.services.upload_post.cross_post_video", side_effect=fake_cross_post):
            success, err = task_module.publish_task(
                task_id,
                platforms=["youtube"],
                synchronous=True,
                youtube_privacy_status="unlisted",
                db_path=self.db_path,
            )

        self.assertTrue(success)
        self.assertEqual(captured_extra.get("privacyStatus"), "unlisted")


if __name__ == "__main__":
    unittest.main()
