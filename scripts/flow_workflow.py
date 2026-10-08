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
from datetime import datetime, timezone
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if ROOT_DIR not in sys.path:
    sys.path.insert(0, ROOT_DIR)

from loguru import logger  # noqa: E402
from app.services.task_artifacts import atomic_write_json  # noqa: E402
from scripts.flow_playwright import (  # noqa: E402
    FlowSceneResult,
    generate_flow_scene,
    validate_clip_file,
)

from app.config import config  # noqa: E402
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


DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT = 6


def select_default_flow_scenes(
    scenes: List[Any],
    target_count: int = DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT,
) -> List[int]:
    """
    Seleciona as cenas de maior impacto visual/narrativo distribuídas ao longo do Short.
    Prioriza:
    1. Cena 1 (Hook inicial indispensável).
    2. Fechamento/resolução (última cena).
    3. Cenas intermediárias uniformemente espaçadas para evitar blocos contíguos de stock.
    4. Cenas com maior duração/relevância visual.
    """
    total = len(scenes)
    if total <= target_count:
        return [s.scene_index for s in scenes]

    indices = [s.scene_index for s in scenes]
    chosen = {indices[0], indices[-1]}
    remaining_needed = target_count - len(chosen)

    if remaining_needed > 0:
        candidates = indices[1:-1]
        step = (len(candidates) - 1) / (remaining_needed - 1) if remaining_needed > 1 else len(candidates) / 2
        for i in range(remaining_needed):
            idx = int(round(i * step))
            idx = max(0, min(len(candidates) - 1, idx))
            chosen.add(candidates[idx])

        if len(chosen) < target_count:
            duration_sorted = sorted(
                [s for s in scenes if s.scene_index not in chosen],
                key=lambda s: getattr(s, "duration_hint", 0.0),
                reverse=True,
            )
            for s in duration_sorted:
                chosen.add(s.scene_index)
                if len(chosen) == target_count:
                    break

    return sorted(list(chosen))


def prepare_project(
    script_text: str,
    project_name: str,
    video_subject: str = "",
    target_scene_duration: float = 8.0,
    voice_name: str = "pt-BR-AntonioNeural-Male",
    base_dir: Optional[str] = None,
    flow_scenes: Optional[List[int]] = None,
    custom_prompts: Optional[Dict[int, str]] = None,
    niche: str = "",
    target_flow_scenes: int = DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT,
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

    if flow_scenes is not None:
        flow_indices = set(flow_scenes)
    else:
        flow_indices = set(select_default_flow_scenes(scene_plan.scenes, target_count=target_flow_scenes))
    custom_map = custom_prompts or {}

    scenes_data = []
    prompts_md_lines = [
        f"# Prompts Google Flow — Projeto: {safe_project_name}",
        f"**Assunto:** {video_subject or 'Geral'}",
        f"**Nicho:** {niche or 'Geral'}",
        f"**Total de Cenas:** {scene_plan.total_scenes}",
        f"**Cenas Flow Premium (a gerar):** {sorted(list(flow_indices))}",
        f"**Voz Recomendada:** {voice_name}",
        "",
        "---",
        "",
        "## Como Usar:",
        "1. Abra o **Google Flow / Veo / Nano Banana** no navegador.",
        "2. Gere clipes APENAS para as cenas marcadas com **[FLOW PREMIUM]** abaixo (formato vertical 9:16).",
        f"3. Baixe os vídeos e salve na pasta: `storage/manual_media/{safe_project_name}/clips/`.",
        "4. As demais cenas serão preenchidas automaticamente pela Video Factory com materiais de estoque.",
        "",
        "---",
        "",
    ]

    for scene in scene_plan.scenes:
        s_idx = scene.scene_index
        is_flow = s_idx in flow_indices
        clip_filename = f"flow_scene_{s_idx:02d}.mp4"

        if is_flow and s_idx in custom_map:
            prompt_en = custom_map[s_idx]
            prompt_pt = f"Cena {s_idx} personalizada para {video_subject}."
            visual_intent = "custom visual"
        else:
            prompt_info = build_flow_prompt(
                narration=scene.narration,
                subject=video_subject,
                visual_intent=scene.visual_intent or "cinematic stock",
            )
            prompt_en = prompt_info["prompt_en"]
            prompt_pt = prompt_info["prompt_pt"]
            visual_intent = prompt_info["visual_intent"]

        scene_dict = {
            "scene_index": s_idx,
            "narration": scene.narration,
            "duration_hint": scene.duration_hint,
            "expected_clip": clip_filename,
            "is_flow_premium": is_flow,
            "prompt_en": prompt_en,
            "prompt_pt": prompt_pt,
            "visual_intent": visual_intent,
            "search_terms": scene.search_terms,
        }
        scenes_data.append(scene_dict)

        if is_flow:
            prompts_md_lines.extend([
                f"### Cena {s_idx:02d} — [FLOW PREMIUM] (Estimativa: ~{scene.duration_hint:.1f}s)",
                f"- **Arquivo Esperado:** `{clip_filename}`",
                f"- **Narração (pt-BR):** \"{scene.narration}\"",
                f"- **Prompt para o Flow (copiar e colar):**",
                "```text",
                prompt_en,
                "```",
                "",
            ])
        else:
            prompts_md_lines.extend([
                f"### Cena {s_idx:02d} — [STOCK FILLER] (Estimativa: ~{scene.duration_hint:.1f}s)",
                f"- **Narração (pt-BR):** \"{scene.narration}\"",
                "- **Status:** Preenchimento automático com materiais de estoque da Video Factory.",
                "",
            ])

    manifest_data = {
        "project_name": safe_project_name,
        "video_subject": video_subject,
        "niche": niche,
        "script_text": script_text.strip(),
        "voice_name": voice_name,
        "target_scene_duration": target_scene_duration,
        "total_scenes": len(scenes_data),
        "flow_scenes": sorted(list(flow_indices)),
        "scenes": scenes_data,
    }

    manifest_path = os.path.join(project_dir, "manifest.json")
    atomic_write_json(manifest_path, manifest_data)

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
        "flow_scenes_count": len(flow_indices),
    }


def update_manifest_flow_checkpoint(
    manifest_path: str,
    project_url: Optional[str] = None,
    last_scene: Optional[int] = None,
    status: Optional[str] = None,
    completed_scenes: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """
    Persiste metadados operacionais de checkpoint no manifest.json do projeto.
    NÃO armazena cookies, tokens ASB, credenciais ou dados sensíveis.
    """
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    if project_url:
        manifest["flow_project_url"] = project_url

    flow_gen = manifest.get("flow_generation", {})
    if status is not None:
        flow_gen["status"] = status
    if project_url is not None:
        flow_gen["project_url"] = project_url
    elif "flow_project_url" in manifest:
        flow_gen["project_url"] = manifest["flow_project_url"]

    if completed_scenes is not None:
        flow_gen["completed_scenes"] = sorted(list(set(completed_scenes)))
    if last_scene is not None:
        flow_gen["last_scene"] = last_scene

    flow_gen["updated_at"] = datetime.now(timezone.utc).isoformat()

    manifest["flow_generation"] = flow_gen
    atomic_write_json(manifest_path, manifest)
    return flow_gen


def generate_pending_flow_scenes(
    manifest_path: str,
    max_scenes: Optional[int] = None,
    project_url: Optional[str] = None,
    failure_policy: str = "strict",
) -> Dict[str, Any]:
    """
    Processa sequencialmente (FLOW_BROWSER_CONCURRENCY = 1) todas as cenas marcadas
    com is_flow_premium == True pendentes de geração.

    Idempotência: Se expected_clip já existir e for válido, pula imediatamente com zero browser.
    Resume: Pula cenas já prontas e continua da primeira pendente.
    Checkpoint: Persiste status, project_url e completed_scenes após cada cena.
    Recovery: Em caso de falha pós-consumo, suspende a execução com FLOW_GENERATION_NEEDS_RECOVERY.
    """
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em {manifest_path}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    project_dir = os.path.dirname(os.path.abspath(manifest_path))
    clips_dir = os.path.join(project_dir, "clips")

    flow_scenes = [
        s for s in manifest.get("scenes", [])
        if s.get("is_flow_premium", True)
    ]
    flow_scenes.sort(key=lambda x: x.get("scene_index", 0))

    effective_project_url = project_url or manifest.get("flow_project_url")
    completed_scenes: List[int] = []
    scene_results: List[Dict[str, Any]] = []
    attempted_count = 0
    overall_status = "ALL_FLOW_SCENES_READY"

    for sc in flow_scenes:
        s_idx = sc["scene_index"]
        expected_clip = sc.get("expected_clip", f"flow_scene_{s_idx:02d}.mp4")
        clip_path = os.path.join(clips_dir, expected_clip)

        # 1. Verifica se já está concluído e válido no disco (idempotência sem abrir browser)
        if os.path.exists(clip_path):
            val = validate_clip_file(clip_path)
            if val.get("valid"):
                completed_scenes.append(s_idx)
                scene_results.append({
                    "scene_index": s_idx,
                    "status": "ALREADY_COMPLETE",
                    "output_file": clip_path,
                    "output_valid": True,
                    "duration": val.get("duration", 0.0),
                    "credits_consumed": 0,
                    "project_url": effective_project_url,
                    "error": None,
                })
                continue

        # 2. Respeita max_scenes
        if max_scenes is not None and attempted_count >= max_scenes:
            overall_status = "MAX_SCENES_REACHED"
            break

        # 3. Execução sequencial controlada (single-flight)
        attempted_count += 1
        res = generate_flow_scene(
            manifest_path=manifest_path,
            scene_index=s_idx,
            project_url=effective_project_url,
            failure_policy=failure_policy,
        )

        if res.project_url:
            effective_project_url = res.project_url

        scene_results.append(res.to_dict())

        # Checkpoint após cada cena
        if res.status in ("SUCCESS", "ALREADY_COMPLETE"):
            completed_scenes.append(s_idx)
            update_manifest_flow_checkpoint(
                manifest_path=manifest_path,
                project_url=effective_project_url,
                last_scene=s_idx,
                status="IN_PROGRESS" if len(completed_scenes) < len(flow_scenes) else "COMPLETE",
                completed_scenes=completed_scenes,
            )
        elif res.status == "FLOW_GENERATION_NEEDS_RECOVERY":
            overall_status = "FLOW_GENERATION_NEEDS_RECOVERY"
            update_manifest_flow_checkpoint(
                manifest_path=manifest_path,
                project_url=effective_project_url,
                last_scene=s_idx,
                status="FLOW_GENERATION_NEEDS_RECOVERY",
                completed_scenes=completed_scenes,
            )
            break
        elif res.status in ("FLOW_BROWSER_BUSY", "AWAITING_FLOW_EDGE_PROFILE_CLOSE"):
            overall_status = "FLOW_BROWSER_BUSY"
            update_manifest_flow_checkpoint(
                manifest_path=manifest_path,
                project_url=effective_project_url,
                last_scene=s_idx,
                status="FLOW_BROWSER_BUSY",
                completed_scenes=completed_scenes,
            )
            break
        else:
            overall_status = f"FAILED_SCENE_{s_idx}"
            update_manifest_flow_checkpoint(
                manifest_path=manifest_path,
                project_url=effective_project_url,
                last_scene=s_idx,
                status=f"FAILED_SCENE_{s_idx}",
                completed_scenes=completed_scenes,
            )
            if failure_policy == "strict":
                break

    if len(completed_scenes) == len(flow_scenes) and len(flow_scenes) > 0:
        overall_status = "COMPLETE"
        update_manifest_flow_checkpoint(
            manifest_path=manifest_path,
            project_url=effective_project_url,
            status="COMPLETE",
            completed_scenes=completed_scenes,
        )

    return {
        "status": overall_status,
        "manifest_path": manifest_path,
        "project_url": effective_project_url,
        "total_flow_scenes": len(flow_scenes),
        "completed_count": len(completed_scenes),
        "completed_scenes": completed_scenes,
        "pending_count": len(flow_scenes) - len(completed_scenes),
        "attempted_count": attempted_count,
        "results": scene_results,
    }


def get_project_status(project_dir: str) -> Dict[str, Any]:
    """
    Passo 3: Inspeciona o estado dos clipes baixados para o projeto.
    Distingue: READY_FLOW, READY_STOCK, PENDING_FLOW, INVALID_FLOW, FLOW_NEEDS_RECOVERY, FAILED_FLOW.
    Usa validate_clip_file() como única fonte de verdade para validade de mídia.
    """
    manifest_path = os.path.join(project_dir, "manifest.json")
    if not os.path.exists(manifest_path):
        raise FileNotFoundError(f"manifest.json não encontrado em {project_dir}")

    with open(manifest_path, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    clips_dir = os.path.join(project_dir, "clips")
    flow_gen = manifest.get("flow_generation", {})
    flow_gen_status = flow_gen.get("status")
    last_scene = flow_gen.get("last_scene")

    scenes_status = []
    ready_flow_count = 0
    ready_stock_count = 0
    invalid_flow_count = 0

    for sc in manifest.get("scenes", []):
        s_idx = sc["scene_index"]
        expected_clip = sc["expected_clip"]
        clip_path = os.path.join(clips_dir, expected_clip)
        exists = os.path.exists(clip_path)
        size_mb = (os.path.getsize(clip_path) / (1024 * 1024)) if exists else 0.0
        val = validate_clip_file(clip_path) if exists else {"valid": False}
        is_valid = bool(val.get("valid", False))
        is_flow = sc.get("is_flow_premium", True)

        if is_flow:
            if exists:
                if is_valid:
                    ready_flow_count += 1
                    status_tag = "READY_FLOW"
                else:
                    if flow_gen_status == "FLOW_GENERATION_NEEDS_RECOVERY" and (
                        last_scene == s_idx or not flow_gen.get("completed_scenes")
                    ):
                        status_tag = "FLOW_NEEDS_RECOVERY"
                    else:
                        status_tag = "INVALID_FLOW"
                        invalid_flow_count += 1
            else:
                if flow_gen_status == "FLOW_GENERATION_NEEDS_RECOVERY" and (
                    last_scene == s_idx or not flow_gen.get("completed_scenes")
                ):
                    status_tag = "FLOW_NEEDS_RECOVERY"
                elif flow_gen_status and str(flow_gen_status).startswith("FAILED"):
                    status_tag = "FAILED_FLOW"
                else:
                    status_tag = "PENDING_FLOW"
        else:
            if exists:
                if is_valid:
                    ready_stock_count += 1
                    status_tag = "READY_STOCK"
                else:
                    status_tag = "MISSING (STOCK_FALLBACK)"
            else:
                status_tag = "MISSING (STOCK_FALLBACK)"

        scenes_status.append({
            "scene_index": s_idx,
            "expected_clip": expected_clip,
            "status": status_tag,
            "size_mb": round(size_mb, 2),
            "narration": sc["narration"][:60] + "...",
            "is_flow_premium": is_flow,
            "is_valid": is_valid,
        })

    total = len(scenes_status)
    return {
        "project_name": manifest.get("project_name"),
        "project_dir": project_dir,
        "flow_project_url": manifest.get("flow_project_url"),
        "flow_generation": flow_gen,
        "total_scenes": total,
        "ready_flow_clips": ready_flow_count,
        "ready_stock_clips": ready_stock_count,
        "invalid_flow_clips": invalid_flow_count,
        "missing_clips": total - (ready_flow_count + ready_stock_count),
        "is_fully_flow": ready_flow_count == total and total > 0,
        "is_hybrid": 0 < ready_flow_count < total,
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
                    if os.path.getsize(fpath) > 0 and validate_clip_file(fpath).get("valid", False):
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
    stock_source: str = "coverr",
    flow_failure_policy: str = "strict",
) -> Dict[str, Any]:
    """
    Passo 4: Ingestão simplificada e montagem pela Video Factory.
    Se dry_run=True, monta o ScenePlan e as instruções sem renderizar vídeo físico.
    flow_failure_policy: 'strict' (falha se Flow ausente/inválido) ou 'fallback_stock' (resolve stock).
    Se manifest indicar FLOW_GENERATION_NEEDS_RECOVERY, fail-closed imediato sem fallback.
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

    flow_gen = manifest.get("flow_generation", {})
    flow_gen_status = flow_gen.get("status")

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
        is_flow = sc.get("is_flow_premium", True)
        flow_clip_path = os.path.join(clips_dir, expected_clip)

        if is_flow:
            flow_exists = os.path.exists(flow_clip_path)
            flow_valid = flow_exists and validate_clip_file(flow_clip_path).get("valid", False)

            if not flow_valid:
                # Se manifest indicar FLOW_GENERATION_NEEDS_RECOVERY, fail-closed imediato sem mascarar com stock
                if flow_gen_status == "FLOW_GENERATION_NEEDS_RECOVERY":
                    raise RuntimeError(
                        f"FLOW_GENERATION_NEEDS_RECOVERY: Cena {s_idx} [FLOW PREMIUM] requer recuperação explícita "
                        f"antes de renderizar. Fallback para stock não permitido neste estado."
                    )

                if not flow_exists:
                    if flow_failure_policy == "strict":
                        raise FileNotFoundError(
                            f"Cena {s_idx} [FLOW PREMIUM]: clipe obrigatório não encontrado ({expected_clip}). "
                            f"Cenas premium do Google Flow não podem ser substituídas por stock (policy=strict)."
                        )
                    elif flow_failure_policy == "fallback_stock":
                        logger.warning(
                            f"Cena {s_idx} [FLOW PREMIUM]: clipe ausente ({expected_clip}). "
                            f"Aplicando fallback para material de estoque (policy=fallback_stock)."
                        )
                    else:
                        raise ValueError(f"flow_failure_policy inválida: {flow_failure_policy}")
                else:
                    # Arquivo existe mas validate_clip_file retornou False!
                    if flow_failure_policy == "strict":
                        raise RuntimeError(
                            f"INVALID_FLOW_CLIP: Cena {s_idx} [FLOW PREMIUM] possui clipe corrompido ou inválido ({flow_clip_path}). "
                            f"Render bloqueado (policy=strict)."
                        )
                    elif flow_failure_policy == "fallback_stock":
                        logger.warning(
                            f"Cena {s_idx} [FLOW PREMIUM]: clipe corrompido ou inválido ({flow_clip_path}). "
                            f"Aplicando fallback para material de estoque (policy=fallback_stock)."
                        )
                    else:
                        raise ValueError(f"flow_failure_policy inválida: {flow_failure_policy}")

                # Resolução de material stock fallback
                filler = _find_stock_filler_clip(s_idx)
                if filler and os.path.exists(filler) and validate_clip_file(filler).get("valid", False):
                    mat_path = filler
                    provider = "stock_fallback"
                    source_type = "stock_fallback"
                else:
                    from app.services import material, scene_material

                    effective_stock = (
                        stock_source
                        or manifest.get("stock_source")
                        or config.app.get("video_source", "coverr")
                        or "coverr"
                    )
                    if not material.has_material_api_keys(effective_stock):
                        raise RuntimeError(
                            f"Cena {s_idx} [STOCK FALLBACK]: Nenhuma credencial configurada para o provider de stock '{effective_stock}'. "
                            f"Configure uma chave válida para buscar materiais de estoque contextuais."
                        )

                    single_scene_plan = ScenePlan(
                        total_scenes=1,
                        scenes=[
                            ScenePlanItem(
                                scene_index=s_idx,
                                narration=sc["narration"],
                                duration_hint=float(sc.get("duration_hint", 8.0)),
                                search_terms=sc.get("search_terms", []),
                                visual_intent=sc.get("visual_intent", "cinematic"),
                            )
                        ],
                    )
                    scene_params = params.model_copy(update={"video_source": effective_stock})
                    resolved_selections = scene_material.resolve_scene_materials(
                        task_id=effective_task_id,
                        scene_plan=single_scene_plan,
                        params=scene_params,
                        audio_duration=float(sc.get("duration_hint", 8.0)),
                        strict=True,
                    )
                    if not resolved_selections or not resolved_selections[0].material_path:
                        raise RuntimeError(f"Falha ao resolver material stock fallback para a cena {s_idx}")
                    mat_path = resolved_selections[0].material_path
                    provider = "stock_fallback"
                    source_type = "stock_fallback"
            else:
                mat_path = flow_clip_path
                provider = "google_flow"
                source_type = "flow"
        else:
            # Cenas STOCK FILLER:
            # 1. Tentar material local/cache existente (na pasta clips/ ou nos caches)
            if os.path.exists(flow_clip_path) and validate_clip_file(flow_clip_path).get("valid", False):
                mat_path = flow_clip_path
                provider = "local_clip"
                source_type = "stock"
            else:
                filler = _find_stock_filler_clip(s_idx)
                if filler and os.path.exists(filler) and validate_clip_file(filler).get("valid", False):
                    mat_path = filler
                    provider = "local_cache"
                    source_type = "stock"
                else:
                    # 2. Reutilizar o resolver nativo de materiais da Video Factory (scene_material)
                    from app.services import material, scene_material

                    effective_stock = (
                        stock_source
                        or manifest.get("stock_source")
                        or config.app.get("video_source", "coverr")
                        or "coverr"
                    )
                    if not material.has_material_api_keys(effective_stock):
                        raise RuntimeError(
                            f"Cena {s_idx} [STOCK FILLER]: Nenhuma credencial configurada para o provider de stock '{effective_stock}' "
                            f"({effective_stock}_api_keys está vazio em config.toml e {effective_stock.upper()}_API_KEY não definido). "
                            f"Configure uma chave válida para buscar e baixar materiais de estoque contextuais."
                        )

                    single_scene_plan = ScenePlan(
                        total_scenes=1,
                        scenes=[
                            ScenePlanItem(
                                scene_index=s_idx,
                                narration=sc["narration"],
                                duration_hint=float(sc.get("duration_hint", 8.0)),
                                search_terms=sc.get("search_terms", []),
                                visual_intent=sc.get("visual_intent", "cinematic"),
                            )
                        ],
                    )
                    scene_params = params.model_copy(update={"video_source": effective_stock})
                    resolved_selections = scene_material.resolve_scene_materials(
                        task_id=effective_task_id,
                        scene_plan=single_scene_plan,
                        params=scene_params,
                        audio_duration=float(sc.get("duration_hint", 8.0)),
                        strict=True,
                    )
                    if not resolved_selections or not resolved_selections[0].material_path:
                        raise RuntimeError(f"Falha ao resolver material de estoque para a cena {s_idx}")
                    mat_path = resolved_selections[0].material_path
                    provider = resolved_selections[0].provider
                    source_type = "stock"

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
        mat_map = {m.scene_index: m.visual_source_type for m in material_selections}
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
                    "source": mat_map.get(inst.scene_index, "flow" if "flow" in inst.material_path else "stock"),
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
    prepare_p.add_argument("--niche", default="", help="Nicho de conteúdo do perfil (ex: curiosidades_ciencia)")
    prepare_p.add_argument("--flow-scenes", default="", help="Índices das cenas Flow separadas por vírgula (ex: 1,4,5,7)")
    prepare_p.add_argument(
        "--flow-count",
        type=int,
        default=DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT,
        help=f"Quantidade padrão de cenas Flow Premium a selecionar (padrão: {DEFAULT_FLOW_PREMIUM_SCENES_PER_SHORT})",
    )
    prepare_p.add_argument("--target-duration", type=float, default=8.0, help="Duração alvo de cada cena")
    prepare_p.add_argument("--voice", default="pt-BR-AntonioNeural-Male", help="Voz TTS neural")

    # Comando 'status'
    status_p = subparsers.add_parser("status", help="Inspeciona clipes baixados para o projeto")
    status_p.add_argument("project_dir", help="Diretório do projeto (ex: storage/manual_media/meu_projeto)")

    # Comando 'generate'
    generate_p = subparsers.add_parser("generate", help="Gera clipes pendentes do Google Flow via Playwright provider")
    generate_p.add_argument("project_dir", help="Diretório do projeto (ex: storage/manual_media/meu_projeto)")
    generate_p.add_argument("--max-scenes", type=int, default=None, help="Limite máximo de cenas a processar nesta execução")
    generate_p.add_argument("--project-url", default=None, help="URL explícita do projeto Flow existente")
    generate_p.add_argument(
        "--failure-policy",
        choices=["strict", "fallback_stock"],
        default="strict",
        help="Política em caso de falha no Flow (strict | fallback_stock, padrão: strict)",
    )

    # Comando 'render'
    render_p = subparsers.add_parser("render", help="Renderiza a montagem do projeto na Video Factory")
    render_p.add_argument("project_dir", help="Diretório do projeto")
    render_p.add_argument("--dry-run", action="store_true", help="Valida pipeline e instruções sem renderizar")
    render_p.add_argument("--output-dir", help="Diretório de saída customizado")
    render_p.add_argument("--stock-source", default="coverr", help="Provedor de estoque para cenas filler (padrão: coverr)")
    render_p.add_argument(
        "--failure-policy",
        choices=["strict", "fallback_stock"],
        default="strict",
        help="Política para cenas Flow ausentes (strict | fallback_stock, padrão: strict)",
    )

    args = parser.parse_args()

    if args.command == "prepare":
        script_content = args.script
        if not script_content and args.script_file:
            with open(args.script_file, "r", encoding="utf-8") as f:
                script_content = f.read()

        if not script_content:
            print("Erro: Forneça --script ou --script-file com o texto do roteiro.")
            sys.exit(1)

        flow_sc_list = None
        if args.flow_scenes:
            flow_sc_list = [int(x.strip()) for x in args.flow_scenes.split(",") if x.strip().isdigit()]

        result = prepare_project(
            script_text=script_content,
            project_name=args.project,
            video_subject=args.subject,
            target_scene_duration=args.target_duration,
            voice_name=args.voice,
            flow_scenes=flow_sc_list,
            niche=args.niche,
            target_flow_scenes=args.flow_count,
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
        print(f"1. Gerar com:    python scripts/flow_workflow.py generate {result['project_dir']}")
        print(f"2. Verificar:    python scripts/flow_workflow.py status {result['project_dir']}")
        print(f"3. Renderizar:   python scripts/flow_workflow.py render {result['project_dir']}")

    elif args.command == "status":
        info = get_project_status(args.project_dir)
        print("\n" + "=" * 60)
        print(f"STATUS DO PROJETO FLOW: {info['project_name']}")
        print("=" * 60)
        print(f"Total de Cenas:     {info['total_scenes']}")
        print(f"Clipes Flow Prontos: {info['ready_flow_clips']}/{info['total_scenes']}")
        print(f"Clipes Pendentes:   {info['missing_clips']}")
        if info.get("flow_project_url"):
            print(f"Flow Project URL:   {info['flow_project_url']}")
        print("-" * 60)
        for s in info["scenes"]:
            print(f"Cena {s['scene_index']:02d}: {s['status']:<25} | {s['expected_clip']} ({s['size_mb']} MB)")
        print("=" * 60)

    elif args.command == "generate":
        manifest_path = os.path.join(args.project_dir, "manifest.json")
        res = generate_pending_flow_scenes(
            manifest_path=manifest_path,
            max_scenes=args.max_scenes,
            project_url=args.project_url,
            failure_policy=args.failure_policy,
        )
        print("\n" + "=" * 60)
        print("EXECUÇÃO DO GERADOR GOOGLE FLOW (PLAYWRIGHT)")
        print("=" * 60)
        print(f"Status Geral:       {res['status']}")
        print(f"Cenas Flow Totais:  {res['total_flow_scenes']}")
        print(f"Cenas Concluídas:   {res['completed_count']}")
        print(f"Cenas Pendentes:    {res['pending_count']}")
        print(f"Cenas Tentadas:     {res['attempted_count']}")
        if res.get("project_url"):
            print(f"Flow Project URL:   {res['project_url']}")
        print("-" * 60)
        for r in res.get("results", []):
            st = r.get("status")
            s_idx = r.get("scene_index")
            out_f = r.get("output_file") or "N/A"
            credits = r.get("credits_consumed", 0)
            print(f"Cena {s_idx:02d}: {st:<30} | {out_f} (créditos: {credits})")
        print("=" * 60)
        if res["status"] in ("COMPLETE", "ALL_FLOW_SCENES_READY"):
            sys.exit(0)
        else:
            sys.exit(1)

    elif args.command == "render":
        res = render_project(
            project_dir=args.project_dir,
            dry_run=args.dry_run,
            output_dir=args.output_dir,
            stock_source=args.stock_source,
            flow_failure_policy=args.failure_policy,
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
