"""
Módulo de Qualidade de Mídia Final (Fase V16.3 — Final Media Quality Gate)

Regra Fundamental: AUTONOMOUS_FINAL_MEDIA_WITH_CRITICAL_DEFECT = FORBIDDEN

Responsabilidades:
1. Inspeção confiável e segura de metadados de contêiner e streams via ffprobe.
2. Validação determinística, objetiva e fail-closed de mídia final renderizada.
3. Bloqueio pré-publicação contra vídeos corrompidos, incompletos, sem áudio,
   sem stream de vídeo, com dimensões/resolução insuficientes ou duração incoerente.
"""

import json
import math
import os
import shutil
import subprocess
from typing import Any, Dict, List, Optional

from loguru import logger

from app.config import config
from app.models.schema import VideoAspect, VideoParams
from app.utils import utils

DEFAULT_MEDIA_PROBE_TIMEOUT = 15
MIN_VALID_MEDIA_FILE_BYTES = 10 * 1024  # 10 KB mínimo para contêiner MP4 funcional com streams
ASPECT_RATIO_TOLERANCE = 0.05
MIN_PORTRAIT_WIDTH = 720
MIN_PORTRAIT_HEIGHT = 1280
MIN_LANDSCAPE_WIDTH = 1280
MIN_LANDSCAPE_HEIGHT = 720
MIN_SQUARE_DIMENSION = 720


def get_ffprobe_binary() -> Optional[str]:
    """Resolve o executável do ffprobe utilizando a mesma estratégia do ecossistema."""
    configured = config.app.get("ffprobe_path") or os.environ.get("FFPROBE_PATH")
    if configured and (shutil.which(configured) or os.path.isfile(configured)):
        return configured

    sys_ffprobe = shutil.which("ffprobe")
    if sys_ffprobe:
        return sys_ffprobe

    try:
        ffmpeg_bin = utils.get_ffmpeg_binary()
        if ffmpeg_bin and ffmpeg_bin != "ffmpeg":
            ffmpeg_dir = os.path.dirname(ffmpeg_bin)
            candidate = os.path.join(
                ffmpeg_dir, "ffprobe.exe" if os.name == "nt" else "ffprobe"
            )
            if os.path.isfile(candidate):
                return candidate
    except Exception:
        pass

    return None


def probe_media(
    file_path: str, timeout_seconds: int = DEFAULT_MEDIA_PROBE_TIMEOUT
) -> Dict[str, Any]:
    """Inspeciona arquivo de vídeo usando ffprobe e retorna metadados estruturados.

    Garantias de segurança:
    - Lista de argumentos (shell=False).
    - Timeout rígido com captura de output.
    - Captura e normalização de erros sem exceções não tratadas.
    """
    base_result: Dict[str, Any] = {
        "valid": False,
        "error_code": None,
        "error_message": None,
        "format": {},
        "video_streams": [],
        "audio_streams": [],
        "format_duration": 0.0,
        "format_size": 0,
    }

    if not file_path or not isinstance(file_path, str) or not file_path.strip():
        base_result["error_code"] = "FINAL_MEDIA_MISSING"
        base_result["error_message"] = "empty or invalid path"
        return base_result

    if not os.path.exists(file_path):
        base_result["error_code"] = "FINAL_MEDIA_MISSING"
        base_result["error_message"] = f"file does not exist: {file_path}"
        return base_result

    if not os.path.isfile(file_path):
        base_result["error_code"] = "FINAL_MEDIA_NOT_A_FILE"
        base_result["error_message"] = f"path is not a regular file: {file_path}"
        return base_result

    ffprobe_bin = get_ffprobe_binary()
    if not ffprobe_bin:
        base_result["error_code"] = "FFPROBE_UNAVAILABLE"
        base_result["error_message"] = "ffprobe binary not found in system or environment"
        return base_result

    cmd = [
        ffprobe_bin,
        "-v",
        "error",
        "-print_format",
        "json",
        "-show_format",
        "-show_streams",
        file_path,
    ]

    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
        )
    except subprocess.TimeoutExpired as exc:
        base_result["error_code"] = "FFPROBE_TIMEOUT"
        base_result["error_message"] = f"ffprobe timed out after {timeout_seconds}s: {exc}"
        return base_result
    except FileNotFoundError as exc:
        base_result["error_code"] = "FFPROBE_UNAVAILABLE"
        base_result["error_message"] = f"ffprobe binary cannot be executed: {exc}"
        return base_result
    except Exception as exc:
        base_result["error_code"] = "FFPROBE_FAILED"
        base_result["error_message"] = f"ffprobe execution error: {exc}"
        return base_result

    if proc.returncode != 0:
        base_result["error_code"] = "FFPROBE_FAILED"
        err_msg = (proc.stderr or "").strip()
        base_result["error_message"] = f"ffprobe exited with code {proc.returncode}: {err_msg}"
        return base_result

    stdout_text = (proc.stdout or "").strip()
    if not stdout_text:
        base_result["error_code"] = "FFPROBE_PARSE_ERROR"
        base_result["error_message"] = "ffprobe returned empty stdout"
        return base_result

    try:
        payload = json.loads(stdout_text)
    except Exception as exc:
        base_result["error_code"] = "FFPROBE_PARSE_ERROR"
        base_result["error_message"] = f"failed to parse ffprobe json: {exc}"
        return base_result

    # Validação estrutural defensiva do payload (Hardening V16.3-1)
    if not isinstance(payload, dict):
        base_result["error_code"] = "FFPROBE_PARSE_ERROR"
        base_result["error_message"] = f"ffprobe payload is not a dictionary: {type(payload).__name__}"
        return base_result

    format_val = payload.get("format")
    if format_val is not None and not isinstance(format_val, dict):
        base_result["error_code"] = "FFPROBE_PARSE_ERROR"
        base_result["error_message"] = f"ffprobe 'format' field is not a dictionary: {type(format_val).__name__}"
        return base_result
    format_dict = format_val or {}

    streams_val = payload.get("streams")
    if not isinstance(streams_val, list):
        base_result["error_code"] = "FFPROBE_PARSE_ERROR"
        base_result["error_message"] = f"ffprobe 'streams' field is not a list: {type(streams_val).__name__}"
        return base_result

    for s in streams_val:
        if not isinstance(s, dict):
            base_result["error_code"] = "FFPROBE_PARSE_ERROR"
            base_result["error_message"] = f"ffprobe stream item is not a dictionary: {type(s).__name__}"
            return base_result

    video_streams = [s for s in streams_val if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams_val if s.get("codec_type") == "audio"]

    # Extrai duração do contêiner ou do stream de vídeo primário
    format_dur = 0.0
    raw_dur = format_dict.get("duration")
    if raw_dur is not None:
        try:
            format_dur = float(raw_dur)
        except (ValueError, TypeError):
            format_dur = 0.0

    if format_dur <= 0.0 and video_streams:
        v_dur = video_streams[0].get("duration")
        if v_dur is not None:
            try:
                format_dur = float(v_dur)
            except (ValueError, TypeError):
                format_dur = 0.0

    # Extrai tamanho do contêiner
    format_sz = 0
    raw_sz = format_dict.get("size")
    if raw_sz is not None:
        try:
            format_sz = int(raw_sz)
        except (ValueError, TypeError):
            format_sz = 0
    if format_sz <= 0:
        try:
            format_sz = os.path.getsize(file_path)
        except Exception:
            format_sz = 0

    return {
        "valid": True,
        "error_code": None,
        "error_message": None,
        "format": format_dict,
        "video_streams": video_streams,
        "audio_streams": audio_streams,
        "format_duration": format_dur,
        "format_size": format_sz,
    }


def evaluate_final_media_quality(
    video_path: str,
    params: Optional[VideoParams] = None,
    expected_audio_duration: Optional[float] = None,
    subtitle_path: Optional[str] = None,
    task_id: Optional[str] = None,
    video_index: int = 1,
    required: bool = True,
) -> Dict[str, Any]:
    """Avalia o arquivo final renderizado contra todos os requisitos de qualidade.

    Retorna dicionário estruturado:
    {
        "status": "PASS" | "BLOCK",
        "reasons": list[str],
        "metrics": {
            "duration": float,
            "width": int,
            "height": int,
            "aspect_ratio": float,
            "video_codec": str,
            "audio_codec": Optional[str],
            "has_audio": bool,
            "file_size": int,
            "fps": float,
        }
    }
    """
    logger.info(
        f"[MEDIA_GATE][START] task_id={task_id} index={video_index} path={video_path} required={required}"
    )

    reasons: List[str] = []
    empty_metrics = {
        "duration": 0.0,
        "width": 0,
        "height": 0,
        "aspect_ratio": 0.0,
        "video_codec": "unknown",
        "audio_codec": None,
        "has_audio": False,
        "file_size": 0,
        "fps": 0.0,
    }

    # 1. Checagens físicas básicas de arquivo
    if not video_path or not isinstance(video_path, str) or not video_path.strip():
        reasons.append("FINAL_MEDIA_MISSING")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": empty_metrics}

    if not os.path.exists(video_path):
        reasons.append("FINAL_MEDIA_MISSING")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": empty_metrics}

    if not os.path.isfile(video_path):
        reasons.append("FINAL_MEDIA_NOT_A_FILE")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": empty_metrics}

    try:
        file_size = os.path.getsize(video_path)
    except Exception:
        file_size = 0

    if file_size == 0:
        reasons.append("FINAL_MEDIA_EMPTY")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": {**empty_metrics, "file_size": 0}}

    if file_size < MIN_VALID_MEDIA_FILE_BYTES:
        reasons.append("FINAL_MEDIA_TOO_SMALL")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": {**empty_metrics, "file_size": file_size}}

    # 2. Inspeção ffprobe
    probe = probe_media(video_path)
    if not probe["valid"]:
        probe_err = probe.get("error_code") or "FFPROBE_FAILED"
        reasons.append(probe_err)
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": {**empty_metrics, "file_size": file_size}}

    video_streams = probe["video_streams"]
    audio_streams = probe["audio_streams"]
    format_duration = probe["format_duration"]

    # 3. Stream de vídeo
    if not video_streams:
        reasons.append("NO_VIDEO_STREAM")
        logger.error(f"[MEDIA_GATE][BLOCK] task_id={task_id} index={video_index} reasons={reasons}")
        return {"status": "BLOCK", "reasons": reasons, "metrics": {**empty_metrics, "file_size": file_size}}

    v_stream = video_streams[0]
    try:
        width = int(v_stream.get("width") or 0)
        height = int(v_stream.get("height") or 0)
    except (ValueError, TypeError):
        width = 0
        height = 0

    video_codec = str(v_stream.get("codec_name") or "unknown")

    fps_str = str(v_stream.get("r_frame_rate") or v_stream.get("avg_frame_rate") or "30/1")
    fps = 30.0
    try:
        if "/" in fps_str:
            num, den = fps_str.split("/")
            if float(den) > 0:
                fps = float(num) / float(den)
        else:
            fps = float(fps_str)
    except Exception:
        fps = 30.0

    if width <= 0 or height <= 0:
        reasons.append("INVALID_DIMENSIONS")

    # 4. Aspect Ratio e Resolução esperados
    aspect_enum = VideoAspect.portrait
    if params and getattr(params, "video_aspect", None):
        try:
            aspect_enum = VideoAspect(params.video_aspect)
        except Exception:
            aspect_enum = VideoAspect.portrait

    aspect_ratio = round(width / height, 4) if height > 0 else 0.0

    if aspect_enum == VideoAspect.portrait:
        # Orientação vertical (9:16)
        if width >= height or height == 0:
            reasons.append("ASPECT_RATIO_MISMATCH")
        else:
            target_ratio = 9.0 / 16.0  # ~0.5625
            if abs(aspect_ratio - target_ratio) > ASPECT_RATIO_TOLERANCE:
                reasons.append("ASPECT_RATIO_MISMATCH")

        if width < MIN_PORTRAIT_WIDTH or height < MIN_PORTRAIT_HEIGHT:
            reasons.append("RESOLUTION_TOO_LOW")

    elif aspect_enum == VideoAspect.landscape:
        # Orientação horizontal (16:9)
        if width <= height or height == 0:
            reasons.append("ASPECT_RATIO_MISMATCH")
        else:
            target_ratio = 16.0 / 9.0  # ~1.7778
            if abs(aspect_ratio - target_ratio) > ASPECT_RATIO_TOLERANCE:
                reasons.append("ASPECT_RATIO_MISMATCH")

        if width < MIN_LANDSCAPE_WIDTH or height < MIN_LANDSCAPE_HEIGHT:
            reasons.append("RESOLUTION_TOO_LOW")

    elif aspect_enum == VideoAspect.square:
        # Quadrado (1:1)
        target_ratio = 1.0
        if abs(aspect_ratio - target_ratio) > ASPECT_RATIO_TOLERANCE:
            reasons.append("ASPECT_RATIO_MISMATCH")

        if width < MIN_SQUARE_DIMENSION or height < MIN_SQUARE_DIMENSION:
            reasons.append("RESOLUTION_TOO_LOW")

    # 5. Duração do vídeo
    if format_duration <= 0.0 or not math.isfinite(format_duration):
        reasons.append("INVALID_VIDEO_DURATION")
    elif expected_audio_duration is not None and expected_audio_duration > 0:
        dev = abs(format_duration - float(expected_audio_duration))
        max_allowed_dev = max(3.0, float(expected_audio_duration) * 0.15)
        if dev > max_allowed_dev:
            reasons.append("AUDIO_VIDEO_DURATION_MISMATCH")

    # 6. Stream de áudio
    is_narration_expected = True
    if params and getattr(params, "voice_name", None):
        if str(params.voice_name).lower() in ("none", "no-voice", ""):
            is_narration_expected = False

    has_audio = len(audio_streams) > 0
    audio_codec = None
    if has_audio:
        a_stream = audio_streams[0]
        audio_codec = str(a_stream.get("codec_name") or "unknown")
        raw_a_dur = a_stream.get("duration")
        if raw_a_dur is not None and str(raw_a_dur).strip() != "":
            try:
                a_dur = float(raw_a_dur)
                if a_dur <= 0.0 or not math.isfinite(a_dur):
                    reasons.append("INVALID_AUDIO_DURATION")
            except (ValueError, TypeError):
                reasons.append("INVALID_AUDIO_DURATION")
    elif is_narration_expected and required:
        reasons.append("NO_AUDIO_STREAM")

    # 7. Contrato de legenda obrigatória
    if params and getattr(params, "subtitle_required", False) and getattr(params, "subtitle_enabled", True):
        if not subtitle_path or not os.path.isfile(subtitle_path):
            reasons.append("SUBTITLE_ARTIFACT_MISSING")
        else:
            try:
                from app.services import subtitle

                val_srt = subtitle.validate_subtitle_file(subtitle_path)
                if not val_srt.get("valid", False):
                    reasons.append("SUBTITLE_ARTIFACT_MISSING")
            except Exception:
                reasons.append("SUBTITLE_ARTIFACT_MISSING")

    metrics = {
        "duration": round(format_duration, 3) if format_duration > 0 else 0.0,
        "width": width,
        "height": height,
        "aspect_ratio": aspect_ratio,
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "has_audio": has_audio,
        "file_size": file_size,
        "fps": round(fps, 2),
    }

    status = "BLOCK" if reasons else "PASS"

    if status == "PASS":
        logger.info(
            f"[MEDIA_GATE][PASS] task_id={task_id} idx={video_index} dur={metrics['duration']}s "
            f"res={width}x{height} fps={metrics['fps']} size={file_size}b"
        )
    else:
        logger.error(
            f"[MEDIA_GATE][BLOCK] task_id={task_id} idx={video_index} reasons={reasons} "
            f"metrics={metrics}"
        )

    return {
        "status": status,
        "reasons": reasons,
        "metrics": metrics,
    }
