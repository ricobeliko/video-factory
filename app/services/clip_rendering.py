"""
Clip Rendering Service (Fase V11-C — Vertical Clip Rendering).

Responsável pela renderização de segmentos SELECTED em vídeos verticais 9:16 (1080x1920 MP4)
utilizando composições determinísticas (FIT_BLUR e CENTER_CROP), preservação de áudio original,
produção em arquivo temporário com promoção atômica via os.replace, controle de concorrência com
transações curtas BEGIN IMMEDIATE e validação técnica do arquivo gerado.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from loguru import logger

from app.services import clip_mode, operator_console, profile_manager
from app.utils import utils

# Lock de processo para sincronização da seção crítica de início de renderização
_render_creation_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

RENDER_PIPELINE_VERSION = "1"
TARGET_WIDTH = 1080
TARGET_HEIGHT = 1920
DEFAULT_VIDEO_CODEC = "libx264"
DEFAULT_AUDIO_CODEC = "aac"
DEFAULT_AUDIO_BITRATE = "192k"
DEFAULT_FPS = 30.0

RENDER_STATUS_PENDING = "PENDING"
RENDER_STATUS_PROCESSING = "PROCESSING"
RENDER_STATUS_COMPLETED = "COMPLETED"
RENDER_STATUS_FAILED = "FAILED"
RENDER_STATUS_INACTIVE = "INACTIVE"
VALID_RENDER_STATUSES = {
    RENDER_STATUS_PENDING,
    RENDER_STATUS_PROCESSING,
    RENDER_STATUS_COMPLETED,
    RENDER_STATUS_FAILED,
    RENDER_STATUS_INACTIVE,
}

STRATEGY_FIT_BLUR = "fit_blur"
STRATEGY_CENTER_CROP = "center_crop"
DEFAULT_STRATEGY = STRATEGY_FIT_BLUR
VALID_STRATEGIES = {STRATEGY_FIT_BLUR, STRATEGY_CENTER_CROP}

WARN_LOW_SOURCE_RESOLUTION = "LOW_SOURCE_RESOLUTION"
WARN_NO_AUDIO = "NO_AUDIO"
WARN_CENTER_CROP_MAY_CUT_SIDES = "CENTER_CROP_MAY_CUT_SIDES"


# ---------------------------------------------------------------------------
# Exceções Específicas de Renderização
# ---------------------------------------------------------------------------

class ClipRenderError(clip_mode.ClipModeError):
    """Exceção base para erros de renderização de clips."""
    pass


class DuplicateProcessingError(ClipRenderError):
    """Lançada quando já existe uma renderização PROCESSING ativa para o segmento."""
    pass


# ---------------------------------------------------------------------------
# Inicialização do Banco de Dados
# ---------------------------------------------------------------------------

def init_clip_rendering_db(db_path: Optional[str] = None) -> None:
    """Inicializa a tabela clip_renders de forma idempotente e aditiva."""
    clip_mode.init_clip_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_renders (
                id TEXT PRIMARY KEY,
                segment_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                render_strategy TEXT NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                fps REAL NOT NULL,
                video_codec TEXT NOT NULL,
                audio_codec TEXT NOT NULL,
                output_path TEXT NOT NULL,
                file_size_bytes INTEGER,
                duration_seconds REAL,
                status TEXT NOT NULL,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                source_sha256 TEXT NOT NULL,
                render_fingerprint TEXT NOT NULL,
                FOREIGN KEY (segment_id) REFERENCES clip_segments(id),
                FOREIGN KEY (source_id) REFERENCES clip_sources(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_renders_segment ON clip_renders(segment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_renders_source ON clip_renders(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_renders_status ON clip_renders(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_renders_fingerprint ON clip_renders(render_fingerprint);")


# ---------------------------------------------------------------------------
# Helpers Determinísticos e Warnings
# ---------------------------------------------------------------------------

def calculate_render_fps(source_fps: Optional[float]) -> float:
    """
    Determina a taxa de quadros (FPS) determinística para o render:
    - Se source_fps entre 15.0 e 30.0: preserva fps.
    - Se source_fps > 30.0: limita a 30.0.
    - Caso contrário ou ausente: default 30.0.
    """
    if source_fps is None:
        return DEFAULT_FPS
    try:
        val = float(source_fps)
        if 15.0 <= val <= 30.0:
            return round(val, 2)
        if val > 30.0:
            return DEFAULT_FPS
    except (ValueError, TypeError):
        pass
    return DEFAULT_FPS


def compute_render_fingerprint(
    source_sha256: str,
    segment_id: str,
    start_seconds: float,
    end_seconds: float,
    strategy: str,
    width: int = TARGET_WIDTH,
    height: int = TARGET_HEIGHT,
    fps: float = DEFAULT_FPS,
    video_codec: str = DEFAULT_VIDEO_CODEC,
    audio_codec: str = DEFAULT_AUDIO_CODEC,
    pipeline_version: str = RENDER_PIPELINE_VERSION,
) -> str:
    """Gera um fingerprint determinístico SHA-256 para idempotência de renderização."""
    raw = (
        f"{str(source_sha256).strip()}:"
        f"{str(segment_id).strip()}:"
        f"{float(start_seconds):.3f}:"
        f"{float(end_seconds):.3f}:"
        f"{str(strategy).strip().lower()}:"
        f"{int(width)}:"
        f"{int(height)}:"
        f"{float(fps):.2f}:"
        f"{str(video_codec).strip()}:"
        f"{str(audio_codec).strip()}:"
        f"{str(pipeline_version).strip()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def get_render_warnings(source: Dict[str, Any], strategy: str) -> List[str]:
    """Retorna warnings contextuais para o operador (não são falhas impeditivas)."""
    warnings: List[str] = []
    if not source.get("has_audio"):
        warnings.append(WARN_NO_AUDIO)

    width = source.get("width") or 0
    height = source.get("height") or 0
    if (width > 0 and width < 720) or (height > 0 and height < 720):
        warnings.append(WARN_LOW_SOURCE_RESOLUTION)

    if strategy == STRATEGY_CENTER_CROP:
        warnings.append(WARN_CENTER_CROP_MAY_CUT_SIDES)

    return warnings


def _safe_resolve_within(base_dir: str, target_path: str) -> bool:
    """Garante que target_path está estritamente contido dentro de base_dir."""
    try:
        norm_base = os.path.abspath(base_dir)
        norm_target = os.path.abspath(target_path)
        return os.path.commonpath([norm_base]) == os.path.commonpath([norm_base, norm_target])
    except Exception:
        return False


def _build_ffmpeg_filtergraph(
    strategy: str,
    source_width: int,
    source_height: int,
) -> str:
    """
    Constrói a expressão -filter_complex do FFmpeg para a estratégia escolhida:
    - fit_blur: se já for 9:16, scale direto; caso contrário, background 9:16 blurred + foreground intacto centralizado.
    - center_crop: scale para cobrir 1080x1920 e crop centralizado.
    """
    target_w = TARGET_WIDTH
    target_h = TARGET_HEIGHT

    # Se a fonte já for exatamente 9:16 (proporção 0.5625)
    is_already_9_16 = False
    if source_width > 0 and source_height > 0:
        ratio = source_width / source_height
        if abs(ratio - (9.0 / 16.0)) < 0.01:
            is_already_9_16 = True

    if is_already_9_16:
        # Scale direto preservando 1080x1920
        return f"[0:v]scale={target_w}:{target_h}[v]"

    if strategy == STRATEGY_FIT_BLUR:
        # Background: scale para cobrir 1080x1920, crop exato e boxblur
        # Foreground: scale mantendo aspect ratio (decrease)
        # Overlay: centraliza foreground no canvas background
        return (
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},boxblur=20:5[bg];"
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=decrease[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v]"
        )
    elif strategy == STRATEGY_CENTER_CROP:
        # Scale para cobrir 1080x1920 e crop central
        return (
            f"[0:v]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h}[v]"
        )
    else:
        raise ClipRenderError(f"Estratégia de renderização desconhecida: {strategy}")


def validate_rendered_output(
    file_path: str,
    expected_duration: float,
    has_audio_expected: bool,
    expected_dir: str,
    duration_tolerance: float = 2.0,
    timeout_seconds: int = 15,
) -> Dict[str, Any]:
    """
    Valida rigorosamente o arquivo de saída gerado pelo FFmpeg:
    - Deve existir, ser arquivo regular, não ser symlink e ter tamanho > 0.
    - Deve estar estritamente contido no diretório esperado.
    - Inspeção via probe confirma stream de vídeo, resolução 1080x1920 e duração aproximada.
    - Se a fonte possuía áudio, confirma stream de áudio.
    """
    if not os.path.exists(file_path):
        raise ClipRenderError("Arquivo de renderização não foi gerado.")
    if os.path.islink(file_path):
        raise ClipRenderError("Arquivo de renderização é um link simbólico.")
    if not os.path.isfile(file_path):
        raise ClipRenderError("Caminho de renderização não aponta para um arquivo regular.")
    file_size = os.path.getsize(file_path)
    if file_size <= 0:
        raise ClipRenderError("Arquivo de renderização gerado está vazio (0 bytes).")

    if not _safe_resolve_within(expected_dir, file_path):
        raise ClipRenderError("Arquivo de renderização viola limites de isolamento de diretório.")

    # Probe de metadados do vídeo renderizado
    try:
        probe = clip_mode.probe_video_metadata(file_path, timeout_seconds=timeout_seconds)
    except Exception as exc:
        raise ClipRenderError(f"Falha ao inspecionar vídeo renderizado: {exc}") from exc

    width = probe.get("width") or 0
    height = probe.get("height") or 0
    if width != TARGET_WIDTH or height != TARGET_HEIGHT:
        raise ClipRenderError(
            f"Resolução inválida no arquivo renderizado: {width}x{height} (esperado: {TARGET_WIDTH}x{TARGET_HEIGHT})."
        )

    duration = probe.get("duration_seconds") or 0.0
    if duration <= 0:
        raise ClipRenderError("Duração inválida do vídeo renderizado (<= 0).")

    diff = abs(duration - expected_duration)
    if diff > duration_tolerance:
        logger.warning(
            f"[CLIP_RENDERING] Duração do render ({duration:.2f}s) divergiu da duração esperada ({expected_duration:.2f}s) "
            f"além da tolerância ({duration_tolerance:.2f}s)."
        )

    if has_audio_expected and not probe.get("has_audio"):
        raise ClipRenderError("Fonte possui áudio original mas o render gerado não possui stream de áudio.")

    return {
        "width": width,
        "height": height,
        "duration_seconds": duration,
        "file_size_bytes": file_size,
        "video_codec": probe.get("video_codec") or DEFAULT_VIDEO_CODEC,
        "audio_codec": probe.get("audio_codec") if probe.get("has_audio") else "none",
    }


# ---------------------------------------------------------------------------
# Operação de Renderização Principal
# ---------------------------------------------------------------------------

def render_clip_segment(
    segment_id: str,
    strategy: str = DEFAULT_STRATEGY,
    force: bool = False,
    timeout_seconds: int = 300,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Renderiza um segmento SELECTED em vídeo vertical 9:16 (1080x1920 MP4).
    Garante execução exclusiva no nó PRIMARY, validação rigorosa de autorização e estado,
    atomicidade na criação do status PROCESSING, geração via arquivo temporário com
    promoção atômica via os.replace e isolamento de falhas.
    """
    # 1. Guard de Instância PRIMÁRIA
    operator_console.require_primary_instance(db_path=db_path)

    clean_seg_id = str(segment_id or "").strip()
    clean_strat = str(strategy or "").strip().lower()

    if clean_strat not in VALID_STRATEGIES:
        raise ClipRenderError(
            f"Estratégia de renderização '{clean_strat}' inválida. Estratégias suportadas: {sorted(VALID_STRATEGIES)}"
        )

    init_clip_rendering_db(db_path=db_path)

    # 2. Leitura e validação dos dados de entrada (Segment e Source)
    with clip_mode.get_connection(db_path) as conn:
        seg_row = conn.execute(
            """
            SELECT id, source_id, profile_id, status,
                   start_seconds, end_seconds, duration_seconds, title,
                   selection_method, selection_reason
            FROM clip_segments WHERE id = ?
            """,
            (clean_seg_id,),
        ).fetchone()

        if not seg_row:
            raise ClipRenderError(f"Segmento '{clean_seg_id}' não encontrado.")

        seg = dict(seg_row)
        source_id = seg["source_id"]

        source_row = conn.execute(
            """
            SELECT id, profile_id, original_filename, stored_path, sha256,
                   width, height, duration_seconds, fps, video_codec, audio_codec,
                   has_audio, authorization_confirmed, status
            FROM clip_sources WHERE id = ?
            """,
            (source_id,),
        ).fetchone()

        if not source_row:
            raise ClipRenderError(f"Fonte '{source_id}' associada ao segmento não encontrada.")

        source = dict(source_row)

    # 3. Validações de Governança e Regras de Negócio
    if source.get("status") != clip_mode.SOURCE_STATUS_READY:
        raise ClipRenderError(
            f"Fonte '{source_id}' não está no estado READY (status atual: {source.get('status')})."
        )

    if not source.get("authorization_confirmed"):
        raise ClipRenderError(f"Fonte '{source_id}' não possui autorização legal confirmada.")

    if seg.get("status") != clip_mode.SEGMENT_STATUS_SELECTED:
        status_atual = seg.get("status")
        if status_atual == clip_mode.SEGMENT_STATUS_CANDIDATE:
            raise ClipRenderError("Segmento em status CANDIDATE não pode ser renderizado. Selecione o segmento primeiro.")
        if status_atual == clip_mode.SEGMENT_STATUS_REJECTED:
            raise ClipRenderError("Segmento em status REJECTED não pode ser renderizado.")
        raise ClipRenderError(f"Segmento com status '{status_atual}' não pode ser renderizado (exige SELECTED).")

    if seg.get("profile_id") != source.get("profile_id"):
        raise ClipRenderError("Inconsistência de profile_id entre segmento e fonte.")

    stored_video_path = source.get("stored_path")
    if not stored_video_path or not os.path.isfile(stored_video_path):
        raise ClipRenderError(f"Arquivo de vídeo da fonte não encontrado em disco: {stored_video_path}")

    start_seconds = float(seg.get("start_seconds") or 0.0)
    end_seconds = float(seg.get("end_seconds") or 0.0)
    if start_seconds < 0:
        raise ClipRenderError(f"start_seconds inválido ({start_seconds} < 0).")
    if end_seconds <= start_seconds:
        raise ClipRenderError(f"end_seconds ({end_seconds}) deve ser maior que start_seconds ({start_seconds}).")

    source_duration = float(source.get("duration_seconds") or 0.0)
    if source_duration > 0 and end_seconds > (source_duration + 1.0):
        raise ClipRenderError(
            f"end_seconds ({end_seconds:.2f}s) excede a duração da fonte ({source_duration:.2f}s)."
        )

    # Duração calculada pelo backend
    cut_duration = end_seconds - start_seconds

    fps = calculate_render_fps(source.get("fps"))
    has_audio = bool(source.get("has_audio"))
    audio_codec = DEFAULT_AUDIO_CODEC if has_audio else "none"
    source_sha256 = source.get("sha256") or ""
    profile_id = source.get("profile_id")

    fingerprint = compute_render_fingerprint(
        source_sha256=source_sha256,
        segment_id=clean_seg_id,
        start_seconds=start_seconds,
        end_seconds=end_seconds,
        strategy=clean_strat,
        width=TARGET_WIDTH,
        height=TARGET_HEIGHT,
        fps=fps,
        video_codec=DEFAULT_VIDEO_CODEC,
        audio_codec=audio_codec,
        pipeline_version=RENDER_PIPELINE_VERSION,
    )

    # 4. Seção Crítica Atômica: Checagem e Inserção de PROCESSING
    now_iso = datetime.now(timezone.utc).isoformat()
    render_id = f"rend_{uuid.uuid4().hex[:12]}"
    target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "renders", render_id), create=True)
    final_output_path = os.path.join(target_dir, "clip.mp4")

    with _render_creation_lock:
        with clip_mode.get_connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # Verifica se já existe um render em PROCESSING para este segmento
            active_row = conn.execute(
                """
                SELECT id FROM clip_renders
                WHERE segment_id = ? AND status = ?
                """,
                (clean_seg_id, RENDER_STATUS_PROCESSING),
            ).fetchone()

            if active_row:
                conn.execute("ROLLBACK;")
                raise DuplicateProcessingError(
                    f"Já existe uma renderização em processamento para o segmento '{clean_seg_id}' (render_id={active_row['id']})."
                )

            # Se force=False, verificar se podemos reutilizar COMPLETED existente com mesmo fingerprint
            if not force:
                comp_row = conn.execute(
                    """
                    SELECT * FROM clip_renders
                    WHERE render_fingerprint = ? AND status = ?
                    ORDER BY created_at DESC LIMIT 1
                    """,
                    (fingerprint, RENDER_STATUS_COMPLETED),
                ).fetchone()

                if comp_row:
                    comp_dict = dict(comp_row)
                    existing_path = comp_dict.get("output_path")
                    if (
                        existing_path
                        and os.path.exists(existing_path)
                        and not os.path.islink(existing_path)
                        and os.path.isfile(existing_path)
                        and os.path.getsize(existing_path) > 0
                    ):
                        logger.info(f"[CLIP_RENDERING] Reutilizando render COMPLETED existente: {comp_dict['id']}")
                        conn.commit()
                        return comp_dict

            # Insere o novo registro com status PROCESSING
            conn.execute(
                """
                INSERT INTO clip_renders (
                    id, segment_id, source_id, profile_id, render_strategy,
                    width, height, fps, video_codec, audio_codec, output_path,
                    file_size_bytes, duration_seconds, status, started_at,
                    completed_at, created_at, updated_at, error_code,
                    error_message, source_sha256, render_fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    render_id,
                    clean_seg_id,
                    source_id,
                    profile_id,
                    clean_strat,
                    TARGET_WIDTH,
                    TARGET_HEIGHT,
                    fps,
                    DEFAULT_VIDEO_CODEC,
                    audio_codec,
                    final_output_path,
                    None,
                    None,
                    RENDER_STATUS_PROCESSING,
                    now_iso,
                    None,
                    now_iso,
                    now_iso,
                    None,
                    None,
                    source_sha256,
                    fingerprint,
                ),
            )
            conn.commit()

    # 5. Execução do FFmpeg (STRICTLY FORA da transação SQLite)
    temp_filename = f"clip_{uuid.uuid4().hex[:8]}.tmp.mp4"
    temp_output_path = os.path.join(target_dir, temp_filename)

    ffmpeg_bin = utils.get_ffmpeg_binary()
    source_w = int(source.get("width") or 0)
    source_h = int(source.get("height") or 0)
    filtergraph = _build_ffmpeg_filtergraph(clean_strat, source_w, source_h)

    # Montagem de argumentos segura com subprocess (shell=False)
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-ss", f"{start_seconds:.3f}",
        "-t", f"{cut_duration:.3f}",
        "-i", stored_video_path,
        "-filter_complex", filtergraph,
        "-map", "[v]",
    ]

    if has_audio:
        cmd += [
            "-map", "0:a?",
            "-c:a", DEFAULT_AUDIO_CODEC,
            "-b:a", DEFAULT_AUDIO_BITRATE,
        ]
    else:
        cmd += ["-an"]

    cmd += [
        "-c:v", DEFAULT_VIDEO_CODEC,
        "-r", f"{fps:.2f}",
        "-pix_fmt", "yuv420p",
        temp_output_path,
    ]

    logger.info(
        f"[CLIP_RENDERING] Iniciando renderização FFmpeg (id={render_id}, segment={clean_seg_id}, "
        f"strategy={clean_strat}, {cut_duration:.2f}s, temp={temp_filename})"
    )

    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            shell=False,
            check=False,
        )

        if res.returncode != 0:
            err_msg = res.stderr[-800:] if res.stderr else "Erro desconhecido do FFmpeg"
            raise ClipRenderError(f"FFmpeg encerrou com erro (rc={res.returncode}): {err_msg}")

        # 6. Validação do arquivo temporário gerado
        val_data = validate_rendered_output(
            file_path=temp_output_path,
            expected_duration=cut_duration,
            has_audio_expected=has_audio,
            expected_dir=target_dir,
            timeout_seconds=min(30, timeout_seconds),
        )

        # 7. Promoção atômica para o arquivo final via os.replace
        os.replace(temp_output_path, final_output_path)

        completed_iso = datetime.now(timezone.utc).isoformat()
        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_renders
                SET status = ?,
                    completed_at = ?,
                    updated_at = ?,
                    file_size_bytes = ?,
                    duration_seconds = ?,
                    video_codec = ?,
                    audio_codec = ?
                WHERE id = ?
                """,
                (
                    RENDER_STATUS_COMPLETED,
                    completed_iso,
                    completed_iso,
                    val_data["file_size_bytes"],
                    val_data["duration_seconds"],
                    val_data["video_codec"],
                    val_data["audio_codec"],
                    render_id,
                ),
            )
            conn.commit()

        logger.success(f"[CLIP_RENDERING] Renderização concluída com sucesso: {render_id} ({final_output_path})")
        return get_clip_render(render_id, db_path=db_path) or {}

    except Exception as exc:
        err_code = "FFMPEG_TIMEOUT" if isinstance(exc, subprocess.TimeoutExpired) else "RENDER_FAILED"
        err_msg = str(exc)
        logger.error(f"[CLIP_RENDERING] Falha na renderização {render_id}: {err_msg}")

        # Limpeza obrigatória do arquivo temporário em caso de falha
        if os.path.exists(temp_output_path):
            try:
                os.unlink(temp_output_path)
            except Exception as e:
                logger.warning(f"[CLIP_RENDERING] Não foi possível remover arquivo temporário {temp_output_path}: {e}")

        # Atualiza status para FAILED sem alterar o segmento nem a fonte
        failed_iso = datetime.now(timezone.utc).isoformat()
        try:
            with clip_mode.get_connection(db_path) as conn:
                conn.execute(
                    """
                    UPDATE clip_renders
                    SET status = ?,
                        updated_at = ?,
                        error_code = ?,
                        error_message = ?
                    WHERE id = ?
                    """,
                    (
                        RENDER_STATUS_FAILED,
                        failed_iso,
                        err_code,
                        err_msg[:500],
                        render_id,
                    ),
                )
                conn.commit()
        except Exception as db_exc:
            logger.error(f"[CLIP_RENDERING] Falha ao persistir status FAILED no banco: {db_exc}")

        raise


# ---------------------------------------------------------------------------
# Consultas e Utilitários de Consulta
# ---------------------------------------------------------------------------

def get_clip_render(render_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera um render pelo ID."""
    clean_id = str(render_id or "").strip()
    if not clean_id:
        return None
    init_clip_rendering_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        row = conn.execute("SELECT * FROM clip_renders WHERE id = ?", (clean_id,)).fetchone()
        return dict(row) if row else None


def list_clip_renders_for_segment(segment_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista todos os renders de um segmento ordenados do mais recente para o mais antigo."""
    clean_id = str(segment_id or "").strip()
    if not clean_id:
        return []
    init_clip_rendering_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM clip_renders WHERE segment_id = ? ORDER BY created_at DESC",
            (clean_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def list_clip_renders_for_source(source_id: str, db_path: Optional[str] = None) -> List[Dict[str, Any]]:
    """Lista todos os renders de uma fonte ordenados do mais recente para o mais antigo."""
    clean_id = str(source_id or "").strip()
    if not clean_id:
        return []
    init_clip_rendering_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        rows = conn.execute(
            "SELECT * FROM clip_renders WHERE source_id = ? ORDER BY created_at DESC",
            (clean_id,),
        ).fetchall()
        return [dict(r) for r in rows]


def get_latest_completed_render(segment_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Retorna o render COMPLETED mais recente de um segmento, se existir."""
    clean_id = str(segment_id or "").strip()
    if not clean_id:
        return None
    init_clip_rendering_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_renders
            WHERE segment_id = ? AND status = ?
            ORDER BY created_at DESC LIMIT 1
            """,
            (clean_id, RENDER_STATUS_COMPLETED),
        ).fetchone()
        return dict(row) if row else None
