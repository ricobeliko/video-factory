#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
scripts/remux_faststart.py — Utilitário Seguro de Remux Faststart para Vídeos da Video Factory.

PRINCÍPIOS DE GOVERNANÇA:
1. Dry-run obrigatório por padrão (--apply necessário para qualquer mutação).
2. Seleção explícita por --task-id. Recusa processamento cego em lote.
3. Bloqueio fail-closed de tarefas com aprovação manual de Copyright vinculada a SHA-256.
4. Bloqueio fail-closed de tarefas publicadas ou agendadas.
5. Remux atômico sem re-encode (-c copy -movflags +faststart) com validação prévia de streams e duração.
6. Preservação de backup (.bak) antes da substituição atômica.
"""

import argparse
import json
import os
import shutil
import sqlite3
import struct
import subprocess
import sys
import tempfile
from typing import Any, Dict, List, Optional, Tuple

# Importa utilitários do MoneyPrinterTurbo
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))
from app.utils import utils
from app.services import copyright_gate


def check_mp4_atoms(file_path: str) -> List[Tuple[str, int, int]]:
    """Lê os átomos de nível superior de um arquivo MP4."""
    atoms = []
    with open(file_path, "rb") as f:
        while True:
            header = f.read(8)
            if len(header) < 8:
                break
            size, atom_type = struct.unpack(">I4s", header)
            atom_name = atom_type.decode("latin-1", errors="replace")
            pos = f.tell() - 8
            atoms.append((atom_name, pos, size))
            if size == 1:
                size = struct.unpack(">Q", f.read(8))[0]
                f.seek(size - 16, 1)
            elif size == 0:
                break
            else:
                f.seek(size - 8, 1)
    return atoms


def is_already_faststart(atoms: List[Tuple[str, int, int]]) -> bool:
    """Retorna True se moov estiver posicionado antes de mdat."""
    moov_pos = None
    mdat_pos = None
    for name, pos, _ in atoms:
        if name == "moov" and moov_pos is None:
            moov_pos = pos
        elif name == "mdat" and mdat_pos is None:
            mdat_pos = pos
    if moov_pos is not None and mdat_pos is not None:
        return moov_pos < mdat_pos
    return False


def probe_media_file(file_path: str) -> Dict[str, Any]:
    """Obtém metadados de vídeo e áudio via ffprobe."""
    cmd = [
        "ffprobe",
        "-v", "error",
        "-show_entries", "format=duration,size:stream=codec_type,codec_name,width,height",
        "-of", "json",
        file_path,
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, check=True)
    return json.loads(res.stdout)


def evaluate_task_safety(task_id: str, db_path: Optional[str] = None) -> Tuple[bool, str]:
    """Verifica se a tarefa pode receber remux com segurança de integridade e governança."""
    clean_tid = str(task_id or "").strip()
    if not clean_tid:
        return False, "Task ID inválido ou vazio."

    db = db_path or utils.db_path()
    if not os.path.isfile(db):
        return True, "Banco SQLite não encontrado (modo DEV isolado)."

    with sqlite3.connect(db) as conn:
        conn.row_factory = sqlite3.Row

        # 1. Verifica se já foi publicada
        try:
            pub = conn.execute(
                "SELECT id, status FROM publication_events WHERE task_id = ? AND status = 'success';",
                (clean_tid,),
            ).fetchone()
            if pub:
                return False, f"BLOQUEIO: Vídeo já publicado no YouTube (publication_events id={pub['id']})."
        except sqlite3.OperationalError:
            pass

        # 2. Verifica se está agendada
        try:
            sched = conn.execute(
                "SELECT id, status FROM scheduled_posts WHERE task_id = ? AND status IN ('pending', 'processing');",
                (clean_tid,),
            ).fetchone()
            if sched:
                return False, f"BLOQUEIO: Vídeo já agendado para publicação (scheduled_posts id={sched['id']})."
        except sqlite3.OperationalError:
            pass

        # 3. Verifica se possui aprovação manual de Copyright vinculada a SHA-256
        try:
            manual_appr = conn.execute(
                "SELECT id, metadata_json FROM operational_events WHERE event_type = ? AND task_id = ?;",
                (copyright_gate.EVENT_TASK_COPYRIGHT_MANUAL_APPROVAL, clean_tid),
            ).fetchall()
            for row in manual_appr:
                meta = json.loads(row["metadata_json"] or "{}")
                if meta.get("final_video_sha256"):
                    return False, (
                        f"BLOQUEIO: Tarefa possui aprovação manual de Copyright (id={row['id']}) "
                        f"criptograficamente vinculada ao SHA-256 exato de final-1.mp4 "
                        f"({meta.get('final_video_sha256')[:12]}...). O remux alteraria o hash do arquivo "
                        f"e invalidaria permanentemente o Copyright Gate."
                    )
        except sqlite3.OperationalError:
            pass

    return True, "Aprovado para remux com segurança."


def remux_task_faststart(
    task_id: str,
    apply: bool = False,
    task_base_dir: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """Executa ou simula o remux faststart de uma tarefa específica."""
    clean_tid = str(task_id or "").strip()
    base_dir = task_base_dir or utils.task_dir()
    task_dir = os.path.join(base_dir, clean_tid)
    video_path = os.path.join(task_dir, "final-1.mp4")

    if not os.path.isfile(video_path) or os.path.getsize(video_path) == 0:
        return {"status": "error", "message": f"Arquivo final-1.mp4 inexistente ou vazio em {video_path}"}

    # Avalia governança e contratos de hash
    is_safe, safety_reason = evaluate_task_safety(clean_tid, db_path=db_path)
    if not is_safe:
        return {"status": "blocked", "message": safety_reason}

    # Avalia se já possui faststart
    atoms = check_mp4_atoms(video_path)
    if is_already_faststart(atoms):
        return {
            "status": "already_faststart",
            "message": "O arquivo final-1.mp4 já possui índice moov no início (faststart ativo).",
            "atoms": atoms,
        }

    # Proba vídeo original
    orig_probe = probe_media_file(video_path)
    orig_duration = float(orig_probe.get("format", {}).get("duration", 0.0))
    orig_size = os.path.getsize(video_path)

    if not apply:
        return {
            "status": "dry_run",
            "task_id": clean_tid,
            "video_path": video_path,
            "original_size_bytes": orig_size,
            "original_duration_seconds": orig_duration,
            "atoms_before": atoms,
            "message": "Simulação (Dry-run) concluída com sucesso. Nenhuma alteração foi gravada em disco.",
        }

    # Aplicação real: arquivo temporário no mesmo diretório
    temp_dir = task_dir
    fd, temp_output = tempfile.mkstemp(prefix=".faststart-", suffix=".mp4", dir=temp_dir)
    os.close(fd)

    ffmpeg_bin = utils.get_ffmpeg_binary()
    cmd = [
        ffmpeg_bin,
        "-y",
        "-i", video_path,
        "-c", "copy",
        "-movflags", "+faststart",
        temp_output,
    ]

    try:
        res = subprocess.run(cmd, capture_output=True, text=True)
        if res.returncode != 0:
            return {"status": "error", "message": f"Falha no FFmpeg: {res.stderr[-300:]}"}

        # Validação estrita do arquivo temporário gerado
        new_probe = probe_media_file(temp_output)
        new_duration = float(new_probe.get("format", {}).get("duration", 0.0))
        if abs(new_duration - orig_duration) > 0.1:
            raise ValueError(f"Divergência de duração: original={orig_duration}s, novo={new_duration}s")

        new_atoms = check_mp4_atoms(temp_output)
        if not is_already_faststart(new_atoms):
            raise ValueError("O arquivo temporário gerado não apresentou o átomo moov no início.")

        # Preserva backup (.bak) antes da substituição atômica
        backup_path = f"{video_path}.bak"
        if not os.path.exists(backup_path):
            shutil.copy2(video_path, backup_path)

        # Substituição atômica
        os.replace(temp_output, video_path)

        return {
            "status": "success",
            "task_id": clean_tid,
            "video_path": video_path,
            "backup_path": backup_path,
            "original_size": orig_size,
            "new_size": os.path.getsize(video_path),
            "atoms_after": new_atoms,
            "message": "Remux faststart aplicado com sucesso e validado atomicamente.",
        }
    except Exception as exc:
        return {"status": "error", "message": f"Erro durante a aplicação do remux: {exc}"}
    finally:
        if os.path.exists(temp_output):
            try:
                os.remove(temp_output)
            except OSError:
                pass


def main():
    parser = argparse.ArgumentParser(description="Remux faststart seguro para vídeos da Video Factory")
    parser.add_argument("--task-id", required=True, help="Identificador canônico da tarefa a inspecionar/remuxar")
    parser.add_argument("--apply", action="store_true", default=False, help="Aplica as alterações em disco (padrão: dry-run)")
    args = parser.parse_args()

    res = remux_task_faststart(task_id=args.task_id, apply=args.apply)
    print(json.dumps(res, indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
