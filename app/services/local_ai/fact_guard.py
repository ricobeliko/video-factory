"""
app/services/local_ai/fact_guard.py
===================================
Fact Guard e Grounded Content Generation (Fase V1.4B).

Responsabilidades:
1. Grounded Content Generation: geração de roteiro e cenas estritamente vinculados aos fatos do FactPack.
2. Fact Guard: auditoria pós-geração para detectar e rejeitar qualquer afirmação externa ou inventada.
3. Política Fail-Closed com no máximo 1 tentativa de reescrita.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from loguru import logger

from app.services.local_ai.fact_pack import FactPack
from app.services.local_ai.provider import LocalAIProvider, LocalAIResponseFormatError
from app.services.local_ai.router import LocalAIRole, LocalAIRouter


class GroundedScene(BaseModel):
    """Representa uma cena com narração e fatos associados."""

    scene: int = Field(..., ge=1, description="Índice da cena")
    narration: str = Field(..., min_length=1, description="Texto narrado da cena")
    visual_prompt: str = Field(default="", description="Prompt descritivo para geração ou busca de vídeo")
    facts_used: List[str] = Field(default_factory=list, description="IDs dos fatos do FactPack utilizados nesta cena")


class GroundedContent(BaseModel):
    """Conteúdo narrativo completo ancorado estritamente em um FactPack."""

    topic: str = Field(..., description="Tema do Short")
    hook: str = Field(..., description="Gancho inicial forte")
    script: str = Field(..., description="Roteiro narrativo completo")
    duration_seconds: int = Field(default=70, description="Duração estimada em segundos")
    facts_used: List[str] = Field(default_factory=list, description="IDs de todos os fatos do FactPack utilizados")
    scenes: List[GroundedScene] = Field(default_factory=list, description="Cenas divididas do vídeo")


class FactGuardResult(BaseModel):
    """Resultado da auditoria de integridade factual do FactGuard."""

    approved: bool = Field(..., description="Indica se o conteúdo foi aprovado sem afirmações espúrias")
    unsupported_claims: List[str] = Field(
        default_factory=list,
        description="Afirmações detectadas no conteúdo que NÃO constam no FactPack",
    )
    used_fact_ids: List[str] = Field(
        default_factory=list,
        description="IDs de fatos do FactPack reconhecidos como presentes",
    )
    notes: List[str] = Field(default_factory=list, description="Observações do auditor")
    rewrite_attempted: bool = Field(default=False, description="Indica se uma tentativa de reescrita foi realizada")
    final_content: Optional[GroundedContent] = Field(
        default=None,
        description="Conteúdo final aprovado (ou None se reprovado)",
    )


class FactGuard:
    """Auditor crítico pós-geração que valida estrita fidelidade ao FactPack."""

    def __init__(self, provider: LocalAIProvider, router: Optional[LocalAIRouter] = None):
        self.provider = provider
        self.router = router or LocalAIRouter(provider)

    def validate_content(
        self,
        fact_pack: FactPack,
        content: GroundedContent,
    ) -> FactGuardResult:
        """
        Audita o conteúdo gerado contra os fatos do FactPack.
        Se qualquer afirmação não estiver suportada pelos fatos, rejeita (approved=False).
        """
        system_prompt = (
            "Você é o FACT GUARD da Video Factory, um auditor de precisão factual implacável.\n"
            "Sua única tarefa é auditar o texto do roteiro contra o FACT PACK fornecido.\n"
            "REGRA DE OURO:\n"
            "Se o roteiro contiver QUALQUER afirmação, detalhe, causa, identidade, profissão, "
            "adjetivo factual ou conclusão que NÃO esteja expressamente sustentada no FACT PACK, "
            "você DEVE listar em 'unsupported_claims' e marcar 'approved': false.\n"
            "Não aceite conhecimento histórico externo prévio nem inferências não enunciadas no FactPack.\n"
            "Retorne SOMENTE um JSON válido com a estrutura:\n"
            "{\n"
            '  "approved": true ou false,\n'
            '  "unsupported_claims": ["afirmação 1", ...],\n'
            '  "used_fact_ids": ["F1", "F2", ...],\n'
            '  "notes": ["observação", ...]\n'
            "}"
        )

        user_prompt = (
            f"/no_think\n"
            f"{fact_pack.format_for_prompt()}\n\n"
            f"--- CONTEÚDO PARA AUDITORIA ---\n"
            f"Tema: {content.topic}\n"
            f"Hook: {content.hook}\n"
            f"Roteiro: {content.script}\n\n"
            f"Analise minuciosamente cada frase. Se alguma claim não estiver textualmente fundamentada no FACT PACK acima, "
            f"rejeite imediatamente."
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt},
        ]

        logger.debug("[FactGuard] Enviando conteúdo para auditoria factual...")
        response = self.router.dispatch_chat(
            role=LocalAIRole.QUALITY,
            messages=messages,
            temperature=0.0,
            max_tokens=384,
        )

        try:
            parsed = response.json()
        except LocalAIResponseFormatError as exc:
            logger.warning(f"[FactGuard] Falha ao parsear JSON da auditoria: {exc}. Fail-closed.")
            return FactGuardResult(
                approved=False,
                unsupported_claims=["Falha estrutural no retorno do FactGuard (resposta não é JSON)."],
                notes=["Fail-closed acionado por erro de formatação."],
            )

        unsupported = parsed.get("unsupported_claims", [])
        if not isinstance(unsupported, list):
            unsupported = [str(unsupported)] if unsupported else []

        approved = bool(parsed.get("approved", False))
        # Se houver claims não suportadas, forçar approved = False
        if unsupported and len(unsupported) > 0:
            approved = False

        used_fact_ids = parsed.get("used_fact_ids", [])
        if not isinstance(used_fact_ids, list):
            used_fact_ids = []

        notes = parsed.get("notes", [])
        if not isinstance(notes, list):
            notes = [str(notes)] if notes else []

        return FactGuardResult(
            approved=approved,
            unsupported_claims=unsupported,
            used_fact_ids=used_fact_ids,
            notes=notes,
            final_content=content if approved else None,
        )


def _generate_grounded_raw(
    fact_pack: FactPack,
    router: LocalAIRouter,
    target_duration_seconds: int = 70,
    rewrite_unsupported: Optional[List[str]] = None,
) -> GroundedContent:
    """Gera o objeto GroundedContent bruto via LLM local."""
    system_prompt = (
        "Você é o roteirista factual da Video Factory.\n"
        "Você deve escrever um roteiro de Short em português brasileiro usando ESTRITAMENTE "
        "e EXCLUSIVAMENTE os fatos presentes no FACT PACK fornecido.\n"
        "É TERMINANTEMENTE PROIBIDO inventar dados, acrescentar detalhes de conhecimento externo ou especular.\n"
        "Retorne SOMENTE um JSON válido com a estrutura:\n"
        "{\n"
        '  "topic": "...",\n'
        '  "hook": "...",\n'
        '  "script": "...",\n'
        f'  "duration_seconds": {target_duration_seconds},\n'
        '  "facts_used": ["F1", ...],\n'
        '  "scenes": [\n'
        '    {"scene": 1, "narration": "...", "visual_prompt": "...", "facts_used": ["F1"]}\n'
        "  ]\n"
        "}"
    )

    prompt_lines = [
        "/no_think",
        fact_pack.format_for_prompt(),
    ]

    if rewrite_unsupported:
        prompt_lines.append(
            "\nATENÇÃO: A versão anterior foi REJEITADA pelo FactGuard por conter afirmações inventadas:\n"
            + "\n".join(f"- {c}" for c in rewrite_unsupported)
            + "\nREESCREVA ELIMINANDO TOTALMENTE essas afirmações e usando apenas os fatos autorizados."
        )

    prompt_lines.append(
        f"\nCrie o roteiro para o Short sobre '{fact_pack.topic}' com duração alvo de {target_duration_seconds} segundos. "
        "Retorne apenas o JSON."
    )

    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": "\n".join(prompt_lines)},
    ]

    response = router.dispatch_chat(
        role=LocalAIRole.QUALITY,
        messages=messages,
        temperature=0.2,
        max_tokens=600,
    )

    data = response.json()
    # Constrói GroundedContent a partir do dicionário
    scenes_raw = data.get("scenes", [])
    scenes = []
    for s in scenes_raw:
        if isinstance(s, dict):
            scenes.append(
                GroundedScene(
                    scene=int(s.get("scene", len(scenes) + 1)),
                    narration=str(s.get("narration", "")),
                    visual_prompt=str(s.get("visual_prompt", "")),
                    facts_used=[str(fid) for fid in s.get("facts_used", [])],
                )
            )

    return GroundedContent(
        topic=str(data.get("topic", fact_pack.topic)),
        hook=str(data.get("hook", "")),
        script=str(data.get("script", "")),
        duration_seconds=int(data.get("duration_seconds", target_duration_seconds)),
        facts_used=[str(fid) for fid in data.get("facts_used", [])],
        scenes=scenes,
    )


def generate_grounded_content_with_guard(
    fact_pack: FactPack,
    provider: LocalAIProvider,
    router: Optional[LocalAIRouter] = None,
    max_rewrites: int = 1,
    target_duration_seconds: int = 70,
) -> FactGuardResult:
    """
    Fluxo completo:
    1. Geração fundamentada no FactPack.
    2. Auditoria FactGuard.
    3. Se reprovada e max_rewrites >= 1: exatamente 1 reescrita e nova auditoria.
    4. Se falhar novamente: FAIL-CLOSED.
    """
    fact_pack.validate_integrity()
    active_router = router or LocalAIRouter(provider)
    guard = FactGuard(provider=provider, router=active_router)

    # 1. Geração inicial
    logger.info(f"[LocalBrain] Gerando conteúdo ancorado para '{fact_pack.topic}'...")
    content = _generate_grounded_raw(
        fact_pack=fact_pack,
        router=active_router,
        target_duration_seconds=target_duration_seconds,
    )

    # 2. Primeira auditoria
    logger.info("[FactGuard] Executando primeira auditoria...")
    audit = guard.validate_content(fact_pack, content)
    if audit.approved and len(audit.unsupported_claims) == 0:
        logger.info("[FactGuard] Conteúdo aprovado na primeira rodada!")
        audit.final_content = content
        return audit

    logger.warning(
        f"[FactGuard] Conteúdo inicial rejeitado. Claims não suportadas: {audit.unsupported_claims}"
    )

    # 3. Tentativa única de reescrita
    if max_rewrites >= 1 and audit.unsupported_claims:
        logger.info("[FactGuard] Executando tentativa única de reescrita...")
        rewritten_content = _generate_grounded_raw(
            fact_pack=fact_pack,
            router=active_router,
            target_duration_seconds=target_duration_seconds,
            rewrite_unsupported=audit.unsupported_claims,
        )

        logger.info("[FactGuard] Auditando conteúdo reescrito...")
        second_audit = guard.validate_content(fact_pack, rewritten_content)
        second_audit.rewrite_attempted = True

        if second_audit.approved and len(second_audit.unsupported_claims) == 0:
            logger.info("[FactGuard] Conteúdo reescrito APROVADO!")
            second_audit.final_content = rewritten_content
            return second_audit

        logger.error(
            f"[FactGuard] Falha persistente na reescrita. Claims não suportadas: {second_audit.unsupported_claims}. FAIL-CLOSED."
        )
        second_audit.approved = False
        second_audit.final_content = None
        return second_audit

    # Reprovado sem reescritas
    audit.final_content = None
    return audit
