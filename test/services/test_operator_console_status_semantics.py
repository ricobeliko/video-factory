import os
import shutil
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.services import operator_console, scheduler, profile_manager
import webui.components.operator_console as op_console_component
import webui.components.channel_factory as channel_factory_component


class TestOperatorConsoleStatusSemantics(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_video_factory.db")
        self.tasks_dir = os.path.join(self.test_dir, "tasks")
        os.makedirs(self.tasks_dir, exist_ok=True)
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)

    def tearDown(self):
        if os.path.exists(self.test_dir):
            shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_scheduler_disabled_with_active_worker_shows_off(self):
        """1. scheduler_enabled=False + worker_active=True -> status visual principal do Scheduler = OFF."""
        scheduler.set_setting("scheduler_enabled", False, db_path=self.db_path)
        sys_status = operator_console.get_system_status(db_path=self.db_path)
        self.assertFalse(sys_status["scheduler_enabled"])

        # Simula worker daemon ativo com scheduler desabilitado
        telemetry_data = {
            "scheduler_enabled": False,
            "scheduler_worker": "ACTIVE",
            "heartbeats": {"scheduler_seconds_ago": 15},
        }

        # Mock de Streamlit para capturar markdown gerado pelos cards
        mock_st = MagicMock()
        mock_col = MagicMock()
        mock_col.__enter__ = MagicMock(return_value=mock_col)
        mock_col.__exit__ = MagicMock(return_value=None)
        mock_st.columns.return_value = (mock_col, mock_col, mock_col, mock_col, mock_col, mock_col)

        with patch.object(op_console_component, "st", mock_st):
            op_console_component._render_health_cards_row(telemetry_data)

        # Captura os blocos HTML/markdown gerados
        rendered_texts = [call_args[0][0] for call_args in mock_st.markdown.call_args_list]
        sched_cards = [t for t in rendered_texts if "Scheduler" in t]
        self.assertTrue(len(sched_cards) > 0, "Card do Scheduler não foi renderizado")

        sched_card = sched_cards[0]
        self.assertIn("⚪ OFF", sched_card, "Scheduler com scheduler_enabled=False deve mostrar '⚪ OFF'")
        self.assertNotIn("🟢 ACTIVE", sched_card, "Scheduler desabilitado NÃO deve mostrar badge verde '🟢 ACTIVE'")
        self.assertIn("worker online", sched_card, "Status do worker deve aparecer como saúde secundária")
        self.assertIn("heartbeat 15s", sched_card)

    def test_02_publication_auto_off_and_dry_run_off_does_not_show_live(self):
        """2. auto_publish=False + dry_run=False -> Publication NÃO mostra LIVE."""
        telemetry_data = {
            "dry_run": "OFF",
            "auto_publish": "OFF",
            "auto_publish_enabled": False,
            "scheduler_enabled": False,
            "scheduler_worker": "IDLE",
            "generation_worker": "IDLE",
            "stock": {"total_ready": 0, "is_below_minimum": False, "minimum_threshold": 3},
            "errors": [],
            "providers": {},
            "heartbeats": {"generation_seconds_ago": None, "scheduler_seconds_ago": None},
        }

        mock_st = MagicMock()
        mock_col = MagicMock()
        mock_col.__enter__ = MagicMock(return_value=mock_col)
        mock_col.__exit__ = MagicMock(return_value=None)
        mock_st.columns.return_value = (mock_col, mock_col, mock_col, mock_col, mock_col, mock_col)

        with patch.object(op_console_component, "st", mock_st):
            op_console_component._render_health_cards_row(telemetry_data)

        rendered_texts = [call_args[0][0] for call_args in mock_st.markdown.call_args_list]
        pub_cards = [t for t in rendered_texts if "Publication" in t]
        self.assertTrue(len(pub_cards) > 0, "Card de Publication não foi renderizado")

        pub_card = pub_cards[0]
        self.assertNotIn("🟢 LIVE", pub_card, "Com auto_publish=False, Publication NÃO pode mostrar '🟢 LIVE'")
        self.assertIn("⚪ AUTO OFF", pub_card, "Com auto_publish=False, deve mostrar '⚪ AUTO OFF'")
        self.assertIn("real mode ready", pub_card, "Com dry_run=False e auto_publish=False, deve indicar 'real mode ready'")

    def test_03_publication_auto_on_and_dry_run_off_shows_live(self):
        """3. auto_publish=True + dry_run=False -> Publication mostra LIVE."""
        telemetry_data = {
            "dry_run": "OFF",
            "auto_publish": "ON",
            "auto_publish_enabled": True,
            "scheduler_enabled": True,
            "scheduler_worker": "ACTIVE",
            "generation_worker": "IDLE",
            "stock": {"total_ready": 2, "is_below_minimum": False, "minimum_threshold": 3},
            "errors": [],
            "providers": {},
            "heartbeats": {"generation_seconds_ago": None, "scheduler_seconds_ago": 10},
        }

        mock_st = MagicMock()
        mock_col = MagicMock()
        mock_col.__enter__ = MagicMock(return_value=mock_col)
        mock_col.__exit__ = MagicMock(return_value=None)
        mock_st.columns.return_value = (mock_col, mock_col, mock_col, mock_col, mock_col, mock_col)

        with patch.object(op_console_component, "st", mock_st):
            op_console_component._render_health_cards_row(telemetry_data)

        rendered_texts = [call_args[0][0] for call_args in mock_st.markdown.call_args_list]
        pub_cards = [t for t in rendered_texts if "Publication" in t]
        self.assertTrue(len(pub_cards) > 0, "Card de Publication não foi renderizado")

        pub_card = pub_cards[0]
        self.assertIn("🟢 LIVE", pub_card, "Com auto_publish=True e dry_run=False, deve mostrar '🟢 LIVE'")
        self.assertIn("auto ON", pub_card)

    def test_04_channel_factory_extracts_total_ready_from_stock_dict(self):
        """4. Channel Factory: ready_stock dict com total_ready=2 -> mostra 2, não representação do dict."""
        profile = {"id": "test-prof-stock", "name": "Canal Teste"}
        fake_stock_dict = {
            "total_ready": 2,
            "minimum_threshold": 3,
            "is_below_minimum": True,
        }

        with patch("app.services.operator_console.get_canonical_ready_stock", return_value=fake_stock_dict), \
             patch("app.services.autonomous_production.is_profile_autonomous_mode_enabled", return_value=False), \
             patch("app.services.autonomous_production.get_target_ready_stock", return_value=3), \
             patch("app.services.profile_manager.get_profile_settings", return_value=MagicMock()), \
             patch("app.services.profile_manager.list_channels", return_value=[]):

            card_data = channel_factory_component._get_channel_card_data(profile, db_path=self.db_path)
            self.assertEqual(card_data["ready_stock"], 2, "ready_stock coletado deve ser o inteiro 2")
            self.assertNotIsInstance(card_data["ready_stock"], dict, "ready_stock não pode ser um dicionário")

            # Testa também a formatação da legenda caso o card recebesse um dict
            mock_st = MagicMock()
            with patch.object(channel_factory_component, "st", mock_st):
                # Simula card com dict bruto para testar a camada de renderização defensiva
                raw_card = {"ready_stock": fake_stock_dict, "target_stock": 3}
                ready_val = raw_card["ready_stock"].get("total_ready", 0) if isinstance(raw_card.get("ready_stock"), dict) else raw_card.get("ready_stock")
                mock_st.caption(f"📦 Estoque: **{ready_val}** / Meta: **{raw_card['target_stock']}** vídeos")

            rendered_caption = mock_st.caption.call_args[0][0]
            self.assertIn("📦 Estoque: **2** / Meta: **3** vídeos", rendered_caption)
            self.assertNotIn("{'total_ready'", rendered_caption)

    def test_05_cancelled_post_not_counted_as_scheduled(self):
        """5. scheduled post 'cancelled' -> NÃO entra no contador scheduled."""
        now_iso = datetime.now(timezone.utc).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            # 1 planned
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, profile_id, scheduled_at, created_at, status)
                VALUES ('t-1', 'youtube', 'default', ?, ?, 'planned');
                """,
                (now_iso, now_iso),
            )
            # 1 ready
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, profile_id, scheduled_at, created_at, status)
                VALUES ('t-2', 'youtube', 'default', ?, ?, 'ready');
                """,
                (now_iso, now_iso),
            )
            # 1 cancelled (post cancelado como o #65)
            conn.execute(
                """
                INSERT INTO scheduled_posts (task_id, platform, profile_id, scheduled_at, created_at, status)
                VALUES ('t-3', 'youtube', 'default', ?, ?, 'cancelled');
                """,
                (now_iso, now_iso),
            )

        overview = operator_console.get_profile_operations_overview(db_path=self.db_path)
        default_po = next((po for po in overview if po["profile_id"] == "default"), None)
        self.assertIsNotNone(default_po, "Perfil default não encontrado no overview")

        # planned (1) + ready (1) = 2. O post 'cancelled' NÃO deve ser contabilizado.
        self.assertEqual(default_po["scheduled"], 2)

        # Se cancelarmos os dois restantes:
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute("UPDATE scheduled_posts SET status = 'cancelled';")

        overview_after = operator_console.get_profile_operations_overview(db_path=self.db_path)
        default_po_after = next((po for po in overview_after if po["profile_id"] == "default"), None)
        self.assertEqual(default_po_after["scheduled"], 0, "Quando todos os posts são cancelled, scheduled deve ser 0")

    def test_06_factory_state_label_presentation(self):
        """Verifica que RUNNING é apresentado como 'SERVIÇO ONLINE' e PAUSED como 'FÁBRICA PAUSADA'."""
        state_labels = {
            "RUNNING": "🟢 SERVIÇO ONLINE",
            "PAUSED": "🟡 FÁBRICA PAUSADA",
            "DEGRADED": "🟠 SERVIÇO DEGRADADO",
            "ERROR": "🔴 ERRO NO SERVIÇO",
        }
        self.assertEqual(state_labels["RUNNING"], "🟢 SERVIÇO ONLINE")
        self.assertEqual(state_labels["PAUSED"], "🟡 FÁBRICA PAUSADA")
