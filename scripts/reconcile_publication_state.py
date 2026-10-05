#!/usr/bin/env python
"""CLI para Reconciliação Determinística de Publicações (Fase V16.4.2A).

Uso:
  python scripts/reconcile_publication_state.py --dry-run
  python scripts/reconcile_publication_state.py --execute --confirm RECONCILE_PUBLICATION_STATE
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import publication_reconciliation  # noqa: E402


def format_reconciliation_report(result: Dict[str, Any]) -> str:
    lines = []
    lines.append("=" * 80)
    mode = result.get("mode", "UNKNOWN")
    lines.append(f"RECONCILIAÇÃO DETERMINÍSTICA DE PUBLICAÇÕES (FASE V16.4.2A) [{mode}]")
    lines.append("=" * 80)

    pre = result.get("preconditions", {})
    lines.append("PRÉ-CONDIÇÕES OPERACIONAIS:")
    lines.append(f"  scheduler_enabled    : {pre.get('scheduler_enabled')}")
    lines.append(f"  auto_publish_enabled: {pre.get('auto_publish_enabled')}")
    lines.append(f"  active_primary      : {pre.get('active_primary')}")
    lines.append(f"  passed              : {pre.get('passed')}")

    if not pre.get("passed") and pre.get("errors"):
        lines.append("  ERROS / BLOQUEIOS:")
        for err in pre["errors"]:
            lines.append(f"    - {err}")

    lines.append("-" * 80)
    lines.append("SUMÁRIO DA RECONCILIAÇÃO:")
    lines.append(f"  failed -> published         : {result.get('reconciled_failed_to_published', 0)}")
    lines.append(f"  processing -> published     : {result.get('reconciled_processing_to_published', 0)}")
    lines.append(f"  pending -> published        : {result.get('reconciled_pending_to_published', 0)}")
    lines.append(f"  cancelled -> published      : {result.get('reconciled_cancelled_to_published', 0)}")
    lines.append(f"  retries desarmados          : {result.get('retries_disarmed', 0)}")
    lines.append(f"  duplicatas neutralizadas    : {result.get('duplicates_neutralized', 0)}")
    lines.append(f"  sucessos órfãos auditados   : {result.get('orphan_success_audited', 0)}")

    if mode == "DRY_RUN":
        lines.append(f"  mutações planejadas         : {result.get('actions_planned_count', 0)}")
        lines.append("  banco mutado                : NÃO (Simulação Segura)")
    else:
        lines.append(f"  mutações aplicadas          : {result.get('mutations_applied', 0)}")
        lines.append(f"  backup realizado            : {result.get('backup', {}).get('path')}")
        lines.append(f"  backup SHA-256              : {result.get('backup', {}).get('sha256')}")
        lines.append(f"  backup integridade          : {result.get('backup', {}).get('integrity')}")

        post = result.get("post_audit", {})
        lines.append("-" * 80)
        lines.append("PÓS-AUDITORIA DE PRODUÇÃO:")
        lines.append(f"  EXECUTABLE_PENDING_PUBLICATIONS     : {post.get('executable_pending_publications')}")
        lines.append(f"  ARMED_RETRIES                       : {post.get('armed_retries')}")
        lines.append(f"  STALE_PROCESSING                    : {post.get('stale_processing')}")
        lines.append(f"  PUBLISHED_POSTS_COUNT               : {post.get('published_posts_count')}")
        lines.append(f"  REMAINING_MUTATIONS_NEEDED          : {post.get('remaining_mutations_needed')}")

    lines.append("=" * 80)
    return "\n".join(lines)


def main():
    parser = argparse.ArgumentParser(
        description="Reconciliação Determinística de Publicações (Fase V16.4.2A)"
    )
    parser.add_argument("--db-path", help="Caminho alternativo para o banco SQLite")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=True,
        help="Execução em modo simulação (padrão)",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        help="Executa a reconciliação real no banco",
    )
    parser.add_argument(
        "--confirm",
        help="Token de confirmação obrigatório para execução real ('RECONCILE_PUBLICATION_STATE')",
    )
    parser.add_argument(
        "--force-preconditions",
        action="store_true",
        help="Ignora verificação de scheduler ativo (apenas para testes)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        help="Exibe saída estruturada em JSON",
    )

    args = parser.parse_args()

    is_dry_run = not args.execute

    try:
        result = publication_reconciliation.reconcile_publication_state(
            db_path=args.db_path,
            dry_run=is_dry_run,
            confirm=args.confirm,
            force_preconditions=args.force_preconditions,
        )

        if args.json:
            print(json.dumps(result, indent=2, ensure_ascii=False))
        else:
            print(format_reconciliation_report(result))

        sys.exit(0)

    except publication_reconciliation.ReconciliationPreconditionError as exc:
        print(f"[ERRO DE PRÉ-CONDIÇÃO] {exc}", file=sys.stderr)
        sys.exit(2)
    except ValueError as exc:
        print(f"[ERRO DE VALIDAÇÃO] {exc}", file=sys.stderr)
        sys.exit(3)
    except Exception as exc:
        print(f"[ERRO FATAL] {exc}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
