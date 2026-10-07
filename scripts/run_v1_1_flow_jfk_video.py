"""
scripts/run_v1_1_flow_jfk_video.py
==================================
V1.1 — Full Real Video with Google Flow Clips & Video Factory Pipeline (75–90s).

Monta o vídeo COMPLETO da frente VIDEO_QUALITY_GOOGLE_FLOW utilizando:
- Narração original completa de JFK (~90s)
- 4 clipes de alta fidelidade do Google Flow como cenas premium nos momentos
  narrativos correspondentes:
    1. flow_01_dallas.mp4            (Dallas / comboio presidencial)
    2. flow_02_parkland.mp4          (Chegada veloz ao Parkland Hospital)
    3. flow_03_nuclear_briefcase.mp4 (Revelação da Football nuclear)
    4. flow_04_cold_war.mp4          (Monumento / guarda da Guerra Fria)
- Materiais stock locais pré-existentes da Video Factory para preencher
  as cenas restantes sem repetição nem esticamento artificial
- Timeline determinística via ScenePlan e SceneAssembly (V16.4)
- Legendas nativas ASS (bottom, 60px, contraste #FFFFFF/#000000)
- Trilha sonora (BGM random @ 0.2)
- Render final 9:16 (1080x1920)
"""

from __future__ import annotations

import os
import shutil
import sys
import time
from typing import List

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from moviepy import VideoFileClip  # noqa: E402

from app.models.schema import (  # noqa: E402
    MaterialInfo,
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    ScenePlanItem,
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
)
from app.services import scene_assembly, task, video, voice  # noqa: E402
from app.services import state as sm  # noqa: E402
from app.services import task_artifacts  # noqa: E402
from app.models import const  # noqa: E402
from app.utils import utils  # noqa: E402


FLOW_MEDIA_DIR = os.path.join(ROOT_DIR, "storage", "manual_media", "flow_jfk")
CACHE_VIDEOS_DIR = os.path.join(ROOT_DIR, "storage", "cache_videos")
LOCAL_VIDEOS_DIR = os.path.join(ROOT_DIR, "storage", "local_videos")
TASK_ID = "v1_1_flow_jfk_001"

# Roteiro integral original de JFK (~90s na cadência de Antônio Neural)
SCRIPT_TEXT = (
    "Você sabia que no momento mais dramático da Guerra Fria, o destino do planeta estava trancado dentro de uma misteriosa maleta preta?\n"
    "Em vinte e dois de novembro de mil novecentos e sessenta e três, em Dallas, o comboio presidencial de John F. Kennedy desfilava sob os aplausos calorosos da multidão, sem qualquer aviso da tragédia que se aproximava.\n"
    "Segundos após os disparos fatais, a limusine acelerou em desespero absoluto rumo ao Parkland Memorial Hospital, onde médicos travaram uma corrida angustiante contra o relógio para salvar o presidente.\n"
    "Nos corredores tomados pela comoção e pelo pânico, um oficial militar mantinha-se rigorosamente ao lado da equipe médica, guardando uma pasta preta de couro que jamais saía de sua vista.\n"
    "Era a maleta de emergência nuclear, conhecida nos bastidores de Washington como a Football, contendo os planos de guerra secretos e os códigos de autorização para disparar o arsenal atômico americano.\n"
    "Se o assassinato de Kennedy fosse o prenúncio de um ataque soviético surpresa, aquela pasta era o único instrumento capaz de ordenar uma retaliação imediata.\n"
    "Com a confirmação da morte de JFK, a custódia do poder militar supremo foi transferida em segredo absoluto para Lyndon Johnson, a bordo do Air Force One, antes mesmo do juramento oficial.\n"
    "Naquele dia sombrio em que a história dos Estados Unidos mudou para sempre, o mundo chorava o presidente, enquanto a misteriosa maleta nuclear permanecia alerta, guardando o poder mais aterrorizante do planeta."
)

FLOW_CLIPS = [
    "flow_01_dallas.mp4",
    "flow_02_parkland.mp4",
    "flow_03_nuclear_briefcase.mp4",
    "flow_04_cold_war.mp4",
]

# Materiais stock pré-existentes no cache local da Video Factory para preenchimento
FILLER_CLIPS = {
    "filler_01_earth.mp4": "vid-498b1cd58ebe6b8acc39f91f08dc80dc.mp4",     # Globo / Guerra Fria (13.93s)
    "filler_02_tension.mp4": "vid-a2392cd6ab4253b6cb3d76ca2b4d0ed0.mp4",   # Tensão / corrida contra o tempo (13.96s)
    "filler_03_apocalypse.mp4": "vid-7a07eb6cd2c5cf8bd74e31a7c995d325.mp4",# Alerta / ameaça global (10.69s)
    "filler_04_plane.mp4": "vid-c9d9e6e93adc6424727b29c5f98d46e1.mp4",     # Air Force One / voo em céu aberto (20.87s)
    "filler_05_outro.mp4": "vid-0cad444fc1f1bbbdb559ae5356ebe120.mp4",     # Atmosfera sombria final (22.80s)
}

# Configuração sequencial do ScenePlan: 9 cenas determinísticas
SCENE_CONFIGS = [
    {
        "scene_index": 1,
        "clip_file": "filler_01_earth.mp4",
        "duration_hint": 8.0,
        "narration": "Você sabia que no momento mais dramático da Guerra Fria, o destino do planeta estava trancado dentro de uma misteriosa maleta preta?",
        "is_flow": False,
    },
    {
        "scene_index": 2,
        "clip_file": "flow_01_dallas.mp4",
        "duration_hint": 9.8,
        "narration": "Em vinte e dois de novembro de mil novecentos e sessenta e três, em Dallas, o comboio presidencial de John F. Kennedy desfilava sob os aplausos calorosos da multidão, sem qualquer aviso da tragédia que se aproximava.",
        "is_flow": True,
    },
    {
        "scene_index": 3,
        "clip_file": "flow_02_parkland.mp4",
        "duration_hint": 9.8,
        "narration": "Segundos após os disparos fatais, a limusine acelerou em desespero absoluto rumo ao Parkland Memorial Hospital, onde médicos travaram uma corrida angustiante contra o relógio para salvar o presidente.",
        "is_flow": True,
    },
    {
        "scene_index": 4,
        "clip_file": "filler_02_tension.mp4",
        "duration_hint": 14.0,
        "narration": "Nos corredores tomados pela comoção e pelo pânico, um oficial militar mantinha-se rigorosamente ao lado da equipe médica, guardando uma pasta preta de couro que jamais saía de sua vista.",
        "is_flow": False,
    },
    {
        "scene_index": 5,
        "clip_file": "flow_03_nuclear_briefcase.mp4",
        "duration_hint": 9.8,
        "narration": "Era a maleta de emergência nuclear, conhecida nos bastidores de Washington como a Football, contendo os planos de guerra secretos e os códigos de autorização para disparar o arsenal atômico americano.",
        "is_flow": True,
    },
    {
        "scene_index": 6,
        "clip_file": "filler_03_apocalypse.mp4",
        "duration_hint": 10.0,
        "narration": "Se o assassinato de Kennedy fosse o prenúncio de um ataque soviético surpresa, aquela pasta era o único instrumento capaz de ordenar uma retaliação imediata.",
        "is_flow": False,
    },
    {
        "scene_index": 7,
        "clip_file": "filler_04_plane.mp4",
        "duration_hint": 14.0,
        "narration": "Com a confirmação da morte de JFK, a custódia do poder militar supremo foi transferida em segredo absoluto para Lyndon Johnson, a bordo do Air Force One, antes mesmo do juramento oficial.",
        "is_flow": False,
    },
    {
        "scene_index": 8,
        "clip_file": "flow_04_cold_war.mp4",
        "duration_hint": 9.8,
        "narration": "Naquele dia sombrio em que a história dos Estados Unidos mudou para sempre, o mundo chorava o presidente, enquanto a misteriosa maleta nuclear permanecia alerta,",
        "is_flow": True,
    },
    {
        "scene_index": 9,
        "clip_file": "filler_05_outro.mp4",
        "duration_hint": 5.8,
        "narration": "guardando o poder mais aterrorizante do planeta.",
        "is_flow": False,
    },
]


def ensure_local_materials():
    """Garante que tanto os clipes Flow quanto os materiais de preenchimento estejam disponíveis."""
    os.makedirs(LOCAL_VIDEOS_DIR, exist_ok=True)

    # 1. Clipes Google Flow
    for clip_name in FLOW_CLIPS:
        src = os.path.join(FLOW_MEDIA_DIR, clip_name)
        dst = os.path.join(LOCAL_VIDEOS_DIR, clip_name)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Clip fonte do Flow não encontrado: {src}")
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
            shutil.copy2(src, dst)
            print(f"  [FLOW READY] {clip_name} copiado para {LOCAL_VIDEOS_DIR}")
        else:
            print(f"  [FLOW READY] {clip_name} já disponível em {LOCAL_VIDEOS_DIR}")

    # 2. Clipes Stock de preenchimento
    for dest_name, src_cache_name in FILLER_CLIPS.items():
        src = os.path.join(CACHE_VIDEOS_DIR, src_cache_name)
        dst = os.path.join(LOCAL_VIDEOS_DIR, dest_name)
        if not os.path.exists(src):
            raise FileNotFoundError(f"Clip fonte de cache não encontrado: {src}")
        if not os.path.exists(dst) or os.path.getsize(dst) != os.path.getsize(src):
            shutil.copy2(src, dst)
            print(f"  [STOCK READY] {dest_name} copiado de {src_cache_name}")
        else:
            print(f"  [STOCK READY] {dest_name} já disponível em {LOCAL_VIDEOS_DIR}")


def run_pipeline() -> str:
    print("=" * 70)
    print("V1.1 FULL VIDEO EXECUTION — FLOW JFK BRIEFCASE (75–90s)")
    print("=" * 70)

    # 1. Garantir materiais locais
    print("\n[Passo 1/5] Garantindo materiais locais em storage/local_videos...")
    ensure_local_materials()

    task_dir = os.path.join(ROOT_DIR, "storage", "tasks", TASK_ID)
    os.makedirs(task_dir, exist_ok=True)

    params = VideoParams(
        video_subject="A Misteriosa Maleta de JFK",
        video_script=SCRIPT_TEXT,
        video_language="pt-BR",
        video_source="local",
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

    sm.state.update_task(TASK_ID, state=const.TASK_STATE_PROCESSING, progress=10)

    # 2. Gerar narração completa e legendas
    print("\n[Passo 2/5] Gerando narração completa e legendas sincronizadas...")
    audio_file, audio_duration, sub_maker = task.generate_audio(
        TASK_ID, params, SCRIPT_TEXT
    )
    if not audio_file or not os.path.exists(audio_file):
        raise RuntimeError(f"Falha ao sintetizar áudio da narração: {audio_file}")

    print(f"  Áudio gerado: {audio_file} ({audio_duration:.2f}s)")

    subtitle_path = task.generate_subtitle(
        TASK_ID, params, SCRIPT_TEXT, sub_maker, audio_file
    )
    print(f"  Legendas geradas: {subtitle_path}")

    sm.state.update_task(TASK_ID, state=const.TASK_STATE_PROCESSING, progress=35)

    # 3. Montar ScenePlan e instruções de corte
    print("\n[Passo 3/5] Construindo ScenePlan e instruções determinísticas...")
    scene_plan_items = [
        ScenePlanItem(
            scene_index=cfg["scene_index"],
            narration=cfg["narration"],
            duration_hint=cfg["duration_hint"],
            search_terms=[],
        )
        for cfg in SCENE_CONFIGS
    ]
    scene_plan = ScenePlan(
        total_scenes=len(scene_plan_items),
        scenes=scene_plan_items,
    )

    material_selections = [
        SceneMaterialSelection(
            scene_index=cfg["scene_index"],
            material_path=os.path.join(LOCAL_VIDEOS_DIR, cfg["clip_file"]),
            duration=cfg["duration_hint"],
            provider="google_flow" if cfg["is_flow"] else "pexels",
            asset_id=cfg["clip_file"],
            media_type="video",
            visual_source_type="flow" if cfg["is_flow"] else "stock",
        )
        for cfg in SCENE_CONFIGS
    ]

    instructions = scene_assembly.assemble_scene_clips(
        scene_plan=scene_plan,
        material_selections=material_selections,
        audio_duration=audio_duration,
        params=params,
        task_id=TASK_ID,
    )

    # Salvaguarda: garantir que clipes Flow nunca ultrapassem a duração física (10.01s)
    for inst in instructions:
        if "flow_" in os.path.basename(inst.material_path):
            inst.duration_seconds = min(inst.duration_seconds, 10.0)

    ordered_video_paths = scene_assembly.get_ordered_video_paths(instructions)
    print(f"  Instruções geradas: {len(instructions)} cenas (duração planejada: {sum(i.duration_seconds for i in instructions):.2f}s)")
    for inst in instructions:
        clip_name = os.path.basename(inst.material_path)
        tag = "[FLOW PREMIUM]" if "flow_" in clip_name else "[STOCK FILLER]"
        print(f"    Cena {inst.scene_index}: {inst.duration_seconds:.2f}s | {tag} {clip_name}")

    sm.state.update_task(TASK_ID, state=const.TASK_STATE_PROCESSING, progress=50)

    # 4. Renderizar vídeo combinado
    print("\n[Passo 4/5] Renderizando montagem combinada (FFmpeg stream copy)...")
    combined_video_path = os.path.join(task_dir, "combined-1.mp4")
    render_timings = {}
    video.combine_videos(
        combined_video_path=combined_video_path,
        video_paths=ordered_video_paths,
        audio_file=audio_file,
        video_aspect=params.video_aspect,
        video_concat_mode=VideoConcatMode.sequential,
        video_fit_mode=VideoFitMode.cover,
        max_clip_duration=params.video_clip_duration,
        threads=2,
        clip_speed=params.video_clip_speed,
        scene_clip_instructions=instructions,
        render_timings=render_timings,
    )

    if not os.path.exists(combined_video_path) or os.path.getsize(combined_video_path) == 0:
        raise RuntimeError("Falha ao gerar o vídeo combinado intermediário")

    print(f"  Vídeo combinado gerado: {combined_video_path} ({os.path.getsize(combined_video_path)} bytes)")

    # 5. Renderizar vídeo final com legendas e BGM
    print("\n[Passo 5/5] Sintetizando vídeo final com legendas ASS e BGM...")
    final_video_path = os.path.join(task_dir, "final-1.mp4")
    video.generate_video(
        video_path=combined_video_path,
        audio_path=audio_file,
        subtitle_path=subtitle_path,
        output_file=final_video_path,
        params=params,
        render_timings=render_timings,
    )

    if not os.path.exists(final_video_path) or os.path.getsize(final_video_path) == 0:
        raise RuntimeError("Falha ao gerar o vídeo final")

    # Persistir metadados da tarefa
    task.save_script_data(
        task_id=TASK_ID,
        video_script=SCRIPT_TEXT,
        video_terms=[],
        params=params,
        scene_plan=[s.model_dump() for s in scene_plan.scenes],
    )
    sm.state.update_task(
        TASK_ID,
        state=const.TASK_STATE_COMPLETE,
        progress=100,
        videos=[final_video_path],
    )

    # Validação do vídeo gerado
    print(f"\nValidando vídeo final: {final_video_path}")
    size_bytes = os.path.getsize(final_video_path)
    print(f"Tamanho do arquivo: {size_bytes / (1024 * 1024):.2f} MB ({size_bytes} bytes)")
    assert size_bytes > 0, "Vídeo final tem 0 bytes!"

    clip = VideoFileClip(final_video_path)
    final_w, final_h = clip.w, clip.h
    final_dur = clip.duration
    final_fps = clip.fps
    has_audio = clip.audio is not None
    audio_dur = clip.audio.duration if has_audio else 0.0
    clip.close()

    print(f"Resolução: {final_w}x{final_h} (Esperado 1080x1920)")
    print(f"Duração: {final_dur:.2f}s (Requisito: >= 60s, meta 75–90s)")
    print(f"FPS: {final_fps}")
    print(f"Faixa de áudio presente: {has_audio} (Duração: {audio_dur:.2f}s)")

    assert final_w == 1080 and final_h == 1920, f"Resolução incorreta: {final_w}x{final_h}"
    assert final_dur >= 60.0, f"Duração inferior ao mínimo de 60s: {final_dur:.2f}s"
    assert has_audio and audio_dur >= 60.0, "Áudio ausente ou incompleto no vídeo final"

    print("\n" + "=" * 70)
    print("STATUS: PASS")
    print(f"DURATION: {final_dur:.2f}s")
    print(f"FINAL_VIDEO: {final_video_path}")
    print("=" * 70)
    return final_video_path


if __name__ == "__main__":
    run_pipeline()
