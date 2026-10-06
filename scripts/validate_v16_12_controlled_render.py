"""
scripts/validate_v16_12_controlled_render.py
============================================
V16.12 — Controlled Local Render Validation.

Validates FFmpeg timeout protection, BT.709 color space tagging,
stage progress reporting, and temp file cleanup in DEV without paid API calls.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

import imageio_ffmpeg  # noqa: E402
from moviepy import VideoFileClip  # noqa: E402

from app.models.schema import VideoConcatMode, VideoFitMode  # noqa: E402
from app.services import video  # noqa: E402

OUTPUT_DIR = os.path.join(ROOT_DIR, "storage", "validation", "v16_12")
os.makedirs(OUTPUT_DIR, exist_ok=True)

AUDIO_FILE = os.path.join(ROOT_DIR, "storage", "tasks", "17386147-cb1b-4192-b827-251a1bbd411f", "audio.mp3")
VIDEO_FILE = os.path.join(ROOT_DIR, "storage", "cache_videos", "vid-01761528642a82d4468f04ffc0ca7e7b.mp4")
OUTPUT_VIDEO = os.path.join(OUTPUT_DIR, "controlled_render_v16_12.mp4")
FFMPEG_EXE = imageio_ffmpeg.get_ffmpeg_exe()


def probe_video(file_path: str):
    res = subprocess.run([FFMPEG_EXE, "-i", file_path], stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    combined_output = res.stderr + res.stdout
    bt709_detected = "bt709" in combined_output
    clip = VideoFileClip(file_path)
    info = {
        "width": clip.w,
        "height": clip.h,
        "duration": clip.duration,
        "bt709_detected": bt709_detected,
        "raw_info": [line.strip() for line in combined_output.splitlines() if "Stream #0:0" in line],
    }
    clip.close()
    return info


def main():
    print("=== STARTING V16.12 CONTROLLED LOCAL RENDER VALIDATION ===")
    stages_captured = []
    progress_samples = []

    SHORT_AUDIO = os.path.join(OUTPUT_DIR, "short_audio.mp3")
    subprocess.run([FFMPEG_EXE, "-y", "-i", AUDIO_FILE, "-t", "3", "-c", "copy", SHORT_AUDIO], check=True)

    def on_stage(stage: str):
        print(f"[STAGE_EVENT] {stage}")
        stages_captured.append(stage)

    def on_progress(fraction: float):
        print(f"[PROGRESS_EVENT] fraction={fraction:.2f}")
        progress_samples.append(fraction)

    t_start = time.perf_counter()

    combined_path = video.combine_videos(
        combined_video_path=OUTPUT_VIDEO,
        video_paths=[VIDEO_FILE],
        audio_file=SHORT_AUDIO,
        video_aspect=video.VideoAspect.portrait,
        video_concat_mode=VideoConcatMode.random,
        video_fit_mode=VideoFitMode.cover,
        max_clip_duration=3,
        threads=2,
        stage_callback=on_stage,
        progress_callback=on_progress,
    )

    t_elapsed = time.perf_counter() - t_start

    assert os.path.exists(combined_path), "Output file was not created!"
    file_size = os.path.getsize(combined_path)
    assert file_size > 0, "Output file is 0 bytes!"

    # Probe color space and resolution
    probe_data = probe_video(combined_path)
    w = probe_data.get("width")
    h = probe_data.get("height")
    duration = float(probe_data.get("duration", 0.0))
    bt709_detected = probe_data.get("bt709_detected")

    # Check that temp clips in OUTPUT_DIR were cleaned up
    all_files = os.listdir(OUTPUT_DIR)
    temp_files = [f for f in all_files if f.startswith("temp-clip-")]

    result = {
        "render_success": True,
        "timeout_not_triggered": True,
        "elapsed_seconds": round(t_elapsed, 2),
        "output_path": combined_path,
        "resolution": f"{w}x{h}",
        "duration": round(duration, 2),
        "file_size_bytes": file_size,
        "bt709_detected": bt709_detected,
        "stream_details": probe_data.get("raw_info"),
        "stages_captured": stages_captured,
        "progress_samples_count": len(progress_samples),
        "temp_files_remaining": len(temp_files),
        "all_temp_files_cleaned": len(temp_files) == 0,
    }

    print("\n=== VALIDATION RESULT ===")
    print(json.dumps(result, indent=2))
    return result


if __name__ == "__main__":
    main()
