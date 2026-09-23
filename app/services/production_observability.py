"""
Serviço de Observabilidade de Produção (Fase V15-A).

Fornece diagnósticos passivos, consolidados e estritamente de leitura (read-only)
sobre a operação da fábrica de vídeos, cobrindo os perfis 'default' e 'profile-historias-misterio'.

PRINCÍPIOS:
- Estritamente passivo e somente leitura (read-only)
- Zero escrita no SQLite
- Zero mutação de MemoryState
- Zero disparo de worker ou execução de ciclos
- Zero chamadas a provedores ou APIs externas de rede
- Zero alteração de configurações, thresholds ou Growth Mode
- Tolerante a falhas (unavailable por seção sem derrubar o snapshot)
- Diferenciação estrita entre 0, "unknown" e "unavailable"
- Sanitização de credenciais e segredos
"""

from __future__ import annotations

import sys
if "--json" in sys.argv:
    from loguru import logger
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

import argparse
import json
import os
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from loguru import logger

from app.models import const
from app.services import (
    analytics,
    analytics_scheduler,
    autonomous_production,
    copyright_gate,
    operator_console,
    profile_manager,
    scheduler,
)

PROFILE_DEFAULT = "default"
PROFILE_MYSTERY = "profile-historias-misterio"
OBSERVABILITY_PROFILES = (PROFILE_DEFAULT, PROFILE_MYSTERY)


def _get_ro_connection(db_path: Optional[str] = None):
    """Retorna uma conexão SQLite estritamente em modo de leitura (mode=ro)."""
    target = scheduler.get_db_path(db_path)
    abs_path = os.path.abspath(target)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Database file not found: {abs_path}")
    conn = sqlite3.connect(f"file:{abs_path}?mode=ro", uri=True, timeout=5.0)
    conn.row_factory = sqlite3.Row
    return conn


def _get_profile_observability(
    profile_id: str,
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Coleta o diagnóstico completo de um perfil de forma estritamente read-only."""
    clean_p = str(profile_id or "").strip()
    is_default = (clean_p == PROFILE_DEFAULT) or (not clean_p)

    # 1. Profile Info
    profile_info: Dict[str, Any] = {
        "status": "available",
        "profile_id": clean_p,
        "name": "Canal Principal (Padrão)" if is_default else clean_p,
        "niche": "unknown",
        "growth_mode": "unknown",
        "channel_id": "unknown",
    }
    try:
        prof = profile_manager.get_profile(clean_p, db_path=db_path)
        if prof:
            profile_info["name"] = prof.get("name") or profile_info["name"]
            profile_info["niche"] = prof.get("niche") or "unknown"
            profile_info["growth_mode"] = prof.get("growth_mode") or "unknown"

        gm = autonomous_production.get_profile_growth_mode(clean_p, db_path=db_path)
        if gm:
            profile_info["growth_mode"] = gm

        chan = autonomous_production.resolve_autonomous_youtube_channel(clean_p, db_path=db_path)
        if chan:
            profile_info["channel_id"] = chan
    except Exception as exc:
        profile_info["status"] = "unavailable"
        profile_info["reason"] = str(exc)

    channel_id = profile_info.get("channel_id")
    resolved_channel = channel_id if channel_id != "unknown" else None

    # 2. Autonomous Production Telemetry
    autonomous_data: Dict[str, Any] = {
        "status": "available",
        "enabled": False,
        "state": "unknown",
        "current_task_id": None,
        "waiting_task_id": None,
        "last_tick": None,
        "last_result": None,
        "message": None,
        "last_error": None,
    }
    try:
        auto_status = autonomous_production.get_autonomous_status(
            db_path=db_path,
            profile_id=clean_p,
            channel_id=resolved_channel,
        )
        autonomous_data["enabled"] = bool(auto_status.get("autonomous_mode_enabled", False))
        autonomous_data["state"] = auto_status.get("state") or "unknown"
        autonomous_data["current_task_id"] = auto_status.get("current_task_id")
        autonomous_data["waiting_task_id"] = auto_status.get("waiting_task_id")
        autonomous_data["last_tick"] = auto_status.get("last_tick")
        autonomous_data["last_result"] = auto_status.get("last_result")
        autonomous_data["message"] = auto_status.get("message")
        autonomous_data["last_error"] = auto_status.get("last_error")
    except Exception as exc:
        autonomous_data["status"] = "unavailable"
        autonomous_data["reason"] = str(exc)

    # 3. Ready Stock
    ready_stock_data: Dict[str, Any] = {
        "status": "available",
        "count": 0,
        "target": 3,
        "is_below_target": False,
        "task_ids": [],
    }
    try:
        stock_info = autonomous_production.get_autonomous_ready_stock(
            task_base_dir=task_base_dir,
            db_path=db_path,
            profile_id=clean_p,
            channel_id=resolved_channel,
        )
        ready_stock_data["count"] = int(stock_info.get("ready_count", 0))
        ready_stock_data["target"] = int(stock_info.get("target_stock", 3))
        ready_stock_data["is_below_target"] = bool(stock_info.get("is_below_target", False))
        ready_list = stock_info.get("youtube_ready", [])
        ready_stock_data["task_ids"] = [
            str(t.get("task_id")) for t in ready_list if t.get("task_id")
        ]
    except Exception as exc:
        ready_stock_data["status"] = "unavailable"
        ready_stock_data["reason"] = str(exc)

    # 4. Scheduler Queue Status
    scheduler_data: Dict[str, Any] = {
        "status": "available",
        "scheduled": 0,
        "published": 0,
        "failed": 0,
        "retry_waiting": 0,
        "next_slot": None,
    }
    try:
        with _get_ro_connection(db_path) as conn:
            if is_default:
                prof_clause = "(profile_id = 'default' OR profile_id IS NULL OR profile_id = '')"
                params: tuple = ()
            else:
                prof_clause = "profile_id = ?"
                params = (clean_p,)

            counts_row = conn.execute(
                f"""
                SELECT
                    SUM(CASE WHEN status IN ('planned', 'ready') THEN 1 ELSE 0 END) AS scheduled_cnt,
                    SUM(CASE WHEN status = 'published' THEN 1 ELSE 0 END) AS published_cnt,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_cnt,
                    SUM(CASE WHEN attempts > 0 AND status IN ('planned', 'ready', 'failed') THEN 1 ELSE 0 END) AS retry_cnt
                FROM scheduled_posts
                WHERE platform = 'youtube' AND {prof_clause};
                """,
                params,
            ).fetchone()

            if counts_row:
                scheduler_data["scheduled"] = int(counts_row["scheduled_cnt"] or 0)
                scheduler_data["published"] = int(counts_row["published_cnt"] or 0)
                scheduler_data["failed"] = int(counts_row["failed_cnt"] or 0)
                scheduler_data["retry_waiting"] = int(counts_row["retry_cnt"] or 0)

            next_row = conn.execute(
                f"""
                SELECT id, task_id, scheduled_at, status, attempts
                FROM scheduled_posts
                WHERE platform = 'youtube' AND status IN ('planned', 'ready') AND {prof_clause}
                ORDER BY scheduled_at ASC
                LIMIT 1;
                """,
                params,
            ).fetchone()

            if next_row:
                scheduler_data["next_slot"] = {
                    "id": next_row["id"],
                    "task_id": next_row["task_id"],
                    "scheduled_at": next_row["scheduled_at"],
                    "status": next_row["status"],
                    "attempts": int(next_row["attempts"] or 0),
                }
    except Exception as exc:
        scheduler_data["status"] = "unavailable"
        scheduler_data["reason"] = str(exc)

    # 5. 24h Production Metrics & Rejections
    production_24h_data: Dict[str, Any] = {
        "status": "available",
        "attempts": 0,
        "approvals": 0,
        "rejects": 0,
        "rejection_reasons": [],
    }
    try:
        attempts = autonomous_production.count_generation_attempts_in_last_24h(
            db_path=db_path, profile_id=clean_p
        )
        approvals = autonomous_production.count_generations_in_last_24h(
            db_path=db_path, profile_id=clean_p
        )
        production_24h_data["attempts"] = int(attempts)
        production_24h_data["approvals"] = int(approvals)
        production_24h_data["rejects"] = max(0, int(attempts) - int(approvals))

        now_utc = scheduler._normalize_utc(None)
        since_iso = scheduler._to_iso(now_utc - timedelta(hours=24))
        with _get_ro_connection(db_path) as conn:
            if is_default:
                prof_filter = "(tp.profile_id = 'default' OR tp.profile_id IS NULL OR tp.profile_id = '')"
                q_params: tuple = (since_iso,)
            else:
                prof_filter = "tp.profile_id = ?"
                q_params = (since_iso, clean_p)

            has_op = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operational_events';"
            ).fetchone()
            if has_op:
                rows = conn.execute(
                    f"""
                    SELECT o.message, o.metadata_json
                    FROM operational_events o
                    LEFT JOIN task_profiles tp ON tp.task_id = o.task_id
                    WHERE o.component = 'autonomous_production'
                      AND o.event_type = 'task_gate_rejected'
                      AND o.timestamp >= ?
                      AND {prof_filter}
                    ORDER BY o.id DESC LIMIT 10;
                    """,
                    q_params,
                ).fetchall()
                reasons = []
                for r in rows:
                    if r["message"]:
                        reasons.append(str(r["message"]))
                production_24h_data["rejection_reasons"] = reasons
    except Exception as exc:
        production_24h_data["status"] = "unavailable"
        production_24h_data["reason"] = str(exc)

    # 6. Publications & Copyright
    publications_data: Dict[str, Any] = {
        "status": "available",
        "recent_publications": [],
    }
    copyright_data: Dict[str, Any] = {
        "status": "available",
        "effective_status": "unknown",
        "source": None,
        "feedback_loop_eligible": False,
        "has_blocked_or_claimed": False,
    }
    try:
        with _get_ro_connection(db_path) as conn:
            if is_default:
                p_clause = "(p.profile_id = 'default' OR p.profile_id IS NULL OR p.profile_id = '')"
                p_params: tuple = ()
            else:
                p_clause = "p.profile_id = ?"
                p_params = (clean_p,)

            has_pubs = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='publication_events';"
            ).fetchone()

            recent = []
            has_blocked = False
            if has_pubs:
                rows = conn.execute(
                    f"""
                    SELECT p.id, p.task_id, p.platform, p.status, p.published_at, p.external_id, p.privacy_status
                    FROM publication_events p
                    WHERE p.platform = 'youtube' AND {p_clause}
                    ORDER BY p.id DESC LIMIT 5;
                    """,
                    p_params,
                ).fetchall()

                for r in rows:
                    pub_id = r["id"]
                    t_id = r["task_id"]
                    ext_id = r["external_id"]
                    c_info = copyright_gate.get_publication_copyright_status(
                        publication_event_id=pub_id,
                        task_id=t_id,
                        external_id=ext_id,
                        db_path=db_path,
                    )
                    c_stat = c_info.get("copyright_status", "unknown")
                    c_src = c_info.get("source")
                    is_eligible = (c_stat == "clean_manual")
                    if c_stat in ("claimed", "blocked", "strike"):
                        has_blocked = True

                    recent.append({
                        "publication_event_id": pub_id,
                        "task_id": t_id,
                        "status": r["status"],
                        "external_id": ext_id,
                        "privacy_status": r["privacy_status"],
                        "published_at": r["published_at"],
                        "copyright_status": c_stat,
                        "copyright_source": c_src,
                        "feedback_loop_eligible": is_eligible,
                    })

            publications_data["recent_publications"] = recent

            if recent:
                first_pub = recent[0]
                copyright_data["effective_status"] = first_pub["copyright_status"]
                copyright_data["source"] = first_pub["copyright_source"]
                copyright_data["feedback_loop_eligible"] = first_pub["feedback_loop_eligible"]
            else:
                copyright_data["effective_status"] = "unknown"
                copyright_data["source"] = None
                copyright_data["feedback_loop_eligible"] = False

            copyright_data["has_blocked_or_claimed"] = has_blocked
    except Exception as exc:
        publications_data["status"] = "unavailable"
        publications_data["reason"] = str(exc)
        copyright_data["status"] = "unavailable"
        copyright_data["reason"] = str(exc)

    # 7. Analytics Snapshots
    analytics_data: Dict[str, Any] = {
        "status": "available",
        "latest_snapshot": None,
        "last_error": None,
    }
    try:
        with _get_ro_connection(db_path) as conn:
            has_analytics = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='content_analytics';"
            ).fetchone()
            if not has_analytics:
                analytics_data["status"] = "no_snapshots"
            else:
                if is_default:
                    a_clause = "(profile_id = 'default' OR profile_id IS NULL OR profile_id = '')"
                    a_params: tuple = ()
                else:
                    a_clause = "profile_id = ?"
                    a_params = (clean_p,)

                row = conn.execute(
                    f"""
                    SELECT id, task_id, external_id, views, likes, comments, shares,
                           published_at, collected_at, age_bucket, source, metadata_json
                    FROM content_analytics
                    WHERE platform = 'youtube' AND {a_clause}
                    ORDER BY collected_at DESC, id DESC LIMIT 1;
                    """,
                    a_params,
                ).fetchone()

                if row:
                    prov = row["source"] or "youtube_api"
                    try:
                        m = json.loads(row["metadata_json"] or "{}")
                        if m.get("provider"):
                            prov = m["provider"]
                    except Exception:
                        pass

                    analytics_data["latest_snapshot"] = {
                        "snapshot_id": row["id"],
                        "task_id": row["task_id"],
                        "external_id": row["external_id"],
                        "collected_at": row["collected_at"],
                        "published_at": row["published_at"],
                        "age_bucket": row["age_bucket"],
                        "provider": prov,
                        "metrics": {
                            "views": int(row["views"] or 0),
                            "likes": int(row["likes"] or 0),
                            "comments": int(row["comments"] or 0),
                            "shares": int(row["shares"] or 0),
                        },
                    }
                else:
                    analytics_data["status"] = "no_snapshots"
    except Exception as exc:
        analytics_data["status"] = "unavailable"
        analytics_data["reason"] = str(exc)

    # 8. Closed Feedback Loop
    closed_loop_data: Dict[str, Any] = {
        "status": "available",
        "mode": "baseline",
        "enabled": False,
        "isolation_key": f"youtube:{clean_p}:{resolved_channel or 'unknown'}",
        "sample_count": 0,
        "evidence_state": "INSUFFICIENT_DATA",
        "fallback_reason": None,
        "latest_decision": None,
    }
    try:
        cl_enabled = operator_console.get_closed_feedback_loop_enabled_op(db_path=db_path)
        closed_loop_data["enabled"] = bool(cl_enabled)
        closed_loop_data["mode"] = "adaptive" if cl_enabled else "baseline"

        if resolved_channel:
            evidence = analytics.get_learning_evidence(
                platform="youtube",
                profile_id=clean_p,
                channel_id=resolved_channel,
                db_path=db_path,
            )
            closed_loop_data["sample_count"] = int(evidence.get("sample_count", 0))
            closed_loop_data["evidence_state"] = evidence.get("evidence_state", "INSUFFICIENT_DATA")
            closed_loop_data["fallback_reason"] = evidence.get("fallback_reason")
            closed_loop_data["recommended_topic_cluster"] = evidence.get("recommended_topic_cluster")
            closed_loop_data["recommended_narrative_structure"] = evidence.get("recommended_narrative_structure")

        with _get_ro_connection(db_path) as conn:
            has_op = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='operational_events';"
            ).fetchone()
            if has_op:
                d_rows = conn.execute(
                    """
                    SELECT id, timestamp, metadata_json
                    FROM operational_events
                    WHERE event_type = 'CLOSED_LOOP_DECISION'
                    ORDER BY id DESC LIMIT 20;
                    """
                ).fetchall()
                for dr in d_rows:
                    try:
                        d_meta = json.loads(dr["metadata_json"] or "{}")
                        meta_prof = d_meta.get("profile_id")
                        if (is_default and meta_prof in (None, "", "default")) or (meta_prof == clean_p):
                            closed_loop_data["latest_decision"] = {
                                "decision_id": dr["id"],
                                "timestamp": dr["timestamp"],
                                "adapted": bool(d_meta.get("adapted", False)),
                                "topic_cluster": d_meta.get("topic_cluster"),
                                "narrative_structure": d_meta.get("narrative_structure"),
                            }
                            break
                    except Exception:
                        continue
    except Exception as exc:
        closed_loop_data["status"] = "unavailable"
        closed_loop_data["reason"] = str(exc)

    # 9. Cost Guard (Profile-scoped)
    cost_guard_profile: Dict[str, Any] = {
        "status": "available",
        "attempts_24h": production_24h_data.get("attempts", 0),
        "approvals_24h": production_24h_data.get("approvals", 0),
        "max_attempts_24h": autonomous_production.get_max_attempts_24h(profile_id=clean_p, db_path=db_path),
        "max_approvals_24h": autonomous_production.get_max_generations_24h(profile_id=clean_p, db_path=db_path),
    }

    return {
        "profile": profile_info,
        "autonomous": autonomous_data,
        "ready_stock": ready_stock_data,
        "scheduler": scheduler_data,
        "production_24h": production_24h_data,
        "publications": publications_data,
        "copyright": copyright_data,
        "analytics": analytics_data,
        "closed_feedback_loop": closed_loop_data,
        "cost_guard": cost_guard_profile,
    }


def get_production_observability_snapshot(
    db_path: Optional[str] = None,
    task_base_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Gera um snapshot consolidado, passivo e determinístico da observabilidade de produção."""
    now_iso = datetime.now(timezone.utc).isoformat()

    # Prepara profiles
    profiles_result: Dict[str, Any] = {}
    for p_id in OBSERVABILITY_PROFILES:
        try:
            profiles_result[p_id] = _get_profile_observability(
                profile_id=p_id,
                db_path=db_path,
                task_base_dir=task_base_dir,
            )
        except Exception as exc:
            profiles_result[p_id] = {
                "status": "unavailable",
                "reason": str(exc),
            }

    # Global: Worker
    worker_data: Dict[str, Any] = {
        "status": "available",
        "is_primary": False,
        "local_role": "unknown",
        "factory_state": "unknown",
        "scheduler_enabled": False,
        "auto_publish_enabled": False,
        "multi_profile_worker": "active",
    }
    try:
        inst_info = operator_console.get_instance_info(db_path=db_path)
        sched_settings = scheduler.get_all_settings(db_path=db_path)
        worker_data["is_primary"] = bool(inst_info.get("is_primary", False))
        worker_data["local_role"] = inst_info.get("local_role") or "unknown"
        worker_data["factory_state"] = operator_console.get_factory_state(db_path=db_path)
        worker_data["scheduler_enabled"] = bool(sched_settings.get("scheduler_enabled", False))
        worker_data["auto_publish_enabled"] = bool(sched_settings.get("auto_publish_enabled", False))
    except Exception as exc:
        worker_data["status"] = "unavailable"
        worker_data["reason"] = str(exc)

    # Global: Cost Guard
    cost_guard_global: Dict[str, Any] = {
        "status": "available",
        "global_approved_24h": 0,
        "global_max_generations_24h": 10,
        "global_attempts_24h": 0,
        "global_max_attempts_24h": 25,
    }
    try:
        cost_guard_global["global_approved_24h"] = int(
            autonomous_production.count_all_profiles_generations_24h(db_path=db_path)
        )
        cost_guard_global["global_max_generations_24h"] = int(
            autonomous_production.get_global_max_generations_24h(db_path=db_path)
        )
        cost_guard_global["global_attempts_24h"] = int(
            autonomous_production.count_all_profiles_attempts_24h(db_path=db_path)
        )
        cost_guard_global["global_max_attempts_24h"] = int(
            autonomous_production.get_global_max_attempts_24h(db_path=db_path)
        )
    except Exception as exc:
        cost_guard_global["status"] = "unavailable"
        cost_guard_global["reason"] = str(exc)

    # Global: Analytics Scheduler
    analytics_sched_data: Dict[str, Any] = {
        "status": "available",
        "auto_collection_enabled": False,
        "snapshots_today": 0,
        "last_cycle_at": None,
        "last_cycle_status": "idle",
        "provider_backoffs": {},
    }
    try:
        sched_st = analytics_scheduler.get_analytics_scheduler_status(db_path=db_path)
        analytics_sched_data.update(sched_st)
    except Exception as exc:
        analytics_sched_data["status"] = "unavailable"
        analytics_sched_data["reason"] = str(exc)

    # Factual Observable Warnings
    warnings: List[str] = []

    for p_id, p_data in profiles_result.items():
        if not isinstance(p_data, dict):
            continue
        auto = p_data.get("autonomous", {})
        stock = p_data.get("ready_stock", {})
        if auto.get("enabled") and stock.get("count") == 0:
            warnings.append(f"READY_STOCK_EMPTY:{p_id}")

        c_info = p_data.get("copyright", {})
        if c_info.get("has_blocked_or_claimed"):
            warnings.append(f"COPYRIGHT_BLOCKED:{p_id}")

        sched = p_data.get("scheduler", {})
        if sched.get("failed", 0) > 0:
            warnings.append(f"SCHEDULER_FAILURES_PRESENT:{p_id}")

        cl = p_data.get("closed_feedback_loop", {})
        if cl.get("enabled") and cl.get("mode") == "adaptive":
            if cl.get("sample_count", 0) < 12 or cl.get("fallback_reason"):
                warnings.append(f"CLOSED_LOOP_BASELINE:{p_id}")

        pubs = p_data.get("publications", {}).get("recent_publications", [])
        an = p_data.get("analytics", {}).get("latest_snapshot")
        now_dt = datetime.now(timezone.utc)
        if pubs and not an:
            warnings.append(f"ANALYTICS_STALE:{p_id}")
        elif pubs and an and an.get("collected_at"):
            try:
                coll_dt = datetime.fromisoformat(str(an["collected_at"]).replace("Z", "+00:00"))
                if (now_dt - coll_dt).total_seconds() > 24 * 3600:
                    warnings.append(f"ANALYTICS_STALE:{p_id}")
            except Exception:
                pass

    if cost_guard_global.get("status") == "available":
        att = cost_guard_global.get("global_attempts_24h", 0)
        max_att = cost_guard_global.get("global_max_attempts_24h", 25)
        appr = cost_guard_global.get("global_approved_24h", 0)
        max_appr = cost_guard_global.get("global_max_generations_24h", 10)
        if (att >= 0.8 * max_att) or (appr >= 0.8 * max_appr):
            warnings.append("GLOBAL_COST_GUARD_NEAR_LIMIT")

    return {
        "generated_at": now_iso,
        "profiles": profiles_result,
        "global": {
            "worker": worker_data,
            "cost_guard": cost_guard_global,
            "analytics_scheduler": analytics_sched_data,
            "warnings": warnings,
        },
    }


def main():
    parser = argparse.ArgumentParser(
        description="Production Observability Baseline (V15-A) — Read-Only Diagnostic"
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Emit strictly valid JSON to stdout",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Optional custom SQLite database path",
    )
    args = parser.parse_args()

    # Redireciona logs para stderr para nunca corromper JSON em stdout
    logger.remove()
    logger.add(sys.stderr, level="WARNING")

    snapshot = get_production_observability_snapshot(db_path=args.db_path)

    if args.json:
        sys.stdout.write(json.dumps(snapshot, indent=2, ensure_ascii=False) + "\n")
        sys.stdout.flush()
    else:
        sys.stdout.write(f"=== PRODUCTION OBSERVABILITY BASELINE (V15-A) ===\n")
        sys.stdout.write(f"Generated at: {snapshot.get('generated_at')}\n")
        sys.stdout.write(f"Profiles: {list(snapshot.get('profiles', {}).keys())}\n")
        sys.stdout.write(f"Global Warnings: {snapshot.get('global', {}).get('warnings', [])}\n")
        sys.stdout.flush()


if __name__ == "__main__":
    main()
