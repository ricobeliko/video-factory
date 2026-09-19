"""
Clip Mode Service (Fase V11-A — Clip Mode Foundation).

Responsável pela importação e catalogação de vídeos-fonte locais autorizados,
validação técnica da mídia, deduplicação por SHA-256, persistência de metadados,
rastreabilidade de autorização legal e criação manual de segmentos/cortes para
reaproveitamento em formato vertical.
"""
from contextlib import contextmanager
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import subprocess
from typing import Any, Dict, List, Optional, Tuple
import uuid

from loguru import logger

from app.services import operator_console, profile_manager
from app.utils import utils

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

SUPPORTED_VIDEO_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}

VALID_SOURCE_ORIGINS = {
    "owned",
    "licensed",
    "permission",
    "public_domain",
    "other_authorized",
}

SOURCE_ORIGIN_DESCRIPTIONS = {
    "owned": "Conteúdo produzido/pertencente ao operador.",
    "licensed": "Uso permitido por licença.",
    "permission": "Autorização explícita do detentor.",
    "public_domain": "Conteúdo declarado pelo operador como domínio público.",
    "other_authorized": "Outro fundamento de autorização informado pelo operador.",
}

SOURCE_STATUS_READY = "READY"
SOURCE_STATUS_INVALID = "INVALID"
SOURCE_STATUS_INACTIVE = "INACTIVE"
VALID_SOURCE_STATUSES = {SOURCE_STATUS_READY, SOURCE_STATUS_INVALID, SOURCE_STATUS_INACTIVE}

SEGMENT_STATUS_CANDIDATE = "CANDIDATE"
SEGMENT_STATUS_SELECTED = "SELECTED"
SEGMENT_STATUS_REJECTED = "REJECTED"
VALID_SEGMENT_STATUSES = {SEGMENT_STATUS_CANDIDATE, SEGMENT_STATUS_SELECTED, SEGMENT_STATUS_REJECTED}

SELECTION_METHOD_MANUAL = "manual"
VALID_SELECTION_METHODS = {
    SELECTION_METHOD_MANUAL,
    "transcript",
    "heuristic",
    "ai_assisted",
}

# Limites de duração recomendados para vídeos curtos (para alertas, não bloqueio)
SHORT_FORM_MIN_RECOMMENDED_DURATION = 5.0
SHORT_FORM_MAX_RECOMMENDED_DURATION = 180.0


class ClipModeError(Exception):
    """Exceção base para erros do Clip Mode."""
    pass


class ClipValidationError(ClipModeError):
    """Erro de validação técnica ou semântica do arquivo de vídeo."""
    pass


class ClipAuthorizationError(ClipModeError):
    """Erro de autorização de uso do conteúdo."""
    pass


# ---------------------------------------------------------------------------
# Conexão e Banco de Dados
# ---------------------------------------------------------------------------

def get_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho do banco SQLite oficial."""
    if custom_path:
        return custom_path
    return os.path.join(utils.root_dir(), "storage", "video_factory.db")


@contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o banco SQLite em modo WAL garantindo integridade e concorrência."""
    path = get_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=30000;")
        conn.execute("PRAGMA foreign_keys = ON;")
        with conn:
            yield conn
    finally:
        conn.close()


def init_clip_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas clip_sources e clip_segments de forma idempotente e aditiva."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_sources (
                id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                original_filename TEXT NOT NULL,
                stored_filename TEXT NOT NULL,
                stored_path TEXT NOT NULL,
                sha256 TEXT UNIQUE NOT NULL,
                file_size_bytes INTEGER NOT NULL,
                duration_seconds REAL NOT NULL,
                width INTEGER NOT NULL,
                height INTEGER NOT NULL,
                fps REAL NOT NULL,
                video_codec TEXT NOT NULL,
                audio_codec TEXT,
                has_audio INTEGER NOT NULL,
                source_origin TEXT NOT NULL,
                authorization_confirmed INTEGER NOT NULL,
                authorization_note TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_sources_sha256 ON clip_sources(sha256);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_sources_profile ON clip_sources(profile_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_sources_status ON clip_sources(status);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_segments (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                duration_seconds REAL NOT NULL,
                title TEXT,
                selection_method TEXT NOT NULL,
                selection_reason TEXT,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (source_id) REFERENCES clip_sources(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_segments_source ON clip_segments(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_segments_profile ON clip_segments(profile_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_segments_status ON clip_segments(status);")


# ---------------------------------------------------------------------------
# Utilitários de Hash, Path e Probe
# ---------------------------------------------------------------------------

def calculate_file_sha256(file_path: str) -> str:
    """Calcula o hash SHA-256 de um arquivo de mídia em blocos de 64KB."""
    sha = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            sha.update(chunk)
    return sha.hexdigest()


def sanitize_clip_filename(filename: str) -> str:
    """Sanitiza o nome de arquivo original para armazenamento de metadados e prevenção de path traversal."""
    if not filename:
        return "video.mp4"
    safe = filename.replace("\\", "/").split("/")[-1].strip()
    safe = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", safe)
    if not safe or safe in {".", ".."}:
        return "video.mp4"
    return safe


def probe_video_metadata(file_path: str, timeout_seconds: int = 30) -> Dict[str, Any]:
    """
    Inspeciona o arquivo de vídeo usando ffprobe (quando disponível) ou
    fallback nativo do FFmpeg (-hide_banner -i).
    Extrai: duration_seconds, width, height, fps, video_codec, audio_codec, has_audio.
    Rejeita explicitamente links simbólicos.
    """
    if os.path.islink(file_path):
        raise ClipValidationError("Links simbólicos (symlinks) não são permitidos para inspeção.")

    if not os.path.isfile(file_path) or os.path.getsize(file_path) <= 0:
        raise ClipValidationError("Arquivo de vídeo inexistente ou vazio.")

    # 1. Tentar ffprobe se disponível no sistema ou configurado
    ffprobe_bin = shutil.which("ffprobe") or os.environ.get("FFPROBE_PATH")
    if ffprobe_bin:
        try:
            cmd = [
                ffprobe_bin,
                "-v", "quiet",
                "-print_format", "json",
                "-show_format",
                "-show_streams",
                file_path,
            ]
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False)
            if res.returncode == 0 and res.stdout.strip():
                data = json.loads(res.stdout)
                streams = data.get("streams", [])
                video_stream = next((s for s in streams if s.get("codec_type") == "video"), None)
                audio_stream = next((s for s in streams if s.get("codec_type") == "audio"), None)

                if not video_stream:
                    raise ClipValidationError("Arquivo não contém stream de vídeo válido.")

                duration_val = float(data.get("format", {}).get("duration") or video_stream.get("duration") or 0.0)
                width = int(video_stream.get("width") or 0)
                height = int(video_stream.get("height") or 0)
                fps_str = video_stream.get("r_frame_rate") or video_stream.get("avg_frame_rate") or "30/1"
                try:
                    num, den = fps_str.split("/")
                    fps = float(num) / float(den) if float(den) != 0 else 30.0
                except Exception:
                    fps = 30.0

                video_codec = str(video_stream.get("codec_name") or "unknown")
                audio_codec = str(audio_stream.get("codec_name")) if audio_stream else None
                has_audio = audio_stream is not None

                return {
                    "duration_seconds": duration_val,
                    "width": width,
                    "height": height,
                    "fps": round(fps, 2),
                    "video_codec": video_codec,
                    "audio_codec": audio_codec,
                    "has_audio": has_audio,
                }
        except subprocess.TimeoutExpired as exc:
            raise ClipValidationError(f"Timeout ao inspecionar mídia com ffprobe: {exc}") from exc
        except Exception as exc:
            logger.debug(f"[CLIP_MODE] ffprobe falhou ou retornou inválido ({exc}), tentando fallback FFmpeg.")

    # 2. Fallback robusto via FFmpeg (-hide_banner -i)
    ffmpeg_bin = utils.get_ffmpeg_binary()
    try:
        cmd = [ffmpeg_bin, "-hide_banner", "-i", file_path]
        res = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout_seconds, check=False, errors="replace")
        output = res.stderr or ""
    except subprocess.TimeoutExpired as exc:
        raise ClipValidationError(f"Timeout ao inspecionar mídia com FFmpeg: {exc}") from exc
    except Exception as exc:
        raise ClipValidationError(f"Erro ao executar FFmpeg para inspeção: {exc}") from exc

    # Parse de Duração
    dur_match = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", output)
    if not dur_match:
        raise ClipValidationError("Não foi possível identificar a duração do vídeo via FFmpeg.")
    h, m, s = float(dur_match.group(1)), float(dur_match.group(2)), float(dur_match.group(3))
    duration_seconds = round(h * 3600 + m * 60 + s, 3)

    # Parse de Streams
    video_codec = None
    width = 0
    height = 0
    fps = 30.0
    audio_codec = None
    has_audio = False

    for line in output.splitlines():
        if ": Video:" in line:
            m_vcodec = re.search(r": Video:\s*([a-zA-Z0-9_-]+)", line)
            if m_vcodec:
                video_codec = m_vcodec.group(1)
            m_res = re.search(r"(\d{2,5})x(\d{2,5})", line)
            if m_res:
                width = int(m_res.group(1))
                height = int(m_res.group(2))
            m_fps = re.search(r"(\d+(?:\.\d+)?)\s*fps", line)
            if m_fps:
                fps = float(m_fps.group(1))
            elif m_tbr := re.search(r"(\d+(?:\.\d+)?)\s*tbr", line):
                fps = float(m_tbr.group(1))
        elif ": Audio:" in line:
            has_audio = True
            m_acodec = re.search(r": Audio:\s*([a-zA-Z0-9_-]+)", line)
            if m_acodec:
                audio_codec = m_acodec.group(1)

    if not video_codec or width <= 0 or height <= 0:
        raise ClipValidationError("Arquivo não contém stream de vídeo com dimensões válidas.")

    return {
        "duration_seconds": duration_seconds,
        "width": width,
        "height": height,
        "fps": round(fps, 2),
        "video_codec": video_codec,
        "audio_codec": audio_codec,
        "has_audio": has_audio,
    }


# ---------------------------------------------------------------------------
# Importação e Gestão de Fontes (Clip Sources)
# ---------------------------------------------------------------------------

def import_clip_source(
    file_path: str,
    source_origin: str,
    authorization_confirmed: bool,
    profile_id: Optional[str] = None,
    authorization_note: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Importa um vídeo local como fonte autorizada para Clip Mode:
    - Guarda PRIMARY estrita
    - Validação de autorização explícita
    - Validação técnica e de extensão
    - Deduplicação por SHA-256 (não duplica arquivo nem registro)
    - Cópia segura para storage/clip_sources/<source_id>/source.<ext>
    - Preserva arquivo original intacto
    """
    # 1. Guarda PRIMARY
    if not operator_console.is_primary_instance(db_path=db_path):
        raise PermissionError("Instância em modo SECONDARY (VIEW ONLY). Importação bloqueada.")

    # 2. Validação de Autorização Obrigatória
    if not authorization_confirmed:
        raise ClipAuthorizationError(
            "Autorização obrigatória: a importação exige confirmação explícita de direitos (authorization_confirmed=True)."
        )

    clean_origin = (source_origin or "").strip().lower()
    if clean_origin not in VALID_SOURCE_ORIGINS:
        raise ClipAuthorizationError(
            f"Origem da fonte inválida ('{source_origin}'). Valores aceitos: {sorted(list(VALID_SOURCE_ORIGINS))}."
        )

    # 3. Validação do Profile
    clean_profile_id = (profile_id or profile_manager.DEFAULT_PROFILE_ID).strip()
    profile_manager.init_profile_db(db_path=db_path)
    prof = profile_manager.get_profile(clean_profile_id, db_path=db_path)
    if not prof:
        clean_profile_id = profile_manager.DEFAULT_PROFILE_ID

    # 4. Validação de Path e Arquivo
    if not file_path or not isinstance(file_path, str):
        raise ClipValidationError("Caminho do arquivo de vídeo inválido ou não fornecido.")

    abs_path = os.path.abspath(file_path.strip())

    # Bloqueio explícito de links simbólicos antes de hash/probe/copy
    if os.path.islink(abs_path) or os.path.islink(file_path.strip()):
        raise ClipValidationError("Links simbólicos (symlinks) não são permitidos como arquivo de entrada.")

    if not os.path.exists(abs_path) or not os.path.isfile(abs_path):
        raise ClipValidationError(f"Arquivo não encontrado ou não é um arquivo regular: {file_path}")

    file_size = os.path.getsize(abs_path)
    if file_size <= 0:
        raise ClipValidationError("Arquivo de vídeo está vazio (tamanho 0 bytes).")

    ext = Path(abs_path).suffix.lower()
    if ext not in SUPPORTED_VIDEO_EXTENSIONS:
        raise ClipValidationError(
            f"Extensão de arquivo '{ext}' não suportada. Extensões aceitas: {sorted(list(SUPPORTED_VIDEO_EXTENSIONS))}."
        )

    original_filename = sanitize_clip_filename(os.path.basename(abs_path))

    # 5. Cálculo de SHA-256 e Deduplicação
    sha256_hash = calculate_file_sha256(abs_path)

    init_clip_db(db_path=db_path)

    with get_connection(db_path) as conn:
        cursor = conn.execute("SELECT * FROM clip_sources WHERE sha256 = ?", (sha256_hash,))
        existing = cursor.fetchone()
        if existing:
            existing_dict = dict(existing)
            logger.info(
                f"[CLIP_MODE] Vídeo duplicado detectado (sha256={sha256_hash[:12]}...). "
                f"Reutilizando source_id '{existing_dict['id']}' sem recópia."
            )
            return {
                "status": "duplicate",
                "source_id": existing_dict["id"],
                "existing_source_id": existing_dict["id"],
                "source": existing_dict,
                "message": "Vídeo idêntico já cadastrado na biblioteca.",
            }

    # 6. Inspeção Técnica da Mídia
    metadata = probe_video_metadata(abs_path)
    duration = metadata["duration_seconds"]
    if duration <= 0:
        raise ClipValidationError(f"Duração de vídeo inválida ({duration}s).")

    # Warnings técnicos não bloqueantes
    warnings = []
    if not metadata["has_audio"]:
        warnings.append("Vídeo sem faixa de áudio detectada.")
    if metadata["width"] < 480 or metadata["height"] < 480:
        warnings.append("Resolução de vídeo muito baixa (<480p).")
    if metadata["height"] > metadata["width"]:
        warnings.append("Vídeo já se encontra em proporção vertical.")

    # 7. Armazenamento Seguro
    source_id = f"src_{uuid.uuid4().hex[:12]}"
    dest_dir = utils.storage_dir(os.path.join("clip_sources", source_id), create=True)
    stored_filename = f"source{ext}"
    stored_path = os.path.join(dest_dir, stored_filename)

    # Copia o arquivo mantendo o original 100% intacto
    shutil.copy2(abs_path, stored_path)

    now_iso = datetime.now(timezone.utc).isoformat()
    note = (authorization_note or "").strip() or None

    # 8. Persistência
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO clip_sources (
                id, profile_id, original_filename, stored_filename, stored_path,
                sha256, file_size_bytes, duration_seconds, width, height, fps,
                video_codec, audio_codec, has_audio, source_origin,
                authorization_confirmed, authorization_note, status,
                created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                source_id,
                clean_profile_id,
                original_filename,
                stored_filename,
                stored_path,
                sha256_hash,
                file_size,
                duration,
                metadata["width"],
                metadata["height"],
                metadata["fps"],
                metadata["video_codec"],
                metadata["audio_codec"],
                1 if metadata["has_audio"] else 0,
                clean_origin,
                1 if authorization_confirmed else 0,
                note,
                SOURCE_STATUS_READY,
                now_iso,
                now_iso,
            ),
        )

    operator_console.log_operational_event(
        component="clip_mode",
        severity="INFO",
        event_type="CLIP_SOURCE_IMPORTED",
        message=f"Fonte de vídeo importada: '{original_filename}' ({duration:.1f}s, origin={clean_origin}).",
        metadata={
            "source_id": source_id,
            "profile_id": clean_profile_id,
            "sha256": sha256_hash,
            "duration_seconds": duration,
            "origin": clean_origin,
        },
        db_path=db_path,
    )

    logger.info(f"[CLIP_MODE] Fonte '{source_id}' importada com sucesso ({original_filename}, {duration}s).")

    source_data = get_clip_source(source_id, db_path=db_path)
    return {
        "status": "created",
        "source_id": source_id,
        "source": source_data,
        "warnings": warnings,
    }


def get_clip_source(source_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera detalhes de uma fonte de clip por ID."""
    init_clip_db(db_path=db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("SELECT * FROM clip_sources WHERE id = ?", (str(source_id).strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_clip_sources(
    profile_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista fontes de clip cadastradas, com filtros opcionais de perfil e status."""
    init_clip_db(db_path=db_path)
    query = "SELECT * FROM clip_sources WHERE 1=1"
    params: List[Any] = []

    if profile_id:
        query += " AND profile_id = ?"
        params.append(str(profile_id).strip())

    if status:
        query += " AND status = ?"
        params.append(str(status).strip())

    query += " ORDER BY created_at DESC;"

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def deactivate_clip_source(source_id: str, db_path: Optional[str] = None) -> Dict[str, Any]:
    """
    Desativa uma fonte de clip (status=INACTIVE):
    - Guarda PRIMARY estrita
    - Política não destrutiva: NÃO apaga o arquivo do disco nem exclui segmentos históricos.
    """
    if not operator_console.is_primary_instance(db_path=db_path):
        raise PermissionError("Instância em modo SECONDARY (VIEW ONLY). Mutação bloqueada.")

    src = get_clip_source(source_id, db_path=db_path)
    if not src:
        raise ClipModeError(f"Fonte de clip '{source_id}' não encontrada.")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE clip_sources SET status = ?, updated_at = ? WHERE id = ?",
            (SOURCE_STATUS_INACTIVE, now_iso, source_id),
        )

    operator_console.log_operational_event(
        component="clip_mode",
        severity="INFO",
        event_type="CLIP_SOURCE_DEACTIVATED",
        message=f"Fonte de clip '{source_id}' desativada.",
        metadata={"source_id": source_id},
        db_path=db_path,
    )

    return get_clip_source(source_id, db_path=db_path) or {}


# ---------------------------------------------------------------------------
# Criação e Validação de Segmentos (Clip Segments)
# ---------------------------------------------------------------------------

def create_clip_segment(
    source_id: str,
    start_seconds: float,
    end_seconds: float,
    title: Optional[str] = None,
    selection_method: str = SELECTION_METHOD_MANUAL,
    selection_reason: Optional[str] = None,
    profile_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Cria uma definição de segmento temporal para uma fonte cadastrada:
    - Guarda PRIMARY estrita
    - Fonte deve existir e estar em status READY
    - start >= 0
    - end > start
    - end <= source.duration_seconds (+ tolerância de 0.05s para arredondamentos)
    - duration calculada pelo backend
    - profile_id validado contra source.profile_id (bloqueia mismatch)
    - Warnings não bloqueantes para durações fora de 5s–180s
    """
    if not operator_console.is_primary_instance(db_path=db_path):
        raise PermissionError("Instância em modo SECONDARY (VIEW ONLY). Criação de segmento bloqueada.")

    clean_source_id = str(source_id or "").strip()
    source = get_clip_source(clean_source_id, db_path=db_path)
    if not source:
        raise ClipValidationError(f"Fonte de clip '{clean_source_id}' não encontrada.")

    if source.get("status") != SOURCE_STATUS_READY:
        raise ClipValidationError(
            f"Fonte '{clean_source_id}' não está no estado READY (status atual: {source.get('status')})."
        )

    # Validação de Perfil (preserva e herda source.profile_id)
    source_profile = source.get("profile_id") or profile_manager.DEFAULT_PROFILE_ID
    if profile_id and str(profile_id).strip() != source_profile:
        raise ClipValidationError(
            f"Conflito de perfil: o segmento especifica profile_id='{profile_id}', "
            f"mas a fonte pertence a '{source_profile}'."
        )
    target_profile_id = source_profile

    # Validação Temporal
    try:
        start_f = float(start_seconds)
        end_f = float(end_seconds)
    except (ValueError, TypeError) as exc:
        raise ClipValidationError("Os tempos de início e término devem ser números válidos.") from exc

    if start_f < 0:
        raise ClipValidationError(f"Tempo inicial inválido ({start_f}s). Deve ser >= 0.")

    if end_f <= start_f:
        raise ClipValidationError(
            f"Tempo final ({end_f}s) deve ser estritamente maior que o tempo inicial ({start_f}s)."
        )

    max_duration = float(source.get("duration_seconds") or 0.0)
    # Tolerância de 0.05s para eventuais imprecisões de ponto flutuante
    if end_f > max_duration + 0.05:
        raise ClipValidationError(
            f"Tempo final ({end_f}s) excede a duração total da fonte ({max_duration:.2f}s)."
        )

    duration_calc = round(end_f - start_f, 3)

    # Avisos de duração para formato curto (não bloqueantes)
    warnings = []
    if duration_calc < SHORT_FORM_MIN_RECOMMENDED_DURATION:
        warnings.append(
            f"Duração do segmento ({duration_calc}s) é muito curta (<{SHORT_FORM_MIN_RECOMMENDED_DURATION}s)."
        )
    if duration_calc > SHORT_FORM_MAX_RECOMMENDED_DURATION:
        warnings.append(
            f"Duração do segmento ({duration_calc}s) é longa para formatos verticais rápidos (>{SHORT_FORM_MAX_RECOMMENDED_DURATION}s)."
        )

    clean_method = (selection_method or SELECTION_METHOD_MANUAL).strip().lower()
    if clean_method not in VALID_SELECTION_METHODS:
        clean_method = SELECTION_METHOD_MANUAL

    segment_id = f"seg_{uuid.uuid4().hex[:12]}"
    now_iso = datetime.now(timezone.utc).isoformat()
    clean_title = (title or "").strip() or None
    clean_reason = (selection_reason or "").strip() or None

    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT INTO clip_segments (
                id, source_id, profile_id, start_seconds, end_seconds,
                duration_seconds, title, selection_method, selection_reason,
                status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
            """,
            (
                segment_id,
                clean_source_id,
                target_profile_id,
                round(start_f, 3),
                round(end_f, 3),
                duration_calc,
                clean_title,
                clean_method,
                clean_reason,
                SEGMENT_STATUS_CANDIDATE,
                now_iso,
                now_iso,
            ),
        )

    operator_console.log_operational_event(
        component="clip_mode",
        severity="INFO",
        event_type="CLIP_SEGMENT_CREATED",
        message=f"Segmento '{segment_id}' criado para fonte '{clean_source_id}' ({duration_calc}s).",
        metadata={
            "segment_id": segment_id,
            "source_id": clean_source_id,
            "profile_id": target_profile_id,
            "duration_seconds": duration_calc,
            "method": clean_method,
        },
        db_path=db_path,
    )

    logger.info(
        f"[CLIP_MODE] Segmento '{segment_id}' criado com sucesso "
        f"({start_f:.1f}s -> {end_f:.1f}s, dur={duration_calc}s)."
    )

    seg_data = get_clip_segment(segment_id, db_path=db_path)
    return {
        "status": "created",
        "segment_id": segment_id,
        "segment": seg_data,
        "warnings": warnings,
    }


def get_clip_segment(segment_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera dados de um segmento de corte por ID."""
    init_clip_db(db_path=db_path)
    with get_connection(db_path) as conn:
        cursor = conn.execute("SELECT * FROM clip_segments WHERE id = ?", (str(segment_id).strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None


def list_clip_segments(
    source_id: Optional[str] = None,
    profile_id: Optional[str] = None,
    status: Optional[str] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista segmentos de corte com filtros opcionais de fonte, perfil e status."""
    init_clip_db(db_path=db_path)
    query = "SELECT * FROM clip_segments WHERE 1=1"
    params: List[Any] = []

    if source_id:
        query += " AND source_id = ?"
        params.append(str(source_id).strip())

    if profile_id:
        query += " AND profile_id = ?"
        params.append(str(profile_id).strip())

    if status:
        query += " AND status = ?"
        params.append(str(status).strip())

    query += " ORDER BY start_seconds ASC, created_at DESC;"

    with get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]


def update_clip_segment_status(
    segment_id: str,
    status: str,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Atualiza o status de um segmento (CANDIDATE, SELECTED, REJECTED):
    - Guarda PRIMARY estrita
    """
    if not operator_console.is_primary_instance(db_path=db_path):
        raise PermissionError("Instância em modo SECONDARY (VIEW ONLY). Atualização de segmento bloqueada.")

    clean_status = (status or "").strip().upper()
    if clean_status not in VALID_SEGMENT_STATUSES:
        raise ClipValidationError(
            f"Status de segmento inválido ('{status}'). Valores aceitos: {sorted(list(VALID_SEGMENT_STATUSES))}."
        )

    seg = get_clip_segment(segment_id, db_path=db_path)
    if not seg:
        raise ClipValidationError(f"Segmento '{segment_id}' não encontrado.")

    now_iso = datetime.now(timezone.utc).isoformat()
    with get_connection(db_path) as conn:
        conn.execute(
            "UPDATE clip_segments SET status = ?, updated_at = ? WHERE id = ?",
            (clean_status, now_iso, segment_id),
        )

    return get_clip_segment(segment_id, db_path=db_path) or {}
