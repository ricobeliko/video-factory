"""Script operacional para auditoria e limpeza de metadados residuais de retry (V16.4.2C).

Uso:
  python scripts/cleanup_retry_metadata.py --dry-run
  python scripts/cleanup_retry_metadata.py --execute --confirm CLEANUP_RETRY_METADATA
"""

import argparse
import json
from pathlib import Path
import sys

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import retry_policy  # noqa: E402


def main():
    parser = argparse.ArgumentParser(description="Auditoria e cleanup de metadados residuais de retry (V16.4.2C)")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        default=False,
        help="Executa apenas auditoria sem aplicar mutações no banco",
    )
    parser.add_argument(
        "--execute",
        action="store_true",
        default=False,
        help="Aplica as mutações de limpeza no banco de dados",
    )
    parser.add_argument(
        "--confirm",
        type=str,
        default="",
        help="Confirmação textual obrigatória: CLEANUP_RETRY_METADATA",
    )
    parser.add_argument(
        "--db-path",
        type=str,
        default=None,
        help="Caminho opcional do arquivo SQLite",
    )

    args = parser.parse_args()

    if args.execute:
        if args.confirm != "CLEANUP_RETRY_METADATA":
            print("ERRO: Para executar mutações é obrigatório passar: --confirm CLEANUP_RETRY_METADATA", file=sys.stderr)
            sys.exit(1)
        res = retry_policy.cleanup_residual_retries(db_path=args.db_path, dry_run=False)
        print("CLEANUP_EXECUTED:")
        print(json.dumps(res, indent=2))
    else:
        res = retry_policy.cleanup_residual_retries(db_path=args.db_path, dry_run=True)
        print("CLEANUP_DRY_RUN:")
        print(json.dumps(res, indent=2))


if __name__ == "__main__":
    main()
