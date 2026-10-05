#!/usr/bin/env python
"""Script de Reset Controlado e Seguro de Publicações Pendentes — Fase V16.4.2R / V16.4.2R.1.

COMPORTAMENTO PADRÃO: DRY-RUN (Estritamente READ-ONLY).

USO:
    python scripts/reset_pending_publications.py
    python scripts/reset_pending_publications.py --dry-run
    python scripts/reset_pending_publications.py --json
    python scripts/reset_pending_publications.py --disable-scheduler
    python scripts/reset_pending_publications.py --execute --confirm RESET_PENDING_PUBLICATIONS
    python scripts/reset_pending_publications.py --db-path storage/video_factory.db
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import publication_reset, scheduler  # noqa: E402


def format_inventory_table(inv: dict) -> str:
    lines = []
    lines.append("=" * 80)
    lines.append("INVENTÁRIO ANTES DO RESET (BEFORE INVENTORY)")
    lines.append("=" * 80)

    lines.append("\n[1] CONTAGEM DE SCHEDULED_POSTS POR PLATAFORMA / STATUS / CANAL:")
    lines.append(f"{'PLATFORM':<12} | {'STATUS':<12} | {'PROFILE':<15} | {'CHANNEL':<25} | {'COUNT':<5}")
    lines.append("-" * 78)
    for g in inv.get("grouped_counts", []):
        lines.append(
            f"{g.get('platform', ''):<12} | {g.get('status', ''):<12} | "
            f"{str(g.get('prof', '')):<15} | {str(g.get('chan', '')):<25} | {g.get('cnt', 0):<5}"
        )

    lines.append(f"\n[2] PUBLICAÇÕES A SEREM ANALISADAS / RESETADAS: {inv.get('pending_count', 0)}")
    if inv.get("pending_posts"):
        lines.append(f"{'ID':<4} | {'TASK_ID':<38} | {'PLAT':<8} | {'STATUS':<10} | {'ATT':<4} | {'NEXT_ATTEMPT':<25}")
        lines.append("-" * 95)
        for p in inv.get("pending_posts", []):
            next_att = str(p.get("next_attempt_at") or "None")
            lines.append(
                f"{p.get('id', ''):<4} | {p.get('task_id', ''):<38} | {p.get('platform', ''):<8} | "
                f"{p.get('status', ''):<10} | {p.get('attempts', 0):<4} | {next_att:<25}"
            )

    if inv.get("published_with_armed_retries"):
        lines.append(f"\n  [NORMALIZAÇÃO] Posts 'published' com next_attempt_at armado: {len(inv['published_with_armed_retries'])}")
        lines.append("  (Ação: manter status='published', desarmar retry limpando next_attempt_at)")
        for r in inv["published_with_armed_retries"]:
            lines.append(f"    - Post #{r['scheduled_post_id']} (Task {r['task_id']}, {r['platform']}): next_attempt={r['next_attempt_at']}")

    if inv.get("failed_with_existing_success"):
        lines.append(f"\n  [INCONSISTÊNCIA] Posts 'failed' com evento de sucesso: {len(inv['failed_with_existing_success'])}")
        lines.append("  (Ação: manter status='failed', desarmar retry e preservar para reconciliação na V16.4.2A)")
        for f in inv["failed_with_existing_success"]:
            lines.append(f"    - Post #{f['scheduled_post_id']} (Task {f['task_id']}, {f['platform']}): Event #{f['publication_event_id']} ({f['external_id']})")

    lines.append("\n[3] PUBLICATION_EVENTS:")
    lines.append(f"  Total: {inv.get('total_publication_events', 0)}")
    lines.append(f"  Success: {inv.get('success_publication_events_count', 0)}")
    lines.append(f"  Failed / Other: {inv.get('failed_publication_events_count', 0)}")

    if inv.get("duplicate_successes"):
        lines.append(f"\n  [ALERTA] Múltiplos sucessos para o mesmo task_id + platform: {len(inv['duplicate_successes'])}")
        for d in inv["duplicate_successes"]:
            lines.append(f"    - Task {d['task_id']} ({d['platform']}): {d['cnt']} sucessos registrados")

    if inv.get("pending_with_existing_success"):
        lines.append(f"\n  [DUPLICATAS PENDENTES] Posts pendentes que JÁ POSSUEM publicação com sucesso: {len(inv['pending_with_existing_success'])}")
        for a in inv["pending_with_existing_success"]:
            lines.append(f"    - Post #{a['scheduled_post_id']} (Task {a['task_id']}, {a['platform']}): status='{a['scheduled_post_status']}' mas Event #{a['publication_event_id']} já é SUCCESS ({a['external_id']})")

    if inv.get("success_without_coherent_post"):
        lines.append(f"\n  [ANOMALIA] Sucessos sem scheduled_post coerente (status != 'published'): {len(inv['success_without_coherent_post'])}")
        for s in inv["success_without_coherent_post"]:
            lines.append(f"    - Event #{s['publication_event_id']} (Task {s['task_id']}, {s['platform']}): {s['external_id']}")

    lines.append("\n[4] ARQUIVOS DE MÍDIA / TAREFAS PENDENTES:")
    for m in inv.get("task_media_info", []):
        lines.append(f"  Task {m['task_id']}: {m['media_files_count']} vídeos encontrados em disco ({', '.join(m['media_files']) if m['media_files'] else 'nenhum'})")

    return "\n".join(lines)


def format_reset_report(res: dict) -> str:
    lines = []
    lines.append("\n" + "=" * 80)
    lines.append(f"RELATÓRIO DE RESULTADOS {'(SIMULAÇÃO / DRY-RUN)' if res.get('dry_run') else '(RESET REAL EXECUTADO)'}")
    lines.append("=" * 80)

    pre = res.get("preconditions", {})
    lines.append(f"PRÉ-CONDIÇÕES DE SEGURANÇA: {'PASS' if pre.get('passed') else 'FAIL'}")
    lines.append(f"  scheduler_enabled    : {pre.get('scheduler_enabled')}")
    lines.append(f"  auto_publish_enabled: {pre.get('auto_publish_enabled')}")
    lines.append(f"  active_primary      : {pre.get('active_primary')}")
    if pre.get("errors"):
        for err in pre["errors"]:
            lines.append(f"  [ERRO] {err}")
        if pre.get("active_primary"):
            lines.append("\n  [PROCEDIMENTO PARA LIBERAÇÃO DO NÓ PRIMÁRIO]:")
            lines.append("  1. No host de produção, pare o serviço da aplicação:")
            lines.append("     powershell> schtasks /End /TN MoneyPrinterTurbo")
            lines.append("     (ou encerre o processo do Streamlit/worker em execução).")
            lines.append("  2. O encerramento limpo executa operator_console.release_instance_lock().")
            lines.append("  3. NUNCA delete registros de instance_locks manualmente.")
            lines.append("  4. Repita a verificação do dry-run/reset.")

    lines.append("\nAÇÕES:")
    lines.append(f"  would_cancel_planned          : {res.get('would_cancel_planned', 0)}")
    lines.append(f"  would_cancel_processing       : {res.get('would_cancel_processing', 0)}")
    lines.append(f"  would_disarm_retries          : {res.get('would_disarm_retries', 0)}")
    lines.append(f"  would_clear_next_attempt      : {res.get('would_clear_next_attempt', 0)}")
    lines.append(f"  would_neutralize_duplicates   : {res.get('would_neutralize_duplicates', 0)}")
    lines.append(f"  already_published_preserved   : {res.get('already_published_preserved', 0)}")
    lines.append(f"  normalized_published          : {res.get('normalized_published', 0)}")
    lines.append(f"  failed_with_success_preserved : {res.get('failed_with_success_preserved', 0)}")
    lines.append(f"  media_files_preserved         : {res.get('media_files_preserved')}")

    backup = res.get("backup_info")
    if backup:
        lines.append("\nBACKUP FÍSICO REALIZADO ANTES DA MUTAÇÃO:")
        lines.append(f"  Arquivo   : {backup.get('backup_file')}")
        lines.append(f"  SHA-256   : {backup.get('sha256')}")
        lines.append(f"  Tamanho   : {backup.get('size_bytes')} bytes")
        lines.append(f"  Integrity : {backup.get('integrity')}")

    after = res.get("after_audit", {})
    lines.append("\nAUDITORIA APÓS OPERAÇÃO:")
    lines.append(f"  EXECUTABLE_PENDING_PUBLICATIONS     : {after.get('executable_pending_publications')}")
    lines.append(f"  ARMED_RETRIES                       : {after.get('armed_retries')}")
    lines.append(f"  STALE_PROCESSING                    : {after.get('stale_processing')}")
    lines.append(f"  CANCELLED_POSTS_COUNT               : {after.get('cancelled_posts_count')}")
    lines.append(f"  PUBLISHED_POSTS_COUNT               : {after.get('published_posts_count')}")
    lines.append(f"  PUBLISHED_SUCCESS_RECORDS_PRESERVED : {'YES' if after.get('published_success_records_preserved') else 'NO'}")
    lines.append(f"  MEDIA_FILES_DELETED                 : {after.get('media_files_deleted')}")

    if after.get("remaining_inconsistencies"):
        lines.append("\nINCONSISTÊNCIAS REMANESCENTES (PARA RECONCILIAÇÃO DETERMINÍSTICA NA V16.4.2A):")
        for inc in after["remaining_inconsistencies"]:
            lines.append(f"  - {inc}")
    else:
        lines.append("\nINCONSISTÊNCIAS REMANESCENTES: Nenhuma")

    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(description="Auditoria e Reset de Publicações Pendentes (V16.4.2R / V16.4.2R.1)")
    parser.add_argument("--db-path", default=None, help="Caminho alternativo para o banco SQLite")
    parser.add_argument("--dry-run", action="store_true", default=True, help="Execução em modo simulação (padrão)")
    parser.add_argument("--execute", action="store_true", help="Executa o reset real no banco")
    parser.add_argument("--confirm", default="", help="Token de confirmação obrigatório para execução real")
    parser.add_argument("--disable-scheduler", action="store_true", help="Desativa administrativamente scheduler_enabled e auto_publish_enabled antes do reset")
    parser.add_argument("--force-preconditions", action="store_true", help="Ignora verificação de scheduler ativo (apenas testes)")
    parser.add_argument("--json", action="store_true", help="Exibe saída estruturada em JSON")

    args = parser.parse_args()

    # Se --disable-scheduler for fornecido
    if args.disable_scheduler:
        target_db = scheduler.get_db_path(args.db_path)
        print(f"Desativando scheduler_enabled e auto_publish_enabled em: {target_db}...")
        status = publication_reset.disable_scheduler_preconditions(target_db)
        print(f"Novas pré-condições: {status}")
        if not args.execute:
            return

    is_dry_run = not args.execute

    target_db = scheduler.get_db_path(args.db_path)
    if not os.path.isfile(target_db):
        print(f"ERRO: Banco de dados não encontrado em {target_db}", file=sys.stderr)
        sys.exit(1)

    try:
        res = publication_reset.reset_pending_publications(
            db_path=args.db_path,
            dry_run=is_dry_run,
            confirm_token=args.confirm,
            force_preconditions=args.force_preconditions,
        )

        if args.json:
            print(json.dumps(res, indent=2, default=str))
        else:
            print(format_inventory_table(res.get("before_inventory", {})))
            print(format_reset_report(res))

    except publication_reset.PreconditionError as pe:
        print(f"\n[BLOQUEIO DE SEGURANÇA] {pe}", file=sys.stderr)
        sys.exit(2)
    except Exception as exc:
        print(f"\n[ERRO CRÍTICO] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
