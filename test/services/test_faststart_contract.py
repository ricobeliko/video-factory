import os
import shutil
import sqlite3
import struct
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.services import video
from scripts import remux_faststart
from app.services import copyright_gate


class TestFaststartContract(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp(prefix="test_faststart_")

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_ffmpeg_commands_include_faststart_for_mp4(self):
        """Verifica se _render_final_stream_copy e _render_final_ffmpeg_ass incluem -movflags +faststart para saídas MP4."""
        # 1. Test stream copy command construction
        with patch("app.services.video._run_concat_with_heartbeat") as mock_run:
            mock_run.return_value = MagicMock(returncode=1, stderr="mocked")
            video._render_final_stream_copy(
                video_path="dummy_in.mp4",
                audio_path="dummy_audio.m4a",
                output_file=os.path.join(self.test_dir, "final-1.mp4"),
            )
            self.assertTrue(mock_run.called)
            cmd = mock_run.call_args[0][0]
            self.assertIn("-movflags", cmd)
            idx = cmd.index("-movflags")
            self.assertEqual(cmd[idx + 1], "+faststart")

        # 2. Test ffmpeg ass command construction
        with patch("app.services.video._run_concat_with_heartbeat") as mock_run_ass:
            mock_run_ass.return_value = MagicMock(returncode=1, stderr="mocked")
            video._render_final_ffmpeg_ass(
                video_path="dummy_in.mp4",
                audio_path="dummy_audio.m4a",
                ass_path="dummy.ass",
                output_file=os.path.join(self.test_dir, "final-1.mp4"),
            )
            self.assertTrue(mock_run_ass.called)
            cmd_ass = mock_run_ass.call_args[0][0]
            self.assertIn("-movflags", cmd_ass)
            idx_ass = cmd_ass.index("-movflags")
            self.assertEqual(cmd_ass[idx_ass + 1], "+faststart")

    def test_moov_position_in_rendered_mp4(self):
        """Verifica se um MP4 gerado com -movflags +faststart possui o átomo moov antes de mdat."""
        out_mp4 = os.path.join(self.test_dir, "test_render.mp4")
        # Gera vídeo mínimo sintético via ffmpeg
        ffmpeg_bin = video.utils.get_ffmpeg_binary()
        cmd = [
            ffmpeg_bin,
            "-y",
            "-f", "lavfi", "-i", "testsrc=duration=1:size=320x240:rate=10",
            "-f", "lavfi", "-i", "sine=frequency=1000:duration=1",
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
            "-c:a", "aac",
            "-movflags", "+faststart",
            out_mp4,
        ]
        import subprocess
        res = subprocess.run(cmd, capture_output=True)
        self.assertEqual(res.returncode, 0, f"FFmpeg failed: {res.stderr}")

        atoms = remux_faststart.check_mp4_atoms(out_mp4)
        atom_names = [a[0] for a in atoms]
        self.assertIn("moov", atom_names)
        self.assertIn("mdat", atom_names)
        self.assertTrue(
            remux_faststart.is_already_faststart(atoms),
            f"moov deve vir antes de mdat: {atoms}"
        )

    def test_remux_blocks_manual_approval_with_sha256(self):
        """Garante que remux_faststart bloqueia tarefas com aprovação manual de Copyright vinculada a SHA-256."""
        db_path = os.path.join(self.test_dir, "test.db")
        with sqlite3.connect(db_path) as conn:
            conn.execute("""
                CREATE TABLE operational_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_type TEXT,
                    task_id TEXT,
                    metadata_json TEXT
                );
            """)
            conn.execute(
                "INSERT INTO operational_events (event_type, task_id, metadata_json) VALUES (?, ?, ?);",
                (
                    copyright_gate.EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL,
                    "task-legacy-123",
                    '{"final_video_sha256": "abcdef1234567890"}',
                ),
            )
            conn.commit()

        is_safe, reason = remux_faststart.evaluate_task_safety("task-legacy-123", db_path=db_path)
        self.assertFalse(is_safe)
        self.assertIn("BLOQUEIO", reason)
        self.assertIn("SHA-256", reason)


if __name__ == "__main__":
    unittest.main()
