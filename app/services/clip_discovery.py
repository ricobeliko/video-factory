"""
Clip Discovery Service (Fase V11-B — Transcript & Segment Discovery).

Implementa algoritmo de descoberta heurística determinística de cortes candidatos
a partir de transcrições completas com timestamps, sem utilização de LLM/IA:
- Janelas de corte direcionadas a formatos curtos (15s–90s, sweet-spot 25s–60s, teto 180s)
- Pontuação transparente (0–100) baseada em duração, limites de frase, densidade de fala, ganchos e autocontenção
- Explicação clara de cada corte persistida em selection_reason
- Deduplicação e preservação de segmentos manuais e status existentes
"""
from datetime import datetime, timezone
import re
import sqlite3
from typing import Any, Dict, List, Optional, Tuple
import uuid

from loguru import logger

from app.services import clip_mode, clip_transcription, operator_console

# ---------------------------------------------------------------------------
# Constantes Heurísticas
# ---------------------------------------------------------------------------

DEFAULT_MAX_DISCOVERED_CANDIDATES = 10

# Limites temporais (em segundos)
MIN_CANDIDATE_DURATION = 15.0
SWEET_SPOT_MIN_DURATION = 25.0
SWEET_SPOT_MAX_DURATION = 60.0
MAX_WINDOW_DURATION = 90.0
HARD_MAX_DURATION = 180.0

# Sinais textuais de gancho (Hooks)
HOOK_QUESTIONS = (
    "?", "você sabia", "voce sabia", "já pensou", "ja pensou", "por que",
    "porque", "como", "qual é", "qual e", "o que acontece", "why", "how", "did you know",
)
HOOK_LISTS = (
    "primeiro", "segundo", "terceiro", "três coisas", "tres coisas", "3 coisas",
    "3 motivos", "motivos", "regras", "passos", "dicas", "erros", "top",
    "first", "three things", "tips", "reasons",
)
HOOK_CONTRASTS = (
    "o segredo", "o problema é", "o problema e", "na verdade", "o maior erro",
    "mas a verdade", "the secret", "the problem is", "actually", "the real truth",
)

# Conjunções ou palavras que indicam início/fim truncado (Self-containment penalties)
DANGLING_START_WORDS = (
    "e ", "mas ", "porém ", "porem ", "ou ", "então ", "entao ", "já que ", "ja que ",
    "porque ", "por que ", "portanto ", "and ", "but ", "so ", "or ", "because ", "although ",
)
DANGLING_END_WORDS = (
    " e", " mas", " ou", " porém", " porem", " que", " para", " com", " and", " but", " that", " with",
)


def _calculate_speech_density(text: str, duration_seconds: float) -> float:
    """Calcula a taxa de palavras por segundo."""
    if duration_seconds <= 0:
        return 0.0
    words = re.findall(r"\b\w+\b", text)
    return round(len(words) / duration_seconds, 2)


def score_candidate_window(
    text: str,
    duration_seconds: float,
    start_text: str,
    end_text: str,
) -> Tuple[float, str]:
    """
    Calcula a pontuação determinística explicável (0–100) para um candidato temporal:
    1. duration_score (0–25)
    2. sentence_boundary_score (0–25)
    3. speech_density_score (0–20)
    4. hook_signal_score (0–15)
    5. self_containment_penalty (-15 a 0)
    """
    reasons: List[str] = []

    # 1. Pontuação de Duração (0–25)
    if SWEET_SPOT_MIN_DURATION <= duration_seconds <= SWEET_SPOT_MAX_DURATION:
        dur_score = 25.0
        reasons.append(f"dur={duration_seconds:.1f}s (sweet-spot 25-60s)")
    elif MIN_CANDIDATE_DURATION <= duration_seconds < SWEET_SPOT_MIN_DURATION:
        dur_score = 18.0
        reasons.append(f"dur={duration_seconds:.1f}s (curto 15-25s)")
    elif SWEET_SPOT_MAX_DURATION < duration_seconds <= MAX_WINDOW_DURATION:
        dur_score = 18.0
        reasons.append(f"dur={duration_seconds:.1f}s (médio 60-90s)")
    elif MAX_WINDOW_DURATION < duration_seconds <= 120.0:
        dur_score = 12.0
        reasons.append(f"dur={duration_seconds:.1f}s (longo 90-120s)")
    elif 120.0 < duration_seconds <= HARD_MAX_DURATION:
        dur_score = 8.0
        reasons.append(f"dur={duration_seconds:.1f}s (muito longo 120-180s)")
    else:
        dur_score = 0.0
        reasons.append(f"dur={duration_seconds:.1f}s (fora do alvo)")

    # 2. Pontuação de Limites de Frase (0–25)
    boundary_score = 0.0
    clean_start = start_text.strip()
    clean_end = end_text.strip()

    # Início limpo (letra maiúscula e sem conjunção óbvia)
    if clean_start and clean_start[0].isupper():
        boundary_score += 12.5
    else:
        boundary_score += 5.0

    # Término limpo (pontuação final ., !, ?)
    if clean_end and clean_end[-1] in (".", "!", "?"):
        boundary_score += 12.5
        reasons.append("frase fechada com pontuação")
    else:
        reasons.append("sem pontuação final estrita")

    # 3. Densidade de Fala (0–20)
    density = _calculate_speech_density(text, duration_seconds)
    if 2.0 <= density <= 3.5:
        density_score = 20.0
        reasons.append(f"ritmo ideal ({density} pal/s)")
    elif 1.5 <= density < 2.0 or 3.5 < density <= 4.2:
        density_score = 15.0
        reasons.append(f"ritmo aceitável ({density} pal/s)")
    elif 1.0 <= density < 1.5:
        density_score = 10.0
        reasons.append(f"ritmo lento/pausas ({density} pal/s)")
    else:
        density_score = 5.0
        reasons.append(f"ritmo atípico ({density} pal/s)")

    # 4. Sinais de Gancho (Hook Signals: 0–15)
    hook_score = 0.0
    lower_start = start_text.lower()
    if any(q in lower_start for q in HOOK_QUESTIONS):
        hook_score = 15.0
        reasons.append("gancho: pergunta de abertura")
    elif any(l in lower_start for l in HOOK_LISTS):
        hook_score = 12.0
        reasons.append("gancho: sinal de lista/número")
    elif any(c in lower_start for c in HOOK_CONTRASTS):
        hook_score = 10.0
        reasons.append("gancho: sinal de revelação/contraste")

    # 5. Penalidades de Autocontenção (-15 a 0)
    penalty = 0.0
    lower_full = text.strip().lower()
    for dangling in DANGLING_START_WORDS:
        if lower_full.startswith(dangling):
            penalty -= 10.0
            reasons.append(f"penalidade: início truncado ('{dangling.strip()}')")
            break

    for dangling in DANGLING_END_WORDS:
        if lower_full.endswith(dangling):
            penalty -= 5.0
            reasons.append(f"penalidade: término truncado ('{dangling.strip()}')")
            break

    raw_total = dur_score + boundary_score + density_score + hook_score + penalty
    final_score = max(0.0, min(100.0, round(raw_total, 1)))

    reason_str = f"score={final_score:.1f}; " + "; ".join(reasons)
    return final_score, reason_str


def _generate_candidate_title(text: str) -> str:
    """Gera um título curto para o segmento a partir das primeiras palavras."""
    clean = re.sub(r"\s+", " ", text).strip()
    words = clean.split(" ")
    if len(words) <= 7:
        title = clean
    else:
        title = " ".join(words[:7]) + "..."
    return title[:75]


# ---------------------------------------------------------------------------
# Descoberta e Persistência de Candidatos
# ---------------------------------------------------------------------------

def discover_clip_candidates(
    transcript_id: str,
    max_candidates: int = DEFAULT_MAX_DISCOVERED_CANDIDATES,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Descobre cortes candidatos a partir de uma transcrição concluída:
    - Valida se o transcript existe e está COMPLETED
    - Rejeita transcripts incompletos com ClipValidationError
    - Agrupa segmentos em janelas temporais coerentes (15s–90s, teto 180s)
    - Calcula pontuação determinística (0–100) com justificativa transparente
    - Persiste os top N candidatos em clip_segments (selection_method='heuristic', status='CANDIDATE')
    - Deduplicação: não insere candidatos temporalmente idênticos já existentes
    - Preserva segmentos manuais e status já alterados (SELECTED/REJECTED)
    - Zero chamadas LLM / Zero chamadas HTTP
    """
    operator_console.require_primary_instance(db_path=db_path)

    clean_tid = str(transcript_id or "").strip()
    transcript = clip_transcription.get_clip_transcript(clean_tid, db_path=db_path)
    if not transcript:
        raise clip_mode.ClipValidationError(f"Transcrição '{clean_tid}' não encontrada.")

    if transcript.get("status") != clip_transcription.TRANSCRIPT_STATUS_COMPLETED:
        raise clip_mode.ClipValidationError(
            f"Transcrição '{clean_tid}' não está concluída (status atual: {transcript.get('status')})."
        )

    source_id = transcript.get("source_id")
    source = clip_mode.get_clip_source(source_id, db_path=db_path)
    if not source:
        raise clip_mode.ClipValidationError(f"Fonte '{source_id}' associada à transcrição não encontrada.")

    source_duration = float(source.get("duration_seconds") or 0.0)
    source_profile_id = source.get("profile_id") or "default"

    # Busca os segmentos da transcrição ordenados temporalmente
    segments = clip_transcription.list_clip_transcript_segments(clean_tid, db_path=db_path)
    if not segments:
        logger.warning(f"[CLIP_DISCOVERY] Transcrição '{clean_tid}' não contém segmentos de texto.")
        return []

    # 1. Agrupamento em Janelas Candidatas
    candidate_windows: List[Dict[str, Any]] = []
    n = len(segments)

    for i in range(n):
        seg_i = segments[i]
        start_time = float(seg_i["start_seconds"])
        window_texts = []

        for j in range(i, n):
            seg_j = segments[j]
            end_time = float(seg_j["end_seconds"])
            dur = end_time - start_time

            # Respeita o teto máximo de 180s e a duração total da mídia
            if dur > HARD_MAX_DURATION or end_time > source_duration + 0.1:
                break

            window_texts.append(seg_j["text"].strip())
            full_window_text = " ".join(window_texts)

            # Janela elegível para avaliação (entre 15s e 90s, ou até 120s se fechar frase)
            if MIN_CANDIDATE_DURATION <= dur <= MAX_WINDOW_DURATION:
                last_char = seg_j["text"].strip()[-1] if seg_j["text"].strip() else ""
                is_sentence_end = last_char in (".", "!", "?")

                # Se fecha frase OU se atingiu a faixa ideal (25s–60s)
                if is_sentence_end or (SWEET_SPOT_MIN_DURATION <= dur <= SWEET_SPOT_MAX_DURATION):
                    score, reason = score_candidate_window(
                        text=full_window_text,
                        duration_seconds=dur,
                        start_text=seg_i["text"],
                        end_text=seg_j["text"],
                    )

                    candidate_windows.append({
                        "source_id": source_id,
                        "profile_id": source_profile_id,
                        "transcript_id": clean_tid,
                        "start_seconds": round(start_time, 3),
                        "end_seconds": round(end_time, 3),
                        "duration_seconds": round(dur, 3),
                        "text": full_window_text,
                        "title": _generate_candidate_title(full_window_text),
                        "selection_method": "heuristic",
                        "selection_reason": reason,
                        "score": score,
                    })

    if not candidate_windows:
        logger.info(f"[CLIP_DISCOVERY] Nenhuma janela atendeu aos critérios temporais mínimos para '{clean_tid}'.")
        return []

    # 2. Ordenação Determinística: score DESC, start_seconds ASC
    candidate_windows.sort(key=lambda c: (-c["score"], c["start_seconds"]))

    # 3. Filtragem de Sobreposição Agressiva (Deduplicação de janelas muito parecidas)
    filtered_candidates: List[Dict[str, Any]] = []
    for cand in candidate_windows:
        # Se já tivermos candidatos, evita pegar outro com início quase idêntico (<5s de diferença)
        overlap = False
        for chosen in filtered_candidates:
            if abs(cand["start_seconds"] - chosen["start_seconds"]) < 5.0:
                overlap = True
                break
        if not overlap:
            filtered_candidates.append(cand)
        if len(filtered_candidates) >= max_candidates:
            break

    # 4. Persistência em clip_segments
    persisted_candidates: List[Dict[str, Any]] = []
    now_iso = datetime.now(timezone.utc).isoformat()

    with clip_mode.get_connection(db_path) as conn:
        for cand in filtered_candidates:
            # Checa se já existe um segmento heuristic exatamente igual no banco
            existing = conn.execute(
                """
                SELECT id, status FROM clip_segments
                WHERE source_id = ?
                  AND ABS(start_seconds - ?) < 0.2
                  AND ABS(end_seconds - ?) < 0.2
                  AND selection_method = 'heuristic';
                """,
                (source_id, cand["start_seconds"], cand["end_seconds"]),
            ).fetchone()

            if existing:
                # Já existe: preserva o ID e o status (inclusive SELECTED/REJECTED)
                row = conn.execute("SELECT * FROM clip_segments WHERE id = ?;", (existing["id"],)).fetchone()
                if row:
                    persisted_candidates.append(dict(row))
                continue

            seg_id = f"seg_{uuid.uuid4().hex[:12]}"
            conn.execute(
                """
                INSERT INTO clip_segments (
                    id, source_id, profile_id, start_seconds, end_seconds,
                    duration_seconds, title, selection_method, selection_reason,
                    status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    seg_id,
                    source_id,
                    source_profile_id,
                    cand["start_seconds"],
                    cand["end_seconds"],
                    cand["duration_seconds"],
                    cand["title"],
                    "heuristic",
                    cand["selection_reason"],
                    clip_mode.SEGMENT_STATUS_CANDIDATE,
                    now_iso,
                    now_iso,
                ),
            )

            row = conn.execute("SELECT * FROM clip_segments WHERE id = ?;", (seg_id,)).fetchone()
            if row:
                persisted_candidates.append(dict(row))

    operator_console.log_operational_event(
        component="clip_discovery",
        severity="INFO",
        event_type="CLIP_CANDIDATES_DISCOVERED",
        message=f"Descoberta de cortes concluída para fonte '{source_id}': {len(persisted_candidates)} candidatos persistidos.",
        metadata={
            "transcript_id": clean_tid,
            "source_id": source_id,
            "candidates_count": len(persisted_candidates),
        },
        db_path=db_path,
    )

    logger.info(
        f"[CLIP_DISCOVERY] {len(persisted_candidates)} candidatos persistidos com sucesso "
        f"para fonte '{source_id}' a partir do transcript '{clean_tid}'."
    )

    return persisted_candidates
