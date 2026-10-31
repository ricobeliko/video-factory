#!/usr/bin/env python3
"""Auditoria de Vozes por Canal (Somente Leitura).

Este script opera exclusivamente sobre uma CÓPIA temporária do banco SQLite
(nunca toca no banco original ao vivo). Pode ser executado com segurança tanto
no ambiente de desenvolvimento quanto na máquina de produção (PC Forte).

Uso:
    python scripts/dev/auditar_vozes_canais.py
    python scripts/dev/auditar_vozes_canais.py --db-path /caminho/para/video_factory.db
"""

import argparse
import json
import os
import shutil
import sqlite3
import sys
import tempfile
from typing import Any, Dict, List, Optional

# Adiciona a raiz do projeto ao sys.path para carregar app.config e app.services se disponíveis
REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if REPO_ROOT not in sys.path:
    sys.path.insert(0, REPO_ROOT)

try:
    from app.config import config
    from app.services import voice
except ImportError:
    config = None
    voice = None


def make_readonly_db_copy(src_path: str) -> str:
    """Cria uma cópia física temporária do banco SQLite via sqlite3.backup."""
    if not os.path.isfile(src_path):
        raise FileNotFoundError(f"Banco SQLite não encontrado em: {src_path}")

    temp_fd, temp_copy_path = tempfile.mkstemp(prefix="audit_voice_", suffix=".db")
    os.close(temp_fd)

    src_conn = sqlite3.connect(f"file:{os.path.abspath(src_path)}?mode=ro", uri=True)
    dst_conn = sqlite3.connect(temp_copy_path)
    try:
        src_conn.backup(dst_conn)
    finally:
        src_conn.close()
        dst_conn.close()

    return temp_copy_path


def get_global_voice() -> Optional[str]:
    """Retorna a voz global configurada na UI."""
    if config and hasattr(config, "ui"):
        v = config.ui.get("voice_name")
        if v and str(v).strip():
            return str(v).strip()

    # Fallback se config não foi inicializado: ler config.toml diretamente
    cfg_file = os.path.join(REPO_ROOT, "config.toml")
    if os.path.isfile(cfg_file):
        try:
            import tomllib
        except ImportError:
            try:
                import tomli as tomllib
            except ImportError:
                tomllib = None
        if tomllib:
            try:
                with open(cfg_file, "rb") as f:
                    data = tomllib.load(f)
                v = data.get("ui", {}).get("voice_name")
                if v and str(v).strip():
                    return str(v).strip()
            except Exception:
                pass
    return None


def canonicalize(voice_name: Optional[str]) -> str:
    if not voice_name:
        return "en-US-BrianMultilingualNeural"
    if voice and hasattr(voice, "canonicalize_voice_name"):
        c = voice.canonicalize_voice_name(voice_name)
        if c and c.endswith(("-Male", "-Female")) and hasattr(voice, "parse_voice_name"):
            c = voice.parse_voice_name(c)
        return c or voice_name
    return voice_name


def audit_channel_voices(db_copy_path: str) -> List[Dict[str, Any]]:
    global_voice = get_global_voice()
    fallback_voice = "en-US-BrianMultilingualNeural"
    if config and hasattr(config, "app"):
        fallback_voice = config.app.get("voice_name") or fallback_voice

    results = []
    conn = sqlite3.connect(f"file:{os.path.abspath(db_copy_path)}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        rows = conn.execute(
            """
            SELECT id, name, slug, niche, is_active, settings_json
            FROM content_profiles
            ORDER BY id ASC;
            """
        ).fetchall()

        for r in rows:
            pid = r["id"]
            pname = r["name"] or pid
            is_active = bool(r["is_active"])

            # Extrai voz salva no perfil a partir do settings_json
            raw_settings = {}
            if r["settings_json"]:
                try:
                    raw_settings = json.loads(r["settings_json"])
                except Exception:
                    pass

            v_sec = raw_settings.get("voice", {})
            profile_voice = str(v_sec.get("voice_name") or "").strip() or None

            # Resolução V1 (main): Global UI > Perfil do Canal > App Fallback
            # Na main, a voz global da fábrica atropelava qualquer voz de canal
            v1_raw = global_voice or profile_voice or fallback_voice
            v1_effective = canonicalize(v1_raw)
            v1_source = "global" if global_voice else ("profile" if profile_voice else "default")

            # Resolução V2 (v2/base): Canal > Global UI > App Fallback
            # Na V2, a voz do canal prevalece se preenchida; se vazia, herda da Global
            v2_raw = profile_voice or global_voice or fallback_voice
            v2_effective = canonicalize(v2_raw)
            v2_source = "channel" if profile_voice else ("global" if global_voice else "default")

            diverges = v1_effective != v2_effective

            results.append({
                "profile_id": pid,
                "profile_name": pname,
                "is_active": is_active,
                "profile_voice": profile_voice or "— (herdada)",
                "global_voice": global_voice or "— (não definida)",
                "v1_effective": v1_effective,
                "v1_source": v1_source,
                "v2_effective": v2_effective,
                "v2_source": v2_source,
                "diverges": diverges,
            })
    finally:
        conn.close()

    return results


def print_audit_report(results: List[Dict[str, Any]], db_source: str) -> None:
    print("=" * 95)
    print("RELATÓRIO DE AUDITORIA DE VOZES POR CANAL (SOMENTE LEITURA)")
    print(f"Banco auditado (cópia temporária): {db_source}")
    print("=" * 95)

    headers = [
        "Perfil / Canal",
        "Ativo?",
        "Voz no Perfil (Canal)",
        "Voz Global UI",
        "Voz Main (V1)",
        "Voz V2/Base (V2)",
        "Diverge?",
    ]
    col_w = [22, 7, 23, 20, 24, 24, 9]

    row_fmt = " | ".join(f"{{:<{w}}}" for w in col_w)
    sep_line = "-+-".join("-" * w for w in col_w)

    print(row_fmt.format(*headers))
    print(sep_line)

    divergence_count = 0
    for r in results:
        status_txt = "Sim" if r["is_active"] else "Não"
        div_txt = "SIM (!)" if r["diverges"] else "Não"
        if r["diverges"]:
            divergence_count += 1

        print(row_fmt.format(
            r["profile_name"][:22],
            status_txt,
            r["profile_voice"][:23],
            r["global_voice"][:20],
            r["v1_effective"][:24],
            r["v2_effective"][:24],
            div_txt,
        ))

    print("=" * 95)
    print(f"Total de perfis/canais: {len(results)}")
    print(f"Perfis com divergência entre V1 e V2: {divergence_count}")
    if divergence_count > 0:
        print("\n[NOTA DE PRECEDÊNCIA]:")
        print(" - Na V1 (main), a Voz Global da UI tinha precedência máxima e atropelava a voz do perfil.")
        print(" - Na V2 (v2/base), a Voz do Canal prevalece sobre a Global (missão v2/voz-por-canal).")
        print(" - Canais sem voz própria ('— (herdada)') continuam usando a Voz Global em ambas as versões.")
    else:
        print("\n[PARIDADE]: Todas as vozes efetivas são idênticas entre V1 e V2.")
    print("=" * 95)


def main():
    parser = argparse.ArgumentParser(description="Auditoria de Vozes por Canal (Somente Leitura)")
    parser.add_argument(
        "--db-path",
        default=os.path.join(REPO_ROOT, "storage", "video_factory.db"),
        help="Caminho do arquivo SQLite de origem (será copiado de forma temporária e somente leitura)",
    )
    args = parser.parse_args()

    src_db = os.path.abspath(args.db_path)
    if not os.path.isfile(src_db):
        print(f"ERRO: Banco não encontrado em: {src_db}", file=sys.stderr)
        sys.exit(1)

    temp_copy = make_readonly_db_copy(src_db)
    try:
        results = audit_channel_voices(temp_copy)
        print_audit_report(results, src_db)
    finally:
        if os.path.isfile(temp_copy):
            try:
                os.remove(temp_copy)
            except OSError:
                pass


if __name__ == "__main__":
    main()
