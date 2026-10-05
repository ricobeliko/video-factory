"""
app/services/visual_matching.py
===============================
V16.5 — Visual Matching v2: Semantic adherence, candidate scoring, diversity, and fallback.

Responsabilidade:
1. Extrair intenção visual estruturada (SceneVisualIntent) por cena a partir da narração e contexto.
2. Gerar queries de busca descritivas e em tiers de especificidade, evitando pesquisas genéricas.
3. Avaliar candidatos retornados por provedores com score determinístico (0-100) baseado em:
   - Termos semânticos (título, tags, slug)
   - Aderência à query e intenção
   - Orientação/proporção e duração útil
   - Penalidade de repetição (diversidade global e cena imediatamente anterior)
4. Orquestrar fallback ordenado e observabilidade auditável para script_data.
"""

from __future__ import annotations

import re
from dataclasses import asdict, dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple
from urllib.parse import urlparse

from app.models.schema import MaterialInfo, VideoAspect


# Termos genéricos banidos de queries de busca de cena
BANNED_GENERIC_TERMS: Set[str] = {
    "cinematic visual",
    "cinematic stock",
    "generic footage",
    "generic stock",
    "generic video",
    "stock video",
    "stock footage",
    "background video",
    "fundo de video",
    "fundo de tela",
    "video escuro",
    "fundo escuro",
}


@dataclass
class SceneVisualIntent:
    """Intenção visual estruturada para uma cena (V16.5)."""
    primary_subject: str
    action: str
    environment: str
    visual_style: str
    must_include: List[str] = field(default_factory=list)
    avoid: List[str] = field(default_factory=list)
    search_queries: List[str] = field(default_factory=list)
    scene_index: int = 1
    confidence: float = 1.0

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "SceneVisualIntent":
        return cls(
            primary_subject=str(data.get("primary_subject", "")),
            action=str(data.get("action", "")),
            environment=str(data.get("environment", "")),
            visual_style=str(data.get("visual_style", "cinematic realistic")),
            must_include=list(data.get("must_include", [])),
            avoid=list(data.get("avoid", [])),
            search_queries=list(data.get("search_queries", [])),
            scene_index=int(data.get("scene_index", 1)),
            confidence=float(data.get("confidence", 1.0)),
        )


def _extract_title_from_url(url: Optional[str]) -> str:
    """Extrai título semântico a partir do slug de uma URL de provedor."""
    if not url:
        return ""
    try:
        path = urlparse(url).path
        parts = [p for p in path.strip("/").split("/") if p]
        if parts:
            slug = parts[-1]
            slug = re.sub(r"-\d+$", "", slug)
            return slug.replace("-", " ").replace("_", " ").strip()
    except Exception:
        pass
    return ""


# =============================================================================
# Léxico Semântico Determinístico para Conceitos de Alto Impacto
# =============================================================================

_DOMAIN_CONCEPTS: List[Dict[str, Any]] = [
    # 1. Fenômenos Meteorológicos e Desastres: Tornados / Furacões
    {
        "patterns": [
            r"\b(tornado|tornados|twister|twisters|funil|funis|redemoinho|redemoinhos|tromba d'?água)\b",
            r"\b(furac[aã]o|furac[oõ]es|ciclone|ciclones|tuf[aã]o)\b",
        ],
        "primary_subject": "large tornado funnel",
        "action": "rotating spinning across landscape touching ground",
        "environment": "dark severe storm clouds rural field plains",
        "visual_style": "dramatic cinematic weather documentary",
        "must_include": ["tornado", "storm"],
        "avoid": ["cartoon", "indoor", "sunny clear sky"],
        "queries": [
            "large tornado rotating across rural field storm clouds close view",
            "tornado spinning dark storm clouds severe weather",
            "tornado funnel cloud touching ground plains",
            "tornado storm destruction weather",
        ],
    },
    # 2. Terremotos e Tremores Sísmicos
    {
        "patterns": [
            r"\b(terremoto|terremotos|terramoto|terramotos|abalo s[ií]smico|abalos s[ií]smicos|sismo|sismos|tremor|tremores|falha geol[oó]gica)\b",
        ],
        "primary_subject": "earthquake aftermath rubble",
        "action": "ground shaking cracks destruction damaged buildings",
        "environment": "urban city street disaster zone ruins",
        "visual_style": "dramatic realistic news documentary",
        "must_include": ["earthquake", "destruction"],
        "avoid": ["cartoon", "party", "sunny beach"],
        "queries": [
            "earthquake ground cracks rubble destruction urban street",
            "earthquake damage fallen buildings rubble emergency",
            "seismic destruction broken road aftermath",
            "earthquake disaster ruins",
        ],
    },
    # 3. Vulcões e Erupções
    {
        "patterns": [
            r"\b(vulc[aã]o|vulc[oõ]es|erup[cç][aã]o|erup[cç][oõ]es|lava|magma|cinzas vulc[aâ]nicas|cratera|fluxo pirocl[aá]stico)\b",
        ],
        "primary_subject": "active volcano erupting",
        "action": "spewing glowing lava exploding dark ash cloud",
        "environment": "volcanic mountain night sky smoking crater",
        "visual_style": "dramatic high contrast nature documentary",
        "must_include": ["volcano", "lava"],
        "avoid": ["snow blizzard", "cartoon", "indoor"],
        "queries": [
            "active volcano erupting glowing lava flow night dark sky",
            "volcanic eruption smoke ash cloud explosive",
            "molten lava river flowing dark rock crater",
            "volcano eruption nature cinematic",
        ],
    },
    # 4. Auroras Polares
    {
        "patterns": [
            r"\b(aurora boreal|aurora austral|auroras boreais|luzes do norte|northern lights|polar lights|aurora)\b",
        ],
        "primary_subject": "green aurora borealis lights",
        "action": "dancing glowing waving across starry night sky",
        "environment": "arctic snowy landscape night stars frozen lake",
        "visual_style": "timelapse cinematic 4k landscape",
        "must_include": ["aurora", "borealis"],
        "avoid": ["daylight sunshine", "city traffic", "indoor room"],
        "queries": [
            "green aurora borealis dancing across arctic starry night sky",
            "northern lights glowing over snowy mountains night",
            "polar aurora green waves starry sky timelapse",
            "aurora borealis northern lights nature",
        ],
    },
    # 5. Tsunamis, Enchentes e Inundações
    {
        "patterns": [
            r"\b(tsunami|tsunamis|maremoto|maremotos|enchente|enchentes|inunda[cç][aã]o|inunda[cç][oõ]es)\b",
        ],
        "primary_subject": "massive tsunami flood wave",
        "action": "surging crashing rising flooding coastline streets",
        "environment": "stormy sea coastal town heavy turbulent water",
        "visual_style": "dramatic powerful documentary",
        "must_include": ["tsunami", "flood"],
        "avoid": ["calm pool", "sunny dry desert"],
        "queries": [
            "massive tsunami ocean wave surge crashing shore",
            "flood water surging through streets heavy rain",
            "turbulent flooding water disaster torrent",
            "tsunami storm surge waves",
        ],
    },
    # 6. Tempestades e Raios / Relâmpagos
    {
        "patterns": [
            r"\b(raio|raios|rel[aâ]mpago|rel[aâ]mpagos|trov[aã]o|trov[oõ]es|tempestade el[eé]trica|tempestades)\b",
        ],
        "primary_subject": "lightning strike bolt",
        "action": "flashing striking dramatic dark stormy clouds",
        "environment": "severe thunderstorm dark sky night horizon",
        "visual_style": "high speed dramatic weather capture",
        "must_include": ["lightning", "storm"],
        "avoid": ["sunny day", "indoor office"],
        "queries": [
            "lightning bolt striking dark storm clouds dramatic night",
            "severe thunderstorm lightning flash clouds",
            "thunderstorm rain dark sky lightning horizon",
            "lightning storm night sky",
        ],
    },
    # 7. Floresta Tropical / Amazônia
    {
        "patterns": [
            r"\b(floresta amaz[oô]nica|amaz[oô]nia|floresta tropical|rainforest|mata atl[aâ]ntica|selva|floresta|matas)\b",
        ],
        "primary_subject": "dense amazon rainforest canopy",
        "action": "aerial flying over lush green trees winding river mist",
        "environment": "tropical rainforest wilderness river morning mist",
        "visual_style": "aerial drone cinematic 4k nature",
        "must_include": ["rainforest", "forest"],
        "avoid": ["city skyline", "dry desert"],
        "queries": [
            "aerial drone over lush green amazon rainforest winding river",
            "tropical rainforest morning mist dense trees canopy",
            "rainforest jungle river flowing aerial",
            "rainforest green trees nature aerial",
        ],
    },
    # 8. Oceano / Mar Profundo
    {
        "patterns": [
            r"\b(oceano|oceanos|mar|mares|ondas gigantes|profundezas marinhas|abismo submarino|recife de corais)\b",
        ],
        "primary_subject": "deep blue ocean rolling waves",
        "action": "crashing surging powerful water slow motion",
        "environment": "open wild ocean horizon stormy waters or coral reef",
        "visual_style": "cinematic aquatic footage slow motion",
        "must_include": ["ocean", "waves"],
        "avoid": ["desert", "traffic"],
        "queries": [
            "deep blue ocean waves rolling crashing slow motion",
            "dramatic ocean waves surge aerial view",
            "crystal clear ocean water marine horizon",
            "ocean waves sea surface",
        ],
    },
    # 9. Montanhas e Cumes Nevados
    {
        "patterns": [
            r"\b(montanha|montanhas|pico|picos|cordilheira|alpes|cume nevado|cordilheiras)\b",
        ],
        "primary_subject": "majestic snow covered mountain peaks",
        "action": "clouds rolling past rugged peaks sunny horizon",
        "environment": "alpine mountain range high altitude rocky landscape",
        "visual_style": "epic cinematic landscape wide angle",
        "must_include": ["mountain", "peaks"],
        "avoid": ["underwater", "indoor"],
        "queries": [
            "majestic snowy mountain peaks clouds rolling aerial",
            "rugged mountain summit alpine range landscape",
            "mountain peaks panoramic landscape epic",
            "mountain range nature landscape",
        ],
    },
    # 10. Deserto e Dunas
    {
        "patterns": [
            r"\b(deserto|desertos|duna|dunas|areia escaldante|tempestade de areia|saara)\b",
        ],
        "primary_subject": "vast golden desert sand dunes",
        "action": "wind blowing sand glowing sunset shadows",
        "environment": "arid desert wilderness sunset expanse",
        "visual_style": "warm glowing cinematic landscape",
        "must_include": ["desert", "dunes"],
        "avoid": ["snow", "rain", "rainforest"],
        "queries": [
            "golden desert sand dunes wind blowing sunset aerial",
            "vast arid desert landscape ripples sand dunes",
            "desert sand storm warm sunset cinematic",
            "desert sand dunes landscape",
        ],
    },
    # 11. Espaço, Astronomia e Galáxias
    {
        "patterns": [
            r"\b(espa[cç]o|universo|gal[aá]xia|gal[aá]xias|estrelas|telesc[oó]pio|buraco negro|nebulosa|foguete|lua|planeta|planetas|cosmo|c[oó]smico)\b",
        ],
        "primary_subject": "deep space galaxy and glowing nebula",
        "action": "spinning cosmic dust twinkling stars orbiting planets",
        "environment": "infinite deep cosmos dark space colorful nebula",
        "visual_style": "astronomical sci-fi cinematic render",
        "must_include": ["space", "galaxy"],
        "avoid": ["underwater", "street traffic"],
        "queries": [
            "deep space galaxy glowing colorful nebula stars spinning",
            "outer space orbiting planet stars cosmos background",
            "cosmic nebula deep space stars universe",
            "galaxy space stars universe",
        ],
    },
    # 12. Tecnologia, IA e Cyber
    {
        "patterns": [
            r"\b(intelig[eê]ncia artificial|ia|rob[oô]|rob[oô]s|rob[oó]tica|computador|servidores|circuitos|dados|chips|cibern[eé]tico|c[oó]digo)\b",
        ],
        "primary_subject": "futuristic artificial intelligence technology",
        "action": "glowing digital data streams motherboard circuits processing",
        "environment": "modern high tech server room dark digital cyberspace",
        "visual_style": "cyber high tech glowing macro",
        "must_include": ["technology", "digital"],
        "avoid": ["ancient", "rural farm"],
        "queries": [
            "futuristic artificial intelligence glowing digital circuits processor",
            "server room data transfer glowing blue led cables",
            "digital network abstract technology glowing lines",
            "technology cyber artificial intelligence",
        ],
    },
    # 13. Metrópole Urbana e Trânsito
    {
        "patterns": [
            r"\b(cidade|cidades|metr[oó]pole|arranha-c[eé]u|arranha-c[eé]us|tr[aâ]nsito|avenida|rua movimentada|urban|metropolitan)\b",
        ],
        "primary_subject": "modern metropolitan city skyline",
        "action": "bustling traffic light trails aerial drone flying",
        "environment": "urban downtown towering skyscrapers sunset night",
        "visual_style": "modern urban drone cinematic timelapse",
        "must_include": ["city", "skyline"],
        "avoid": ["jungle", "deep forest"],
        "queries": [
            "modern city skyline skyscrapers drone shot sunset",
            "urban downtown traffic bustling street lights night",
            "aerial view metropolitan city highway traffic",
            "city skyline urban architecture",
        ],
    },
]


def extract_scene_visual_intent(
    narration: str,
    video_subject: Optional[str] = None,
    scene_index: int = 1,
    total_scenes: int = 1,
    previous_intent: Optional[SceneVisualIntent] = None,
) -> SceneVisualIntent:
    """
    Extrai uma intenção visual estruturada e determinística para a cena.
    Mapeia termos do roteiro (em português ou inglês) e do assunto global para
    consultas em inglês ricas e em tiers de especificidade.
    """
    text_clean = (narration or "").strip().lower()
    subj_clean = (video_subject or "").strip().lower()
    combined_text = f"{subj_clean} {text_clean}"

    matched_concept: Optional[Dict[str, Any]] = None

    # 1. Verifica casamento contra a base de conceitos determinísticos
    for concept in _DOMAIN_CONCEPTS:
        for pat in concept["patterns"]:
            if re.search(pat, combined_text, re.IGNORECASE):
                matched_concept = concept
                break
        if matched_concept:
            break

    if matched_concept:
        # Enriquece queries com contexto da cena quando relevante
        queries = list(matched_concept["queries"])
        return SceneVisualIntent(
            primary_subject=matched_concept["primary_subject"],
            action=matched_concept["action"],
            environment=matched_concept["environment"],
            visual_style=matched_concept["visual_style"],
            must_include=list(matched_concept["must_include"]),
            avoid=list(matched_concept["avoid"]),
            search_queries=queries,
            scene_index=scene_index,
            confidence=0.95,
        )

    # 2. Extração aberta baseada em tokens salientes quando não casa conceito fixo
    raw_tokens = re.findall(r"\b[a-zA-ZáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]{3,}\b", text_clean)
    from app.services.scene_planner import ALL_STOPWORDS
    salient = [t for t in raw_tokens if t not in ALL_STOPWORDS]

    subj_tokens = re.findall(r"\b[a-zA-ZáéíóúâêîôûãõçÁÉÍÓÚÂÊÎÔÛÃÕÇ]{3,}\b", subj_clean)
    salient_subj = [t for t in subj_tokens if t not in ALL_STOPWORDS]

    primary_sub = " ".join(salient[:2]) if salient else (video_subject or "cinematic scene")
    action_desc = "moving through scene"
    env_desc = "natural or urban background"

    tier1_terms = []
    if video_subject:
        tier1_terms.append(video_subject.strip())
    if salient:
        tier1_terms.extend(salient[:3])
    tier1_query = " ".join(dict.fromkeys(tier1_terms)) + " cinematic view"

    tier2_query = " ".join(dict.fromkeys(salient[:2] or salient_subj[:2])) + " documentary"
    tier3_query = video_subject.strip() if video_subject else "nature landscape"
    tier4_query = "documentary stock footage"

    queries = [
        q for q in [tier1_query, tier2_query, tier3_query, tier4_query]
        if q and q.lower() not in BANNED_GENERIC_TERMS
    ]
    if not queries:
        queries = [f"{primary_sub} cinematic"]

    return SceneVisualIntent(
        primary_subject=primary_sub,
        action=action_desc,
        environment=env_desc,
        visual_style="cinematic realistic",
        must_include=salient[:2],
        avoid=["cartoon", "graphic design"],
        search_queries=queries,
        scene_index=scene_index,
        confidence=0.6,
    )


# =============================================================================
# Algoritmo de Pontuação Determinística de Candidatos
# =============================================================================

def score_candidate_material(
    candidate: MaterialInfo,
    visual_intent: SceneVisualIntent,
    target_aspect: VideoAspect = VideoAspect.portrait,
    used_asset_ids: Optional[Set[str]] = None,
    last_selected_asset_id: Optional[str] = None,
    scene_duration_hint: Optional[float] = None,
    search_query_used: str = "",
) -> Tuple[float, Dict[str, Any]]:
    """
    Calcula um score determinístico (0 a 100) para um candidato a material.

    Critérios:
    - Termos Semânticos (0 - 45 pts): correspondência de subject, action, environment, must_include vs title, tags, slug.
    - Correspondência com a Query (0 - 25 pts): tokens da query presente nos metadados.
    - Proporção / Resolução (0 - 15 pts): orientação estrita e aspecto.
    - Duração Útil (0 - 10 pts): proporção da duração em relação à cena.
    - Penalidades de Repetição: -50 pts se repete cena anterior; -35 pts se já usado na tarefa.
    """
    breakdown: Dict[str, Any] = {
        "semantic_score": 0.0,
        "query_score": 0.0,
        "aspect_score": 0.0,
        "duration_score": 0.0,
        "repetition_penalty": 0.0,
        "avoid_penalty": 0.0,
        "matched_terms": [],
    }

    source_info = (
        candidate.source_info
        if isinstance(candidate.source_info, dict)
        else {}
    )

    # 1. Monta o corpus textual do candidato
    candidate_texts: List[str] = []

    # Título explícito ou extraído da URL
    title = str(source_info.get("title") or "")
    if not title:
        title = _extract_title_from_url(source_info.get("source_page") or candidate.url)
    if title:
        candidate_texts.append(title)

    # Tags do provedor (Pixabay / Coverr / Pexels)
    tags = source_info.get("tags") or []
    if isinstance(tags, list):
        candidate_texts.extend([str(t) for t in tags])
    elif isinstance(tags, str):
        candidate_texts.append(tags)

    # Termo original de busca registrado no source_info
    orig_term = str(source_info.get("search_term") or "")
    if orig_term:
        candidate_texts.append(orig_term)

    # URL / página de origem
    candidate_texts.append(str(source_info.get("source_page") or candidate.url or ""))

    combined_corpus = " ".join(candidate_texts).lower()
    corpus_tokens = set(re.findall(r"\w+", combined_corpus))

    # --- A. Pontuação Semântica (0 a 45 pts) ---
    semantic_pts = 0.0

    # Primary subject (até 20 pts): casamento da entidade principal dá base de 14 pts + proporcional
    subject_tokens = [t.lower() for t in re.findall(r"\w+", visual_intent.primary_subject) if len(t) > 2]
    matched_subject = [t for t in subject_tokens if t in corpus_tokens]
    if subject_tokens and matched_subject:
        subj_ratio = len(matched_subject) / len(subject_tokens)
        semantic_pts += 14.0 + (subj_ratio * 6.0)
        breakdown["matched_terms"].extend(matched_subject)

    # Action (até 10 pts)
    action_tokens = [t.lower() for t in re.findall(r"\w+", visual_intent.action) if len(t) > 2]
    matched_action = [t for t in action_tokens if t in corpus_tokens]
    if action_tokens and matched_action:
        act_ratio = len(matched_action) / len(action_tokens)
        semantic_pts += 5.0 + (act_ratio * 5.0)
        breakdown["matched_terms"].extend(matched_action)

    # Environment (até 10 pts)
    env_tokens = [t.lower() for t in re.findall(r"\w+", visual_intent.environment) if len(t) > 2]
    matched_env = [t for t in env_tokens if t in corpus_tokens]
    if env_tokens and matched_env:
        env_ratio = len(matched_env) / len(env_tokens)
        semantic_pts += 5.0 + (env_ratio * 5.0)
        breakdown["matched_terms"].extend(matched_env)

    # Must-include bonus (até 10 pts)
    for mi in visual_intent.must_include:
        mi_clean = mi.strip().lower()
        if mi_clean and (mi_clean in combined_corpus or mi_clean in corpus_tokens):
            semantic_pts += 10.0
            breakdown["matched_terms"].append(f"must_include:{mi_clean}")
            break

    # Avoid penalty (-25 pts)
    for av in visual_intent.avoid:
        av_clean = av.strip().lower()
        if av_clean and (av_clean in combined_corpus or av_clean in corpus_tokens):
            breakdown["avoid_penalty"] = -25.0
            break

    breakdown["semantic_score"] = round(min(45.0, semantic_pts), 2)

    # --- B. Correspondência com a Query Usada (0 a 25 pts) ---
    query_tokens = [t.lower() for t in re.findall(r"\w+", search_query_used) if len(t) > 2]
    if query_tokens:
        matched_q = [t for t in query_tokens if t in corpus_tokens]
        if matched_q:
            q_ratio = len(matched_q) / len(query_tokens)
            breakdown["query_score"] = round(12.0 + (q_ratio * 13.0), 2)
        else:
            breakdown["query_score"] = 0.0
    else:
        # Se nenhuma query específica passada, atribui pontuação moderada baseada no subject
        breakdown["query_score"] = 15.0 if matched_subject else 5.0

    # --- C. Orientação e Aspect Ratio (0 a 15 pts) ---
    aspect = VideoAspect(target_aspect)
    rendition = source_info.get("rendition") or {}
    w = int(rendition.get("width") or 0)
    h = int(rendition.get("height") or 0)

    if w > 0 and h > 0:
        is_port = h > w
        is_land = w > h
        is_sq = w == h

        if aspect == VideoAspect.portrait:
            if is_port:
                breakdown["aspect_score"] = 15.0
            elif is_sq:
                breakdown["aspect_score"] = 8.0
            else:
                breakdown["aspect_score"] = -30.0  # Orientação errada
        elif aspect == VideoAspect.landscape:
            if is_land:
                breakdown["aspect_score"] = 15.0
            elif is_sq:
                breakdown["aspect_score"] = 8.0
            else:
                breakdown["aspect_score"] = -30.0
        elif aspect == VideoAspect.square:
            breakdown["aspect_score"] = 15.0 if is_sq else 12.0
    else:
        # Rendition sem dimensões explícitas mas aceito pelo filtro do provedor
        breakdown["aspect_score"] = 10.0

    # --- D. Duração Útil (0 a 10 pts) ---
    target_dur = float(scene_duration_hint or 5.0)
    cand_dur = float(candidate.duration or 0.0)

    if cand_dur >= target_dur:
        if cand_dur <= target_dur * 4.0:
            breakdown["duration_score"] = 10.0
        elif cand_dur <= target_dur * 8.0:
            breakdown["duration_score"] = 7.0
        else:
            breakdown["duration_score"] = 4.0
    elif cand_dur >= target_dur * 0.7:
        breakdown["duration_score"] = 5.0
    else:
        breakdown["duration_score"] = 1.0

    # --- E. Penalidades de Repetição e Diversidade ---
    asset_id = str(source_info.get("asset_id") or source_info.get("id") or candidate.url or "")

    if last_selected_asset_id and asset_id == last_selected_asset_id:
        breakdown["repetition_penalty"] -= 50.0  # Repetição consecutiva imediata
    elif used_asset_ids and asset_id in used_asset_ids:
        breakdown["repetition_penalty"] -= 35.0  # Repetição global no mesmo vídeo

    raw_total = (
        breakdown["semantic_score"]
        + breakdown["query_score"]
        + breakdown["aspect_score"]
        + breakdown["duration_score"]
        + breakdown["avoid_penalty"]
        + breakdown["repetition_penalty"]
    )
    final_score = max(0.0, min(100.0, round(raw_total, 2)))
    breakdown["total_score"] = final_score

    return final_score, breakdown


# =============================================================================
# Ranking e Seleção de Candidatos
# =============================================================================

def rank_and_select_candidates(
    candidates: List[MaterialInfo],
    visual_intent: SceneVisualIntent,
    target_aspect: VideoAspect = VideoAspect.portrait,
    used_asset_ids: Optional[Set[str]] = None,
    last_selected_asset_id: Optional[str] = None,
    scene_duration_hint: Optional[float] = None,
    search_query_used: str = "",
    min_acceptable_score: float = 30.0,
) -> Tuple[Optional[MaterialInfo], float, str, List[Dict[str, Any]]]:
    """
    Avalia e ordena deterministamente todos os candidatos retornados.
    Retorna o melhor candidato, seu score, motivo da escolha e sumário auditável.
    """
    if not candidates:
        return None, 0.0, "NO_CANDIDATES", []

    scored_list: List[Tuple[MaterialInfo, float, Dict[str, Any]]] = []

    for c in candidates:
        score, bdown = score_candidate_material(
            candidate=c,
            visual_intent=visual_intent,
            target_aspect=target_aspect,
            used_asset_ids=used_asset_ids,
            last_selected_asset_id=last_selected_asset_id,
            scene_duration_hint=scene_duration_hint,
            search_query_used=search_query_used,
        )
        scored_list.append((c, score, bdown))

    # Ordena decrescente por score
    scored_list.sort(key=lambda x: x[1], reverse=True)

    best_cand, best_score, best_bdown = scored_list[0]

    # Prepara sumário auditável resumido dos top 5 candidatos
    audit_summary: List[Dict[str, Any]] = []
    for c, sc, bd in scored_list[:5]:
        si = c.source_info if isinstance(c.source_info, dict) else {}
        aid = str(si.get("asset_id") or si.get("id") or c.url)
        audit_summary.append({
            "asset_id": aid,
            "score": sc,
            "matched_terms": bd.get("matched_terms", []),
            "repetition_penalty": bd.get("repetition_penalty", 0.0),
        })

    asset_id = str((best_cand.source_info or {}).get("asset_id") or best_cand.url)
    matched_str = ",".join(best_bdown.get("matched_terms", [])[:3])
    reason = f"score={best_score:.1f} terms=[{matched_str}] asset={asset_id}"

    return best_cand, best_score, reason, audit_summary
