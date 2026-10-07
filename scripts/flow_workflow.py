"""
scripts/flow_workflow.py
========================
Fase V1.2 — Otimização de Passos Manuais (Google Flow / Video Factory).

Objetivo:
Reduzir a fricção operacional na produção híbrida:
1. Preparação automatizada de prompts visuais otimizados para o Google Flow (9:16 portrait).
2. Divisão de cenas temporizada e alinhamento com a narração via scene_planner.
3. Organização e nomenclatura padronizada dos clipes (clips/flow_scene_01.mp4, etc.).
4. Ingestão e montagem simplificadas pela Video Factory (um comando CLI de render).
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from app.models import const  # noqa: E402
from app.models.schema import (  # noqa: E402
    SceneClipInstruction,
    SceneMaterialSelection,
    ScenePlan,
    ScenePlanItem,
    VideoAspect,
    VideoConcatMode,
    VideoFitMode,
    VideoParams,
)
from app.services import scene_assembly, scene_planner, task, video, voice  # noqa: E402
from app.services import state as sm  # noqa: E402
from app.utils import utils  # noqa: E402


DEFAULT_MANUAL_MEDIA_DIR = os.path.join(ROOT_DIR, "storage", "manual_media")
DEFAULT_CACHE_VIDEOS_DIR = os.path.join(ROOT_DIR, "storage", "cache_videos")
DEFAULT_LOCAL_VIDEOS_DIR = os.path.join(ROOT_DIR, "storage", "local_videos")


def build_flow_prompt(
    narration: str,
    subject: str = "",
    visual_intent: str = "cinematic",
) -> Dict[str, str]:
    """
    Gera prompts estruturados para o Google Flow / Veo / Nano Banana.
    Prioriza o idioma inglês com descritores cinemáticos e enquadramento 9:16 portrait.
    """
    cleaned_narration = utils.remove_pause_tags(narration or "").strip()
    subj_clean = (subject or "").strip()

    # Mapeamento semântico simplificado para estilos cinematográficos
    intent_descriptors = {
        "archival footage": "authentic 1960s archival film style, 35mm grainy film texture, vintage color grading, historical documentary look",
        "urban scene": "sleek urban cinematography, moody city atmosphere, realistic natural lighting, cinematic street composition",
        "nature landscape": "majestic atmospheric landscape, epic wide perspective, rich natural colors, cinematic golden hour lighting",
        "technology/space": "futuristic technological ambiance, deep volumetric lighting, razor-sharp focus, cinematic realism",
        "person portrait": "expressive cinematic close-up, dramatic side lighting, shallow depth of field, authentic emotional atmosphere",
        "cinematic stock": "dramatic cinematic lighting, photorealistic atmosphere, cinematic depth of field, 4k masterwork look",
    }

    style = intent_descriptors.get(visual_intent, intent_descriptors["cinematic stock"])

    # Extrai palavras-chave principais em minúsculas
    words = re.findall(r"\b[a-zA-ZÀ-ÿ]{4,}\b", cleaned_narration.lower())
    core_theme = " ".join(words[:5]) if words else "dramatic narrative moment"

    # Montagem do prompt em inglês para máxima fidelidade no Google Flow
    action_en = f"Cinematic scene depicting {subj_clean + ': ' if subj_clean else ''}{core_theme}"
    flow_prompt_en = (
        f"{action_en}. {style}. "
        "Slow cinematic camera movement, smooth tracking shot, 9:16 vertical portrait composition, "
        "hyperrealistic, photorealistic, highly detailed, no text, no captions, no watermark."
    )

    prompt_pt = (
        f"Cena cinematográfica ilustrando: {cleaned_narration[:120]}... "
        f"Estilo: {visual_intent}. Enquadramento vertical 9:16 para Shorts/Reels."
    )

    return {
        "prompt_en": flow_prompt_en,
        "prompt_pt": prompt_pt,
        "visual_intent": visual_intent,
    }


def prepare_project(
    script_text: str,
    project_name: str,
    video_subject: str = "",
    target_scene_duration: float = 8.0,
    voice_name: str = "pt-BR-AntonioNeural-Male",
    base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Passo 1 & 2: Divide o roteiro em cenas temporizadas e gera prompts para o Flow.
    Cria a estrutura de pastas e o manifesto estruturado.
    """
    if not script_text or not script_text.strip():
        raise ValueError("script_text não pode ser vazio")
    if not project_name or not project_name.strip():
        raise ValueError("project_name não pode ser vazio")

    # Sanitiza nome do projeto
    safe_project_name = re.sub(r"[^\w-]", "_", project_name.strip()).lower()
    base_storage = base_dir or DEFAULT_MANUAL_MEDIA_DIR
    project_dir = os.path.join(base_storage, safe_project_name)
    clips_dir = os.path.join(project_dir, "clips")
    os.makedirs(clips_dir, exist_ok=True)

    # 1. Planejamento determinístico de cenas
    scene_plan = scene_planner.plan_scenes(
        video_script=script_text,
        target_scene_duration=target_scene_duration,
        task_id=f"flow_prep_{safe_project_name}",
    )

    scenes_data = []
    prompts_md_lines = [
        f"# Prompts Google Flow — Projeto: {safe_project_name}",
        f"**Assunto:** {video_subject or 'Geral'}",
        f"**Total de Cenas:** {scene_plan.total_scenes}",
        f"**Voz Recomendada:** {voice_name}",
        "",
        "---",
        "",
        "## Como Usar:",
        "1. Abra o **Google Flow / Veo / Nano Banana** no navegador.",
        "2. Para cada cena abaixo, copie o **Prompt para o Flow** e gere o clipe em formato vertical (9:16).",
        f"3. Baixe o vídeo gerado e salve diretamente na pasta: `storage/manual_media/{safe_project_name}/clips/`",
        "4. Utilize o nome do arquivo indicado em **Arquivo Esperado** (ex: `flow_scene_01.mp4`).",
        "",
        "---",
        "",
    ]

    for scene in scene_plan.scenes:
        clip_filename = f"flow_scene_{scene.scene_index:02d}.mp4"
        prompt_info = build_flow_prompt(
            narration=scene.narration,
            subject=video_subject,
            visual_intent=scene.visual_intent or "cinematic stock",
        )

        scene_dict = {
            "scene_index": scene.scene_index,
            "narration": scene.narration,
            "duration_hint": scene.duration_hint,
            "expected_clip": clip_filename,
            "prompt_en": prompt_info["prompt_en"],
            "prompt_pt": prompt_info["prompt_pt"],
            "visual_intent": prompt_info["visual_intent"],
            "search_terms": scene.search_terms,
        }
        scenes_data.append(scene_dict)

        prompts_md_lines.extend([
            f"### Cena {scene.scene_index:02d} (Estimativa: ~{scene.duration_hint:.1f}s)",
            f"- **Arquivo Esperado:** `{clip_filename}`",
            f"- **Narração (pt-BR):** \"{scene.narration}\"",
            f"- **Prompt para o Flow (copiar e colar):**",
            "```text",
            prompt_info["prompt_en"],
            "```",
            "",
        ])

    manifest_data = {
        "project_name": safe_project_name,
        "video_subject": video_subject,
        "script_text": script_text.strip(),
        "voice_name": voice_name,
        "target_scene_duration": target_scene_duration,
        "total_scenes": len(scenes_data),
        "scenes": scenes_data,
    }

    manifest_path = os.path.join(project_dir, "manifest.json")
    with open(manifest_path, "w", encoding="utf-8") as f:
        json.dump(manifest_data, f, indent=2, ensure_ascii=False)

    prompts_md_path = os.path.join(project_dir, "prompts_for_flow.md")
    with open(prompts_md_path, "w", encoding="utf-8") as f:
        f.write("\n".join(prompts_md_lines))

    return {
        "project_name": safe_project_name,
        "project_dir": project_dir,
        "manifest_path": manifest_path,
        "prompts_md_path": prompts_md_path,
        "clips_dir": clips_dir,
        "total_scenes": len(scenes_data),
    }


def get_project_status(project_dir: str) -> Dict[str, Any]:
    """
    Passo 3: Inspeciona o estado dos clipes baixados para o projeto.
    """
    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em {project_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    clips_dir = os.path.join(project_dir, "clips")
    scenes_status = []
    ready_count = 0

    for sc in manifest.get("scenes", []):
        expected_clip = sc["expected_clip"]
        clip_path = os.path.join(clips_dir, expected_clip)
        exists = os.path.exists(clip_path) and os.path.getsize(clip_path) > 0
        if exists:
            ready_count += 1
            size_mb = os.path.getsize(clip_path) / (1024 * 1024)
            status_tag = "READY_FLOW"
        else:
            size_mb = 0.0
            status_tag = "MISSING (STOCK_FALLBACK)"

        scenes_status.append({
            "scene_index": sc["scene_index"],
            "expected_clip": expected_clip,
            "status": status_tag,
            "size_mb": round(size_mb, 2),
            "narration": sc["narration"][:60] + "...",
        })

    total = len(scenes_status)
    return {
        "project_name": manifest.get("project_name"),
        "project_dir": project_dir,
        "total_scenes": total,
        "ready_flow_clips": ready_count,
        "missing_clips": total - ready_count,
        "is_fully_flow": ready_count == total and total > 0,
        "is_hybrid": 0 < ready_count < total,
        "scenes": scenes_status,
    }


def _find_stock_filler_clip(scene_idx: int) -> Optional[str]:
    """Busca um clipe de preenchimento local existente para fallback híbrido."""
    candidate_dirs = [DEFAULT_CACHE_VIDEOS_DIR, DEFAULT_LOCAL_VIDEOS_DIR]
    all_videos = []
    for c_dir in candidate_dirs:
        if os.path.exists(c_dir):
            for fname in os.listdir(c_dir):
                if fname.endswith(".mp4") and not fname.startswith("flow_"):
                    fpath = os.path.join(c_dir, fname)
                    if os.path.getsize(fpath) > 0:
                        all_videos.append(fpath)

    if not all_videos:
        return None
    # Seleção determinística por índice de cena
    return all_videos[(scene_idx - 1) % len(all_videos)]


def render_project(
    project_dir: str,
    dry_run: bool = False,
    task_id: Optional[str] = None,
    output_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Passo 4: Ingestão simplificada e montagem pela Video Factory.
    Se dry_run=True, monta o ScenePlan e as instruções sem renderizar vídeo físico.
    """
    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em {project_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    project_name = manifest.get("project_name", "flow_project")
    effective_task_id = task_id or f"task_{project_name}"
    clips_dir = os.path.join(project_dir, "clips")
    out_dir = output_dir or os.path.join(project_dir, "final")
    os.makedirs(out_dir, exist_ok=True)

    params = VideoParams(
        video_subject=manifest.get("video_subject", project_name),
        video_script=manifest["script_text"],
        video_language="pt-BR",
        video_source="local",
        video_concat_mode=VideoConcatMode.sequential,
        video_fit_mode=VideoFitMode.cover,
        video_clip_duration=10,
        video_aspect=VideoAspect.portrait,
        voice_name=manifest.get("voice_name", "pt-BR-AntonioNeural-Male"),
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

    # 1. Mapeamento de materiais para cada cena
    material_selections: List[SceneMaterialSelection] = []
    scene_plan_items: List[ScenePlanItem] = []

    for sc in manifest["scenes"]:
        s_idx = sc["scene_index"]
        expected_clip = sc["expected_clip"]
        flow_clip_path = os.path.join(clips_dir, expected_clip)

        if os.path.exists(flow_clip_path) and os.path.getsize(flow_clip_path) > 0:
            mat_path = flow_clip_path
            provider = "google_flow"
            source_type = "flow"
        else:
            # Fallback híbrido de stock
            filler = _find_stock_filler_clip(s_idx)
            if filler:
                mat_path = filler
                provider = "pexels"
                source_type = "stock"
            else:
                raise FileNotFoundError(
                    f"Cena {s_idx}: clipe Flow não encontrado ({expected_clip}) "
                    f"e nenhum clipe de cache disponível para fallback."
                )

        scene_plan_items.append(
            ScenePlanItem(
                scene_index=s_idx,
                narration=sc["narration"],
                duration_hint=float(sc.get("duration_hint", 8.0)),
                search_terms=sc.get("search_terms", []),
                visual_intent=sc.get("visual_intent", "cinematic"),
            )
        )

        material_selections.append(
            SceneMaterialSelection(
                scene_index=s_idx,
                material_path=mat_path,
                duration=float(sc.get("duration_hint", 8.0)),
                provider=provider,
                asset_id=os.path.basename(mat_path),
                media_type="video",
                visual_source_type=source_type,
            )
        )

    scene_plan = ScenePlan(
        total_scenes=len(scene_plan_items),
        scenes=scene_plan_items,
    )

    estimated_total_duration = sum(s.duration_hint for s in scene_plan_items)

    # Se dry_run, monta as instruções de corte e encerra sem renderizar
    if dry_run:
        instructions = scene_assembly.assemble_scene_clips(
            scene_plan=scene_plan,
            material_selections=material_selections,
            audio_duration=estimated_total_duration,
            params=params,
            task_id=effective_task_id,
        )
        return {
            "status": "DRY_RUN_SUCCESS",
            "project_name": project_name,
            "total_scenes": len(instructions),
            "estimated_duration": round(estimated_total_duration, 2),
            "instructions": [
                {
                    "scene_index": inst.scene_index,
                    "duration_seconds": inst.duration_seconds,
                    "material_path": inst.material_path,
                    "source": "flow" if "flow" in inst.material_path else "stock",
                }
                for inst in instructions
            ],
        }

    # 2. Execução física real da pipeline
    task_dir = os.path.join(ROOT_DIR, "storage", "tasks", effective_task_id)
    os.makedirs(task_dir, exist_ok=True)
    sm.state.update_task(effective_task_id, state=const.TASK_STATE_PROCESSING, progress=10)

    # Geração de áudio e legendas
    audio_file, audio_duration, sub_maker = task.generate_audio(
        effective_task_id, params, manifest["script_text"]
    )
    if not audio_file or not os.path.exists(audio_file):
        raise RuntimeError(f"Falha ao sintetizar narração: {audio_file}")

    subtitle_path = task.generate_subtitle(
        effective_task_id, params, manifest["script_text"], sub_maker, audio_file
    )

    # Instruções de montagem sincronizadas com a duração exata do áudio
    instructions = scene_assembly.assemble_scene_clips(
        scene_plan=scene_plan,
        material_selections=material_selections,
        audio_duration=audio_duration,
        params=params,
        task_id=effective_task_id,
    )

    # Salvaguarda de clipes Flow: limitar a 10s se necessário
    for inst in instructions:
        if "flow_" in os.path.basename(inst.material_path):
            inst.duration_seconds = min(inst.duration_seconds, 10.0)

    ordered_video_paths = scene_assembly.get_ordered_video_paths(instructions)

    # Render intermediário concatenado
    combined_video_path = os.path.join(task_dir, "combined-1.mp4")
    render_timings: Dict[str, Any] = {}
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

    # Render final com legendas e mixagem BGM
    final_video_path = os.path.join(out_dir, f"{project_name}_final.mp4")
    video.generate_video(
        video_path=combined_video_path,
        audio_path=audio_file,
        subtitle_path=subtitle_path,
        output_file=final_video_path,
        params=params,
        render_timings=render_timings,
    )

    if not os.path.exists(final_video_path) or os.path.getsize(final_video_path) == 0:
        raise RuntimeError("Falha ao gerar o vídeo final na montagem do Flow")

    sm.state.update_task(
        effective_task_id,
        state=const.TASK_STATE_COMPLETE,
        progress=100,
        videos=[final_video_path],
    )

    return {
        "status": "RENDER_SUCCESS",
        "project_name": project_name,
        "final_video_path": final_video_path,
        "duration_seconds": round(audio_duration, 2),
        "total_scenes": len(instructions),
        "size_bytes": os.path.getsize(final_video_path),
    }


def main():
    parser = argparse.ArgumentParser(
        description="Flow Workflow Helper — Otimização de Produção Manual com Google Flow"
    )
    subparsers = parser.add_subparsers(dest="command", help="Comando a executar")

    # Comando 'prepare'
    prepare_p = subparsers.add_parser("prepare", help="Prepara cenas, prompts e estrutura de projeto")
    prepare_p.add_argument("--project", required=True, help="Identificador único do projeto")
    prepare_p.add_argument("--script", help="Texto integral do roteiro")
    prepare_p.add_argument("--script-file", help="Caminho para arquivo .txt contendo o roteiro")
    prepare_p.add_argument("--subject", default="", help="Assunto ou tema do vídeo")
    prepare_p.add_argument("--target-duration", type=float, default=8.0, help="Duração alvo de cada cena")
    prepare_p.add_argument("--voice", default="pt-BR-AntonioNeural-Male", help="Voz TTS neural")

    # Comando 'status'
    status_p = subparsers.add_parser("status", help="Inspeciona clipes baixados para o projeto")
    status_p.add_argument("project_dir", help="Diretório do projeto (ex: storage/manual_media/meu_projeto)")

    # Comando 'render'
    render_p = subparsers.add_parser("render", help="Renderiza a montagem do projeto na Video Factory")
    render_p.add_argument("project_dir", help="Diretório do projeto")
    render_p.add_argument("--dry-run", action="store_true", help="Valida pipeline e instruções sem renderizar")
    render_p.add_argument("--output-dir", help="Diretório de saída customizado")

    args = parser.parse_args()

    if args.command == "prepare":
        script_content = args.script
        if not script_content and args.script_file:
            with open(args.script_file, "r", encoding="utf-8") as f:
                script_content = f.read()

        if not script_content:
            print("Erro: Forneça --script ou --script-file com o texto do roteiro.")
            sys.exit(1)

        result = prepare_project(
            script_text=script_content,
            project_name=args.project,
            video_subject=args.subject,
            target_scene_duration=args.target_duration,
            voice_name=args.voice,
        )
        print("\n" + "=" * 60)
        print("PROJETO FLOW PREPARADO COM SUCESSO!")
        print("=" * 60)
        print(f"Diretório:       {result['project_dir']}")
        print(f"Manifesto:       {result['manifest_path']}")
        print(f"Prompts MD:      {result['prompts_md_path']}")
        print(f"Total de Cenas:  {result['total_scenes']}")
        print(f"Pasta de Clipes: {result['clips_dir']}")
        print("\nPróximos passos:")
        print(f"1. Abra '{result['prompts_md_path']}' e copie os prompts para o Google Flow.")
        print(f"2. Salve os clipes .mp4 baixados em '{result['clips_dir']}'.")
        print(f"3. Verifique com: python scripts/flow_workflow.py status {result['project_dir']}")
        print(f"4. Renderize com: python scripts/flow_workflow.py render {result['project_dir']}")

    elif args.command == "status":
        info = get_project_status(args.project_dir)
        print("\n" + "=" * 60)
        print(f"STATUS DO PROJETO FLOW: {info['project_name']}")
        print("=" * 60)
        print(f"Total de Cenas:     {info['total_scenes']}")
        print(f"Clipes Flow Prontos: {info['ready_flow_clips']}/{info['total_scenes']}")
        print(f"Clipes Pendentes:   {info['missing_clips']}")
        print("-" * 60)
        for s in info["scenes"]:
            print(f"Cena {s['scene_index']:02d}: {s['status']:<25} | {s['expected_clip']} ({s['size_mb']} MB)")
        print("=" * 60)

    elif args.command == "render":
        res = render_project(
            project_dir=args.project_dir,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
        )
        print("\n" + "=" * 60)
        if args.dry_run:
            print("MONTAGEM FLOW — VALIDAÇÃO DRY-RUN CONCLUÍDA")
            print("=" * 60)
            print(f"Total de Cenas Instruídas: {res['total_scenes']}")
            print(f"Duração Estimada Total:    {res['estimated_duration']}s")
            for inst in res["instructions"]:
                print(f"  Cena {inst['scene_index']}: {inst['duration_seconds']:.2f}s [{inst['source'].upper()}] -> {inst['material_path']}")
        else:
            print("MONTAGEM FLOW — VÍDEO FINAL RENDERIZADO COM SUCESSO!")
            print("=" * 60)
            print(f"Vídeo Final:     {res['final_video_path']}")
            print(f"Duração:         {res['duration_seconds']}s")
            print(f"Tamanho:         {res['size_bytes'] / (1024*1024):.2f} MB")
        print("=" * 60)

    else:
        parser.print_help()


if __name__ == "__main__":
    main()
