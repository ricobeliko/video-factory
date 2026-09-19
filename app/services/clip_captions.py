"""
Clip Captions Service (Fase V11-D — Captions & Final Review Polish).

Responsável pela derivação determinística de faixas de legendas (SRT e ASS)
a partir dos segmentos da transcrição da V11-B (clip_transcript_segments),
com timing relativo ao corte, chunking legível, safe area inferior vertical,
estilos CLEAN e BOLD, e governança estrita de perfil e roles.
"""
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sqlite3
import threading
from typing import Any, Dict, List, Optional, Tuple
import uuid

from loguru import logger

from app.services import clip_mode, operator_console, profile_manager
from app.utils import utils

# Lock de processo para sincronização da criação de faixas de legenda
_caption_creation_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

CAPTION_PIPELINE_VERSION = "1"

CAPTION_STATUS_PENDING = "PENDING"
CAPTION_STATUS_PROCESSING = "PROCESSING"
CAPTION_STATUS_COMPLETED = "COMPLETED"
CAPTION_STATUS_FAILED = "FAILED"
CAPTION_STATUS_INACTIVE = "INACTIVE"
VALID_CAPTION_STATUSES = {
    CAPTION_STATUS_PENDING,
    CAPTION_STATUS_PROCESSING,
    CAPTION_STATUS_COMPLETED,
    CAPTION_STATUS_FAILED,
    CAPTION_STATUS_INACTIVE,
}

CAPTION_STYLE_CLEAN = "CLEAN"
CAPTION_STYLE_BOLD = "BOLD"
DEFAULT_CAPTION_STYLE = CAPTION_STYLE_CLEAN
VALID_CAPTION_STYLES = {CAPTION_STYLE_CLEAN, CAPTION_STYLE_BOLD}

MIN_CAPTION_DURATION_SECONDS = 0.6
MAX_LINE_CHARS = 38
MAX_CUE_LINES = 2
SAFE_AREA_MARGIN_V = 340  # ~17.7% acima da base em 1080x1920

# ---------------------------------------------------------------------------
# Exceções Específicas de Legendas
# ---------------------------------------------------------------------------

class ClipCaptionError(clip_mode.ClipModeError):
    """Exceção base para erros de geração de legendas."""
    pass


class TranscriptRequiredError(ClipCaptionError):
    """Lançada quando a fonte não possui uma transcrição COMPLETED válida."""
    pass


class DuplicateCaptionProcessingError(ClipCaptionError):
    """Lançada quando já existe uma geração de legenda PROCESSING ativa."""
    pass


# ---------------------------------------------------------------------------
# Inicialização do Banco de Dados
# ---------------------------------------------------------------------------

def init_clip_captions_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas clip_caption_tracks e clip_caption_cues de forma idempotente."""
    clip_mode.init_clip_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_caption_tracks (
                id TEXT PRIMARY KEY,
                segment_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                transcript_id TEXT NOT NULL,
                style TEXT NOT NULL,
                language TEXT,
                cue_count INTEGER NOT NULL DEFAULT 0,
                duration_seconds REAL,
                srt_path TEXT NOT NULL,
                ass_path TEXT,
                caption_fingerprint TEXT NOT NULL,
                status TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                FOREIGN KEY (segment_id) REFERENCES clip_segments(id),
                FOREIGN KEY (source_id) REFERENCES clip_sources(id),
                FOREIGN KEY (transcript_id) REFERENCES clip_transcripts(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_captions_segment ON clip_caption_tracks(segment_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_captions_source ON clip_caption_tracks(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_captions_status ON clip_caption_tracks(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_captions_fingerprint ON clip_caption_tracks(caption_fingerprint);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_caption_cues (
                id TEXT PRIMARY KEY,
                caption_track_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                text TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (caption_track_id) REFERENCES clip_caption_tracks(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_cues_track ON clip_caption_cues(caption_track_id);")


# ---------------------------------------------------------------------------
# Helpers de Formatação e Escrita de Legendas
# ---------------------------------------------------------------------------

def format_timestamp_srt(seconds: float) -> str:
    """Formata segundos em HH:MM:SS,mmm (formato padrão SRT)."""
    secs = max(0.0, float(seconds))
    hours = int(secs // 3600)
    rem = secs % 3600
    minutes = int(rem // 60)
    sec_int = int(rem % 60)
    millis = int(round((rem - int(rem)) * 1000.0)) % 1000
    return f"{hours:02d}:{minutes:02d}:{sec_int:02d},{millis:03d}"


def format_timestamp_ass(seconds: float) -> str:
    """Formata segundos em H:MM:SS.cc (formato padrão ASS centésimos)."""
    secs = max(0.0, float(seconds))
    hours = int(secs // 3600)
    rem = secs % 3600
    minutes = int(rem // 60)
    sec_int = int(rem % 60)
    centis = int(round((rem - int(rem)) * 100.0)) % 100
    return f"{hours:d}:{minutes:02d}:{sec_int:02d}.{centis:02d}"


def clean_caption_text(text: str) -> str:
    """
    Limpeza leve e determinística de texto de legenda:
    - trim de espaços externos
    - normalização de quebras de linha e colapso de espaços múltiplos
    - preserva unicode e pontuação original intactos.
    """
    if not text:
        return ""
    t = text.replace("\r\n", "\n").replace("\r", "\n")
    t = re.sub(r"[ \t\f\v]+", " ", t)
    t = re.sub(r" *\n *", "\n", t)
    t = re.sub(r"\n+", "\n", t)
    return t.strip()


def escape_text_for_ass(text: str) -> str:
    """
    Escapa texto para inclusão segura no corpo de eventos ASS:
    - Escapa chaves { e } para evitar injeção acidental de tags de estilo ASS
    - Converte quebras de linha em \\N
    """
    cleaned = clean_caption_text(text)
    escaped = cleaned.replace("{", "\\{").replace("}", "\\}")
    escaped = escaped.replace("\n", "\\N")
    return escaped


def escape_text_for_srt(text: str) -> str:
    """Escapa texto para SRT mantendo quebras de linha normais."""
    return clean_caption_text(text)


def chunk_caption_cues(
    raw_cues: List[Dict[str, Any]],
    clip_duration: float,
    max_line_chars: int = MAX_LINE_CHARS,
    max_lines: int = MAX_CUE_LINES,
    min_duration: float = MIN_CAPTION_DURATION_SECONDS,
) -> List[Dict[str, Any]]:
    """
    Ajusta e divide cues para legibilidade ótima em vídeo vertical:
    - Garante que cada cue tenha no máximo 2 linhas e ~38 caracteres por linha.
    - Não divide palavras ao meio.
    - Garante duração mínima de ~0.6s quando possível sem ultrapassar próximo cue ou clip_duration.
    """
    if not raw_cues:
        return []

    split_cues: List[Dict[str, Any]] = []

    for raw in raw_cues:
        c_start = float(raw["start_seconds"])
        c_end = float(raw["end_seconds"])
        text = clean_caption_text(raw.get("text", ""))
        if not text or c_end <= c_start:
            continue

        words = text.split(" ")
        words = [w for w in words if w]
        if not words:
            continue

        # Se o texto cabe confortavelmente em 1 ou 2 linhas
        total_len = len(text)
        max_cue_capacity = max_line_chars * max_lines

        if total_len <= max_cue_capacity:
            # Formata em 1 ou 2 linhas se necessário
            if total_len > max_line_chars:
                mid = len(words) // 2
                line1 = " ".join(words[:mid])
                line2 = " ".join(words[mid:])
                formatted_text = f"{line1}\n{line2}"
            else:
                formatted_text = text

            split_cues.append({
                "start_seconds": c_start,
                "end_seconds": c_end,
                "text": formatted_text,
            })
        else:
            # Divide em múltiplos sub-cues dividindo tempo proporcionalmente
            num_splits = (total_len + max_cue_capacity - 1) // max_cue_capacity
            words_per_split = max(1, len(words) // num_splits)
            cue_total_dur = c_end - c_start

            current_pos = 0
            while current_pos < len(words):
                chunk_words = words[current_pos : current_pos + words_per_split]
                current_pos += words_per_split
                # Se sobrar só 1 palavra no fim, anexa ao chunk atual
                if len(words) - current_pos == 1:
                    chunk_words.append(words[current_pos])
                    current_pos += 1

                chunk_text = " ".join(chunk_words)
                ratio_start = (current_pos - len(chunk_words)) / len(words)
                ratio_end = current_pos / len(words)

                sub_start = c_start + (cue_total_dur * ratio_start)
                sub_end = c_start + (cue_total_dur * ratio_end)

                if len(chunk_text) > max_line_chars:
                    c_mid = len(chunk_words) // 2
                    l1 = " ".join(chunk_words[:c_mid])
                    l2 = " ".join(chunk_words[c_mid:])
                    chunk_text = f"{l1}\n{l2}"

                split_cues.append({
                    "start_seconds": round(sub_start, 3),
                    "end_seconds": round(sub_end, 3),
                    "text": chunk_text,
                })

    # Segunda passagem: ajuste de duração mínima e ordenação estrita
    split_cues.sort(key=lambda x: x["start_seconds"])
    final_cues: List[Dict[str, Any]] = []

    for i, cue in enumerate(split_cues):
        s = max(0.0, float(cue["start_seconds"]))
        e = float(cue["end_seconds"])
        dur = e - s

        # Tenta estender até min_duration se couber
        if dur < min_duration:
            next_start = split_cues[i + 1]["start_seconds"] if (i + 1 < len(split_cues)) else clip_duration
            available = min(next_start, clip_duration)
            e = min(s + min_duration, available)

        # Garante limites válidos dentro do clipe
        if e > clip_duration:
            e = clip_duration
        if e > s:
            final_cues.append({
                "sequence": len(final_cues) + 1,
                "start_seconds": round(s, 3),
                "end_seconds": round(e, 3),
                "text": cue["text"],
            })

    return final_cues


def generate_srt_content(cues: List[Dict[str, Any]]) -> str:
    """Gera o arquivo SRT completo a partir da lista de cues."""
    lines: List[str] = []
    for cue in cues:
        seq = cue["sequence"]
        start_str = format_timestamp_srt(cue["start_seconds"])
        end_str = format_timestamp_srt(cue["end_seconds"])
        txt = escape_text_for_srt(cue["text"])
        lines.append(f"{seq}\n{start_str} --> {end_str}\n{txt}\n")
    return "\n".join(lines)


def generate_ass_content(
    cues: List[Dict[str, Any]],
    style: str = DEFAULT_CAPTION_STYLE,
    font_name: str = "Arial",
) -> str:
    """
    Gera o conteúdo de arquivo ASS v4.00+ para resolução 1080x1920:
    - Safe area inferior (MarginV = 340px, aprox. 17.7% acima do rodapé)
    - Estilo CLEAN: branco, contorno fino 2.5px, sombra 1.5px, tamanho 54px
    - Estilo BOLD: branco, contorno forte 4.0px, sombra 2.0px, negrito, tamanho 62px
    - Centralizado (Alignment = 2)
    """
    clean_style = str(style or DEFAULT_CAPTION_STYLE).upper()
    if clean_style not in VALID_CAPTION_STYLES:
        clean_style = DEFAULT_CAPTION_STYLE

    if clean_style == CAPTION_STYLE_BOLD:
        fontsize = 62
        bold_flag = -1  # True no ASS
        outline = 4.0
        shadow = 2.0
    else:  # CLEAN
        fontsize = 54
        bold_flag = 0   # Normal
        outline = 2.5
        shadow = 1.5

    header = f"""[Script Info]
; Script generated by MoneyPrinterTurbo V11-D Clip Captions Service
ScriptType: v4.00+
PlayResX: 1080
PlayResY: 1920
WrapStyle: 0
ScaledBorderAndShadow: yes

[V4+ Styles]
Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding
Style: Default,{font_name},{fontsize},&H00FFFFFF,&H000000FF,&H00000000,&H80000000,{bold_flag},0,0,0,100,100,0,0,1,{outline:.1f},{shadow:.1f},2,60,60,{SAFE_AREA_MARGIN_V},1

[Events]
Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text
"""
    events = []
    for cue in cues:
        start_str = format_timestamp_ass(cue["start_seconds"])
        end_str = format_timestamp_ass(cue["end_seconds"])
        ass_txt = escape_text_for_ass(cue["text"])
        events.append(f"Dialogue: 0,{start_str},{end_str},Default,,0,0,0,,{ass_txt}")

    return header + "\n".join(events) + "\n"


def compute_caption_fingerprint(
    segment_id: str,
    transcript_id: str,
    cues_hash: str,
    style: str,
    language: str,
    pipeline_version: str = CAPTION_PIPELINE_VERSION,
) -> str:
    """Gera um hash SHA-256 determinístico para garantir idempotência de faixas de legendas."""
    raw = (
        f"{str(segment_id).strip()}:"
        f"{str(transcript_id).strip()}:"
        f"{str(cues_hash).strip()}:"
        f"{str(style).strip().upper()}:"
        f"{str(language).strip().lower()}:"
        f"{str(pipeline_version).strip()}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Operação Central de Geração de Legendas
# ---------------------------------------------------------------------------

def generate_clip_captions(
    segment_id: str,
    style: str = DEFAULT_CAPTION_STYLE,
    force: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Gera uma faixa de legendas sincronizadas (SRT e ASS) para um segmento SELECTED
    derivando exclusivamente dos segmentos da transcrição existente (V11-B).
    Requer papel PRIMARY. Bloqueia SECONDARY_VIEW_ONLY.
    """
    # 1. Checagem de Governança e Permissões
    operator_console.require_primary_instance(db_path=db_path)

    clean_seg_id = str(segment_id or "").strip()
    if not clean_seg_id:
        raise ClipCaptionError("segment_id não pode ser vazio.")

    clean_style = str(style or DEFAULT_CAPTION_STYLE).strip().upper()
    if clean_style not in VALID_CAPTION_STYLES:
        raise ClipCaptionError(
            f"Estilo de legenda inválido: '{clean_style}'. Estilos permitidos: {sorted(list(VALID_CAPTION_STYLES))}"
        )

    init_clip_captions_db(db_path=db_path)

    # 2. Carrega Segmento e Fonte
    with clip_mode.get_connection(db_path) as conn:
        seg_row = conn.execute(
            """
            SELECT id, source_id, profile_id, status,
                   start_seconds, end_seconds, duration_seconds, title
            FROM clip_segments WHERE id = ?
            """,
            (clean_seg_id,),
        ).fetchone()

        if not seg_row:
            raise ClipCaptionError(f"Segmento '{clean_seg_id}' não encontrado.")

        seg = dict(seg_row)
        source_id = seg["source_id"]

        source_row = conn.execute(
            """
            SELECT id, profile_id, original_filename, stored_path, sha256,
                   duration_seconds, authorization_confirmed, status
            FROM clip_sources WHERE id = ?
            """,
            (source_id,),
        ).fetchone()

        if not source_row:
            raise ClipCaptionError(f"Fonte '{source_id}' associada ao segmento não encontrada.")

        source = dict(source_row)

        # 3. Validações de Governança
        if source.get("status") != clip_mode.SOURCE_STATUS_READY:
            raise ClipCaptionError(f"Fonte '{source_id}' não está no estado READY.")

        if not source.get("authorization_confirmed"):
            raise ClipCaptionError(f"Fonte '{source_id}' não possui autorização legal confirmada.")

        if seg.get("status") != clip_mode.SEGMENT_STATUS_SELECTED:
            raise ClipCaptionError(
                f"Segmento com status '{seg.get('status')}' não pode gerar legendas (exige SELECTED)."
            )

        if seg.get("profile_id") != source.get("profile_id"):
            raise ClipCaptionError("Inconsistência de profile_id entre segmento e fonte.")

        # 4. Busca Transcrição COMPLETED Existente (NÃO REEXECUTA STT)
        trans_row = conn.execute(
            """
            SELECT id, source_id, profile_id, language, status
            FROM clip_transcripts
            WHERE source_id = ? AND status = 'COMPLETED'
            ORDER BY completed_at DESC, created_at DESC
            LIMIT 1
            """,
            (source_id,),
        ).fetchone()

        if not trans_row:
            raise TranscriptRequiredError(
                "TRANSCRIPT_REQUIRED: Transcrição COMPLETED não encontrada para esta fonte. "
                "Execute a transcrição da fonte antes de gerar legendas."
            )

        transcript = dict(trans_row)
        transcript_id = transcript["id"]
        language = transcript.get("language") or "unknown"

        # Carrega todos os segmentos da transcrição
        t_segs = conn.execute(
            """
            SELECT id, sequence, start_seconds, end_seconds, text
            FROM clip_transcript_segments
            WHERE transcript_id = ?
            ORDER BY sequence ASC
            """,
            (transcript_id,),
        ).fetchall()

    # 5. Filtragem e Timing Clip-Relative
    seg_start = float(seg.get("start_seconds") or 0.0)
    seg_end = float(seg.get("end_seconds") or 0.0)
    clip_dur = float(seg.get("duration_seconds") or (seg_end - seg_start))

    raw_cues: List[Dict[str, Any]] = []
    for ts in t_segs:
        t_start = float(ts["start_seconds"])
        t_end = float(ts["end_seconds"])

        # Verifica interseção estrita com a janela do segmento
        if t_end <= seg_start or t_start >= seg_end:
            continue

        # Projeta os timestamps para a escala relativa do clipe (0s -> clip_dur)
        rel_start = max(t_start, seg_start) - seg_start
        rel_end = min(t_end, seg_end) - seg_start

        if rel_end > rel_start:
            raw_cues.append({
                "start_seconds": rel_start,
                "end_seconds": rel_end,
                "text": str(ts["text"] or "").strip(),
            })

    # Chunking e legibilidade
    cues = chunk_caption_cues(raw_cues, clip_duration=clip_dur)

    # 6. Cálculo do Fingerprint
    cues_data_str = json.dumps(
        [{"s": c["start_seconds"], "e": c["end_seconds"], "t": c["text"]} for c in cues],
        sort_keys=True,
    )
    cues_hash = hashlib.sha256(cues_data_str.encode("utf-8")).hexdigest()

    fingerprint = compute_caption_fingerprint(
        segment_id=clean_seg_id,
        transcript_id=transcript_id,
        cues_hash=cues_hash,
        style=clean_style,
        language=language,
        pipeline_version=CAPTION_PIPELINE_VERSION,
    )

    # 7. Idempotência com force=False
    if not force:
        with clip_mode.get_connection(db_path) as conn:
            existing = conn.execute(
                """
                SELECT * FROM clip_caption_tracks
                WHERE caption_fingerprint = ? AND status = ?
                ORDER BY created_at DESC
                LIMIT 1
                """,
                (fingerprint, CAPTION_STATUS_COMPLETED),
            ).fetchone()

            if existing:
                ex_dict = dict(existing)
                # Verifica se arquivos em disco continuam íntegros
                if os.path.isfile(ex_dict["srt_path"]) and (
                    not ex_dict.get("ass_path") or os.path.isfile(ex_dict["ass_path"])
                ):
                    logger.info(f"Reutilizando faixa de legendas idêntica: {ex_dict['id']}")
                    return ex_dict

    # 8. Seção Crítica: Verificação de PROCESSING e Inserção Atômica
    track_id = f"cap_{uuid.uuid4().hex[:12]}"
    target_dir = utils.storage_dir(os.path.join("clip_sources", source_id, "captions", track_id), create=True)
    srt_path = os.path.join(target_dir, "captions.srt")
    ass_path = os.path.join(target_dir, "captions.ass")
    now_iso = datetime.now(timezone.utc).isoformat()

    with _caption_creation_lock:
        with clip_mode.get_connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")

            # Verifica se já há track PROCESSING para o mesmo segmento e estilo
            active = conn.execute(
                """
                SELECT id FROM clip_caption_tracks
                WHERE segment_id = ? AND style = ? AND status = ?
                """,
                (clean_seg_id, clean_style, CAPTION_STATUS_PROCESSING),
            ).fetchone()

            if active:
                raise DuplicateCaptionProcessingError(
                    f"Já existe uma geração de legendas em processamento (ID: {active['id']}) para este segmento."
                )

            # Insere em estado PROCESSING
            conn.execute(
                """
                INSERT INTO clip_caption_tracks (
                    id, segment_id, source_id, profile_id, transcript_id,
                    style, language, cue_count, duration_seconds,
                    srt_path, ass_path, caption_fingerprint, status,
                    created_at, updated_at, error_code, error_message
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    track_id,
                    clean_seg_id,
                    source_id,
                    seg["profile_id"],
                    transcript_id,
                    clean_style,
                    language,
                    len(cues),
                    clip_dur,
                    srt_path,
                    ass_path,
                    fingerprint,
                    CAPTION_STATUS_PROCESSING,
                    now_iso,
                    now_iso,
                    None,
                    None,
                ),
            )
            conn.commit()

    # 9. Geração dos Arquivos SRT e ASS em Disco
    try:
        srt_content = generate_srt_content(cues)
        with open(srt_path, "w", encoding="utf-8") as f_srt:
            f_srt.write(srt_content)

        ass_content = generate_ass_content(cues, style=clean_style)
        with open(ass_path, "w", encoding="utf-8") as f_ass:
            f_ass.write(ass_content)

        # 10. Persistência das Cues Individuais no SQLite
        with clip_mode.get_connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE")

            # Insere cues
            for cue in cues:
                cue_id = f"cue_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO clip_caption_cues (
                        id, caption_track_id, sequence, start_seconds, end_seconds, text, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        cue_id,
                        track_id,
                        int(cue["sequence"]),
                        float(cue["start_seconds"]),
                        float(cue["end_seconds"]),
                        str(cue["text"]),
                        now_iso,
                    ),
                )

            # Atualiza track para COMPLETED
            completed_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE clip_caption_tracks
                SET status = ?, cue_count = ?, duration_seconds = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    CAPTION_STATUS_COMPLETED,
                    len(cues),
                    clip_dur,
                    completed_iso,
                    track_id,
                ),
            )
            conn.commit()

        logger.info(f"Faixa de legendas {track_id} ({clean_style}) criada com sucesso com {len(cues)} cues.")
        return get_caption_track(track_id, db_path=db_path)  # type: ignore

    except Exception as exc:
        logger.error(f"Falha na escrita da faixa de legendas {track_id}: {exc}", exc_info=True)
        # Marca como FAILED
        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_caption_tracks
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    CAPTION_STATUS_FAILED,
                    "CAPTION_WRITE_ERROR",
                    str(exc)[:500],
                    datetime.now(timezone.utc).isoformat(),
                    track_id,
                ),
            )
        raise ClipCaptionError(f"Falha na geração dos arquivos de legenda: {exc}") from exc


# ---------------------------------------------------------------------------
# Consultas de Legendas
# ---------------------------------------------------------------------------

def get_caption_track(track_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera uma faixa de legendas pelo ID."""
    clean_id = str(track_id or "").strip()
    if not clean_id:
        return None

    init_clip_captions_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        row = conn.execute(
            """
            SELECT * FROM clip_caption_tracks WHERE id = ?
            """,
            (clean_id,),
        ).fetchone()

        if not row:
            return None
        return dict(row)


def list_caption_tracks_for_segment(
    segment_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista todas as faixas de legenda associadas a um segmento."""
    clean_id = str(segment_id or "").strip()
    if not clean_id:
        return []

    init_clip_captions_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_caption_tracks
            WHERE segment_id = ?
            ORDER BY created_at DESC
            """,
            (clean_id,),
        ).fetchall()

        return [dict(r) for r in rows]


def get_caption_cues(
    caption_track_id: str,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera as cues individuais de uma faixa de legendas em ordem sequencial."""
    clean_id = str(caption_track_id or "").strip()
    if not clean_id:
        return []

    init_clip_captions_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM clip_caption_cues
            WHERE caption_track_id = ?
            ORDER BY sequence ASC
            """,
            (clean_id,),
        ).fetchall()

        return [dict(r) for r in rows]
