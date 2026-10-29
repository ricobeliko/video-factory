"""Testes unitários da fonte única de status do canal (`app/services/channel_status.py`).

Cobre:
1. Dose Diária de Escolhas (autônomo desligado, estoque 39/10 => paused)
2. Dose Diária de GTA VI (pausado/desativado de propósito => paused)
3. Quiz_Quiz (10/10 aprovados em 24h, estoque abaixo da meta => ok DAILY_GOAL_REACHED)
4. Dose Diária de Histórias e Mistério (warmup 2/2 aprovados em 24h => ok DAILY_GOAL_REACHED)
5. Estoque desconhecido (None) => attention (STOCK_UNKNOWN)
6. Fábrica pausada => sempre paused
7. Ordem estrita de prioridade: paused > blocked > running > attention > ok
8. Guarda Fail-Closed: sem destinos de publicação habilitados => blocked (NO_PUBLISH_DESTINATION)
"""

import unittest

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
        self.assertEqual(res["reason_code"], "DAILY_GOAL_REACHED")
        self.assertEqual(res["reason"], "Meta diária atingida")

    def test_case_5_stock_unknown_is_always_attention(self):
        """Caso real 5 — Estoque desconhecido (None) NUNCA vira ok (mesmo com meta diária atingida)."""
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

    def test_case_fail_closed_no_publish_destination_blocked(self):
        """Item 5 — Perfil com autônomo ligado e nenhum destino habilitado => Bloqueado com NO_PUBLISH_DESTINATION."""
        res = evaluate_canonical_channel_status(
            is_factory_paused=False,
            is_channel_active=True,
            autonomous_enabled=True,
            has_publish_destination=False,
            auto_state="idle",
            ready_stock=0,
            target_stock=3,
        )
        self.assertEqual(res["status"], "blocked")
        self.assertEqual(res["label"], "Bloqueado")
        self.assertEqual(res["reason_code"], "NO_PUBLISH_DESTINATION")
        self.assertEqual(res["reason"], "Nenhum canal/destino de publicação habilitado (YouTube ou TikTok)")

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


if __name__ == "__main__":
    unittest.main()
