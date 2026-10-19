"""
app/services/quiz_safety_gate.py
================================
VIDEO FACTORY — QUIZ SAFETY GATE (ISOLADO PARA QUIZ_DILEMMA)

Validador especializado para o formato quiz_dilemma (Q0-R):
1. Aceita abertura, CTA e estrutura narrativa padronizados inerentes ao formato de Quiz.
2. Bloqueia roteiro vazio, conteúdo insuficiente e falhas técnicas de duração.
3. Detecta duplicidade real através da comparação de perguntas, alternativas e sequência
   de dilemas entre vídeos.
4. Garante isolamento estrito do histórico por perfil/canal (cross-channel isolation).
5. Mantém conformidade com o contrato de retorno do pipeline (PASS, REVIEW, BLOCK).
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

from loguru import logger

from app.models import const
from app.services import profile_manager
from app.services.safety_gate import (
    count_spoken_words,
    estimate_duration_seconds,
    get_preset_spec,
    get_safety_assessment,
    get_safety_db_path,
    init_safety_db,
    normalize_topic,
    save_safety_assessment,
    text_similarity,
    token_overlap,
)
from app.utils import utils

# Prefixos clichês/estruturais de abertura de dilema para normalização
_DILEMMA_PREFIXES = [
    "o que voce prefere",
    "qual voce escolhe",
    "qual voce escolheria",
    "decisao dificil",
    "dilema impossivel",
    "escolha rapido",
    "proximo dilema",
    "qual o seu destino",
    "o que voce faria",
]


def is_quiz_dilemma(params: Any = None, narrative_structure: Optional[str] = None) -> bool:
    """Verifica se a tarefa é identificada como quiz_dilemma."""
    struct = (
        narrative_structure
        or getattr(params, "narrative_structure", None)
        or getattr(params, "video_format", None)
        or ""
    )
    return str(struct).strip().lower() in (const.STRUCTURE_QUIZ_DILEMMA, "quiz_dilemma")


def init_quiz_safety_db(db_path: Optional[str] = None) -> None:
    """Cria a tabela quiz_safety_history se não existir, de forma idempotente."""
    init_safety_db(db_path)
    path = get_safety_db_path(db_path)
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS quiz_safety_history (
                task_id TEXT PRIMARY KEY,
                profile_id TEXT NOT NULL,
                channel_id TEXT,
                topic TEXT,
                dilemmas_json TEXT NOT NULL,
                dilemma_count INTEGER NOT NULL,
                safety_status TEXT NOT NULL,
                safety_reasons TEXT,
                checked_at TEXT NOT NULL
            );
            """
        )
        conn.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_quiz_safety_profile_date
            ON quiz_safety_history (profile_id, checked_at);
            """
        )
        conn.commit()
    finally:
        conn.close()


def save_quiz_safety_record(
    task_id: str,
    profile_id: str,
    channel_id: Optional[str],
    topic: str,
    dilemmas: List[Dict[str, Any]],
    safety_status: str,
    safety_reasons: List[str],
    db_path: Optional[str] = None,
    checked_at: Optional[str] = None,
) -> None:
    """Persiste os metadados estruturais do quiz para comparação histórica isolada."""
    init_quiz_safety_db(db_path)
    path = get_safety_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    try:
        now_iso = checked_at or datetime.now(timezone.utc).isoformat()
        reasons_str = "; ".join(safety_reasons) if isinstance(safety_reasons, list) else str(safety_reasons or "")
        clean_pid = str(profile_id or profile_manager.DEFAULT_PROFILE_ID).strip()
        conn.execute(
            """
            INSERT INTO quiz_safety_history (
                task_id, profile_id, channel_id, topic,
                dilemmas_json, dilemma_count, safety_status, safety_reasons, checked_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(task_id) DO UPDATE SET
                profile_id = excluded.profile_id,
                channel_id = excluded.channel_id,
                topic = excluded.topic,
                dilemmas_json = excluded.dilemmas_json,
                dilemma_count = excluded.dilemma_count,
                safety_status = excluded.safety_status,
                safety_reasons = excluded.safety_reasons,
                checked_at = excluded.checked_at;
            """,
            (
                task_id,
                clean_pid,
                channel_id or "",
                topic or "",
                json.dumps(dilemmas, ensure_ascii=False),
                len(dilemmas),
                safety_status,
                reasons_str,
                now_iso,
            ),
        )
        conn.commit()
    finally:
        conn.close()


def clean_dilemma_text(text: str) -> str:
    """Normaliza texto removendo pontuação, diacríticos e fórmulas clichês de abertura."""
    if not text:
        return ""
    norm = normalize_topic(text)
    for pfx in _DILEMMA_PREFIXES:
        if norm.startswith(pfx):
            norm = norm[len(pfx):].strip()
    return norm


def dilemma_similarity(d1: Dict[str, Any], d2: Dict[str, Any]) -> float:
    """
    Calcula a similaridade real entre dois dilemas baseando-se nas alternativas e narração.
    Exige coerência semântica e overlap de tokens para evitar falsos positivos em rótulos curtos.
    """
    t1_top = clean_dilemma_text(d1.get("top_title", ""))
    t1_bot = clean_dilemma_text(d1.get("bottom_title", ""))
    t2_top = clean_dilemma_text(d2.get("top_title", ""))
    t2_bot = clean_dilemma_text(d2.get("bottom_title", ""))

    # Se ambos tiverem alternativas explícitas preenchidas
    if t1_top and t1_bot and t2_top and t2_bot:
        # Match direto (A1 com A2 e B1 com B2)
        sim_t_dir = text_similarity(t1_top, t2_top)
        sim_b_dir = text_similarity(t1_bot, t2_bot)
        tok_t_dir = token_overlap(t1_top, t2_top)
        tok_b_dir = token_overlap(t1_bot, t2_bot)
        if (sim_t_dir >= 0.85 and tok_t_dir >= 0.60) and (sim_b_dir >= 0.85 and tok_b_dir >= 0.60):
            return 1.0

        # Match invertido (A1 com B2 e B1 com A2)
        sim_t_cross = text_similarity(t1_top, t2_bot)
        sim_b_cross = text_similarity(t1_bot, t2_top)
        tok_t_cross = token_overlap(t1_top, t2_bot)
        tok_b_cross = token_overlap(t1_bot, t2_top)
        if (sim_t_cross >= 0.85 and tok_t_cross >= 0.60) and (sim_b_cross >= 0.85 and tok_b_cross >= 0.60):
            return 1.0

    n1 = clean_dilemma_text(d1.get("narration", ""))
    n2 = clean_dilemma_text(d2.get("narration", ""))
    if not n1 or not n2:
        return 0.0
    if n1 == n2:
        return 1.0

    sim_seq = text_similarity(n1, n2)
    sim_jac = token_overlap(n1, n2)
    # Requer consistência entre similaridade sequencial e vocabulário compartilhado
    if sim_seq >= 0.85 and sim_jac >= 0.60:
        return 1.0
    return max(sim_seq * 0.5 + sim_jac * 0.5, sim_seq if sim_jac >= 0.40 else 0.0)


def _load_dilemmas_from_task_artifact(task_id: str) -> List[Dict[str, Any]]:
    """Tenta recuperar dilemas de script.json em storage/tasks/<task_id>/."""
    try:
        task_dir = utils.task_dir(task_id)
        script_json_path = os.path.join(task_dir, "script.json")
        if os.path.isfile(script_json_path):
            with open(script_json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            quiz_data = data.get("quiz_data")
            if isinstance(quiz_data, dict):
                return extract_quiz_dilemmas(quiz_data=quiz_data)
            script_text = data.get("video_script") or data.get("script")
            if script_text:
                return extract_quiz_dilemmas(script=script_text)
    except Exception as exc:
        logger.debug(f"[QuizSafetyGate] Erro ao ler artifact para {task_id}: {exc}")
    return []


def extract_quiz_dilemmas(
    script: Optional[str] = None,
    quiz_data: Optional[Dict[str, Any]] = None,
    task_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Extrai lista estruturada de dilemas a partir de quiz_data ou de script.
    Identifica dilemas de conteúdo e marca opções de fechamento (is_closing_choice).
    """
    dilemmas: List[Dict[str, Any]] = []

    # 1. Extração prioritária a partir da estrutura real raw_quiz
    if quiz_data and isinstance(quiz_data, dict) and quiz_data.get("questions"):
        for q in quiz_data.get("questions", []):
            if not isinstance(q, dict):
                continue
            qid = str(q.get("id") or "").strip()
            header = str(q.get("header") or "").strip()
            narration = str(q.get("narration") or "").strip()
            top = q.get("top") if isinstance(q.get("top"), dict) else {}
            bottom = q.get("bottom") if isinstance(q.get("bottom"), dict) else {}
            top_title = str(top.get("title") or "").strip()
            bottom_title = str(bottom.get("title") or "").strip()
            is_closing = bool(q.get("is_closing_choice") or False)

            # Cues textuais de CTA/encerramento que caracterizam tela de fechamento
            closing_keywords = ("comentários", "inscreva", "pontuação", "desafio", "fechamento", "comente")
            if not is_closing and any(k in header.lower() or k in narration.lower() for k in closing_keywords):
                is_closing = True

            dilemmas.append({
                "id": qid,
                "header": header,
                "narration": narration,
                "top_title": top_title,
                "bottom_title": bottom_title,
                "is_closing": is_closing,
            })
        if dilemmas:
            return dilemmas

    # 2. Fallback: tentar carregar do artifact se task_id fornecido
    if task_id:
        from_art = _load_dilemmas_from_task_artifact(task_id)
        if from_art:
            return from_art

    # 3. Fallback: parse do texto do script formatado "[qid] header narration"
    if script:
        clean = script.strip()
        blocks = re.findall(r"\[([^\]]+)\]\s*(.*?)(?=(?:\[[^\]]+\]|\Z))", clean, re.DOTALL)
        for qid, block in blocks:
            b_text = block.strip()
            lines = [line.strip() for line in b_text.splitlines() if line.strip()]
            header = lines[0] if lines else ""
            narration = " ".join(lines[1:]) if len(lines) > 1 else header

            closing_keywords = ("comentários", "inscreva", "pontuação", "desafio", "fechamento", "comente")
            is_closing = any(k in b_text.lower() for k in closing_keywords)

            # Tenta extrair opções se o padrão "A... Ou B..." estiver presente
            top_title = ""
            bottom_title = ""
            if " ou " in narration.lower():
                parts = re.split(r"\s+[oO]u\s+", narration, maxsplit=1)
                if len(parts) == 2:
                    top_title = parts[0].strip()
                    bottom_title = parts[1].strip()

            dilemmas.append({
                "id": qid,
                "header": header,
                "narration": narration,
                "top_title": top_title,
                "bottom_title": bottom_title,
                "is_closing": is_closing,
            })

    return dilemmas


def get_isolated_quiz_history(
    profile_id: str,
    channel_id: Optional[str] = None,
    exclude_task_id: Optional[str] = None,
    limit: int = 20,
    db_path: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """
    Recupera histórico recente de quiz_dilemma estritamente isolado por perfil e canal.
    Não compara contra conteúdos de outros canais/perfis.
    """
    init_quiz_safety_db(db_path)
    path = get_safety_db_path(db_path)
    conn = sqlite3.connect(path, timeout=15.0)
    conn.row_factory = sqlite3.Row
    try:
        clean_pid = str(profile_id or profile_manager.DEFAULT_PROFILE_ID).strip()
        clean_exclude = str(exclude_task_id or "").strip()
        clean_cid = str(channel_id or "").strip()

        query = """
            SELECT task_id, profile_id, channel_id, topic, dilemmas_json, dilemma_count, safety_status, checked_at
            FROM quiz_safety_history
            WHERE profile_id = ?
              AND safety_status IN ('PASS', 'REVIEW')
        """
        params_list: List[Any] = [clean_pid]
        if clean_exclude:
            query += " AND task_id <> ?"
            params_list.append(clean_exclude)
        if clean_cid:
            query += " AND (channel_id = ? OR channel_id = '' OR channel_id IS NULL)"
            params_list.append(clean_cid)
        query += " ORDER BY checked_at DESC LIMIT ?"
        params_list.append(limit)

        rows = conn.execute(query, params_list).fetchall()
        results: List[Dict[str, Any]] = []
        seen_tids = set()
        for r in rows:
            d = dict(r)
            try:
                d["dilemmas"] = json.loads(d["dilemmas_json"]) if d.get("dilemmas_json") else []
            except Exception:
                d["dilemmas"] = []
            results.append(d)
            seen_tids.add(d["task_id"])

        # Complementa com tarefas de task_profiles do mesmo perfil se a tabela específica tiver poucos registros
        if len(results) < limit:
            try:
                tp_rows = conn.execute(
                    """
                    SELECT ms.task_id, ms.topic, ms.checked_at
                    FROM monetization_safety ms
                    JOIN task_profiles tp ON tp.task_id = ms.task_id
                    WHERE tp.profile_id = ?
                      AND ms.narrative_structure = 'quiz_dilemma'
                      AND ms.safety_status IN ('PASS', 'REVIEW')
                      AND ms.task_id <> ?
                    ORDER BY ms.checked_at DESC
                    LIMIT ?;
                    """,
                    (clean_pid, clean_exclude, (limit - len(results)) * 2),
                ).fetchall()
                for tp_row in tp_rows:
                    tid = tp_row["task_id"]
                    if tid in seen_tids:
                        continue
                    dilemmas = _load_dilemmas_from_task_artifact(tid)
                    if dilemmas:
                        results.append({
                            "task_id": tid,
                            "profile_id": clean_pid,
                            "channel_id": clean_cid,
                            "topic": tp_row["topic"] or "",
                            "dilemmas": dilemmas,
                            "dilemma_count": len(dilemmas),
                            "safety_status": const.SAFETY_STATUS_PASS,
                            "checked_at": tp_row["checked_at"],
                        })
                        seen_tids.add(tid)
                        if len(results) >= limit:
                            break
            except Exception as exc:
                logger.debug(f"[QuizSafetyGate] Erro ao complementar histórico legado: {exc}")

        return results
    finally:
        conn.close()


def evaluate_quiz_script_safety(
    task_id: str,
    topic: str,
    script: str,
    quiz_data: Optional[Dict[str, Any]] = None,
    preset: Optional[str] = None,
    narrative_structure: Optional[str] = const.STRUCTURE_QUIZ_DILEMMA,
    platform: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    history: Optional[List[Dict[str, Any]]] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Avalia a segurança do roteiro de um Quiz (pré-TTS / pré-render).
    
    Regras especializadas:
    - Aceita abertura padronizada ('O que você prefere?'), CTA fixo e repetição do formato quiz_dilemma.
    - Bloqueia roteiro vazio ou com conteúdo insuficiente (< 10 palavras ou sem dilemas).
    - Detecta duplicidade real através da comparação de perguntas, alternativas e sequência de dilemas.
    - Compara o histórico de forma isolada exclusivamente com o mesmo perfil/canal.
    - Retorna status canônico: PASS, REVIEW ou BLOCK.
    """
    preset_spec = get_preset_spec(preset)
    preset_id = preset_spec["id"]
    clean_topic = (topic or "").strip()
    clean_script = (script or "").strip()

    word_count = count_spoken_words(clean_script)
    est_duration = estimate_duration_seconds(word_count)

    reasons: List[str] = []
    status = const.SAFETY_STATUS_PASS

    # 1. Verificação de conteúdo vazio / insuficiente
    if not clean_script or word_count < 10:
        reasons.append("Roteiro vazio ou com conteúdo insuficiente")
        status = const.SAFETY_STATUS_BLOCK
        assessment = {
            "task_id": task_id,
            "topic": clean_topic,
            "preset": preset_id,
            "narrative_structure": const.STRUCTURE_QUIZ_DILEMMA,
            "word_count": word_count,
            "estimated_duration": est_duration,
            "actual_duration": None,
            "safety_status": status,
            "safety_reasons": reasons,
            "hook_text": "[QUIZ_HOOK_STANDARDIZED]",
            "cta_text": "[QUIZ_CTA_STANDARDIZED]",
            "dilemma_count": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        save_safety_assessment(assessment, db_path=db_path)
        return assessment

    # 2. Extração dos dilemas reais da tarefa
    dilemmas = extract_quiz_dilemmas(script=clean_script, quiz_data=quiz_data, task_id=task_id)
    active_dilemmas = [d for d in dilemmas if not d.get("is_closing")]
    if not active_dilemmas:
        active_dilemmas = dilemmas

    if not active_dilemmas:
        reasons.append("Quiz sem dilemas válidos detectados")
        status = const.SAFETY_STATUS_BLOCK
        assessment = {
            "task_id": task_id,
            "topic": clean_topic,
            "preset": preset_id,
            "narrative_structure": const.STRUCTURE_QUIZ_DILEMMA,
            "word_count": word_count,
            "estimated_duration": est_duration,
            "actual_duration": None,
            "safety_status": status,
            "safety_reasons": reasons,
            "hook_text": "[QUIZ_HOOK_STANDARDIZED]",
            "cta_text": "[QUIZ_CTA_STANDARDIZED]",
            "dilemma_count": 0,
            "checked_at": datetime.now(timezone.utc).isoformat(),
        }
        save_safety_assessment(assessment, db_path=db_path)
        return assessment

    # 3. Verificação de duplicidade interna (dentro do próprio vídeo)
    for i in range(len(active_dilemmas)):
        for j in range(i + 1, len(active_dilemmas)):
            sim = dilemma_similarity(active_dilemmas[i], active_dilemmas[j])
            if sim >= 0.80:
                reasons.append(f"Dilema repetido internamente no mesmo vídeo (posições {i+1} e {j+1})")
                status = const.SAFETY_STATUS_BLOCK
                break
        if status == const.SAFETY_STATUS_BLOCK:
            break

    # 4. Verificação de duração técnica preliminar (YouTube Shorts: 15s a 180s)
    clean_plat = str(platform or "").strip().lower()
    if clean_plat == "youtube":
        if est_duration < 15.0 or word_count < 35:
            reasons.append(
                f"Estimativa de duração ({est_duration:.1f}s, {word_count} palavras) muito curta para YouTube Shorts (< 15s)"
            )
            status = const.SAFETY_STATUS_BLOCK
        elif est_duration > 180.0:
            reasons.append(
                f"Estimativa de duração ({est_duration:.1f}s) excede o limite máximo de 180s do YouTube Shorts"
            )
            status = const.SAFETY_STATUS_BLOCK

    # 5. Resolução do perfil/canal para histórico isolado
    clean_pid = str(profile_id or "").strip()
    if not clean_pid and task_id:
        clean_pid = profile_manager.get_task_profile_id(task_id, db_path=db_path)
    if not clean_pid:
        clean_pid = profile_manager.DEFAULT_PROFILE_ID

    # 6. Anti-repetição contra histórico isolado do perfil
    if history is None:
        history = get_isolated_quiz_history(
            profile_id=clean_pid,
            channel_id=channel_id,
            exclude_task_id=task_id,
            limit=20,
            db_path=db_path,
        )

    relevant_history = [h for h in history if h.get("task_id") != task_id]

    for h in relevant_history:
        h_dilemmas = [d for d in h.get("dilemmas", []) if not d.get("is_closing")]
        if not h_dilemmas:
            continue

        h_tid = h.get("task_id", "")

        # A. Overlap de dilemas
        matched_indices: List[Tuple[int, int]] = []
        for i, c in enumerate(active_dilemmas):
            for j, hd in enumerate(h_dilemmas):
                if dilemma_similarity(c, hd) >= 0.80:
                    matched_indices.append((i, j))
                    break

        matched_count = len(matched_indices)
        total_count = len(active_dilemmas)
        overlap_ratio = matched_count / float(total_count) if total_count > 0 else 0.0

        if overlap_ratio >= 0.70:
            reasons.append(
                f"Conteúdo do Quiz altamente duplicado: {matched_count} de {total_count} dilemas ({overlap_ratio:.0%}) são idênticos ao vídeo recente {h_tid}"
            )
            status = const.SAFETY_STATUS_BLOCK
        elif overlap_ratio >= 0.40:
            reasons.append(
                f"Similaridade moderada de dilemas: {matched_count} de {total_count} dilemas ({overlap_ratio:.0%}) repetem o vídeo recente {h_tid}"
            )
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW

        # B. Repetição de sequência de dilemas
        if len(matched_indices) >= 3:
            max_streak = 0
            current_streak = 1
            for k in range(len(matched_indices) - 1):
                c_curr, h_curr = matched_indices[k]
                c_next, h_next = matched_indices[k + 1]
                if c_next == c_curr + 1 and h_next == h_curr + 1:
                    current_streak += 1
                    if current_streak > max_streak:
                        max_streak = current_streak
                else:
                    current_streak = 1

            if max_streak >= 3:
                streak_ratio = max_streak / float(total_count)
                if streak_ratio >= 0.50:
                    reasons.append(
                        f"Sequência idêntica de {max_streak} dilemas consecutivos repetida do vídeo recente {h_tid}"
                    )
                    status = const.SAFETY_STATUS_BLOCK
                else:
                    reasons.append(
                        f"Sequência de {max_streak} dilemas repetida do vídeo recente {h_tid}"
                    )
                    if status != const.SAFETY_STATUS_BLOCK:
                        status = const.SAFETY_STATUS_REVIEW

    # 7. Persistência do resultado
    now_iso = datetime.now(timezone.utc).isoformat()
    assessment = {
        "task_id": task_id,
        "topic": clean_topic,
        "preset": preset_id,
        "narrative_structure": const.STRUCTURE_QUIZ_DILEMMA,
        "word_count": word_count,
        "estimated_duration": est_duration,
        "actual_duration": None,
        "safety_status": status,
        "safety_reasons": reasons,
        "hook_text": "[QUIZ_HOOK_STANDARDIZED]",
        "cta_text": "[QUIZ_CTA_STANDARDIZED]",
        "dilemma_count": len(active_dilemmas),
        "checked_at": now_iso,
    }

    # Salva na tabela canônica monetization_safety para compatibilidade plena
    save_safety_assessment(assessment, db_path=db_path)

    # Salva na tabela especializada quiz_safety_history para isolamento futuro
    save_quiz_safety_record(
        task_id=task_id,
        profile_id=clean_pid,
        channel_id=channel_id,
        topic=clean_topic,
        dilemmas=dilemmas,
        safety_status=status,
        safety_reasons=reasons,
        db_path=db_path,
        checked_at=now_iso,
    )

    return assessment


def evaluate_quiz_duration_safety(
    task_id: str,
    actual_duration: float,
    preset: Optional[str] = None,
    platform: Optional[str] = None,
    profile_id: Optional[str] = None,
    channel_id: Optional[str] = None,
    db_path: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Reavalia a segurança da tarefa pós-render para vídeos do Quiz.
    Preserva a faixa técnica do YouTube Shorts (15s a 180s) e valida conformidade editorial.
    """
    assessment = get_safety_assessment(task_id, db_path=db_path)
    preset_spec = get_preset_spec(preset or (assessment.get("preset") if assessment else None))
    now_iso = datetime.now(timezone.utc).isoformat()

    if not assessment:
        assessment = {
            "task_id": task_id,
            "topic": "",
            "preset": preset_spec["id"],
            "narrative_structure": const.STRUCTURE_QUIZ_DILEMMA,
            "word_count": 0,
            "estimated_duration": actual_duration,
            "actual_duration": actual_duration,
            "safety_status": const.SAFETY_STATUS_PASS,
            "safety_reasons": [],
            "hook_text": "[QUIZ_HOOK_STANDARDIZED]",
            "cta_text": "[QUIZ_CTA_STANDARDIZED]",
            "checked_at": now_iso,
        }

    reasons = list(assessment.get("safety_reasons") or [])
    status = assessment.get("safety_status", const.SAFETY_STATUS_PASS)

    actual_duration = round(float(actual_duration), 1)
    assessment["actual_duration"] = actual_duration

    clean_platform = str(platform or "").strip().lower()
    if not clean_platform:
        clean_platform = "youtube"

    if clean_platform == "youtube":
        if actual_duration < 15.0:
            reasons.append(f"Duração de {actual_duration:.1f}s insuficiente para YouTube Shorts (< 15s)")
            status = const.SAFETY_STATUS_BLOCK
        elif actual_duration > 180.0:
            reasons.append(
                f"Duração de {actual_duration:.1f}s excede o limite oficial de 180s (3 minutos) do YouTube Shorts"
            )
            status = const.SAFETY_STATUS_BLOCK
        elif actual_duration < 60.0 or actual_duration > 65.0:
            reasons.append(
                f"Duração de {actual_duration:.1f}s fora da faixa editorial recomendada para Quiz [60.0s, 65.0s]"
            )
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_REVIEW
        else:
            if status != const.SAFETY_STATUS_BLOCK:
                status = const.SAFETY_STATUS_PASS
    else:
        if actual_duration < 15.0:
            reasons.append(f"Duração de {actual_duration:.1f}s muito curta (< 15s)")
            status = const.SAFETY_STATUS_BLOCK
        elif status != const.SAFETY_STATUS_BLOCK:
            status = const.SAFETY_STATUS_PASS

    assessment["safety_status"] = status
    assessment["safety_reasons"] = reasons
    assessment["checked_at"] = now_iso

    save_safety_assessment(assessment, db_path=db_path)

    # Atualiza registro de histórico se disponível
    clean_pid = str(profile_id or "").strip()
    if not clean_pid and task_id:
        clean_pid = profile_manager.get_task_profile_id(task_id, db_path=db_path)
    if not clean_pid:
        clean_pid = profile_manager.DEFAULT_PROFILE_ID

    dilemmas = _load_dilemmas_from_task_artifact(task_id)
    save_quiz_safety_record(
        task_id=task_id,
        profile_id=clean_pid,
        channel_id=channel_id,
        topic=assessment.get("topic") or "",
        dilemmas=dilemmas,
        safety_status=status,
        safety_reasons=reasons,
        db_path=db_path,
        checked_at=now_iso,
    )

    return assessment


# Aliases para compatibilidade total de interface
evaluate_script_safety = evaluate_quiz_script_safety
evaluate_duration_safety = evaluate_quiz_duration_safety
