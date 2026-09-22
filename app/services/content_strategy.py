"""Módulo de Estratégia de Conteúdo e Otimização (Fase V7).

Combina determinística e explicavelmente os sinais existentes:
- V4 Trend Radar (trend_score, opportunity_score, relevance_score, source_confidence)
- V5 Analytics (performance_score, estruturas, presets, duração ótima, fontes)
- V6 Quality Score (quality_score, hook, originality, repetition, narrative_fit, visual_match)
- Autopilot (histórico recente de pauta, clusters e estruturas usadas)

Responsabilidades:
- Calcular strategy_score (0–100) com faixas operacionais (PRIORITY, PROMISING, EXPERIMENT, LOW)
- Classificar em buckets de mix (Proven Winner, Trend Opportunity, Evergreen, Experiment, Diversity)
- Identificar topic_cluster lexical para controle de saturação
- Calcular diversity_score com penalidade a repetições recentes
- Recomendar estrutura narrativa com anti-repetição consecutiva
- Recomendar janela de duração orientada por dados
- Organizar lotes diversificados (build_strategy_batch)
- Persistir avaliações em content_strategy_scores
"""

import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# Faixas operacionais do Strategy Score
LABEL_PRIORITY = "PRIORITY"       # 85–100
LABEL_PROMISING = "PROMISING"     # 70–84
LABEL_EXPERIMENT = "EXPERIMENT"   # 55–69
LABEL_LOW = "LOW"                 # 0–54

# Buckets estratégicos para equilíbrio de mix
BUCKET_PROVEN_WINNER = "Proven Winner"
BUCKET_TREND_OPPORTUNITY = "Trend Opportunity"
BUCKET_EVERGREEN = "Evergreen"
BUCKET_EXPERIMENT = "Experiment"
BUCKET_DIVERSITY = "Diversity"

# Pesos do Strategy Score (soma = 1.00)
STRATEGY_WEIGHTS = {
    "quality_signal": 0.30,
    "trend_opportunity": 0.20,
    "historical_performance": 0.20,
    "novelty_diversity": 0.15,
    "niche_relevance": 0.10,
    "source_confidence": 0.05,
}

# Configuração de persistência SQLite
DB_PATH: Optional[str] = None


def select_closed_loop_candidate(baseline_candidate, candidates, evidence, recent_submissions, niche=None):
    """Pure bounded policy; only topic and official narrative structure may change.

    Trend opportunity remains the primary ranking. Structure heuristics have rank
    50 (baseline) / 48 (other fitting structures); history can add at most 5.
    Engagement is descriptive only: it cannot break a views tie.
    """
    from app.services import analytics
    from app.models import const
    baseline = dict(baseline_candidate)
    baseline.setdefault("narrative_structure", recommend_narrative_structure(baseline["topic"], niche=niche)[0])
    result = {"baseline_candidate": baseline, "selected_candidate": dict(baseline),
              "adapted": False, "reason": evidence.get("fallback_reason") or "baseline",
              "evidence_summary": evidence, "diversity_result": "not_evaluated",
              "history_bonus": 0.0, "policy_version": analytics.LEARNING_POLICY_VERSION}
    if evidence.get("evidence_state") != "ELIGIBLE":
        return result
    if any(s.get("adapted") for s in recent_submissions[:analytics.ADAPTATION_INTERVAL - 1]):
        result.update(reason="exploration_slot", diversity_result="adaptation_interval")
        return result
    winner_cluster = evidence.get("recommended_topic_cluster")
    winner_structure = evidence.get("recommended_narrative_structure")
    ranked = []
    for index, candidate in enumerate([baseline] + list(candidates)):
        topic = candidate.get("topic")
        if not topic:
            continue
        rank = float((candidate.get("trend_data") or {}).get("opportunity_score", 50.0))
        if not 0 <= rank <= 100:
            continue
        bonus = analytics.MAX_HISTORY_RANKING_BONUS if classify_topic_cluster(topic) == winner_cluster else 0.0
        ranked.append((min(100.0, rank + bonus), -index, candidate, bonus))
    if not ranked:
        return result
    _, _, selected, bonus = max(ranked, key=lambda x: (x[0], x[1]))
    selected = dict(selected)
    heuristic = recommend_narrative_structure(selected["topic"], niche=niche)[0]
    structure = heuristic
    # Only consider historically supported structures that the topic heuristic
    # itself accepts as its immediate alternate (no arbitrary format substitution).
    alternate = recommend_narrative_structure(selected["topic"], niche=niche, last_used_structure=heuristic)[0]
    if winner_structure in const.NARRATIVE_STRUCTURES and winner_structure in (heuristic, alternate):
        if winner_structure != heuristic and 48.0 + analytics.MAX_HISTORY_RANKING_BONUS > 50.0:
            structure = winner_structure
            bonus = max(bonus, analytics.MAX_HISTORY_RANKING_BONUS)
    selected["narrative_structure"] = structure
    changed = selected["topic"] != baseline["topic"] or structure != baseline["narrative_structure"]
    if not changed:
        result.update(reason="baseline_already_selected", diversity_result="pass")
        return result
    recent = recent_submissions[:analytics.RECENT_SUBMISSIONS - 1]
    cluster = classify_topic_cluster(selected["topic"])
    if sum(s.get("topic_cluster") == cluster for s in recent) >= analytics.MAX_CLUSTER_USES:
        result.update(reason="cluster_saturated", diversity_result="cluster_limit")
        return result
    if recent and recent[0].get("narrative_structure") == structure and alternate != heuristic:
        result.update(reason="structure_repetition", diversity_result="structure_limit")
        return result
    result.update(selected_candidate=selected, adapted=True, reason="stable_history",
                  diversity_result="pass", history_bonus=bonus)
    return result


def _get_default_db_path() -> str:
    if DB_PATH:
        return DB_PATH
    base_dir = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    storage_dir = os.path.join(base_dir, "storage")
    os.makedirs(storage_dir, exist_ok=True)
    return os.path.join(storage_dir, "video_factory.db")


def get_connection(db_path: Optional[str] = None):
    p = db_path or _get_default_db_path()
    conn = sqlite3.connect(p)
    conn.row_factory = sqlite3.Row
    return conn


def init_strategy_db(db_path: Optional[str] = None) -> None:
    """Inicializa a tabela content_strategy_scores no SQLite."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_strategy_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                topic TEXT NOT NULL,
                trend_id TEXT,
                task_id TEXT,
                topic_cluster TEXT,
                strategy_score REAL NOT NULL,
                strategy_label TEXT NOT NULL,
                strategy_bucket TEXT NOT NULL,
                quality_score REAL,
                trend_opportunity_score REAL,
                historical_performance_score REAL,
                diversity_score REAL,
                relevance_score REAL,
                source_confidence_score REAL,
                recommended_structure TEXT,
                recommended_duration_min REAL,
                recommended_duration_max REAL,
                reasons_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_created ON content_strategy_scores(created_at);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_score ON content_strategy_scores(strategy_score);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_bucket ON content_strategy_scores(strategy_bucket);")
        conn.execute("CREATE INDEX IF NOT EXISTS idx_strategy_cluster ON content_strategy_scores(topic_cluster);")


def _normalize_text(text: str) -> str:
    if not text:
        return ""
    nfkd = unicodedata.normalize("NFKD", text.lower())
    without_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", without_accents).strip()


# Vocabulário determinístico de Topic Clusters
CLUSTER_KEYWORDS: Dict[str, List[str]] = {
    "oceanos": [
        "oceano", "oceanos", "mar", "mares", "salgado", "salgada", "agua", "aguas",
        "peixe", "peixes", "tubarao", "submarino", "marinho", "abissal", "rio", "rios", "fossa", "marianas"
    ],
    "astronomia": [
        "espaco", "planeta", "planetas", "estrela", "estrelas", "sol", "lua", "galaxia",
        "universo", "marte", "saturno", "jupiter", "buraco", "cometa", "asteroide", "nasa", "astronomia"
    ],
    "ciencia_tecnologia": [
        "aviao", "avioes", "voar", "motor", "foguete", "tecnologia", "computador", "celular",
        "internet", "eletricidade", "relampago", "raio", "quimica", "fisica", "experimento", "invento", "maquina"
    ],
    "biologia_corpo": [
        "corpo", "cerebro", "coracao", "sangue", "acucar", "saude", "sono", "dormir",
        "animal", "animais", "bicho", "gato", "gatos", "cachorro", "cao", "inseto", "formiga", "biologia"
    ],
    "historia_misterios": [
        "historia", "historico", "antigo", "antiga", "piramide", "piramides", "egito", "roma",
        "grecia", "imperio", "rei", "rainha", "seculo", "guerra", "medieval", "civilizacao", "arqueologia"
    ],
    "celebridades_cultura": [
        "musica", "album", "cantor", "cantora", "faixa", "filme", "cinema", "ator", "atriz",
        "casamento", "bolo", "hickmann", "ceu", "famoso", "famosos", "novela", "serie", "saga", "jogos"
    ],
    "institucional_sociedade": [
        "stf", "ministra", "ministro", "governo", "justica", "lei", "brasil", "brasileiro",
        "presidenciavel", "politica", "eleicao", "senado", "congresso"
    ],
}


def classify_topic_cluster(topic: str) -> str:
    """Classifica o tópico em um cluster temático determinístico por sobreposição lexical."""
    norm = _normalize_text(topic)
    words = set(re.findall(r"\w+", norm))

    best_cluster = "geral"
    max_matches = 0

    for cluster_name, keywords in CLUSTER_KEYWORDS.items():
        matches = len(words.intersection(keywords))
        if matches > max_matches:
            max_matches = matches
            best_cluster = cluster_name

    if max_matches > 0:
        return best_cluster

    # Fallback determinístico: primeiro termo relevante (len >= 4 que não seja stopword)
    stopwords = {"onde", "como", "quem", "qual", "para", "sobre", "esse", "essa", "este", "esta", "voce", "sabia", "fatos", "tudo", "mais", "muito"}
    for w in sorted(words):
        if len(w) >= 4 and w not in stopwords:
            return f"tema_{w}"

    return "geral"


def calculate_diversity_score(
    topic: str,
    topic_cluster: str,
    recommended_structure: Optional[str] = None,
    source: Optional[str] = None,
    recent_history: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, List[str]]:
    """Calcula score de diversidade (0–100) penalizando clusters, estruturas e fontes repetidas."""
    if not recent_history:
        return 95.0, ["Cluster e estrutura inéditos no histórico recente (+)"]

    score = 100.0
    penalties = 0.0
    reasons = []

    # 1. Penalidade por cluster temático recente
    cluster_counts = 0
    immediate_cluster = False
    for idx, item in enumerate(recent_history[:5]):
        past_cluster = item.get("topic_cluster") or classify_topic_cluster(item.get("topic", ""))
        if past_cluster == topic_cluster:
            cluster_counts += 1
            if idx == 0:
                immediate_cluster = True

    if immediate_cluster:
        penalties += 35.0
        reasons.append(f"Cluster '{topic_cluster}' utilizado no vídeo anterior (-)")
    elif cluster_counts >= 2:
        penalties += 25.0
        reasons.append(f"Cluster '{topic_cluster}' saturado recentemente ({cluster_counts}x nos últimos 5) (-)")
    elif cluster_counts == 1:
        penalties += 10.0
        reasons.append(f"Cluster '{topic_cluster}' presente no histórico recente")
    else:
        reasons.append(f"Cluster '{topic_cluster}' pouco explorado recentemente (+)")

    # 2. Penalidade por repetição imediata de estrutura narrativa
    if recommended_structure and len(recent_history) > 0:
        last_struct = recent_history[0].get("recommended_structure") or recent_history[0].get("narrative_structure")
        if last_struct and last_struct == recommended_structure:
            penalties += 20.0
            reasons.append(f"Estrutura '{recommended_structure}' coincide com o último vídeo (-)")

    # 3. Penalidade por repetição consecutiva de fonte de trend
    if source and len(recent_history) >= 2:
        last_sources = [it.get("source") for it in recent_history[:2] if it.get("source")]
        if len(last_sources) == 2 and all(s == source for s in last_sources):
            penalties += 10.0
            reasons.append(f"Fonte '{source}' repetida consecutivamente")

    final_score = round(max(0.0, min(100.0, score - penalties)), 1)
    return final_score, reasons


def recommend_narrative_structure(
    topic: str,
    niche: Optional[str] = None,
    preferred_structure: Optional[str] = None,
    last_used_structure: Optional[str] = None,
    historical_feedback: Optional[Dict[str, Any]] = None,
) -> Tuple[str, List[str]]:
    """Recomenda a estrutura narrativa mais adequada evitando repetições consecutivas.
    
    Restrito exclusivamente às 5 estruturas narrativas oficiais do projeto:
    - investigative_mystery
    - explainer
    - fact_context
    - myth_vs_reality
    - short_story
    """
    from app.models import const

    official_structures = [
        const.STRUCTURE_MYSTERY,      # "investigative_mystery"
        const.STRUCTURE_EXPLAINER,    # "explainer"
        const.STRUCTURE_FACT_CONTEXT, # "fact_context"
        const.STRUCTURE_MYTH_REALITY, # "myth_vs_reality"
        const.STRUCTURE_SHORT_STORY,  # "short_story"
    ]

    norm = _normalize_text(topic)
    reasons = []

    # Heurística de aderência temática estritamente mapeada para as 5 estruturas oficiais:
    # 1. mito / verdade / crença -> myth_vs_reality
    if any(m in norm for m in ["mito", "mentira", "verdade", "crenca", "crendice", "sera que", "boato"]):
        candidates = [const.STRUCTURE_MYTH_REALITY, const.STRUCTURE_EXPLAINER, const.STRUCTURE_FACT_CONTEXT]
    # 2. mistério / descoberta / fenômeno -> investigative_mystery
    elif any(q in norm for q in ["misterio", "misterios", "descoberta", "fenomeno", "segredo", "segredos", "enigma", "oculto", "abissal", "desconhecido"]):
        candidates = [const.STRUCTURE_MYSTERY, const.STRUCTURE_EXPLAINER, const.STRUCTURE_FACT_CONTEXT]
    # 3. como funciona / ciência / causa -> explainer
    elif any(e in norm for e in ["como funciona", "por que", "ciencia", "cientifica", "cientifico", "causa", "como", "explicacao", "entenda", "motivo"]):
        candidates = [const.STRUCTURE_EXPLAINER, const.STRUCTURE_FACT_CONTEXT, const.STRUCTURE_MYSTERY]
    # 4. personagem / sequência / acontecimento -> short_story
    elif any(s in norm for s in ["historia", "personagem", "sequencia", "acontecimento", "caso", "biografia", "trajetoria", "conto", "relato"]):
        candidates = [const.STRUCTURE_SHORT_STORY, const.STRUCTURE_FACT_CONTEXT, const.STRUCTURE_MYSTERY]
    # 5. fatos / contexto / histórico / lista explicada -> fact_context
    elif re.search(r"\b\d+\s+(curiosidades|fatos|coisas|motivos|itens)\b", norm) or any(f in norm for f in ["fatos", "curiosidades", "contexto", "origem", "top "]):
        candidates = [const.STRUCTURE_FACT_CONTEXT, const.STRUCTURE_EXPLAINER, const.STRUCTURE_SHORT_STORY]
    else:
        candidates = [const.STRUCTURE_EXPLAINER, const.STRUCTURE_FACT_CONTEXT, const.STRUCTURE_MYSTERY]

    if preferred_structure and preferred_structure in official_structures and preferred_structure not in candidates:
        candidates.insert(0, preferred_structure)

    # Se houver feedback histórico do Analytics com >= 5 amostras, valoriza estruturas com boa performance
    if historical_feedback and historical_feedback.get("total_measured", 0) >= 5:
        structs = historical_feedback.get("structures", {})
        candidates.sort(
            key=lambda st: (
                structs.get(st, {}).get("relative_diff", 0.0) if structs.get(st, {}).get("count", 0) >= 3 else -99.0
            ),
            reverse=True,
        )

    # Regra anti-repetição consecutiva: nunca repetir a mesma estrutura do vídeo imediatamente anterior
    chosen = candidates[0]
    if last_used_structure and chosen == last_used_structure and len(candidates) > 1:
        chosen = candidates[1]
        reasons.append(f"Estrutura alternada para '{chosen}' para evitar repetição consecutiva de '{last_used_structure}' (+)")
    else:
        reasons.append(f"Estrutura recomendada: '{chosen}' com base no gancho e tema")

    if chosen not in official_structures:
        chosen = const.STRUCTURE_EXPLAINER

    return chosen, reasons


def recommend_duration(
    preset: Optional[str] = None,
    optimal_duration_seconds: Optional[float] = None,
    has_sufficient_history: bool = False,
) -> Tuple[float, float, str]:
    """Sugere janela de duração ótima com base em dados de Analytics ou preset oficial.
    
    Regras V3:
    - tiktok_rewards: 62–75s
    - cross_platform: 62–75s
    - youtube_shorts_original: 45–90s
    """
    from app.models import const

    # Se houver histórico suficiente de Analytics (>= 5 vídeos medidos), pode recomendar uma subfaixa
    if has_sufficient_history and optimal_duration_seconds and optimal_duration_seconds > 20.0:
        opt = round(optimal_duration_seconds, 0)
        dur_min = max(30.0, opt - 5.0)
        dur_max = opt + 5.0
        return dur_min, dur_max, f"{int(dur_min)}–{int(dur_max)}s"

    # Sem histórico suficiente: usar rigorosamente as faixas oficiais dos presets V3
    p = (preset or "").strip().lower()
    if p == const.PRESET_YOUTUBE_ORIGINAL:  # "youtube_shorts_original"
        return 45.0, 90.0, "45–90s"
    elif p == const.PRESET_TIKTOK_REWARDS:  # "tiktok_rewards"
        return 62.0, 75.0, "62–75s"
    elif p == const.PRESET_CROSS_PLATFORM:  # "cross_platform"
        return 62.0, 75.0, "62–75s"

    # Fallback oficial padrão (cross_platform: 62–75s)
    return 62.0, 75.0, "62–75s"


def determine_strategy_label(strategy_score: float) -> str:
    """Classifica o Strategy Score nas faixas operacionais explicáveis."""
    if strategy_score >= 85.0:
        return LABEL_PRIORITY
    elif strategy_score >= 70.0:
        return LABEL_PROMISING
    elif strategy_score >= 55.0:
        return LABEL_EXPERIMENT
    else:
        return LABEL_LOW


def classify_strategy_bucket(
    topic: str,
    strategy_score: float,
    quality_score: Optional[float],
    trend_opportunity_score: Optional[float],
    historical_performance_score: Optional[float],
    diversity_score: float,
    relevance_score: Optional[float],
    has_sufficient_history: bool,
) -> Tuple[str, str]:
    """Classifica a ideia no bucket estratégico apropriado para o mix."""
    # 1. PROVEN WINNER: Requer estritamente histórico suficiente (>= 5 vídeos medidos)
    if has_sufficient_history and historical_performance_score is not None and historical_performance_score >= 70.0:
        if (quality_score or 0.0) >= 65.0 or strategy_score >= 70.0:
            return BUCKET_PROVEN_WINNER, "Tema e estrutura com histórico comprovado no Analytics"

    # 2. TREND OPPORTUNITY: Forte sinal do Trend Radar
    if trend_opportunity_score is not None and trend_opportunity_score >= 55.0 and (relevance_score or 0.0) >= 45.0:
        return BUCKET_TREND_OPPORTUNITY, "Tópico respaldado por tendência ativa com alta oportunidade"

    # 3. DIVERSITY: Cluster ou formato subutilizado recentemente
    if diversity_score >= 85.0 and (quality_score or 0.0) >= 55.0:
        return BUCKET_DIVERSITY, "Alta diversidade temática, oxigenando o portfólio de pautas"

    # 4. EVERGREEN: Relevância alta e atemporal
    if (relevance_score or 0.0) >= 75.0 and (quality_score or 0.0) >= 65.0:
        return BUCKET_EVERGREEN, "Tema atemporal com forte relevância ao nicho"

    # 5. EXPERIMENT: Ideia nova com bom potencial ou sem histórico
    return BUCKET_EXPERIMENT, "Ideia exploratória para teste de novos formatos ou abordagens"


def calculate_strategy_score(
    quality_score: Optional[float] = None,
    trend_opportunity_score: Optional[float] = None,
    historical_performance_score: Optional[float] = None,
    diversity_score: Optional[float] = None,
    relevance_score: Optional[float] = None,
    source_confidence_score: Optional[float] = None,
) -> Tuple[float, str, Dict[str, Optional[float]]]:
    """Calcula o strategy_score (0–100) com redistribuição proporcional de pesos."""
    components = {
        "quality_signal": quality_score,
        "trend_opportunity": trend_opportunity_score,
        "historical_performance": historical_performance_score,
        "novelty_diversity": diversity_score,
        "niche_relevance": relevance_score,
        "source_confidence": source_confidence_score,
    }

    available_weight = sum(
        STRATEGY_WEIGHTS[k] for k, v in components.items() if v is not None
    )

    if available_weight > 0:
        weighted_sum = sum(
            (v * STRATEGY_WEIGHTS[k]) for k, v in components.items() if v is not None
        )
        final_score = round(weighted_sum / available_weight, 1)
    else:
        final_score = 50.0

    final_score = max(0.0, min(100.0, final_score))
    label = determine_strategy_label(final_score)
    return final_score, label, components


def evaluate_strategy(
    topic: str,
    niche: Optional[str] = None,
    preset: Optional[str] = None,
    trend_data: Optional[Dict[str, Any]] = None,
    quality_data: Optional[Dict[str, Any]] = None,
    recent_history: Optional[List[Dict[str, Any]]] = None,
    last_used_structure: Optional[str] = None,
    task_id: Optional[str] = None,
    persist: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Avaliação estratégica completa de uma ideia de conteúdo."""
    from app.services import analytics, quality_score

    # 1. Resolução do Topic Cluster
    cluster = classify_topic_cluster(topic)

    # 2. Extração de sinais do Quality Score (ou cálculo se ausente)
    if not quality_data:
        quality_data = quality_score.evaluate_quality(
            topic=topic,
            niche=niche,
            preset=preset,
            trend_id=trend_data.get("trend_id") if trend_data else None,
            trend_score=trend_data.get("trend_score") if trend_data else None,
            opportunity_score=trend_data.get("opportunity_score") if trend_data else None,
            relevance_score=trend_data.get("relevance_score") if trend_data else None,
            source_confidence=trend_data.get("source_confidence") if trend_data else None,
            source=trend_data.get("source") if trend_data else None,
            source_count=trend_data.get("source_count", 1) if trend_data else 1,
            verification=trend_data.get("verification") if trend_data else None,
            db_path=db_path,
        )

    q_score = quality_data.get("quality_score")
    q_label = quality_data.get("quality_label")
    q_comps = quality_data.get("components", {})

    # 3. Extração de sinais de Tendência
    trend_id = trend_data.get("trend_id") if trend_data else quality_data.get("trend_id")
    trend_opp = None
    if trend_data and trend_data.get("opportunity_score") is not None:
        trend_opp = float(trend_data["opportunity_score"])
    elif q_comps.get("trend_strength") is not None:
        trend_opp = float(q_comps["trend_strength"])

    source = trend_data.get("source") if trend_data else None
    rel_score = trend_data.get("relevance_score") if trend_data else q_comps.get("niche_relevance")
    if rel_score is not None:
        rel_score = float(rel_score)
    src_conf_score = q_comps.get("source_confidence")

    # 4. Consulta ao Analytics para Histórico e Duração Ótima
    hist_score = None
    optimal_dur = None
    has_sufficient_history = False
    analytics_feedback = {}
    try:
        analytics_feedback = analytics.get_content_performance_feedback(db_path=db_path)
        total_measured = analytics_feedback.get("total_measured", 0)
        optimal_dur = analytics_feedback.get("optimal_duration")
        if total_measured >= 5:
            has_sufficient_history = True
            top_topics = analytics_feedback.get("topics", [])
            for t in top_topics:
                if classify_topic_cluster(t.get("topic", "")) == cluster:
                    hist_score = float(t.get("performance_score", 70.0))
                    break
    except Exception:
        pass

    # 5. Recomendação de Estrutura Narrativa e Duração
    rec_struct, r_struct = recommend_narrative_structure(
        topic=topic,
        niche=niche,
        preferred_structure=quality_data.get("narrative_structure"),
        last_used_structure=last_used_structure,
        historical_feedback=analytics_feedback,
    )
    dur_min, dur_max, dur_str = recommend_duration(
        preset=preset,
        optimal_duration_seconds=optimal_dur,
        has_sufficient_history=has_sufficient_history,
    )

    # 6. Cálculo do Diversity Score
    div_score, r_div = calculate_diversity_score(
        topic=topic,
        topic_cluster=cluster,
        recommended_structure=rec_struct,
        source=source,
        recent_history=recent_history,
    )

    # 7. Cálculo do Strategy Score Final
    strat_score, strat_label, strat_comps = calculate_strategy_score(
        quality_score=q_score,
        trend_opportunity_score=trend_opp,
        historical_performance_score=hist_score,
        diversity_score=div_score,
        relevance_score=rel_score,
        source_confidence_score=src_conf_score,
    )

    # 8. Classificação do Bucket
    strat_bucket, r_bucket = classify_strategy_bucket(
        topic=topic,
        strategy_score=strat_score,
        quality_score=q_score,
        trend_opportunity_score=trend_opp,
        historical_performance_score=hist_score,
        diversity_score=div_score,
        relevance_score=rel_score,
        has_sufficient_history=has_sufficient_history,
    )

    # 9. Consolidação dos motivos estratégicos (máximo 5)
    reasons = []
    if q_score is not None and q_score >= 75.0:
        reasons.append(f"Quality Score alto ({q_score:.0f}/100) (+)")
    if trend_opp is not None and trend_opp >= 55.0:
        reasons.append(f"Tema em tendência com boa oportunidade ({trend_opp:.0f}/100) (+)")
    reasons.append(r_bucket)
    if r_struct:
        reasons.append(r_struct[0])
    if r_div:
        reasons.append(r_div[0])
    selected_reasons = reasons[:5]

    created_iso = datetime.now(timezone.utc).isoformat()
    record_id = None

    # 10. Persistência opcional
    if persist:
        init_strategy_db(db_path)
        with get_connection(db_path) as conn:
            cur = conn.execute(
                """
                INSERT INTO content_strategy_scores (
                    topic, trend_id, task_id, topic_cluster,
                    strategy_score, strategy_label, strategy_bucket,
                    quality_score, trend_opportunity_score, historical_performance_score,
                    diversity_score, relevance_score, source_confidence_score,
                    recommended_structure, recommended_duration_min, recommended_duration_max,
                    reasons_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    topic, trend_id, task_id, cluster,
                    strat_score, strat_label, strat_bucket,
                    q_score, trend_opp, hist_score,
                    div_score, rel_score, src_conf_score,
                    rec_struct, dur_min, dur_max,
                    json.dumps(selected_reasons), created_iso,
                ),
            )
            record_id = cur.lastrowid

    return {
        "id": record_id,
        "topic": topic,
        "trend_id": trend_id,
        "task_id": task_id,
        "topic_cluster": cluster,
        "strategy_score": strat_score,
        "strategy_label": strat_label,
        "strategy_bucket": strat_bucket,
        "quality_score": q_score,
        "quality_label": q_label,
        "trend_opportunity_score": trend_opp,
        "historical_performance_score": hist_score,
        "diversity_score": div_score,
        "relevance_score": rel_score,
        "source_confidence_score": src_conf_score,
        "recommended_structure": rec_struct,
        "recommended_duration_min": dur_min,
        "recommended_duration_max": dur_max,
        "suggested_duration": dur_str,
        "reasons": selected_reasons,
        "components": strat_comps,
        "created_at": created_iso,
    }


def get_recent_strategy_scores(
    limit: int = 20,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera avaliações estratégicas recentes do SQLite."""
    init_strategy_db(db_path)
    with get_connection(db_path) as conn:
        rows = conn.execute(
            """
            SELECT * FROM (
                SELECT 
                    *,
                    ROW_NUMBER() OVER (
                        PARTITION BY COALESCE(trend_id, topic) 
                        ORDER BY created_at DESC, id DESC
                    ) AS rn
                FROM content_strategy_scores
            ) WHERE rn = 1
            ORDER BY created_at DESC, id DESC LIMIT ?;
            """,
            (limit,)
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("reasons_json"):
                try:
                    d["reasons"] = json.loads(d["reasons_json"])
                except Exception:
                    d["reasons"] = []
            dur_min = d.get("recommended_duration_min")
            dur_max = d.get("recommended_duration_max")
            if dur_min and dur_max:
                d["suggested_duration"] = f"{int(dur_min)}–{int(dur_max)}s"
            else:
                d["suggested_duration"] = "62–75s"
            result.append(d)
        return result


def build_strategy_batch(
    evaluated_ideas: List[Dict[str, Any]],
    target_count: int = 10,
    has_sufficient_history: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Monta lote estratégico diversificado priorizando strategy_score e respeitando cotas de mix."""
    if not evaluated_ideas:
        return []

    count = min(target_count, len(evaluated_ideas))

    # 1. Definição de cotas ideais de mix (proporção para lote de 10)
    if has_sufficient_history:
        quotas = {
            BUCKET_PROVEN_WINNER: max(1, round(0.30 * count)),
            BUCKET_TREND_OPPORTUNITY: max(1, round(0.30 * count)),
            BUCKET_EVERGREEN: max(1, round(0.20 * count)),
            BUCKET_EXPERIMENT: max(1, round(0.10 * count)),
            BUCKET_DIVERSITY: max(1, round(0.10 * count)),
        }
    else:
        quotas = {
            BUCKET_PROVEN_WINNER: 0,
            BUCKET_TREND_OPPORTUNITY: max(1, round(0.40 * count)),
            BUCKET_EVERGREEN: max(1, round(0.30 * count)),
            BUCKET_EXPERIMENT: max(1, round(0.20 * count)),
            BUCKET_DIVERSITY: max(1, round(0.10 * count)),
        }

    # Ajusta soma para ser no máximo count
    while sum(quotas.values()) > count:
        for k in reversed(list(quotas.keys())):
            if quotas[k] > 0 and sum(quotas.values()) > count:
                quotas[k] -= 1

    # 2. Agrupamento das ideias por bucket e ordenação por strategy_score decrescente
    by_bucket: Dict[str, List[Dict[str, Any]]] = {
        BUCKET_PROVEN_WINNER: [],
        BUCKET_TREND_OPPORTUNITY: [],
        BUCKET_EVERGREEN: [],
        BUCKET_EXPERIMENT: [],
        BUCKET_DIVERSITY: [],
    }
    for item in evaluated_ideas:
        b = item.get("strategy_bucket", BUCKET_EXPERIMENT)
        by_bucket.setdefault(b, []).append(item)

    for b in by_bucket:
        by_bucket[b].sort(key=lambda x: x.get("strategy_score", 0.0), reverse=True)

    # 3. Alocação das ideias respeitando cotas
    selected: List[Dict[str, Any]] = []
    selected_topics = set()

    for b, q in quotas.items():
        candidates = by_bucket.get(b, [])
        allocated = 0
        for cand in candidates:
            top_key = (cand.get("topic") or "").strip().lower()
            if top_key not in selected_topics:
                selected.append(cand)
                selected_topics.add(top_key)
                allocated += 1
                if allocated >= q:
                    break

    # 4. Se cotas não atingiram count, preenche com as melhores ideias remanescentes por strategy_score
    if len(selected) < count:
        remaining = [
            cand for cand in sorted(evaluated_ideas, key=lambda x: x.get("strategy_score", 0.0), reverse=True)
            if (cand.get("topic") or "").strip().lower() not in selected_topics
        ]
        for cand in remaining:
            selected.append(cand)
            selected_topics.add((cand.get("topic") or "").strip().lower())
            if len(selected) >= count:
                break

    # 5. Ordenação e interleaving para evitar repetição consecutiva de cluster e estrutura
    ordered: List[Dict[str, Any]] = []
    pool = list(selected)

    last_cluster = None
    last_struct = None

    while pool:
        best_candidate_idx = None
        for i, cand in enumerate(pool):
            c_clust = cand.get("topic_cluster")
            c_struct = cand.get("recommended_structure")
            if (last_cluster is None or c_clust != last_cluster) and (last_struct is None or c_struct != last_struct):
                best_candidate_idx = i
                break

        if best_candidate_idx is None:
            for i, cand in enumerate(pool):
                c_clust = cand.get("topic_cluster")
                if last_cluster is None or c_clust != last_cluster:
                    best_candidate_idx = i
                    break

        if best_candidate_idx is None:
            best_candidate_idx = 0

        picked = pool.pop(best_candidate_idx)
        ordered.append(picked)
        last_cluster = picked.get("topic_cluster")
        last_struct = picked.get("recommended_structure")

    return ordered
