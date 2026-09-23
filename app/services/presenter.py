"""
Presenter Service (Fase V14-C — Hybrid Character Overlay MVP).

Responsável pelo gerenciamento, dimensionamento, posicionamento e composição
do personagem / apresentador virtual transparente sobre o vídeo final.
Totalmente local, sem dependências externas pagas ou lip-sync neural.
"""

import os
from contextlib import ExitStack
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger
from moviepy import ImageClip, VideoFileClip

from app.models import const
from app.models.schema import VideoParams


ALLOWED_AVATAR_EXTENSIONS = {".png", ".webp", ".webm"}
ALLOWED_AVATAR_MODES = set(const.AVATAR_MODES)
ALLOWED_AVATAR_POSITIONS = set(const.AVATAR_POSITIONS)


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

    asset_path = getattr(params, "avatar_asset_path", "")
    if isinstance(params, dict):
        asset_path = params.get("avatar_asset_path", "")
    if not asset_path or not str(asset_path).strip():
        return False, "avatar_asset_path é obrigatório quando avatar_mode != 'none'"

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

    # Validação do arquivo de asset
    asset_path = getattr(params, "avatar_asset_path", "")
    if isinstance(params, dict):
        asset_path = params.get("avatar_asset_path", "")
    resolved_path = validate_asset_path(asset_path)

    # Carrega clip base
    base_clip, is_video = load_presenter_base_clip(resolved_path, clip_stack=clip_stack)

    # Layout: dimensões e coordenadas
    scale = getattr(params, "avatar_scale", 0.38)
    position = getattr(params, "avatar_position", const.DEFAULT_AVATAR_POSITION)
    opacity = getattr(params, "avatar_opacity", 1.0)
    if isinstance(params, dict):
        scale = params.get("avatar_scale", scale)
        position = params.get("avatar_position", position)
        opacity = params.get("avatar_opacity", opacity)

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
