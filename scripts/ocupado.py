#!/usr/bin/env python3
"""Verificador de Ociosidade da Fábrica para Manutenção e Cutover (scripts/ocupado.py).

Verifica se a fábrica de vídeos está ociosa ou se existem tarefas ativas
em processamento, renderização ou publicação. Utilizado antes de updates e cutover.

Retorna:
  Exit code 0 se OCIOSA (seguro atualizar/reiniciar).
  Exit code 1 se OCUPADA (aguardar conclusão antes de interrupção).
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.services import operator_console, scheduler


def check_factory_idle() -> tuple[bool, list[str]]:
    """Avalia se a fábrica está totalmente ociosa."""
    busy_reasons: list[str] = []

    # 1. Checa estado consolidado da fábrica
    is_paused = operator_console.is_factory_paused()
    factory_state = operator_console.get_factory_state()

    # 2. Checa estados autônomos em autopilot_settings
    settings = scheduler.get_all_settings()
    for k, v in settings.items():
        if k.startswith("autonomous_state"):
            val_lower = str(v).lower().strip()
            if val_lower not in ("idle", "paused", "stopped", "off", ""):
                busy_reasons.append(f"Automação ativa em {k} = '{v}'")

    # 3. Checa tarefas em processamento no SQLite
    db_path = operator_console.get_db_path()
    if os.path.isfile(db_path):
        try:
            with operator_console.get_connection(db_path) as conn:
                # Verifica tabela de tarefas se existir
                cursor = conn.cursor()
                cursor.execute(
                    "SELECT count(*) FROM sqlite_master WHERE type='table' AND name='tasks';"
                )
                if cursor.fetchone()[0] > 0:
                    cursor.execute(
                        """
                        SELECT task_id, status FROM tasks
                        WHERE status IN ('generating', 'rendering', 'publishing', 'processing', 'in_progress')
                        LIMIT 5;
                        """
                    )
                    active_tasks = cursor.fetchall()
                    if active_tasks:
                        for tid, st in active_tasks:
                            busy_reasons.append(f"Tarefa {tid} em status '{st}'")
        except Exception as exc:
            busy_reasons.append(f"Aviso ao consultar banco: {exc}")

    is_idle = len(busy_reasons) == 0
    return is_idle, busy_reasons


def main() -> int:
    is_idle, reasons = check_factory_idle()
    is_paused = operator_console.is_factory_paused()

    print("==================================================")
    print(" VERIFICAÇÃO DE OCIOSIDADE DA FÁBRICA (CUTOVER)")
    print("==================================================")
    print(f"Status da Fábrica : {operator_console.get_factory_state()}")
    print(f"Pausa Operacional : {'PAUSADA' if is_paused else 'ATIVA (ATENÇÃO: pause antes do update)'}")

    if is_idle:
        print("Diagnóstico       : OCIOSA")
        print("Resultado         : SEGURO prosseguir com atualização / cutover.")
        print("==================================================")
        return 0
    else:
        print("Diagnóstico       : OCUPADA")
        print("Motivos           :")
        for r in reasons:
            print(f"  - {r}")
        print("Resultado         : NÃO interromper o serviço agora. Aguarde a conclusão.")
        print("==================================================")
        return 1


if __name__ == "__main__":
    sys.exit(main())
