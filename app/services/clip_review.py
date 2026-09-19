"""
Clip Review Service (Fase V11-D — Captions & Final Review Polish).

Responsável pela fusão por burn-in da faixa de legendas (ASS/SRT) no vídeo vertical (V11-C),
gerando o artefato final em storage/clip_sources/<source_id>/reviews/<review_id>/clip_final.mp4.
Inclui promoção atômica, isolamento de falhas, idempotência e workflow de governança
(aprovação/rejeição pelo operador primário e helper de artefato aprovado para publicação).
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import sqlite3
import subprocess
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from loguru import logger

from app.services import (
    clip_captions,
    clip_mode,
    clip_rendering,
    operator_console,
    profile_manager,
)
from app.utils import utils

# Lock de processo para sincronização da seção crítica de review
_review_creation_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

REVIEW_PIPELINE_VERSION = "1"

REVIEW_OUTPUT_STATUS_PENDING = "PENDING"
REVIEW_OUTPUT_STATUS_PROCESSING = "PROCESSING"
REVIEW_OUTPUT_STATUS_COMPLETED = "COMPLETED"
REVIEW_OUTPUT_STATUS_FAILED = "FAILED"
REVIEW_OUTPUT_STATUS_INACTIVE = "INACTIVE"
VALID_REVIEW_OUTPUT_STATUSES = {
    REVIEW_OUTPUT_STATUS_PENDING,
    REVIEW_OUTPUT_STATUS_PROCESSING,
    REVIEW_OUTPUT_STATUS_COMPLETED,
    REVIEW_OUTPUT_STATUS_FAILED,
    REVIEW_OUTPUT_STATUS_INACTIVE,
}

REVIEW_STATUS_PENDING_REVIEW = "PENDING_REVIEW"
REVIEW_STATUS_APPROVED = "APPROVED"
REVIEW_STATUS_REJECTED = "REJECTED"
VALID_REVIEW_STATUSES = {
    REVIEW_STATUS_PENDING_REVIEW,
    REVIEW_STATUS_APPROVED,
    REVIEW_STATUS_REJECTED,
}

APPROVAL_POLICY = "SINGLE_ACTIVE_APPROVED_PER_SEGMENT"

# ---------------------------------------------------------------------------
# Exceções Específicas de Revisão
# ---------------------------------------------------------------------------

class ClipReviewError(clip_mode.ClipModeError):
    """Exceção base para erros do pipeline de revisão de clips."""
    pass


class DuplicateReviewProcessingError(ClipReviewError):
    """Lançada quando já existe uma geração de review em PROCESSING ativa."""
    pass


# ---------------------------------------------------------------------------
# Inicialização do Banco de Dados
# ---------------------------------------------------------------------------

def init_clip_review_db(db_path: Optional[str] = None) -> None:
    """Inicializa a tabela clip_review_outputs de forma idempotente e aditiva."""
    clip_mode.init_clip_db(db_path=db_path)
    clip_rendering.init_clip_rendering_db(db_path=db_path)
    clip_captions.init_clip_captions_db(db_path=db_path)

    with clip_mode.get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_review_outputs (
                id TEXT PRIMARY KEY,
                render_id TEXT NOT NULL,
                caption_track_id TEXT NOT NULL,
                segment_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                output_path TEXT NOT NULL,
                file_size_bytes INTEGER,
                duration_seconds REAL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                status TEXT NOT NULL,
                review_status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                completed_at TEXT,
                error_code TEXT,
                error_message TEXT,
                fingerprint TEXT NOT NULL,
                FOREIGN KEY (render_id) REFERENCES clip_renders(id),
                FOREIGN KEY (caption_track_id) REFERENCES clip_caption_tracks(id),
                FOREIGN KEY (segment_id) REFERENCES clip_segments(id),
                FOREIGN KEY (source_id) REFERENCES clip_sources(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_reviews_segment ON clip_review_outputs(segment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_reviews_source ON clip_review_outputs(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_reviews_fingerprint ON clip_review_outputs(fingerprint);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_reviews_status ON clip_review_outputs(review_status);")


# ---------------------------------------------------------------------------
# Helpers de Fingerprint e Validação
# ---------------------------------------------------------------------------

def compute_review_fingerprint(
    render_id: str,
    caption_track_id: str,
    pipeline_version: str = REVIEW_PIPELINE_VERSION,
) -> str:
    """Gera um hash SHA-256 determinístico para garantir idempotência de outputs de review."""
    raw = f"{str(render_id).strip()}:{str(caption_track_id).strip()}:{str(pipeline_version).strip()}"
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _safe_resolve_within(base_dir: str, target_path: str) -> bool:
    """Garante que target_path está estritamente contido dentro de base_dir."""
    try:
        norm_base = os.path.abspath(base_dir)
        norm_target = os.path.abspath(target_path)
        return os.path.commonpath([norm_base]) == os.path.commonpath([norm_base, norm_target])
    except Exception:
        return False


def _escape_path_for_ffmpeg_filter(path_str: str) -> str:
    """Escapa caminhos de arquivos para inclusão em filtros FFmpeg (ass/subtitles) no Windows."""
    norm = path_str.replace("\\", "/")
    # Escapa os dois pontos de letras de unidade (ex: D: -> D\:)
    escaped = norm.replace(":", "\\:")
    return escaped


# ---------------------------------------------------------------------------
# Pipeline de Burn-In de Legendas e Geração de Review Final
# ---------------------------------------------------------------------------

def create_clip_review_output(
    render_id: str,
    caption_track_id: str,
    force: bool = False,
    timeout_seconds: int = 180,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executa o burn-in determinístico de uma faixa de legendas sobre o render base vertical,
    produzindo o arquivo de vídeo final para revisão do operador.
    Requer role PRIMARY. Gravação atômica com promoção via os.replace.
    """
    # 1. Checagem de Governança e Permissões
    operator_console.require_primary_instance(db_path=db_path)

    clean_render_id = str(render_id or "").strip()
    clean_caption_id = str(caption_track_id or "").strip()

    if not clean_render_id:
        raise ClipReviewError("render_id não pode ser vazio.")
    if not clean_caption_id:
        raise ClipReviewError("caption_track_id não pode ser vazio.")

    init_clip_review_db(db_path=db_path)

    # 2. Carrega e Valida Render Base
    render = clip_rendering.get_clip_render(clean_render_id, db_path=db_path)
    if not render:
        raise ClipReviewError(f"Render base '{clean_render_id}' não encontrado.")

    if render.get("status") != clip_rendering.RENDER_STATUS_COMPLETED:
        raise ClipReviewError(
            f"Render base '{clean_render_id}' não está no estado COMPLETED (status atual: {render.get('status')})."
        )

    base_video_path = render.get("output_path")
    if not base_video_path or not os.path.isfile(base_video_path):
        raise ClipReviewError(f"Arquivo de vídeo do render base não encontrado em disco: {base_video_path}")

    # 3. Carrega e Valida Faixa de Legendas
    caption_track = clip_captions.get_caption_track(clean_caption_id, db_path=db_path)
    if not caption_track:
        raise ClipReviewError(f"Faixa de legendas '{clean_caption_id}' não encontrada.")

    if caption_track.get("status") != clip_captions.CAPTION_STATUS_COMPLETED:
        raise ClipReviewError(
            f"Faixa de legendas '{clean_caption_id}' não está no estado COMPLETED "
            f"(status atual: {caption_track.get('status')})."
        )

    # Validação de consistência entre render e legenda
    if render.get("segment_id") != caption_track.get("segment_id"):
        raise ClipReviewError("Inconsistência: render e faixa de legendas pertencem a segmentos distintos.")
    if render.get("source_id") != caption_track.get("source_id"):
        raise ClipReviewError("Inconsistência: render e faixa de legendas pertencem a fontes distintas.")
    if render.get("profile_id") != caption_track.get("profile_id"):
        raise ClipReviewError("Inconsistência de profile_id entre render e faixa de legendas.")

    segment_id = render["segment_id"]
    source_id = render["source_id"]
    profile_id = render["profile_id"]

    # Determina arquivo de legenda a utilizar (preferência ASS, fallback SRT)
    ass_file = caption_track.get("ass_path")
    srt_file = caption_track.get("srt_path")
    subtitle_file_to_use = None
    use_ass = False

    if ass_file and os.path.isfile(ass_file):
        subtitle_file_to_use = ass_file
        use_ass = True
    elif srt_file and os.path.isfile(srt_file):
        subtitle_file_to_use = srt_file
        use_ass = False
    else:
        raise ClipReviewError("Nenhum arquivo de legenda (ASS ou SRT) encontrado em disco.")

    # 4. Cálculo do Fingerprint e Idempotência
    fingerprint = compute_review_fingerprint(clean_render_id, clean_caption_id, REVIEW_PIPELINE_VERSION)

    if not force:
        with clip_mode.get_connection(db_path) as conn:
            existing = conn.execute(
                """
                SELECT * FROM clip_review_outputs
                WHERE fingerprint = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (fingerprint, REVIEW_OUTPUT_STATUS_COMPLETED),
            ).fetchone()

            if existing:
                ex_dict = dict(existing)
                if os.path.isfile(ex_dict["output_path"]):
                    logger.info(f"Reutilizando review final existente: {ex_dict['id']}")
                    return ex_dict

    # 5. Seção Crítica: Verificação de PROCESSING e Inserção Atômica
    review_id = f"rev_{uuid.uuid4().hex[:12]}"
    target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "reviews", review_id), create=True)
    final_output_path = os.path.join(target_dir, "clip_final.mp4")
    temp_filename = f"clip_final_{uuid.uuid4().hex[:8]}.tmp.mp4"
    temp_output_path = os.path.join(target_dir, temp_filename)
    now_iso = datetime.now(timezone.utc).isoformat()

    with _review_creation_lock:
        with clip_mode.get_connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")

            active = conn.execute(
                """
                SELECT id FROM clip_review_outputs
                WHERE render_id = ? AND caption_track_id = ? AND status = ?
                """,
                (clean_render_id, clean_caption_id, REVIEW_OUTPUT_STATUS_PROCESSING),
            ).fetchone()

            if active:
                raise DuplicateReviewProcessingError(
                    f"Já existe uma composição de review em processamento (ID: {active['id']}) para estes parâmetros."
                )

            conn.execute(
                """
                INSERT INTO clip_review_outputs (
                    id, render_id, caption_track_id, segment_id, source_id, profile_id,
                    output_path, file_size_bytes, duration_seconds, width, height,
                    status, review_status, created_at, updated_at, completed_at,
                    error_code, error_message, fingerprint
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    review_id,
                    clean_render_id,
                    clean_caption_id,
                    segment_id,
                    source_id,
                    profile_id,
                    final_output_path,
                    None,
                    None,
                    clip_rendering.TARGET_WIDTH,
                    clip_rendering.TARGET_HEIGHT,
                    REVIEW_OUTPUT_STATUS_PROCESSING,
                    REVIEW_STATUS_PENDING_REVIEW,
                    now_iso,
                    now_iso,
                    None,
                    None,
                    None,
                    fingerprint,
                ),
            )
            conn.commit()

    # 6. Execução do FFmpeg para Burn-in (ESTRITAMENTE FORA da transação)
    try:
        ffmpeg_bin = utils.get_ffmpeg_binary()
        escaped_sub_path = _escape_path_for_ffmpeg_filter(subtitle_file_to_use)

        if use_ass:
            filter_str = f"ass='{escaped_sub_path}'"
        else:
            filter_str = f"subtitles='{escaped_sub_path}'"

        # Inspeciona áudio do render base para decidir se preserva ou usa -an
        probe_base = clip_mode.probe_video_metadata(base_video_path)
        has_audio = bool(probe_base.get("has_audio"))

        cmd = [
            ffmpeg_bin,
            "-hide_banner",
            "-y",
            "-i", base_video_path,
            "-vf", filter_str,
            "-c:v", "libx264",
            "-pix_fmt", "yuv420p",
        ]

        if has_audio:
            cmd += [
                "-c:a", "aac",
                "-b:a", "192k",
            ]
        else:
            cmd += ["-an"]

        cmd.append(temp_output_path)

        logger.info(f"Iniciando FFmpeg burn-in para review {review_id}...")
        proc = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            shell=False,
            timeout=timeout_seconds,
        )

        if proc.returncode != 0:
            err_snippet = (proc.stderr or "")[-800:]
            raise ClipReviewError(f"FFmpeg encerrou com código {proc.returncode}: {err_snippet}")

        # 7. Validação Técnica do Arquivo Temporário
        expected_dur = float(render.get("duration_seconds") or 0.0)
        clip_rendering.validate_rendered_output(
            temp_output_path,
            expected_duration=expected_dur,
            has_audio_expected=has_audio,
            expected_dir=target_dir,
        )

        # 8. Promoção Atômica via os.replace
        os.replace(temp_output_path, final_output_path)

        # Inspeciona arquivo final promovido
        probe_final = clip_mode.probe_video_metadata(final_output_path)
        file_size = os.path.getsize(final_output_path)
        final_dur = float(probe_final.get("duration_seconds") or expected_dur)
        completed_iso = datetime.now(timezone.utc).isoformat()

        # 9. Atualização no SQLite para COMPLETED
        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_review_outputs
                SET status = ?, file_size_bytes = ?, duration_seconds = ?,
                    completed_at = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    REVIEW_OUTPUT_STATUS_COMPLETED,
                    file_size,
                    final_dur,
                    completed_iso,
                    completed_iso,
                    review_id,
                ),
            )
            conn.commit()

        logger.info(f"Review final {review_id} gerado com sucesso ({file_size} bytes, {final_dur:.2f}s).")
        return get_clip_review(review_id, db_path=db_path)  # type: ignore

    except Exception as exc:
        logger.error(f"Falha na geração do review final {review_id}: {exc}", exc_info=True)
        # Limpa arquivo temporário em caso de falha
        if os.path.isfile(temp_output_path):
            try:
                os.remove(temp_output_path)
            except Exception:
                pass

        error_code = "FFMPEG_ERROR"
        if isinstance(exc, subprocess.TimeoutExpired):
            error_code = "FFMPEG_TIMEOUT"
        elif isinstance(exc, clip_rendering.ClipRenderError):
            error_code = "VALIDATION_ERROR"
        elif isinstance(exc, ClipReviewError) and "FFmpeg encerrou" not in str(exc):
            error_code = "VALIDATION_ERROR"

        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_review_outputs
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    REVIEW_OUTPUT_STATUS_FAILED,
                    error_code,
                    str(exc)[:500],
                    datetime.now(timezone.utc).isoformat(),
                    review_id,
                ),
            )
            conn.commit()

        raise


# ---------------------------------------------------------------------------
# Workflow de Revisão (Aprovação / Rejeição)
# ---------------------------------------------------------------------------

def approve_clip_review(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Aprova um artefato de review COMPLETED. Apenas o operador PRIMARY pode aprovar.
    Política: apenas UM review APPROVED ativo por segmento. Qualquer review aprovado
    anterior para este segmento tem seu review_status alterado para PENDING_REVIEW histórico.
    NÃO realiza publicação automática.
    """
    operator_console.require_primary_instance(db_path=db_path)

    clean_id = str(review_id or "").strip()
    if not clean_id:
        raise ClipReviewError("review_id não pode ser vazio.")

    init_clip_review_db(db_path=db_path)

    with clip_mode.get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT id, segment_id, status, review_status
            FROM clip_review_outputs
            WHERE id = ?
            """,
            (clean_id,),
        ).fetchone()

        if not row:
            raise ClipReviewError(f"Review '{clean_id}' não encontrado.")

        if row["status"] != REVIEW_OUTPUT_STATUS_COMPLETED:
            raise ClipReviewError(
                f"Apenas reviews em status COMPLETED podem ser aprovados (status atual: {row['status']})."
            )

        segment_id = row["segment_id"]
        now_iso = datetime.now(timezone.utc).isoformat()

        # Desativa qualquer outro review aprovado anteriormente para este segmento
        conn.execute(
            """
            UPDATE clip_review_outputs
            SET review_status = ?, updated_at = ?
            WHERE segment_id = ? AND review_status = ? AND id != ?
            """,
            (
                REVIEW_STATUS_PENDING_REVIEW,
                now_iso,
                segment_id,
                REVIEW_STATUS_APPROVED,
                clean_id,
            ),
        )

        # Marca este review como APPROVED
        conn.execute(
            """
            UPDATE clip_review_outputs
            SET review_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                REVIEW_STATUS_APPROVED,
                now_iso,
                clean_id,
            ),
        )
        conn.commit()

    logger.info(f"Review {clean_id} aprovado com sucesso para o segmento {segment_id}.")
    return get_clip_review(clean_id, db_path=db_path)  # type: ignore


def reject_clip_review(
    review_id: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Rejeita um artefato de review COMPLETED. Apenas o operador PRIMARY pode rejeitar.
    Não apaga o arquivo físico em disco. Apenas altera o status de revisão para REJECTED.
    """
    operator_console.require_primary_instance(db_path=db_path)

    clean_id = str(review_id or "").strip()
    if not clean_id:
        raise ClipReviewError("review_id não pode ser vazio.")

    init_clip_review_db(db_path=db_path)

    with clip_mode.get_connection(db_path) as conn:
        conn.execute("BEGIN IMMEDIATE")

        row = conn.execute(
            """
            SELECT id, status, review_status
            FROM clip_review_outputs
            WHERE id = ?
            """,
            (clean_id,),
        ).fetchone()

        if not row:
            raise ClipReviewError(f"Review '{clean_id}' não encontrado.")

        now_iso = datetime.now(timezone.utc).isoformat()
        conn.execute(
            """
            UPDATE clip_review_outputs
            SET review_status = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                REVIEW_STATUS_REJECTED,
                now_iso,
                clean_id,
            ),
        )
        conn.commit()

    logger.info(f"Review {clean_id} rejeitado pelo operador.")
    return get_clip_review(clean_id, db_path=db_path)  # type: ignore


# ---------------------------------------------------------------------------
# Helper de Artefato Final Aprovado (Rastreabilidade e Publicação Futura)
# ---------------------------------------------------------------------------

def get_approved_clip_artifact(
    segment_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """
    Retorna os detalhes do artefato final aprovado mais recente para um segmento.
    Utilizado para inspeção e integração com futuros pipelines de publicação.
    """
    clean_seg_id = str(segment_id or "").strip()
    if not clean_seg_id:
        return None

    init_clip_review_db(db_path=db_path)

    with clip_mode.get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT r.*, c.style as caption_style
            FROM clip_review_outputs r
            LEFT JOIN clip_caption_tracks c ON r.caption_track_id = c.id
            WHERE r.segment_id = ?
              AND r.review_status = ?
              AND r.status = ?
            ORDER BY r.updated_at DESC
            LIMIT 1
            """,
            (
                clean_seg_id,
                REVIEW_STATUS_APPROVED,
                REVIEW_OUTPUT_STATUS_COMPLETED,
            ),
        ).fetchone()

        if not row:
            return None

        r = dict(row)
        return {
            "review_id": r["id"],
            "output_path": r["output_path"],
            "source_id": r["source_id"],
            "segment_id": r["segment_id"],
            "profile_id": r["profile_id"],
            "duration_seconds": r["duration_seconds"],
            "resolution": f"{r['width']}x{r['height']}",
            "caption_style": r.get("caption_style") or "CLEAN",
            "created_at": r["created_at"],
        }


# ---------------------------------------------------------------------------
# Consultas de Review Outputs
# ---------------------------------------------------------------------------

def get_clip_review(review_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera um review output pelo ID."""
    clean_id = str(review_id or "").strip()
    if not clean_id:
        return None

    init_clip_review_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_review_outputs WHERE id = ?
            """,
            (clean_id,),
        ).fetchone()

        if not row:
            return None
        return dict(row)


def list_clip_reviews_for_segment(
    segment_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista todos os review outputs associados a um segmento."""
    clean_id = str(segment_id or "").strip()
    if not clean_id:
        return []

    init_clip_review_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_review_outputs
            WHERE segment_id = ?
            ORDER BY created_at DESC
            """,
            (clean_id,),
        ).fetchall()

        return [dict(r) for r in rows]
