import os
import re
import sqlite3
import unicodedata
from datetime import datetime, timezone
from difflib import SequenceMatcher
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.utils import utils

# Reutilizar normalização de tópico do autopilot se disponível
try:
    from app.services.autopilot import normalize_topic
except ImportError:
    _NORMALIZE_PUNCT_RE = re.compile(
        r"[" + re.escape("!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~") + r"]"
    )

    def normalize_topic(text: str) -> str:
        if not text:
            return ""
        cleaned = text.strip().lower()
        cleaned = "".join(
            c
            for c in unicodedata.normalize("NFKD", cleaned)
            if not unicodedata.combining(c)
        )
        cleaned = _NORMALIZE_PUNCT_RE.sub(" ", cleaned)
        return re.sub(r"\s+", " ", cleaned).strip()


# ---------------------------------------------------------------------------
# Estruturas Narrativas
# ---------------------------------------------------------------------------

NARRATIVE_STRUCTURE_SPECS: Dict[str, Dict[str, Any]] = {
    const.STRUCTURE_MYSTERY: {
        "id": const.STRUCTURE_MYSTERY,
        "name": "Mistério Investigativo",
        "description": "Gancho intrigante -> Fato -> Pistas/contexto -> Revelação -> Conclusão aberta",
        "steps": [
            "Gancho enigmático ou pergunta instigante",
            "Apresentação do fato principal",
            "Pistas e contexto detalhado",
            "Revelação surpreendente ou reviravolta",
            "Conclusão aberta provocando reflexão",
        ],
        "prompt_pt": (
            "ESTRUTURA NARRATIVA: Mistério Investigativo\n"
            "1. Comece com um gancho intrigante ou enigma instigante (NUNCA use 'Você sabia que' ou 'Hoje vamos falar').\n"
            "2. Apresente o fato central de forma cativante.\n"
            "3. Desenvolva pistas, contexto e detalhes analíticos aprofundados.\n"
            "4. Revele a descoberta ou ponto de virada com impacto.\n"
            "5. Conclua com uma reflexão ou pergunta aberta memorável."
        ),
    },
    const.STRUCTURE_EXPLAINER: {
        "id": const.STRUCTURE_EXPLAINER,
        "name": "Explicador",
        "description": "Problema/pergunta -> Explicação -> Exemplo -> Impacto -> Conclusão",
        "steps": [
            "Problema ou pergunta prática",
            "Explicação clara do conceito central",
            "Exemplo concreto ou analogia",
            "Impacto real no mundo ou na vida",
            "Conclusão sintética e memorável",
        ],
        "prompt_pt": (
            "ESTRUTURA NARRATIVA: Explicador\n"
            "1. Apresente um problema concreto ou pergunta direta ao ouvinte.\n"
            "2. Explique a causa ou o conceito de forma simples, fluida e clara.\n"
            "3. Use um exemplo prático ou analogia vívida.\n"
            "4. Mostre o impacto real e por que isso importa.\n"
            "5. Conclua com um resumo sintético e marcante."
        ),
    },
    const.STRUCTURE_FACT_CONTEXT: {
        "id": const.STRUCTURE_FACT_CONTEXT,
        "name": "Fato + Contexto",
        "description": "Acontecimento -> Contexto histórico/científico -> Por que importa -> Implicação",
        "steps": [
            "Acontecimento ou descoberta central",
            "Contexto histórico ou científico profundo",
            "Por que isso importa de verdade",
            "Implicações futuras ou consequências",
        ],
        "prompt_pt": (
            "ESTRUTURA NARRATIVA: Fato + Contexto\n"
            "1. Apresente um acontecimento ou dado fascinante logo na abertura.\n"
            "2. Forneça contexto histórico, científico ou social que dê profundidade ao fato.\n"
            "3. Explique por que esse fato importa e o que ele muda na nossa visão.\n"
            "4. Finalize com as implicações futuras ou consequências diretas."
        ),
    },
    const.STRUCTURE_MYTH_REALITY: {
        "id": const.STRUCTURE_MYTH_REALITY,
        "name": "Mito vs Realidade",
        "description": "Crença comum -> Contraponto -> Evidência/contexto -> Explicação -> Conclusão",
        "steps": [
            "Crença comum ou mito popular",
            "Contraponto revelando a verdade",
            "Evidência concreta e contexto",
            "Explicação científica ou lógica",
            "Conclusão prática desmistificada",
        ],
        "prompt_pt": (
            "ESTRUTURA NARRATIVA: Mito vs Realidade\n"
            "1. Exponha uma crença comum ou suposição popular logo de início.\n"
            "2. Apresente o contraponto que quebra essa expectativa com firmeza.\n"
            "3. Traga a evidência concreta e o contexto que comprova o equívoco.\n"
            "4. Explique a razão lógica ou científica por trás da realidade.\n"
            "5. Feche com uma conclusão desmistificada e definitiva."
        ),
    },
    const.STRUCTURE_SHORT_STORY: {
        "id": const.STRUCTURE_SHORT_STORY,
        "name": "História Curta",
        "description": "Situação -> Conflito -> Descoberta -> Consequência -> Fechamento",
        "steps": [
            "Situação inicial ou evento",
            "Conflito ou obstáculo inesperado",
            "Descoberta ou ponto de virada",
            "Consequência prática",
            "Fechamento marcante",
        ],
        "prompt_pt": (
            "ESTRUTURA NARRATIVA: História Curta\n"
            "1. Estabeleça uma situação envolvente ou evento inicial com ritmo vivo.\n"
            "2. Introduza um conflito, dilema ou obstáculo que gere curiosidade imediata.\n"
            "3. Revele a descoberta ou o ponto de virada decisivo.\n"
            "4. Mostre as consequências que isso causou.\n"
            "5. Finalize com um fechamento reflexivo e marcante."
        ),
    },
}


# ---------------------------------------------------------------------------
# Presets de Monetização
# ---------------------------------------------------------------------------

MONETIZATION_PRESET_SPECS: Dict[str, Dict[str, Any]] = {
    const.PRESET_CROSS_PLATFORM: {
        "id": const.PRESET_CROSS_PLATFORM,
        "name": "YouTube + TikTok Monetization",
        "description": "Duração alvo: 62–75s. Compatível com TikTok Rewards (>60s) e Shorts original.",
        "target_duration_min": 62.0,
        "target_duration_max": 75.0,
        "min_acceptable_duration": 60.0,
        "target_words_min": 140,
        "target_words_max": 175,
        "enforce_tiktok_rule": True,
        "prompt_pt": (
            "PRESET: YouTube + TikTok Monetization (Duração alvo: 62 a 75 segundos)\n"
            "- Duração falada obrigatória: entre 62 e 75 segundos (NUNCA abaixo de 60 segundos).\n"
            "- Meta de extensão: aproximadamente 140 a 175 palavras faladas em português brasileiro natural.\n"
            "- Desenvolva conteúdo aprofundado, com riqueza analítica e narrativa contínua para preencher o tempo com relevância.\n"
            "- O CTA (chamada para ação) é opcional: inclua apenas se agregar naturalmente, ou termine com reflexão."
        ),
    },
    const.PRESET_TIKTOK_REWARDS: {
        "id": const.PRESET_TIKTOK_REWARDS,
        "name": "TikTok Rewards",
        "description": "Duração alvo: 62–75s. Mínimo aceitável: >60s. Roteiro de 140–175 palavras.",
        "target_duration_min": 62.0,
        "target_duration_max": 75.0,
        "min_acceptable_duration": 60.0,
        "target_words_min": 140,
        "target_words_max": 175,
        "enforce_tiktok_rule": True,
        "prompt_pt": (
            "PRESET: TikTok Creator Rewards (Duração alvo: 62 a 75 segundos)\n"
            "- Duração falada obrigatória: entre 62 e 75 segundos (NUNCA abaixo de 60 segundos).\n"
            "- NÃO faça roteiros curtos de 30 a 50 segundos sob nenhuma hipótese.\n"
            "- Meta de extensão: aproximadamente 140 a 175 palavras faladas em ritmo natural.\n"
            "- Mantenha a audiência envolvida ao longo de todo o minuto com progressão narrativa rica."
        ),
    },
    const.PRESET_YOUTUBE_ORIGINAL: {
        "id": const.PRESET_YOUTUBE_ORIGINAL,
        "name": "YouTube Shorts Original",
        "description": "Duração alvo: 45–90s. Alta originalidade, comentário e análise autêntica.",
        "target_duration_min": 45.0,
        "target_duration_max": 90.0,
        "min_acceptable_duration": 30.0,
        "target_words_min": 100,
        "target_words_max": 210,
        "enforce_tiktok_rule": False,
        "prompt_pt": (
            "PRESET: YouTube Shorts Original (Duração sugerida: 45 a 90 segundos)\n"
            "- Duração falada flexível: entre 45 e 90 segundos.\n"
            "- Meta de extensão: aproximadamente 100 a 210 palavras faladas.\n"
            "- Alta originalidade: traga análise, interpretação e perspectiva própria, evitando resumos óbvios."
        ),
    },
}


# Clichês de abertura comuns em automações genéricas
_GENERIC_HOOK_PATTERNS = [
    re.compile(r"^\s*voc[eê]\s+sabia\s+que", re.IGNORECASE),
    re.compile(r"^\s*hoje\s+(vamos|eu\s+vou)\s+falar", re.IGNORECASE),
    re.compile(r"^\s*neste\s+v[ií]deo\s+(vamos|eu\s+vou)", re.IGNORECASE),
    re.compile(r"^\s*voc[eê]\s+n[aã]o\s+vai\s+acreditar", re.IGNORECASE),
    re.compile(r"^\s*seja\s+bem[- ]vindo", re.IGNORECASE),
    re.compile(r"^\s*ol[aá]\s+pessoal", re.IGNORECASE),
]


def get_preset_spec(preset_name: Optional[str]) -> Dict[str, Any]:
    """Retorna as especificações do preset com fallback para o padrão cross-platform."""
    clean = (preset_name or "").strip().lower()
    return MONETIZATION_PRESET_SPECS.get(clean, MONETIZATION_PRESET_SPECS[const.DEFAULT_MONETIZATION_PRESET])


def get_structure_spec(structure_name: Optional[str]) -> Optional[Dict[str, Any]]:
    """Retorna as especificações da estrutura narrativa ou None se não informada."""
    if not structure_name:
        return None
    clean = structure_name.strip().lower()
    return NARRATIVE_STRUCTURE_SPECS.get(clean)


def get_next_narrative_structure(
    recent_structures: Optional[List[str]] = None,
    current_index: int = 0,
) -> str:
    """Seleciona a próxima estrutura narrativa de forma variada e não-repetitiva.
    
    Regra:
    - Se houver histórico recente, evita repetir a mesma estrutura do último vídeo.
    - Se for geração em lote (current_index), varia sequencialmente entre as 5 opções.
    """
    structures = const.NARRATIVE_STRUCTURES
    if not recent_structures:
        return structures[current_index % len(structures)]

    last_structure = recent_structures[0] if recent_structures else None

    # Tenta usar a estrutura indicada pelo índice do lote, desde que diferente da anterior
    candidate = structures[current_index % len(structures)]
    if candidate != last_structure:
        return candidate

    # Se colidir com a última, avança para a próxima da lista
    next_idx = (current_index + 1) % len(structures)
    return structures[next_idx]


# ---------------------------------------------------------------------------
# Persistência SQLite: monetization_safety
# ---------------------------------------------------------------------------

def get_safety_db_path(custom_path: Optional[str] = None) -> str:
    if custom_path:
        return custom_path
    storage_folder = utils.storage_dir(create=True)
    return os.path.join(storage_folder, "video_factory.db")


def init_safety_db(db_path: Optional[str] = None) -> None:
    """Cria a tabela monetization_safety se não existir, de forma idempotente."""
    path = get_safety_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS monetization_safety (
                task_id TEXT PRIMARY KEY,
                topic TEXT,
                preset TEXT NOT NULL,
                narrative_structure TEXT,
                word_count INTEGER,
                estimated_duration REAL,
                actual_duration REAL,
                safety_status TEXT NOT NULL,
                safety_reasons TEXT,
                hook_text TEXT,
                cta_text TEXT,
                checked_at TEXT NOT NULL
            );
            """
        )
        # Migração idempotente para bancos existentes
        cols = [
            r[1]
            for r in conn.execute(
                "PRAGMA table_info(monetization_safety);"
            ).fetchall()
        ]
        if "topic" not in cols:
            conn.execute("ALTER TABLE monetization_safety ADD COLUMN topic TEXT;")
        conn.commit()
    finally:
        conn.close()


def save_safety_assessment(
    assessment: Dict[str, Any],
    db_path: Optional[str] = None,
) -> None:
    """Persiste ou atualiza uma avaliação de segurança de monetização."""
    init_safety_db(db_path)
    path = get_safety_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        reasons = assessment.get("safety_reasons")
        if isinstance(reasons, list):
            reasons_str = "; ".join(reasons)
        else:
            reasons_str = str(reasons or "")

        now_iso = assessment.get("checked_at") or datetime.now(timezone.utc).isoformat()

        conn.execute(
            """
            INSERT INTO monetization_safety (
                task_id, topic, preset, narrative_structure, word_count,
                estimated_duration, actual_duration, safety_status,
                safety_reasons, hook_text, cta_text, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                topic = excluded.topic,
                preset = excluded.preset,
                narrative_structure = excluded.narrative_structure,
                word_count = excluded.word_count,
                estimated_duration = excluded.estimated_duration,
                actual_duration = excluded.actual_duration,
                safety_status = excluded.safety_status,
                safety_reasons = excluded.safety_reasons,
                hook_text = excluded.hook_text,
                cta_text = excluded.cta_text,
                checked_at = excluded.checked_at;
            """,
            (
                assessment.get("task_id", ""),
                assessment.get("topic", ""),
                assessment.get("preset", const.DEFAULT_MONETIZATION_PRESET),
                assessment.get("narrative_structure"),
                assessment.get("word_count", 0),
                assessment.get("estimated_duration"),
                assessment.get("actual_duration"),
                assessment.get("safety_status", const.SAFETY_STATUS_PASS),
                reasons_str,
                assessment.get("hook_text", ""),
                assessment.get("cta_text", ""),
                now_iso,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def get_safety_assessment(
    task_id: str,
    db_path: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Consulta o resultado de segurança de uma tarefa."""
    init_safety_db(db_path)
    path = get_safety_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            """
            SELECT * FROM monetization_safety WHERE task_id = ?;
            """,
            (task_id,),
        ).fetchone()
        if not row:
            return None
        res = dict(row)
        if res.get("safety_reasons"):
            res["safety_reasons"] = [
                r.strip() for r in res["safety_reasons"].split(";") if r.strip()
            ]
        else:
            res["safety_reasons"] = []
        return res
    finally:
        conn.close()


def get_recent_safety_history(
    limit: int = 20,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Retorna os registros de segurança mais recentes para comparação."""
    init_safety_db(db_path)
    path = get_safety_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT * FROM monetization_safety
            ORDER BY checked_at DESC
            LIMIT ?;
            """,
            (limit,),
        ).fetchall()
        result = []
        for r in rows:
            d = dict(r)
            if d.get("safety_reasons"):
                d["safety_reasons"] = [
                    x.strip() for x in d["safety_reasons"].split(";") if x.strip()
                ]
            else:
                d["safety_reasons"] = []
            result.append(d)
        return result
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Funções de Extração e Similaridade Local (Stdlib Puro)
# ---------------------------------------------------------------------------

def extract_hook(script: str) -> str:
    """Extrai as primeiras 1 a 2 sentenças do roteiro (Hook)."""
    if not script:
        return ""
    sentences = [
        s.strip()
        for s in re.split(r"[.!?\n]+", script)
        if s.strip()
    ]
    if not sentences:
        return ""
    if len(sentences) == 1:
        return sentences[0]
    return f"{sentences[0]}. {sentences[1]}"


def extract_cta(script: str) -> str:
    """Extrai a última sentença do roteiro (CTA ou fechamento)."""
    if not script:
        return ""
    sentences = [
        s.strip()
        for s in re.split(r"[.!?\n]+", script)
        if s.strip()
    ]
    if not sentences:
        return ""
    return sentences[-1]


def first_sentence(text: str) -> str:
    """Extrai a primeira frase de um texto."""
    if not text:
        return ""
    parts = [s.strip() for s in re.split(r"[.!?\n]+", text) if s.strip()]
    return parts[0] if parts else text.strip()


def count_spoken_words(script: str) -> int:
    """Conta palavras faladas ignorando pontuações e quebras."""
    if not script:
        return 0
    words = re.findall(r"\b\w+\b", script, flags=re.UNICODE)
    return len(words)


def estimate_duration_seconds(word_count: int, words_per_second: float = 2.4) -> float:
    """Estima a duração em segundos a partir da contagem de palavras faladas em pt-BR."""
    if word_count <= 0:
        return 0.0
    return round(word_count / max(0.5, words_per_second), 1)


def text_similarity(s1: str, s2: str) -> float:
    """Calcula a similaridade textual local via SequenceMatcher."""
    n1 = normalize_topic(s1)
    n2 = normalize_topic(s2)
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0
    return SequenceMatcher(None, n1, n2).ratio()


def token_overlap(s1: str, s2: str) -> float:
    """Calcula o índice Jaccard de palavras entre dois textos."""
    w1 = set(normalize_topic(s1).split())
    w2 = set(normalize_topic(s2).split())
    if not w1 or not w2:
        return 0.0
    intersection = len(w1.intersection(w2))
    union = len(w1.union(w2))
    return float(intersection) / float(union) if union > 0 else 0.0


# ---------------------------------------------------------------------------
# Avaliação do Safety Gate V1
# ---------------------------------------------------------------------------

def evaluate_script_safety(
    task_id: str,
    topic: str,
    script: str,
    preset: Optional[str] = None,
    narrative_structure: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Avalia o roteiro (pré-TTS) contra repetição, clichês e estimativa de duração.
    
    Retorna checklist com PASS, REVIEW ou BLOCK.
    """
    preset_spec = get_preset_spec(preset)
    preset_id = preset_spec["id"]
    clean_topic = (topic or "").strip()
    clean_script = (script or "").strip()

    word_count = count_spoken_words(clean_script)
    est_duration = estimate_duration_seconds(word_count)
    hook = extract_hook(clean_script)
    cta = extract_cta(clean_script)

    reasons: List[str] = []
    status = const.SAFETY_STATUS_PASS

    # 1. Verificação de conteúdo vazio
    if not clean_script or word_count < 10:
        reasons.append("Roteiro vazio ou com conteúdo insuficiente")
        status = const.SAFETY_STATUS_BLOCK
        assessment = {
            "task_id": task_id,
            "preset": preset_id,
            "narrative_structure": narrative_structure,
            "word_count": word_count,
            "estimated_duration": est_duration,
            "actual_duration": None,
            "safety_status": status,
            "safety_reasons": reasons,
            "hook_text": hook,
            "cta_text": cta,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        save_safety_assessment(assessment, db_path=db_path)
        return assessment

    # 2. Clichês genéricos de abertura
    for pattern in _GENERIC_HOOK_PATTERNS:
        if pattern.search(clean_script):
            reasons.append("Abertura genérica/clichê detectada (evitar fórmulas repetitivas)")
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW
            break

    # 3. Estimativa de duração pré-TTS
    if preset_spec["enforce_tiktok_rule"]:
        if est_duration < 55.0 or word_count < 130:
            reasons.append(
                f"Estimativa de duração ({est_duration:.1f}s, {word_count} palavras) abaixo do alvo de 62–75s"
            )
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW

    # 4. Anti-repetição contra histórico recente
    if history is None:
        history = get_recent_safety_history(limit=20, db_path=db_path)

    # Filtrar o próprio task_id se já estiver no histórico
    relevant_history = [h for h in history if h.get("task_id") != task_id]

    consecutive_same_structure = 0
    for h in relevant_history:
        h_topic = h.get("topic") or ""
        h_hook = h.get("hook_text") or ""
        h_cta = h.get("cta_text") or ""

        # Similaridade de Tópico/Tema
        if clean_topic and h_topic:
            sim_topic = text_similarity(clean_topic, h_topic)
            if sim_topic >= 0.85:
                reasons.append(f"Tema altamente semelhante a vídeo recente ({sim_topic:.0%})")
                status = const.SAFETY_STATUS_BLOCK
            elif sim_topic >= 0.65:
                reasons.append(f"Tema com similaridade moderada a vídeo recente ({sim_topic:.0%})")
                if status != const.SAFETY_STATUS_BLOCK:
                    status = const.SAFETY_STATUS_REVIEW

        # Repetição de Hook
        if hook and h_hook:
            sim_hook_full = text_similarity(hook, h_hook)
            first_curr = first_sentence(hook)
            first_hist = first_sentence(h_hook)
            sim_hook_first = text_similarity(first_curr, first_hist) if first_curr and first_hist else 0.0
            sim_hook = max(sim_hook_full, sim_hook_first)
            if sim_hook >= 0.80:
                reasons.append(f"Hook/abertura muito semelhante a vídeo recente ({sim_hook:.0%})")
                status = const.SAFETY_STATUS_BLOCK

        # Repetição de CTA
        if cta and h_cta:
            sim_cta = text_similarity(cta, h_cta)
            if sim_cta >= 0.80:
                reasons.append(f"CTA muito semelhante ao vídeo recente ({sim_cta:.0%})")
                if status != const.SAFETY_STATUS_BLOCK:
                    status = const.SAFETY_STATUS_REVIEW

    # Repetição de estrutura consecutiva
    if narrative_structure:
        for h in relevant_history[:4]:
            if h.get("narrative_structure") == narrative_structure:
                consecutive_same_structure += 1
            else:
                break
        if consecutive_same_structure >= 3:
            reasons.append("Mesma estrutura narrativa usada 3+ vezes consecutivas")
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW

    assessment = {
        "task_id": task_id,
        "topic": clean_topic,
        "preset": preset_id,
        "narrative_structure": narrative_structure,
        "word_count": word_count,
        "estimated_duration": est_duration,
        "actual_duration": None,
        "safety_status": status,
        "safety_reasons": reasons,
        "hook_text": hook,
        "cta_text": cta,
        "checked_at": datetime.now(timezone.utc).isoformat(),
    }
    save_safety_assessment(assessment, db_path=db_path)
    return assessment


def evaluate_duration_safety(
    task_id: str,
    actual_duration: float,
    preset: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Reavalia a segurança da tarefa após a síntese de áudio (pós-TTS).
    
    Aplica a regra rígida de duração:
    - TikTok Rewards / Cross-platform: < 60s -> BLOCK absoluto
    - Alvo 62–75s -> PASS
    """
    assessment = get_safety_assessment(task_id, db_path=db_path)
    if not assessment:
        preset_spec = get_preset_spec(preset)
        assessment = {
            "task_id": task_id,
            "preset": preset_spec["id"],
            "narrative_structure": None,
            "word_count": 0,
            "estimated_duration": actual_duration,
            "actual_duration": actual_duration,
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
            "hook_text": "",
            "cta_text": "",
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }

    preset_spec = get_preset_spec(preset or assessment.get("preset"))
    reasons = list(assessment.get("safety_reasons") or [])
    status = assessment.get("safety_status", const.SAFETY_STATUS_PASS)

    actual_duration = round(float(actual_duration), 1)
    assessment["actual_duration"] = actual_duration

    # Regra para TikTok Rewards / Cross-Platform
    if preset_spec["enforce_tiktok_rule"]:
        if actual_duration < preset_spec["min_acceptable_duration"]:
            reasons.append(
                f"Duração de {actual_duration:.1f}s abaixo do mínimo de 60s para {preset_spec['name']}"
            )
            status = const.SAFETY_STATUS_BLOCK
        elif actual_duration < preset_spec["target_duration_min"]:
            reasons.append(
                f"Duração de {actual_duration:.1f}s ligeiramente abaixo do alvo de 62–75s"
            )
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW
    else:
        # YouTube Shorts Original
        if actual_duration < preset_spec["min_acceptable_duration"]:
            reasons.append(
                f"Duração de {actual_duration:.1f}s muito curta para {preset_spec['name']}"
            )
            status = const.SAFETY_STATUS_BLOCK

    assessment["safety_status"] = status
    assessment["safety_reasons"] = reasons
    assessment["checked_at"] = datetime.now(timezone.utc).isoformat()

    save_safety_assessment(assessment, db_path=db_path)
    return assessment
