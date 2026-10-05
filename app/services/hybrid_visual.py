"""
Hybrid Visual Generation Foundation & Contextual Image-to-Video (Fases V16.6 e V16.6.2).

Fornece uma arquitetura provider-agnostic para síntese e seleção visual de cenas:
1. stock (Pexels, Pixabay, biblioteca local de clipes)
2. generated_image (Nano Banana, SDXL, Flux)
3. generated_video (Wan 2.2, LTX-Video, FramePack via ComfyUI ou remoto)
4. image_motion (Keyframe gerado contextualizado + motion simples/Ken Burns local)

Princípio Fundamental:
- Não gerar 100% do vídeo por IA.
- Usar geração IA somente quando melhorar de verdade a aderência visual (score de stock fraco).
- Se o provider falhar, timeout, indisponível ou capability não suportada:
  o pipeline continua usando stock de forma resiliente e transparente.
- Nunca deixar a geração do vídeo inteiro falhar por indisponibilidade de IA.
- Hardware real do PC Forte (AMD Radeon RX 580 2048SP ~4 GB VRAM sem CUDA):
  classificado formalmente como NOT_RECOMMENDED_ON_CURRENT_HARDWARE para vídeo generativo local.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import asdict, dataclass, field
from enum import Enum
import json
import os
import sys
import time
from typing import Any, Callable, Dict, List, Optional, Union
import urllib.error
import urllib.parse
import urllib.request

from loguru import logger


# =============================================================================
# Benchmark & Hardware Constants (Fases V16.6.1 e V16.6.2)
# =============================================================================

STANDARD_BENCHMARK_PROMPT = (
    "large tornado rotating across rural field under dark storm clouds, "
    "cinematic realistic footage, vertical 9:16"
)

BENCHMARK_MODELS = [
    "wan_2_2",
    "ltx_video",
    "framepack",
]

# Registro canônico da postura de hardware da fábrica de vídeos
LOCAL_GENERATIVE_VIDEO_GPU_STATUS = "NOT_RECOMMENDED_ON_CURRENT_HARDWARE"


# =============================================================================
# Hardware Capability Report (Fase V16.6.1)
# =============================================================================

class HardwareClassification(str, Enum):
    LOCAL_GPU_READY = "LOCAL_GPU_READY"
    LIMITED = "LIMITED"
    NOT_RECOMMENDED = "NOT_RECOMMENDED"


@dataclass
class HardwareCapabilityReport:
    gpu_vendor: str = "Unknown"
    gpu_name: str = "Unknown"
    vram_mb: Optional[float] = None
    cuda_available: bool = False
    rocm_available: bool = False
    directml_available: bool = False
    classification: HardwareClassification = HardwareClassification.NOT_RECOMMENDED
    recommended_local_models: List[str] = field(default_factory=list)
    not_recommended_models: List[str] = field(default_factory=list)
    reason: str = ""
    suggested_alternatives: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["classification"] = self.classification.value
        return res


def probe_hardware_capability(
    mock_specs: Optional[Dict[str, Any]] = None,
) -> HardwareCapabilityReport:
    """
    Detecta de forma best-effort as capacidades de hardware do host para geração de vídeo por IA.
    Não instala dependências, não baixa modelos e não falha se torch ou CUDA estiverem ausentes.
    """
    if mock_specs is not None:
        gpu_vendor = str(mock_specs.get("gpu_vendor", "Unknown"))
        gpu_name = str(mock_specs.get("gpu_name", "Unknown"))
        vram_mb = mock_specs.get("vram_mb")
        cuda_available = bool(mock_specs.get("cuda_available", False))
        rocm_available = bool(mock_specs.get("rocm_available", False))
        directml_available = bool(mock_specs.get("directml_available", False))
    else:
        gpu_vendor = "Unknown"
        gpu_name = "Unknown"
        vram_mb = None
        cuda_available = False
        rocm_available = False
        directml_available = False

        # 1. Tenta via PyTorch
        try:
            import torch
            cuda_available = bool(torch.cuda.is_available())
            if cuda_available:
                gpu_vendor = "NVIDIA"
                gpu_name = torch.cuda.get_device_name(0)
                vram_mb = round(torch.cuda.get_device_properties(0).total_memory / (1024 * 1024), 2)
            if hasattr(torch.version, "hip") and torch.version.hip:
                rocm_available = True
                gpu_vendor = "AMD"
        except Exception:
            pass

        # 2. Se não detectado e estiver em Windows, tenta Win32_VideoController
        if gpu_name == "Unknown" and sys.platform == "win32":
            try:
                import subprocess
                cmd = [
                    "powershell",
                    "-NoProfile",
                    "-Command",
                    "Get-CimInstance Win32_VideoController | Select-Object Name, AdapterRAM | ConvertTo-Json",
                ]
                res = subprocess.run(cmd, capture_output=True, text=True, timeout=5)
                if res.returncode == 0 and res.stdout.strip():
                    data = json.loads(res.stdout)
                    item = data[0] if isinstance(data, list) else data
                    gpu_name = item.get("Name", "Unknown")
                    if "AMD" in gpu_name or "Radeon" in gpu_name:
                        gpu_vendor = "AMD"
                    elif "NVIDIA" in gpu_name or "GeForce" in gpu_name:
                        gpu_vendor = "NVIDIA"
                    elif "Intel" in gpu_name:
                        gpu_vendor = "Intel"
                    adapter_ram = item.get("AdapterRAM")
                    if adapter_ram:
                        vram_mb = round(float(adapter_ram) / (1024 * 1024), 2)
            except Exception:
                pass

    # Classificação baseada nas capacidades
    is_rx580 = "rx 580" in gpu_name.lower() or "2048sp" in gpu_name.lower() or "polaris" in gpu_name.lower()
    is_amd_no_rocm = gpu_vendor == "AMD" and not rocm_available
    has_low_vram = vram_mb is not None and vram_mb < 6144.0

    if (is_rx580 or is_amd_no_rocm or has_low_vram or not cuda_available) and not (cuda_available and vram_mb and vram_mb >= 8192.0):
        classification = HardwareClassification.NOT_RECOMMENDED
        rec: List[str] = []
        not_rec = ["wan_2_2", "ltx_video", "framepack"]
        vram_str = f"{vram_mb:.0f}" if vram_mb else "~4096"
        reason = (
            f"{gpu_vendor} {gpu_name} (~{vram_str} MB VRAM, CUDA={cuda_available}). "
            "Hardware insuficiente para modelos de vídeo generativo locais (Wan 2.2 / LTX / FramePack). "
            f"Status: {LOCAL_GENERATIVE_VIDEO_GPU_STATUS}."
        )
        alternatives = [
            "remote_video_provider",
            "contextual_keyframe_image_generation (Nano Banana)",
            "still_motion_effects (Ken Burns / Pan / Zoom)",
            "stock_library_fallback (Pexels / Pixabay)",
        ]
    elif cuda_available and vram_mb and vram_mb >= 16384.0:
        classification = HardwareClassification.LOCAL_GPU_READY
        rec = ["wan_2_2", "ltx_video", "framepack"]
        not_rec = []
        reason = f"NVIDIA CUDA GPU com {vram_mb:.0f} MB VRAM. Compatível com modelos locais de vídeo."
        alternatives = ["local_comfyui_headless"]
    elif cuda_available and vram_mb and vram_mb >= 8192.0:
        classification = HardwareClassification.LIMITED
        rec = ["ltx_video_quantized", "framepack_light"]
        not_rec = ["wan_2_2_full"]
        reason = f"VRAM moderada ({vram_mb:.0f} MB). Suporta modelos quantizados com offloading de memória."
        alternatives = ["quantized_models", "remote_provider"]
    else:
        classification = HardwareClassification.NOT_RECOMMENDED
        rec = []
        not_rec = ["wan_2_2", "ltx_video", "framepack"]
        reason = "Ambiente de execução não possui GPU com VRAM mínima (>=8GB) ou CUDA."
        alternatives = ["stock_library_fallback", "contextual_keyframe_image_generation"]

    return HardwareCapabilityReport(
        gpu_vendor=gpu_vendor,
        gpu_name=gpu_name,
        vram_mb=vram_mb,
        cuda_available=cuda_available,
        rocm_available=rocm_available,
        directml_available=directml_available,
        classification=classification,
        recommended_local_models=rec,
        not_recommended_models=not_rec,
        reason=reason,
        suggested_alternatives=alternatives,
    )


# =============================================================================
# Capabilities & Data Contracts
# =============================================================================

class VisualCapability(str, Enum):
    TEXT_TO_IMAGE = "text_to_image"
    IMAGE_TO_VIDEO = "image_to_video"
    TEXT_TO_VIDEO = "text_to_video"
    STOCK = "stock"


class HybridDecision(str, Enum):
    STOCK_HIGH_CONFIDENCE = "STOCK_HIGH_CONFIDENCE"
    GENERATED_IMAGE_PREFERRED = "GENERATED_IMAGE_PREFERRED"
    GENERATED_VIDEO_PREFERRED = "GENERATED_VIDEO_PREFERRED"
    FALLBACK_STOCK = "FALLBACK_STOCK"


class SceneImportance(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HERO = "HERO"


HERO_KEYWORDS = {
    "tornado", "tempestade", "explosão", "destruição", "mistério", "revelação",
    "chocante", "surpreendente", "monstro", "catástrofe", "ápice", "incrível",
    "segredo", "perigo", "confronto", "bizarro", "morte", "inacreditável", "abdução",
    "explosion", "destruction", "mystery", "shocking", "catastrophe", "climax",
    "spectacular", "danger", "secret", "reveal", "alien", "hero", "epic",
}

TRANSITION_KEYWORDS = {
    "enquanto isso", "por exemplo", "além disso", "segundo fontes", "assim",
    "portanto", "entretanto", "no entanto", "dessa forma", "em seguida",
    "meanwhile", "for example", "furthermore", "in addition", "therefore",
    "transition", "bridge",
}


def classify_scene_importance(
    scene_index: int,
    total_scenes: int = 1,
    narration: str = "",
    visual_intent: Optional[Any] = None,
    duration_seconds: float = 4.0,
    source_strategy: Optional[str] = None,
) -> SceneImportance:
    """
    Classifica a importância da cena de forma leve e determinística (sem LLM pago).
    Categorias:
    - HERO: Abertura (hook / cena 1), clímax narrativo, momentos com forte carga dramática / visual.
    - LOW: Transições, pontes sonoras ou cenas muito curtas (< 2.5s) que devem economizar IA.
    - NORMAL: Cenas narrativas regulares do corpo do vídeo.
    """
    if source_strategy:
        strat_clean = str(source_strategy).lower().strip()
        if strat_clean in ("hero", "hook", "climax", "key", "highlight"):
            return SceneImportance.HERO
        if strat_clean in ("low", "bridge", "transition", "filler", "ambient"):
            return SceneImportance.LOW
        if strat_clean in ("normal", "body", "narrative"):
            return SceneImportance.NORMAL

    # 1. Posição no vídeo: Primeira cena é o gancho principal (HERO)
    if scene_index == 1:
        return SceneImportance.HERO

    # 2. Texto / Intent para análise de keywords
    text_corpus = narration.lower() if narration else ""
    if visual_intent:
        if isinstance(visual_intent, dict):
            subj = str(visual_intent.get("primary_subject", "")).lower()
            act = str(visual_intent.get("action", "")).lower()
            env = str(visual_intent.get("environment", "")).lower()
        else:
            subj = str(getattr(visual_intent, "primary_subject", "")).lower()
            act = str(getattr(visual_intent, "action", "")).lower()
            env = str(getattr(visual_intent, "environment", "")).lower()
        text_corpus += f" {subj} {act} {env}"

    # 3. Keywords de alto impacto promovem a cena para HERO
    for kw in HERO_KEYWORDS:
        if kw in text_corpus:
            return SceneImportance.HERO

    # 4. Transições ou duração muito curta rebaixam para LOW
    if duration_seconds < 2.5:
        return SceneImportance.LOW

    for kw in TRANSITION_KEYWORDS:
        if kw in text_corpus:
            return SceneImportance.LOW

    return SceneImportance.NORMAL


@dataclass
class ProviderCapabilities:
    supports_text_to_image: bool = False
    supports_image_to_video: bool = False
    supports_text_to_video: bool = False
    supports_stock: bool = False
    max_duration_seconds: float = 10.0
    supported_aspect_ratios: List[str] = field(
        default_factory=lambda: ["9:16", "16:9", "1:1"]
    )
    requires_input_image: bool = False

    def has_capability(self, capability: Union[str, VisualCapability]) -> bool:
        cap_str = capability.value if isinstance(capability, VisualCapability) else str(capability)
        if cap_str == VisualCapability.TEXT_TO_IMAGE.value:
            return self.supports_text_to_image
        if cap_str == VisualCapability.IMAGE_TO_VIDEO.value:
            return self.supports_image_to_video
        if cap_str == VisualCapability.TEXT_TO_VIDEO.value:
            return self.supports_text_to_video
        if cap_str == VisualCapability.STOCK.value:
            return self.supports_stock
        return False


@dataclass
class GenerationRequest:
    scene_id: Union[int, str]
    prompt: str
    negative_prompt: str = ""
    aspect_ratio: str = "9:16"
    duration_seconds: float = 4.0
    seed: Optional[int] = None
    input_image_path: Optional[str] = None
    output_path: Optional[str] = None
    target_capability: VisualCapability = VisualCapability.TEXT_TO_VIDEO
    model: str = ""
    extra_params: Dict[str, Any] = field(default_factory=dict)


@dataclass
class GenerationMetrics:
    generation_time_seconds: float = 0.0
    queue_time_seconds: float = 0.0
    frames_generated: int = 0
    fps: float = 0.0
    vram_peak_mb: Optional[float] = None
    ram_peak_mb: Optional[float] = None
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class GenerationResult:
    scene_id: Union[int, str]
    success: bool
    provider: str
    model: str = ""
    output_path: Optional[str] = None
    media_type: str = "video"  # "video", "image", "stock"
    metrics: GenerationMetrics = field(default_factory=GenerationMetrics)
    error: Optional[str] = None
    fallback_reason: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        res = asdict(self)
        res["metrics"] = self.metrics.to_dict()
        return res


@dataclass
class VideoVisualSummary:
    total_scenes: int = 0
    stock_scenes: int = 0
    generated_image_scenes: int = 0
    generated_video_scenes: int = 0
    fallback_scenes: int = 0
    average_stock_score: float = 0.0
    generation_attempts: int = 0
    generation_successes: int = 0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def compute_video_visual_summary(
    selections: List[Any],
) -> VideoVisualSummary:
    """
    Computa o resumo estatístico e de governança visual para o vídeo completo (V16.7).
    """
    total = len(selections)
    if total == 0:
        return VideoVisualSummary()

    stock_count = 0
    gen_img_count = 0
    gen_vid_count = 0
    fallback_count = 0
    attempts = 0
    successes = 0
    total_score = 0.0

    for s in selections:
        score = None
        if hasattr(s, "stock_score") and s.stock_score is not None:
            score = float(s.stock_score)
        elif hasattr(s, "stock_match_score") and s.stock_match_score is not None:
            score = float(s.stock_match_score)
        elif hasattr(s, "match_score") and s.match_score is not None:
            score = float(s.match_score)
        elif isinstance(s, dict):
            score = s.get("stock_score") or s.get("stock_match_score") or s.get("match_score")
        if score is not None:
            total_score += float(score)

        source_type = "stock"
        if hasattr(s, "final_visual_source") and s.final_visual_source:
            source_type = s.final_visual_source
        elif hasattr(s, "visual_source_type") and s.visual_source_type:
            source_type = s.visual_source_type
        elif isinstance(s, dict):
            source_type = s.get("final_visual_source") or s.get("visual_source_type") or "stock"

        if source_type in ("generated_image", "image_motion"):
            gen_img_count += 1
        elif source_type == "generated_video":
            gen_vid_count += 1
        else:
            stock_count += 1

        fallback_used = False
        if hasattr(s, "fallback_used"):
            fallback_used = bool(s.fallback_used)
        elif isinstance(s, dict):
            fallback_used = bool(s.get("fallback_used"))
        if fallback_used:
            fallback_count += 1

        gen_status = getattr(s, "generation_status", None) if not isinstance(s, dict) else s.get("generation_status")
        gen_attempted = getattr(s, "generated_attempted", None) if not isinstance(s, dict) else s.get("generated_attempted")

        if gen_attempted or (gen_status and gen_status in ("success", "fallback")):
            attempts += 1
            if gen_status == "success":
                successes += 1

    avg_score = round(total_score / total, 2) if total > 0 else 0.0
    return VideoVisualSummary(
        total_scenes=total,
        stock_scenes=stock_count,
        generated_image_scenes=gen_img_count,
        generated_video_scenes=gen_vid_count,
        fallback_scenes=fallback_count,
        average_stock_score=avg_score,
        generation_attempts=attempts,
        generation_successes=successes,
    )


# =============================================================================
# Image Prompt Synthesis & Quality Gate (Fase V16.6.2)
# =============================================================================

@dataclass
class ImagePromptPayload:
    prompt: str
    negative_prompt: str
    aspect_ratio: str
    style: str
    avoid_terms: List[str] = field(default_factory=list)


def build_image_prompt_from_visual_intent(
    intent: Union[Any, dict, None],
    narration: str = "",
    aspect_ratio: str = "9:16",
) -> ImagePromptPayload:
    """
    Sintetiza um prompt de imagem contextualizado a partir do SceneVisualIntent (V16.5 / V16.6.2).
    Combina subject, action, environment e style realism, evitando termos proibidos e marcas d'água.
    """
    subject = ""
    action = ""
    environment = ""
    style = "Photorealistic, dramatic natural lighting, documentary realism"
    avoid_list: List[str] = []

    if intent is not None:
        if isinstance(intent, dict):
            subject = str(intent.get("primary_subject", "")).strip()
            action = str(intent.get("action", "")).strip()
            environment = str(intent.get("environment", "")).strip()
            style_in = str(intent.get("visual_style", "")).strip()
            if style_in and style_in.lower() not in ("none", "default"):
                style = f"{style}, {style_in}"
            avoid_list = list(intent.get("avoid", []))
        else:
            subject = str(getattr(intent, "primary_subject", "")).strip()
            action = str(getattr(intent, "action", "")).strip()
            environment = str(getattr(intent, "environment", "")).strip()
            style_in = str(getattr(intent, "visual_style", "")).strip()
            if style_in and style_in.lower() not in ("none", "default"):
                style = f"{style}, {style_in}"
            avoid_list = list(getattr(intent, "avoid", []))

    if not subject and narration:
        subject = narration.split(".")[0].strip()[:60]

    parts = []
    if subject:
        parts.append(subject)
    if action:
        parts.append(action)
    if environment and environment.lower() not in (subject.lower(), action.lower()):
        parts.append(f"in {environment}")

    if aspect_ratio == "9:16":
        parts.append("vertical composition, 9:16 aspect ratio")
    elif aspect_ratio == "16:9":
        parts.append("cinematic widescreen composition, 16:9 aspect ratio")
    elif aspect_ratio == "1:1":
        parts.append("square composition, 1:1 aspect ratio")

    parts.append(style)
    parts.append("clean shot, no text, no watermark, high detail")

    final_prompt = ", ".join(parts)
    negative_prompt = (
        "ugly, deformed, blurry, cartoon, 3d render, illustration, low quality, "
        "watermark, text, signature, low-resolution, oversaturated, disfigured, "
        "artifacts, cropped"
    )
    if avoid_list:
        negative_prompt += f", {', '.join(avoid_list)}"

    return ImagePromptPayload(
        prompt=final_prompt,
        negative_prompt=negative_prompt,
        aspect_ratio=aspect_ratio,
        style=style,
        avoid_terms=avoid_list,
    )


@dataclass
class KeyframeQualityResult:
    is_valid: bool
    reason: str
    file_size_bytes: int = 0
    width: int = 0
    height: int = 0
    details: Dict[str, Any] = field(default_factory=dict)


def evaluate_keyframe_quality(
    image_path: Optional[str],
    expected_aspect_ratio: str = "9:16",
    min_dimension: int = 512,
) -> KeyframeQualityResult:
    """
    Image Quality Gate simples e leve para keyframes gerados:
    - Arquivo existe e não está vazio.
    - Formato de imagem válido.
    - Dimensões mínimas respeitadas.
    - Orientação compatível com o aspect ratio esperado.
    """
    if not image_path or not os.path.exists(image_path):
        return KeyframeQualityResult(
            is_valid=False,
            reason="FILE_NOT_FOUND",
            details={"path": str(image_path)},
        )

    file_size = os.path.getsize(image_path)
    if file_size <= 0:
        return KeyframeQualityResult(
            is_valid=False,
            reason="FILE_EMPTY",
            file_size_bytes=0,
            details={"path": image_path},
        )

    try:
        from PIL import Image
        with Image.open(image_path) as img:
            w, h = img.size
            fmt = img.format or "UNKNOWN"

            if w < min_dimension or h < min_dimension:
                return KeyframeQualityResult(
                    is_valid=False,
                    reason="RESOLUTION_TOO_LOW",
                    file_size_bytes=file_size,
                    width=w,
                    height=h,
                    details={"min_dimension": min_dimension},
                )

            if expected_aspect_ratio == "9:16" and h < w:
                return KeyframeQualityResult(
                    is_valid=False,
                    reason="ORIENTATION_MISMATCH_EXPECTED_PORTRAIT",
                    file_size_bytes=file_size,
                    width=w,
                    height=h,
                    details={"expected": "portrait", "actual": f"{w}x{h}"},
                )
            elif expected_aspect_ratio == "16:9" and w < h:
                return KeyframeQualityResult(
                    is_valid=False,
                    reason="ORIENTATION_MISMATCH_EXPECTED_LANDSCAPE",
                    file_size_bytes=file_size,
                    width=w,
                    height=h,
                    details={"expected": "landscape", "actual": f"{w}x{h}"},
                )

            return KeyframeQualityResult(
                is_valid=True,
                reason="QUALITY_GATE_PASS",
                file_size_bytes=file_size,
                width=w,
                height=h,
                details={"format": fmt, "dimensions": f"{w}x{h}"},
            )
    except Exception as exc:
        return KeyframeQualityResult(
            is_valid=False,
            reason="IMAGE_DECODE_ERROR",
            file_size_bytes=file_size,
            details={"error": str(exc)},
        )


# =============================================================================
# Motion from Still (Ken Burns / Pan / Zoom Foundation)
# =============================================================================

class StillMotionMode(str, Enum):
    ZOOM_IN = "zoom_in"
    ZOOM_OUT = "zoom_out"
    PAN_LEFT = "pan_left"
    PAN_RIGHT = "pan_right"
    PAN_UP = "pan_up"
    PAN_DOWN = "pan_down"
    KEN_BURNS = "ken_burns"
    STATIC = "static"


@dataclass
class StillMotionParams:
    mode: StillMotionMode = StillMotionMode.ZOOM_IN
    duration_seconds: float = 4.0
    scale_factor: float = 1.08
    fps: int = 24
    output_width: int = 1080
    output_height: int = 1920


def generate_still_motion_instructions(
    image_path: str,
    duration_seconds: float = 4.0,
    aspect_ratio: str = "9:16",
    mode: Union[str, StillMotionMode] = StillMotionMode.ZOOM_IN,
    scale_factor: float = 1.08,
    fps: int = 24,
) -> Dict[str, Any]:
    """
    Gera parâmetros estruturados e filtros ffmpeg/moviepy para aplicar movimento a imagem estática.
    Sem executar render pesado de vídeo nos testes.
    """
    mode_val = mode.value if isinstance(mode, StillMotionMode) else str(mode)
    w, h = (1080, 1920) if aspect_ratio == "9:16" else ((1920, 1080) if aspect_ratio == "16:9" else (1080, 1080))
    total_frames = int(duration_seconds * fps)

    if mode_val == StillMotionMode.ZOOM_IN.value:
        ffmpeg_filter = f"zoompan=z='min(zoom+0.0015,{scale_factor})':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
    elif mode_val == StillMotionMode.ZOOM_OUT.value:
        ffmpeg_filter = f"zoompan=z='if(lte(zoom,1.0),1.0,{scale_factor}-0.0015*on)':d={total_frames}:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':s={w}x{h}:fps={fps}"
    elif mode_val in (StillMotionMode.PAN_LEFT.value, StillMotionMode.PAN_RIGHT.value):
        ffmpeg_filter = f"zoompan=z={scale_factor}:x='if(lte(on,1),(iw-iw/zoom)/2,x+1)':y='ih/2-(ih/zoom/2)':d={total_frames}:s={w}x{h}:fps={fps}"
    else:
        ffmpeg_filter = f"zoompan=z=1.0:d={total_frames}:s={w}x{h}:fps={fps}"

    return {
        "image_path": image_path,
        "duration_seconds": duration_seconds,
        "mode": mode_val,
        "aspect_ratio": aspect_ratio,
        "scale_factor": scale_factor,
        "fps": fps,
        "total_frames": total_frames,
        "resolution": f"{w}x{h}",
        "ffmpeg_filter": ffmpeg_filter,
    }


def select_still_motion_mode(
    scene_index: int,
    visual_intent: Optional[Any] = None,
    narration: str = "",
) -> StillMotionMode:
    """
    Seleciona determinística e cinematicamente o modo de still motion para keyframes (V16.7).
    Garante variação entre cenas e alinhamento com a semântica da ação.
    """
    text_corpus = (narration or "").lower()
    if visual_intent:
        if isinstance(visual_intent, dict):
            act = str(visual_intent.get("action", "")).lower()
            subj = str(visual_intent.get("primary_subject", "")).lower()
            env = str(visual_intent.get("environment", "")).lower()
        else:
            act = str(getattr(visual_intent, "action", "")).lower()
            subj = str(getattr(visual_intent, "primary_subject", "")).lower()
            env = str(getattr(visual_intent, "environment", "")).lower()
        text_corpus += f" {act} {subj} {env}"

    if any(
        k in text_corpus
        for k in (
            "aproxim", "zoom in", "close", "revel", "detalh", "foco", "focus",
            "touching", "desce", "descendo", "rotating", "funil", "tornado",
            "ground", "solo", "impact",
        )
    ):
        return StillMotionMode.ZOOM_IN
    if any(k in text_corpus for k in ("afast", "zoom out", "panorâm", "amplo", "wide", "paisag", "aerial", "sky", "céu")):
        return StillMotionMode.ZOOM_OUT
    if any(k in text_corpus for k in ("caminh", "pass", "andando", "movend", "pan right", "direita", "right", "estrada", "road")):
        return StillMotionMode.PAN_RIGHT
    if any(k in text_corpus for k in ("esquerda", "left", "olhando", "pan left")):
        return StillMotionMode.PAN_LEFT
    if any(k in text_corpus for k in ("parado", "estático", "static", "imóvel", "congel", "still")):
        return StillMotionMode.STATIC

    modes = [
        StillMotionMode.ZOOM_IN,
        StillMotionMode.PAN_RIGHT,
        StillMotionMode.ZOOM_OUT,
        StillMotionMode.PAN_LEFT,
        StillMotionMode.STATIC,
    ]
    return modes[(max(1, scene_index) - 1) % len(modes)]


# =============================================================================
# Provider Interface (ABC)
# =============================================================================

class VisualGenerationProvider(ABC):
    """Interface abstrata provider-agnostic para geradores visuais."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Identificador único do provider."""
        ...

    @property
    @abstractmethod
    def capabilities(self) -> ProviderCapabilities:
        """Capacidades técnicas suportadas pelo provider."""
        ...

    @abstractmethod
    def is_available(self) -> bool:
        """Health check ou verificação de disponibilidade operacional."""
        ...

    @abstractmethod
    def generate(self, request: GenerationRequest) -> GenerationResult:
        """Executa a geração do ativo visual."""
        ...


# =============================================================================
# Stock Visual Provider (Default baseline)
# =============================================================================

class StockVisualProvider(VisualGenerationProvider):
    """
    Provider representativo da biblioteca de stock footage (Pexels, Pixabay, etc.).
    Sempre disponível e serve como destino seguro do fallback.
    """

    @property
    def name(self) -> str:
        return "stock"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_stock=True,
            max_duration_seconds=60.0,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return True

    def generate(self, request: GenerationRequest) -> GenerationResult:
        return GenerationResult(
            scene_id=request.scene_id,
            success=True,
            provider=self.name,
            model="stock_library",
            output_path=request.output_path,
            media_type="stock",
            metadata={"note": "resolved_via_stock_library"},
        )


# =============================================================================
# Nano Banana Adapter (Configurable Keyframe Image Generator)
# =============================================================================

class NanoBananaImageAdapter(VisualGenerationProvider):
    """
    Adapter para o gerador de imagem Nano Banana (Fases V16.6 / V16.6.2 / V16.7.1).

    Contrato Operacional:
    - Provider opcional de imagem para keyframes e ilustrações conceituais de cena.
    - Em ambiente DEV: implementado em modo configurável sem chamadas pagas nos testes.
    - Suporta modo mock determinístico que gera imagens válidas para o Quality Gate.
    - Se a chave de API não estiver configurada, is_available() retorna False e
      o HybridVisualDirector realiza fallback seguro para stock.
    """

    def __init__(
        self,
        api_key: Optional[str] = None,
        endpoint: str = "https://api.nanobanana.ai/v1",
        timeout_seconds: float = 30.0,
        mock_mode: bool = False,
    ):
        self.api_key = api_key or os.getenv("NANO_BANANA_API_KEY", "")
        self.endpoint = endpoint
        self.timeout_seconds = timeout_seconds
        self.mock_mode = mock_mode

    @property
    def name(self) -> str:
        return "nano_banana"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_text_to_image=True,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return bool(self.mock_mode or (self.api_key and self.api_key.strip()))

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.is_available():
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model="nano_banana_image_v1",
                fallback_reason="NANO_BANANA_NOT_CONFIGURED",
                error="Nano Banana API key not configured",
            )

        if not self.capabilities.has_capability(request.target_capability):
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model="nano_banana_image_v1",
                fallback_reason="CAPABILITY_UNSUPPORTED",
                error=f"Capability '{request.target_capability}' not supported by Nano Banana",
            )

        start_time = time.time()

        # Modo Mock: Cria um arquivo de imagem real e leve para validação pelo Quality Gate
        if self.mock_mode:
            gen_time = round(time.time() - start_time, 3)
            out_file = request.output_path or f"storage/mock_nano_banana_scene_{request.scene_id}.png"
            os.makedirs(os.path.dirname(os.path.abspath(out_file)), exist_ok=True)

            w = 1080 if request.aspect_ratio == "9:16" else (1920 if request.aspect_ratio == "16:9" else 1080)
            h = 1920 if request.aspect_ratio == "9:16" else (1080 if request.aspect_ratio == "16:9" else 1080)

            try:
                from PIL import Image
                img = Image.new("RGB", (w, h), color=(30, 35, 45))
                img.save(out_file, "PNG")
            except Exception:
                with open(out_file, "wb") as f:
                    f.write(b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR" + b"\x00" * 20)

            file_size = os.path.getsize(out_file) if os.path.exists(out_file) else 1024

            return GenerationResult(
                scene_id=request.scene_id,
                success=True,
                provider=self.name,
                model="nano_banana_image_v1",
                output_path=out_file,
                media_type="image",
                metrics=GenerationMetrics(
                    generation_time_seconds=gen_time,
                    width=w,
                    height=h,
                    file_size_bytes=file_size,
                ),
                metadata={
                    "prompt": request.prompt,
                    "aspect_ratio": request.aspect_ratio,
                    "visual_source_type": "generated_image",
                },
            )

        # Chamada real futura (requer credencial autorizada)
        return GenerationResult(
            scene_id=request.scene_id,
            success=False,
            provider=self.name,
            model="nano_banana_image_v1",
            fallback_reason="NANO_BANANA_STUB_MODE",
            error="Real generation not executed in DEV environment",
        )


# =============================================================================
# ComfyUI Integration (Headless / API Client)
# =============================================================================

class ComfyUIClient:
    """
    Cliente HTTP mínimo para orquestração remota/local do ComfyUI API.
    Zero dependência pesada no notebook de desenvolvimento.
    """

    def __init__(
        self,
        endpoint: str = "http://127.0.0.1:8188",
        timeout_seconds: float = 60.0,
    ):
        self.endpoint = endpoint.rstrip("/")
        self.timeout_seconds = timeout_seconds

    def check_health(self) -> bool:
        """Verifica se o servidor ComfyUI está respondendo via /system_stats."""
        url = f"{self.endpoint}/system_stats"
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
            with urllib.request.urlopen(req, timeout=min(5.0, self.timeout_seconds)) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    data = json.loads(resp.read().decode("utf-8"))
                    return "system" in data or "devices" in data or isinstance(data, dict)
            return False
        except Exception as exc:
            logger.debug(f"[COMFYUI][HEALTH_CHECK_FAILED] endpoint={url} error={exc}")
            return False

    def submit_workflow(
        self,
        prompt_workflow: Dict[str, Any],
        client_id: str = "moneyprinterturbo_client",
    ) -> Dict[str, Any]:
        """Submete um workflow ComfyUI para a fila de execução via POST /prompt."""
        url = f"{self.endpoint}/prompt"
        payload = json.dumps({"prompt": prompt_workflow, "client_id": client_id}).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json", "User-Agent": "MoneyPrinterTurbo-VisualDirector"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                raise RuntimeError(f"ComfyUI HTTP {status}")
        except Exception as exc:
            logger.error(f"[COMFYUI][SUBMIT_FAILED] endpoint={url} error={exc}")
            raise

    def get_history(self, prompt_id: str) -> Dict[str, Any]:
        """Consulta o status e histórico de execução via GET /history/{prompt_id}."""
        url = f"{self.endpoint}/history/{prompt_id}"
        req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
        try:
            with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp:
                status = getattr(resp, "status", getattr(resp, "code", 200))
                if status == 200:
                    return json.loads(resp.read().decode("utf-8"))
                raise RuntimeError(f"ComfyUI HTTP {status}")
        except Exception as exc:
            logger.error(f"[COMFYUI][GET_HISTORY_FAILED] prompt_id={prompt_id} error={exc}")
            raise

    def poll_until_complete(
        self,
        prompt_id: str,
        poll_interval: float = 1.0,
        max_wait_seconds: float = 60.0,
    ) -> Dict[str, Any]:
        """Aguarda a conclusão do processamento em ComfyUI via polling de /history."""
        start = time.time()
        while time.time() - start < max_wait_seconds:
            history = self.get_history(prompt_id)
            if prompt_id in history:
                prompt_data = history[prompt_id]
                if "outputs" in prompt_data and prompt_data["outputs"]:
                    return prompt_data
                status = prompt_data.get("status", {})
                if status.get("status_str") == "error":
                    raise RuntimeError(f"ComfyUI execution error: {status.get('messages', [])}")
            time.sleep(poll_interval)
        raise TimeoutError(f"ComfyUI polling timed out after {max_wait_seconds}s for prompt_id={prompt_id}")

    def get_output_url(
        self,
        filename: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> str:
        """Retorna a URL HTTP direta para download do ativo gerado via GET /view."""
        params = {"filename": filename, "type": folder_type}
        if subfolder:
            params["subfolder"] = subfolder
        return f"{self.endpoint}/view?{urllib.parse.urlencode(params)}"

    def download_output(
        self,
        filename: str,
        destination_path: str,
        subfolder: str = "",
        folder_type: str = "output",
    ) -> str:
        """Faz download do ativo final gerado pelo ComfyUI para o disco local."""
        url = self.get_output_url(filename, subfolder=subfolder, folder_type=folder_type)
        os.makedirs(os.path.dirname(os.path.abspath(destination_path)), exist_ok=True)
        req = urllib.request.Request(url, headers={"User-Agent": "MoneyPrinterTurbo-VisualDirector"})
        with urllib.request.urlopen(req, timeout=self.timeout_seconds) as resp, open(
            destination_path, "wb"
        ) as fp:
            fp.write(resp.read())
        return destination_path


# =============================================================================
# ComfyUI Visual Provider (Wan 2.2, LTX-Video, FramePack)
# =============================================================================

class ComfyUIVisualProvider(VisualGenerationProvider):
    """
    Provider para geração de vídeo acelerada via ComfyUI (Wan 2.2, LTX-Video, FramePack).
    Suporta text_to_video, image_to_video e text_to_image.
    """

    def __init__(
        self,
        client: Optional[ComfyUIClient] = None,
        endpoint: str = "http://127.0.0.1:8188",
        default_model: str = "wan_2_2",
        timeout_seconds: float = 60.0,
    ):
        self.client = client or ComfyUIClient(endpoint=endpoint, timeout_seconds=timeout_seconds)
        self.default_model = default_model
        self.timeout_seconds = timeout_seconds

    @property
    def name(self) -> str:
        return "comfyui"

    @property
    def capabilities(self) -> ProviderCapabilities:
        return ProviderCapabilities(
            supports_text_to_video=True,
            supports_image_to_video=True,
            supports_text_to_image=True,
            max_duration_seconds=10.0,
            supported_aspect_ratios=["9:16", "16:9", "1:1"],
        )

    def is_available(self) -> bool:
        return self.client.check_health()

    def generate(self, request: GenerationRequest) -> GenerationResult:
        if not self.is_available():
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=request.model or self.default_model,
                fallback_reason="PROVIDER_UNAVAILABLE",
                error=f"ComfyUI endpoint {self.client.endpoint} unreachable",
            )

        if not self.capabilities.has_capability(request.target_capability):
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=request.model or self.default_model,
                fallback_reason="CAPABILITY_UNSUPPORTED",
                error=f"Capability '{request.target_capability}' not supported by ComfyUI provider",
            )

        start_time = time.time()
        model_name = request.model or self.default_model

        try:
            workflow = {
                "3": {
                    "class_type": "KSampler",
                    "inputs": {
                        "seed": request.seed or 42,
                        "steps": 20,
                        "cfg": 7.0,
                        "sampler_name": "euler",
                        "scheduler": "normal",
                    },
                },
                "6": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": request.prompt},
                },
                "7": {
                    "class_type": "CLIPTextEncode",
                    "inputs": {"text": request.negative_prompt or "ugly, blurry, low quality"},
                },
                "meta": {
                    "model": model_name,
                    "aspect_ratio": request.aspect_ratio,
                    "duration_seconds": request.duration_seconds,
                    "capability": request.target_capability.value,
                },
            }

            sub_resp = self.client.submit_workflow(workflow)
            prompt_id = sub_resp.get("prompt_id")
            if not prompt_id:
                raise RuntimeError(f"Missing prompt_id in ComfyUI response: {sub_resp}")

            history_data = self.client.poll_until_complete(
                prompt_id=prompt_id,
                poll_interval=1.0,
                max_wait_seconds=self.timeout_seconds,
            )

            outputs = history_data.get("outputs", {})
            filename = f"comfyui_{model_name}_{request.scene_id}.mp4"
            subfolder = ""
            for node_id, node_out in outputs.items():
                if "gifs" in node_out and node_out["gifs"]:
                    filename = node_out["gifs"][0].get("filename", filename)
                    subfolder = node_out["gifs"][0].get("subfolder", "")
                    break
                if "images" in node_out and node_out["images"]:
                    filename = node_out["images"][0].get("filename", filename)
                    subfolder = node_out["images"][0].get("subfolder", "")
                    break

            out_path = request.output_path or f"storage/comfyui_output_{filename}"
            self.client.download_output(filename, out_path, subfolder=subfolder)

            duration = time.time() - start_time
            file_size = os.path.getsize(out_path) if os.path.exists(out_path) else 0

            return GenerationResult(
                scene_id=request.scene_id,
                success=True,
                provider=self.name,
                model=model_name,
                output_path=out_path,
                media_type="video" if "video" in request.target_capability.value else "image",
                metrics=GenerationMetrics(
                    generation_time_seconds=round(duration, 3),
                    file_size_bytes=file_size,
                    frames_generated=int(request.duration_seconds * 24),
                    fps=24.0,
                ),
                metadata={
                    "prompt_id": prompt_id,
                    "prompt": request.prompt,
                    "model": model_name,
                },
            )

        except TimeoutError as exc:
            logger.warning(f"[COMFYUI][TIMEOUT] scene_id={request.scene_id} model={model_name} error={exc}")
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=model_name,
                fallback_reason="PROVIDER_TIMEOUT",
                error=str(exc),
            )
        except Exception as exc:
            logger.error(f"[COMFYUI][ERROR] scene_id={request.scene_id} model={model_name} error={exc}")
            return GenerationResult(
                scene_id=request.scene_id,
                success=False,
                provider=self.name,
                model=model_name,
                fallback_reason="GENERATION_FAILED",
                error=str(exc),
            )


# =============================================================================
# Hybrid Visual Director (Orchestrator with Contextual Decision & Resilient Fallback)
# =============================================================================

class HybridVisualDirector:
    """
    Orquestrador central de seleção e geração visual de cenas (V16.6 e V16.6.2).

    Implementa a política de decisão inteligente e fail-safe:
    - visual_generation_enabled = false -> 100% stock library (comportamento legado idêntico).
    - score de stock >= stock_high_confidence_threshold (60) -> STOCK_HIGH_CONFIDENCE
    - 35 <= score < 60 -> GENERATED_IMAGE_PREFERRED (Nano Banana keyframe + still motion)
    - score < 35 -> GENERATED_VIDEO_PREFERRED (ou imagem + motion se vídeo desabilitado)
    - Qualquer falha (indisponibilidade, timeout, erro, capability não suportada, quality gate reprovado) ->
      Fallback imediato e transparente para stock.
    - O pipeline nunca falha por indisponibilidade de IA.
    """

    def __init__(
        self,
        visual_generation_enabled: bool = False,
        generated_image_enabled: bool = False,
        generated_video_enabled: bool = False,
        stock_high_confidence_threshold: float = 60.0,
        generated_image_threshold: float = 35.0,
        preferred_video_provider: str = "disabled",
        preferred_image_provider: str = "nano_banana",
        image_to_video_provider: str = "disabled",
        still_motion_enabled: bool = True,
        providers: Optional[Dict[str, VisualGenerationProvider]] = None,
    ):
        self.visual_generation_enabled = visual_generation_enabled
        self.generated_image_enabled = generated_image_enabled
        self.generated_video_enabled = generated_video_enabled
        self.stock_high_confidence_threshold = stock_high_confidence_threshold
        self.generated_image_threshold = generated_image_threshold
        self.preferred_video_provider = preferred_video_provider
        self.preferred_image_provider = preferred_image_provider
        self.image_to_video_provider = image_to_video_provider
        self.still_motion_enabled = still_motion_enabled
        self.providers: Dict[str, VisualGenerationProvider] = providers or {}

    def register_provider(self, provider: VisualGenerationProvider) -> None:
        self.providers[provider.name] = provider

    def get_provider(self, name: str) -> Optional[VisualGenerationProvider]:
        return self.providers.get(name)

    def determine_scene_strategy(
        self,
        stock_match_score: Optional[float] = None,
        visual_intent: Optional[Any] = None,
        scene_importance: Optional[Union[str, SceneImportance]] = None,
        candidate_is_reused: bool = False,
        candidate_aspect_ratio: Optional[str] = None,
        target_aspect_ratio: str = "9:16",
        candidate_duration: Optional[float] = None,
        scene_duration: float = 4.0,
        fallback_history_count: int = 0,
    ) -> HybridDecision:
        """
        Determina a estratégia visual para a cena com base no score de stock, importância da cena
        e heurística de custo/benefício (V16.7):
        - visual_generation_enabled=False -> STOCK_HIGH_CONFIDENCE
        - Aplica modificadores de threshold baseados em:
          * scene_importance: HERO (+10 stock threshold, mais propenso a IA), LOW (-10 stock threshold, prioriza stock).
          * candidate_aspect_ratio: nativo alinhado (-5 stock threshold) vs crop desalinhado (+5 stock threshold).
          * candidate_is_reused: repetição (+15 stock threshold, desestimula repetir stock).
          * fallback_history_count: falha prévia de IA (-10 stock threshold, cautela com retries).
          * candidate_duration: duração insuficiente (+5 stock threshold).
        - score >= effective_stock_threshold -> STOCK_HIGH_CONFIDENCE
        - score >= effective_image_threshold -> GENERATED_IMAGE_PREFERRED (se imagem habilitada)
        - score < effective_image_threshold -> GENERATED_VIDEO_PREFERRED (se vídeo habilitado e != disabled)
          ou GENERATED_IMAGE_PREFERRED (se imagem habilitada)
        - Fallback padrão: STOCK_HIGH_CONFIDENCE
        """
        if not self.visual_generation_enabled:
            return HybridDecision.STOCK_HIGH_CONFIDENCE

        score = 0.0 if stock_match_score is None else float(stock_match_score)

        effective_stock_threshold = float(self.stock_high_confidence_threshold)
        effective_image_threshold = float(self.generated_image_threshold)

        # 1. Scene Importance
        imp_str = (
            scene_importance.value
            if isinstance(scene_importance, SceneImportance)
            else str(scene_importance or "NORMAL").upper()
        )
        if imp_str == SceneImportance.HERO.value:
            effective_stock_threshold += 10.0
            effective_image_threshold -= 5.0
        elif imp_str == SceneImportance.LOW.value:
            effective_stock_threshold -= 10.0
            effective_image_threshold += 5.0

        # 2. Aspect Ratio do candidato
        if candidate_aspect_ratio:
            c_asp = str(candidate_aspect_ratio).strip().lower()
            t_asp = str(target_aspect_ratio).strip().lower()
            if c_asp == t_asp or (c_asp == "portrait" and t_asp == "9:16") or (c_asp == "landscape" and t_asp == "16:9"):
                effective_stock_threshold -= 5.0
            elif (c_asp in ("16:9", "landscape") and t_asp in ("9:16", "portrait")):
                effective_stock_threshold += 5.0

        # 3. Penalidade de reuso (repetition penalty)
        if candidate_is_reused:
            effective_stock_threshold += 15.0

        # 4. Histórico de falhas de IA nesta execução
        if fallback_history_count > 0:
            effective_stock_threshold -= 10.0

        # 5. Duração insuficiente do stock
        if candidate_duration is not None and candidate_duration < scene_duration:
            effective_stock_threshold += 5.0

        # Clamps para limites razoáveis
        effective_stock_threshold = max(20.0, min(95.0, effective_stock_threshold))
        effective_image_threshold = max(10.0, min(effective_stock_threshold - 5.0, effective_image_threshold))

        if score >= effective_stock_threshold:
            return HybridDecision.STOCK_HIGH_CONFIDENCE

        if score >= effective_image_threshold:
            if self.generated_image_enabled:
                return HybridDecision.GENERATED_IMAGE_PREFERRED
            return HybridDecision.STOCK_HIGH_CONFIDENCE

        # score < effective_image_threshold
        if self.generated_video_enabled and self.preferred_video_provider not in ("disabled", "stock"):
            return HybridDecision.GENERATED_VIDEO_PREFERRED
        if self.generated_image_enabled:
            return HybridDecision.GENERATED_IMAGE_PREFERRED

        return HybridDecision.STOCK_HIGH_CONFIDENCE

    def resolve_contextual_scene_visual(
        self,
        scene_index: int,
        stock_match_score: Optional[float] = None,
        visual_intent: Optional[Any] = None,
        narration: str = "",
        aspect_ratio: str = "9:16",
        duration_seconds: float = 4.0,
        stock_asset_resolver: Optional[Callable[[], Any]] = None,
        scene_importance: Optional[Union[str, SceneImportance]] = None,
        candidate_aspect_ratio: Optional[str] = None,
        target_aspect_ratio: str = "9:16",
        candidate_is_reused: bool = False,
        candidate_duration: Optional[float] = None,
        candidate_identifier: Optional[str] = None,
        fallback_history_count: int = 0,
    ) -> GenerationResult:
        """
        Resolve o ativo visual da cena aplicando a política contextual híbrida (V16.7).
        Avalia score de stock, importância da cena, heurística de custo/benefício,
        sintetiza keyframe contextual se necessário, passa pelo Quality Gate,
        injeta still motion determinístico e preserva fallback resiliente com observabilidade.
        """
        if scene_importance is None:
            scene_importance = classify_scene_importance(
                scene_index=scene_index,
                narration=narration,
                visual_intent=visual_intent,
                duration_seconds=duration_seconds,
            )

        imp_val = (
            scene_importance.value
            if isinstance(scene_importance, SceneImportance)
            else str(scene_importance).upper()
        )
        score_val = float(stock_match_score) if stock_match_score is not None else 0.0

        strategy = self.determine_scene_strategy(
            stock_match_score=stock_match_score,
            visual_intent=visual_intent,
            scene_importance=scene_importance,
            candidate_aspect_ratio=candidate_aspect_ratio,
            target_aspect_ratio=target_aspect_ratio or aspect_ratio,
            candidate_is_reused=candidate_is_reused,
            candidate_duration=candidate_duration,
            scene_duration=duration_seconds,
            fallback_history_count=fallback_history_count,
        )

        base_meta = {
            "strategy_selected": strategy.value,
            "scene_importance": imp_val,
            "stock_score": score_val,
            "stock_candidate": candidate_identifier or "",
            "decision": strategy.value,
            "stock_match_score": score_val,
        }

        # Caso 1: Stock de alta confiança ou geração global desabilitada
        if strategy == HybridDecision.STOCK_HIGH_CONFIDENCE:
            logger.info(
                f"[HYBRID_DECISION] Scene {scene_index} ({imp_val}) -> STOCK_HIGH_CONFIDENCE (score={score_val:.1f})"
            )
            meta = dict(base_meta)
            meta.update({
                "visual_source_type": "stock",
                "final_visual_source": "stock",
                "generation_status": "bypassed",
                "generated_attempted": False,
                "fallback_used": False,
            })
            return self._execute_stock_fallback(
                request=GenerationRequest(
                    scene_id=scene_index,
                    prompt=narration,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=duration_seconds,
                ),
                reason="STOCK_HIGH_CONFIDENCE",
                stock_resolver_fallback=stock_asset_resolver,
                metadata=meta,
            )

        # Caso 2: Geração de Imagem / Keyframe Contextual
        if strategy == HybridDecision.GENERATED_IMAGE_PREFERRED:
            logger.info(
                f"[HYBRID_DECISION] Scene {scene_index} ({imp_val}) -> GENERATED_IMAGE_PREFERRED (score={score_val:.1f})"
            )
            prompt_payload = build_image_prompt_from_visual_intent(
                intent=visual_intent,
                narration=narration,
                aspect_ratio=aspect_ratio,
            )

            provider_name = self.preferred_image_provider
            provider = self.get_provider(provider_name)

            if not provider or not provider.is_available():
                reason = "PROVIDER_NOT_REGISTERED" if not provider else "PROVIDER_UNAVAILABLE"
                logger.warning(
                    f"[HYBRID_DECISION][FALLBACK] Image provider '{provider_name}' {reason}. Fallback to stock."
                )
                meta = dict(base_meta)
                meta.update({
                    "visual_source_type": "stock",
                    "final_visual_source": "stock",
                    "generation_status": "fallback",
                    "generated_attempted": True,
                    "generation_provider": provider_name,
                    "fallback_used": True,
                    "fallback_reason": reason,
                })
                return self._execute_stock_fallback(
                    request=GenerationRequest(
                        scene_id=scene_index,
                        prompt=prompt_payload.prompt,
                        aspect_ratio=aspect_ratio,
                        duration_seconds=duration_seconds,
                    ),
                    reason=reason,
                    stock_resolver_fallback=stock_asset_resolver,
                    metadata=meta,
                )

            req = GenerationRequest(
                scene_id=scene_index,
                prompt=prompt_payload.prompt,
                negative_prompt=prompt_payload.negative_prompt,
                aspect_ratio=aspect_ratio,
                duration_seconds=duration_seconds,
                target_capability=VisualCapability.TEXT_TO_IMAGE,
                output_path=f"storage/keyframe_scene_{scene_index}.png",
            )

            try:
                gen_res = provider.generate(req)
            except TimeoutError as exc:
                logger.warning(f"[HYBRID_DECISION][FALLBACK] Image provider timeout: {exc}. Fallback to stock.")
                meta = dict(base_meta)
                meta.update({
                    "visual_source_type": "stock",
                    "final_visual_source": "stock",
                    "generation_status": "fallback",
                    "generated_attempted": True,
                    "generation_provider": provider_name,
                    "fallback_used": True,
                    "fallback_reason": "PROVIDER_TIMEOUT",
                })
                return self._execute_stock_fallback(
                    request=req,
                    reason="PROVIDER_TIMEOUT",
                    error=str(exc),
                    stock_resolver_fallback=stock_asset_resolver,
                    metadata=meta,
                )
            except Exception as exc:
                logger.error(
                    f"[HYBRID_DECISION][FALLBACK] Exception in image provider: {exc}. Fallback to stock."
                )
                meta = dict(base_meta)
                meta.update({
                    "visual_source_type": "stock",
                    "final_visual_source": "stock",
                    "generation_status": "fallback",
                    "generated_attempted": True,
                    "generation_provider": provider_name,
                    "fallback_used": True,
                    "fallback_reason": "GENERATION_EXCEPTION",
                })
                return self._execute_stock_fallback(
                    request=req,
                    reason="GENERATION_EXCEPTION",
                    error=str(exc),
                    stock_resolver_fallback=stock_asset_resolver,
                    metadata=meta,
                )

            if not gen_res.success:
                fallback_rsn = gen_res.fallback_reason or "IMAGE_GENERATION_FAILED"
                logger.warning(
                    f"[HYBRID_DECISION][FALLBACK] Image generation failed ({fallback_rsn}). Fallback to stock."
                )
                meta = dict(base_meta)
                meta.update({
                    "visual_source_type": "stock",
                    "final_visual_source": "stock",
                    "generation_status": "fallback",
                    "generated_attempted": True,
                    "generation_provider": gen_res.provider,
                    "generation_model": gen_res.model,
                    "fallback_used": True,
                    "fallback_reason": fallback_rsn,
                })
                return self._execute_stock_fallback(
                    request=req,
                    reason=fallback_rsn,
                    error=gen_res.error,
                    stock_resolver_fallback=stock_asset_resolver,
                    metadata=meta,
                )

            # Image Quality Gate
            qg = evaluate_keyframe_quality(gen_res.output_path, expected_aspect_ratio=aspect_ratio)
            if not qg.is_valid:
                logger.warning(
                    f"[HYBRID_DECISION][FALLBACK] Keyframe quality gate failed: {qg.reason}. Fallback to stock."
                )
                meta = dict(base_meta)
                meta.update({
                    "visual_source_type": "stock",
                    "final_visual_source": "stock",
                    "generation_status": "fallback",
                    "generated_attempted": True,
                    "generation_provider": gen_res.provider,
                    "generation_model": gen_res.model,
                    "fallback_used": True,
                    "fallback_reason": f"QUALITY_GATE_{qg.reason}",
                    "quality_gate_details": qg.details,
                })
                return self._execute_stock_fallback(
                    request=req,
                    reason=f"QUALITY_GATE_{qg.reason}",
                    error=qg.reason,
                    stock_resolver_fallback=stock_asset_resolver,
                    metadata=meta,
                )

            # Sucesso no Keyframe
            chosen_mode = select_still_motion_mode(scene_index, visual_intent, narration)
            meta = dict(base_meta)
            meta.update({
                "generated_attempted": True,
                "generation_prompt": prompt_payload.prompt,
                "generation_model": gen_res.model,
                "generation_provider": gen_res.provider,
                "generation_status": "success",
                "generated_asset_path": gen_res.output_path,
                "fallback_used": False,
                "fallback_reason": None,
            })
            if self.still_motion_enabled:
                motion = generate_still_motion_instructions(
                    image_path=gen_res.output_path or "",
                    duration_seconds=duration_seconds,
                    aspect_ratio=aspect_ratio,
                    mode=chosen_mode,
                )
                meta["still_motion_mode"] = chosen_mode.value
                meta["motion_mode"] = chosen_mode.value
                meta["motion_instructions"] = motion
                meta["visual_source_type"] = "image_motion"
                meta["final_visual_source"] = "image_motion"
            else:
                meta["visual_source_type"] = "generated_image"
                meta["final_visual_source"] = "generated_image"

            gen_res.metadata.update(meta)
            return gen_res

        # Caso 3: Vídeo Generativo Preferido
        if strategy == HybridDecision.GENERATED_VIDEO_PREFERRED:
            logger.info(
                f"[HYBRID_DECISION] Scene {scene_index} ({imp_val}) -> GENERATED_VIDEO_PREFERRED (score={score_val:.1f})"
            )
            v_provider = self.get_provider(self.preferred_video_provider)
            if v_provider and v_provider.is_available():
                req = GenerationRequest(
                    scene_id=scene_index,
                    prompt=narration,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=duration_seconds,
                    target_capability=VisualCapability.TEXT_TO_VIDEO,
                    output_path=f"storage/gen_video_scene_{scene_index}.mp4",
                )
                try:
                    res = v_provider.generate(req)
                    if res.success:
                        meta = dict(base_meta)
                        meta.update({
                            "generated_attempted": True,
                            "visual_source_type": "generated_video",
                            "final_visual_source": "generated_video",
                            "generation_status": "success",
                            "fallback_used": False,
                            "fallback_reason": None,
                        })
                        res.metadata.update(meta)
                        return res
                except TimeoutError as exc:
                    logger.warning(f"[HYBRID_DECISION] Video provider timeout: {exc}")
                except Exception as exc:
                    logger.warning(f"[HYBRID_DECISION] Video provider exception: {exc}")

            # Fallback para generated_image se vídeo falhar
            if self.generated_image_enabled:
                logger.info("[HYBRID_DECISION] Video provider unavailable/failed. Attempting generated image fallback.")
                return self.resolve_contextual_scene_visual(
                    scene_index=scene_index,
                    stock_match_score=self.generated_image_threshold + 5.0,  # Força ramo de imagem
                    visual_intent=visual_intent,
                    narration=narration,
                    aspect_ratio=aspect_ratio,
                    duration_seconds=duration_seconds,
                    stock_asset_resolver=stock_asset_resolver,
                    scene_importance=scene_importance,
                    candidate_aspect_ratio=candidate_aspect_ratio,
                    target_aspect_ratio=target_aspect_ratio,
                    candidate_is_reused=candidate_is_reused,
                    candidate_duration=candidate_duration,
                    candidate_identifier=candidate_identifier,
                    fallback_history_count=fallback_history_count,
                )

            # Fallback para stock se tudo mais falhar
            meta = dict(base_meta)
            meta.update({
                "visual_source_type": "stock",
                "final_visual_source": "stock",
                "generation_status": "fallback",
                "generated_attempted": True,
                "fallback_used": True,
                "fallback_reason": "VIDEO_GENERATION_FAILED_OR_DISABLED",
            })
            return self._execute_stock_fallback(
                request=GenerationRequest(scene_id=scene_index, prompt=narration, aspect_ratio=aspect_ratio, duration_seconds=duration_seconds),
                reason="VIDEO_GENERATION_FAILED_OR_DISABLED",
                stock_resolver_fallback=stock_asset_resolver,
                metadata=meta,
            )

        # Fallback padrão
        meta = dict(base_meta)
        meta.update({
            "visual_source_type": "stock",
            "final_visual_source": "stock",
            "generation_status": "fallback",
            "generated_attempted": False,
            "fallback_used": True,
            "fallback_reason": "DEFAULT_FALLBACK",
        })
        return self._execute_stock_fallback(
            request=GenerationRequest(scene_id=scene_index, prompt=narration, aspect_ratio=aspect_ratio, duration_seconds=duration_seconds),
            reason="DEFAULT_FALLBACK",
            stock_resolver_fallback=stock_asset_resolver,
            metadata=meta,
        )

    def resolve_scene_visual(
        self,
        request: GenerationRequest,
        stock_resolver_fallback: Optional[Callable[[], Any]] = None,
    ) -> GenerationResult:
        """
        Resolve o ativo visual para uma cena respeitando o pipeline híbrido (assinatura V16.6 mantida).
        Garante retorno de GenerationResult válido ou acionamento do fallback stock.
        """
        if not self.visual_generation_enabled:
            logger.info(
                f"[HYBRID_VISUAL] visual_generation_enabled=False. Using stock for scene {request.scene_id}"
            )
            return self._execute_stock_fallback(
                request=request,
                reason="VISUAL_GENERATION_DISABLED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        target_cap = request.target_capability
        if target_cap == VisualCapability.TEXT_TO_IMAGE:
            provider_name = self.preferred_image_provider
        elif target_cap in (VisualCapability.TEXT_TO_VIDEO, VisualCapability.IMAGE_TO_VIDEO):
            provider_name = self.preferred_video_provider
        else:
            provider_name = "stock"

        if provider_name in ("stock", "disabled"):
            return self._execute_stock_fallback(
                request=request,
                reason="PREFERRED_IS_STOCK" if provider_name == "stock" else "PROVIDER_DISABLED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        provider = self.get_provider(provider_name)
        if not provider:
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' not registered. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="PROVIDER_NOT_REGISTERED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        if not provider.is_available():
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' unavailable. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="PROVIDER_UNAVAILABLE",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        if not provider.capabilities.has_capability(target_cap):
            logger.warning(
                f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' does not support '{target_cap}'. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="CAPABILITY_UNSUPPORTED",
                stock_resolver_fallback=stock_resolver_fallback,
            )

        try:
            result = provider.generate(request)
            if result.success:
                logger.info(
                    f"[HYBRID_VISUAL][SUCCESS] Generated scene {request.scene_id} "
                    f"using provider={provider_name} model={result.model}"
                )
                return result
            else:
                logger.warning(
                    f"[HYBRID_VISUAL][FALLBACK] Provider '{provider_name}' failed "
                    f"(reason={result.fallback_reason}, error={result.error}). Fallback to stock."
                )
                return self._execute_stock_fallback(
                    request=request,
                    reason=result.fallback_reason or "GENERATION_FAILED",
                    error=result.error,
                    stock_resolver_fallback=stock_resolver_fallback,
                )
        except Exception as exc:
            logger.error(
                f"[HYBRID_VISUAL][FALLBACK] Unexpected exception in provider '{provider_name}': {exc}. Fallback to stock."
            )
            return self._execute_stock_fallback(
                request=request,
                reason="GENERATION_EXCEPTION",
                error=str(exc),
                stock_resolver_fallback=stock_resolver_fallback,
            )

    def _execute_stock_fallback(
        self,
        request: GenerationRequest,
        reason: str,
        error: Optional[str] = None,
        stock_resolver_fallback: Optional[Callable[[], Any]] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> GenerationResult:
        """Executa com segurança o fallback para material de stock."""
        fallback_path = None
        if stock_resolver_fallback:
            try:
                fallback_path = stock_resolver_fallback()
            except Exception as exc:
                logger.warning(f"[HYBRID_VISUAL] Stock fallback callback failed: {exc}")

        meta = {
            "reason_for_generated_vs_stock": f"fallback_due_to_{reason}",
            "original_prompt": request.prompt,
            "visual_source_type": "stock",
        }
        if metadata:
            meta.update(metadata)

        return GenerationResult(
            scene_id=request.scene_id,
            success=True,
            provider="stock",
            model="stock_library",
            output_path=str(fallback_path) if fallback_path else request.output_path,
            media_type="stock",
            fallback_reason=reason,
            error=error,
            metadata=meta,
        )


# =============================================================================
# Factory Helper
# =============================================================================

def build_hybrid_visual_director(
    config_dict: Optional[Dict[str, Any]] = None,
) -> HybridVisualDirector:
    """
    Cria uma instância configurada do HybridVisualDirector com os providers
    padrão inicializados (Stock, Nano Banana adapter, ComfyUI provider).
    """
    cfg = config_dict or {}
    enabled = bool(cfg.get("visual_generation_enabled", False))
    gen_img_enabled = bool(cfg.get("generated_image_enabled", False))
    gen_vid_enabled = bool(cfg.get("generated_video_enabled", False))
    stock_threshold = float(cfg.get("stock_high_confidence_threshold", 60.0))
    img_threshold = float(cfg.get("generated_image_threshold", 35.0))
    preferred_video = str(cfg.get("preferred_video_provider", "disabled"))
    preferred_image = str(cfg.get("preferred_image_provider", "nano_banana"))
    i2v_provider = str(cfg.get("image_to_video_provider", "disabled"))
    still_motion = bool(cfg.get("still_motion_enabled", True))
    comfyui_endpoint = str(cfg.get("comfyui_endpoint", "http://127.0.0.1:8188"))

    director = HybridVisualDirector(
        visual_generation_enabled=enabled,
        generated_image_enabled=gen_img_enabled,
        generated_video_enabled=gen_vid_enabled,
        stock_high_confidence_threshold=stock_threshold,
        generated_image_threshold=img_threshold,
        preferred_video_provider=preferred_video,
        preferred_image_provider=preferred_image,
        image_to_video_provider=i2v_provider,
        still_motion_enabled=still_motion,
    )

    director.register_provider(StockVisualProvider())
    director.register_provider(NanoBananaImageAdapter())
    director.register_provider(
        ComfyUIVisualProvider(
            client=ComfyUIClient(endpoint=comfyui_endpoint),
            default_model="wan_2_2",
        )
    )

    return director
