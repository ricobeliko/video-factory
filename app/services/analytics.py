import contextlib
import json
import os
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

# Caminho opcional override do SQLite (útil em testes)
DB_PATH: Optional[str] = None

# Constantes de Buckets de Idade
BUCKET_0_24H = "0-24h"
BUCKET_24_72H = "24-72h"
BUCKET_3_7D = "3-7d"
BUCKET_7_30D = "7-30d"
BUCKET_OVER_30D = ">30d"

VALID_BUCKETS = (
    BUCKET_0_24H,
    BUCKET_24_72H,
    BUCKET_3_7D,
    BUCKET_7_30D,
    BUCKET_OVER_30D,
)


def _get_default_db_path() -> str:
    """Retorna o caminho padrão do SQLite do MoneyPrinterTurbo."""
    if DB_PATH:
        return DB_PATH
    from app.services import scheduler
    return scheduler.get_db_path()


@contextlib.contextmanager
def get_connection(db_path: Optional[str] = None):
    """Abre conexão com o SQLite em modo WAL garantindo integridade e timeout seguro."""
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


def init_analytics_db(db_path: Optional[str] = None) -> None:
    """Inicializa as tabelas de analytics de forma idempotente e segura."""
    with get_connection(db_path) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS content_analytics (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id TEXT NOT NULL,
                platform TEXT NOT NULL,
                external_id TEXT,
                publication_event_id INTEGER,
                trend_id TEXT,
                topic TEXT,
                preset TEXT,
                narrative_structure TEXT,
                duration_seconds REAL,
                views INTEGER NOT NULL DEFAULT 0,
                likes INTEGER NOT NULL DEFAULT 0,
                comments INTEGER NOT NULL DEFAULT 0,
                shares INTEGER NOT NULL DEFAULT 0,
                favorites INTEGER NOT NULL DEFAULT 0,
                average_view_duration REAL,
                average_percentage_viewed REAL,
                completion_rate REAL,
                subscribers_gained INTEGER,
                published_at TEXT NOT NULL,
                collected_at TEXT NOT NULL,
                age_bucket TEXT NOT NULL,
                engagement_rate REAL NOT NULL DEFAULT 0.0,
                retention_score REAL,
                performance_score REAL NOT NULL DEFAULT 0.0,
                metadata_json TEXT
            );
            """
        )

        # Índices essenciais para consultas rápidas
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_task ON content_analytics(task_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_platform ON content_analytics(platform);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_external ON content_analytics(external_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_trend ON content_analytics(trend_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_published ON content_analytics(published_at);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_analytics_collected ON content_analytics(collected_at);"
        )
        conn.execute(
            "CREATE UNIQUE INDEX IF NOT EXISTS idx_analytics_unique_snapshot "
            "ON content_analytics(platform, task_id, collected_at);"
        )


def _parse_iso_dt(dt_val: Any) -> datetime:
    """Converte string ISO ou datetime para datetime UTC aware."""
    if isinstance(dt_val, datetime):
        if dt_val.tzinfo is None:
            return dt_val.replace(tzinfo=timezone.utc)
        return dt_val.astimezone(timezone.utc)
    if isinstance(dt_val, str):
        clean_str = dt_val.strip()
        if clean_str.endswith("Z"):
            clean_str = clean_str[:-1] + "+00:00"
        try:
            dt = datetime.fromisoformat(clean_str)
            if dt.tzinfo is None:
                return dt.replace(tzinfo=timezone.utc)
            return dt.astimezone(timezone.utc)
        except Exception:
            pass
    return datetime.now(timezone.utc)


def calculate_age_bucket(published_at: Any, collected_at: Any) -> str:
    """Calcula o bucket de idade entre a publicação e a coleta."""
    p_dt = _parse_iso_dt(published_at)
    c_dt = _parse_iso_dt(collected_at)
    delta_hours = max(0.0, (c_dt - p_dt).total_seconds() / 3600.0)

    if delta_hours < 24.0:
        return BUCKET_0_24H
    elif delta_hours < 72.0:
        return BUCKET_24_72H
    elif delta_hours < 168.0:  # 7 dias
        return BUCKET_3_7D
    elif delta_hours <= 720.0:  # 30 dias
        return BUCKET_7_30D
    else:
        return BUCKET_OVER_30D


def validate_metrics(
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    favorites: int = 0,
    average_view_duration: Optional[float] = None,
    average_percentage_viewed: Optional[float] = None,
    completion_rate: Optional[float] = None,
    subscribers_gained: Optional[int] = None,
) -> None:
    """Valida métricas numéricas, rejeitando negativos e porcentagens > 100."""
    if views is not None and views < 0:
        raise ValueError(f"views cannot be negative: {views}")
    if likes is not None and likes < 0:
        raise ValueError(f"likes cannot be negative: {likes}")
    if comments is not None and comments < 0:
        raise ValueError(f"comments cannot be negative: {comments}")
    if shares is not None and shares < 0:
        raise ValueError(f"shares cannot be negative: {shares}")
    if favorites is not None and favorites < 0:
        raise ValueError(f"favorites cannot be negative: {favorites}")
    if average_view_duration is not None and average_view_duration < 0:
        raise ValueError(f"average_view_duration cannot be negative: {average_view_duration}")
    if average_percentage_viewed is not None:
        if average_percentage_viewed < 0 or average_percentage_viewed > 100:
            raise ValueError(
                f"average_percentage_viewed must be between 0 and 100: {average_percentage_viewed}"
            )
    if completion_rate is not None:
        if completion_rate < 0 or completion_rate > 100:
            raise ValueError(
                f"completion_rate must be between 0 and 100: {completion_rate}"
            )


def calculate_engagement_rate(
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
) -> float:
    """Calcula taxa de engajamento: (likes + comments + shares) / views se views > 0."""
    if views is None or views <= 0:
        return 0.0
    tot_interactions = (likes or 0) + (comments or 0) + (shares or 0)
    return round(float(tot_interactions) / float(views), 4)


def calculate_retention_score(
    completion_rate: Optional[float] = None,
    average_percentage_viewed: Optional[float] = None,
) -> Optional[float]:
    """Retorna o retention_score a partir das métricas disponíveis ou None se ausente."""
    if completion_rate is not None:
        return round(float(completion_rate), 2)
    if average_percentage_viewed is not None:
        return round(float(average_percentage_viewed), 2)
    return None


def _calculate_percentile(value: float, population: List[float]) -> float:
    """Calcula a posição percentil (0 a 100) de um valor frente à sua população."""
    if not population:
        return 50.0
    count_lower_or_equal = sum(1 for x in population if x <= value)
    percentile = (count_lower_or_equal / len(population)) * 100.0
    return round(max(0.0, min(100.0, percentile)), 1)


def calculate_performance_score(
    views: int,
    engagement_rate: float,
    retention_score: Optional[float],
    history_items: List[Dict[str, Any]],
) -> float:
    """Calcula o performance_score (0 a 100) normalizado relativamente ao histórico da mesma plataforma.

    Combina apenas as métricas disponíveis sem penalizar métricas ausentes.
    """
    if views == 0 and engagement_rate == 0.0 and retention_score is None:
        return 0.0

    if not history_items:
        # Se for a primeira medição ou sem histórico suficiente, baseline determinístico
        base_views = min(100.0, (views / 1000.0) * 50.0) if views > 0 else 25.0
        base_eng = min(100.0, engagement_rate * 500.0)
        if retention_score is not None:
            score = 0.4 * base_views + 0.3 * base_eng + 0.3 * retention_score
        else:
            score = 0.55 * base_views + 0.45 * base_eng
        return round(max(0.0, min(100.0, score)), 1)

    hist_views = [float(h.get("views") or 0) for h in history_items]
    hist_eng = [float(h.get("engagement_rate") or 0.0) for h in history_items]
    hist_ret = [
        float(h["retention_score"])
        for h in history_items
        if h.get("retention_score") is not None
    ]

    views_p = _calculate_percentile(float(views), hist_views)
    eng_p = _calculate_percentile(float(engagement_rate), hist_eng)

    if retention_score is not None and hist_ret:
        ret_p = _calculate_percentile(float(retention_score), hist_ret)
        score = 0.40 * views_p + 0.30 * eng_p + 0.30 * ret_p
    elif retention_score is not None and not hist_ret:
        # Primeiro item com retenção na plataforma
        ret_p = float(retention_score)
        score = 0.40 * views_p + 0.30 * eng_p + 0.30 * ret_p
    else:
        # Sem métrica de retenção: redistribui peso proporcionalmente sem penalizar
        score = 0.55 * views_p + 0.45 * eng_p

    return round(max(0.0, min(100.0, score)), 1)


def save_snapshot(
    task_id: str,
    platform: str,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    shares: int = 0,
    favorites: int = 0,
    average_view_duration: Optional[float] = None,
    average_percentage_viewed: Optional[float] = None,
    completion_rate: Optional[float] = None,
    subscribers_gained: Optional[int] = None,
    external_id: Optional[str] = None,
    publication_event_id: Optional[int] = None,
    trend_id: Optional[str] = None,
    topic: Optional[str] = None,
    preset: Optional[str] = None,
    narrative_structure: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    published_at: Optional[Any] = None,
    collected_at: Optional[Any] = None,
    metadata_json: Optional[Dict[str, Any]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Valida, calcula scores e persiste um snapshot de analytics para o vídeo."""
    init_analytics_db(db_path)

    # Validação estrita
    validate_metrics(
        views=views,
        likes=likes,
        comments=comments,
        shares=shares,
        favorites=favorites,
        average_view_duration=average_view_duration,
        average_percentage_viewed=average_percentage_viewed,
        completion_rate=completion_rate,
        subscribers_gained=subscribers_gained,
    )

    clean_platform = (platform or "").strip().lower()
    if not clean_platform:
        raise ValueError("platform must be specified")

    now_utc = datetime.now(timezone.utc)
    c_dt = _parse_iso_dt(collected_at) if collected_at else now_utc
    collected_iso = c_dt.isoformat()

    with get_connection(db_path) as conn:
        # Enriquecer com metadados de publication_events se publicado_at não foi passado
        p_iso = None
        if published_at:
            p_iso = _parse_iso_dt(published_at).isoformat()
        else:
            try:
                pub_row = conn.execute(
                    """
                    SELECT id, published_at, external_id
                    FROM publication_events
                    WHERE task_id = ? AND platform = ? AND status = 'success'
                    ORDER BY id DESC LIMIT 1;
                    """,
                    (task_id, clean_platform),
                ).fetchone()
                if pub_row:
                    p_iso = pub_row["published_at"]
                    if not external_id and pub_row["external_id"]:
                        external_id = pub_row["external_id"]
                    if not publication_event_id:
                        publication_event_id = pub_row["id"]
            except Exception:
                pass


        if not p_iso:
            p_iso = collected_iso  # fallback se não houver histórico de publicação

        # Enriquecer com dados de monetization_safety caso não informados
        if not (topic and preset and narrative_structure and duration_seconds):
            try:
                safety_row = conn.execute(
                    """
                    SELECT topic, preset, narrative_structure, actual_duration, estimated_duration
                    FROM monetization_safety WHERE task_id = ? LIMIT 1;
                    """,
                    (task_id,),
                ).fetchone()
                if safety_row:
                    if not topic:
                        topic = safety_row["topic"]
                    if not preset:
                        preset = safety_row["preset"]
                    if not narrative_structure:
                        narrative_structure = safety_row["narrative_structure"]
                    if duration_seconds is None:
                        duration_seconds = safety_row["actual_duration"] or safety_row["estimated_duration"]
            except Exception:
                pass

        # Calcular bucket, engagement_rate e retention_score
        age_bucket = calculate_age_bucket(p_iso, collected_iso)
        engagement_rate = calculate_engagement_rate(
            views=views, likes=likes, comments=comments, shares=shares
        )
        retention_score = calculate_retention_score(
            completion_rate=completion_rate,
            average_percentage_viewed=average_percentage_viewed,
        )

        # Buscar histórico da mesma plataforma para normalização por percentis
        # Prioriza mesmo age_bucket se houver amostras suficientes (>= 3)
        bucket_history_rows = conn.execute(
            """
            SELECT views, engagement_rate, retention_score
            FROM content_analytics
            WHERE platform = ? AND age_bucket = ?;
            """,
            (clean_platform, age_bucket),
        ).fetchall()

        if len(bucket_history_rows) >= 3:
            history_samples = [dict(r) for r in bucket_history_rows]
        else:
            platform_history_rows = conn.execute(
                """
                SELECT views, engagement_rate, retention_score
                FROM content_analytics
                WHERE platform = ?;
                """,
                (clean_platform,),
            ).fetchall()
            history_samples = [dict(r) for r in platform_history_rows]

        performance_score = calculate_performance_score(
            views=views,
            engagement_rate=engagement_rate,
            retention_score=retention_score,
            history_items=history_samples,
        )

        meta_str = json.dumps(metadata_json) if metadata_json else None

        cursor = conn.execute(
            """
            INSERT INTO content_analytics (
                task_id, platform, external_id, publication_event_id, trend_id,
                topic, preset, narrative_structure, duration_seconds,
                views, likes, comments, shares, favorites,
                average_view_duration, average_percentage_viewed,
                completion_rate, subscribers_gained,
                published_at, collected_at, age_bucket,
                engagement_rate, retention_score, performance_score, metadata_json
            ) VALUES (
                ?, ?, ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?
            );
            """,
            (
                task_id, clean_platform, external_id, publication_event_id, trend_id,
                topic, preset, narrative_structure, duration_seconds,
                views, likes, comments, shares, favorites,
                average_view_duration, average_percentage_viewed,
                completion_rate, subscribers_gained,
                p_iso, collected_iso, age_bucket,
                engagement_rate, retention_score, performance_score, meta_str,
            ),
        )
        record_id = cursor.lastrowid

    return {
        "id": record_id,
        "task_id": task_id,
        "platform": clean_platform,
        "external_id": external_id,
        "publication_event_id": publication_event_id,
        "trend_id": trend_id,
        "topic": topic,
        "preset": preset,
        "narrative_structure": narrative_structure,
        "duration_seconds": duration_seconds,
        "views": views,
        "likes": likes,
        "comments": comments,
        "shares": shares,
        "favorites": favorites,
        "average_view_duration": average_view_duration,
        "average_percentage_viewed": average_percentage_viewed,
        "completion_rate": completion_rate,
        "subscribers_gained": subscribers_gained,
        "published_at": p_iso,
        "collected_at": collected_iso,
        "age_bucket": age_bucket,
        "engagement_rate": engagement_rate,
        "retention_score": retention_score,
        "performance_score": performance_score,
    }


def get_snapshots(
    task_id: Optional[str] = None,
    platform: Optional[str] = None,
    latest_only: bool = False,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Recupera snapshots gravados com opção de filtrar pelo mais recente por (task_id, platform)."""
    init_analytics_db(db_path)
    with get_connection(db_path) as conn:
        if latest_only:
            query = """
                SELECT ca.*
                FROM content_analytics ca
                INNER JOIN (
                    SELECT task_id, platform, MAX(collected_at) as max_collected
                    FROM content_analytics
                    GROUP BY task_id, platform
                ) latest ON ca.task_id = latest.task_id
                        AND ca.platform = latest.platform
                        AND ca.collected_at = latest.max_collected
            """
            params = []
            conditions = []
            if task_id:
                conditions.append("ca.task_id = ?")
                params.append(task_id)
            if platform:
                conditions.append("ca.platform = ?")
                params.append(platform.lower().strip())
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY ca.performance_score DESC, ca.collected_at DESC;"
            rows = conn.execute(query, tuple(params)).fetchall()
        else:
            query = "SELECT * FROM content_analytics"
            params = []
            conditions = []
            if task_id:
                conditions.append("task_id = ?")
                params.append(task_id)
            if platform:
                conditions.append("platform = ?")
                params.append(platform.lower().strip())
            if conditions:
                query += " WHERE " + " AND ".join(conditions)
            query += " ORDER BY collected_at DESC;"
            rows = conn.execute(query, tuple(params)).fetchall()

        return [dict(r) for r in rows]


def get_content_performance_feedback(
    platform: Optional[str] = None,
    lookback_days: Optional[int] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Gera insights consolidados de desempenho a partir dos snapshots mais recentes.

    Retorna agregados por narrative_structure, preset, topic, trend source e duração ótima.
    """
    init_analytics_db(db_path)
    clean_plat = platform.lower().strip() if platform else None

    with get_connection(db_path) as conn:
        # Considerar os snapshots mais recentes de cada (task_id, platform)
        base_query = """
            SELECT ca.*
            FROM content_analytics ca
            INNER JOIN (
                SELECT task_id, platform, MAX(collected_at) as max_collected
                FROM content_analytics
                GROUP BY task_id, platform
            ) latest ON ca.task_id = latest.task_id
                    AND ca.platform = latest.platform
                    AND ca.collected_at = latest.max_collected
        """
        conditions = []
        params = []
        if clean_plat:
            conditions.append("ca.platform = ?")
            params.append(clean_plat)
        if lookback_days and lookback_days > 0:
            conditions.append(
                "julianday('now') - julianday(ca.published_at) <= ?"
            )
            params.append(lookback_days)

        if conditions:
            base_query += " WHERE " + " AND ".join(conditions)

        rows = [dict(r) for r in conn.execute(base_query, tuple(params)).fetchall()]

    if not rows:
        return {
            "total_measured": 0,
            "avg_performance_score": 0.0,
            "avg_engagement_rate": 0.0,
            "structures": {},
            "presets": {},
            "topics": [],
            "trend_sources": {},
            "optimal_duration": None,
            "platform_breakdown": {},
        }

    total_measured = len(rows)
    all_scores = [r["performance_score"] for r in rows]
    all_engagements = [r["engagement_rate"] for r in rows]
    global_avg_perf = sum(all_scores) / total_measured if total_measured else 0.0
    global_avg_eng = sum(all_engagements) / total_measured if total_measured else 0.0

    # 1. Agregação por narrative_structure
    structures_map: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        st = r.get("narrative_structure") or "unspecified"
        structures_map.setdefault(st, []).append(r)

    structures_feedback: Dict[str, Dict[str, Any]] = {}
    for st, items in structures_map.items():
        cnt = len(items)
        avg_perf = sum(it["performance_score"] for it in items) / cnt
        avg_eng = sum(it["engagement_rate"] for it in items) / cnt
        avg_vw = sum(it["views"] for it in items) / cnt
        rel_diff = round(((avg_perf - global_avg_perf) / global_avg_perf * 100.0), 1) if global_avg_perf > 0 else 0.0
        structures_feedback[st] = {
            "count": cnt,
            "avg_performance": round(avg_perf, 1),
            "avg_engagement": round(avg_eng, 4),
            "avg_views": round(avg_vw, 1),
            "relative_diff": rel_diff,
        }

    # 2. Agregação por preset
    presets_map: Dict[str, List[Dict[str, Any]]] = {}
    for r in rows:
        pr = r.get("preset") or "unspecified"
        presets_map.setdefault(pr, []).append(r)

    presets_feedback: Dict[str, Dict[str, Any]] = {}
    for pr, items in presets_map.items():
        cnt = len(items)
        avg_perf = sum(it["performance_score"] for it in items) / cnt
        avg_eng = sum(it["engagement_rate"] for it in items) / cnt
        avg_vw = sum(it["views"] for it in items) / cnt
        rel_diff = round(((avg_perf - global_avg_perf) / global_avg_perf * 100.0), 1) if global_avg_perf > 0 else 0.0
        presets_feedback[pr] = {
            "count": cnt,
            "avg_performance": round(avg_perf, 1),
            "avg_engagement": round(avg_eng, 4),
            "avg_views": round(avg_vw, 1),
            "relative_diff": rel_diff,
        }

    # 3. Top tópicos
    topics_list = []
    for r in sorted(rows, key=lambda x: x["performance_score"], reverse=True)[:10]:
        topics_list.append({
            "topic": r.get("topic") or "Sem título",
            "task_id": r.get("task_id"),
            "platform": r.get("platform"),
            "performance_score": r.get("performance_score"),
            "views": r.get("views"),
            "engagement_rate": r.get("engagement_rate"),
        })

    # 4. Agregação por fonte do Trend Radar
    trend_sources_feedback = get_trend_source_performance(db_path=db_path)

    # 5. Duração ótima: média de duração dos 25% melhores vídeos (ou performance >= 65)
    top_performers = [r for r in rows if r["performance_score"] >= max(60.0, global_avg_perf)]
    if not top_performers:
        top_performers = sorted(rows, key=lambda x: x["performance_score"], reverse=True)[:max(1, len(rows) // 2)]
    durations = [r["duration_seconds"] for r in top_performers if r.get("duration_seconds") and r["duration_seconds"] > 0]
    optimal_dur = round(sum(durations) / len(durations), 1) if durations else None

    # 6. Plataformas
    plat_breakdown: Dict[str, Dict[str, Any]] = {}
    for r in rows:
        p = r.get("platform", "other")
        pb = plat_breakdown.setdefault(p, {"count": 0, "total_views": 0, "scores": [], "engagements": []})
        pb["count"] += 1
        pb["total_views"] += r.get("views", 0)
        pb["scores"].append(r.get("performance_score", 0))
        pb["engagements"].append(r.get("engagement_rate", 0))

    for p, data in plat_breakdown.items():
        cnt = data["count"]
        data["avg_performance"] = round(sum(data["scores"]) / cnt, 1) if cnt else 0.0
        data["avg_engagement"] = round(sum(data["engagements"]) / cnt, 4) if cnt else 0.0
        del data["scores"]
        del data["engagements"]

    return {
        "total_measured": total_measured,
        "avg_performance_score": round(global_avg_perf, 1),
        "avg_engagement_rate": round(global_avg_eng, 4),
        "structures": structures_feedback,
        "presets": presets_feedback,
        "topics": topics_list,
        "trend_sources": trend_sources_feedback,
        "optimal_duration": optimal_dur,
        "platform_breakdown": plat_breakdown,
    }


def get_trend_source_performance(db_path: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """Calcula a performance média dos conteúdos associados a fontes do Trend Radar."""
    init_analytics_db(db_path)
    with get_connection(db_path) as conn:
        # Verifica se tabela trend_items existe
        check = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='trend_items';"
        ).fetchone()
        if not check:
            return {}

        query = """
            SELECT
                ti.source AS trend_source,
                COUNT(ca.id) AS count,
                AVG(ca.performance_score) AS avg_performance,
                AVG(ca.views) AS avg_views,
                AVG(ca.engagement_rate) AS avg_engagement
            FROM content_analytics ca
            INNER JOIN trend_items ti ON ca.trend_id = ti.trend_id
            GROUP BY ti.source;
        """
        rows = conn.execute(query).fetchall()
        result = {}
        for r in rows:
            src = r["trend_source"] or "unknown"
            result[src] = {
                "count": r["count"],
                "avg_performance": round(r["avg_performance"] or 0.0, 1),
                "avg_views": round(r["avg_views"] or 0.0, 1),
                "avg_engagement": round(r["avg_engagement"] or 0.0, 4),
            }
        return result


# ==============================================================================
# Interfaces e Stubs para Coleta Automática Futura (Sem OAuth / APIs pagas na V5)
# ==============================================================================


class BaseAnalyticsProvider:
    """Interface base para providers de métricas analíticas."""
    platform: str = "base"

    def fetch_metrics(self, external_id: str) -> Optional[Dict[str, Any]]:
        raise NotImplementedError


class YouTubeAnalyticsProvider(BaseAnalyticsProvider):
    """Provider stub para YouTube Analytics API futura."""
    platform: str = "youtube"

    def fetch_metrics(self, external_id: str) -> Optional[Dict[str, Any]]:
        # Stub: retorna None sem chamadas externas na V5
        return None


class TikTokAnalyticsProvider(BaseAnalyticsProvider):
    """Provider stub para TikTok Display/Analytics API futura."""
    platform: str = "tiktok"

    def fetch_metrics(self, external_id: str) -> Optional[Dict[str, Any]]:
        # Stub: retorna None sem chamadas externas na V5
        return None
