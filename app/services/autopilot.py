import re
import string
from typing import Any, Dict, List, Optional
from loguru import logger

from app.models import const
from app.services import llm

MIN_IDEAS_COUNT = 1
MAX_IDEAS_COUNT = 30
DEFAULT_IDEAS_COUNT = 15

DEFAULT_TIKTOK_TARGET = 15
MAX_TIKTOK_TARGET = 15
DEFAULT_YOUTUBE_TARGET = 10
MAX_YOUTUBE_TARGET = 10
DEFAULT_DESIRED_STOCK = 30

import unicodedata

_NORMALIZE_PUNCT_RE = re.compile(r"[" + re.escape(string.punctuation) + r"".join(re.escape(p) for p in const.PUNCTUATIONS) + r"]")


def normalize_topic(text: str) -> str:
    """Normaliza um tema para comparação e deduplicação barata.
    
    Regras:
    - trim
    - lowercase
    - remover acentos (NFKD)
    - remover pontuação básica (incluindo pontuações do app.models.const)
    - remover espaços múltiplos
    """
    if not text:
        return ""
    cleaned = text.strip().lower()
    cleaned = "".join(
        c for c in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(c)
    )
    cleaned = _NORMALIZE_PUNCT_RE.sub(" ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def deduplicate_ideas(ideas: List[str]) -> List[str]:
    """Remove duplicatas exatas normalizadas e linhas vazias, preservando ordem original."""
    seen = set()
    result = []
    for idea in ideas:
        cleaned = (idea or "").strip()
        if not cleaned:
            continue
        normalized = normalize_topic(cleaned)
        if not normalized:
            continue
        if normalized not in seen:
            seen.add(normalized)
            result.append(cleaned)
    return result


def _clean_idea_line(line: str) -> str:
    """Remove numerações, marcadores e aspas do início/fim de cada linha de ideia."""
    line = line.strip()
    # Remove marcação tipo 1., 1 -, - , *, •
    line = re.sub(r"^(\d+[\.\-\)]\s*|[\*\-•\>]\s*)", "", line).strip()
    # Remove aspas externas se houver
    if (line.startswith('"') and line.endswith('"')) or (line.startswith("'") and line.endswith("'")):
        line = line[1:-1].strip()
    return line


def build_ideas_prompt(niche: str, count: int, language: str = "") -> str:
    """Constrói o prompt curto para geração de ideias em uma única chamada ao LLM."""
    count = max(MIN_IDEAS_COUNT, min(MAX_IDEAS_COUNT, int(count)))
    normalized_lang = (language or "").strip().lower().replace("_", "-")
    is_pt = normalized_lang in {
        "pt",
        "pt-br",
        "português",
        "portugues",
        "português (brasil)",
        "portugues (brasil)",
        "portuguese (brazil)",
    }

    if is_pt:
        return f"""Você é um especialista em criação de conteúdo viral para vídeos curtos (Shorts, TikTok, Reels).

Gere exatamente {count} ideias de temas para vídeos no nicho: "{niche}".

Regras obrigatórias:
1. Gere APENAS temas/títulos conceituais, NÃO gere roteiros.
2. Cada tema deve ser compreensível em 3 segundos e despertar alta curiosidade.
3. Evite clickbait enganoso ou falso.
4. Varie as estruturas dos temas para não repetir o mesmo formato em todos. Use formatos como:
   - "Você sabia..."
   - "Por que..."
   - "O que aconteceria se..."
   - "3 fatos sobre..."
   - "A verdade sobre..."
   - pergunta direta
   - comparação surpreendente
   - mito vs realidade
5. Escreva em português do Brasil (pt-BR), natural e direto.
6. Responda APENAS com a lista numerada de 1 a {count}, uma ideia por linha, sem introdução, sem explicações e sem comentários adicionais.
""".strip()

    return f"""You are an expert short-form viral content creator (Shorts, TikTok, Reels).

Generate exactly {count} video topic ideas for the niche: "{niche}".

Mandatory rules:
1. Generate ONLY topic titles/themes, DO NOT generate scripts.
2. Each topic must be instantly understandable and trigger curiosity.
3. Avoid misleading clickbait.
4. Vary topic structures across the list. Use formats like:
   - "Did you know..."
   - "Why..."
   - "What would happen if..."
   - "3 facts about..."
   - "The truth about..."
   - direct questions
   - surprising comparisons
   - myth vs reality
5. Write in the requested language: {language or "English"}.
6. Output ONLY the numbered list from 1 to {count}, one idea per line, with no introductory or concluding text.
""".strip()


def generate_ideas(
    niche: str,
    count: int = DEFAULT_IDEAS_COUNT,
    language: str = "pt-BR",
    app_config: Optional[Any] = None,
) -> List[str]:
    """Gera ideias de temas usando o LLM configurado, deduplica e retorna a lista."""
    niche = (niche or "").strip()
    if not niche:
        return []

    count = max(MIN_IDEAS_COUNT, min(MAX_IDEAS_COUNT, int(count)))
    prompt = build_ideas_prompt(niche=niche, count=count, language=language)

    logger.info(f"[Autopilot] Generating {count} ideas for niche='{niche}', lang='{language}'")
    try:
        response = llm._generate_response(prompt=prompt, app_config=app_config)
    except Exception as exc:
        logger.error(f"[Autopilot] LLM idea generation failed: {exc}")
        raise exc

    if not response:
        logger.warning("[Autopilot] LLM returned empty response for ideas generation")
        return []

    raw_lines = response.strip().splitlines()
    parsed_ideas = []
    for line in raw_lines:
        cleaned = _clean_idea_line(line)
        if cleaned:
            parsed_ideas.append(cleaned)

    unique_ideas = deduplicate_ideas(parsed_ideas)
    return unique_ideas[:count]


def calculate_stock(tasks: List[Dict[str, Any]], desired_stock: int = DEFAULT_DESIRED_STOCK) -> Dict[str, Any]:
    """Calcula o estoque de vídeos a partir do histórico/TaskManager existente.
    
    Separa:
    - prontos: tarefas concluídas e com vídeo que NÃO foram publicadas (cross_post_state != 'complete')
    - processando: tarefas em processamento (TASK_STATE_PROCESSING)
    - pendentes: tarefas na fila (TASK_STATE_PENDING)
    
    Estoque atual: prontos + processando + pendentes
    Déficit: max(0, estoque_desejado - estoque_atual)
    """
    ready_count = 0
    processing_count = 0
    pending_count = 0

    for task in tasks:
        state = task.get("state")
        cross_post_state = task.get("cross_post_state")
        has_video = bool(task.get("video_file"))

        # Publicados são excluídos do estoque pronto
        if cross_post_state == const.CROSS_POST_STATE_COMPLETE:
            continue

        if state == const.TASK_STATE_COMPLETE or (has_video and state != const.TASK_STATE_FAILED and state != const.TASK_STATE_PROCESSING):
            ready_count += 1
        elif state == const.TASK_STATE_PROCESSING:
            processing_count += 1
        elif state == const.TASK_STATE_PENDING:
            pending_count += 1

    total = ready_count + processing_count + pending_count
    deficit = max(0, desired_stock - total)
    is_sufficient = total >= desired_stock

    return {
        "desired": desired_stock,
        "ready": ready_count,
        "processing": processing_count,
        "pending": pending_count,
        "total": total,
        "deficit": deficit,
        "is_sufficient": is_sufficient,
    }


def plan_distribution(
    selected_count: int,
    tiktok_active: bool = True,
    tiktok_target: int = DEFAULT_TIKTOK_TARGET,
    youtube_active: bool = True,
    youtube_target: int = DEFAULT_YOUTUBE_TARGET,
) -> List[List[str]]:
    """Planeja as plataformas de destino para cada vídeo selecionado.
    
    Regras:
    - Se TikTok + YouTube ativos:
      1 a 10 (até meta YouTube): ["tiktok", "youtube"]
      11 a 15 (até meta TikTok): ["tiktok"]
    - Se só TikTok: todos ["tiktok"] até meta TikTok
    - Se só YouTube: todos ["youtube"] até meta YouTube
    - Se quantidade < metas: distribui apenas o necessário
    
    O planejamento NÃO publica nada, apenas retorna a lista de plataformas por vídeo.
    """
    if selected_count <= 0:
        return []

    # Limitar metas às cotas permitidas nesta fase
    effective_tiktok_target = min(MAX_TIKTOK_TARGET, max(0, int(tiktok_target))) if tiktok_active else 0
    effective_youtube_target = min(MAX_YOUTUBE_TARGET, max(0, int(youtube_target))) if youtube_active else 0

    plan: List[List[str]] = []
    assigned_tiktok = 0
    assigned_youtube = 0

    for _ in range(selected_count):
        item_platforms: List[str] = []
        if assigned_tiktok < effective_tiktok_target:
            item_platforms.append("tiktok")
            assigned_tiktok += 1

        if assigned_youtube < effective_youtube_target:
            item_platforms.append("youtube")
            assigned_youtube += 1

        plan.append(item_platforms)

    return plan


def assign_batch_narrative_structures(
    selected_count: int,
    recent_structures: Optional[List[str]] = None,
) -> List[str]:
    """Distribui estruturas narrativas entre os itens do lote de forma variada.

    Garante que itens consecutivos nunca usem a mesma estrutura e evita repetir
    a última estrutura registrada no histórico.
    """
    if selected_count <= 0:
        return []

    from app.services import safety_gate

    assigned: List[str] = []
    current_history = list(recent_structures or [])

    for i in range(selected_count):
        struct = safety_gate.get_next_narrative_structure(
            recent_structures=current_history,
            current_index=i,
        )
        assigned.append(struct)
        current_history = [struct] + current_history[:5]

    return assigned
