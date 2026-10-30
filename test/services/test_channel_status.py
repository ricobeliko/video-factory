"""Testes unitários da fonte única de status do canal (`app/services/channel_status.py`)
e correções associadas do Passo 1 (`get_fleet_summary` e `get_autonomous_status`).

Cobre os casos reais obrigatórios da frota:
1. Dose Diária de Escolhas (autônomo desligado, estoque 39/10 => paused)
2. Dose Diária de GTA VI (pausado/desativado de propósito, mesmo com rejeições/erros por baixo => paused)
3. Quiz_Quiz (10/10 aprovados em 24h, estoque abaixo da meta => ok com reason_code DAILY_GOAL_REACHED e reason "Meta diária atingida")
4. Dose Diária de Histórias e Mistério (warmup 2/2 aprovados em 24h, estoque abaixo da meta => ok com DAILY_GOAL_REACHED)
5. Estoque desconhecido (None) => NUNCA vira ok (mesmo com meta diária atingida): vira attention (STOCK_UNKNOWN)
6. Fábrica pausada => sempre paused (prioridade 1 sobre qualquer bloqueio ou geração)
7. Ordem estrita de prioridade: paused > blocked > running > attention > ok
8. get_autonomous_status: estado fantasma (autônomo desligado + scheduler_enabled=True + autonomous_state antigo gravado) => "disabled", e falha de leitura de estoque propaga None (não mascara como 0).
"""

import os
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from app.services import autonomous_production, operator_console, profile_manager, scheduler
from app.services.channel_status import evaluate_canonical_channel_status


class TestCanonicalChannelStatus(unittest.TestCase):
    def test_case_1_escolhas_autonomous_disabled_full_stock_is_paused(self):
        """Caso real 1 — Dose Diária de Escolhas: autônomo desligado, estoque 39/10 => paused."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=False,
            auto_state="idle",
            ready_stock=39,
            target_stock=10,
            approved_24h=0,
            max_generations_24h=3,
        )
        self.assertEqual(res["status"], "paused")
        self.assertEqual(res["label"], "Pausado")
        self.assertEqual(res["reason_code"], "AUTONOMOUS_DISABLED")
        self.assertEqual(res["reason"], "Modo autônomo desligado")

    def test_case_2_gta_vi_paused_on_purpose_overrides_underlying_problems(self):
        """Caso real 2 — Dose Diária de GTA VI: pausado de propósito prevalece sobre disjuntor/erro/estoque 0."""
        # Mesmo com consec_rejections >= max_rejections, auto_state='blocked' e ready_stock=0:
        res_inactive = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=False,
            autonomous_enabled=False,
            auto_state="blocked",
            auto_message="Rejeitado 3x",
            ready_stock=0,
            target_stock=3,
            consec_rejections=10,
            max_rejections=10,
            failed_24h=5,
        )
        self.assertEqual(res_inactive["status"], "paused")
        self.assertEqual(res_inactive["reason_code"], "CHANNEL_INACTIVE")
        self.assertEqual(res_inactive["reason"], "Canal desativado pelo operador")

        res_auto_off = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=False,
            auto_state="blocked",
            auto_message="Disjuntor antigo",
            ready_stock=0,
            target_stock=3,
            consec_rejections=10,
            max_rejections=10,
        )
        self.assertEqual(res_auto_off["status"], "paused")
        self.assertEqual(res_auto_off["reason_code"], "AUTONOMOUS_DISABLED")
        self.assertEqual(res_auto_off["reason"], "Modo autônomo desligado")

    def test_case_3_quiz_quiz_daily_goal_10_of_10_below_target_stock_is_ok(self):
        """Caso real 3 — Quiz_Quiz: 10/10 aprovados em 24h com estoque < meta (2/5) => ok DAILY_GOAL_REACHED."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="idle",
            ready_stock=2,
            target_stock=5,
            approved_24h=10,
            max_generations_24h=10,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["label"], "OK")
        self.assertEqual(res["reason_code"], "DAILY_GOAL_REACHED")
        self.assertEqual(res["reason"], "Meta diária atingida")

    def test_case_4_historias_warmup_2_of_2_below_target_stock_is_ok(self):
        """Caso real 4 — Dose Diária de Histórias e Mistério: warmup 2/2 aprovados em 24h com estoque 1/3 => ok."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="cooldown",
            ready_stock=1,
            target_stock=3,
            approved_24h=2,
            max_generations_24h=2,
        )
        self.assertEqual(res["status"], "ok")
        self.assertEqual(res["label"], "OK")
        self.assertEqual(res["reason_code"], "DAILY_GOAL_REACHED")
        self.assertEqual(res["reason"], "Meta diária atingida")

    def test_case_5_ready_stock_none_never_becomes_ok(self):
        """Caso real 5 — Estoque desconhecido (None) NUNCA vira ok (nem com meta diária batida): vira attention."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="idle",
            ready_stock=None,
            target_stock=3,
            approved_24h=10,
            max_generations_24h=10,
        )
        self.assertEqual(res["status"], "attention")
        self.assertEqual(res["label"], "Atenção")
        self.assertEqual(res["reason_code"], "STOCK_UNKNOWN")
        self.assertIn("Estoque desconhecido", res["reason"])

    def test_case_6_factory_paused_always_paused(self):
        """Caso real 6 — Fábrica pausada => sempre paused (prioridade 1 sobre bloqueio ou geração)."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=True,
            factory_state="PAUSED",
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="generating",
            pending_proc=2,
            consec_rejections=15,
            max_rejections=10,
            ready_stock=0,
            target_stock=5,
        )
        self.assertEqual(res["status"], "paused")
        self.assertEqual(res["label"], "Pausado")
        self.assertEqual(res["reason_code"], "FACTORY_PAUSED")
        self.assertEqual(res["reason"], "Fábrica pausada pelo operador")

    def test_strict_priority_order_paused_blocked_running_attention_ok(self):
        """Valida a hierarquia estrita: paused > blocked > running > attention > ok."""
        # blocked > running
        res_blocked = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="generating",
            pending_proc=1,
            consec_rejections=10,
            max_rejections=10,
            ready_stock=0,
            target_stock=5,
        )
        self.assertEqual(res_blocked["status"], "blocked")
        self.assertEqual(res_blocked["reason_code"], "REJECTION_BREAKER")

        # running > attention (estoque 0 mas gerando agora => running)
        res_running = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="generating",
            pending_proc=1,
            ready_stock=0,
            target_stock=5,
        )
        self.assertEqual(res_running["status"], "running")
        self.assertIsNone(res_running["reason"])

        # attention (estoque < meta e ainda não atingiu meta diária 1/10)
        res_attention = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            auto_state="idle",
            ready_stock=2,
            target_stock=5,
            approved_24h=1,
            max_generations_24h=10,
        )
        self.assertEqual(res_attention["status"], "attention")
        self.assertEqual(res_attention["reason_code"], "STOCK_BELOW_TARGET")

    def test_case_no_publish_destination_blocked(self):
        """Sem destino de publicação com autônomo ligado => blocked com NO_PUBLISH_DESTINATION."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            has_publish_destination=False,
            auto_state="idle",
            ready_stock=5,
            target_stock=3,
        )
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["label"], "Bloqueado")
        self.assertEqual(res["reason_code"], "NO_PUBLISH_DESTINATION")
        self.assertEqual(res["reason"], "Sem destino de publicação habilitado (YouTube ou TikTok)")

    def test_case_no_publish_destination_priority_order(self):
        """Ordem de prioridade de NO_PUBLISH_DESTINATION: abaixo de FACTORY_PAUSED, CHANNEL_INACTIVE, AUTONOMOUS_DISABLED e FACTORY_ERROR; acima de disjuntor e outros bloqueios."""
        # 1. Fábrica pausada vence
        res_p = evaluate_canonical_channel_status(
            is_factory_paused=True,
            autonomous_enabled=True,
            has_publish_destination=False,
        )
        self.assertEqual(res_p["status"], "paused")
        self.assertEqual(res_p["reason_code"], "FACTORY_PAUSED")

        # 2. Autônomo desligado vence (paused)
        res_dis = evaluate_canonical_channel_status(
            is_factory_paused=False,
            autonomous_enabled=False,
            has_publish_destination=False,
        )
        self.assertEqual(res_dis["status"], "paused")
        self.assertEqual(res_dis["reason_code"], "AUTONOMOUS_DISABLED")

        # 3. FACTORY_ERROR vence NO_PUBLISH_DESTINATION
        res_err = evaluate_canonical_channel_status(
            factory_state="ERROR",
            autonomous_enabled=True,
            has_publish_destination=False,
        )
        self.assertEqual(res_err["status"], "blocked")
        self.assertEqual(res_err["reason_code"], "FACTORY_ERROR")

        # 4. NO_PUBLISH_DESTINATION vence REJECTION_BREAKER e auto_state='blocked'
        res_dest = evaluate_canonical_channel_status(
            is_factory_paused=False,
            autonomous_enabled=True,
            has_publish_destination=False,
            consec_rejections=15,
            max_rejections=10,
            auto_state="blocked",
            auto_message="Bloqueado por disjuntor",
        )
        self.assertEqual(res_dest["status"], "blocked")
        self.assertEqual(res_dest["reason_code"], "NO_PUBLISH_DESTINATION")


class TestAutonomousStatusFixes(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_auto_status.db")
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)
        operator_console.init_operator_db(self.db_path)

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_phantom_state_cleared_when_autonomous_disabled_even_with_scheduler_enabled(self):
        """Quando autonomous_enabled=False, state deve ser 'disabled' mesmo se scheduler_enabled=True e autonomous_state antigo estiver gravado."""
        with scheduler.get_connection(self.db_path) as conn:
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('scheduler_enabled', 'True');"
            )
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_mode_enabled', 'False');"
            )
            conn.execute(
                "INSERT OR REPLACE INTO autopilot_settings (key, value) VALUES ('autonomous_state', 'waiting_schedule');"
            )

        snap = autonomous_production.get_autonomous_status(
            db_path=self.db_path, profile_id="default"
        )
        self.assertFalse(snap["autonomous_mode_enabled"])
        self.assertEqual(snap["state"], "disabled")

    def test_stock_read_failure_propagates_none_instead_of_zero(self):
        """Falha de leitura de estoque em get_autonomous_status propaga None (não mascara como 0)."""
        with patch(
            "app.services.autonomous_production.get_autonomous_ready_stock",
            side_effect=RuntimeError("disk error"),
        ):
            snap = autonomous_production.get_autonomous_status(
                db_path=self.db_path, profile_id="default"
            )
            self.assertIsNone(snap["ready_stock_total"])
            self.assertIsNone(snap["youtube_ready_count"])
            self.assertIsNone(snap["is_below_target"])
            self.assertIsInstance(snap["target_ready_stock"], int)


if __name__ == "__main__":
    unittest.main()
