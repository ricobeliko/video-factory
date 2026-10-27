#!/usr/bin/env python3
"""Script de Auditoria Somente Leitura da Voz (Configurada vs. Realmente Usada).

Missão V0 — V2 Auditoria de Voz.
Opera estritamente em modo READ-ONLY sobre cópia temporária do banco SQLite (via sqlite3 backup).
ZERO gravações no banco, ZERO chamadas de rede externas e ZERO vazamento de segredos.
"""

from __future__ import annotations

import argparse
import hashlib
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


def _compute_file_sha256(file_path: str) -> str:
    """Calcula o hash SHA-256 de um arquivo."""
    hasher = hashlib.sha256()
    with open(file_path, "rb") as f:
        while chunk := f.read(65536):
            hasher.update(chunk)
    return hasher.hexdigest()


def _create_ro_temp_backup(source_db_path: str) -> Tuple[str, str, float]:
    """Cria uma cópia temporária do banco via sqlite3 backup e retorna (temp_path, sha256_inicial, mtime_inicial)."""
    abs_src = os.path.abspath(source_db_path)
    if not os.path.isfile(abs_src):
        raise FileNotFoundError(f"Banco de dados de origem não encontrado: {abs_src}")

    # Cria arquivo temporário
    temp_fd, temp_db_path = tempfile.mkstemp(prefix="audit_voice_backup_", suffix=".db")
    os.close(temp_fd)

    # Abre origem em modo somente leitura (mode=ro)
    src_uri = Path(abs_src).as_uri() + "?mode=ro"
    src_conn = sqlite3.connect(src_uri, uri=True, timeout=10.0)
    dst_conn = sqlite3.connect(temp_db_path, timeout=10.0)

    try:
        src_conn.backup(dst_conn)
    finally:
        dst_conn.close()
        src_conn.close()

    initial_sha = _compute_file_sha256(temp_db_path)
    initial_mtime = os.path.getmtime(temp_db_path)
    return temp_db_path, initial_sha, initial_mtime


def _get_ro_connection(db_path: str) -> sqlite3.Connection:
    """Abre conexão SQLite estritamente em modo somente leitura (mode=ro)."""
    abs_path = os.path.abspath(db_path)
    if not os.path.isfile(abs_path):
        raise FileNotFoundError(f"Arquivo não encontrado: {abs_path}")
    uri = Path(abs_path).as_uri() + "?mode=ro"
    conn = sqlite3.connect(uri, uri=True, timeout=10.0)
    conn.row_factory = sqlite3.Row
    return conn


def _mask_secrets(data: Any) -> Any:
    """Mascara recursivamente qualquer chave ou valor que pareça ser segredo."""
    sensitive_keywords = {"key", "token", "secret", "password", "auth", "credential", "private", "api"}
    if isinstance(data, dict):
        masked = {}
        for k, v in data.items():
            if any(s in str(k).lower() for s in sensitive_keywords):
                masked[k] = "***MASKED***" if v else None
            else:
                masked[k] = _mask_secrets(v)
        return masked
    elif isinstance(data, list):
        return [_mask_secrets(item) for item in data]
    return data


def load_masked_config(config_path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Carrega config.toml de forma segura, mascarando segredos e extraindo seções relevantes."""
    abs_config = os.path.abspath(config_path)
    if not os.path.isfile(abs_config):
        return {}, {}

    try:
        if sys.version_info >= (3, 11):
            import tomllib
            with open(abs_config, "rb") as f:
                raw_cfg = tomllib.load(f)
        else:
            import toml
            raw_cfg = toml.load(abs_config)
    except Exception as exc:
        return {"error": f"Falha ao carregar TOML: {exc}"}, {}

    masked_cfg = _mask_secrets(raw_cfg)
    ui_section = raw_cfg.get("ui", {})
    app_section = raw_cfg.get("app", {})

    extracted = {
        "ui_voice_name": ui_section.get("voice_name"),
        "ui_tts_server": ui_section.get("tts_server"),
        "ui_voice_rate": ui_section.get("voice_rate"),
        "ui_voice_volume": ui_section.get("voice_volume"),
        "app_voice_name": app_section.get("voice_name"),
        "app_tts_server": app_section.get("tts_server"),
    }
    return masked_cfg, extracted


def audit_channel_voices(
    db_path: str,
    config_path: str,
    tasks_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """Audita a resolução de vozes para todos os canais em todas as camadas (a, b, c, d, e)."""
    from app.config import config
    from app.services import profile_manager, voice
    from app.services.autonomous_production import build_autonomous_video_params

    # Carrega config especificado em memória para avaliação fiel
    abs_config = os.path.abspath(config_path)
    if os.path.isfile(abs_config):
        try:
            if sys.version_info >= (3, 11):
                import tomllib
                with open(abs_config, "rb") as f:
                    loaded_toml = tomllib.load(f)
            else:
                import toml
                with open(abs_config, "r", encoding="utf-8") as f:
                    loaded_toml = toml.load(f)
            config._cfg.clear()
            config._cfg.update(loaded_toml)
            if "app" in loaded_toml:
                config.app.clear()
                config.app.update(loaded_toml.get("app", {}))
            if "ui" in loaded_toml:
                config.ui.clear()
                config.ui.update(loaded_toml.get("ui", {}))
        except Exception as exc:
            pass

    masked_config, config_extracted = load_masked_config(config_path)
    base_tasks_dir = Path(tasks_dir or "storage/tasks").resolve()

    report: Dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "database_analyzed": os.path.abspath(db_path),
        "config_analyzed": os.path.abspath(config_path),
        "tasks_directory": str(base_tasks_dir),
        "config_layer_a": config_extracted,
        "channels": [],
    }

    # 1. Obter todos os perfis do banco
    with _get_ro_connection(db_path) as conn:
        profiles_rows = conn.execute(
            "SELECT id, name, is_active, settings_json FROM content_profiles ORDER BY id ASC;"
        ).fetchall()

    for row in profiles_rows:
        pid = row["id"]
        pname = row["name"]
        is_active = bool(row["is_active"])
        raw_settings_str = row["settings_json"]
        settings_dict = {}
        if raw_settings_str:
            try:
                settings_dict = json.loads(raw_settings_str)
            except Exception:
                settings_dict = {}

        editorial = settings_dict.get("editorial", {})
        voice_settings = settings_dict.get("voice", {})
        video_format = editorial.get("video_format") or "traditional"
        content_style = editorial.get("content_style")

        # Camada (a)
        layer_a = {
            "config_ui_voice_name": config_extracted.get("ui_voice_name"),
            "config_ui_tts_server": config_extracted.get("ui_tts_server"),
            "config_app_voice_name": config_extracted.get("app_voice_name"),
            "profile_stored_voice_name": voice_settings.get("voice_name"),
        }

        # Camada (b): get_generation_profile_context
        try:
            ctx = profile_manager.get_generation_profile_context(profile_id=pid, db_path=db_path)
            layer_b = {
                "resolved_voice_name": ctx.get("voice_name"),
                "voice_rate": ctx.get("voice_rate"),
                "voice_volume": ctx.get("voice_volume"),
                "video_format": ctx.get("video_format"),
                "narrative_structure": ctx.get("narrative_structure"),
            }
        except Exception as exc:
            layer_b = {"error": str(exc), "resolved_voice_name": None}

        # Camada (c): build_autonomous_video_params (resolução pura sem renderizar)
        try:
            params = build_autonomous_video_params(
                topic="auditoria_somente_leitura",
                profile_id=pid,
                narrative_structure=layer_b.get("narrative_structure"),
                db_path=db_path,
            )
            layer_c = {
                "resolved_voice_name": params.voice_name,
                "voice_rate": params.voice_rate,
                "voice_volume": params.voice_volume,
                "video_format": params.video_format,
                "narrative_structure": params.narrative_structure,
            }
        except Exception as exc:
            layer_c = {"error": str(exc), "resolved_voice_name": None}

        # Camada (d): Parâmetros específicos de Quiz
        is_quiz = (video_format in ("quiz_dilemma", "quiz_paper")) or (
            str(layer_b.get("narrative_structure", "")).startswith("quiz")
        )
        layer_d = {
            "is_quiz_pipeline": is_quiz,
            "export_to_quiz_config_fallback": "pt-BR-AntonioNeural",
            "export_to_paper_quiz_config_fallback": "pt-BR-AntonioNeural",
            "quiz_tts_engine": "Edge TTS direto (edge_tts.Communicate)",
            "quiz_voice_behavior": (
                "Herda params.voice_name se não-vazio; se vazio ou nulo, aplica fallback hardcoded 'pt-BR-AntonioNeural' (voz masculina)."
                if is_quiz
                else "Não aplicável (canal tradicional / não-quiz)."
            ),
        }

        # Camada (e): Últimas 5 tarefas do canal
        # Busca tarefas associadas ao canal em task_profiles ou no filesystem
        channel_tasks: List[str] = []
        with _get_ro_connection(db_path) as conn:
            t_rows = conn.execute(
                "SELECT task_id, created_at FROM task_profiles WHERE profile_id = ? ORDER BY created_at DESC, rowid DESC LIMIT 20;",
                (pid,),
            ).fetchall()
            for tr in t_rows:
                channel_tasks.append(tr["task_id"])

        # Também verifica operational_events para encontrar task_ids
        with _get_ro_connection(db_path) as conn:
            ev_rows = conn.execute(
                "SELECT task_id FROM operational_events WHERE metadata_json LIKE ? AND task_id IS NOT NULL ORDER BY id DESC LIMIT 50;",
                (f"%{pid}%",),
            ).fetchall()
            for er in ev_rows:
                tid = er["task_id"]
                if tid and tid not in channel_tasks:
                    channel_tasks.append(tid)

        # Se houver menos de 5 tarefas, varre o diretório storage/tasks
        if len(channel_tasks) < 5 and base_tasks_dir.is_dir():
            try:
                for entry in sorted(base_tasks_dir.iterdir(), key=lambda p: p.stat().st_mtime, reverse=True):
                    if entry.is_dir() and entry.name not in channel_tasks:
                        s_file = entry / "script.json"
                        if s_file.is_file():
                            try:
                                with s_file.open("r", encoding="utf-8") as sf:
                                    s_json = json.load(sf)
                                task_p = s_json.get("params", {})
                                t_pid = task_p.get("profile_id")
                                if t_pid == pid or (not t_pid and pid == "default"):
                                    channel_tasks.append(entry.name)
                                    if len(channel_tasks) >= 5:
                                        break
                            except Exception:
                                pass
            except Exception:
                pass

        task_audits: List[Dict[str, Any]] = []
        for tid in channel_tasks[:5]:
            task_dir = base_tasks_dir / tid
            script_path = task_dir / "script.json"
            manifest_path = task_dir / "flow" / "manifest.json"
            quiz_cfg_path = task_dir / "quiz_config.json"
            audio_path = task_dir / "audio.mp3"
            video_path = task_dir / "final-1.mp4"

            has_audio = audio_path.is_file()
            audio_size = audio_path.stat().st_size if has_audio else 0
            has_video = video_path.is_file()

            script_voice_name = None
            script_provider = None
            flow_voice_name = None
            quiz_voice_name = None

            if script_path.is_file():
                try:
                    with script_path.open("r", encoding="utf-8") as f:
                        s_data = json.load(f)
                    p_data = s_data.get("params", {})
                    script_voice_name = p_data.get("voice_name")
                    tts_diag = s_data.get("tts_diagnostic", {})
                    script_provider = tts_diag.get("provider") or tts_diag.get("tts_server")
                except Exception:
                    pass

            if manifest_path.is_file():
                try:
                    with manifest_path.open("r", encoding="utf-8") as f:
                        m_data = json.load(f)
                    flow_voice_name = m_data.get("voice_name")
                except Exception:
                    pass

            if quiz_cfg_path.is_file():
                try:
                    with quiz_cfg_path.open("r", encoding="utf-8") as f:
                        q_data = json.load(f)
                    quiz_voice_name = q_data.get("voice_settings", {}).get("voice_name")
                except Exception:
                    pass

            # Busca eventos operacionais registrados para a tarefa
            op_voice = None
            with _get_ro_connection(db_path) as conn:
                op_ev = conn.execute(
                    "SELECT event_type, metadata_json FROM operational_events WHERE task_id = ? ORDER BY id DESC;",
                    (tid,),
                ).fetchall()
                for op in op_ev:
                    try:
                        meta = json.loads(op["metadata_json"]) if op["metadata_json"] else {}
                        if "voice_name" in meta:
                            op_voice = meta["voice_name"]
                            break
                    except Exception:
                        pass

            # Voz consolidada gravada na tarefa
            recorded_voice = (
                script_voice_name
                or flow_voice_name
                or quiz_voice_name
                or op_voice
                or "(não gravada / desconhecida)"
            )

            configured_voice = layer_b.get("resolved_voice_name")
            is_consistent = (
                (recorded_voice == configured_voice)
                if (recorded_voice and configured_voice and recorded_voice != "(não gravada / desconhecida)")
                else False
            )

            task_audits.append({
                "task_id": tid,
                "has_audio_mp3": has_audio,
                "audio_size_bytes": audio_size,
                "has_final_video": has_video,
                "script_voice_name": script_voice_name,
                "script_provider": script_provider,
                "flow_voice_name": flow_voice_name,
                "quiz_voice_name": quiz_voice_name,
                "operational_event_voice": op_voice,
                "effective_recorded_voice": recorded_voice,
                "status": "CONSISTENTE" if is_consistent else "INCONSISTENTE",
            })

        channel_report = {
            "profile_id": pid,
            "profile_name": pname,
            "is_active": is_active,
            "video_format": video_format,
            "content_style": content_style,
            "layer_a_config": layer_a,
            "layer_b_profile_context": layer_b,
            "layer_c_autonomous_params": layer_c,
            "layer_d_quiz_specifics": layer_d,
            "layer_e_last_tasks": task_audits,
        }
        report["channels"].append(channel_report)

    return report


def print_report_table(report: Dict[str, Any]) -> None:
    """Imprime relatório estruturado no terminal com tabelas legíveis e identificação por camada."""
    print("=" * 80)
    print("RELATÓRIO DE AUDITORIA DE VOZ (SOMENTE LEITURA) — MISSÃO V0")
    print(f"Timestamp: {report.get('timestamp')}")
    print(f"Banco auditado: {report.get('database_analyzed')}")
    print(f"Configuração: {report.get('config_analyzed')}")
    print("=" * 80)

    cfg_a = report.get("config_layer_a", {})
    print("\n[CAMADA A — Configuração Global (config.toml)]")
    print(f"  • ui.voice_name: {cfg_a.get('ui_voice_name') or '(não definido / comentado)'}")
    print(f"  • ui.tts_server: {cfg_a.get('ui_tts_server') or '(não definido / default azure-tts-v1)'}")
    print(f"  • app.voice_name: {cfg_a.get('app_voice_name') or '(não definido / fallback interno)'}")

    channels = report.get("channels", [])
    if not channels:
        print("\nNenhum canal/perfil encontrado no banco de dados.")
        return

    print(f"\nTotal de Canais / Perfis Encontrados: {len(channels)}")

    for idx, ch in enumerate(channels, 1):
        print("\n" + "-" * 80)
        print(f"CANAL {idx}/{len(channels)}: {ch['profile_name']} (ID: {ch['profile_id']})")
        print(f"  Status: {'ATIVO' if ch['is_active'] else 'INATIVO'} | Formato: {ch['video_format']} | Estilo: {ch['content_style'] or '—'}")
        print("-" * 80)

        # Camada A
        la = ch["layer_a_config"]
        print("  1. Camada A (config.toml / DB Profile):")
        print(f"     - config.ui.voice_name: {la.get('config_ui_voice_name') or '(vazio)'}")
        print(f"     - settings_json.voice.voice_name: {la.get('profile_stored_voice_name') or '(null / herda global)'}")

        # Camada B
        lb = ch["layer_b_profile_context"]
        print("  2. Camada B (get_generation_profile_context):")
        print(f"     - resolved_voice_name: {lb.get('resolved_voice_name') or 'NULO'}")
        print(f"     - voice_rate: {lb.get('voice_rate')} | voice_volume: {lb.get('voice_volume')}")

        # Camada C
        lc = ch["layer_c_autonomous_params"]
        print("  3. Camada C (build_autonomous_video_params):")
        print(f"     - resolved_voice_name: {lc.get('resolved_voice_name') or 'NULO'}")
        print(f"     - video_format: {lc.get('video_format')} | structure: {lc.get('narrative_structure')}")

        # Camada D
        ld = ch["layer_d_quiz_specifics"]
        print("  4. Camada D (Pipeline de Quiz):")
        print(f"     - É pipeline de quiz: {'SIM' if ld.get('is_quiz_pipeline') else 'NÃO'}")
        print(f"     - Regra: {ld.get('quiz_voice_behavior')}")

        # Camada E
        le = ch["layer_e_last_tasks"]
        print(f"  5. Camada E (Últimas Tarefas Concluídas — total auditado: {len(le)}):")
        if not le:
            print("     (Nenhuma tarefa registrada para este canal)")
        else:
            print("     " + f"{'TASK_ID':<24} | {'AUDIO.MP3':<10} | {'VOZ GRAVADA':<32} | {'STATUS'}")
            print("     " + "-" * 75)
            for t in le:
                aud_status = f"SIM ({t['audio_size_bytes']}b)" if t['has_audio_mp3'] else "NÃO"
                rec_voice = t['effective_recorded_voice'] or "N/A"
                print(f"     {t['task_id']:<24} | {aud_status:<10} | {rec_voice:<32} | {t['status']}")

    print("\n" + "=" * 80)
    print("FIM DO RELATÓRIO DE AUDITORIA")
    print("=" * 80)


def main():
    parser = argparse.ArgumentParser(description="Auditoria Somente Leitura da Cadeia de Decisão da Voz.")
    parser.add_argument("--db", default="storage/video_factory.db", help="Caminho do banco SQLite")
    parser.add_argument("--config", default="config.toml", help="Caminho do config.toml")
    parser.add_argument("--tasks-dir", default="storage/tasks", help="Diretório das tarefas")
    parser.add_argument("--json-out", default=None, help="Caminho para salvar relatório em JSON")
    args = parser.parse_args()

    db_path = os.path.abspath(args.db)
    config_path = os.path.abspath(args.config)
    tasks_dir = os.path.abspath(args.tasks_dir)

    if not os.path.exists(db_path):
        print(f"ERRO: Banco de dados não encontrado em {db_path}", file=sys.stderr)
        sys.exit(1)

    # Cria cópia temporária do banco via backup para garantir ZERO interferência no banco real
    temp_db_path, initial_sha, initial_mtime = _create_ro_temp_backup(db_path)

    try:
        report = audit_channel_voices(
            db_path=temp_db_path,
            config_path=config_path,
            tasks_dir=tasks_dir,
        )

        print_report_table(report)

        if args.json_out:
            out_p = os.path.abspath(args.json_out)
            os.makedirs(os.path.dirname(out_p), exist_ok=True)
            with open(out_p, "w", encoding="utf-8") as f:
                json.dump(report, f, ensure_ascii=False, indent=2)
            print(f"\nRelatório JSON salvo com sucesso em: {out_p}")

    finally:
        # Verifica se o arquivo temporário foi alterado
        final_sha = _compute_file_sha256(temp_db_path)
        final_mtime = os.path.getmtime(temp_db_path)
        if initial_sha != final_sha or initial_mtime != final_mtime:
            print("\nALERTA CRÍTICO DE INTEGRIDADE: O banco temporário foi modificado durante a auditoria!", file=sys.stderr)
            sys.exit(2)

        # Limpa arquivo temporário
        try:
            os.remove(temp_db_path)
        except OSError:
            pass


if __name__ == "__main__":
    main()
