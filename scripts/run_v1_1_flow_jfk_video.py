"""
scripts/run_v1_1_flow_jfk_video.py
==================================
V1.1 — First Real Video with Google Flow Clips & Video Factory Pipeline.

Monta o primeiro vídeo REAL da frente VIDEO_QUALITY_GOOGLE_FLOW utilizando:
- 4 clipes de alta fidelidade gerados no Google Flow:
  1. flow_01_dallas.mp4
  2. flow_02_parkland.mp4
  3. flow_03_nuclear_briefcase.mp4
  4. flow_04_cold_war.mp4
- Pipeline nativo da Video Factory:
  - Roteiro narrativo e TTS neural (pt-BR-AntonioNeural-Male)
  - Legendas ASS nativas da Video Factory (bottom, 60px, contraste #FFFFFF/#000000)
  - Trilha sonora (BGM random @ 0.2)
  - Concatenação sequencial e render final 9:16 (1080x1920)
  - Áudio interno dos clipes Flow ignorado por padrão
"""

from __future__ import annotations

import os
import shutil
import sys
import time

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from moviepy import VideoFileClip  # noqa: E402

from app.models.schema import (  # noqa: E402
    MaterialInfo,
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
)
from app.services import task, video  # noqa: E402
from app.services.media_quality import probe_media  # noqa: E402


FLOW_MEDIA_DIR = os.path.join(ROOT_DIR, "storage", "manual_media", "flow_jfk")
LOCAL_VIDEOS_DIR = os.path.join(ROOT_DIR, "storage", "local_videos")
TASK_ID = "v1_1_flow_jfk_001"

SCRIPT_TEXT = (
    "Em vinte e dois de novembro de 1963, em Dallas, o comboio presidencial de John Kennedy desfilava em festa, "
    "sem imaginar o trágico destino.\n"
    "Segundos após os disparos, o carro acelerou desesperadamente para o Parkland Memorial Hospital, "
    "onde médicos lutaram contra o tempo.\n"
    "No meio do caos, um oficial militar protegia a misteriosa maleta preta: a Football, "
    "com os códigos nucleares dos Estados Unidos.\n"
    "No auge da Guerra Fria, enquanto o mundo chorava a morte de JFK, o poder nuclear permanecia guardado naquela maleta."
)

FLOW_CLIPS = [
    "flow_01_dallas.mp4",
    "flow_02_parkland.mp4",
    "flow_03_nuclear_briefcase.mp4",
    "flow_04_cold_war.mp4",
]


def ensure_local_materials():
    os.makedirs(LOCAL_VIDEOS_DIR, exist_ok=True)
    for clip_name in FLOW_CLIPS:
        src = os.path.join(FLOW_MEDIA_DIR, clip_name)
        dst = os.path.join(LOCAL_VIDEOS_DIR, clip_name)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Clips fonte do Flow não encontrado: {src}")
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
            shutil.copy2(src, dst)
            print(f"  [COPY] {clip_name} copiado para {LOCAL_VIDEOS_DIR}")
        else:
            print(f"  [READY] {clip_name} já disponível em {LOCAL_VIDEOS_DIR}")


def run_pipeline() -> str:
    print("=" * 70)
    print("V1.1 FIRST REAL VIDEO EXECUTION — FLOW JFK BRIEFCASE")
    print("=" * 70)

    print("\n[Passo 1/3] Garantindo materiais locais em storage/local_videos...")
    ensure_local_materials()

    params = VideoParams(
        video_subject="A Misteriosa Maleta de JFK",
        video_script=SCRIPT_TEXT,
        video_language="pt-BR",
        video_source="local",
        video_materials=[
            MaterialInfo(provider="local", url=clip_name)
            for clip_name in FLOW_CLIPS
        ],
        video_concat_mode=VideoConcatMode.sequential,
        video_fit_mode=VideoFitMode.cover,
        video_clip_duration=10,
        video_aspect=VideoAspect.portrait,
        voice_name="pt-BR-AntonioNeural-Male",
        voice_volume=1.0,
        voice_rate=1.0,
        bgm_type="random",
        bgm_volume=0.2,
        subtitle_enabled=True,
        font_name="STHeitiMedium.ttc",
        font_size=60,
        text_fore_color="#FFFFFF",
        stroke_color="#000000",
        stroke_width=2.0,
        subtitle_position="bottom",
    )

    print("\n[Passo 2/3] Executando pipeline completo da Video Factory...")
    t_start = time.perf_counter()
    result = task.start(TASK_ID, params, stop_at="video")
    t_duration = time.perf_counter() - t_start
    print(f"Pipeline concluído em {t_duration:.2f}s")

    if not result or result.get("state") == "failed":
        raise RuntimeError(f"Pipeline falhou: {result}")

    final_videos = result.get("videos") or []
    if not final_videos:
        raise RuntimeError(f"Nenhum vídeo final retornado: {result}")

    final_video = final_videos[0]
    print(f"\n[Passo 3/3] Validando vídeo gerado: {final_video}")
    assert os.path.exists(final_video), f"Arquivo não encontrado: {final_video}"
    size_bytes = os.path.getsize(final_video)
    print(f"Tamanho do arquivo: {size_bytes / (1024 * 1024):.2f} MB ({size_bytes} bytes)")
    assert size_bytes > 0, "Vídeo final tem 0 bytes!"

    clip = VideoFileClip(final_video)
    print(f"Resolução: {clip.w}x{clip.h} (Esperado 1080x1920)")
    print(f"Duração: {clip.duration:.2f}s")
    print(f"FPS: {clip.fps}")
    has_audio = clip.audio is not None
    audio_dur = clip.audio.duration if has_audio else 0.0
    print(f"Faixa de áudio presente: {has_audio} (Duração: {audio_dur:.2f}s)")
    clip.close()

    assert clip.w == 1080 and clip.h == 1920, f"Resolução incorreta: {clip.w}x{clip.h}"
    assert clip.duration > 30.0, f"Duração inesperada: {clip.duration:.2f}s"
    assert has_audio and audio_dur > 30.0, "Áudio ausente ou incompleto no vídeo final"

    print("\n" + "=" * 70)
    print("RESULTADO: PASS — VÍDEO FINAL GERADO COM SUCESSO!")
    print(f"Caminho do vídeo: {final_video}")
    print("=" * 70)
    return final_video


if __name__ == "__main__":
    run_pipeline()
