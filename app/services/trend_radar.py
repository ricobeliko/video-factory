import contextlib
import difflib
import hashlib
import json
import os
import re
import sqlite3
import time
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services.trends.base import (
    CONFIDENCE_HIGH,
    CONFIDENCE_LOW,
    CONFIDENCE_MEDIUM,
    STATUS_APPROVED,
    STATUS_NEW,
    STATUS_REJECTED,
    STATUS_REVIEW,
    STATUS_USED,
    VALID_STATUSES,
    VERIFICATION_MULTI,
    VERIFICATION_SINGLE,
    BaseTrendProvider,
    TrendSignal,
)
from app.services.trends.google_trends import GoogleTrendsProvider
from app.services.trends.reddit import RedditTrendsProvider
from app.services.trends.rss import RssNewsProvider
from app.services.trends.tiktok_creative import TikTokCreativeProvider

# Caminho opcional override do SQLite (útil em testes)
DB_PATH: Optional[str] = None

# Cache em memória (TTL: 30 minutos)
_CACHE_TTL_SECONDS = 1800
_TREND_CACHE: Dict[Tuple[str, str, str], Tuple[float, List[Dict[str, Any]]]] = {}


def clear_cache() -> None:
    """Limpa o cache em memória de tendências."""
    _TREND_CACHE.clear()


def _get_default_db_path() -> str:
    """Retorna o caminho padrão do SQLite do MoneyPrinterTurbo."""
    if DB_PATH:
        return DB_PATH
    from app.services import scheduler
    return scheduler.get_db_path()


@contextlib.contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o SQLite em modo WAL garantindo fechamento em qualquer SO."""
    path = db_path or _get_default_db_path()
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=30.0)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA busy_timeout=30000;")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_trend_db(db_path: Optional[str] = None) -> None:
    """Inicializa a tabela trend_items de forma idempotente."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS trend_items (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trend_id TEXT UNIQUE NOT NULL,
                source TEXT NOT NULL,
                source_key TEXT,
                source_url TEXT,
                title TEXT NOT NULL,
                normalized_topic TEXT NOT NULL,
                description TEXT,
                published_at TEXT,
                collected_at TEXT NOT NULL,
                region TEXT,
                language TEXT,
                niche TEXT,
                trend_score REAL NOT NULL,
                novelty_score REAL NOT NULL,
                relevance_score REAL NOT NULL,
                opportunity_score REAL NOT NULL,
                source_confidence TEXT NOT NULL,
                source_count INTEGER DEFAULT 1,
                verification TEXT NOT NULL,
                status TEXT DEFAULT 'NEW',
                metadata_json TEXT
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trend_status ON trend_items(status);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trend_norm ON trend_items(normalized_topic);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_trend_collected ON trend_items(collected_at);")


init_trend_tables = init_trend_db


def normalize_topic(text: str) -> str:
    """Normaliza um título para deduplicação robusta e limpa.
    
    Regras:
    - trim
    - lowercase
    - remover acentos (NFKD)
    - remover pontuação e caracteres especiais
    - unificar espaços múltiplos
    - remover artigos iniciais para equivalência semântica segura
    """
    if not text:
        return ""
    cleaned = text.strip().lower()
    cleaned = "".join(
        c for c in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(c)
    )
    cleaned = re.sub(r"[^\w\s]", " ", cleaned)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    # Remove artigos no início para equivalência de títulos (o, a, os, as, um, uma, the)
    cleaned = re.sub(r"^(o|a|os|as|um|uma|the)\s+", "", cleaned)
    return cleaned


normalize_trend_title = normalize_topic


OFF_NICHE_POLITICS_KEYWORDS = {
    "stf", "ministro", "ministra", "presidenciável", "presidenciavel", "eleição",
    "eleicao", "eleições", "eleicoes", "partido", "senado", "senador", "deputado",
    "deputada", "prefeito", "governador", "governo", "campanha", "parlamentar", "voto",
    "candidato", "candidata", "planalto", "congresso", "bolsonaro", "lula", "pt", "pl",
    "moraes", "tofolli", "tse", "vereador", "mandato", "tribunal", "politica", "politico"
}

GENUINE_CURIOSITY_TOKENS = {
    "misterio", "misterios", "segredo", "segredos", "descoberta", "descobertas",
    "fato", "fatos", "como", "porque", "funciona", "mundo", "universo",
    "espaco", "ciencia", "cientifico", "cientifica", "historia", "historias",
    "natureza", "corpo", "humano", "origem", "animais", "animal", "bizarro",
    "incrivel", "raro", "rara", "antigo", "antiga", "alienigena", "oceano",
    "profundo", "terra", "planeta", "surpreendente", "mitos", "mito", "verdade",
    "sabia", "fenomeno", "espantoso", "estranho", "curioso", "album", "estreia",
    "filme", "musica", "arte", "cultura", "tecnologia", "invento", "criatura"
}


def determine_source_confidence(
    source: str = "",
    source_count: int = 1,
    provider_conf: str = CONFIDENCE_MEDIUM,
) -> str:
    """Classifica a confiança da fonte (HIGH, MEDIUM, LOW).

    Regras estritas da V4:
    HIGH:
      - 2+ fontes independentes confirmam
      OU
      - fonte primária/oficial claramente identificada (Google Trends)
    MEDIUM:
      - RSS/news de fonte única
      - Reddit de fonte única
    LOW:
      - sinal isolado de baixa qualidade
    """
    if source_count >= 2:
        return CONFIDENCE_HIGH

    s_lower = source.lower().strip()
    clean_prov = str(provider_conf).upper().strip()

    # Google Trends é agregador oficial de volume de buscas
    if "google_trends" in s_lower:
        return CONFIDENCE_HIGH

    # RSS agregador e Reddit de fonte única são MEDIUM (nunca HIGH automaticamente)
    if "rss" in s_lower or "reddit" in s_lower:
        return CONFIDENCE_MEDIUM

    if clean_prov == CONFIDENCE_LOW or "unknown" in s_lower:
        return CONFIDENCE_LOW

    return CONFIDENCE_MEDIUM


def calculate_relevance_score(
    topic: str,
    niche: str,
    description: str = "",
) -> float:
    """Calcula a relevância (0–100) do tópico em relação ao nicho.

    Aplica penalidade severa a categorias sensíveis/fora do nicho (como política)
    quando o nicho não as solicitar explicitamente.
    Evita considerar um item relevante apenas porque contém a palavra literal do nicho.
    """
    if not niche or not niche.strip():
        return 75.0

    norm_topic = normalize_topic(topic)
    norm_niche = normalize_topic(niche)
    norm_desc = normalize_topic(description or "")

    combined_text = f"{norm_topic} {norm_desc}".strip()
    topic_tokens = set(combined_text.split())
    niche_tokens = set(norm_niche.split())

    # 1. Verifica se o nicho pede política/governo/eleições
    is_politics_niche = any(
        p in norm_niche
        for p in ["politica", "eleicao", "governo", "noticia", "stf", "eleicoes", "partido"]
    )

    # 2. Se o nicho NÃO for de política, penaliza fortemente termos políticos/eleitorais
    if not is_politics_niche:
        politics_overlap = topic_tokens.intersection(OFF_NICHE_POLITICS_KEYWORDS)
        if politics_overlap:
            # Penalidade drástica: pontuação cai para 10–25
            penalty = max(10.0, 25.0 - (len(politics_overlap) - 1) * 5.0)
            return round(penalty, 1)
    else:
        # Se o nicho FOR de política, termos políticos confirmam alta relevância
        politics_matches = topic_tokens.intersection(OFF_NICHE_POLITICS_KEYWORDS)
        if politics_matches:
            base = 72.0 + min(20.0, len(politics_matches) * 6.0)
            return round(min(96.0, base + (len(norm_topic) % 5)), 1)

    # 3. Tratamento específico para o nicho "Curiosidades"
    is_curiosity_niche = any(c in norm_niche for c in ["curiosidade", "curiosidades"])
    if is_curiosity_niche:
        curiosity_matches = topic_tokens.intersection(GENUINE_CURIOSITY_TOKENS)
        if curiosity_matches:
            # Recompensa temas com ganchos genuínos de curiosidade, mistério, ciência, fatos
            base = 72.0 + min(20.0, len(curiosity_matches) * 5.5)
            # Variação sutil baseada no comprimento do título para evitar empates
            variation = (len(norm_topic) % 7) * 0.7
            return round(min(96.0, base + variation), 1)
        else:
            # Se apenas tem a palavra literal "curiosidade" sem outros ganchos temáticos
            if "curiosidade" in topic_tokens or "curiosidades" in topic_tokens:
                return round(48.0 + (len(norm_topic) % 5), 1)
            else:
                # Tema genérico não relacionado
                return round(40.0 + (len(norm_topic) % 6), 1)

    # 4. Nichos gerais (Espaço, História, Tecnologia, etc.)
    generic_stops = {"de", "do", "da", "em", "um", "uma", "os", "as", "para", "com", "sobre", "e"}
    clean_niche_tokens = niche_tokens - generic_stops
    intersection = topic_tokens.intersection(clean_niche_tokens)

    if intersection:
        base = 70.0 + min(25.0, len(intersection) * 12.0)
        variation = (len(norm_topic) % 5) * 0.8
        return round(min(98.0, base + variation), 1)

    # Similaridade aproximada difflib
    matcher = difflib.SequenceMatcher(None, norm_topic, norm_niche)
    ratio = matcher.ratio()
    return round(min(85.0, max(30.0, 30.0 + ratio * 55.0)), 1)


def calculate_novelty_score(
    topic: str,
    history_topics: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> float:
    """Calcula a novidade (0–100) comparando com o histórico recente de temas gerados ou usados."""
    norm_topic = normalize_topic(topic)
    if not norm_topic:
        return 50.0

    highest_similarity = 0.0

    if history_topics is not None:
        for past in history_topics:
            past_norm = normalize_topic(past)
            if past_norm:
                ratio = difflib.SequenceMatcher(None, norm_topic, past_norm).ratio()
                if ratio > highest_similarity:
                    highest_similarity = ratio
    else:
        init_trend_db(db_path)
        with get_connection(db_path) as conn:
            used_rows = conn.execute(
                "SELECT normalized_topic FROM trend_items WHERE status = 'USED' ORDER BY id DESC LIMIT 50;"
            ).fetchall()
            for row in used_rows:
                past_topic = row["normalized_topic"]
                if past_topic:
                    ratio = difflib.SequenceMatcher(None, norm_topic, past_topic).ratio()
                    if ratio > highest_similarity:
                        highest_similarity = ratio

            try:
                safety_rows = conn.execute(
                    "SELECT topic FROM monetization_safety ORDER BY id DESC LIMIT 50;"
                ).fetchall()
                for row in safety_rows:
                    t = normalize_topic(row["topic"] or "")
                    if t:
                        ratio = difflib.SequenceMatcher(None, norm_topic, t).ratio()
                        if ratio > highest_similarity:
                            highest_similarity = ratio
            except Exception:
                pass

    if highest_similarity >= 0.85:
        return 15.0
    elif highest_similarity >= 0.65:
        return round(max(20.0, 100.0 - (highest_similarity * 80.0)), 1)

    return 100.0 if (history_topics is not None and not history_topics) else 95.0


def calculate_trend_score(
    signals_or_raw: Any = None,
    raw_source_score: Optional[float] = None,
    source_count: int = 1,
    source_confidence: str = CONFIDENCE_MEDIUM,
    is_recent: bool = True,
) -> float:
    """Calcula o score de tendência (0–100) determinístico."""
    if isinstance(signals_or_raw, list):
        signals = signals_or_raw
        if not signals:
            return 50.0
        raw_scores = [s.raw_score for s in signals]
        base_score = sum(raw_scores) / len(raw_scores)
        distinct_sources = {s.source for s in signals}
        multi_source_bonus = 15.0 if len(distinct_sources) >= 2 else 0.0
        gt_bonus = 10.0 if any(s.source == "google_trends" and s.raw_score >= 75.0 for s in signals) else 0.0
        total = base_score + multi_source_bonus + gt_bonus
        return round(min(100.0, max(0.0, total)), 1)
    else:
        val = raw_source_score if raw_source_score is not None else signals_or_raw
        raw_score = float(val) if val is not None else 50.0
        multi_bonus = 15.0 if source_count >= 2 else 0.0
        conf_bonus = 10.0 if source_confidence == CONFIDENCE_HIGH else 0.0
        recency_bonus = 5.0 if is_recent else 0.0
        total = raw_score * 0.7 + multi_bonus + conf_bonus + recency_bonus
        return round(min(100.0, max(0.0, total)), 1)


def calculate_opportunity_score(
    trend_score: float,
    novelty_score: float,
    relevance_score: float,
    source_confidence: str = CONFIDENCE_MEDIUM,
    confidence: Optional[str] = None,
    repetition_risk: int = 0,
) -> float:
    """Calcula o Opportunity Score final (0–100) com Relevance Quality Gate determinístico.

    O Relevance Gate atua como filtro de qualidade de nicho:
    - relevance_score >= 60: Elegível integralmente (sem penalidade)
    - 40 <= relevance_score < 60: Relação fraca com o nicho (penalidade progressiva de 15% a 50%)
    - relevance_score < 40: Fora do nicho / oportunidade insignificante (penalidade drástica de 65%)
    """
    conf_to_use = confidence or source_confidence
    conf_weights = {CONFIDENCE_HIGH: 100.0, CONFIDENCE_MEDIUM: 75.0, CONFIDENCE_LOW: 50.0}
    conf_val = conf_weights.get(str(conf_to_use).upper(), 70.0)

    base_score = (
        0.35 * trend_score
        + 0.35 * novelty_score
        + 0.20 * relevance_score
        + 0.10 * conf_val
        - (repetition_risk * 5.0)
    )

    # Relevance Quality Gate
    if relevance_score < 40.0:
        opportunity = base_score * 0.35
    elif relevance_score < 60.0:
        rel_factor = 0.50 + 0.35 * ((relevance_score - 40.0) / 20.0)
        opportunity = base_score * rel_factor
    else:
        opportunity = base_score

    return round(min(100.0, max(0.0, opportunity)), 1)


def _generate_trend_id(normalized_topic: str, source: str) -> str:
    """Gera um identificador determinístico para um tema e fonte."""
    seed = f"{normalized_topic}:{source}".encode("utf-8")
    return hashlib.sha256(seed).hexdigest()[:16]


def are_topics_similar(t1: str, t2: str) -> bool:
    """Verifica se dois tópicos normalizados representam o mesmo tema essencial."""
    if not t1 or not t2:
        return False
    if t1 == t2:
        return True
    ratio = difflib.SequenceMatcher(None, t1, t2).ratio()
    if ratio >= 0.70:
        return True
    tokens1 = {w for w in t1.split() if len(w) > 2}
    tokens2 = {w for w in t2.split() if len(w) > 2}
    if tokens1 and tokens2:
        common = tokens1.intersection(tokens2)
        if len(common) >= 2 and (len(common) / min(len(tokens1), len(tokens2)) >= 0.33):
            return True
    return False


def deduplicate_and_merge_signals(signals: List[TrendSignal]) -> List[TrendSignal]:
    """Agrupa sinais semelhantes e retorna lista de TrendSignals consolidados."""
    grouped: Dict[str, List[TrendSignal]] = {}
    for sig in signals:
        norm = normalize_topic(sig.normalized_topic) if sig.normalized_topic else normalize_topic(sig.title)
        if not norm:
            continue

        matched_key = None
        for existing_key in grouped.keys():
            if are_topics_similar(norm, existing_key):
                matched_key = existing_key
                break

        key = matched_key or norm
        if key not in grouped:
            grouped[key] = []
        grouped[key].append(sig)

    merged_list: List[TrendSignal] = []
    for norm_key, sig_list in grouped.items():
        best_sig = sorted(
            sig_list,
            key=lambda s: (1 if s.source_confidence == CONFIDENCE_HIGH else 0, len(s.title)),
            reverse=True,
        )[0]
        distinct_sources = list({s.source for s in sig_list})
        source_count = len(distinct_sources)
        verification = VERIFICATION_MULTI if source_count >= 2 else VERIFICATION_SINGLE
        confidence = determine_source_confidence(
            source=best_sig.source,
            source_count=source_count,
            provider_conf=best_sig.source_confidence,
        )

        merged_signal = TrendSignal(
            title=best_sig.title,
            source=", ".join(distinct_sources),
            source_key=best_sig.source_key,
            source_url=next((s.source_url for s in sig_list if s.source_url), ""),
            description=best_sig.description,
            published_at=best_sig.published_at,
            region=best_sig.region,
            language=best_sig.language,
            raw_score=max(s.raw_score for s in sig_list),
            source_confidence=confidence,
            normalized_topic=norm_key,
            source_count=source_count,
            verification=verification,
            status=best_sig.status or STATUS_NEW,
        )
        merged_list.append(merged_signal)

    return merged_list


def deduplicate_and_rank_signals(
    signals: List[TrendSignal],
    niche: str = "",
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Agrupa sinais semelhantes, consolida fontes e calcula todos os scores."""
    init_trend_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()

    merged_signals = deduplicate_and_merge_signals(signals)
    items: List[Dict[str, Any]] = []

    for sig in merged_signals:
        trend_score = calculate_trend_score(
            signals_or_raw=sig.raw_score,
            source_count=sig.source_count,
            source_confidence=sig.source_confidence,
            is_recent=True,
        )
        novelty_score = calculate_novelty_score(sig.normalized_topic, db_path=db_path)
        relevance_score = calculate_relevance_score(
            sig.title, niche, description=sig.description
        )
        opportunity_score = calculate_opportunity_score(
            trend_score=trend_score,
            novelty_score=novelty_score,
            relevance_score=relevance_score,
            source_confidence=sig.source_confidence,
        )

        trend_id = _generate_trend_id(sig.normalized_topic, sig.source)
        metadata = {
            "source_count": sig.source_count,
            "verification": sig.verification,
            "raw_score": sig.raw_score,
        }

        items.append({
            "trend_id": trend_id,
            "source": sig.source,
            "source_key": sig.source_key,
            "source_url": sig.source_url,
            "title": sig.title,
            "normalized_topic": sig.normalized_topic,
            "description": sig.description,
            "published_at": sig.published_at,
            "collected_at": now_iso,
            "region": sig.region,
            "language": sig.language,
            "niche": niche,
            "trend_score": trend_score,
            "novelty_score": novelty_score,
            "relevance_score": relevance_score,
            "opportunity_score": opportunity_score,
            "source_confidence": sig.source_confidence,
            "source_count": sig.source_count,
            "verification": sig.verification,
            "status": sig.status or STATUS_NEW,
            "metadata_json": json.dumps(metadata, ensure_ascii=False),
        })

    items.sort(key=lambda x: x["opportunity_score"], reverse=True)
    return items


def upsert_trend_item(
    signal: TrendSignal,
    db_path: Optional[str] = None,
    niche: str = "",
) -> str:
    """Insere ou atualiza um item de tendência no SQLite e retorna seu trend_id."""
    init_trend_db(db_path)
    now_iso = datetime.now(timezone.utc).isoformat()
    norm_topic = signal.normalized_topic or normalize_topic(signal.title)
    trend_id = _generate_trend_id(norm_topic, signal.source)

    with get_connection(db_path) as conn:
        existing = conn.execute(
            "SELECT id, status FROM trend_items WHERE trend_id = ?;", (trend_id,)
        ).fetchone()

        status_to_use = signal.status if signal.status != STATUS_NEW else (
            existing["status"] if existing else STATUS_NEW
        )

        if existing:
            conn.execute(
                """
                UPDATE trend_items SET
                    title = ?,
                    source = ?,
                    source_url = ?,
                    description = ?,
                    trend_score = ?,
                    novelty_score = ?,
                    relevance_score = ?,
                    opportunity_score = ?,
                    source_confidence = ?,
                    source_count = ?,
                    verification = ?,
                    status = ?
                WHERE trend_id = ?;
                """,
                (
                    signal.title, signal.source, signal.source_url, signal.description,
                    signal.trend_score, signal.novelty_score, signal.relevance_score,
                    signal.opportunity_score, signal.source_confidence, signal.source_count,
                    signal.verification, status_to_use, trend_id,
                ),
            )
        else:
            conn.execute(
                """
                INSERT INTO trend_items (
                    trend_id, source, source_key, source_url, title, normalized_topic,
                    description, published_at, collected_at, region, language, niche,
                    trend_score, novelty_score, relevance_score, opportunity_score,
                    source_confidence, source_count, verification, status, metadata_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    trend_id, signal.source, signal.source_key, signal.source_url, signal.title,
                    norm_topic, signal.description, signal.published_at, now_iso,
                    signal.region, signal.language, niche.strip().lower(), signal.trend_score, signal.novelty_score,
                    signal.relevance_score, signal.opportunity_score, signal.source_confidence,
                    signal.source_count, signal.verification, status_to_use, "{}",
                ),
            )
    return trend_id


def get_active_providers() -> List[BaseTrendProvider]:
    """Retorna instâncias dos providers de tendência ativos."""
    return [
        GoogleTrendsProvider(),
        RedditTrendsProvider(),
        RssNewsProvider(),
        TikTokCreativeProvider(),
    ]


def refresh_trend_radar(
    niche: str = "",
    language: str = "pt-BR",
    region: str = "BR",
    limit: int = 30,
    db_path: Optional[str] = None,
    force_refresh: bool = False,
    bypass_cache: bool = False,
    providers: Optional[List[BaseTrendProvider]] = None,
) -> List[Dict[str, Any]]:
    """Consulta os providers com isolamento de falhas, aplica deduplicação, pontuação e salva no SQLite."""
    init_trend_db(db_path)
    clean_niche = (niche or "").strip().lower()
    clean_lang = (language or "pt-BR").strip()
    clean_reg = (region or "BR").strip().upper()
    cache_key = (clean_niche, clean_lang, clean_reg)

    now = time.time()
    should_bypass = force_refresh or bypass_cache
    if not should_bypass and cache_key in _TREND_CACHE:
        cached_time, cached_items = _TREND_CACHE[cache_key]
        if now - cached_time < _CACHE_TTL_SECONDS:
            logger.debug(f"[TrendRadar] Retornando {len(cached_items)} itens do cache TTL (niche='{clean_niche}')")
            return cached_items

    active_providers = providers if providers is not None else get_active_providers()

    all_signals: List[TrendSignal] = []
    for prov in active_providers:
        try:
            if hasattr(prov, "fetch_trends"):
                signals = prov.fetch_trends(
                    niche=clean_niche,
                    language=clean_lang,
                    region=clean_reg,
                    limit=limit,
                )
            elif hasattr(prov, "fetch_signals"):
                signals = prov.fetch_signals(
                    niche=clean_niche,
                    language=clean_lang,
                    region=clean_reg,
                    limit=limit,
                )
            else:
                signals = []
            all_signals.extend(signals)
            logger.info(f"[TrendRadar] Provider '{prov.name}' retornou {len(signals)} sinais")
        except Exception as exc:
            logger.warning(f"[TrendRadar] Falha no provider '{prov.name}': {exc}")

    ranked_items = deduplicate_and_rank_signals(all_signals, niche=clean_niche, db_path=db_path)

    with get_connection(db_path) as conn:
        for it in ranked_items:
            existing = conn.execute(
                "SELECT status, collected_at FROM trend_items WHERE trend_id = ?;",
                (it["trend_id"],),
            ).fetchone()
            if existing:
                it["status"] = existing["status"]
                it["collected_at"] = existing["collected_at"]
                conn.execute(
                    """
                    UPDATE trend_items SET
                        trend_score = ?,
                        novelty_score = ?,
                        relevance_score = ?,
                        opportunity_score = ?,
                        source_count = ?,
                        verification = ?,
                        metadata_json = ?
                    WHERE trend_id = ?;
                    """,
                    (
                        it["trend_score"],
                        it["novelty_score"],
                        it["relevance_score"],
                        it["opportunity_score"],
                        it["source_count"],
                        it["verification"],
                        it["metadata_json"],
                        it["trend_id"],
                    ),
                )
            else:
                conn.execute(
                    """
                    INSERT INTO trend_items (
                        trend_id, source, source_key, source_url, title, normalized_topic,
                        description, published_at, collected_at, region, language, niche,
                        trend_score, novelty_score, relevance_score, opportunity_score,
                        source_confidence, source_count, verification, status, metadata_json
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                    """,
                    (
                        it["trend_id"], it["source"], it["source_key"], it["source_url"], it["title"],
                        it["normalized_topic"], it["description"], it["published_at"], it["collected_at"],
                        it["region"], it["language"], it["niche"], it["trend_score"], it["novelty_score"],
                        it["relevance_score"], it["opportunity_score"], it["source_confidence"],
                        it["source_count"], it["verification"], it["status"], it["metadata_json"],
                    ),
                )

    _TREND_CACHE[cache_key] = (now, ranked_items)
    return ranked_items


def get_trend_items(
    status: Optional[str] = None,
    niche: Optional[str] = None,
    limit: int = 50,
    db_path: Optional[str] = None,
    language: Optional[str] = None,
    region: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Consulta itens salvos no banco com filtros opcionais de status e nicho."""
    init_trend_db(db_path)
    query = "SELECT * FROM trend_items"
    params = []
    conditions = []

    if status and status.upper() != "ALL":
        conditions.append("status = ?")
        params.append(status.upper())
    if niche:
        conditions.append("niche = ?")
        params.append(niche.strip().lower())

    if conditions:
        query += " WHERE " + " AND ".join(conditions)

    query += " ORDER BY opportunity_score DESC, id DESC LIMIT ?;"
    params.append(limit)

    with get_connection(db_path) as conn:
        rows = conn.execute(query, tuple(params)).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            d["id"] = d["trend_id"]
            result.append(d)
        return result


def update_trend_item_status(
    trend_id: str,
    status: str,
    db_path: Optional[str] = None,
) -> bool:
    """Atualiza o status de um item de tendência no banco (ex: APPROVED, REJECTED, USED)."""
    clean_status = str(status).upper().strip()
    if clean_status not in VALID_STATUSES:
        raise ValueError(f"Status inválido: {status}. Permitidos: {VALID_STATUSES}")

    init_trend_db(db_path)
    with get_connection(db_path) as conn:
        cur = conn.execute(
            "UPDATE trend_items SET status = ? WHERE trend_id = ?;",
            (clean_status, trend_id),
        )
        _TREND_CACHE.clear()
        return cur.rowcount > 0


def send_trends_to_autopilot(
    trend_ids: Optional[List[str]] = None,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Converte itens de tendência aprovados em temas para o Autopilot."""
    init_trend_db(db_path)
    sent_items: List[Dict[str, Any]] = []

    with get_connection(db_path) as conn:
        if trend_ids is None:
            rows = conn.execute(
                "SELECT trend_id FROM trend_items WHERE status = ?;", (STATUS_APPROVED,)
            ).fetchall()
            target_ids = [r["trend_id"] for r in rows]
        else:
            target_ids = list(trend_ids)

        if not target_ids:
            return []

        for tid in target_ids:
            row = conn.execute(
                "SELECT * FROM trend_items WHERE trend_id = ?;", (tid,)
            ).fetchone()
            if not row:
                continue

            item = dict(row)
            if item["status"] != STATUS_APPROVED:
                logger.info(f"[TrendRadar] Item {tid} com status {item['status']} não foi enviado ao Autopilot.")
                continue

            conn.execute(
                "UPDATE trend_items SET status = ? WHERE trend_id = ?;", (STATUS_USED, tid)
            )

            sent_items.append({
                "topic": item["title"],
                "trend_id": item["trend_id"],
                "source": item["source"],
                "source_count": item.get("source_count") or 1,
                "verification": item.get("verification"),
                "trend_score": item.get("trend_score"),
                "relevance_score": item.get("relevance_score"),
                "source_confidence": item.get("source_confidence"),
                "opportunity_score": item.get("opportunity_score"),
                "niche": item["niche"],
                "selected": True,
            })


    _TREND_CACHE.clear()
    logger.info(f"[TrendRadar] {len(sent_items)} temas enviados com sucesso para o Autopilot.")
    return sent_items


def get_trend_source_performance(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Retorna o desempenho histórico das fontes do Trend Radar a partir do Analytics."""
    from app.services import analytics
    return analytics.get_trend_source_performance(db_path=db_path)
