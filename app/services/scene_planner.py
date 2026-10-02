"""
app/services/scene_planner.py
=============================
V16.4 — Scene-Based Video Generation: Scene Planner.

Responsabilidade:
Transformar o roteiro (video_script) em um plano ordenado de cenas (ScenePlan)
com indexação determinística, segmentação semântica, termos de busca específicos
por cena e estimativa temporal, sem dependência de rede/LLM no baseline local.
"""

from __future__ import annotations

import hashlib
import re
from typing import Any, List, Optional, Tuple

from loguru import logger

from app.models.schema import ScenePlan, ScenePlanItem, VideoParams
from app.utils import utils

# Stopwords mínimas para pt-BR e EN para garantir extração limpa de termos visuais
_PT_STOPWORDS = {
    "de", "a", "o", "que", "e", "do", "da", "em", "um", "para", "é", "com",
    "não", "uma", "os", "no", "se", "na", "por", "mais", "as", "dos", "como",
    "mas", "foi", "ao", "ele", "das", "tem", "à", "seu", "sua", "ou", "ser",
    "quando", "muito", "há", "nos", "já", "está", "eu", "também", "só", "pelo",
    "pela", "até", "isso", "ela", "entre", "era", "depois", "sem", "mesmo",
    "aos", "ter", "seus", "quem", "nas", "me", "esse", "eles", "estão", "você",
    "tinha", "foram", "essa", "num", "nem", "suas", "meu", "às", "minha", "têm",
    "numa", "pelos", "elas", "havia", "seja", "qual", "será", "nós", "tenho",
    "lhe", "deles", "essas", "esses", "pelas", "este", "fosse", "dele", "tu",
    "te", "vocês", "vos", "lhes", "meus", "minhas", "teu", "tua", "teus", "tuas",
    "onde", "aqui", "ali", "então", "assim", "tudo", "nada", "cada", "sobre",
    "durante", "pouco", "antes", "ainda", "apenas", "pois", "contra",
}

_EN_STOPWORDS = {
    "the", "a", "an", "and", "or", "but", "in", "on", "at", "to", "for", "with",
    "by", "about", "against", "between", "into", "through", "during", "before",
    "after", "above", "below", "from", "up", "down", "in", "out", "on", "off",
    "over", "under", "again", "further", "then", "once", "here", "there", "when",
    "where", "why", "how", "all", "any", "both", "each", "few", "more", "most",
    "other", "some", "such", "no", "nor", "not", "only", "own", "same", "so",
    "than", "too", "very", "s", "t", "can", "will", "just", "don", "should", "now",
}

ALL_STOPWORDS = _PT_STOPWORDS | _EN_STOPWORDS


class ScenePlanError(ValueError):
    """Exceção levantada quando o planejamento de cenas falha ou viola o contrato."""
    def __init__(self, message: str, reason_code: str = "SCENE_INVALID"):
        super().__init__(message)
        self.reason_code = reason_code


def _clean_text(text: str) -> str:
    """Remove tags de pausa e normaliza espaçamentos mantendo acentuação."""
    text = utils.remove_pause_tags(text or "")
    text = re.sub(r"[ \t]+", " ", text)
    return text.strip()


def _split_into_sentences(text: str) -> List[str]:
    """
    Divide o texto em frases com base em pontuação e quebras de linha.
    Preserva acentuação e evita quebrar números decimais ou abreviações comuns.
    """
    if not text:
        return []

    # Quebra inicial por parágrafos
    paragraphs = [p.strip() for p in re.split(r"\n+", text) if p.strip()]
    raw_sentences = []

    for p in paragraphs:
        # Regex para pontuações de término de frase: . ! ? ; ou reticências (...)
        # seguido de espaço ou fim de linha, sem quebrar números tipo 3.14
        parts = re.split(r"(?<=[.!?;\n])\s+", p)
        for part in parts:
            part = part.strip()
            if part:
                raw_sentences.append(part)

    # Segunda passagem: mesclar fragmentos excessivamente curtos (< 15 caracteres ou < 3 palavras)
    merged: List[str] = []
    for s in raw_sentences:
        if not merged:
            merged.append(s)
            continue

        words = s.split()
        if len(s) < 15 or len(words) < 3:
            # Mescla com a frase anterior para evitar micro-cenas
            merged[-1] = f"{merged[-1]} {s}"
        else:
            merged.append(s)

    # Terceira passagem: dividir frases gigantes (> 180 caracteres ou > 30 palavras)
    final_segments: List[str] = []
    for s in merged:
        words = s.split()
        if len(s) > 180 and len(words) > 30:
            # Tenta dividir em vírgula, travessão ou conectivo
            subparts = re.split(r"(?<=[,-])\s+", s)
            current_chunk = ""
            for sp in subparts:
                if not current_chunk:
                    current_chunk = sp
                elif len(current_chunk) + len(sp) < 140:
                    current_chunk = f"{current_chunk} {sp}"
                else:
                    final_segments.append(current_chunk.strip())
                    current_chunk = sp
            if current_chunk.strip():
                final_segments.append(current_chunk.strip())
        else:
            final_segments.append(s)

    return [seg.strip() for seg in final_segments if seg.strip()]


def _extract_scene_search_terms(
    narration: str,
    video_subject: Optional[str] = None,
    max_terms: int = 3,
) -> List[str]:
    """
    Extrai termos de busca visuais específicos da narração da cena.
    Remove stopwords, pontuações, deduplica mantendo a ordem e aplica limite.
    """
    cleaned = re.sub(r"[^\w\s-]", " ", narration.lower())
    tokens = [t.strip() for t in cleaned.split() if t.strip()]

    meaningful = [
        t for t in tokens
        if len(t) >= 3 and t not in ALL_STOPWORDS and not t.isdigit()
    ]

    terms: List[str] = []

    # 1. Frases-chave de 2 palavras se houver tokens contíguos
    if len(meaningful) >= 2:
        bigram = f"{meaningful[0]} {meaningful[1]}"
        terms.append(bigram)

    # 2. Palavras individuais mais salientes
    for token in meaningful:
        if token not in terms:
            terms.append(token)
        if len(terms) >= max_terms:
            break

    # 3. Se ainda faltam termos e temos video_subject, contextualiza
    if video_subject:
        subj_clean = re.sub(r"[^\w\s-]", " ", video_subject.lower()).strip()
        if subj_clean and subj_clean not in terms:
            terms.append(subj_clean)

    # 4. Fallback garantido se nada foi extraído
    if not terms:
        # Usa primeiras palavras limpas da própria narração
        fallback_words = [w for w in tokens if len(w) >= 2][:3]
        if fallback_words:
            terms.append(" ".join(fallback_words))
        elif video_subject:
            terms.append(video_subject.strip())
        else:
            terms.append("cinematic visual")

    # Deduplicação final preservando ordem e limitando quantidade
    seen = set()
    deduped = []
    for term in terms:
        t_clean = term.strip()
        if t_clean and t_clean not in seen:
            seen.add(t_clean)
            deduped.append(t_clean)
        if len(deduped) >= max_terms:
            break

    return deduped


def _infer_visual_intent(narration: str) -> str:
    """Classificador leve e determinístico de intenção visual."""
    text_lower = narration.lower()

    if re.search(r"\b(19\d\d|20\d\d|história|século|passado|antigo|antiga)\b", text_lower):
        return "archival footage"
    if re.search(r"\b(cidade|rua|prédio|avenida|trânsito|metrópole|city|urban)\b", text_lower):
        return "urban scene"
    if re.search(r"\b(mar|oceano|floresta|rio|montanha|natureza|árvore|céu|nature)\b", text_lower):
        return "nature landscape"
    if re.search(r"\b(espaço|lua|foguete|universo|estrela|tecnologia|robô|ia|space)\b", text_lower):
        return "technology/space"
    if re.search(r"\b(pessoa|homem|mulher|rosto|gente|olhar|sorriso|person)\b", text_lower):
        return "person portrait"

    return "cinematic stock"


def validate_scene_plan(
    scene_plan: ScenePlan,
    strict: bool = True,
) -> Tuple[bool, List[str]]:
    """
    Valida as regras fundamentais do ScenePlan (Fail-closed):
    - total_scenes > 0 e len(scenes) > 0 (SCENE_PLAN_EMPTY)
    - Índices sequenciais iniciando em 1 (SCENE_INDEX_INVALID / SCENE_ORDER_INVALID)
    - Narração não-vazia para cada cena (SCENE_INVALID)
    - search_terms não-vazios para cada cena no modo estrito (SCENE_TERMS_EMPTY)
    - Sem índices duplicados (SCENE_INDEX_INVALID)
    """
    reasons: List[str] = []

    if not scene_plan.scenes or scene_plan.total_scenes <= 0:
        reasons.append("SCENE_PLAN_EMPTY")
        return False, reasons

    seen_indices = set()
    for idx, scene in enumerate(scene_plan.scenes):
        expected_index = idx + 1
        if scene.scene_index in seen_indices:
            reasons.append("SCENE_INDEX_INVALID")
        seen_indices.add(scene.scene_index)

        if scene.scene_index != expected_index:
            reasons.append("SCENE_ORDER_INVALID")

        if not scene.narration or not scene.narration.strip():
            reasons.append("SCENE_INVALID")

        if strict and (not scene.search_terms or not any(t.strip() for t in scene.search_terms)):
            reasons.append("SCENE_TERMS_EMPTY")

    # Remove duplicados de reasons preservando ordem
    unique_reasons = list(dict.fromkeys(reasons))
    is_valid = len(unique_reasons) == 0
    return is_valid, unique_reasons


def plan_scenes(
    video_script: str,
    params: Optional[VideoParams] = None,
    target_scene_duration: float = 5.0,
    task_id: Optional[str] = None,
) -> ScenePlan:
    """
    Ponto de entrada do planejador de cenas.
    Transforma o roteiro em um ScenePlan determinístico.
    """
    tid_str = task_id or "unknown"
    logger.info(f"[SCENE_PLAN][START] task_id={tid_str} script_len={len(video_script or '')}")

    cleaned = _clean_text(video_script or "")
    if not cleaned:
        logger.error(f"[SCENE_PLAN][BLOCK] task_id={tid_str} reason=SCENE_PLAN_EMPTY")
        raise ScenePlanError("SCENE_PLAN_EMPTY: video_script is empty or whitespace only", reason_code="SCENE_PLAN_EMPTY")

    script_hash = hashlib.sha256(cleaned.encode("utf-8")).hexdigest()
    segments = _split_into_sentences(cleaned)

    if not segments:
        logger.error(f"[SCENE_PLAN][BLOCK] task_id={tid_str} reason=SCENE_PLAN_EMPTY")
        raise ScenePlanError("SCENE_PLAN_EMPTY: no valid sentences could be extracted", reason_code="SCENE_PLAN_EMPTY")

    video_subject = params.video_subject if params else None
    if params and getattr(params, "video_clip_duration", None):
        target_scene_duration = float(params.video_clip_duration)

    scenes: List[ScenePlanItem] = []
    for idx, narration in enumerate(segments):
        scene_index = idx + 1
        search_terms = _extract_scene_search_terms(
            narration=narration,
            video_subject=video_subject,
            max_terms=3,
        )

        # Estimativa de duração da cena com base no número de palavras (~2.5 palavras/segundo)
        words_count = len(narration.split())
        est_duration = max(2.5, min(12.0, round(words_count / 2.5, 2)))

        visual_intent = _infer_visual_intent(narration)

        scene_item = ScenePlanItem(
            scene_index=scene_index,
            narration=narration,
            search_terms=search_terms,
            duration_hint=est_duration,
            visual_intent=visual_intent,
            source_strategy="stock_video",
        )
        scenes.append(scene_item)

    scene_plan = ScenePlan(
        scenes=scenes,
        total_scenes=len(scenes),
        script_hash=script_hash,
        planner_version="v1.0",
    )

    is_valid, reasons = validate_scene_plan(scene_plan, strict=True)
    if not is_valid:
        primary_reason = reasons[0]
        logger.error(f"[SCENE_PLAN][BLOCK] task_id={tid_str} reason={primary_reason} reasons={reasons}")
        raise ScenePlanError(f"{primary_reason}: invalid scene plan {reasons}", reason_code=primary_reason)

    logger.info(f"[SCENE_PLAN][PASS] task_id={tid_str} scenes_count={len(scenes)}")
    return scene_plan
