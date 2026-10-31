#!/usr/bin/env python3
"""Build Stamp Generator and Verifier for Web UI V2.

Calcula e valida determinísticamente o hash dos arquivos em webui-v2/src,
do package-lock.json e a versão do Vite, gerando ou verificando o arquivo
webui-v2/dist/BUILD_STAMP.json.

Suporta verificação do sistema de arquivos local ou diretamente de um
commit/árvore Git (via --git-ref <ref>), permitindo validações em preflight
sem necessidade de checkout prévio nem de Node.js.

Normaliza quebras de linha (CRLF -> LF) para garantir hashes idênticos
no Windows e Linux independentemente da configuração de core.autocrlf do Git.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))


def get_paths(repo_root: Optional[str] = None) -> Tuple[str, str, str, str]:
    root = os.path.abspath(repo_root or REPO_ROOT)
    webui_root = os.path.join(root, "webui-v2")
    src_dir = os.path.join(webui_root, "src")
    lock_file = os.path.join(webui_root, "package-lock.json")
    dist_dir = os.path.join(webui_root, "dist")
    stamp_file = os.path.join(dist_dir, "BUILD_STAMP.json")
    return src_dir, lock_file, dist_dir, stamp_file


def compute_build_stamp(repo_root: Optional[str] = None) -> Dict[str, Any]:
    src_dir, lock_file, _, _ = get_paths(repo_root)

    if not os.path.isdir(src_dir):
        raise FileNotFoundError(f"Diretório src não encontrado: {src_dir}")
    if not os.path.isfile(lock_file):
        raise FileNotFoundError(f"package-lock.json não encontrado: {lock_file}")

    # 1. src_hash: hash determinístico de todos os arquivos de código sob src/
    file_entries: List[str] = []
    for root_dir, _, files in os.walk(src_dir):
        for f in sorted(files):
            if f.startswith("."):
                continue
            full_path = os.path.join(root_dir, f)
            rel_path = os.path.relpath(full_path, src_dir).replace("\\", "/")
            with open(full_path, "rb") as fp:
                content = fp.read().replace(b"\r\n", b"\n")
            f_hash = hashlib.sha256(content).hexdigest()
            file_entries.append(f"{rel_path}:{f_hash}")

    file_entries.sort()
    manifest = "\n".join(file_entries).encode("utf-8")
    src_hash = hashlib.sha256(manifest).hexdigest()

    # 2. package_lock_hash
    with open(lock_file, "rb") as fp:
        lock_raw = fp.read().replace(b"\r\n", b"\n")
    lock_hash = hashlib.sha256(lock_raw).hexdigest()

    # 3. vite_version
    lock_data = json.loads(lock_raw.decode("utf-8"))
    vite_version = (
        lock_data.get("packages", {}).get("node_modules/vite", {}).get("version")
        or lock_data.get("dependencies", {}).get("vite", {}).get("version")
        or ""
    )

    # 4. combined_hash
    combined_raw = f"{src_hash}:{lock_hash}:{vite_version}".encode("utf-8")
    combined_hash = hashlib.sha256(combined_raw).hexdigest()

    return {
        "src_hash": src_hash,
        "package_lock_hash": lock_hash,
        "vite_version": vite_version,
        "combined_hash": combined_hash,
        "built_at": datetime.now(timezone.utc).isoformat(),
    }


def compute_build_stamp_from_git(git_ref: str, repo_root: Optional[str] = None) -> Dict[str, Any]:
    root = os.path.abspath(repo_root or REPO_ROOT)

    # 1. Obter lista de arquivos em webui-v2/src para o ref
    cmd_tree = ["git", "ls-tree", "-r", "--name-only", git_ref, "webui-v2/src"]
    res_tree = subprocess.run(cmd_tree, cwd=root, capture_output=True, text=True, check=True)
    file_paths = [p.strip().replace("\\", "/") for p in res_tree.stdout.splitlines() if p.strip()]

    file_entries: List[str] = []
    prefix = "webui-v2/src/"
    for fpath in sorted(file_paths):
        base_name = os.path.basename(fpath)
        if base_name.startswith("."):
            continue
        rel_to_src = fpath[len(prefix):] if fpath.startswith(prefix) else fpath
        cmd_show = ["git", "show", f"{git_ref}:{fpath}"]
        res_show = subprocess.run(cmd_show, cwd=root, capture_output=True, check=True)
        content = res_show.stdout.replace(b"\r\n", b"\n")
        f_hash = hashlib.sha256(content).hexdigest()
        file_entries.append(f"{rel_to_src}:{f_hash}")

    file_entries.sort()
    manifest = "\n".join(file_entries).encode("utf-8")
    src_hash = hashlib.sha256(manifest).hexdigest()

    # 2. package-lock.json
    cmd_lock = ["git", "show", f"{git_ref}:webui-v2/package-lock.json"]
    res_lock = subprocess.run(cmd_lock, cwd=root, capture_output=True, check=True)
    lock_raw = res_lock.stdout.replace(b"\r\n", b"\n")
    lock_hash = hashlib.sha256(lock_raw).hexdigest()

    # 3. vite_version
    lock_data = json.loads(lock_raw.decode("utf-8"))
    vite_version = (
        lock_data.get("packages", {}).get("node_modules/vite", {}).get("version")
        or lock_data.get("dependencies", {}).get("vite", {}).get("version")
        or ""
    )

    # 4. combined_hash
    combined_raw = f"{src_hash}:{lock_hash}:{vite_version}".encode("utf-8")
    combined_hash = hashlib.sha256(combined_raw).hexdigest()

    return {
        "src_hash": src_hash,
        "package_lock_hash": lock_hash,
        "vite_version": vite_version,
        "combined_hash": combined_hash,
        "git_ref": git_ref,
    }


def write_build_stamp(repo_root: Optional[str] = None) -> Dict[str, Any]:
    _, _, dist_dir, stamp_file = get_paths(repo_root)
    os.makedirs(dist_dir, exist_ok=True)
    stamp = compute_build_stamp(repo_root)
    with open(stamp_file, "w", encoding="utf-8") as f:
        json.dump(stamp, f, indent=2)
        f.write("\n")
    print(f"[BUILD_STAMP] Gravado com sucesso em {stamp_file} (combined_hash={stamp['combined_hash']})")
    return stamp


def verify_build_stamp(
    repo_root: Optional[str] = None,
    git_ref: Optional[str] = None,
) -> Tuple[bool, str, Optional[Dict[str, Any]]]:
    """Valida se o dist existe e se BUILD_STAMP.json coincide com src/lockfile."""
    root = os.path.abspath(repo_root or REPO_ROOT)

    if git_ref:
        try:
            res_ref = subprocess.run(
                ["git", "rev-parse", "--verify", f"{git_ref}^{{commit}}"],
                cwd=root,
                capture_output=True,
                text=True,
            )
            if res_ref.returncode != 0:
                return False, f"Git ref inválido: {git_ref}", None
            resolved_ref = res_ref.stdout.strip()
        except Exception as exc:
            return False, f"Falha ao validar git ref '{git_ref}': {exc}", None

        # 1. Confirma index.html no commit
        res_idx = subprocess.run(
            ["git", "cat-file", "-e", f"{resolved_ref}:webui-v2/dist/index.html"],
            cwd=root,
            capture_output=True,
        )
        if res_idx.returncode != 0:
            return False, f"webui-v2/dist/index.html ausente no commit {git_ref}", None

        # 2. Lê BUILD_STAMP.json do commit
        res_stamp = subprocess.run(
            ["git", "show", f"{resolved_ref}:webui-v2/dist/BUILD_STAMP.json"],
            cwd=root,
            capture_output=True,
        )
        if res_stamp.returncode != 0:
            return False, f"webui-v2/dist/BUILD_STAMP.json ausente no commit {git_ref}", None

        try:
            persisted = json.loads(res_stamp.stdout.decode("utf-8"))
        except Exception as exc:
            return False, f"Falha ao decodificar BUILD_STAMP.json no commit {git_ref}: {exc}", None

        try:
            current = compute_build_stamp_from_git(resolved_ref, root)
        except Exception as exc:
            return False, f"Falha ao computar build stamp do commit {git_ref}: {exc}", None

        if persisted.get("src_hash") != current["src_hash"]:
            return (
                False,
                f"Divergência de código em src no commit {git_ref} (gravado={persisted.get('src_hash')[:12]}, calculado={current['src_hash'][:12]})",
                {"persisted": persisted, "current": current},
            )

        if persisted.get("package_lock_hash") != current["package_lock_hash"]:
            return (
                False,
                f"Divergência em package-lock.json no commit {git_ref} (gravado={persisted.get('package_lock_hash')[:12]}, calculado={current['package_lock_hash'][:12]})",
                {"persisted": persisted, "current": current},
            )

        if persisted.get("vite_version") != current["vite_version"]:
            return (
                False,
                f"Divergência de versão do Vite no commit {git_ref} (gravado={persisted.get('vite_version')}, calculado={current['vite_version']})",
                {"persisted": persisted, "current": current},
            )

        if persisted.get("combined_hash") != current["combined_hash"]:
            return (
                False,
                f"Divergência em combined_hash no commit {git_ref} (gravado={persisted.get('combined_hash')[:12]}, calculado={current['combined_hash'][:12]})",
                {"persisted": persisted, "current": current},
            )

        return True, f"BUILD_STAMP válido e sincronizado no commit {git_ref}", current

    # Validação no sistema de arquivos local
    _, _, dist_dir, stamp_file = get_paths(repo_root)

    if not os.path.isdir(dist_dir):
        return False, f"Diretório dist não encontrado em {dist_dir}", None

    index_html = os.path.join(dist_dir, "index.html")
    if not os.path.isfile(index_html):
        return False, f"index.html ausente no dist: {index_html}", None

    if not os.path.isfile(stamp_file):
        return False, f"BUILD_STAMP.json ausente no dist: {stamp_file}", None

    try:
        with open(stamp_file, "r", encoding="utf-8") as f:
            persisted = json.load(f)
    except Exception as exc:
        return False, f"Falha ao ler BUILD_STAMP.json: {exc}", None

    try:
        current = compute_build_stamp(repo_root)
    except Exception as exc:
        return False, f"Falha ao computar build stamp local: {exc}", None

    if persisted.get("src_hash") != current["src_hash"]:
        return (
            False,
            f"Divergência de código em src (gravado={persisted.get('src_hash')[:12]}, atual={current['src_hash'][:12]})",
            {"persisted": persisted, "current": current},
        )

    if persisted.get("package_lock_hash") != current["package_lock_hash"]:
        return (
            False,
            f"Divergência em package-lock.json (gravado={persisted.get('package_lock_hash')[:12]}, atual={current['package_lock_hash'][:12]})",
            {"persisted": persisted, "current": current},
        )

    if persisted.get("vite_version") != current["vite_version"]:
        return (
            False,
            f"Divergência de versão do Vite (gravado={persisted.get('vite_version')}, atual={current['vite_version']})",
            {"persisted": persisted, "current": current},
        )

    if persisted.get("combined_hash") != current["combined_hash"]:
        return (
            False,
            f"Divergência em combined_hash (gravado={persisted.get('combined_hash')[:12]}, atual={current['combined_hash'][:12]})",
            {"persisted": persisted, "current": current},
        )

    return True, "BUILD_STAMP válido e sincronizado com src e package-lock.json", current


def main() -> int:
    parser = argparse.ArgumentParser(description="Build Stamp Generator & Verifier for Web UI V2")
    parser.add_argument("--write", action="store_true", help="Gera e grava webui-v2/dist/BUILD_STAMP.json")
    parser.add_argument("--verify", action="store_true", help="Valida se webui-v2/dist está sincronizado com o código atual")
    parser.add_argument("--git-ref", default=None, help="Commit/Ref Git para validação direta da árvore sem tocar na working tree")
    parser.add_argument("--repo-root", default=None, help="Caminho raiz do repositório (opcional)")

    args = parser.parse_args()

    if args.write:
        try:
            write_build_stamp(args.repo_root)
            return 0
        except Exception as exc:
            print(f"ERRO ao gerar BUILD_STAMP: {exc}", file=sys.stderr)
            return 1

    if args.verify or args.git_ref or not sys.argv[1:]:
        ok, msg, _ = verify_build_stamp(args.repo_root, git_ref=args.git_ref)
        if ok:
            print(f"OK: {msg}")
            return 0
        else:
            print(f"FALHA: {msg}", file=sys.stderr)
            return 1

    parser.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
