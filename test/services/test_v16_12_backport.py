import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest
import requests

from app.config import config
from app.services import material, upload_post, video
from app.services.cache_manager import _VIDEO_CACHE_TEMP_FILE_PATTERN, clean_video_cache


def test_concurrency_defaults():
    """Concurrency settings must default strictly to 1 (serial execution)."""
    assert material._get_material_concurrency() == 1
    assert video._get_clip_processing_concurrency() == 1
    assert config.app.get("material_concurrency") == 1
    assert config.app.get("video_clip_concurrency") == 1
    assert config.app.get("ffmpeg_concat_timeout_seconds") == 3600


def test_bt709_color_parameters():
    """BT.709 filter and parameters must tag the stream and use BT.709 color matrix."""
    assert "out_color_matrix=bt709" in video._BT709_VIDEO_FILTER
    assert "color_primaries=bt709" in video._BT709_VIDEO_FILTER
    assert "color_trc=bt709" in video._BT709_VIDEO_FILTER
    assert "colorspace=bt709" in video._BT709_VIDEO_FILTER
    assert video._BT709_FFMPEG_PARAMS == ["-vf", video._BT709_VIDEO_FILTER]


def test_ffmpeg_concat_timeout_raises_timeout_error():
    """Hanging FFmpeg call must time out and raise TimeoutError without fallback retry."""
    with patch.dict(config.app, {"ffmpeg_concat_timeout_seconds": 0.05}):
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired(cmd=["ffmpeg"], timeout=0.05)):
            with pytest.raises(TimeoutError) as exc_info:
                video._run_concat_with_heartbeat(["ffmpeg"], "output.mp4")
            assert "exceeded" in str(exc_info.value)


def test_atomic_final_render_preserves_valid_file_on_failure():
    """Failed encode must not overwrite or corrupt an already existing valid video."""
    with tempfile.TemporaryDirectory() as tmpdir:
        target_video = os.path.join(tmpdir, "final.mp4")
        with open(target_video, "w") as f:
            f.write("VALID_ORIGINAL_CONTENT")

        fake_clip = MagicMock()
        fake_clip.write_videofile.side_effect = RuntimeError("Encoding failure")

        with pytest.raises(RuntimeError):
            video._write_videofile_with_codec_fallback(
                clip=fake_clip,
                output_file=target_video,
                codec="libx264",
                atomic_output=True,
            )

        # Target file must remain untouched and intact
        assert os.path.exists(target_video)
        with open(target_video, "r") as f:
            assert f.read() == "VALID_ORIGINAL_CONTENT"

        # Staged temp files must be cleaned
        remaining_files = os.listdir(tmpdir)
        assert remaining_files == ["final.mp4"]


def test_temp_file_cleanup_on_concat_failure():
    """Temporary clips must be cleaned up even if concatenation fails."""
    with tempfile.TemporaryDirectory() as tmpdir:
        clip1 = os.path.join(tmpdir, "mat-1.mp4")
        clip2 = os.path.join(tmpdir, "mat-2.mp4")
        for p in (clip1, clip2):
            with open(p, "w") as f:
                f.write("content")

        with patch("app.services.video.AudioFileClip") as mock_audio:
            mock_audio.return_value.duration = 10.0
            with patch("app.services.video._open_video_clip_quietly") as mock_clip:
                m = MagicMock(duration=10.0, size=(1080, 1920), w=1080, h=1920)
                m.subclipped.return_value = m
                mock_clip.return_value = m

                with patch("app.services.video._write_videofile_with_codec_fallback") as mock_write:
                    def fake_write(clip, clip_file, **kwargs):
                        with open(clip_file, "w") as f:
                            f.write("temp clip")
                    mock_write.side_effect = fake_write

                    with patch("app.services.video.concat_video_clips_with_ffmpeg", side_effect=RuntimeError("Concat error")):
                        with pytest.raises(RuntimeError):
                            video.combine_videos(
                                combined_video_path=os.path.join(tmpdir, "combined.mp4"),
                                video_paths=[],
                                audio_file=os.path.join(tmpdir, "audio.mp3"),
                                scene_clip_instructions=[
                                    MagicMock(scene_index=1, material_path=clip1, duration_seconds=5.0),
                                    MagicMock(scene_index=2, material_path=clip2, duration_seconds=5.0),
                                ],
                            )

        # Temp rendered clip files must be cleaned up in finally block
        temp_clip_1 = os.path.join(tmpdir, "temp-clip-scene-1.mp4")
        temp_clip_2 = os.path.join(tmpdir, "temp-clip-scene-2.mp4")
        assert not os.path.exists(temp_clip_1)
        assert not os.path.exists(temp_clip_2)
        # Source material files remain intact
        assert os.path.exists(clip1)
        assert os.path.exists(clip2)


def test_stock_download_corrupted_file_rejection_and_atomic_replace():
    """Corrupted downloaded video must be rejected and not promoted to cache."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_url = "https://example.com/video.mp4?sig=123#frag"

        # Mock requests.get returning empty or invalid stream
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": "100"}
        mock_resp.iter_content.return_value = [b"CORRUPTED_BYTES"]
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("requests.get", return_value=mock_resp):
            with patch("app.services.material.VideoFileClip", side_effect=Exception("Corrupt video")):
                saved = material.save_video(fake_url, save_dir=tmpdir)
                assert saved == ""

        # Cache must be clean, no corrupt .mp4 left
        assert len(os.listdir(tmpdir)) == 0


def test_stock_download_size_cap_enforcement():
    """Downloads declaring or sending > 512MB must be rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        fake_url = "https://example.com/huge_video.mp4"

        # Declared size > 512MB
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        mock_resp.headers = {"Content-Length": str(material.MAX_VIDEO_DOWNLOAD_BYTES + 1024)}
        mock_resp.__enter__.return_value = mock_resp
        mock_resp.__exit__.return_value = None

        with patch("requests.get", return_value=mock_resp):
            with pytest.raises(ValueError, match="exceeds 512 MB limit"):
                material.save_video(fake_url, save_dir=tmpdir)

        # No partial files left
        assert len(os.listdir(tmpdir)) == 0


def test_cache_manager_temp_file_pattern_and_cleanup():
    """Cache manager must recognize .vid-* temp files and clean aged ones."""
    pattern = _VIDEO_CACHE_TEMP_FILE_PATTERN
    assert pattern.fullmatch(".vid-0123456789abcdef0123456789abcdef-xyz.mp4")
    assert not pattern.fullmatch("vid-0123456789abcdef0123456789abcdef.mp4")

    with tempfile.TemporaryDirectory() as tmpdir:
        with patch("app.services.cache_manager.video_cache_dir", return_value=os.path.realpath(tmpdir)):
            aged_temp = os.path.join(tmpdir, ".vid-0123456789abcdef0123456789abcdef-tmp.mp4")
            with open(aged_temp, "w") as f:
                f.write("abandoned download")
            # Set mtime to 3 days ago
            old_time = 1000.0
            os.utime(aged_temp, (old_time, old_time))

            result = clean_video_cache()
            assert result.deleted_count == 1
            assert not os.path.exists(aged_temp)


def test_upload_post_redirect_rejection_and_client_request_id():
    """Upload-Post must reject 3xx redirects and include client_request_id for recovery."""
    service = upload_post.UploadPostService()
    with patch.object(service, "is_configured", return_value=True):
        with tempfile.TemporaryDirectory() as tmpdir:
            video_file = os.path.join(tmpdir, "test.mp4")
            with open(video_file, "wb") as f:
                f.write(b"video content")

            # Test redirect response
            mock_redirect = MagicMock(status_code=302)
            with patch("requests.post", return_value=mock_redirect) as mock_post:
                res = service.upload_video(video_file, "Test Title", platforms=["tiktok"])
                assert res["success"] is False
                assert "redirect" in res["error"]
                assert mock_post.call_args[1]["allow_redirects"] is False

            # Test timeout recovery request_id
            with patch("requests.post", side_effect=requests.exceptions.Timeout("Read timeout")):
                res = service.upload_video(video_file, "Test Title", platforms=["tiktok"])
                assert res["success"] is False
                assert "request_id" in res
                assert "unconfirmed" in res["error"]


def test_stage_progress_reporting_flow():
    """Pipeline stages must be triggered in sequence."""
    stages_seen = []

    def on_stage(stage):
        stages_seen.append(stage)

    # Test combine_videos stage emission with mock clips
    with tempfile.TemporaryDirectory() as tmpdir:
        clip_path = os.path.join(tmpdir, "mat.mp4")
        with open(clip_path, "w") as f:
            f.write("clip")

        with patch("app.services.video.AudioFileClip") as mock_audio:
            mock_audio.return_value.duration = 5.0
            with patch("app.services.video.concat_video_clips_with_ffmpeg"):
                with patch("app.services.video._open_video_clip_quietly") as mock_clip:
                    m = MagicMock(duration=10.0, size=(1080, 1920), w=1080, h=1920)
                    m.subclipped.return_value = m
                    mock_clip.return_value = m
                    with patch("app.services.video._write_videofile_with_codec_fallback") as mock_write:
                        def fake_write(clip, clip_file, **kwargs):
                            with open(clip_file, "w") as f:
                                f.write("clip")
                        mock_write.side_effect = fake_write

                        video.combine_videos(
                            combined_video_path=os.path.join(tmpdir, "combined.mp4"),
                            video_paths=[],
                            audio_file=os.path.join(tmpdir, "audio.mp3"),
                            scene_clip_instructions=[
                                MagicMock(scene_index=1, material_path=clip_path, duration_seconds=5.0, fit_mode=None)
                            ],
                            stage_callback=on_stage,
                        )

    assert "SCENE_RENDER_PREP" in stages_seen
    assert "SCENE_RENDER_CLIPS" in stages_seen
    assert "CONCAT" in stages_seen
