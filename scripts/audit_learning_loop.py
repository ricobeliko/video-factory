#!/usr/bin/env python3
"""Script de Auditoria Somente Leitura do Ciclo Fechado de Aprendizado (Closed Feedback Loop).

Missão B — V2 Auditoria de Aprendizado.
Opera estritamente em modo READ-ONLY sobre cópia temporária do banco SQLite (via sqlite3 backup).
ZERO modificações no banco ao vivo, ZERO chamadas de rede externas e ZERO vazamento de segredos.
"""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))


def _get_ro_connection(db_path: str) -> sqlite3.Connection:
    """Abre conexão SQLite estritamente em modo somente leitura (mode=ro)."""
    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Arquivo de banco de dados não encontrado: {abs_path}")
    uri = Path(abs_path).as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _table_exists(conn: sqlite3.Connection, table_name: str) -> bool:
    """Verifica se uma tabela existe no banco de dados."""
    cur = conn.cursor()
    row = cur.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?;",
        (table_name,),
    ).fetchone()
    return bool(row)


def audit_learning_loop(db_path: str, original_db_path: Optional[str] = None) -> Dict[str, Any]:
    """Executa a auditoria completa de aprendizado e métricas sobre a cópia do banco."""
    report_data: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "db_path": original_db_path or os.path.abspath(db_path),
        "db_exists": os.path.isfile(db_path),
        "global_settings": {},
        "channels": [],
        "analytics_summary": {},
        "closed_loop_events_total": 0,
        "closed_loop_adapted_total": 0,
    }

    if not os.path.isfile(db_path):
        return report_data

    conn = _get_ro_connection(db_path)
    try:
        # 1. Configurações Globais (autopilot_settings e scheduler_settings)
        if _table_exists(conn, "autopilot_settings"):
            cur = conn.execute("SELECT key, value FROM autopilot_settings;")
            for r in cur.fetchall():
                report_data["global_settings"][r["key"]] = r["value"]

        if _table_exists(conn, "scheduler_settings"):
            cur = conn.execute("SELECT key, value FROM scheduler_settings WHERE key LIKE 'analytics_%';")
            for r in cur.fetchall():
                report_data["global_settings"][r["key"]] = r["value"]

        # 2. Resumo de Decisões de Closed Loop em operational_events
        if _table_exists(conn, "operational_events"):
            cur = conn.execute(
                "SELECT COUNT(*) FROM operational_events WHERE event_type LIKE '%CLOSED_LOOP%';"
            )
            report_data["closed_loop_events_total"] = cur.fetchone()[0]

            # Contagem com adapted=True
            cur = conn.execute(
                "SELECT metadata_json FROM operational_events WHERE event_type LIKE '%CLOSED_LOOP%';"
            )
            adapted_count = 0
            for r in cur.fetchall():
                try:
                    meta = json.loads(r["metadata_json"] or "{}")
                    if meta.get("adapted") is True:
                        adapted_count += 1
                except Exception:
                    pass
            report_data["closed_loop_adapted_total"] = adapted_count

        # 3. Perfis e Canais Operacionais
        profiles = []
        if _table_exists(conn, "content_profiles"):
            cur = conn.execute("SELECT id, name, slug, is_active, settings_json FROM content_profiles ORDER BY id;")
            profiles = [dict(r) for r in cur.fetchall()]

        # Mapeamento de canais de publicação
        channels_by_profile: Dict[str, List[Dict[str, Any]]] = {}
        if _table_exists(conn, "publishing_channels"):
            cur = conn.execute(
                "SELECT id, profile_id, platform, display_name, is_enabled, auto_publish_authorized "
                "FROM publishing_channels;"
            )
            for r in cur.fetchall():
                ch_dict = dict(r)
                p_id_key = ch_dict.get("profile_id") or "default"
                channels_by_profile.setdefault(p_id_key, []).append(ch_dict)

        channels_info = []
        for prof in profiles:
            p_id = prof["id"]
            p_name = prof["name"]

            # Formato e configurações do perfil (fonte de verdade de autonomous_production e profile_manager)
            fixed_format = "traditional"
            target_stock = 3
            is_autonomous = False

            resolved_via_service = False
            try:
                from app.services import profile_manager, autonomous_production
                prof_ctx = profile_manager.get_generation_profile_context(profile_id=p_id, db_path=db_path)
                fixed_format = prof_ctx.get("video_format") or prof_ctx.get("content_style") or "traditional"
                is_autonomous = bool(autonomous_production.is_profile_autonomous_mode_enabled(p_id, db_path=db_path))
                target_stock = autonomous_production.get_target_ready_stock(p_id, db_path=db_path)
                resolved_via_service = True
            except Exception:
                pass

            # Fallback direto via banco / settings_json
            if not resolved_via_service or fixed_format in ("traditional", "standard", ""):
                try:
                    p_settings = json.loads(prof.get("settings_json") or "{}")
                    ed = p_settings.get("editorial", {})
                    raw_fmt = str(ed.get("video_format") or p_settings.get("video_format") or "").strip().lower()
                    raw_style = str(ed.get("narrative_structure") or ed.get("content_style") or p_settings.get("content_style") or "").strip().lower()
                    if raw_fmt in ("quiz_dilemma", "quiz", "quiz_escolhas_impossiveis") or raw_style in ("quiz_dilemma", "quiz", "quiz_escolhas_impossiveis"):
                        fixed_format = "quiz_dilemma"
                    elif raw_fmt in ("quiz_paper", "paper") or raw_style in ("quiz_paper", "paper"):
                        fixed_format = "quiz_paper"
                    elif raw_fmt:
                        fixed_format = raw_fmt
                    elif raw_style:
                        fixed_format = raw_style
                except Exception:
                    pass

            if not resolved_via_service and _table_exists(conn, "autopilot_settings"):
                auto_key = "autonomous_mode_enabled" if p_id in ("default", "profile-default", "") else f"autonomous_mode_enabled:{p_id}"
                cur_auto = conn.execute("SELECT value FROM autopilot_settings WHERE key=?;", (auto_key,))
                r_auto = cur_auto.fetchone()
                if not r_auto and p_id not in ("default", "profile-default", ""):
                    cur_auto = conn.execute("SELECT value FROM autopilot_settings WHERE key='autonomous_mode_enabled';")
                    r_auto = cur_auto.fetchone()
                if r_auto:
                    is_autonomous = str(r_auto["value"]).lower() in ("true", "1", "yes")

            # Canais associados
            ch_list = channels_by_profile.get(p_id, [])
            yt_ch = next((c for c in ch_list if c.get("platform") == "youtube"), None)
            yt_channel_id = yt_ch["id"] if yt_ch else None
            auto_publish_auth = bool(yt_ch.get("auto_publish_authorized")) if yt_ch else False

            # Verificação de override autônomo por canal em autopilot_settings
            if yt_channel_id and _table_exists(conn, "autopilot_settings"):
                cur_ch_auto = conn.execute(
                    "SELECT value FROM autopilot_settings WHERE key=?;",
                    (f"autonomous_mode_enabled:{yt_channel_id}",),
                )
                r_ch_auto = cur_ch_auto.fetchone()
                if r_ch_auto:
                    is_autonomous = str(r_ch_auto["value"]).lower() in ("true", "1", "yes")

            # Contagem de linhas em content_analytics por age_bucket para este canal
            age_buckets = {
                "under_6h": 0,
                "6h_to_24h": 0,
                "24h_to_72h": 0,
                "72h_to_96h": 0,  # Janela canônica de evidência do closed loop
                "over_96h": 0,
                "total": 0,
            }
            last_collected_at = None

            if _table_exists(conn, "content_analytics"):
                query = """
                    SELECT ca.published_at, ca.collected_at
                    FROM content_analytics ca
                    WHERE ca.profile_id=?
                """
                params = [p_id]
                if yt_channel_id:
                    query += " AND (ca.channel_id=? OR ca.channel_id IS NULL)"
                    params.append(yt_channel_id)

                cur = conn.execute(query, tuple(params))
                rows = cur.fetchall()
                age_buckets["total"] = len(rows)

                for r in rows:
                    pub_str = r["published_at"]
                    col_str = r["collected_at"]
                    if not last_collected_at or (col_str and col_str > last_collected_at):
                        last_collected_at = col_str

                    if pub_str and col_str:
                        try:
                            dt_pub = datetime.fromisoformat(pub_str.replace("Z", "+00:00"))
                            dt_col = datetime.fromisoformat(col_str.replace("Z", "+00:00"))
                            diff_hours = (dt_col - dt_pub).total_seconds() / 3600.0

                            if diff_hours < 6:
                                age_buckets["under_6h"] += 1
                            elif 6 <= diff_hours < 24:
                                age_buckets["6h_to_24h"] += 1
                            elif 24 <= diff_hours < 72:
                                age_buckets["24h_to_72h"] += 1
                            elif 72 <= diff_hours <= 96:
                                age_buckets["72h_to_96h"] += 1
                            else:
                                age_buckets["over_96h"] += 1
                        except Exception:
                            pass

            # Decisões de closed loop para este perfil específico
            prof_decisions_total = 0
            prof_decisions_adapted = 0
            if _table_exists(conn, "operational_events"):
                cur = conn.execute(
                    "SELECT metadata_json FROM operational_events WHERE event_type LIKE '%CLOSED_LOOP%';"
                )
                for r in cur.fetchall():
                    try:
                        meta = json.loads(r["metadata_json"] or "{}")
                        if meta.get("profile_id") == p_id:
                            prof_decisions_total += 1
                            if meta.get("adapted") is True:
                                prof_decisions_adapted += 1
                    except Exception:
                        pass

            channels_info.append({
                "profile_id": p_id,
                "profile_name": p_name,
                "is_active": bool(prof["is_active"]),
                "format": fixed_format,
                "is_autonomous": is_autonomous,
                "target_stock": target_stock,
                "yt_channel_id": yt_channel_id,
                "auto_publish_authorized": auto_publish_auth,
                "age_buckets": age_buckets,
                "last_collected_at": last_collected_at,
                "decisions_total": prof_decisions_total,
                "decisions_adapted": prof_decisions_adapted,
            })

        report_data["channels"] = channels_info

    finally:
        conn.close()

    # 4. Avaliação canônica de get_learning_evidence (se o serviço estiver importável)
    for ch in report_data["channels"]:
        p_id = ch["profile_id"]
        yt_id = ch["yt_channel_id"]
        if yt_id:
            try:
                from app.services import analytics
                evidence = analytics.get_learning_evidence(
                    platform="youtube",
                    profile_id=p_id,
                    channel_id=yt_id,
                    db_path=db_path,
                )
                ch["evidence_state"] = evidence.get("evidence_state", "UNKNOWN")
                ch["fallback_reason"] = evidence.get("fallback_reason")
                ch["sample_count"] = evidence.get("sample_count", 0)
                ch["eligible_publication_ids_count"] = len(evidence.get("eligible_publication_ids", []))
                ch["excluded_counts_by_reason"] = evidence.get("excluded_counts_by_reason", {})
            except Exception as exc:
                ch["evidence_state"] = f"ERROR: {exc}"
                ch["fallback_reason"] = "exception"
                ch["sample_count"] = 0
                ch["eligible_publication_ids_count"] = 0
                ch["excluded_counts_by_reason"] = {}
        else:
            ch["evidence_state"] = "NO_YOUTUBE_CHANNEL"
            ch["fallback_reason"] = "no_channel"
            ch["sample_count"] = 0
            ch["eligible_publication_ids_count"] = 0
            ch["excluded_counts_by_reason"] = {}

    return report_data


def generate_markdown_report(data: Dict[str, Any]) -> str:
    """Gera relatório legível em Markdown sanitizado (zero segredos)."""
    ts = data.get("timestamp", "")
    db_path = data.get("db_path", "")
    g_set = data.get("global_settings", {})
    cl_enabled = g_set.get("closed_feedback_loop_enabled")
    auto_coll_enabled = g_set.get("auto_collection_enabled")
    last_cycle = g_set.get("analytics_last_cycle_at", "—")
    last_succ = g_set.get("analytics_last_success_at", "—")

    md = []
    md.append("# Relatório de Auditoria: Ciclo Fechado de Aprendizado (Closed Feedback Loop)")
    md.append("")
    md.append(f"- **Data da Auditoria (UTC):** `{ts}`")
    md.append(f"- **Banco Inspecionado:** `{db_path}` *(Auditado via cópia segura snapshot `sqlite3.backup`)*")
    md.append(f"- **Flag Global de Closed Loop (`closed_feedback_loop_enabled`):** `{cl_enabled}`")
    md.append(f"- **Flag Global de Coleta de Métricas (`auto_collection_enabled`):** `{auto_coll_enabled}`")
    md.append(f"- **Último Ciclo de Analytics Executado:** `{last_cycle}`")
    md.append(f"- **Último Sucesso de Coleta de Analytics:** `{last_succ}`")
    md.append(f"- **Total de Decisões de Closed Loop no SQLite:** `{data.get('closed_loop_events_total', 0)}` "
              f"*(Adaptadas: {data.get('closed_loop_adapted_total', 0)})*")
    md.append("")
    md.append("---")
    md.append("")
    md.append("## 1. Diagnóstico Consolidado por Canal / Perfil")
    md.append("")
    md.append("| Perfil / Canal | Formato | Autônomo? | Snapshots (72–96h) | Amostras Elegíveis | Evidence State | Decisões (Adaptadas) | Última Coleta | Veredito |")
    md.append("| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |")

    for ch in data.get("channels", []):
        p_name = ch["profile_name"]
        p_fmt = ch["format"]
        is_auto = "Sim" if ch["is_autonomous"] else "Não"
        b_72_96 = ch["age_buckets"].get("72h_to_96h", 0)
        elig_cnt = ch.get("eligible_publication_ids_count", 0)
        ev_state = ch.get("evidence_state", "UNKNOWN")
        fb_reason = ch.get("fallback_reason")
        if fb_reason and ("FALLBACK" in ev_state or ev_state == "INSUFFICIENT_DATA"):
            ev_state_display = f"{ev_state} ({fb_reason})"
        else:
            ev_state_display = ev_state
        dec_str = f"{ch['decisions_total']} ({ch['decisions_adapted']})"
        last_col = ch.get("last_collected_at") or "Nunca"
        if len(last_col) > 16:
            last_col = last_col[:16].replace("T", " ")

        # Veredito analítico
        if p_fmt in ("quiz_dilemma", "quiz_paper"):
            veredito = "❌ NÃO FUNCIONA (formato procedural sobrescreve estrutura)"
        elif str(cl_enabled).lower() not in ("true", "1"):
            veredito = "⏸️ NÃO FUNCIONA (flag global desativada)"
        elif ev_state == "ELIGIBLE" and ch["decisions_adapted"] > 0:
            veredito = "✅ FUNCIONA"
        elif elig_cnt < 12:
            faltam = 12 - elig_cnt
            veredito = f"⏳ FALTA DADO (faltam {faltam} pubs 72–96h)"
        else:
            veredito = f"⚠️ {ev_state}"

        md.append(f"| **{p_name}** | `{p_fmt}` | {is_auto} | {b_72_96} | {elig_cnt} / 12 | `{ev_state_display}` | {dec_str} | `{last_col}` | {veredito} |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## 2. Detalhamento de Snapshots em `content_analytics` por Janela de Idade")
    md.append("")
    md.append("| Perfil | Canal YouTube | < 6h | 6–24h | 24–72h | **72–96h (Janela Alvo)** | > 96h | **Total Snapshots** |")
    md.append("| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |")

    for ch in data.get("channels", []):
        b = ch["age_buckets"]
        yt = ch["yt_channel_id"] or "—"
        md.append(f"| **{ch['profile_name']}** | `{yt}` | {b['under_6h']} | {b['6h_to_24h']} | {b['24h_to_72h']} | **{b['72h_to_96h']}** | {b['over96h'] if 'over96h' in b else b['over_96h']} | **{b['total']}** |")

    md.append("")
    md.append("---")
    md.append("")
    md.append("## 3. Motivos de Exclusão de Evidências (`excluded_counts_by_reason`)")
    md.append("")
    has_exclusions = False
    for ch in data.get("channels", []):
        ex = ch.get("excluded_counts_by_reason", {})
        if ex:
            has_exclusions = True
            md.append(f"### {ch['profile_name']} (`{ch['profile_id']}`)")
            for reason, count in ex.items():
                md.append(f"- `{reason}`: **{count}** publicações/snapshots descartados")
            md.append("")

    if not has_exclusions:
        md.append("*Nenhum motivo de exclusão registrado ou sem publicações para avaliar.*")
        md.append("")

    md.append("---")
    md.append("*Relatório gerado automaticamente de forma estritamente somente-leitura pelo `scripts/audit_learning_loop.py`.*")
    return "\n".join(md)


def main():
    if hasattr(sys.stdout, "reconfigure"):
        try:
            sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    if hasattr(sys.stderr, "reconfigure"):
        try:
            sys.stderr.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass

    default_output = os.path.join(tempfile.gettempdir(), "AUDIT_LEARNING_LOOP_REPORT.md")

    parser = argparse.ArgumentParser(description="Auditoria Somente Leitura do Ciclo Fechado de Aprendizado")
    parser.add_argument("--db-path", default="storage/video_factory.db", help="Caminho do banco SQLite")
    parser.add_argument("--output", default=default_output, help="Arquivo markdown de saída (padrão: pasta temporária)")
    parser.add_argument("--stdout", action="store_true", help="Imprime o relatório markdown também no console")
    args = parser.parse_args()

    db_file = Path(args.db_path).resolve()
    if not db_file.is_file():
        print(f"[ERRO FATAL] Banco de dados SQLite não encontrado: {db_file}", file=sys.stderr)
        sys.exit(1)

    print(f"[AUDIT] Criando snapshot seguro do banco em arquivo temporário via sqlite3 backup...")
    temp_fd, temp_db_path = tempfile.mkstemp(prefix="audit_learning_loop_", suffix=".db")
    os.close(temp_fd)

    try:
        # Abre o banco de origem em modo estritamente somente-leitura (mode=ro)
        src_uri = db_file.as_uri() + "?mode=ro"
        src_conn = sqlite3.connect(src_uri, uri=True, timeout=10.0)
        dst_conn = sqlite3.connect(temp_db_path)
        src_conn.backup(dst_conn)
        dst_conn.close()
        src_conn.close()

        print(f"[AUDIT] Snapshot do banco copiado com sucesso para: {temp_db_path}")
        print(f"[AUDIT] Executando auditoria sobre a cópia temporária...")
        data = audit_learning_loop(temp_db_path, original_db_path=str(db_file))
        report_md = generate_markdown_report(data)

        out_path = Path(args.output).resolve()
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with open(out_path, "w", encoding="utf-8") as f:
            f.write(report_md)

        print(f"[AUDIT] Relatório gravado com sucesso em: {out_path}")

        if args.stdout:
            print("\n" + report_md)
    finally:
        if os.path.exists(temp_db_path):
            try:
                os.remove(temp_db_path)
            except Exception:
                pass


if __name__ == "__main__":
    main()
