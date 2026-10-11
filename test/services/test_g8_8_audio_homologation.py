"""
test/services/test_g8_8_audio_homologation.py
=============================================
Testes direcionados para a Homologação Controlada de Áudio G8.8 (GTA VI).
"""

import json
import os
import shutil
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.models.schema import (
    SceneClipInstruction,
)
from scripts.validate_g8_8_audio_homologation import run_g8_8_homologation


class TestG88AudioHomologation(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_g8_8_")
        self.source_task_id = "8909befc-7ec5-47bd-829d-b3412041beb2"
        self.source_task_dir = os.path.join(self.test_dir, "storage", "tasks", self.source_task_id)
        os.makedirs(self.source_task_dir, exist_ok=True)

        self.flow_dir = os.path.join(self.source_task_dir, "flow")
        self.clips_dir = os.path.join(self.flow_dir, "clips")
        os.makedirs(self.clips_dir, exist_ok=True)

        # Roteiro sintético GTA VI
        self.script_text = (
            "Em GTA VI, o que parece apenas cenário pode esconder um sistema "
            "muito mais inteligente do que a Rockstar mostrou até agora."
        )

        # ScenePlan sintético (2 cenas)
        self.scene_plan_data = {
            "total_scenes": 2,
            "scenes": [
                {
                    "scene_index": 1,
                    "narration": "Cena 1 narração inicial",
                    "duration_hint": 5.0,
                    "search_terms": ["gta", "vice city"],
                },
                {
                    "scene_index": 2,
                    "narration": "Cena 2 narração final",
                    "duration_hint": 5.0,
                    "search_terms": ["gta", "rockstar"],
                },
            ],
        }

        # script.json sintético da task original
        self.original_script_data = {
            "task_id": self.source_task_id,
            "script": self.script_text,
            "video_script": self.script_text,
            "search_terms": ["gta vi"],
            "params": {
                "video_subject": "Dose Diária de GTA VI",
                "video_script": self.script_text,
                "voice_name": "pt-BR-AntonioNeural-Male",
                "voice_volume": 0.8,
                "voice_rate": 1.0,
                "bgm_type": "random",
                "bgm_volume": 0.1,
                "subtitle_enabled": True,
            },
            "scene_plan": self.scene_plan_data,
        }

        with open(os.path.join(self.source_task_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(self.original_script_data, f)

        # Criar clips sintéticos no diretório Flow
        clip1_path = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        clip2_path = os.path.join(self.clips_dir, "flow_scene_02.mp4")
        with open(clip1_path, "wb") as f:
            f.write(b"MOCK_CLIP_1_DATA" * 100)
        with open(clip2_path, "wb") as f:
            f.write(b"MOCK_CLIP_2_DATA" * 100)

        # manifest.json sintético
        manifest_data = {
            "project_name": "gta_vi_flow",
            "scenes": [
                {"scene_index": 1, "expected_clip": "flow_scene_01.mp4", "is_flow_premium": True},
                {"scene_index": 2, "expected_clip": "flow_scene_02.mp4", "is_flow_premium": True},
            ],
        }
        with open(os.path.join(self.flow_dir, "manifest.json"), "w", encoding="utf-8") as f:
            json.dump(manifest_data, f)

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_missing_source_task_fails_closed(self):
        """Valida que ausência do script.json original levanta FileNotFoundError fail-closed."""
        with self.assertRaises(FileNotFoundError) as ctx:
            run_g8_8_homologation(
                source_task_id="non-existent-task-id",
                base_dir=self.test_dir,
            )
        self.assertIn("script.json da task original não encontrado", str(ctx.exception))

    def test_missing_scene_plan_fails_closed(self):
        """Valida que script.json sem scene_plan levanta ValueError fail-closed."""
        bad_script_data = dict(self.original_script_data)
        del bad_script_data["scene_plan"]
        with open(os.path.join(self.source_task_dir, "script.json"), "w", encoding="utf-8") as f:
            json.dump(bad_script_data, f)

        with self.assertRaises(ValueError) as ctx:
            run_g8_8_homologation(
                source_task_id=self.source_task_id,
                base_dir=self.test_dir,
            )
        self.assertIn("scene_plan ausente", str(ctx.exception))

    @patch("scripts.flow_workflow.validate_clip_file")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.subtitle.validate_subtitle_file")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.scene_assembly.get_ordered_video_paths")
    @patch("app.services.task.generate_final_videos")
    @patch("app.utils.utils.task_dir")
    def test_successful_g8_8_controlled_execution(
        self,
        mock_task_dir,
        mock_generate_final_videos,
        mock_get_ordered_video_paths,
        mock_assemble_scene_clips,
        mock_validate_sub,
        mock_generate_subtitle,
        mock_generate_audio,
        mock_validate_clip,
    ):
        """Valida execução completa sem chamadas de rede ou APIs pagas."""
        val_task_id = "g8-audio-validation-test-001"
        val_dir = os.path.join(self.test_dir, "storage", "tasks", val_task_id)
        os.makedirs(val_dir, exist_ok=True)
        mock_task_dir.return_value = val_dir

        mock_validate_clip.return_value = {"valid": True}

        # Mock áudio gerado
        mock_audio_path = os.path.join(val_dir, "audio.mp3")
        with open(mock_audio_path, "wb") as f:
            f.write(b"MOCK_AUDIO" * 50)
        mock_generate_audio.return_value = (mock_audio_path, 10.0, MagicMock())

        # Mock legenda gerada
        mock_sub_path = os.path.join(val_dir, "subtitle.srt")
        with open(mock_sub_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nTeste legenda\n")
        mock_generate_subtitle.return_value = mock_sub_path
        mock_validate_sub.return_value = {"valid": True}

        # Mock instruções e paths de vídeo
        clip1_path = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        clip2_path = os.path.join(self.clips_dir, "flow_scene_02.mp4")
        mock_instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=clip1_path,
                start_time_seconds=0.0,
                duration_seconds=5.0,
            ),
            SceneClipInstruction(
                scene_index=2,
                material_path=clip2_path,
                start_time_seconds=0.0,
                duration_seconds=5.0,
            ),
        ]
        mock_assemble_scene_clips.return_value = mock_instructions
        mock_get_ordered_video_paths.return_value = [clip1_path, clip2_path]

        # Mock render final
        mock_final_path = os.path.join(val_dir, "final-1.mp4")
        with open(mock_final_path, "wb") as f:
            f.write(b"MOCK_FINAL_VIDEO_BYTES" * 1024 * 50)  # ~1MB
        mock_generate_final_videos.return_value = ([mock_final_path], [], [])

        # Executa homologação
        res = run_g8_8_homologation(
            source_task_id=self.source_task_id,
            profile_id="profile-2095da4fbe23",
            validation_task_id=val_task_id,
            base_dir=self.test_dir,
        )

        # Verificações de integridade
        self.assertEqual(res["status"], "SUCCESS")
        self.assertEqual(res["source_task_id"], self.source_task_id)
        self.assertEqual(res["validation_task_id"], val_task_id)
        self.assertEqual(res["voice_name"], "en-US-BrianMultilingualNeural")
        self.assertEqual(res["voice_rate"], 0.8)
        self.assertEqual(res["voice_volume"], 1.0)
        self.assertEqual(res["bgm_type"], "ambient_auto")
        self.assertEqual(res["bgm_volume"], 0.20)
        self.assertEqual(res["bgm_default_mood"], "futuristic")
        self.assertEqual(res["bgm_provenance"], "SAFE_PROCEDURAL")
        self.assertEqual(res["flow_calls"], 0)
        self.assertEqual(res["paid_visual_api_calls"], 0)
        self.assertEqual(res["paid_api_calls"], 0)
        self.assertEqual(res["publication_calls"], 0)
        self.assertEqual(res["tts_generation"], "BRIAN_EXPECTED")
        self.assertEqual(res["scenes"], 2)
        self.assertEqual(res["existing_materials_reused"], 2)
        self.assertEqual(res["new_visual_assets_generated"], "NO")
        self.assertEqual(res["final_video_exists"], "YES")
        self.assertGreater(res["final_video_size_mb"], 0.0)
        self.assertEqual(res["original_task_modified"], "NO")
        self.assertEqual(res["gen_worker"], "NOT_MEASURED_STANDALONE")
        self.assertIn(res["auto_publish"], ("ON", "OFF"))
        self.assertIn(res["factory"], ("RUNNING", "PAUSED"))

        # Verifica que o script.json original permaneceu intocado
        with open(os.path.join(self.source_task_dir, "script.json"), "r", encoding="utf-8") as f:
            persisted_original = json.load(f)
        self.assertEqual(persisted_original["params"]["voice_name"], "pt-BR-AntonioNeural-Male")
        self.assertEqual(persisted_original["params"]["bgm_type"], "random")

        # Verifica que a chamada a generate_audio usou Brian e roteiro original
        called_params = mock_generate_audio.call_args[0][1]
        self.assertEqual(called_params.voice_name, "en-US-BrianMultilingualNeural")
        self.assertEqual(called_params.voice_rate, 0.8)
        self.assertEqual(called_params.voice_volume, 1.0)
        self.assertEqual(called_params.bgm_type, "ambient_auto")
        self.assertEqual(called_params.bgm_volume, 0.20)

    @patch("scripts.flow_workflow.generate_pending_flow_scenes")
    @patch("scripts.flow_workflow.validate_clip_file")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.subtitle.validate_subtitle_file")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.scene_assembly.get_ordered_video_paths")
    @patch("app.services.task.generate_final_videos")
    @patch("app.utils.utils.task_dir")
    def test_flow_generation_is_never_called(
        self,
        mock_task_dir,
        mock_generate_final_videos,
        mock_get_ordered_video_paths,
        mock_assemble_scene_clips,
        mock_validate_sub,
        mock_generate_subtitle,
        mock_generate_audio,
        mock_validate_clip,
        mock_generate_pending_flow_scenes,
    ):
        """Garante que generate_pending_flow_scenes NÃO é chamado durante a homologação."""
        val_task_id = "g8-audio-validation-test-002"
        val_dir = os.path.join(self.test_dir, "storage", "tasks", val_task_id)
        os.makedirs(val_dir, exist_ok=True)
        mock_task_dir.return_value = val_dir

        mock_validate_clip.return_value = {"valid": True}
        mock_audio_path = os.path.join(val_dir, "audio.mp3")
        with open(mock_audio_path, "wb") as f:
            f.write(b"MOCK_AUDIO" * 50)
        mock_generate_audio.return_value = (mock_audio_path, 10.0, MagicMock())

        mock_sub_path = os.path.join(val_dir, "subtitle.srt")
        with open(mock_sub_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nTeste\n")
        mock_generate_subtitle.return_value = mock_sub_path
        mock_validate_sub.return_value = {"valid": True}

        clip1_path = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        mock_instructions = [
            SceneClipInstruction(
                scene_index=1,
                material_path=clip1_path,
                start_time_seconds=0.0,
                duration_seconds=5.0,
            ),
        ]
        mock_assemble_scene_clips.return_value = mock_instructions
        mock_get_ordered_video_paths.return_value = [clip1_path]

        mock_final_path = os.path.join(val_dir, "final-1.mp4")
        with open(mock_final_path, "wb") as f:
            f.write(b"MOCK_FINAL_VIDEO" * 100)
        mock_generate_final_videos.return_value = ([mock_final_path], [], [])

        res = run_g8_8_homologation(
            source_task_id=self.source_task_id,
            base_dir=self.test_dir,
        )

        mock_generate_pending_flow_scenes.assert_not_called()
        self.assertEqual(res["flow_calls"], 0)
        self.assertEqual(res["paid_visual_api_calls"], 0)

    @patch("app.services.scheduler.get_all_settings")
    @patch("app.services.operator_console.get_factory_state")
    @patch("scripts.flow_workflow.validate_clip_file")
    @patch("app.services.task.generate_audio")
    @patch("app.services.task.generate_subtitle")
    @patch("app.services.subtitle.validate_subtitle_file")
    @patch("app.services.scene_assembly.assemble_scene_clips")
    @patch("app.services.scene_assembly.get_ordered_video_paths")
    @patch("app.services.task.generate_final_videos")
    @patch("app.utils.utils.task_dir")
    def test_operational_report_telemetry_sources(
        self,
        mock_task_dir,
        mock_generate_final_videos,
        mock_get_ordered_video_paths,
        mock_assemble_scene_clips,
        mock_validate_sub,
        mock_generate_subtitle,
        mock_generate_audio,
        mock_validate_clip,
        mock_get_factory_state,
        mock_get_all_settings,
    ):
        """Valida que auto_publish e factory refletem consultas dinâmicas reais."""
        val_task_id = "g8-audio-validation-test-003"
        val_dir = os.path.join(self.test_dir, "storage", "tasks", val_task_id)
        os.makedirs(val_dir, exist_ok=True)
        mock_task_dir.return_value = val_dir

        mock_validate_clip.return_value = {"valid": True}
        mock_audio_path = os.path.join(val_dir, "audio.mp3")
        with open(mock_audio_path, "wb") as f:
            f.write(b"MOCK_AUDIO" * 50)
        mock_generate_audio.return_value = (mock_audio_path, 10.0, MagicMock())

        mock_sub_path = os.path.join(val_dir, "subtitle.srt")
        with open(mock_sub_path, "w", encoding="utf-8") as f:
            f.write("1\n00:00:00,000 --> 00:00:05,000\nTeste\n")
        mock_generate_subtitle.return_value = mock_sub_path
        mock_validate_sub.return_value = {"valid": True}

        clip1_path = os.path.join(self.clips_dir, "flow_scene_01.mp4")
        mock_assemble_scene_clips.return_value = [
            SceneClipInstruction(scene_index=1, material_path=clip1_path, start_time_seconds=0.0, duration_seconds=5.0)
        ]
        mock_get_ordered_video_paths.return_value = [clip1_path]

        mock_final_path = os.path.join(val_dir, "final-1.mp4")
        with open(mock_final_path, "wb") as f:
            f.write(b"MOCK_FINAL_VIDEO" * 100)
        mock_generate_final_videos.return_value = ([mock_final_path], [], [])

        # Cenário 1: auto_publish_enabled=True, factory_state="PAUSED"
        mock_get_all_settings.return_value = {"auto_publish_enabled": True}
        mock_get_factory_state.return_value = "PAUSED"

        res1 = run_g8_8_homologation(source_task_id=self.source_task_id, base_dir=self.test_dir)
        self.assertEqual(res1["auto_publish"], "ON")
        self.assertEqual(res1["factory"], "PAUSED")
        self.assertEqual(res1["gen_worker"], "NOT_MEASURED_STANDALONE")

        # Cenário 2: auto_publish_enabled=False, factory_state="RUNNING"
        mock_get_all_settings.return_value = {"auto_publish_enabled": False}
        mock_get_factory_state.return_value = "RUNNING"

        res2 = run_g8_8_homologation(source_task_id=self.source_task_id, base_dir=self.test_dir)
        self.assertEqual(res2["auto_publish"], "OFF")
        self.assertEqual(res2["factory"], "RUNNING")
        self.assertEqual(res2["gen_worker"], "NOT_MEASURED_STANDALONE")


if __name__ == "__main__":
    unittest.main()

