"""
Clip Transcription Service (Fase V11-B — Transcript & Segment Discovery).

Responsável pela extração segura de áudio de mídias cadastradas em Clip Mode,
arquitetura desacoplada de provedores de Speech-to-Text (faster-whisper e mocks),
persistência de transcrições e segmentos temporais no SQLite, concorrência controlada
e isolamento rigoroso de falhas.
"""
from abc import ABC, abstractmethod
from contextlib import contextmanager
from datetime import datetime, timezone
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

# Lock de processo para sincronização da seção crítica de início de transcrição
_transcription_creation_lock = threading.Lock()

# ---------------------------------------------------------------------------
# Constantes e Políticas
# ---------------------------------------------------------------------------

DEFAULT_TRANSCRIPT_PROVIDER = "faster_whisper"
DEFAULT_TRANSCRIPT_MODEL = "small"
SUPPORTED_TRANSCRIPT_LANGUAGES = ("auto", "pt", "en", "es")

TRANSCRIPT_STATUS_PENDING = "PENDING"
TRANSCRIPT_STATUS_PROCESSING = "PROCESSING"
TRANSCRIPT_STATUS_COMPLETED = "COMPLETED"
TRANSCRIPT_STATUS_FAILED = "FAILED"
VALID_TRANSCRIPT_STATUSES = {
    TRANSCRIPT_STATUS_PENDING,
    TRANSCRIPT_STATUS_PROCESSING,
    TRANSCRIPT_STATUS_COMPLETED,
    TRANSCRIPT_STATUS_FAILED,
}


# ---------------------------------------------------------------------------
# Inicialização do Banco de Dados
# ---------------------------------------------------------------------------

def init_clip_transcription_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas clip_transcripts e clip_transcript_segments de forma idempotente e aditiva."""
    clip_mode.init_clip_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_transcripts (
                id TEXT PRIMARY KEY,
                source_id TEXT NOT NULL,
                profile_id TEXT NOT NULL,
                provider TEXT NOT NULL,
                model_name TEXT NOT NULL,
                language TEXT NOT NULL,
                status TEXT NOT NULL,
                full_text TEXT,
                started_at TEXT NOT NULL,
                completed_at TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                error_code TEXT,
                error_message TEXT,
                FOREIGN KEY (source_id) REFERENCES clip_sources(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_transcripts_source ON clip_transcripts(source_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_transcripts_status ON clip_transcripts(status);")

        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS clip_transcript_segments (
                id TEXT PRIMARY KEY,
                transcript_id TEXT NOT NULL,
                source_id TEXT NOT NULL,
                sequence INTEGER NOT NULL,
                start_seconds REAL NOT NULL,
                end_seconds REAL NOT NULL,
                text TEXT NOT NULL,
                confidence REAL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (transcript_id) REFERENCES clip_transcripts(id),
                FOREIGN KEY (source_id) REFERENCES clip_sources(id)
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_tsegments_transcript ON clip_transcript_segments(transcript_id);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_clip_tsegments_source ON clip_transcript_segments(source_id);")


# ---------------------------------------------------------------------------
# Extração Segura de Áudio via FFmpeg
# ---------------------------------------------------------------------------

def extract_clip_source_audio(
    source_id: str,
    force: bool = False,
    timeout_seconds: int = 120,
    db_path: Optional[str] = None,
) -> str:
    """
    Extrai a faixa de áudio de uma fonte READY para áudio mono 16kHz PCM WAV.
    Destino strictly isolado em storage/clip_sources/<source_id>/transcription/audio.wav.
    Preserva a fonte de vídeo original 100% intacta.
    Reutiliza cache se já existente e force=False.
    """
    clean_sid = str(source_id or "").strip()
    source = clip_mode.get_clip_source(clean_sid, db_path=db_path)
    if not source:
        raise clip_mode.ClipValidationError(f"Fonte de clip '{clean_sid}' não encontrada.")

    if source.get("status") != clip_mode.SOURCE_STATUS_READY:
        raise clip_mode.ClipValidationError(
            f"Fonte '{clean_sid}' não está no estado READY (status atual: {source.get('status')})."
        )

    if not source.get("has_audio"):
        raise clip_mode.ClipModeError("NO_AUDIO")

    stored_video_path = source.get("stored_path")
    if not stored_video_path or not os.path.isfile(stored_video_path):
        raise clip_mode.ClipValidationError(f"Arquivo de vídeo da fonte não encontrado em disco: {stored_video_path}")

    # Diretório de destino estritamente contido no storage da source
    target_dir = utils.storage_dir(os.path.join("clip_sources", clean_sid, "transcription"), create=True)
    audio_path = os.path.join(target_dir, "audio.wav")

    # Cache técnico: validação rigorosa (existe, arquivo regular, não-symlink, size > 0, dentro de target_dir)
    if not force:
        norm_target_dir = os.path.abspath(target_dir)
        norm_audio_path = os.path.abspath(audio_path)
        is_contained = os.path.commonpath([norm_target_dir]) == os.path.commonpath([norm_target_dir, norm_audio_path])
        if (
            is_contained
            and os.path.exists(audio_path)
            and not os.path.islink(audio_path)
            and os.path.isfile(audio_path)
            and os.path.getsize(audio_path) > 0
        ):
            logger.debug(f"[CLIP_TRANSCRIPTION] Reutilizando áudio extraído existente: {audio_path}")
            return audio_path

    # Gera arquivo temporário no mesmo diretório com extensão .tmp.wav compatível com FFmpeg
    temp_filename = f"audio_{uuid.uuid4().hex[:8]}.tmp.wav"
    temp_path = os.path.join(target_dir, temp_filename)

    ffmpeg_bin = utils.get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin,
        "-hide_banner",
        "-y",
        "-i", stored_video_path,
        "-vn",
        "-ac", "1",
        "-ar", "16000",
        "-c:a", "pcm_s16le",
        temp_path,
    ]

    logger.info(f"[CLIP_TRANSCRIPTION] Extraindo áudio mono 16kHz de '{clean_sid}' para temporário '{temp_path}'")
    try:
        res = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
            shell=False,
            errors="replace",
        )
        if res.returncode != 0:
            err_msg = res.stderr[-500:] if res.stderr else "Erro desconhecido do FFmpeg"
            raise clip_mode.ClipValidationError(f"Falha ao extrair áudio com FFmpeg (rc={res.returncode}): {err_msg}")

        # Validação pós-extração do arquivo temporário
        if (
            not os.path.exists(temp_path)
            or os.path.islink(temp_path)
            or not os.path.isfile(temp_path)
            or os.path.getsize(temp_path) <= 0
        ):
            raise clip_mode.ClipValidationError("Arquivo de áudio temporário extraído está vazio ou não foi gerado.")

        # Promoção atômica no mesmo filesystem (preserva audio.wav anterior se houve falha prévia)
        os.replace(temp_path, audio_path)

    except subprocess.TimeoutExpired as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        raise clip_mode.ClipValidationError(f"Timeout ao extrair áudio ({timeout_seconds}s): {exc}") from exc
    except Exception as exc:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass
        if isinstance(exc, clip_mode.ClipModeError):
            raise
        raise clip_mode.ClipValidationError(f"Erro ao executar extração de áudio: {exc}") from exc

    return audio_path


# ---------------------------------------------------------------------------
# Arquitetura Desacoplada de Provedores de Transcrição
# ---------------------------------------------------------------------------

class TranscriptProvider(ABC):
    """Interface abstrata para provedores de Speech-to-Text."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Nome identificador do provedor."""
        pass

    @abstractmethod
    def status(self) -> str:
        """Retorna 'AVAILABLE', 'NOT_INSTALLED' ou 'NOT_CONFIGURED'."""
        pass

    @abstractmethod
    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        model_name: str = "small",
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        """
        Transcreve o arquivo de áudio WAV.
        Retorna: (full_text, detected_language, segments_list)
        onde cada item de segments_list contém:
        {
            "sequence": int,
            "start_seconds": float,
            "end_seconds": float,
            "text": str,
            "confidence": Optional[float]
        }
        """
        pass


class FasterWhisperTranscriptProvider(TranscriptProvider):
    """
    Provedor baseado em faster-whisper.
    Lazy-loading total: o modelo NUNCA é baixado ou instanciado no import ou boot.
    Carrega estritamente mediante chamada explícita a transcribe().
    """

    @property
    def name(self) -> str:
        return "faster_whisper"

    def status(self) -> str:
        try:
            import faster_whisper  # noqa: F401
            return "AVAILABLE"
        except ImportError:
            return "NOT_INSTALLED"

    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        model_name: str = "small",
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        if self.status() != "AVAILABLE":
            raise clip_mode.ClipModeError("Provedor faster-whisper não está instalado no ambiente.")

        from faster_whisper import WhisperModel

        clean_model = (model_name or "small").strip()
        clean_lang = None if (not language or language.lower() == "auto") else language.strip().lower()

        logger.info(f"[CLIP_TRANSCRIPTION] Instanciando WhisperModel ({clean_model}, cpu, int8) sob demanda...")
        try:
            model = WhisperModel(clean_model, device="cpu", compute_type="int8")
            segments_gen, info = model.transcribe(
                audio_path,
                language=clean_lang,
                beam_size=5,
                vad_filter=True,
                vad_parameters=dict(min_silence_duration_ms=500),
            )
        except Exception as exc:
            logger.error(f"[CLIP_TRANSCRIPTION] Falha ao executar transcrição faster-whisper: {exc}")
            raise clip_mode.ClipModeError(f"Falha no motor de transcrição: {str(exc)[:300]}") from exc

        detected_lang = getattr(info, "language", clean_lang or "auto")
        segments_list: List[Dict[str, Any]] = []
        full_text_parts: List[str] = []

        seq = 0
        for seg in segments_gen:
            t = (seg.text or "").strip()
            if not t:
                continue
            start_s = round(float(seg.start), 3)
            end_s = round(float(seg.end), 3)
            if end_s <= start_s:
                end_s = start_s + 0.1

            # Média de probabilidade ou None
            avg_prob = getattr(seg, "avg_logprob", None)
            conf = round(float(avg_prob), 4) if avg_prob is not None else None

            segments_list.append({
                "sequence": seq,
                "start_seconds": start_s,
                "end_seconds": end_s,
                "text": t,
                "confidence": conf,
            })
            full_text_parts.append(t)
            seq += 1

        full_text = " ".join(full_text_parts)
        return full_text, detected_lang, segments_list


class MockTranscriptProvider(TranscriptProvider):
    """Provedor mockado para testes automatizados determinísticos sem dependência de rede ou pesos."""

    def __init__(
        self,
        mock_text: str = "Este é um teste de transcrição. Falamos sobre inovação e inteligência artificial.",
        mock_language: str = "pt",
        mock_segments: Optional[List[Dict[str, Any]]] = None,
        should_fail: bool = False,
    ):
        self._mock_text = mock_text
        self._mock_language = mock_language
        self._mock_segments = mock_segments
        self._should_fail = should_fail
        self.call_count = 0

    @property
    def name(self) -> str:
        return "mock"

    def status(self) -> str:
        return "AVAILABLE"

    def transcribe(
        self,
        audio_path: str,
        language: str = "auto",
        model_name: str = "small",
    ) -> Tuple[str, str, List[Dict[str, Any]]]:
        self.call_count += 1
        if self._should_fail:
            raise clip_mode.ClipModeError("Mock transcript provider failure triggered.")

        if self._mock_segments is not None:
            return self._mock_text, self._mock_language, self._mock_segments

        # Gera segmentos sintéticos padrão
        segs = [
            {
                "sequence": 0,
                "start_seconds": 0.0,
                "end_seconds": 15.0,
                "text": "Você sabia que inteligência artificial pode acelerar sua criação?",
                "confidence": 0.95,
            },
            {
                "sequence": 1,
                "start_seconds": 15.0,
                "end_seconds": 38.0,
                "text": "O segredo é estruturar o conteúdo em tópicos objetivos e manter a narrativa coesa.",
                "confidence": 0.92,
            },
            {
                "sequence": 2,
                "start_seconds": 38.0,
                "end_seconds": 55.0,
                "text": "Três coisas fundamentais definem um bom vídeo: gancho, retenção e clareza.",
                "confidence": 0.88,
            },
        ]
        return self._mock_text, self._mock_language, segs


# ---------------------------------------------------------------------------
# Registry de Provedores
# ---------------------------------------------------------------------------

_TRANSCRIPT_PROVIDERS: Dict[str, TranscriptProvider] = {
    "faster_whisper": FasterWhisperTranscriptProvider(),
}


def register_transcript_provider(name: str, provider: TranscriptProvider) -> None:
    """Registra ou substitui um provedor de transcrição."""
    clean_name = (name or "").strip().lower()
    _TRANSCRIPT_PROVIDERS[clean_name] = provider


def get_transcript_provider(name: str = DEFAULT_TRANSCRIPT_PROVIDER) -> TranscriptProvider:
    """Recupera o provedor de transcrição pelo nome."""
    clean_name = (name or DEFAULT_TRANSCRIPT_PROVIDER).strip().lower()
    if clean_name not in _TRANSCRIPT_PROVIDERS:
        raise clip_mode.ClipModeError(f"Provedor de transcrição '{name}' não registrado.")
    return _TRANSCRIPT_PROVIDERS[clean_name]


# ---------------------------------------------------------------------------
# Operações de Transcrição
# ---------------------------------------------------------------------------

def transcribe_clip_source(
    source_id: str,
    language: str = "auto",
    model_name: str = DEFAULT_TRANSCRIPT_MODEL,
    provider_name: str = DEFAULT_TRANSCRIPT_PROVIDER,
    force: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Executa a transcrição de áudio de uma fonte autorizada e persiste os segmentos com timestamps:
    - Guarda PRIMARY estrita
    - Fonte deve estar READY e com autorização confirmada
    - Fonte deve possuir áudio (rejeita com NO_AUDIO sem invalidar a fonte)
    - Concorrência: bloqueia se outra transcrição estiver PROCESSING para a mesma fonte
    - Idempotência: se já existir COMPLETED para mesma config e force=False, reutiliza
    - force=True: cria novo registro histórico sem apagar os anteriores
    - Falhas não alteram o status da fonte (isolamento de falhas)
    """
    operator_console.require_primary_instance(db_path=db_path)

    clean_sid = str(source_id or "").strip()
    source = clip_mode.get_clip_source(clean_sid, db_path=db_path)
    if not source:
        raise clip_mode.ClipValidationError(f"Fonte de clip '{clean_sid}' não encontrada.")

    if source.get("status") != clip_mode.SOURCE_STATUS_READY:
        raise clip_mode.ClipValidationError(
            f"Fonte '{clean_sid}' não está no estado READY (status atual: {source.get('status')})."
        )

    if not source.get("authorization_confirmed"):
        raise clip_mode.ClipAuthorizationError("Fonte sem autorização confirmada não pode ser transcrita.")

    if not source.get("has_audio"):
        raise clip_mode.ClipModeError("NO_AUDIO")

    profile_id = source.get("profile_id") or profile_manager.DEFAULT_PROFILE_ID
    clean_provider = (provider_name or DEFAULT_TRANSCRIPT_PROVIDER).strip().lower()
    clean_model = (model_name or DEFAULT_TRANSCRIPT_MODEL).strip().lower()
    clean_lang = (language or "auto").strip().lower()

    init_clip_transcription_db(db_path=db_path)

    # 1. Seção crítica atômica: Checagem e Inserção sob a MESMA transação com BEGIN IMMEDIATE
    with _transcription_creation_lock:
        with clip_mode.get_connection(db_path) as conn:
            conn.execute("BEGIN IMMEDIATE;")

            # 1.1 Bloqueia SEMPRE se já houver PROCESSING ativo para a mesma source (mesmo com force=True)
            curr_processing = conn.execute(
                "SELECT id FROM clip_transcripts WHERE source_id = ? AND status = ?;",
                (clean_sid, TRANSCRIPT_STATUS_PROCESSING),
            ).fetchone()
            if curr_processing:
                raise clip_mode.ClipModeError("DUPLICATE_PROCESSING: Transcrição já em andamento para esta fonte.")

            # 1.2 Reutiliza transcrição idêntica completada se force=False
            if not force:
                if clean_lang == "auto":
                    existing_completed = conn.execute(
                        """
                        SELECT * FROM clip_transcripts
                        WHERE source_id = ? AND provider = ? AND model_name = ? AND status = ?
                        ORDER BY created_at DESC LIMIT 1;
                        """,
                        (clean_sid, clean_provider, clean_model, TRANSCRIPT_STATUS_COMPLETED),
                    ).fetchone()
                else:
                    existing_completed = conn.execute(
                        """
                        SELECT * FROM clip_transcripts
                        WHERE source_id = ? AND provider = ? AND model_name = ? AND language = ? AND status = ?
                        ORDER BY created_at DESC LIMIT 1;
                        """,
                        (clean_sid, clean_provider, clean_model, clean_lang, TRANSCRIPT_STATUS_COMPLETED),
                    ).fetchone()
                if existing_completed:
                    logger.info(f"[CLIP_TRANSCRIPTION] Reutilizando transcrição COMPLETED existente '{existing_completed['id']}'.")
                    return {
                        "status": "reused",
                        "transcript_id": existing_completed["id"],
                        "transcript": dict(existing_completed),
                        "message": "Transcrição idêntica já existente reutilizada (use force=True para reprocessar).",
                    }

            # 1.3 Cria registro PROCESSING atomicamente dentro da mesma transação
            transcript_id = f"tr_{uuid.uuid4().hex[:12]}"
            now_iso = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                INSERT INTO clip_transcripts (
                    id, source_id, profile_id, provider, model_name, language,
                    status, full_text, started_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    transcript_id,
                    clean_sid,
                    profile_id,
                    clean_provider,
                    clean_model,
                    clean_lang,
                    TRANSCRIPT_STATUS_PROCESSING,
                    None,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            # Transação é comitada automaticamente na saída do bloco `with conn:`.
            # FFmpeg e STT executarão totalmente fora de qualquer transação SQLite.

    # 3. Execução Controlada da Transcrição
    provider = get_transcript_provider(clean_provider)
    audio_path = None
    try:
        # Extrai áudio mono 16kHz
        audio_path = extract_clip_source_audio(clean_sid, force=force, db_path=db_path)

        # Transcreve via provider desacoplado
        full_text, detected_lang, segments = provider.transcribe(
            audio_path=audio_path,
            language=clean_lang,
            model_name=clean_model,
        )

        completed_iso = datetime.now(timezone.utc).isoformat()

        # 4. Persiste Transcrição e Segmentos
        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_transcripts
                SET status = ?, full_text = ?, language = ?, completed_at = ?, updated_at = ?
                WHERE id = ?;
                """,
                (
                    TRANSCRIPT_STATUS_COMPLETED,
                    full_text,
                    detected_lang,
                    completed_iso,
                    completed_iso,
                    transcript_id,
                ),
            )

            # Insere segmentos ordenados com timestamps
            for seg in segments:
                seg_id = f"tseg_{uuid.uuid4().hex[:12]}"
                conn.execute(
                    """
                    INSERT INTO clip_transcript_segments (
                        id, transcript_id, source_id, sequence, start_seconds,
                        end_seconds, text, confidence, created_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        seg_id,
                        transcript_id,
                        clean_sid,
                        int(seg["sequence"]),
                        float(seg["start_seconds"]),
                        float(seg["end_seconds"]),
                        str(seg["text"]).strip(),
                        float(seg["confidence"]) if seg.get("confidence") is not None else None,
                        completed_iso,
                    ),
                )

        operator_console.log_operational_event(
            component="clip_transcription",
            severity="INFO",
            event_type="CLIP_TRANSCRIPT_COMPLETED",
            message=f"Transcrição '{transcript_id}' concluída para fonte '{clean_sid}' ({len(segments)} segmentos).",
            metadata={
                "transcript_id": transcript_id,
                "source_id": clean_sid,
                "provider": clean_provider,
                "model": clean_model,
                "segments_count": len(segments),
            },
            db_path=db_path,
        )

        logger.info(f"[CLIP_TRANSCRIPTION] Transcrição '{transcript_id}' concluída com sucesso ({len(segments)} segmentos).")

        return {
            "status": "completed",
            "transcript_id": transcript_id,
            "transcript": get_clip_transcript(transcript_id, db_path=db_path),
            "segments_count": len(segments),
        }

    except Exception as exc:
        err_msg = str(exc)[:400]
        now_failed = datetime.now(timezone.utc).isoformat()
        with clip_mode.get_connection(db_path) as conn:
            conn.execute(
                """
                UPDATE clip_transcripts
                SET status = ?, error_code = ?, error_message = ?, updated_at = ?
                WHERE id = ?;
                """,
                (
                    TRANSCRIPT_STATUS_FAILED,
                    "TRANSCRIPTION_ERROR",
                    err_msg,
                    now_failed,
                    transcript_id,
                ),
            )

        operator_console.log_operational_event(
            component="clip_transcription",
            severity="ERROR",
            event_type="CLIP_TRANSCRIPT_FAILED",
            message=f"Falha na transcrição '{transcript_id}' da fonte '{clean_sid}': {err_msg}",
            metadata={"transcript_id": transcript_id, "source_id": clean_sid, "error": err_msg},
            db_path=db_path,
        )

        logger.error(f"[CLIP_TRANSCRIPTION] Transcrição '{transcript_id}' falhou: {err_msg}")
        raise clip_mode.ClipModeError(f"Falha na transcrição da fonte: {err_msg}") from exc


def get_clip_transcript(transcript_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera detalhes de uma transcrição por ID."""
    init_clip_transcription_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        cursor = conn.execute("SELECT * FROM clip_transcripts WHERE id = ?;", (str(transcript_id).strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None


def get_latest_successful_transcript(source_id: str, db_path: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """Recupera a transcrição COMPLETED mais recente de uma fonte."""
    init_clip_transcription_db(db_path=db_path)
    with clip_mode.get_connection(db_path) as conn:
        cursor = conn.execute(
            """
            SELECT * FROM clip_transcripts
            WHERE source_id = ? AND status = ?
            ORDER BY completed_at DESC, created_at DESC LIMIT 1;
            """,
            (str(source_id).strip(), TRANSCRIPT_STATUS_COMPLETED),
        )
        row = cursor.fetchone()
        return dict(row) if row else None


def list_clip_transcript_segments(
    transcript_id: str,
    limit: Optional[int] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Lista os segmentos de texto e timestamps ordenados temporalmente."""
    init_clip_transcription_db(db_path=db_path)
    query = "SELECT * FROM clip_transcript_segments WHERE transcript_id = ? ORDER BY sequence ASC"
    params: List[Any] = [str(transcript_id).strip()]
    if limit is not None:
        query += " LIMIT ?"
        params.append(int(limit))

    with clip_mode.get_connection(db_path) as conn:
        cursor = conn.execute(query, params)
        return [dict(r) for r in cursor.fetchall()]
