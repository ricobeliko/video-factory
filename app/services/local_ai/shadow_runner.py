"""
app/services/local_ai/shadow_runner.py
======================================
Executor em modo Shadow para o Cérebro de IA Local (Fase V1.4C).

Garante que o Local Brain possa ser observado, comparado e homologado
em paralelo ao pipeline de produção com ZERO risco operacional:
- Nunca substitui o conteúdo oficial da tarefa
- Nunca altera estado de produção ou publicação
- Falhas do servidor local não afetam o fluxo principal (fail-safe total)
- Reutiliza storage/SQLite existente (video_factory.db)
- Não armazena nem expõe credenciais ou segredos
"""

from __future__ import annotations

import json
import os
import re
import sqlite3
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Any, Dict, Generator, List, Optional, Union
from uuid import uuid4

from loguru import logger
from pydantic import BaseModel, Field

from app.services.local_ai.fact_guard import (
    FactGuardResult,
    generate_grounded_content_with_guard,
)
from app.services.local_ai.fact_pack import DEFAULT_SAFE_EXPANSION_RATIO, FactPack
from app.services.local_ai.provider import (
    LocalAIConfig,
    LocalAIError,
    LocalAIProvider,
    LocalAIResponseFormatError,
    LocalAIServerUnavailableError,
    LocalAITimeoutError,
)
from app.services.local_ai.router import LocalAIRole, LocalAIRouter
from app.services.safety_gate import count_spoken_words, estimate_duration_seconds
from app.utils import utils


def sanitize_message(msg: str) -> str:
    """Remove potenciais tokens ou segredos de mensagens de erro."""
    if not msg:
        return ""
    # Mascara chaves tipo sk-..., bearer tokens ou hashes sensíveis
    cleaned = re.sub(r"(sk-[a-zA-Z0-9_-]{8,})", "[REDACTED_API_KEY]", msg)
    cleaned = re.sub(r"(Bearer\s+[a-zA-Z0-9_\-\.]{8,})", "Bearer [REDACTED]", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"(key=[a-zA-Z0-9_\-]{8,})", "key=[REDACTED]", cleaned, flags=re.IGNORECASE)
    return cleaned[:500]


class ShadowRunResult(BaseModel):
    """Registro estruturado de observação da execução em modo Shadow."""

    shadow_run_id: str = Field(default_factory=lambda: str(uuid4()), description="Identificador único da corrida shadow")
    task_id: Optional[str] = Field(default=None, description="ID da tarefa no Video Factory")
    profile_id: Optional[str] = Field(default=None, description="Perfil de canal associado")
    topic: str = Field(..., description="Tema ou assunto fornecido")
    model_role: str = Field(default="QUALITY", description="Papel utilizado no LocalAIRouter (ex: QUALITY)")
    model_name: str = Field(default="qwen3-8b", description="Nome do modelo local")

    started_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp de início da execução",
    )
    finished_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat(),
        description="Timestamp de conclusão da execução",
    )
    latency_seconds: float = Field(default=0.0, description="Tempo decorrido de inferência local")

    generation_success: bool = Field(default=False, description="Geração de conteúdo foi bem-sucedida")
    json_valid: bool = Field(default=False, description="Estrutura retornada é JSON estrito válido")

    fact_guard_approved: bool = Field(default=False, description="Conteúdo aprovado pelo FactGuard")
    rewrite_attempted: bool = Field(default=False, description="Tentativa de reescrita acionada")
    unsupported_claims_count: int = Field(default=0, description="Quantidade de afirmações espúrias detectadas")
    unsupported_claims: List[str] = Field(default_factory=list, description="Lista de afirmações não sustentadas")

    final_shadow_available: bool = Field(default=False, description="Conteúdo final válido gerado em shadow")
    current_provider: Optional[str] = Field(default=None, description="Provedor oficial ativo para comparação")

    error_type: Optional[str] = Field(default=None, description="Código tipado de erro se houver")
    error_message: Optional[str] = Field(default=None, description="Mensagem sanitizada de erro")

    # Métricas de comparação & Duração do roteiro (conteúdo aprovado)
    script_length_chars: int = Field(default=0, description="Comprimento em caracteres do roteiro")
    script_word_count: int = Field(default=0, description="Contagem de palavras faladas calculada")
    target_word_count: int = Field(default=0, description="Alvo determinístico de palavras calculado")
    requested_duration_seconds: float = Field(default=70.0, description="Duração solicitada em segundos")
    estimated_duration_seconds: float = Field(default=0.0, description="Duração estimada baseada em palavras faladas")
    duration_delta_seconds: float = Field(default=0.0, description="Diferença: estimada - solicitada")
    duration_within_tolerance: bool = Field(default=False, description="Duração estimada dentro da tolerância esperada")
    cost_comparison: str = Field(default="UNKNOWN", description="Comparação de custo de API evitado")

    # Telemetria do candidato gerado (mesmo se reprovado pelo FactGuard — Fase V1.4D.2)
    candidate_script_word_count: int = Field(default=0, description="Palavras do último candidato gerado (mesmo se reprovado)")
    candidate_estimated_duration_seconds: float = Field(default=0.0, description="Duração estimada do último candidato em segundos")
    candidate_duration_delta_seconds: float = Field(default=0.0, description="Delta de duração do último candidato em segundos")

    # Telemetria de suficiência factual pré-geração (Fase V1.4D.2)
    safe_target_words: int = Field(default=0, description="Capacidade máxima segura de palavras do FactPack")
    recommended_duration_seconds: float = Field(default=0.0, description="Duração recomendada pelo gate de suficiência")
    fact_count: int = Field(default=0, description="Quantidade de fatos no FactPack")
    fact_word_count: int = Field(default=0, description="Total de palavras no texto dos fatos")

    # Telemetria detalhada por estágio e tokens (V1.4D.1)
    generation_latency_seconds: float = Field(default=0.0, description="Latência da etapa de geração em segundos")
    fact_guard_latency_seconds: float = Field(default=0.0, description="Latência da primeira auditoria em segundos")
    rewrite_latency_seconds: float = Field(default=0.0, description="Latência da reescrita em segundos")
    second_guard_latency_seconds: float = Field(default=0.0, description="Latência da segunda auditoria em segundos")
    total_llm_calls: int = Field(default=0, description="Total de chamadas LLM realizadas no fluxo")
    prompt_tokens_total: int = Field(default=0, description="Total de tokens de prompt somados")
    completion_tokens_total: int = Field(default=0, description="Total de tokens de completion somados")
    total_tokens_total: int = Field(default=0, description="Total de tokens somados")
    raw_timings: Dict[str, Any] = Field(default_factory=dict, description="Timings detalhados consolidados")

    # Conteúdo de observação (somente para auditoria analítica interna)
    shadow_content: Optional[Dict[str, Any]] = Field(default=None, description="Cópia observacional do conteúdo shadow")


# ---------------------------------------------------------------------------
# Persistência em SQLite (Reutiliza storage/video_factory.db)
# ---------------------------------------------------------------------------

def get_shadow_db_path(custom_path: Optional[str] = None) -> str:
    """Retorna o caminho canônico do banco SQLite para auditoria shadow."""
    if custom_path:
        return custom_path
    try:
        base = utils.storage_dir(create=True)
        return os.path.join(base, "video_factory.db")
    except Exception:
        return os.path.join(os.getcwd(), "storage", "video_factory.db")


@contextmanager
def shadow_db_session(
    target: Optional[Union[str, sqlite3.Connection]] = None,
) -> Generator[sqlite3.Connection, None, None]:
    """Gerenciador seguro de conexão SQLite com timeout e WAL."""
    if isinstance(target, sqlite3.Connection):
        yield target
    else:
        path = get_shadow_db_path(target)
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        conn = sqlite3.connect(path, timeout=30.0)
        conn.row_factory = sqlite3.Row
        try:
            conn.execute("PRAGMA journal_mode=WAL;")
            conn.execute("PRAGMA busy_timeout=30000;")
            yield conn
            conn.commit()
        finally:
            conn.close()


def init_shadow_db(target: Optional[Union[str, sqlite3.Connection]] = None) -> None:
    """Cria a tabela local_ai_shadow_runs de forma idempotente sem alterar tabelas existentes."""
    with shadow_db_session(target) as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS local_ai_shadow_runs (
                id TEXT PRIMARY KEY,
                task_id TEXT,
                profile_id TEXT,
                topic TEXT NOT NULL,
                model_role TEXT,
                model_name TEXT,
                started_at TEXT NOT NULL,
                finished_at TEXT NOT NULL,
                latency_seconds REAL,
                generation_success INTEGER NOT NULL,
                json_valid INTEGER NOT NULL,
                fact_guard_approved INTEGER NOT NULL,
                rewrite_attempted INTEGER NOT NULL,
                unsupported_claims_count INTEGER NOT NULL,
                unsupported_claims_json TEXT,
                final_shadow_available INTEGER NOT NULL,
                current_provider TEXT,
                error_type TEXT,
                error_message TEXT,
                script_length_chars INTEGER,
                script_word_count INTEGER,
                requested_duration_seconds REAL,
                estimated_duration_seconds REAL,
                duration_delta_seconds REAL,
                duration_within_tolerance INTEGER,
                cost_comparison TEXT,
                target_word_count INTEGER DEFAULT 0,
                generation_latency_seconds REAL DEFAULT 0.0,
                fact_guard_latency_seconds REAL DEFAULT 0.0,
                rewrite_latency_seconds REAL DEFAULT 0.0,
                second_guard_latency_seconds REAL DEFAULT 0.0,
                total_llm_calls INTEGER DEFAULT 0,
                prompt_tokens_total INTEGER DEFAULT 0,
                completion_tokens_total INTEGER DEFAULT 0,
                total_tokens_total INTEGER DEFAULT 0,
                candidate_script_word_count INTEGER DEFAULT 0,
                candidate_estimated_duration_seconds REAL DEFAULT 0.0,
                candidate_duration_delta_seconds REAL DEFAULT 0.0,
                safe_target_words INTEGER DEFAULT 0,
                recommended_duration_seconds REAL DEFAULT 0.0,
                fact_count INTEGER DEFAULT 0,
                fact_word_count INTEGER DEFAULT 0,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_task_id ON local_ai_shadow_runs (task_id);"
        )
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_shadow_created_at ON local_ai_shadow_runs (created_at);"
        )

        # Migração idempotente para bancos existentes sem as novas colunas
        existing_cols = {row[1] for row in conn.execute("PRAGMA table_info(local_ai_shadow_runs);").fetchall()}
        new_cols = [
            ("target_word_count", "INTEGER DEFAULT 0"),
            ("generation_latency_seconds", "REAL DEFAULT 0.0"),
            ("fact_guard_latency_seconds", "REAL DEFAULT 0.0"),
            ("rewrite_latency_seconds", "REAL DEFAULT 0.0"),
            ("second_guard_latency_seconds", "REAL DEFAULT 0.0"),
            ("total_llm_calls", "INTEGER DEFAULT 0"),
            ("prompt_tokens_total", "INTEGER DEFAULT 0"),
            ("completion_tokens_total", "INTEGER DEFAULT 0"),
            ("total_tokens_total", "INTEGER DEFAULT 0"),
            ("candidate_script_word_count", "INTEGER DEFAULT 0"),
            ("candidate_estimated_duration_seconds", "REAL DEFAULT 0.0"),
            ("candidate_duration_delta_seconds", "REAL DEFAULT 0.0"),
            ("safe_target_words", "INTEGER DEFAULT 0"),
            ("recommended_duration_seconds", "REAL DEFAULT 0.0"),
            ("fact_count", "INTEGER DEFAULT 0"),
            ("fact_word_count", "INTEGER DEFAULT 0"),
        ]
        for col_name, col_type in new_cols:
            if col_name not in existing_cols:
                conn.execute(f"ALTER TABLE local_ai_shadow_runs ADD COLUMN {col_name} {col_type};")


def save_shadow_run(result: ShadowRunResult, target: Optional[Union[str, sqlite3.Connection]] = None) -> None:
    """Persiste o registro do experimento shadow no SQLite."""
    init_shadow_db(target)
    with shadow_db_session(target) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO local_ai_shadow_runs (
                id, task_id, profile_id, topic, model_role, model_name,
                started_at, finished_at, latency_seconds,
                generation_success, json_valid, fact_guard_approved, rewrite_attempted,
                unsupported_claims_count, unsupported_claims_json,
                final_shadow_available, current_provider,
                error_type, error_message,
                script_length_chars, script_word_count,
                requested_duration_seconds, estimated_duration_seconds,
                duration_delta_seconds, duration_within_tolerance,
                cost_comparison,
                target_word_count,
                generation_latency_seconds, fact_guard_latency_seconds,
                rewrite_latency_seconds, second_guard_latency_seconds,
                total_llm_calls,
                prompt_tokens_total, completion_tokens_total, total_tokens_total,
                candidate_script_word_count, candidate_estimated_duration_seconds,
                candidate_duration_delta_seconds,
                safe_target_words, recommended_duration_seconds,
                fact_count, fact_word_count
            ) VALUES (
                ?, ?, ?, ?, ?, ?,
                ?, ?, ?,
                ?, ?, ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?, ?,
                ?,
                ?,
                ?, ?,
                ?, ?,
                ?,
                ?, ?, ?,
                ?, ?, ?,
                ?, ?,
                ?, ?
            );
            """,
            (
                result.shadow_run_id,
                result.task_id,
                result.profile_id,
                result.topic,
                result.model_role,
                result.model_name,
                result.started_at,
                result.finished_at,
                result.latency_seconds,
                1 if result.generation_success else 0,
                1 if result.json_valid else 0,
                1 if result.fact_guard_approved else 0,
                1 if result.rewrite_attempted else 0,
                result.unsupported_claims_count,
                json.dumps(result.unsupported_claims, ensure_ascii=False),
                1 if result.final_shadow_available else 0,
                result.current_provider,
                result.error_type,
                result.error_message,
                result.script_length_chars,
                result.script_word_count,
                result.requested_duration_seconds,
                result.estimated_duration_seconds,
                result.duration_delta_seconds,
                1 if result.duration_within_tolerance else 0,
                result.cost_comparison,
                result.target_word_count,
                result.generation_latency_seconds,
                result.fact_guard_latency_seconds,
                result.rewrite_latency_seconds,
                result.second_guard_latency_seconds,
                result.total_llm_calls,
                result.prompt_tokens_total,
                result.completion_tokens_total,
                result.total_tokens_total,
                result.candidate_script_word_count,
                result.candidate_estimated_duration_seconds,
                result.candidate_duration_delta_seconds,
                result.safe_target_words,
                result.recommended_duration_seconds,
                result.fact_count,
                result.fact_word_count,
            ),
        )



# ---------------------------------------------------------------------------
# Shadow Runner Engine
# ---------------------------------------------------------------------------

class LocalAIShadowRunner:
    """
    Executor isolado que roda o Local Brain (Qwen3-8B + FactGuard) em modo de observação.
    Garante que o pipeline de produção nunca seja afetado por falhas ou dados locais.
    """

    def __init__(
        self,
        provider: Optional[LocalAIProvider] = None,
        router: Optional[LocalAIRouter] = None,
        db_path: Optional[str] = None,
        safe_expansion_ratio: float = DEFAULT_SAFE_EXPANSION_RATIO,
    ):
        self.provider = provider or LocalAIProvider()
        # Na V1.4C homologa prioritariamente QUALITY MODEL (qwen3-8b)
        self.router = router or LocalAIRouter(self.provider, quality_model="qwen3-8b")
        self.db_path = db_path
        self.safe_expansion_ratio = safe_expansion_ratio

    def should_run(self) -> bool:
        """Determina se a IA local está configurada para rodar em modo shadow."""
        return self.provider.config.is_shadow()

    def run_shadow(
        self,
        fact_pack: FactPack,
        task_id: Optional[str] = None,
        profile_id: Optional[str] = None,
        current_provider: Optional[str] = None,
        requested_duration_seconds: float = 70.0,
        words_per_second: float = 2.4,
        duration_tolerance_seconds: float = 15.0,
    ) -> ShadowRunResult:
        """
        Executa o pipeline local em modo shadow.
        Totalmente fail-safe: NUNCA levanta exceção para quem chama.
        """
        run_id = str(uuid4())
        started_at = datetime.now(timezone.utc).isoformat()
        t0 = time.time()

        # 1. Se modo for off ou diferente de shadow, registra bypass sem executar
        if not self.should_run():
            finished_at = datetime.now(timezone.utc).isoformat()
            return ShadowRunResult(
                shadow_run_id=run_id,
                task_id=task_id,
                profile_id=profile_id,
                topic=fact_pack.topic,
                model_role=LocalAIRole.QUALITY.value,
                model_name=self.router.get_model_for_role(LocalAIRole.QUALITY),
                started_at=started_at,
                finished_at=finished_at,
                latency_seconds=0.0,
                generation_success=False,
                json_valid=False,
                fact_guard_approved=False,
                final_shadow_available=False,
                current_provider=current_provider,
                error_type="MODE_OFF",
                error_message=f"Local AI mode is '{self.provider.config.mode}', shadow execution skipped.",
                requested_duration_seconds=requested_duration_seconds,
            )

        # 1.5 Gate de Suficiência Factual ANTES de qualquer chamada ao LLM (Fase V1.4D.2)
        sufficiency = fact_pack.evaluate_sufficiency(
            requested_duration_seconds=requested_duration_seconds,
            words_per_second=words_per_second,
            expansion_ratio=self.safe_expansion_ratio,
        )
        if not sufficiency.sufficient:
            logger.warning(
                f"[LocalAIShadow] FactPack insuficiente para {requested_duration_seconds:.1f}s: {sufficiency.reason}"
            )
            finished_at = datetime.now(timezone.utc).isoformat()
            dt = time.time() - t0
            result = ShadowRunResult(
                shadow_run_id=run_id,
                task_id=task_id,
                profile_id=profile_id,
                topic=fact_pack.topic,
                model_role=LocalAIRole.QUALITY.value,
                model_name=self.router.get_model_for_role(LocalAIRole.QUALITY),
                started_at=started_at,
                finished_at=finished_at,
                latency_seconds=round(dt, 3),
                generation_success=False,
                json_valid=False,
                fact_guard_approved=False,
                final_shadow_available=False,
                current_provider=current_provider,
                error_type="FACT_PACK_INSUFFICIENT",
                error_message=sufficiency.reason,
                target_word_count=sufficiency.target_words,
                safe_target_words=sufficiency.safe_target_words,
                requested_duration_seconds=requested_duration_seconds,
                recommended_duration_seconds=sufficiency.recommended_duration_seconds,
                fact_count=sufficiency.fact_count,
                fact_word_count=sufficiency.fact_word_count,
                total_llm_calls=0,
            )
            try:
                save_shadow_run(result, target=self.db_path)
            except Exception as exc:
                logger.error(f"[LocalAIShadow] Falha ao persistir corrida shadow no banco: {exc}")
            return result

        # 2. Execução protegida do Local Brain
        target_model = self.router.get_model_for_role(LocalAIRole.QUALITY)
        error_type: Optional[str] = None
        error_message: Optional[str] = None
        guard_result: Optional[FactGuardResult] = None
        json_valid = False
        generation_success = False

        try:
            logger.info(
                f"[LocalAIShadow] Iniciando execução shadow para tema '{fact_pack.topic}' (task: {task_id})..."
            )
            guard_result = generate_grounded_content_with_guard(
                fact_pack=fact_pack,
                provider=self.provider,
                router=self.router,
                max_rewrites=1,
                target_duration_seconds=int(requested_duration_seconds),
                words_per_second=words_per_second,
                duration_tolerance_seconds=duration_tolerance_seconds,
                safe_expansion_ratio=self.safe_expansion_ratio,
                check_sufficiency=False,  # Já validado pelo gate acima
            )
            generation_success = True
            json_valid = True
        except LocalAIServerUnavailableError as exc:
            error_type = "SERVER_UNAVAILABLE"
            error_message = sanitize_message(str(exc))
            logger.warning(f"[LocalAIShadow] Servidor local de IA indisponível: {error_message}")
        except LocalAITimeoutError as exc:
            error_type = "TIMEOUT"
            error_message = sanitize_message(str(exc))
            logger.warning(f"[LocalAIShadow] Timeout ao consultar IA local: {error_message}")
        except LocalAIResponseFormatError as exc:
            error_type = "INVALID_JSON_FORMAT"
            error_message = sanitize_message(str(exc))
            logger.warning(f"[LocalAIShadow] Resposta da IA local com formato JSON inválido: {error_message}")
        except LocalAIError as exc:
            error_type = "LOCAL_AI_ERROR"
            error_message = sanitize_message(str(exc))
            logger.warning(f"[LocalAIShadow] Erro no provider local: {error_message}")
        except Exception as exc:
            error_type = "UNEXPECTED_ERROR"
            error_message = sanitize_message(str(exc))
            logger.error(f"[LocalAIShadow] Erro inesperado no runner shadow: {error_message}")

        dt = time.time() - t0
        finished_at = datetime.now(timezone.utc).isoformat()

        # 3. Análise das métricas do conteúdo gerado (se disponível)
        script_text = ""
        script_len = 0
        word_count = 0
        est_duration = 0.0
        delta_duration = 0.0
        within_tolerance = False
        shadow_content_dict: Optional[Dict[str, Any]] = None

        if guard_result and guard_result.final_content:
            script_text = guard_result.final_content.script or ""
            script_len = len(script_text)
            word_count = count_spoken_words(script_text)
            est_duration = estimate_duration_seconds(word_count, words_per_second=words_per_second)
            delta_duration = round(est_duration - requested_duration_seconds, 1)
            within_tolerance = abs(delta_duration) <= duration_tolerance_seconds
            shadow_content_dict = guard_result.final_content.model_dump()

        # Telemetria do candidato gerado (mesmo se reprovado pelo FactGuard — Fase V1.4D.2)
        cand_word_count = 0
        cand_est_duration = 0.0
        cand_delta_duration = 0.0
        candidate_obj = getattr(guard_result, "last_candidate_content", None) or (guard_result.final_content if guard_result else None)
        if candidate_obj and candidate_obj.script:
            cand_word_count = count_spoken_words(candidate_obj.script)
            cand_est_duration = estimate_duration_seconds(cand_word_count, words_per_second=words_per_second)
            cand_delta_duration = round(cand_est_duration - requested_duration_seconds, 1)

        # Extração dos resultados do FactGuard e telemetria por estágio
        fact_guard_approved = guard_result.approved if guard_result else False
        rewrite_attempted = guard_result.rewrite_attempted if guard_result else False
        unsupported_claims = guard_result.unsupported_claims if guard_result else []
        final_shadow_available = (
            generation_success
            and fact_guard_approved
            and (guard_result.final_content is not None)
        )

        target_words = int(round(requested_duration_seconds * words_per_second))
        gen_latency = getattr(guard_result, "generation_latency_seconds", 0.0) if guard_result else 0.0
        fg_latency = getattr(guard_result, "fact_guard_latency_seconds", 0.0) if guard_result else 0.0
        rw_latency = getattr(guard_result, "rewrite_latency_seconds", 0.0) if guard_result else 0.0
        sec_guard_latency = getattr(guard_result, "second_guard_latency_seconds", 0.0) if guard_result else 0.0
        llm_calls = getattr(guard_result, "total_llm_calls", 0) if guard_result else 0
        prompt_tokens_tot = getattr(guard_result, "prompt_tokens_total", 0) if guard_result else 0
        comp_tokens_tot = getattr(guard_result, "completion_tokens_total", 0) if guard_result else 0
        total_tokens_tot = getattr(guard_result, "total_tokens_total", 0) if guard_result else 0
        raw_timings_dict = getattr(guard_result, "raw_timings", {}) if guard_result else {}

        result = ShadowRunResult(
            shadow_run_id=run_id,
            task_id=task_id,
            profile_id=profile_id,
            topic=fact_pack.topic,
            model_role=LocalAIRole.QUALITY.value,
            model_name=target_model,
            started_at=started_at,
            finished_at=finished_at,
            latency_seconds=round(dt, 3),
            generation_success=generation_success,
            json_valid=json_valid,
            fact_guard_approved=fact_guard_approved,
            rewrite_attempted=rewrite_attempted,
            unsupported_claims_count=len(unsupported_claims),
            unsupported_claims=unsupported_claims,
            final_shadow_available=final_shadow_available,
            current_provider=current_provider,
            error_type=error_type,
            error_message=error_message,
            script_length_chars=script_len,
            script_word_count=word_count,
            target_word_count=target_words,
            requested_duration_seconds=requested_duration_seconds,
            estimated_duration_seconds=est_duration,
            duration_delta_seconds=delta_duration,
            duration_within_tolerance=within_tolerance,
            candidate_script_word_count=cand_word_count,
            candidate_estimated_duration_seconds=cand_est_duration,
            candidate_duration_delta_seconds=cand_delta_duration,
            safe_target_words=sufficiency.safe_target_words,
            recommended_duration_seconds=sufficiency.recommended_duration_seconds,
            fact_count=sufficiency.fact_count,
            fact_word_count=sufficiency.fact_word_count,
            cost_comparison="UNKNOWN",
            generation_latency_seconds=round(gen_latency, 3),
            fact_guard_latency_seconds=round(fg_latency, 3),
            rewrite_latency_seconds=round(rw_latency, 3),
            second_guard_latency_seconds=round(sec_guard_latency, 3),
            total_llm_calls=llm_calls,
            prompt_tokens_total=prompt_tokens_tot,
            completion_tokens_total=comp_tokens_tot,
            total_tokens_total=total_tokens_tot,
            raw_timings=raw_timings_dict,
            shadow_content=shadow_content_dict,
        )

        # 4. Persistência isolada no SQLite
        try:
            save_shadow_run(result, target=self.db_path)
            logger.debug(f"[LocalAIShadow] Registro shadow {run_id} persistido com sucesso.")
        except Exception as exc:
            logger.error(f"[LocalAIShadow] Falha ao persistir corrida shadow no banco: {exc}")

        return result

