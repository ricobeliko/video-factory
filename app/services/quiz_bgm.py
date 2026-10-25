"""
Serviço de Resolução Segura de Trilha de Fundo (BGM) para Quizzes (Missão H - Hotfix V1).

Resolve a trilha de fundo seguindo a ordem estrita de prioridade:
1. Whitelist própria do formato: storage/bgm_whitelist/<format_key>/ (ex: quiz_paper, quiz_dilemma)
   validada contra licencas.csv, com rodízio sem repetição imediata.
2. Whitelist comum: storage/bgm_whitelist/_comum/ com as mesmas regras.
3. Síntese procedural local via ambient_bgm (status SAFE_PROCEDURAL).
4. Sem trilha (path=None, status NONE) caso ocorra qualquer falha.

NUNCA devolve faixas de resource/songs/*.mp3.
"""

from __future__ import annotations

import csv
import os
import uuid
from typing import Any, Dict, List, Optional, Set

from loguru import logger

from app.utils import utils

AUDIO_EXTENSIONS = frozenset({".mp3", ".wav", ".m4a", ".aac", ".ogg", ".flac"})


def _is_legacy_resource_song(file_path: Optional[str]) -> bool:
    """Verifica se o caminho aponta para faixas legadas de resource/songs."""
    if not file_path:
        return False
    norm = str(file_path).replace("\\", "/").lower()
    return "resource/songs" in norm or "/songs/output" in norm


def _select_from_whitelist_dir(dir_path: str) -> Optional[Dict[str, Any]]:
    """
    Busca uma faixa de áudio em uma pasta de whitelist com base em licencas.csv.
    Aplica rodízio simples sem repetir a última faixa utilizada (.last_used).
    Ignora arquivos que não constem no CSV com log de aviso.
    """
    if not os.path.isdir(dir_path):
        return None

    csv_path = os.path.join(dir_path, "licencas.csv")
    if not os.path.isfile(csv_path):
        return None

    allowed_files: Set[str] = set()
    try:
        with open(csv_path, mode="r", encoding="utf-8-sig") as f:
            reader = csv.DictReader(f)
            if reader.fieldnames:
                reader.fieldnames = [fn.strip() for fn in reader.fieldnames if fn]
            for row in reader:
                fname = (row.get("arquivo") or "").strip()
                if fname:
                    allowed_files.add(fname)
    except Exception as exc:
        logger.warning(f"[QUIZ_BGM] Falha ao ler licencas.csv em '{dir_path}': {exc}")
        return None

    if not allowed_files:
        return None

    # Varrer arquivos físicos na pasta
    try:
        dir_entries = os.listdir(dir_path)
    except Exception as exc:
        logger.warning(f"[QUIZ_BGM] Falha ao listar arquivos em '{dir_path}': {exc}")
        return None

    # Arquivos que não estão no CSV são ignorados com aviso
    for entry in dir_entries:
        if entry in (".last_used", "licencas.csv"):
            continue
        ext = os.path.splitext(entry)[1].lower()
        if ext in AUDIO_EXTENSIONS and entry not in allowed_files:
            logger.warning(
                f"[QUIZ_BGM] Arquivo '{entry}' em '{dir_path}' não consta em licencas.csv e será ignorado."
            )

    # Filtrar apenas arquivos autorizados que existem fisicamente e não estão vazios
    valid_candidates: List[str] = []
    for fname in sorted(allowed_files):
        fpath = os.path.join(dir_path, fname)
        if os.path.isfile(fpath) and os.path.getsize(fpath) > 0:
            if not _is_legacy_resource_song(fpath):
                valid_candidates.append(fname)
            else:
                logger.error(
                    f"[QUIZ_BGM] Bloqueio de segurança: faixa de resource/songs em licencas.csv de '{dir_path}': {fname}"
                )

    if not valid_candidates:
        return None

    # Rodízio simples lendo o .last_used
    last_used_file = os.path.join(dir_path, ".last_used")
    last_used: Optional[str] = None
    if os.path.isfile(last_used_file):
        try:
            with open(last_used_file, "r", encoding="utf-8") as f:
                last_used = f.read().strip()
        except Exception:
            last_used = None

    if len(valid_candidates) > 1 and last_used in valid_candidates:
        next_idx = (valid_candidates.index(last_used) + 1) % len(valid_candidates)
        selected = valid_candidates[next_idx]
    else:
        selected = valid_candidates[0]

    # Atualiza .last_used
    try:
        with open(last_used_file, "w", encoding="utf-8") as f:
            f.write(selected)
    except Exception as exc:
        logger.warning(f"[QUIZ_BGM] Não foi possível atualizar {last_used_file}: {exc}")

    chosen_abs_path = os.path.abspath(os.path.join(dir_path, selected))
    if _is_legacy_resource_song(chosen_abs_path):
        logger.error(f"[QUIZ_BGM] Violação: caminho resolvido pertence a resource/songs: {chosen_abs_path}")
        return None

    return {
        "path": chosen_abs_path,
        "source": "whitelist",
        "provenance_status": "WHITELISTED_MANUAL",
        "track_id": selected,
    }


def resolve_quiz_bgm(
    format_key: str,
    work_dir: str,
    seed: Optional[Any] = None,
    duration_sec: Optional[float] = None,
    mood: str = "energetic",
    base_whitelist_dir: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Resolve a trilha sonora segura para o quiz indicado.

    Retorna um dicionário com:
    - path: caminho absoluto do arquivo de áudio ou None (sem música)
    - source: 'whitelist', 'procedural' ou 'none'
    - provenance_status: 'WHITELISTED_MANUAL', 'SAFE_PROCEDURAL' ou 'NONE'
    - track_id: identificador da faixa ou None
    """
    clean_fmt = str(format_key or "quiz_dilemma").strip().lower()
    if clean_fmt.startswith("video_format_"):
        clean_fmt = clean_fmt.replace("video_format_", "")

    base_dir = base_whitelist_dir or os.path.join(utils.storage_dir(), "bgm_whitelist")

    # 1. Pasta específica do formato (ex: storage/bgm_whitelist/quiz_paper/)
    format_dir = os.path.join(base_dir, clean_fmt)
    selected_format = _select_from_whitelist_dir(format_dir)
    if selected_format:
        logger.info(
            f"[QUIZ_BGM] Faixa selecionada da whitelist do formato '{clean_fmt}': {selected_format['track_id']}"
        )
        return selected_format

    # 2. Pasta comum (storage/bgm_whitelist/_comum/)
    common_dir = os.path.join(base_dir, "_comum")
    selected_common = _select_from_whitelist_dir(common_dir)
    if selected_common:
        logger.info(
            f"[QUIZ_BGM] Faixa selecionada da whitelist comum '_comum': {selected_common['track_id']}"
        )
        return selected_common

    # 3. Faixa procedural local via ambient_bgm
    try:
        from app.services import ambient_bgm

        raw_seed = str(seed or uuid.uuid4().hex[:8])
        clean_seed = raw_seed.replace("/", "_").replace("\\", "_").replace(":", "_")
        target_dir = work_dir or os.path.join(utils.storage_dir(), "temp_quiz")
        os.makedirs(target_dir, exist_ok=True)

        target_dur = float(duration_sec or 65.0)
        if target_dur <= 0:
            target_dur = 65.0

        proc_filename = f"quiz_procedural_{clean_fmt}_{clean_seed}.mp3"
        out_proc_path = os.path.join(target_dir, proc_filename)

        gen_path = ambient_bgm.generate_ambient_bgm(
            output_path=out_proc_path,
            duration=target_dur,
            mood=mood or "energetic",
            seed=seed,
        )

        if gen_path and os.path.isfile(gen_path) and os.path.getsize(gen_path) > 0:
            abs_gen = os.path.abspath(gen_path)
            if not _is_legacy_resource_song(abs_gen):
                logger.info(
                    f"[QUIZ_BGM] Faixa procedural gerada com sucesso para '{clean_fmt}': {proc_filename}"
                )
                return {
                    "path": abs_gen,
                    "source": "procedural",
                    "provenance_status": "SAFE_PROCEDURAL",
                    "track_id": f"procedural_{mood}_{clean_seed}",
                }
            else:
                logger.error("[QUIZ_BGM] Trilha procedural gerada colidiu com resource/songs")
    except Exception as exc:
        logger.warning(f"[QUIZ_BGM] Falha ao sintetizar trilha procedural para '{clean_fmt}': {exc}")

    # 4. Sem música (fallback seguro final)
    logger.info(
        f"[QUIZ_BGM] Nenhuma trilha válida para '{clean_fmt}'. Prosseguindo sem música de fundo (NONE)."
    )
    return {
        "path": None,
        "source": "none",
        "provenance_status": "NONE",
        "track_id": None,
    }
