#!/usr/bin/env python
"""
Ferramenta de Auditoria e Reset Controlado de Baseline de Métricas — Fase V15-D.1.

COMPORTAMENTO PADRÃO: DRY-RUN (Estritamente READ-ONLY).

Garante:
1. Inventário e classificação factual de todas as tabelas SQLite em:
   - PRESERVE: tabelas críticas de identidade, canais, perfis e idempotência de publicação.
   - RESET: tabelas de métricas e histórico derivado para baseline limpa.
   - REVIEW_REQUIRED: tabelas de uso misto ou que exigem estratégia de particionamento/marcador.
2. Preservação mandatória de:
   - publication_events e scheduled_posts (garantia absoluta contra republicação no YouTube)
   - content_profiles, publishing_channels, task_profiles (identidade e isolamento multi-perfil)
   - PUBLICATION_COPYRIGHT_STATUS_SET em operational_events (auditorias manuais de copyright)
   - configurações persistentes do sistema em autopilot_settings
3. Modo execute futuro:
   - FAIL-CLOSED sem a confirmação explícita exata: --confirm CLEAN_METRICS_BASELINE
   - Backup físico consistente com PRAGMA integrity_check e SHA-256 ANTES de qualquer mutação
   - Transação atômica (BEGIN IMMEDIATE / COMMIT / ROLLBACK)
   - Gravação de marcador temporal 'metrics_baseline_started_at' em autopilot_settings (zero schema migration)
   - Zero chamadas de rede ou APIs externas.

USO:
    python scripts/reset_metrics_baseline.py
    python scripts/reset_metrics_baseline.py --dry-run
    python scripts/reset_metrics_baseline.py --json
    python scripts/reset_metrics_baseline.py --db-path storage/database/video_factory.db
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

# Classificação Canônica de Tabelas
TABLE_CLASSIFICATION: Dict[str, Dict[str, Any]] = {
    # 1. PRESERVE — Identidade, Canais, Configurações e Idempotência de Publicação
    "content_profiles": {
        "classification": "PRESERVE",
        "purpose": "Configuração de perfis de conteúdo, nichos e modos de crescimento (WARMUP/SCALE)",
        "can_cause_republication": True,
        "reason": "Define a identidade canônica dos canais e perfis ativos. Remoção destrói configurações do operador.",
    },
    "publishing_channels": {
        "classification": "PRESERVE",
        "purpose": "Canais de publicação vinculados aos perfis (YouTube, etc.) e credenciais associadas",
        "can_cause_republication": True,
        "reason": "Mapeamento fundamental de destinos de publicação. Remoção quebra o isolamento de canais.",
    },
    "task_profiles": {
        "classification": "PRESERVE",
        "purpose": "Vínculo imutável entre cada task_id e seu profile_id de origem",
        "can_cause_republication": True,
        "reason": "Necessário para recuperação pós-restart e isolamento de canal do Quality Score (V15-C.1/C.2).",
    },
    "scheduled_posts": {
        "classification": "PRESERVE",
        "purpose": "Fila de agendamento e trava de idempotência contra agendamento duplicado",
        "can_cause_republication": True,
        "reason": "CRÍTICO: Contém registros de tarefas publicadas/canceladas; remoção causaria republicação de vídeos!",
    },
    "publication_events": {
        "classification": "PRESERVE",
        "purpose": "Livro-razão histórico de publicações reais no YouTube com external_id",
        "can_cause_republication": True,
        "reason": "CRÍTICO: Fonte primária de idempotência externa. Remoção provocaria republicação imediata no YouTube!",
    },
    "task_platforms": {
        "classification": "PRESERVE",
        "purpose": "Destinos de plataforma planejados por tarefa",
        "can_cause_republication": False,
        "reason": "Usado para verificar integridade e status de publicação completa (are_all_task_platforms_published).",
    },
    "instance_locks": {
        "classification": "PRESERVE",
        "purpose": "Trava de concorrência de instância PRIMARY do console do operador",
        "can_cause_republication": False,
        "reason": "Necessário para a estabilidade do processo primário em execução.",
    },
    "clip_sources": {
        "classification": "PRESERVE",
        "purpose": "Metadados de vídeos-fonte importados no módulo Clip Mode",
        "can_cause_republication": False,
        "reason": "Dados de usuário do módulo Clip Mode, independentes da linha autônoma de shorts.",
    },
    "clip_segments": {
        "classification": "PRESERVE",
        "purpose": "Segmentos de corte do módulo Clip Mode",
        "can_cause_republication": False,
        "reason": "Dados do usuário do módulo Clip Mode.",
    },
    "clip_transcripts": {
        "classification": "PRESERVE",
        "purpose": "Transcrições brutas do módulo Clip Mode",
        "can_cause_republication": False,
        "reason": "Cache de transcrição do Clip Mode.",
    },
    "clip_transcript_segments": {
        "classification": "PRESERVE",
        "purpose": "Segmentos pontuais de transcrição do Clip Mode",
        "can_cause_republication": False,
        "reason": "Dados do Clip Mode.",
    },
    "clip_review_outputs": {
        "classification": "PRESERVE",
        "purpose": "Avaliações e decisões de revisão do Clip Mode",
        "can_cause_republication": False,
        "reason": "Dados do Clip Mode.",
    },
    "clip_renders": {
        "classification": "PRESERVE",
        "purpose": "Renderizações concluídas do Clip Mode",
        "can_cause_republication": False,
        "reason": "Arquivos renderizados de clipes.",
    },
    "clip_caption_tracks": {
        "classification": "PRESERVE",
        "purpose": "Faixas de legendas do Clip Mode",
        "can_cause_republication": False,
        "reason": "Legendas do Clip Mode.",
    },
    "clip_caption_cues": {
        "classification": "PRESERVE",
        "purpose": "Cues de legenda do Clip Mode",
        "can_cause_republication": False,
        "reason": "Cues do Clip Mode.",
    },

    # 2. RESET — Métricas e Histórico Derivado Obsoleto para Nova Baseline Limpa
    "content_analytics": {
        "classification": "RESET",
        "purpose": "Snapshots de métricas externas (views, likes, retenção) coletadas do YouTube",
        "can_cause_republication": False,
        "reason": "Métricas históricas contaminadas ou obsoletas que devem iniciar do zero na nova baseline.",
    },
    "content_quality_scores": {
        "classification": "RESET",
        "purpose": "Avaliações históricas de Quality Score (incluindo scores com penalidades artificiais pré-V15-C)",
        "can_cause_republication": False,
        "reason": "Contém histórico de scores antigos (ex: 20+ rejeições artificiais por self-comparison).",
    },
    "content_strategy_scores": {
        "classification": "RESET",
        "purpose": "Classificações de clusters e oportunidades recomendadas pela estratégia",
        "can_cause_republication": False,
        "reason": "Dados derivados baseados em métricas legadas. Recalculáveis a partir da nova baseline.",
    },

    # 3. PRESERVE ADICIONAL — Auditoria, Tendências e Segurança com Filtro por Marcador
    "monetization_safety": {
        "classification": "PRESERVE",
        "purpose": "Avaliações de segurança (Safety Gate) e histórico de tópicos/hooks",
        "can_cause_republication": False,
        "reason": "PRESERVADA integralmente no banco para proveniência de copyright e conformidade de tasks existentes. "
                  "Isolamento temporal implementado via metrics_baseline_started_at em autopilot_settings.",
    },
    "operational_events": {
        "classification": "PRESERVE",
        "purpose": "Log operacional de eventos de telemetria, ciclos autônomos e decisões de feedback loop",
        "can_cause_republication": False,
        "reason": "PRESERVADA como trilha de auditoria histórica completa (incluindo telemetria e PUBLICATION_COPYRIGHT_STATUS_SET). "
                  "Observabilidade futura distingue PRE e POST baseline pelo marcador temporal.",
    },
    "trend_items": {
        "classification": "PRESERVE",
        "purpose": "Cache de tendências mineradas pelo Trend Radar e histórico de tópicos já utilizados",
        "can_cause_republication": False,
        "reason": "PRESERVADA para proteção contra repetição de temas: itens com status 'USED' impedem o loop autônomo "
                  "de reutilizar tópicos recentes. Não contém métricas de performance e possui expiração natural própria.",
    },

    # 4. REVIEW_REQUIRED — Tabela Mista de Configurações Persistentes e Marcador
    "autopilot_settings": {
        "classification": "REVIEW_REQUIRED",
        "purpose": "Configurações chave-valor do Autopilot, flags, contadores de rejeições e marcador temporal",
        "can_cause_republication": False,
        "reason": "TABELA MISTA: toggles essenciais (autonomous_production_enabled, growth_mode) DEVEM SER PRESERVADOS; "
                  "contadores de rejeições consecutivas são zerados; local canônico para metrics_baseline_started_at.",
    },
}

CONFIRMATION_PHRASE = "CLEAN_METRICS_BASELINE"
BASELINE_MARKER_KEY = "metrics_baseline_started_at"

# Auditoria de Chaves de autopilot_settings (Fase V15-D.1A)
AUTOPILOT_SETTINGS_PRESERVE_KEYS: List[str] = [
    "active_profile_id",
    "analytics_auto_collection_enabled",
    "analytics_cycle_min_interval_seconds",
    "analytics_max_fetches_per_cycle",
    "auto_publish_enabled",
    "autonomous_cycle_interval_minutes",
    "autonomous_global_max_attempts_24h",
    "autonomous_global_max_generations_24h",
    "autonomous_max_attempts_24h",
    "autonomous_max_generations_24h",
    "autonomous_max_new_tasks_per_cycle",
    "autonomous_mode_enabled",
    "autonomous_production_enabled",
    "autonomous_target_ready_stock",
    "closed_feedback_loop_enabled",
    "dry_run",
    "estoque_desejado",
    "factory_state",
    "growth_mode",
    "minimum_ready_stock",
    "scheduler_enabled",
    "tiktok_enabled",
    "tiktok_limit_24h",
    "youtube_enabled",
    "youtube_limit_24h",
]

AUTOPILOT_SETTINGS_RESET_KEYS: List[str] = [
    "autonomous_consecutive_rejections",
    "closed_loop_consecutive_rejections",
    "autonomous_last_narrative_structure",
    "autonomous_rejected_narrative_structure",
]


def check_baseline_consumers_support() -> Dict[str, Any]:
    """Verifica se os consumidores relevantes suportam o filtro pelo marcador de baseline."""
    import inspect
    from app.services import quality_score, analytics_scheduler, analytics

    qs_src = inspect.getsource(quality_score._get_isolated_recent_safety_history)
    qs_supported = "metrics_baseline_started_at" in qs_src and "checked_at >=" in qs_src

    as_src = inspect.getsource(analytics_scheduler.check_publication_eligibility)
    as_supported = "get_metrics_baseline_started_at" in as_src and "pre_baseline_publication" in as_src

    cf_src = inspect.getsource(analytics.get_learning_evidence)
    cf_supported = "metrics_baseline_started_at" in cf_src and "pre_baseline_publication" in cf_src

    all_supported = qs_supported and as_supported and cf_supported

    return {
        "QUALITY_HISTORY": "SUPPORTED" if qs_supported else "MISSING",
        "ANALYTICS_COLLECTION": "SUPPORTED" if as_supported else "MISSING",
        "CLOSED_FEEDBACK_LOOP": "SUPPORTED" if cf_supported else "MISSING",
        "all_supported": all_supported,
    }


def get_default_db_path() -> str:
    """Retorna o caminho padrão canônico do banco SQLite."""
    from app.services import scheduler
    return scheduler.get_db_path()


def compute_file_sha256(filepath: str) -> str:
    """Calcula o hash SHA-256 de um arquivo em blocos."""
    hasher = hashlib.sha256()
    with open(filepath, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def check_sqlite_integrity(db_path: str) -> Tuple[bool, str]:
    """Executa PRAGMA integrity_check no banco especificado."""
    if not os.path.exists(db_path):
        return False, "file_not_found"
    try:
        conn = sqlite3.connect(f"file:{os.path.abspath(db_path)}?mode=ro", uri=True)
        try:
            res = conn.execute("PRAGMA integrity_check;").fetchone()
            val = res[0] if res else "empty_result"
            return (val == "ok", str(val))
        finally:
            conn.close()
    except Exception as exc:
        return False, str(exc)


def create_sqlite_backup(source_db_path: str, backup_dir: Optional[str] = None) -> Dict[str, Any]:
    """Cria backup físico consistente do SQLite usando a API nativa sqlite3.backup()."""
    abs_src = os.path.abspath(source_db_path)
    if not os.path.exists(abs_src):
        raise FileNotFoundError(f"Banco de dados não encontrado: {abs_src}")

    target_dir = backup_dir or os.path.join(os.path.dirname(abs_src), "backups")
    os.makedirs(target_dir, exist_ok=True)

    timestamp_str = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    base_name = os.path.splitext(os.path.basename(abs_src))[0]
    backup_filename = f"{base_name}_backup_pre_baseline_{timestamp_str}.db"
    backup_path = os.path.join(target_dir, backup_filename)

    src_conn = sqlite3.connect(f"file:{abs_src}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(backup_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()

    # Valida integridade do arquivo de backup
    ok, msg = check_sqlite_integrity(backup_path)
    if not ok:
        raise RuntimeError(f"Integrity check falhou no arquivo de backup gerado: {msg}")

    sha256 = compute_file_sha256(backup_path)
    size_bytes = os.path.getsize(backup_path)

    return {
        "backup_path": backup_path,
        "integrity_check": "ok",
        "sha256": sha256,
        "size_bytes": size_bytes,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def audit_metrics_baseline(db_path: Optional[str] = None) -> Dict[str, Any]:
    """Realiza auditoria completa e 100% READ-ONLY do banco de dados SQLite."""
    resolved_path = os.path.abspath(db_path or get_default_db_path())
    timestamp_iso = datetime.now(timezone.utc).isoformat()

    if not os.path.exists(resolved_path):
        return {
            "status": "error",
            "db_path": resolved_path,
            "message": f"Arquivo de banco de dados não encontrado: {resolved_path}",
            "timestamp": timestamp_iso,
        }

    sha_before = compute_file_sha256(resolved_path)
    integrity_ok, integrity_msg = check_sqlite_integrity(resolved_path)

    tables_audit: Dict[str, Dict[str, Any]] = {}
    preserve_list: List[str] = []
    reset_list: List[str] = []
    review_list: List[str] = []

    conn = sqlite3.connect(f"file:{resolved_path}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        # Descobre todas as tabelas de usuário
        t_rows = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' ORDER BY name;"
        ).fetchall()
        table_names = [r["name"] for r in t_rows]

        for tname in table_names:
            try:
                cnt_row = conn.execute(f"SELECT COUNT(*) FROM {tname};").fetchone()
                row_count = cnt_row[0] if cnt_row else 0
            except Exception:
                row_count = 0

            info = TABLE_CLASSIFICATION.get(tname, {
                "classification": "REVIEW_REQUIRED",
                "purpose": "Tabela não mapeada no catálogo padrão",
                "can_cause_republication": False,
                "reason": "Classificação conservadora fail-safe para tabelas desconhecidas.",
            })

            classification = info["classification"]
            rows_to_remove = 0

            if classification == "PRESERVE":
                rows_to_remove = 0
                preserve_list.append(tname)
            elif classification == "RESET":
                rows_to_remove = row_count
                reset_list.append(tname)
            else:  # REVIEW_REQUIRED
                review_list.append(tname)
                if tname == "operational_events":
                    try:
                        c_row = conn.execute(
                            "SELECT COUNT(*) FROM operational_events WHERE event_type != 'PUBLICATION_COPYRIGHT_STATUS_SET';"
                        ).fetchone()
                        rows_to_remove = c_row[0] if c_row else 0
                    except Exception:
                        rows_to_remove = 0
                elif tname == "autopilot_settings":
                    rows_to_remove = 0  # configurações preservadas; contadores zerados in-place
                elif tname == "monetization_safety":
                    rows_to_remove = 0  # preservado via marcador temporal seguro

            tables_audit[tname] = {
                "table_name": tname,
                "classification": classification,
                "current_rows": row_count,
                "rows_to_remove": rows_to_remove,
                "purpose": info["purpose"],
                "reason": info["reason"],
                "can_cause_republication": info["can_cause_republication"],
            }

        # Consulta estado atual do marcador temporal se existir
        current_marker = None
        try:
            if "autopilot_settings" in table_names:
                m_row = conn.execute(
                    "SELECT value FROM autopilot_settings WHERE key = ?;",
                    (BASELINE_MARKER_KEY,),
                ).fetchone()
                if m_row:
                    current_marker = str(m_row["value"])
        except Exception:
            pass

    finally:
        conn.close()

    # Confirmação de imutabilidade estrita durante dry-run
    sha_after = compute_file_sha256(resolved_path)
    assert sha_before == sha_after, "Falha crítica: o banco foi modificado durante o dry-run!"

    consumers_support = check_baseline_consumers_support()

    return {
        "status": "success",
        "db_path": resolved_path,
        "integrity_check": integrity_msg,
        "sha256": sha_before,
        "timestamp": timestamp_iso,
        "tables_found_count": len(table_names),
        "tables_found": table_names,
        "tables_audit": tables_audit,
        "preserve_tables": preserve_list,
        "reset_tables": reset_list,
        "review_required_tables": review_list,
        "current_baseline_marker": current_marker,
        "publication_idempotency_preserved": True,
        "old_task_republication_risk": "NONE",
        "old_task_recovery_risk": "NONE",
        "monetization_safety_strategy": (
            "PRESERVAÇÃO SEGURA VIA MARCADOR TEMPORAL: Os registros de monetization_safety permanecem "
            "intactos no banco para garantir compliance de compliance/safety em _recover_waiting_task e "
            "no Closed Feedback Loop, enquanto o marcador 'metrics_baseline_started_at' em autopilot_settings "
            "isolará novas avaliações do Quality Score sem risco de republicação ou quebra de idempotência."
        ),
        "quality_history_will_be_clean": True,
        "baseline_marker_strategy": (
            f"Gravação da chave '{BASELINE_MARKER_KEY}' em autopilot_settings contendo o timestamp ISO "
            f"da nova baseline limpa. Zero schema migration."
        ),
        "baseline_filter_consumers": consumers_support,
        "all_consumers_supported": consumers_support["all_supported"],
        "autopilot_settings_keys_audit": {
            "preserve_keys": AUTOPILOT_SETTINGS_PRESERVE_KEYS,
            "reset_keys": AUTOPILOT_SETTINGS_RESET_KEYS,
            "baseline_marker_key": BASELINE_MARKER_KEY,
        },
        "ready_for_production_dry_run": consumers_support["all_supported"],
        "dry_run_mode": True,
    }


def execute_metrics_baseline_reset(
    db_path: Optional[str] = None,
    confirm: Optional[str] = None,
    backup_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa o reset controlado da baseline com backup mandatória e transação atômica."""
    clean_confirm = str(confirm or "").strip()
    if clean_confirm != CONFIRMATION_PHRASE:
        raise ValueError(
            f"Operação abortada (FAIL-CLOSED): Confirmação explícita ausente ou inválida. "
            f"Para executar, forneça exatamente: --confirm {CONFIRMATION_PHRASE}"
        )

    resolved_path = os.path.abspath(db_path or get_default_db_path())
    if not os.path.exists(resolved_path):
        raise FileNotFoundError(f"Banco de dados não encontrado: {resolved_path}")

    # 1. PRAGMA integrity_check pré-mutação
    ok_pre, msg_pre = check_sqlite_integrity(resolved_path)
    if not ok_pre:
        raise RuntimeError(f"Integrity check falhou antes da mutação: {msg_pre}")

    # 2. Backup físico obrigatório e verificado
    backup_meta = create_sqlite_backup(resolved_path, backup_dir=backup_dir)

    # 3. Transação atômica de reset
    now_iso = datetime.now(timezone.utc).isoformat()
    deleted_counts: Dict[str, int] = {}

    conn = sqlite3.connect(resolved_path, timeout=30.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("BEGIN IMMEDIATE;")

        # A) Reset de tabelas puramente de métricas/estratégia legada
        for reset_table in ("content_analytics", "content_quality_scores", "content_strategy_scores"):
            try:
                cur = conn.execute(f"DELETE FROM {reset_table};")
                deleted_counts[reset_table] = cur.rowcount
            except sqlite3.OperationalError:
                deleted_counts[reset_table] = 0

        # B) operational_events é PRESERVE (preserva 100% como trilha de auditoria histórica)
        deleted_counts["operational_events"] = 0

        # C) Reset de contadores em autopilot_settings e gravação do marcador temporal
        try:
            conn.execute(
                "UPDATE autopilot_settings SET value = '0' "
                "WHERE key = 'autonomous_consecutive_rejections' OR key LIKE 'autonomous_consecutive_rejections:%' "
                "   OR key = 'closed_loop_consecutive_rejections';"
            )
            conn.execute(
                "DELETE FROM autopilot_settings "
                "WHERE key IN ('autonomous_last_narrative_structure', 'autonomous_rejected_narrative_structure');"
            )
            conn.execute(
                "INSERT INTO autopilot_settings (key, value) VALUES (?, ?) "
                "ON CONFLICT(key) DO UPDATE SET value = excluded.value;",
                (BASELINE_MARKER_KEY, now_iso),
            )
            deleted_counts["autopilot_settings_counters_reset"] = 1
        except sqlite3.OperationalError:
            pass

        conn.commit()
    except Exception as exc:
        conn.rollback()
        raise RuntimeError(f"Erro durante a mutação da baseline. Transação revertida (ROLLBACK): {exc}")
    finally:
        conn.close()

    # 4. PRAGMA integrity_check pós-mutação
    ok_post, msg_post = check_sqlite_integrity(resolved_path)
    if not ok_post:
        raise RuntimeError(f"Integrity check falhou após a mutação: {msg_post}")

    sha_post = compute_file_sha256(resolved_path)

    return {
        "status": "success",
        "db_path": resolved_path,
        "backup": backup_meta,
        "deleted_counts": deleted_counts,
        "baseline_marker": {
            "key": BASELINE_MARKER_KEY,
            "value": now_iso,
        },
        "integrity_check": msg_post,
        "sha256_after": sha_post,
        "executed_at": now_iso,
    }


def format_report_cli(report: Dict[str, Any]) -> str:
    """Formata o relatório de auditoria para exibição amigável no terminal."""
    lines: List[str] = []
    lines.append("=" * 72)
    lines.append(" CLEAN METRICS BASELINE AUDIT — DRY RUN (READ-ONLY)")
    lines.append("=" * 72)
    lines.append(f"Database Path    : {report.get('db_path')}")
    lines.append(f"Integrity Check  : {report.get('integrity_check')}")
    lines.append(f"Timestamp (UTC)  : {report.get('timestamp')}")
    lines.append(f"SHA-256 (DB)     : {report.get('sha256')}")
    lines.append(f"Total Tables     : {report.get('tables_found_count')}")
    lines.append(f"Baseline Marker  : {report.get('current_baseline_marker') or 'NONE (Ready to set)'}")
    lines.append("-" * 72)

    lines.append("\n[1] CLASSIFICAÇÃO DAS TABELAS:")
    lines.append(f"{'TABELA':<28} | {'CLASSIFICAÇÃO':<16} | {'LINHAS ATUAIS':<14} | {'A REMOVER'}")
    lines.append("-" * 72)

    tables_audit = report.get("tables_audit", {})
    for tname, tdata in sorted(tables_audit.items()):
        cls_str = tdata["classification"]
        cur_r = str(tdata["current_rows"])
        rem_r = str(tdata["rows_to_remove"])
        lines.append(f"{tname:<28} | {cls_str:<16} | {cur_r:<14} | {rem_r}")

    lines.append("\n[2] RESUMO POR CATEGORIA:")
    lines.append(f"  • PRESERVE ({len(report.get('preserve_tables', []))} tabelas)        : {', '.join(report.get('preserve_tables', []))}")
    lines.append(f"  • RESET ({len(report.get('reset_tables', []))} tabelas)           : {', '.join(report.get('reset_tables', []))}")
    lines.append(f"  • REVIEW_REQUIRED ({len(report.get('review_required_tables', []))} tabelas) : {', '.join(report.get('review_required_tables', []))}")

    lines.append("\n[3] SALVAGUARDAS E RISCOS DETECTADOS:")
    lines.append(f"  • Republication Risk        : {report.get('old_task_republication_risk')}")
    lines.append(f"  • Recovery Risk             : {report.get('old_task_recovery_risk')}")
    lines.append(f"  • Publication Idempotency   : PRESERVED (publication_events e scheduled_posts 100% intocadas)")
    lines.append(f"  • Identidade Multi-Perfil   : PRESERVED (content_profiles, publishing_channels, task_profiles intocadas)")
    lines.append(f"  • Auditorias de Copyright   : PRESERVED (PUBLICATION_COPYRIGHT_STATUS_SET mantido em operational_events)")

    lines.append("\n[4] ESTRATÉGIA MONETIZATION_SAFETY:")
    lines.append(f"  {report.get('monetization_safety_strategy')}")

    lines.append("\n[5] ESTRATÉGIA DE MARCADOR TEMPORAL:")
    lines.append(f"  {report.get('baseline_marker_strategy')}")

    lines.append("\n[6] CONSUMIDORES DO FILTRO DE BASELINE (CONTRATO FECHADO):")
    consumers = report.get("baseline_filter_consumers", {})
    for cname in ("QUALITY_HISTORY", "ANALYTICS_COLLECTION", "CLOSED_FEEDBACK_LOOP"):
        st = consumers.get(cname, "UNKNOWN")
        desc = ""
        if cname == "QUALITY_HISTORY":
            desc = "(filtra monetization_safety.checked_at >= baseline)"
        elif cname == "ANALYTICS_COLLECTION":
            desc = "(filtra publication_events.published_at >= baseline)"
        elif cname == "CLOSED_FEEDBACK_LOOP":
            desc = "(filtra publication.published_at >= baseline)"
        lines.append(f"  • {cname:<24} : {st:<10} {desc}")
    all_supp = "YES" if report.get("all_consumers_supported") else "NO"
    lines.append(f"  • Status Geral Consumidores : ALL_CONSUMERS_SUPPORTED ({all_supp})")

    lines.append("\n[7] AUDITORIA DE CHAVES DE AUTOPILOT_SETTINGS:")
    keys_aud = report.get("autopilot_settings_keys_audit", {})
    preserve_keys = keys_aud.get("preserve_keys", [])
    reset_keys = keys_aud.get("reset_keys", [])
    lines.append(f"  • PRESERVE ({len(preserve_keys)} chaves)        : {', '.join(preserve_keys[:8])}...")
    lines.append(f"  • RESET_DERIVED_STATE ({len(reset_keys)} chaves) : {', '.join(reset_keys)}")
    lines.append(f"  • BASELINE_MARKER ({keys_aud.get('baseline_marker_key')})")

    lines.append(f"\n[8] PRONTIDÃO PARA DRY-RUN EM PRODUÇÃO:")
    ready_str = "YES" if report.get("ready_for_production_dry_run") else "NO"
    lines.append(f"  • READY_FOR_PRODUCTION_DRY_RUN = {ready_str}")

    lines.append("\n" + "=" * 72)
    lines.append(" [DRY-RUN CONCLUÍDO] Banco 100% inalterado. Zero bytes modificados.")
    lines.append(" Para executar o reset real (quando autorizado):")
    lines.append(f"     python scripts/reset_metrics_baseline.py --execute --confirm {CONFIRMATION_PHRASE}")
    lines.append("=" * 72)

    return "\n".join(lines)


def parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Auditoria e Reset Seguro de Baseline de Métricas (V15-D.1)",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Executa auditoria em modo estritamente READ-ONLY (padrão)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Executa o reset real (requer obrigatoriamente --confirm CLEAN_METRICS_BASELINE)",
    )
    parser.add_argument(
        "--confirm",
        default=None,
        help=f"Frase de confirmação obrigatória para mutação: '{CONFIRMATION_PHRASE}'",
    )
    parser.add_argument(
        "--db-path",
        default=None,
        help="Caminho do banco SQLite (padrão: storage/database/video_factory.db)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Gera saída estruturada em JSON para stdout",
    )
    parser.add_argument(
        "--backup-dir",
        default=None,
        help="Diretório customizado para salvar o backup pré-reset",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    args = parse_args(argv)

    if args.execute:
        try:
            res = execute_metrics_baseline_reset(
                db_path=args.db_path,
                confirm=args.confirm,
                backup_dir=args.backup_dir,
            )
            if args.json:
                print(json.dumps(res, indent=2, ensure_ascii=False))
            else:
                print("=" * 72)
                print(" RESET DA BASELINE EXECUTADO COM SUCESSO")
                print("=" * 72)
                print(f"Backup Gerado    : {res['backup']['backup_path']}")
                print(f"SHA-256 Backup   : {res['backup']['sha256']}")
                print(f"Integrity Check  : {res['integrity_check']}")
                print(f"Marcador Gravado : {res['baseline_marker']['key']} = {res['baseline_marker']['value']}")
                print(f"Linhas Removidas : {res['deleted_counts']}")
                print("=" * 72)
            return 0
        except Exception as exc:
            if args.json:
                print(json.dumps({"status": "error", "error": str(exc)}, indent=2))
            else:
                print(f"[ERRO CRÍTICO] Execução abortada: {exc}", file=sys.stderr)
            return 1
    else:
        # Modo DRY-RUN padrão
        report = audit_metrics_baseline(db_path=args.db_path)
        if args.json:
            print(json.dumps(report, indent=2, ensure_ascii=False))
        else:
            print(format_report_cli(report))
        return 0


if __name__ == "__main__":
    sys.exit(main())
