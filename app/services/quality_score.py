import contextlib
import json
import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const

# Caminho opcional override do SQLite (útil em testes)
DB_PATH: Optional[str] = None

# Faixas Operacionais Heurísticas
LABEL_STRONG = "STRONG"  # 85–100
LABEL_GOOD = "GOOD"      # 70–84
LABEL_REVIEW = "REVIEW"  # 55–69
LABEL_WEAK = "WEAK"      # 0–54

# Ponderação Nominal Inicial (Soma = 1.00 / 100%)
COMPONENT_WEIGHTS = {
    "hook_strength": 0.15,
    "originality": 0.15,
    "trend_strength": 0.10,
    "niche_relevance": 0.10,
    "source_confidence": 0.05,
    "repetition_risk": 0.10,
    "narrative_fit": 0.10,
    "duration_fit": 0.10,
    "historical_performance": 0.10,
    "visual_match": 0.05,
}

# Palavras-chave concretas (alto potencial visual pesquisável)
CONCRETE_VISUAL_KEYWORDS = {
    "oceano", "mar", "agua", "onda", "tubarao", "peixe", "baleia",
    "aviao", "voo", "asa", "piloto", "ceu", "nuvem", "espaco", "lua", "sol",
    "vulcao", "lava", "fogo", "gelo", "geleira", "neve", "montanha", "floresta",
    "arvore", "rio", "cachoeira", "animal", "leao", "cachorro", "gato", "passaro",
    "ouro", "diamante", "castelo", "piramide", "navio", "carro", "trem", "cidade",
    "planeta", "estrela", "universo", "robo", "maquina", "rocha", "pedra",
    "dinossauro", "fossil", "deserto", "tempestade", "raio", "floresta",
}

# Palavras-chave abstratas (baixo potencial visual imediato)
ABSTRACT_CONCEPT_KEYWORDS = {
    "significado", "existencial", "existencialismo", "filosofia", "dilema",
    "moral", "metafisica", "sentimento", "pensamento", "mente", "alma",
    "reflexao", "abstrato", "inconsciente", "logica", "paradoxo",
    "etica", "intencao", "consciencia",
}


def _get_default_db_path() -> str:
    if DB_PATH:
        return DB_PATH
    from app.services import scheduler
    return scheduler.get_db_path()


@contextlib.contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o SQLite em modo WAL garantindo integridade e fechamento."""
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


def init_quality_db(db_path: Optional[str] = None) -> None:
    """Inicializa a tabela content_quality_scores de forma idempotente."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_quality_scores (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT,
                trend_id TEXT,
                topic TEXT NOT NULL,
                niche TEXT,
                preset TEXT,
                narrative_structure TEXT,
                hook_text TEXT,
                quality_score REAL NOT NULL,
                quality_label TEXT NOT NULL,
                hook_score REAL,
                originality_score REAL,
                trend_score REAL,
                relevance_score REAL,
                source_confidence_score REAL,
                repetition_score REAL,
                narrative_fit_score REAL,
                duration_fit_score REAL,
                historical_performance_score REAL,
                visual_match_score REAL,
                reasons_json TEXT,
                created_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_task ON content_quality_scores(task_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_trend ON content_quality_scores(trend_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_quality_created ON content_quality_scores(created_at);"
        )


def _normalize_text(text: str) -> str:
    """Normaliza texto para comparação lexical."""
    if not text:
        return ""
    cleaned = text.strip().lower()
    cleaned = "".join(
        c for c in unicodedata.normalize("NFKD", cleaned)
        if not unicodedata.combining(c)
    )
    return re.sub(r"\s+", " ", cleaned).strip()


def calculate_hook_strength(
    hook_text: str,
    recent_hooks: Optional[List[str]] = None,
) -> Tuple[float, List[str]]:
    """Avalia a força do hook (primeira frase ou chamada inicial)."""
    norm = _normalize_text(hook_text)
    if not norm:
        return 50.0, ["Sem texto de hook explícito"]

    score = 70.0
    reasons = []

    # 1. Penalidade para introdução genérica
    generic_patterns = [
        r"^hoje vamos falar",
        r"^neste video",
        r"^ola pessoal",
        r"^bem vindos",
        r"^no video de hoje",
        r"^vamos falar sobre",
    ]
    is_generic = any(re.search(pat, norm) for pat in generic_patterns)
    if is_generic:
        score -= 40.0
        reasons.append("Início genérico com preâmbulo desnecessário (-)")
    else:
        # 2. Bônus para início direto com gatilho de curiosidade
        curiosity_triggers = [
            "voce sabia", "por que", "como", "o misterio", "o segredo",
            "a verdade sobre", "o que acontece", "qual e", "o estranho caso",
            "o dia em que", "3 fatos", "fatos sobre", "sera que",
        ]
        has_curiosity = any(trig in norm for trig in curiosity_triggers) or norm.endswith("?")
        if has_curiosity:
            score += 20.0
            reasons.append("Hook direto com gatilho de curiosidade (+)")
        else:
            score += 5.0
            reasons.append("Início objetivo sem enrolação (+)")

    # 3. Penalidade para CTA prematuro no início
    cta_patterns = [
        "inscreva se", "inscrevase", "deixe seu like", "curta e compartilhe",
        "siga o canal", "nao esqueca de curtir",
    ]
    if any(pat in norm for pat in cta_patterns):
        score -= 30.0
        reasons.append("Chamada para ação (CTA) prematura no gancho (-)")

    # 4. Penalidade para hook repetido no histórico recente
    if recent_hooks:
        for prev in recent_hooks:
            norm_prev = _normalize_text(prev)
            if norm_prev and SequenceMatcher(None, norm, norm_prev).ratio() >= 0.75:
                score -= 30.0
                reasons.append("Gancho muito similar a conteúdos recentes (-)")
                break

    final_score = round(max(0.0, min(100.0, score)), 1)
    return final_score, reasons


def calculate_originality(
    topic: str,
    recent_topics: Optional[List[str]] = None,
) -> Tuple[float, List[str]]:
    """Avalia originalidade frente ao histórico recente."""
    norm_topic = _normalize_text(topic)
    if not recent_topics or not norm_topic:
        return 95.0, ["Tema original sem repetições no histórico recente (+)"]

    max_sim = 0.0
    for prev in recent_topics:
        norm_prev = _normalize_text(prev)
        if norm_prev:
            sim = SequenceMatcher(None, norm_topic, norm_prev).ratio()
            if sim > max_sim:
                max_sim = sim

    orig_score = round(max(0.0, min(100.0, (1.0 - max_sim) * 100.0)), 1)
    if orig_score >= 80.0:
        reasons = ["Tema com alta originalidade e baixo overlap recente (+)"]
    elif orig_score >= 50.0:
        reasons = ["Tema moderadamente similar a tópicos já abordados (neutro)"]
    else:
        reasons = ["Tema altamente repetitivo ou quase idêntico a conteúdo recente (-)"]

    return orig_score, reasons


def calculate_trend_strength(
    trend_id: Optional[str] = None,
    trend_score: Optional[float] = None,
    opportunity_score: Optional[float] = None,
    source_count: int = 1,
    verification: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """Avalia o sinal de tendência a partir do Trend Radar se presente."""
    if not trend_id:
        return None, []

    t_sc = float(trend_score) if trend_score is not None else 50.0
    opp_sc = float(opportunity_score) if opportunity_score is not None else t_sc

    base = 0.6 * opp_sc + 0.4 * t_sc
    if verification == "multi" or (source_count and source_count > 1):
        base += 5.0

    final_score = round(max(0.0, min(100.0, base)), 1)
    reasons = [f"Respaldado por sinal de tendência comprovado ({final_score}/100) (+)"]
    return final_score, reasons


def calculate_niche_relevance(
    topic: str,
    niche: Optional[str] = None,
    trend_relevance_score: Optional[float] = None,
) -> Tuple[float, List[str]]:
    """Avalia relevância ao nicho pretendido."""
    # 1. Prioridade absoluta ao relevance_score vindo do Trend Radar (V4)
    if trend_relevance_score is not None:
        rel = float(trend_relevance_score)
        reasons = [f"Relevância calibrada pelo Trend Radar: {rel:.1f}/100"]
        return round(max(0.0, min(100.0, rel)), 1), reasons

    # 2. Fallback lexical apenas quando NÃO existir relevance_score válido da V4
    norm_t = _normalize_text(topic)
    norm_n = _normalize_text(niche or "")
    if not norm_n:
        return 75.0, ["Nicho não especificado (score neutro)"]

    # Se o nicho for Curiosidades, nunca inflar temas políticos/institucionais só pela palavra "curiosidades"
    if norm_n in ("curiosidades", "curiosidade"):
        political_tokens = [
            "stf", "ministra", "ministro", "governo", "senado", "deputado",
            "congresso", "presidenciável", "presidenciavel", "partido", "eleicao",
            "eleição", "politica", "política", "lula", "bolsonaro", "stj"
        ]
        if any(tok in norm_t for tok in political_tokens):
            return 20.0, ["Tema institucional/político com baixa aderência ao nicho de curiosidades (-)"]

        curiosity_tokens = ["por que", "como", "fatos", "misterio", "segredo", "descobri", "verdade", "sabia"]
        if any(tok in norm_t for tok in curiosity_tokens):
            return 85.0, ["Termos com alta aderência ao nicho de curiosidades (+)"]
        if norm_n in norm_t:
            return 65.0, ["Menciona curiosidades mas sem gancho instigante"]
        return 60.0, ["Aderência moderada ao nicho de curiosidades"]

    if norm_n in norm_t:
        return 90.0, [f"Alinhamento direto com o nicho '{niche}' (+)"]

    return 70.0, [f"Relevância estimada ao nicho '{niche}'"]


def calculate_source_confidence(
    confidence_str: Optional[str] = None,
    source: Optional[str] = None,
    source_count: int = 1,
    verification: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """Converte source confidence em score 0-100 normalizado conforme regras da V4/V6."""
    if not confidence_str and not source:
        return None, []

    conf_clean = (confidence_str or "").strip().upper()
    src_clean = (source or "").strip().lower()
    is_multi = (verification in ("multi_source", "multi") or (source_count and source_count > 1))
    is_google = src_clean in ("google_trends", "google-trends", "trends", "google")
    is_rss = "rss" in src_clean
    is_reddit = "reddit" in src_clean

    # Regra 1: LOW é sempre 40
    if conf_clean == "LOW":
        return 40.0, ["Confiança de fonte baixa (LOW: 40) (-)"]

    # Regra 2: Google Trends oficial ou multi_source -> HIGH = 100
    if is_google or is_multi:
        if conf_clean == "MEDIUM":
            return 70.0, ["Confiança de fonte moderada (MEDIUM: 70)"]
        return 100.0, ["Confiança de fonte alta oficial/multi-source (HIGH: 100) (+)"]

    # Regra 3: RSS single_source -> sempre normalizado para MEDIUM = 70 (mesmo com label legado HIGH)
    if is_rss:
        return 70.0, ["Confiança de fonte moderada (RSS single-source normalizado: 70)"]

    # Regra 4: Reddit single_source -> no máximo MEDIUM = 70
    if is_reddit:
        return 70.0, ["Confiança de fonte moderada (Reddit single-source: 70)"]

    # Fallback geral quando source é desconhecida
    if conf_clean == "HIGH":
        if verification == "single_source":
            return 70.0, ["Confiança de fonte moderada (single-source normalizado: 70)"]
        return 100.0, ["Confiança de fonte alta (HIGH: 100) (+)"]
    elif conf_clean == "MEDIUM":
        return 70.0, ["Confiança de fonte moderada (MEDIUM: 70)"]

    return None, []


def calculate_repetition_risk(
    topic: str,
    narrative_structure: Optional[str] = None,
    recent_items: Optional[List[Dict[str, Any]]] = None,
) -> Tuple[float, List[str]]:
    """Calcula risco de repetição e inverte em score de qualidade (baixo risco = alto score)."""
    if not recent_items:
        return 95.0, ["Sem risco de repetição contra o histórico recente (+)"]

    norm_topic = _normalize_text(topic)
    risk = 10.0  # baseline baixo risco

    # 1. Risco por similaridade de tópico
    max_sim = 0.0
    for it in recent_items:
        prev_t = _normalize_text(it.get("topic") or it.get("title") or "")
        if prev_t:
            sim = SequenceMatcher(None, norm_topic, prev_t).ratio()
            if sim > max_sim:
                max_sim = sim
    risk += max_sim * 50.0

    # 2. Risco por repetição excessiva da mesma estrutura narrativa recente
    if narrative_structure and len(recent_items) >= 2:
        last_structs = [it.get("narrative_structure") for it in recent_items[:2]]
        if all(s == narrative_structure for s in last_structs):
            risk += 25.0

    risk = max(0.0, min(100.0, risk))
    repetition_score = round(100.0 - risk, 1)

    if repetition_score >= 80.0:
        reasons = ["Baixo risco de repetição temática e estrutural (+)"]
    elif repetition_score >= 55.0:
        reasons = ["Risco moderado de sobreposição temática (atenção)"]
    else:
        reasons = ["Alto risco de repetição com conteúdos recentes (-)"]

    return repetition_score, reasons


def calculate_narrative_fit(
    topic: str,
    narrative_structure: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """Avalia o alinhamento lexical da estrutura narrativa ao tema."""
    if not narrative_structure:
        return None, []

    clean_struct = narrative_structure.strip().lower()
    norm_t = _normalize_text(topic)

    keywords_by_struct = {
        const.STRUCTURE_MYSTERY: [
            "misterio", "segredo", "enigma", "descoberta", "fenomeno",
            "estranho", "desapareceu", "sumiu", "verdade", "por que",
        ],
        const.STRUCTURE_EXPLAINER: [
            "como funciona", "ciencia", "explicacao", "causa", "efeito",
            "por que", "fisica", "biologia", "entenda", "motivo",
        ],
        const.STRUCTURE_FACT_CONTEXT: [
            "fatos", "curiosidades", "historia", "historico", "origem",
            "mundo", "lista", "detalhes", "coisas que",
        ],
        const.STRUCTURE_MYTH_REALITY: [
            "mito", "verdade", "mentira", "crenca", "realidade", "falso",
            "enganado", "sera que", "ilusao",
        ],
        const.STRUCTURE_SHORT_STORY: [
            "homem", "mulher", "caso", "aconteceu", "historia de", "jornada",
            "vida", "tragedia", "saga", "menino", "menina",
        ],
    }

    target_keywords = keywords_by_struct.get(clean_struct, [])
    matches = sum(1 for kw in target_keywords if kw in norm_t)

    if matches >= 2:
        score = 95.0
        reasons = [f"Forte alinhamento temático com a estrutura '{clean_struct}' (+)"]
    elif matches == 1:
        score = 85.0
        reasons = [f"Bom alinhamento temático com a estrutura '{clean_struct}' (+)"]
    else:
        score = 70.0
        reasons = [f"Alinhamento neutro com a estrutura '{clean_struct}'"]

    return score, reasons


def calculate_duration_fit(
    estimated_duration: Optional[float] = None,
    actual_duration: Optional[float] = None,
    word_count: Optional[int] = None,
    preset: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """Avalia se a duração prevista ou real está alinhada às metas do preset."""
    # Duração real pós-TTS sempre prevalece
    duration = actual_duration or estimated_duration
    if duration is None and word_count:
        # Estimativa pré-TTS: ~2.3 palavras faladas por segundo
        duration = word_count / 2.3

    if duration is None or not preset:
        return None, []

    from app.services import safety_gate
    spec = safety_gate.MONETIZATION_PRESET_SPECS.get(preset)
    if not spec:
        return 75.0, ["Preset sem limites estritos"]

    target_min = spec["target_duration_min"]
    target_max = spec["target_duration_max"]
    min_acceptable = spec["min_acceptable_duration"]

    if target_min <= duration <= target_max:
        return 100.0, [f"Duração ideal ({duration:.1f}s) dentro da meta ({target_min}–{target_max}s) (+)"]
    elif duration >= min_acceptable:
        return 85.0, [f"Duração aceitável ({duration:.1f}s) para o preset '{preset}'"]
    else:
        # Violação de duração mínima (ex: < 60s no TikTok Rewards)
        return 30.0, [f"Duração ({duration:.1f}s) abaixo do mínimo aceitável ({min_acceptable}s) (-)"]


def calculate_historical_performance_signal(
    narrative_structure: Optional[str] = None,
    preset: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Tuple[Optional[float], List[str]]:
    """Consulta V5 Analytics; retorna None caso haja menos de 3 amostras."""
    from app.services import analytics
    try:
        feedback = analytics.get_content_performance_feedback(db_path=db_path)
    except Exception:
        return None, []

    # Verificar amostras por estrutura
    if narrative_structure:
        struct_data = feedback.get("structures", {}).get(narrative_structure)
        if struct_data and struct_data.get("count", 0) >= 3:
            rel_diff = struct_data.get("relative_diff", 0.0)
            score = round(max(0.0, min(100.0, 70.0 + rel_diff)), 1)
            prefix = "+" if rel_diff > 0 else ""
            reasons = [f"Histórico positivo para a estrutura ({prefix}{rel_diff}% performance) (+)"]
            return score, reasons

    # Verificar amostras por preset
    if preset:
        preset_data = feedback.get("presets", {}).get(preset)
        if preset_data and preset_data.get("count", 0) >= 3:
            rel_diff = preset_data.get("relative_diff", 0.0)
            score = round(max(0.0, min(100.0, 70.0 + rel_diff)), 1)
            prefix = "+" if rel_diff > 0 else ""
            reasons = [f"Histórico positivo para o preset ({prefix}{rel_diff}% performance) (+)"]
            return score, reasons

    # Menos de 3 amostras: estritamente None sem conclusões fortes
    return None, []


def calculate_visual_match_potential(
    topic: str,
    script_text: Optional[str] = None,
) -> Tuple[float, List[str]]:
    """Avalia a presença de conceitos visuais concretos vs conceitos puramente abstratos."""
    full_text = f"{topic} {script_text or ''}"
    norm = _normalize_text(full_text)
    words = set(re.findall(r"\w+", norm))

    concrete_matches = words.intersection(CONCRETE_VISUAL_KEYWORDS)
    abstract_matches = words.intersection(ABSTRACT_CONCEPT_KEYWORDS)

    if len(concrete_matches) >= 2 and not abstract_matches:
        score = 95.0
        reasons = ["Alto potencial visual com termos concretos pesquisáveis (+)"]
    elif len(concrete_matches) >= 1:
        score = 80.0
        reasons = ["Bom potencial visual com elementos concretos (+)"]
    elif abstract_matches:
        score = 45.0
        reasons = ["Tema com alta abstração conceitual, requerendo busca visual criativa (-)"]
    else:
        score = 70.0
        reasons = ["Potencial visual padrão com termos genéricos"]

    return score, reasons


def determine_quality_label(quality_score: float) -> str:
    """Classifica o score em faixas operacionais explicáveis."""
    if quality_score >= 85.0:
        return LABEL_STRONG
    elif quality_score >= 70.0:
        return LABEL_GOOD
    elif quality_score >= 55.0:
        return LABEL_REVIEW
    else:
        return LABEL_WEAK


def evaluate_quality(
    topic: str,
    niche: Optional[str] = None,
    hook_text: Optional[str] = None,
    script_text: Optional[str] = None,
    preset: Optional[str] = None,
    narrative_structure: Optional[str] = None,
    trend_id: Optional[str] = None,
    trend_score: Optional[float] = None,
    opportunity_score: Optional[float] = None,
    relevance_score: Optional[float] = None,
    source_confidence: Optional[str] = None,
    source: Optional[str] = None,
    source_count: int = 1,
    verification: Optional[str] = None,
    estimated_duration: Optional[float] = None,
    actual_duration: Optional[float] = None,
    word_count: Optional[int] = None,
    task_id: Optional[str] = None,
    persist: bool = False,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Avalia determinística e integralmente a qualidade e potencial do conteúdo."""
    effective_hook = hook_text or (script_text.split(".")[0] if script_text else topic)

    # Se trend_id for fornecido e algum metadado do Trend Radar estiver faltando, busca em trend_items
    if trend_id:
        try:
            with get_connection(db_path) as conn:
                has_trend = conn.execute(
                    "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trend_items';"
                ).fetchone()
                if has_trend:
                    t_row = conn.execute(
                        "SELECT source, source_count, verification, trend_score, relevance_score, source_confidence, opportunity_score FROM trend_items WHERE trend_id = ?;",
                        (trend_id,)
                    ).fetchone()
                    if t_row:
                        t_dict = dict(t_row)
                        if trend_score is None:
                            trend_score = t_dict.get("trend_score")
                        if relevance_score is None:
                            relevance_score = t_dict.get("relevance_score")
                        if opportunity_score is None:
                            opportunity_score = t_dict.get("opportunity_score")
                        if source_confidence is None:
                            source_confidence = t_dict.get("source_confidence")
                        if source is None:
                            source = t_dict.get("source")
                        if source_count is None or source_count <= 1:
                            source_count = t_dict.get("source_count") or 1
                        if verification is None:
                            verification = t_dict.get("verification")
        except Exception:
            pass

    # 1. Recuperar dados recentes para originalidade e repetição (excluindo a própria task)
    recent_topics = []
    recent_hooks = []
    recent_items = []
    try:
        with get_connection(db_path) as conn:
            check_table = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name='monetization_safety';"
            ).fetchone()
            if check_table:
                clean_tid = str(task_id or "").strip()
                if clean_tid:
                    rows = conn.execute(
                        "SELECT task_id, topic, hook_text, narrative_structure FROM monetization_safety "
                        "WHERE task_id IS NULL OR task_id <> ? "
                        "ORDER BY checked_at DESC LIMIT 15;",
                        (clean_tid,),
                    ).fetchall()
                else:
                    rows = conn.execute(
                        "SELECT task_id, topic, hook_text, narrative_structure FROM monetization_safety "
                        "ORDER BY checked_at DESC LIMIT 15;"
                    ).fetchall()
                for r in rows:
                    row_tid = str(r["task_id"] or "").strip() if "task_id" in r.keys() else ""
                    if clean_tid and row_tid and row_tid == clean_tid:
                        continue
                    if r["topic"]:
                        recent_topics.append(r["topic"])
                    if r["hook_text"]:
                        recent_hooks.append(r["hook_text"])
                    recent_items.append(dict(r))
    except Exception:
        pass

    # 2. Calcular scores individuais e capturar justificativas
    all_reasons = []

    s_hook, r_hook = calculate_hook_strength(effective_hook, recent_hooks=recent_hooks)
    all_reasons.extend(r_hook)

    s_orig, r_orig = calculate_originality(topic, recent_topics=recent_topics)
    all_reasons.extend(r_orig)

    s_trend, r_trend = calculate_trend_strength(
        trend_id=trend_id,
        trend_score=trend_score,
        opportunity_score=opportunity_score,
        source_count=source_count,
        verification=verification,
    )
    all_reasons.extend(r_trend)

    s_niche, r_niche = calculate_niche_relevance(
        topic=topic, niche=niche, trend_relevance_score=relevance_score
    )
    all_reasons.extend(r_niche)

    s_src, r_src = calculate_source_confidence(
        confidence_str=source_confidence,
        source=source,
        source_count=source_count,
        verification=verification,
    )
    all_reasons.extend(r_src)

    s_rep, r_rep = calculate_repetition_risk(
        topic=topic, narrative_structure=narrative_structure, recent_items=recent_items
    )
    all_reasons.extend(r_rep)

    s_narr, r_narr = calculate_narrative_fit(topic=topic, narrative_structure=narrative_structure)
    all_reasons.extend(r_narr)

    s_dur, r_dur = calculate_duration_fit(
        estimated_duration=estimated_duration,
        actual_duration=actual_duration,
        word_count=word_count,
        preset=preset,
    )
    all_reasons.extend(r_dur)

    s_hist, r_hist = calculate_historical_performance_signal(
        narrative_structure=narrative_structure, preset=preset, db_path=db_path
    )
    all_reasons.extend(r_hist)

    s_vis, r_vis = calculate_visual_match_potential(topic=topic, script_text=script_text)
    all_reasons.extend(r_vis)

    # 3. Ponderação proporcional entre os componentes disponíveis
    components = {
        "hook_strength": s_hook,
        "originality": s_orig,
        "trend_strength": s_trend,
        "niche_relevance": s_niche,
        "source_confidence": s_src,
        "repetition_risk": s_rep,
        "narrative_fit": s_narr,
        "duration_fit": s_dur,
        "historical_performance": s_hist,
        "visual_match": s_vis,
    }

    available_weight = sum(
        COMPONENT_WEIGHTS[k] for k, v in components.items() if v is not None
    )

    if available_weight > 0:
        weighted_sum = sum(
            (v * COMPONENT_WEIGHTS[k]) for k, v in components.items() if v is not None
        )
        final_quality_score = round(weighted_sum / available_weight, 1)
    else:
        final_quality_score = 50.0

    final_quality_score = max(0.0, min(100.0, final_quality_score))
    label = determine_quality_label(final_quality_score)

    # Limitar justificativas às top 3 a 5 mais relevantes
    selected_reasons = all_reasons[:5] if all_reasons else ["Avaliação com base nos parâmetros disponíveis"]

    record_id = None
    created_iso = datetime.now(timezone.utc).isoformat()

    # 4. Persistência opcional no SQLite
    if persist:
        init_quality_db(db_path)
        with get_connection(db_path) as conn:
            cursor = conn.execute(
                """
                INSERT INTO content_quality_scores (
                    task_id, trend_id, topic, niche, preset, narrative_structure,
                    hook_text, quality_score, quality_label,
                    hook_score, originality_score, trend_score, relevance_score,
                    source_confidence_score, repetition_score, narrative_fit_score,
                    duration_fit_score, historical_performance_score, visual_match_score,
                    reasons_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    task_id, trend_id, topic, niche, preset, narrative_structure,
                    effective_hook, final_quality_score, label,
                    s_hook, s_orig, s_trend, s_niche,
                    s_src, s_rep, s_narr,
                    s_dur, s_hist, s_vis,
                    json.dumps(selected_reasons), created_iso,
                ),
            )
            record_id = cursor.lastrowid

    return {
        "id": record_id,
        "task_id": task_id,
        "trend_id": trend_id,
        "topic": topic,
        "niche": niche,
        "preset": preset,
        "narrative_structure": narrative_structure,
        "hook_text": effective_hook,
        "quality_score": final_quality_score,
        "quality_label": label,
        "components": components,
        "reasons": selected_reasons,
        "created_at": created_iso,
    }


def get_recent_quality_scores(
    limit: int = 20,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera avaliações de qualidade recentes do banco preservando dados de tendência."""
    init_quality_db(db_path)
    with get_connection(db_path) as conn:
        has_trend_table = conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='trend_items';"
        ).fetchone()
        if has_trend_table:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT
                        cqs.*,
                        ti.source AS trend_source,
                        ti.source_count AS trend_source_count,
                        ti.verification AS trend_verification,
                        ti.trend_score AS trend_radar_trend_score,
                        ti.relevance_score AS trend_radar_relevance_score,
                        ti.source_confidence AS trend_radar_source_confidence,
                        ti.opportunity_score AS trend_radar_opportunity_score,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(cqs.trend_id, cqs.topic)
                            ORDER BY cqs.created_at DESC, cqs.id DESC
                        ) AS rn
                    FROM content_quality_scores cqs
                    LEFT JOIN trend_items ti ON cqs.trend_id = ti.trend_id
                ) WHERE rn = 1
                ORDER BY created_at DESC, id DESC LIMIT ?;
                """,
                (limit,)
            ).fetchall()
        else:
            rows = conn.execute(
                """
                SELECT * FROM (
                    SELECT
                        *,
                        ROW_NUMBER() OVER (
                            PARTITION BY COALESCE(trend_id, topic)
                            ORDER BY created_at DESC, id DESC
                        ) AS rn
                    FROM content_quality_scores
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
            if d.get("trend_id"):
                d["source"] = d.get("trend_source") or d.get("source")
                d["source_count"] = d.get("trend_source_count") or d.get("source_count") or 1
                d["verification"] = d.get("trend_verification") or d.get("verification")
                if d.get("trend_radar_relevance_score") is not None:
                    d["relevance_score"] = d["trend_radar_relevance_score"]
                if d.get("trend_radar_trend_score") is not None:
                    d["trend_score"] = d["trend_radar_trend_score"]
                if d.get("trend_radar_opportunity_score") is not None:
                    d["opportunity_score"] = d["trend_radar_opportunity_score"]
                if d.get("trend_radar_source_confidence") is not None:
                    d["source_confidence"] = d["trend_radar_source_confidence"]
            result.append(d)
        return result
