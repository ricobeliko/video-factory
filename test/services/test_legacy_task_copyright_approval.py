"""
test/services/test_legacy_task_copyright_approval.py
===================================================
Testes direcionados para a aprovação manual de direitos autorais / proveniência
de artefatos finais legados (V1.5E).

Cobre os requisitos obrigatórios:
A) legacy hybrid + manual approval + hash correto => PASS
B) hash mudou depois da aprovação => FAIL
C) sem approval => FAIL
D) unsafe BGM => FAIL
E) claimed/blocked/strike => FAIL
F) idempotência
G) confirmação explícita obrigatória
H) clipe Flow corrompido / ausente => FAIL
I) final-1.mp4 ausente ou vazio => FAIL
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import patch

from app.services import copyright_gate, operator_console, scheduler


class TestLegacyTaskCopyrightApproval(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_legacy_appr_")
        self.db_path = os.path.join(self.test_dir, "test_factory.db")
        scheduler.init_db(self.db_path)
        operator_console.init_operator_db(self.db_path)

        self.task_id = "test_legacy_hybrid_task_001"
        self.task_dir = os.path.join(self.test_dir, self.task_id)
        os.makedirs(self.task_dir, exist_ok=True)
        self.flow_dir = os.path.join(self.task_dir, "flow")
        self.clips_dir = os.path.join(self.flow_dir, "clips")
        os.makedirs(self.clips_dir, exist_ok=True)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def _create_final_video(self, content=b"VALID_FINAL_VIDEO_BYTES_TEST_CONTENT_12345"):
        final_path = os.path.join(self.task_dir, "final-1.mp4")
        with open(final_path, "wb") as f:
            f.write(content)
        return final_path

    def _create_flow_clip(self, clip_name="flow_scene_01.mp4", content=b"\x00" * 1024):
        clip_path = os.path.join(self.clips_dir, clip_name)
        with open(clip_path, "wb") as f:
            f.write(content)
        return clip_path

    def _create_legacy_hybrid_task_files(
        self,
        bgm_type="ambient_auto",
        bgm_volume=0.2,
        with_flow_clip=True,
    ):
        """Cria estrutura real de task legada híbrida:
        - script.json sem material_sources e sem scene_materials
        - asset_provenance com visual_clips=[]
        - flow/manifest.json com 2 cenas: cena 1 Flow premium, cena 2 stock sem rastreio
        - final-1.mp4 existente
        """
        if with_flow_clip:
            self._create_flow_clip("flow_scene_01.mp4")

        manifest = {
            "project_name": "flow",
            "flow_generation": {
                "status": "COMPLETE",
                "completed_scenes": [1],
            },
            "scenes": [
                {
                    "scene_index": 1,
                    "expected_clip": "flow_scene_01.mp4",
                    "is_flow_premium": True,
                    "narration": "Cena Flow Premium",
                    "duration_hint": 5.0,
                },
                {
                    "scene_index": 2,
                    "expected_clip": "pexels_stock_02.mp4",
                    "is_flow_premium": False,
                    "narration": "Cena Stock Legada",
                    "duration_hint": 5.0,
                },
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest, f, indent=2)

        script_payload = {
            "params": {
                "bgm_type": bgm_type,
                "bgm_volume": bgm_volume,
                "video_subject": "Teste Legado Híbrido",
            },
            "asset_provenance": {
                "bgm": {
                    "enabled": (bgm_type not in ("", "none") and bgm_volume > 0),
                    "source": "procedural" if bgm_type == "ambient_auto" else "unknown",
                    "provenance_status": "SAFE_PROCEDURAL" if bgm_type == "ambient_auto" else "UNVERIFIED_BGM",
                },
                "visual_clips": [],
            },
        }
        with open(os.path.join(self.task_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(script_payload, f, indent=2)

        return self._create_final_video()

    # =========================================================================
    # A) legacy hybrid + manual approval + hash correto => PASS
    # =========================================================================
    def test_a_legacy_hybrid_with_manual_approval_and_correct_hash_passes(self):
        self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # 1. Aprovação manual pelo operador
            res = operator_console.approve_legacy_task_copyright_op(
                task_id=self.task_id,
                note="Revisão humana dos assets stock da tarefa legada confirmada",
                confirm="APPROVE_LEGACY_COPYRIGHT",
                db_path=self.db_path,
                task_base_dir=self.test_dir,
            )

            self.assertTrue(res["success"])
            self.assertFalse(res["idempotent"])
            self.assertEqual(res["copyright_status"], "clean_manual")
            self.assertEqual(res["source"], "operator")
            self.assertEqual(res["scope"], "legacy_final_artifact")
            self.assertTrue(bool(res["final_video_sha256"]))

            # 2. Avaliação do gate com evidência de aprovação manual
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
                db_path=self.db_path,
            )

            self.assertTrue(passed, f"Gate deveria aprovar com manual approval válido: {reason}")
            self.assertEqual(details.get("copyright_provenance_gate"), "PASS")
            self.assertEqual(details.get("approval_mode"), "MANUAL_LEGACY_FINAL_ARTIFACT")
            self.assertEqual(details.get("copyright_status"), "clean_manual")
            self.assertEqual(details.get("source"), "operator")
            self.assertTrue(details.get("final_video_sha256_verified"))
            self.assertEqual(details.get("flow_provenance_status"), "GENERATED_FLOW_PROVENANCE_VERIFIED")
            self.assertEqual(details.get("flow_clips_verified"), 1)
            self.assertIn("MANUAL_LEGACY_FINAL_ARTIFACT", reason)
            # Regra estrita: nunca retornar CONTENT_ID_SAFE
            self.assertNotIn("CONTENT_ID_SAFE", str(details))
            self.assertNotIn("CONTENT_ID_SAFE", reason)

    # =========================================================================
    # B) hash mudou depois da aprovação => FAIL
    # =========================================================================
    def test_b_hash_changed_after_approval_fails_gate(self):
        final_video = self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # Aprova com hash original
            res = operator_console.approve_legacy_task_copyright_op(
                task_id=self.task_id,
                confirm="APPROVE_LEGACY_COPYRIGHT",
                db_path=self.db_path,
                task_base_dir=self.test_dir,
            )
            self.assertTrue(res["success"])

            # Altera o arquivo final-1.mp4 em disco (simula substituição ou adulteração)
            with open(final_video, "ab") as f:
                f.write(b"TAMPERED_EXTRA_BYTES")

            # Avaliação deve reprovar fail-closed (hash mismatch)
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
                db_path=self.db_path,
            )

            self.assertFalse(passed, "Gate deve reprovar se o hash do vídeo mudou pós-aprovação")
            self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")

    # =========================================================================
    # C) sem approval => FAIL
    # =========================================================================
    def test_c_without_manual_approval_fails_gate(self):
        self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir):

            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
                db_path=self.db_path,
            )

            self.assertFalse(passed, "Gate deve reprovar tarefa híbrida legada sem aprovação manual")
            self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
            self.assertEqual(details.get("visual_status"), "MISSING_CLIPS")

    # =========================================================================
    # D) unsafe BGM => FAIL
    # =========================================================================
    def test_d_unsafe_bgm_fails_approval_and_gate(self):
        self._create_legacy_hybrid_task_files(bgm_type="random", bgm_volume=0.5)

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # 1. Operação do operador deve recusar aprovação manual com BGM insegura
            with self.assertRaises(ValueError) as ctx:
                operator_console.approve_legacy_task_copyright_op(
                    task_id=self.task_id,
                    confirm="APPROVE_LEGACY_COPYRIGHT",
                    db_path=self.db_path,
                    task_base_dir=self.test_dir,
                )
            self.assertIn("BGM insegura", str(ctx.exception))

            # 2. Gate deve falhar imediatamente na verificação de BGM
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
                db_path=self.db_path,
            )
            self.assertFalse(passed)
            self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
            self.assertEqual(details.get("bgm_status"), "BLOCKED_LEGACY")

    # =========================================================================
    # E) claimed / blocked / strike => FAIL
    # =========================================================================
    def test_e_claimed_blocked_strike_fails_approval_and_gate(self):
        self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # Simula registro prévio de Content ID claim na task em operational_events
            operator_console.log_operational_event(
                component="copyright",
                severity="WARNING",
                event_type="PUBLICATION_COPYRIGHT_STATUS_SET",
                task_id=self.task_id,
                message="Claim detectado no YouTube",
                metadata={"task_id": self.task_id, "copyright_status": "claimed", "platform": "youtube"},
                db_path=self.db_path,
            )

            # 1. Operação deve recusar aprovação para task com claim
            with self.assertRaises(ValueError) as ctx:
                operator_console.approve_legacy_task_copyright_op(
                    task_id=self.task_id,
                    confirm="APPROVE_LEGACY_COPYRIGHT",
                    db_path=self.db_path,
                    task_base_dir=self.test_dir,
                )
            self.assertIn("adverso", str(ctx.exception).lower())

            # 2. Gate também deve reprovar sumariamente
            passed, reason, details = copyright_gate.evaluate_copyright_provenance_gate(
                task_id=self.task_id,
                task_base_dir=self.test_dir,
                db_path=self.db_path,
            )
            self.assertFalse(passed)
            self.assertEqual(details.get("copyright_provenance_gate"), "FAIL")
            self.assertEqual(details.get("copyright_status"), "claimed")

    # =========================================================================
    # F) idempotência
    # =========================================================================
    def test_f_manual_approval_idempotence(self):
        self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            # Primeira execução
            res1 = operator_console.approve_legacy_task_copyright_op(
                task_id=self.task_id,
                note="Nota idêntica de revisão",
                confirm="APPROVE_LEGACY_COPYRIGHT",
                db_path=self.db_path,
                task_base_dir=self.test_dir,
            )
            self.assertTrue(res1["success"])
            self.assertFalse(res1["idempotent"])

            with scheduler.get_connection(self.db_path) as conn:
                count_1 = conn.execute(
                    "SELECT COUNT(*) FROM operational_events WHERE event_type = 'TASK_COPYRIGHT_MANUAL_APPROVAL';"
                ).fetchone()[0]
            self.assertEqual(count_1, 1)

            # Segunda execução com mesmos parâmetros
            res2 = operator_console.approve_legacy_task_copyright_op(
                task_id=self.task_id,
                note="Nota idêntica de revisão",
                confirm="APPROVE_LEGACY_COPYRIGHT",
                db_path=self.db_path,
                task_base_dir=self.test_dir,
            )
            self.assertTrue(res2["success"])
            self.assertTrue(res2["idempotent"])
            self.assertEqual(res2["final_video_sha256"], res1["final_video_sha256"])

            # Não deve ter inserido novo evento
            with scheduler.get_connection(self.db_path) as conn:
                count_2 = conn.execute(
                    "SELECT COUNT(*) FROM operational_events WHERE event_type = 'TASK_COPYRIGHT_MANUAL_APPROVAL';"
                ).fetchone()[0]
            self.assertEqual(count_2, 1)

    # =========================================================================
    # G) confirmação explícita obrigatória
    # =========================================================================
    def test_g_invalid_confirmation_token_fails(self):
        self._create_legacy_hybrid_task_files()

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True, "duration": 5.0}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            with self.assertRaises(ValueError) as ctx:
                operator_console.approve_legacy_task_copyright_op(
                    task_id=self.task_id,
                    confirm="INVALID_CONFIRMATION",
                    db_path=self.db_path,
                    task_base_dir=self.test_dir,
                )
            self.assertIn("APPROVE_LEGACY_COPYRIGHT", str(ctx.exception))

    # =========================================================================
    # H) clipe Flow corrompido ou ausente => FAIL
    # =========================================================================
    def test_h_corrupted_flow_clip_fails_approval_and_gate(self):
        self._create_legacy_hybrid_task_files(with_flow_clip=False)
        # O arquivo de clip flow_scene_01.mp4 NÃO foi criado

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": False}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            with self.assertRaises(ValueError) as ctx:
                operator_console.approve_legacy_task_copyright_op(
                    task_id=self.task_id,
                    confirm="APPROVE_LEGACY_COPYRIGHT",
                    db_path=self.db_path,
                    task_base_dir=self.test_dir,
                )
            self.assertIn("inexistente ou vazio", str(ctx.exception).lower())

    # =========================================================================
    # I) final-1.mp4 ausente ou vazio => FAIL
    # =========================================================================
    def test_i_missing_final_video_fails(self):
        self._create_legacy_hybrid_task_files()
        final_video = os.path.join(self.task_dir, "final-1.mp4")
        if os.path.isfile(final_video):
            os.remove(final_video)

        with patch("scripts.flow_workflow.validate_clip_file", return_value={"valid": True}), \
             patch("app.utils.utils.task_dir", return_value=self.task_dir), \
             patch("app.services.operator_console.is_primary_instance", return_value=True):

            with self.assertRaises(ValueError) as ctx:
                operator_console.approve_legacy_task_copyright_op(
                    task_id=self.task_id,
                    confirm="APPROVE_LEGACY_COPYRIGHT",
                    db_path=self.db_path,
                    task_base_dir=self.test_dir,
                )
            self.assertIn("final-1.mp4", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
