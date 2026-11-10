"""
test/services/test_flow_cenas_por_perfil.py
============================================
Testes direcionados da Missão v2/flow-cenas-por-perfil:
1. update_profile_visual_settings valida limites estritos [1, 8] e rejeita 0, 9, negativos e não-inteiros.
2. update_profile_visual_settings grava flow_scene_count=3 no settings_json do perfil especificado.
3. get_generation_profile_context reflete flow_scene_count=3 para o perfil alterado e mantém 6 para perfis sem override.
4. check_required_providers_preflight exige exatamente N * 15 créditos:
   - com 3 cenas (45 cr) e conta com 50 cr, o pré-voo aprova;
   - com 6 cenas (90 cr) e mesma conta com 50 cr, o pré-voo bloqueia por saldo insuficiente.
5. Endpoint API V2 PATCH /api/v2/channels/{profile_id}/visual:
   - atualiza com sucesso flow_scene_count=3 (200 OK);
   - rejeita valores fora do range [1, 8] com 400/422.
6. select_default_flow_scenes:
   - target_count=1 retorna exatamente 1 cena (o hook);
   - target_count=3 retorna exatamente 3 cenas;
   - target_count=6 retorna 6 cenas.
"""

import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import profile_manager
from app.services import autonomous_production as ap
from app.services import flow_account_pool as fap
from scripts.flow_workflow import select_default_flow_scenes
from app import asgi
from fastapi.testclient import TestClient


class DummyScene:
    def __init__(self, idx: int, duration_hint: float = 8.0):
        self.scene_index = idx
        self.duration_hint = duration_hint


class TestFlowCenasPorPerfil(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.db_path = os.path.join(self.test_dir, "test_profiles.db")
        self.flow_cfg = os.path.join(self.test_dir, "flow_accounts.json")
        self.flow_rt = os.path.join(self.test_dir, "flow_accounts_runtime.json")

        profile_manager.init_profile_db(self.db_path)

        # Configura mock pool de contas: conta com 50 créditos
        mock_config = {
            "schema_version": 1,
            "accounts": [
                {
                    "account_id": "flow-b",
                    "display_name": "Conta B",
                    "enabled": True,
                    "priority": 100,
                    "user_data_dir": os.path.join(self.test_dir, "p_b"),
                }
            ],
        }
        with open(self.flow_cfg, "w", encoding="utf-8") as f:
            import json
            json.dump(mock_config, f)

        fap.record_verified_credit_balance("flow-b", 50, runtime_path=self.flow_rt)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_01_update_profile_visual_settings_validation(self):
        """Validação estrita de limites [1, 8] em update_profile_visual_settings."""
        with patch("app.services.operator_console.require_primary_instance", return_value=True):
            prof = profile_manager.onboard_channel_workspace(
                name="Canal GTA",
                slug="canal-gta",
                niche="games",
                topic_brief="GTA VI",
                require_destination=False,
                db_path=self.db_path,
            )
            pid = prof["profile"]["id"]

            # Válidos: 1, 3, 8
            res1 = profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": 1}, db_path=self.db_path)
            self.assertEqual(res1.flow_scene_count, 1)

            res3 = profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": 3}, db_path=self.db_path)
            self.assertEqual(res3.flow_scene_count, 3)

            res8 = profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": 8}, db_path=self.db_path)
            self.assertEqual(res8.flow_scene_count, 8)

            # Inválidos: 0, 9, -1, 'abc'
            with self.assertRaises(ValueError):
                profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": 0}, db_path=self.db_path)

            with self.assertRaises(ValueError):
                profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": 9}, db_path=self.db_path)

            with self.assertRaises(ValueError):
                profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": -2}, db_path=self.db_path)

            with self.assertRaises(ValueError):
                profile_manager.update_profile_visual_settings(pid, {"flow_scene_count": "invalid"}, db_path=self.db_path)

    def test_02_perfil_especifico_versus_outro_perfil(self):
        """Alterar o canal GTA para 3 cenas não afeta o canal secundário (que mantém 6)."""
        with patch("app.services.operator_console.require_primary_instance", return_value=True):
            prof_gta = profile_manager.onboard_channel_workspace(
                name="GTA VI",
                slug="gta-vi",
                niche="games",
                topic_brief="GTA VI",
                require_destination=False,
                db_path=self.db_path,
            )
            pid_gta = prof_gta["profile"]["id"]

            prof_outro = profile_manager.onboard_channel_workspace(
                name="Canal Histórias",
                slug="historias",
                niche="curiosities",
                topic_brief="Histórias",
                require_destination=False,
                db_path=self.db_path,
            )
            pid_outro = prof_outro["profile"]["id"]

            profile_manager.update_profile_visual_settings(pid_gta, {"flow_scene_count": 3}, db_path=self.db_path)

            # Contexto de geração do GTA VI deve ter 3 cenas
            ctx_gta = profile_manager.get_generation_profile_context(pid_gta, db_path=self.db_path)
            self.assertEqual(ctx_gta["flow_scene_count"], 3)

            # Contexto de geração do outro canal deve manter padrão global 6
            ctx_outro = profile_manager.get_generation_profile_context(pid_outro, db_path=self.db_path)
            self.assertEqual(ctx_outro["flow_scene_count"], 6)

    def test_03_preflight_creditos_por_cenas(self):
        """Pré-voo aprova canal de 3 cenas (45 cr) e rejeita canal de 6 cenas (90 cr) contra saldo de 50 cr."""
        from unittest.mock import MagicMock
        with patch("app.services.flow_account_pool.DEFAULT_CONFIG_PATH", self.flow_cfg), \
             patch("app.services.flow_account_pool.DEFAULT_RUNTIME_PATH", self.flow_rt), \
             patch("app.utils.utils.check_ffmpeg_ready", return_value=True), \
             patch("app.services.material.has_material_api_keys", return_value=True), \
             patch("shutil.disk_usage", return_value=(100, 50, 10 * (1024 ** 3))), \
             patch("app.models.llm_provider.get_llm_provider") as mock_llm_prov:

            mock_spec = MagicMock()
            mock_spec.requires_api_key = False
            mock_llm_prov.return_value = mock_spec

            # 1. Pré-voo com 3 cenas (custo = 3 * 15 = 45 cr <= 50 cr da Conta B) -> APROVA
            ok_3, msg_3, details_3 = ap.check_required_providers_preflight(
                video_source="pexels",
                voice_name="pt-BR-AntonioNeural-Male",
                db_path=self.db_path,
                flow_enabled=True,
                flow_scene_count=3,
            )
            self.assertTrue(ok_3, f"Esperado aprovação com 3 cenas mas falhou: {msg_3}")
            self.assertEqual(details_3.get("Flow"), "Account flow-b")

            # 2. Pré-voo com 6 cenas (custo = 6 * 15 = 90 cr > 50 cr da Conta B) -> BLOQUEIA
            ok_6, msg_6, details_6 = ap.check_required_providers_preflight(
                video_source="pexels",
                voice_name="pt-BR-AntonioNeural-Male",
                db_path=self.db_path,
                flow_enabled=True,
                flow_scene_count=6,
            )
            self.assertFalse(ok_6, "Esperado bloqueio com 6 cenas para saldo de 50 cr")
            self.assertEqual(details_6.get("Flow"), "INSUFFICIENT_CREDITS")
            self.assertIn("90 cr para 6 cenas", msg_6)

    def test_04_api_patch_channel_visual(self):
        """Endpoint PATCH /api/v2/channels/{profile_id}/visual atualiza e valida corretamente."""
        with patch("app.services.operator_console.get_db_path", return_value=self.db_path), \
             patch("app.services.operator_console.require_primary_instance", return_value=True):

            prof = profile_manager.onboard_channel_workspace(
                name="Canal GTA API",
                slug="canal-gta-api",
                niche="games",
                topic_brief="GTA VI",
                require_destination=False,
                db_path=self.db_path,
            )
            pid = prof["profile"]["id"]

            client = TestClient(asgi.app)

            # PATCH válido
            resp = client.patch(f"/api/v2/channels/{pid}/visual", json={"flow_scene_count": 3})
            self.assertEqual(resp.status_code, 200, resp.text)
            data = resp.json()["data"]
            self.assertEqual(data.get("flow_scene_count"), 3)

            # Confirma que gravou no banco
            saved_ctx = profile_manager.get_generation_profile_context(pid, db_path=self.db_path)
            self.assertEqual(saved_ctx["flow_scene_count"], 3)

            # PATCH inválido: 0 (rejeitado por validação Pydantic ge=1)
            resp_zero = client.patch(f"/api/v2/channels/{pid}/visual", json={"flow_scene_count": 0})
            self.assertIn(resp_zero.status_code, (400, 422))

            # PATCH inválido: 9 (rejeitado por validação Pydantic le=8)
            resp_nine = client.patch(f"/api/v2/channels/{pid}/visual", json={"flow_scene_count": 9})
            self.assertIn(resp_nine.status_code, (400, 422))

    def test_05_select_default_flow_scenes_bounds(self):
        """select_default_flow_scenes respeita exatamente target_count para 1, 3 e 6 cenas."""
        scenes = [DummyScene(i) for i in range(1, 7)]  # 6 cenas

        # target_count = 1 -> exatamente 1 cena (o hook: cena 1)
        res1 = select_default_flow_scenes(scenes, target_count=1)
        self.assertEqual(res1, [1])

        # target_count = 3 -> exatamente 3 cenas
        res3 = select_default_flow_scenes(scenes, target_count=3)
        self.assertEqual(len(res3), 3)
        self.assertEqual(res3[0], 1)   # hook
        self.assertEqual(res3[-1], 6)  # closing

        # target_count = 6 -> todas as 6 cenas
        res6 = select_default_flow_scenes(scenes, target_count=6)
        self.assertEqual(res6, [1, 2, 3, 4, 5, 6])


if __name__ == "__main__":
    unittest.main()
