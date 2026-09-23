"""
Presenter Service (Fase V14-C / V14-C.1 — Cartoon Character Asset Pack + Preview).

Responsável pelo gerenciamento, dimensionamento, posicionamento e composição
do personagem / apresentador virtual transparente sobre o vídeo final.
Suporta tanto asset único (.png/.webp/.webm) quanto character packs completos
com múltiplas poses determinísticas (neutral, talking, surprised, thinking, cta, etc.).
Totalmente local, sem dependências externas pagas ou lip-sync neural.
"""

import json
import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
from loguru import logger
from moviepy import ColorClip, CompositeVideoClip, ImageClip, VideoFileClip

from app.models import const
from app.models.schema import VideoParams


ALLOWED_AVATAR_EXTENSIONS = {".png", ".webp", ".webm"}
ALLOWED_AVATAR_MODES = set(const.AVATAR_MODES)
ALLOWED_AVATAR_POSITIONS = set(const.AVATAR_POSITIONS)

# Catálogo de poses padrão do Character Asset Pack (Fase V14-C.1)
STANDARD_PRESENTER_POSES = [
    "neutral",
    "talking_1",
    "talking_2",
    "surprised",
    "serious",
    "thinking",
    "pointing_left",
    "pointing_right",
    "cta",
]

# Poses mínimas requeridas para que um character pack seja considerado válido
REQUIRED_CORE_POSES = [
    "neutral",
    "talking_1",
    "talking_2",
    "cta",
]


def get_character_pack_search_dirs() -> List[str]:
    """Retorna a lista de diretórios padrão de busca para character packs."""
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    return [
        os.path.join(base_dir, "resource", "presenter_assets"),
        os.path.join(base_dir, "storage", "presenter_assets"),
    ]


def validate_presenter_config(params: Any) -> Tuple[bool, str]:
    """Valida se a configuração de avatar/presenter é válida e suportada."""
    mode = getattr(params, "avatar_mode", const.DEFAULT_AVATAR_MODE)
    if isinstance(params, dict):
        mode = params.get("avatar_mode", const.DEFAULT_AVATAR_MODE)
    mode = str(mode or const.DEFAULT_AVATAR_MODE).lower().strip()

    if mode in (const.AVATAR_MODE_NONE, "", None):
        return True, "Presenter desativado (mode=none)"

    if mode not in ALLOWED_AVATAR_MODES:
        return False, f"Modo de avatar inválido: '{mode}'. Opções válidas: {sorted(list(ALLOWED_AVATAR_MODES))}"

    if mode == const.AVATAR_MODE_FULL:
        return False, "Modo 'full' de presenter não suportado no MVP; utilize 'hybrid' ou 'corner'"

    char_id = getattr(params, "avatar_character_id", "")
    asset_path = getattr(params, "avatar_asset_path", "")
    if isinstance(params, dict):
        char_id = params.get("avatar_character_id", "")
        asset_path = params.get("avatar_asset_path", "")

    has_char_id = bool(char_id and str(char_id).strip())
    has_asset_path = bool(asset_path and str(asset_path).strip())

    if not has_char_id and not has_asset_path:
        return False, "avatar_character_id ou avatar_asset_path é obrigatório quando avatar_mode != 'none'"

    pos = getattr(params, "avatar_position", const.DEFAULT_AVATAR_POSITION)
    if isinstance(params, dict):
        pos = params.get("avatar_position", const.DEFAULT_AVATAR_POSITION)
    pos = str(pos or const.DEFAULT_AVATAR_POSITION).lower().strip()
    if pos not in ALLOWED_AVATAR_POSITIONS:
        return False, f"Posição do avatar inválida: '{pos}'. Opções: {sorted(list(ALLOWED_AVATAR_POSITIONS))}"

    return True, "Configuração de presenter válida"


def validate_asset_path(asset_path: str) -> str:
    """Valida o caminho do asset contra traversal, existência e extensões permitidas."""
    if not asset_path or not str(asset_path).strip():
        raise ValueError("avatar_asset_path não pode ser vazio quando presenter estiver ativado")

    clean_path = str(asset_path).strip()
    parts = Path(clean_path).parts
    if ".." in parts:
        raise ValueError(f"Path traversal detectado no caminho do avatar: '{clean_path}'")

    if not os.path.isabs(clean_path):
        base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        clean_path = os.path.normpath(os.path.join(base_dir, clean_path))

    resolved = os.path.realpath(clean_path)
    if not os.path.isfile(resolved):
        raise FileNotFoundError(f"Arquivo de asset do avatar não encontrado: '{clean_path}'")

    ext = Path(resolved).suffix.lower()
    if ext not in ALLOWED_AVATAR_EXTENSIONS:
        raise ValueError(
            f"Extensão de asset não suportada: '{ext}'. Extensões permitidas: {sorted(list(ALLOWED_AVATAR_EXTENSIONS))}"
        )

    return resolved


def resolve_character_pack(
    character_id: str,
    custom_root: Optional[str] = None,
) -> Dict[str, Any]:
    """Resolve e valida o Character Asset Pack completo a partir do character_id.

    Verifica a existência de poses obrigatórias e carrega metadados do config.json.
    """
    clean_id = str(character_id or "").strip()
    if not clean_id:
        raise ValueError("character_id não pode ser vazio")

    if ".." in Path(clean_id).parts:
        raise ValueError(f"Path traversal detectado no character_id: '{clean_id}'")

    # Localiza o diretório do pacote
    pack_dir: Optional[str] = None
    if custom_root:
        candidate = (
            custom_root
            if os.path.basename(custom_root) == clean_id
            else os.path.join(custom_root, clean_id)
        )
        if os.path.isdir(candidate):
            pack_dir = candidate

    if not pack_dir:
        for search_root in get_character_pack_search_dirs():
            candidate = os.path.join(search_root, clean_id)
            if os.path.isdir(candidate):
                pack_dir = candidate
                break

    if not pack_dir:
        raise FileNotFoundError(
            f"Character pack '{clean_id}' não encontrado em nenhum dos diretórios padrão."
        )

    resolved_pack_dir = os.path.realpath(pack_dir)

    # Lê config.json se presente
    config_file = os.path.join(resolved_pack_dir, "config.json")
    pack_config: Dict[str, Any] = {}
    if os.path.isfile(config_file):
        try:
            with open(config_file, "r", encoding="utf-8") as f:
                pack_config = json.load(f)
        except Exception as exc:
            logger.warning(f"[PRESENTER] Falha ao ler config.json de {clean_id}: {exc}")

    # Mapeia poses disponíveis
    poses_config = pack_config.get("poses", {})
    resolved_poses: Dict[str, str] = {}

    for pose_name in STANDARD_PRESENTER_POSES:
        filename = poses_config.get(pose_name)
        if filename:
            file_path = os.path.join(resolved_pack_dir, filename)
            if os.path.isfile(file_path):
                resolved_poses[pose_name] = file_path
                continue

        # Procura convenção direta <pose_name>.png ou <pose_name>.webp
        for ext in (".png", ".webp"):
            candidate_file = os.path.join(resolved_pack_dir, f"{pose_name}{ext}")
            if os.path.isfile(candidate_file):
                resolved_poses[pose_name] = candidate_file
                break

    # Validação de integridade do pack: poses obrigatórias
    missing_core = [p for p in REQUIRED_CORE_POSES if p not in resolved_poses]
    if missing_core:
        raise ValueError(
            f"Character pack '{clean_id}' incompleto. Poses obrigatórias ausentes: {missing_core}"
        )

    return {
        "character_id": clean_id,
        "name": pack_config.get("name", clean_id),
        "style": pack_config.get("style", "cartoon"),
        "root_dir": resolved_pack_dir,
        "config": pack_config,
        "poses": resolved_poses,
        "default_scale": float(pack_config.get("default_scale", 0.38)),
        "default_position": pack_config.get("default_position", const.DEFAULT_AVATAR_POSITION),
        "default_opacity": float(pack_config.get("default_opacity", 1.0)),
    }


def select_presenter_pose(
    segment_type: str,
    segment_index: int = 0,
    script_text: str = "",
    available_poses: Optional[Dict[str, str]] = None,
) -> str:
    """Seleciona deterministicamente a pose ideal do presenter com base no contexto narrativo.

    Regras determinísticas:
    - HOOK: Alterna talking_1 / talking_2; usa surprised se houver palavras de impacto.
    - CTA: Prioriza cta, pointing_right ou pointing_left.
    - RETORNO / EXPLICAÇÃO: Prioriza thinking ou serious.
    - CORNER: Alterna ciclicamente neutral / talking_1 / talking_2.
    - Fallback: neutral ou talking_1.
    """
    st = str(segment_type or "").lower().strip()
    text_lower = str(script_text or "").lower()

    def _pick(choice: str, fallbacks: List[str]) -> str:
        if available_poses is None:
            return choice
        if choice in available_poses:
            return choice
        for fb in fallbacks:
            if fb in available_poses:
                return fb
        return list(available_poses.keys())[0] if available_poses else choice

    if st in ("hook", "intro") or (segment_index == 0 and st == "hybrid"):
        impact_words = [
            "mistério",
            "misterio",
            "segredo",
            "inacreditável",
            "inacreditavel",
            "chocante",
            "sombrio",
            "bizarro",
            "enigma",
        ]
        if any(w in text_lower for w in impact_words):
            return _pick("surprised", ["talking_1", "talking_2", "neutral"])
        preferred = "talking_1" if (segment_index % 2 == 0) else "talking_2"
        return _pick(preferred, ["talking_1", "talking_2", "neutral"])

    if st in ("cta", "outro"):
        return _pick("cta", ["pointing_right", "pointing_left", "talking_1", "neutral"])

    if st in ("return", "body", "explanation", "middle"):
        preferred = "thinking" if (segment_index % 2 == 1) else "serious"
        return _pick(preferred, ["serious", "thinking", "talking_1", "neutral"])

    if st == "corner":
        cycle = ["neutral", "talking_1", "talking_2"]
        preferred = cycle[segment_index % len(cycle)]
        return _pick(preferred, ["neutral", "talking_1"])

    return _pick("neutral", ["talking_1", "talking_2"])


def build_hybrid_presenter_segments(total_duration: float) -> List[Tuple[float, float]]:
    """Calcula determinística e proporcionalmente os segmentos de exibição do presenter no modo Hybrid.

    Estrutura:
    - HOOK: Início do vídeo (0.0 -> 3.5s para vídeos >= 25s)
    - RETURN: Meio do vídeo (~35% -> ~45%)
    - CTA: Final do vídeo (últimos ~4.5s)
    - Intermediários: Presenter oculto para destacar o B-roll
    """
    if total_duration <= 0:
        return []
    total_duration = round(float(total_duration), 2)
    if total_duration < 6.0:
        return [(0.0, round(min(total_duration, 2.5), 2))]

    if total_duration >= 25.0:
        s1 = (0.0, 3.5)
        ret_start = round(total_duration * 0.35, 2)
        ret_end = round(total_duration * 0.45, 2)
        s2 = (ret_start, ret_end)
        cta_start = round(max(ret_end + 0.5, total_duration - 4.5), 2)
        cta_end = total_duration
        s3 = (cta_start, cta_end)
        return [s1, s2, s3]
    else:
        hook_end = round(min(2.5, total_duration * 0.15), 2)
        ret_start = round(total_duration * 0.40, 2)
        ret_end = round(total_duration * 0.55, 2)
        cta_start = round(max(ret_end + 0.2, total_duration * 0.85), 2)
        cta_end = total_duration

        segments = []
        if hook_end > 0:
            segments.append((0.0, hook_end))
        if ret_start > hook_end and ret_end > ret_start:
            segments.append((ret_start, ret_end))
        if cta_start > (segments[-1][1] if segments else 0) and cta_end > cta_start:
            segments.append((cta_start, cta_end))
        return segments


def calculate_presenter_layout(
    canvas_size: Tuple[int, int],
    original_size: Tuple[int, int],
    scale: float = 0.38,
    position: str = const.DEFAULT_AVATAR_POSITION,
    mode: str = const.AVATAR_MODE_HYBRID,
) -> Tuple[Tuple[int, int], Tuple[int, int]]:
    """Calcula dimensões e posicionamento seguro do overlay do apresentador."""
    canvas_w, canvas_h = canvas_size
    orig_w, orig_h = original_size

    effective_scale = max(0.1, min(1.0, float(scale)))
    if mode == const.AVATAR_MODE_CORNER:
        effective_scale = effective_scale * 0.75

    target_w = max(10, int(canvas_w * effective_scale))
    aspect_ratio = float(orig_h) / float(orig_w) if orig_w > 0 else 1.0
    target_h = max(10, int(target_w * aspect_ratio))

    margin_x = max(16, int(canvas_w * 0.04))
    margin_y = max(32, int(canvas_h * 0.06))

    pos_clean = str(position or const.DEFAULT_AVATAR_POSITION).lower().strip()
    if pos_clean == const.AVATAR_POSITION_BOTTOM_LEFT:
        x = margin_x
        y = canvas_h - target_h - margin_y
    elif pos_clean == const.AVATAR_POSITION_BOTTOM_CENTER:
        x = int((canvas_w - target_w) / 2)
        y = canvas_h - target_h - margin_y
    else:  # bottom_right
        x = canvas_w - target_w - margin_x
        y = canvas_h - target_h - margin_y

    return (target_w, target_h), (x, y)


def load_presenter_base_clip(
    asset_path: str,
    clip_stack: Optional[ExitStack] = None,
) -> Tuple[Any, bool]:
    """Carrega o asset gráfico (PNG, WebP ou WebM) como Clip com alpha preservado."""
    ext = Path(asset_path).suffix.lower()

    if ext in (".png", ".webp"):
        clip = ImageClip(asset_path)
        if clip_stack:
            clip_stack.callback(clip.close)
        return clip, False

    if ext == ".webm":
        try:
            clip = VideoFileClip(asset_path, has_mask=True, audio=False)
            if clip.mask is None:
                logger.warning(
                    f"[PRESENTER] WebM '{asset_path}' não possui máscara de transparência (alpha) detectada."
                )
            if clip_stack:
                clip_stack.callback(clip.close)
            return clip, True
        except Exception as exc:
            logger.warning(
                f"[PRESENTER] Falha ao carregar WebM transparente: {exc}. Utilizando fallback seguro."
            )
            raise ValueError(f"Não foi possível decodificar canal alfa do WebM: {exc}")

    raise ValueError(f"Extensão de asset não suportada: {ext}")


def build_presenter_clips(
    params: Any,
    total_duration: float,
    canvas_size: Tuple[int, int],
    clip_stack: Optional[ExitStack] = None,
) -> List[Any]:
    """Constrói a lista de MoviePy clips posicionados e temporizados do Presenter Overlay.

    Suporta:
    1. Character Pack via avatar_character_id (V14-C.1) com seleção dinâmica de poses.
    2. Asset estático direto via avatar_asset_path (V14-C retrocompatível).

    Retorna lista vazia se avatar_mode for 'none'.
    Lança exceção fail-closed se o presenter foi solicitado mas estiver inválido.
    """
    mode = getattr(params, "avatar_mode", const.DEFAULT_AVATAR_MODE)
    if isinstance(params, dict):
        mode = params.get("avatar_mode", const.DEFAULT_AVATAR_MODE)
    mode = str(mode or const.DEFAULT_AVATAR_MODE).lower().strip()

    if mode in (const.AVATAR_MODE_NONE, "", None):
        return []

    # Validação da configuração
    valid, reason = validate_presenter_config(params)
    if not valid:
        raise ValueError(f"Configuração do presenter inválida: {reason}")

    char_id = getattr(params, "avatar_character_id", "")
    asset_path = getattr(params, "avatar_asset_path", "")
    if isinstance(params, dict):
        char_id = params.get("avatar_character_id", "")
        asset_path = params.get("avatar_asset_path", "")

    scale = getattr(params, "avatar_scale", 0.38)
    position = getattr(params, "avatar_position", const.DEFAULT_AVATAR_POSITION)
    opacity = getattr(params, "avatar_opacity", 1.0)
    if isinstance(params, dict):
        scale = params.get("avatar_scale", scale)
        position = params.get("avatar_position", position)
        opacity = params.get("avatar_opacity", opacity)

    # Caso A: Character Pack Completo (Fase V14-C.1)
    if char_id and str(char_id).strip():
        pack = resolve_character_pack(char_id)
        scale = scale or pack.get("default_scale", 0.38)
        position = position or pack.get("default_position", const.DEFAULT_AVATAR_POSITION)
        opacity = opacity if opacity is not None else pack.get("default_opacity", 1.0)
        available_poses = pack["poses"]

        clips = []
        if mode == const.AVATAR_MODE_CORNER:
            pose_name = select_presenter_pose("corner", 0, available_poses=available_poses)
            pose_file = available_poses[pose_name]
            base_clip, is_video = load_presenter_base_clip(pose_file, clip_stack=clip_stack)
            orig_w, orig_h = base_clip.size
            target_size, pos = calculate_presenter_layout(
                canvas_size, (orig_w, orig_h), scale, position, mode
            )
            resized = base_clip.resized(target_size)
            if float(opacity) < 1.0:
                resized = resized.with_opacity(float(opacity))
            c = resized.with_position(pos).with_start(0.0).with_duration(total_duration).with_end(total_duration)
            if clip_stack:
                clip_stack.callback(c.close)
            clips.append(c)

        elif mode == const.AVATAR_MODE_HYBRID:
            segments = build_hybrid_presenter_segments(total_duration)
            seg_types = ["hook", "return", "cta"]
            for idx, (st_t, en_t) in enumerate(segments):
                dur = max(0.01, round(en_t - st_t, 2))
                st_type = seg_types[idx] if idx < len(seg_types) else "middle"
                script_hint = getattr(params, "video_subject", "") if isinstance(params, VideoParams) else ""
                pose_name = select_presenter_pose(st_type, idx, script_hint, available_poses)
                pose_file = available_poses[pose_name]

                base_clip, is_video = load_presenter_base_clip(pose_file, clip_stack=clip_stack)
                orig_w, orig_h = base_clip.size
                target_size, pos = calculate_presenter_layout(
                    canvas_size, (orig_w, orig_h), scale, position, mode
                )
                resized = base_clip.resized(target_size)
                if float(opacity) < 1.0:
                    resized = resized.with_opacity(float(opacity))

                if is_video:
                    vid_dur = getattr(resized, "duration", dur)
                    sub = resized.subclipped(0, min(dur, vid_dur))
                    c = sub.with_position(pos).with_start(st_t).with_duration(dur).with_end(en_t)
                else:
                    c = resized.with_position(pos).with_start(st_t).with_duration(dur).with_end(en_t)

                if clip_stack:
                    clip_stack.callback(c.close)
                clips.append(c)

        return clips

    # Caso B: Asset único direto (V14-C retrocompatível)
    resolved_path = validate_asset_path(asset_path)
    base_clip, is_video = load_presenter_base_clip(resolved_path, clip_stack=clip_stack)
    orig_w, orig_h = base_clip.size
    target_size, pos = calculate_presenter_layout(
        canvas_size=canvas_size,
        original_size=(orig_w, orig_h),
        scale=scale,
        position=position,
        mode=mode,
    )

    resized_clip = base_clip.resized(target_size)
    try:
        op_val = float(opacity)
        if op_val < 1.0:
            resized_clip = resized_clip.with_opacity(max(0.0, min(1.0, op_val)))
    except (ValueError, TypeError):
        pass

    clips = []
    if mode == const.AVATAR_MODE_CORNER:
        c = (
            resized_clip.with_position(pos)
            .with_start(0.0)
            .with_duration(total_duration)
            .with_end(total_duration)
        )
        if clip_stack:
            clip_stack.callback(c.close)
        clips.append(c)

    elif mode == const.AVATAR_MODE_HYBRID:
        segments = build_hybrid_presenter_segments(total_duration)
        for start_t, end_t in segments:
            dur = max(0.01, round(end_t - start_t, 2))
            if is_video:
                vid_dur = getattr(resized_clip, "duration", dur)
                sub = resized_clip.subclipped(0, min(dur, vid_dur))
                c = sub.with_position(pos).with_start(start_t).with_duration(dur).with_end(end_t)
            else:
                c = (
                    resized_clip.with_position(pos)
                    .with_start(start_t)
                    .with_duration(dur)
                    .with_end(end_t)
                )
            if clip_stack:
                clip_stack.callback(c.close)
            clips.append(c)

    return clips


def generate_presenter_preview_frame(
    character_id: str,
    pose: str = "neutral",
    canvas_size: Tuple[int, int] = (1080, 1920),
    custom_root: Optional[str] = None,
    scale: Optional[float] = None,
    position: Optional[str] = None,
    bg_color: Tuple[int, int, int] = (25, 25, 35),
) -> np.ndarray:
    """Gera um frame RGB sintético renderizado para validação estática do presenter."""
    pack = resolve_character_pack(character_id, custom_root=custom_root)
    available_poses = pack["poses"]
    if pose not in available_poses:
        pose = select_presenter_pose("neutral", available_poses=available_poses)
    pose_file = available_poses[pose]

    eff_scale = scale or pack.get("default_scale", 0.38)
    eff_pos = position or pack.get("default_position", const.DEFAULT_AVATAR_POSITION)

    with ExitStack() as stack:
        bg_clip = stack.enter_context(
            ColorClip(size=canvas_size, color=bg_color, duration=1.0)
        )
        char_clip, _ = load_presenter_base_clip(pose_file, clip_stack=stack)
        orig_w, orig_h = char_clip.size
        target_size, pos_xy = calculate_presenter_layout(
            canvas_size, (orig_w, orig_h), eff_scale, eff_pos, mode=const.AVATAR_MODE_HYBRID
        )
        resized = char_clip.resized(target_size).with_position(pos_xy)
        composite = stack.enter_context(CompositeVideoClip([bg_clip, resized]))
        frame = composite.get_frame(0.0)
        return frame


def render_presenter_preview(
    character_id: str,
    output_path: str,
    pose: Optional[str] = None,
    canvas_size: Tuple[int, int] = (1080, 1920),
    duration: float = 3.0,
    bg_color: Tuple[int, int, int] = (25, 25, 35),
    custom_root: Optional[str] = None,
) -> str:
    """Renderiza um vídeo ou imagem de preview local para inspeção manual do operador."""
    pack = resolve_character_pack(character_id, custom_root=custom_root)
    selected_pose = pose or pack.get("default_pose", "neutral")
    frame = generate_presenter_preview_frame(
        character_id=character_id,
        pose=selected_pose,
        canvas_size=canvas_size,
        custom_root=custom_root,
        bg_color=bg_color,
    )

    out_p = Path(output_path)
    out_p.parent.mkdir(parents=True, exist_ok=True)

    if out_p.suffix.lower() in (".png", ".jpg", ".jpeg"):
        from PIL import Image
        img = Image.fromarray(frame)
        img.save(out_p)
        return str(out_p)

    # Se vídeo (.mp4):
    from moviepy import ImageClip
    clip = ImageClip(frame).with_duration(duration)
    clip.write_videofile(
        str(out_p),
        fps=24,
        codec="libx264",
        audio=False,
        logger=None,
    )
    clip.close()
    return str(out_p)
