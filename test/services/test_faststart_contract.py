import os
import shutil
import tempfile
import unittest
from unittest.mock import patch, MagicMock

from app.services import video


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


if __name__ == "__main__":
    unittest.main()
