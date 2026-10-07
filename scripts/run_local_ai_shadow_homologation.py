#!/usr/bin/env python3
"""
scripts/run_local_ai_shadow_homologation.py
============================================
Harness de Homologação Manual do Local Brain em Modo Shadow (Fase V1.4D).

Executa uma bateria padronizada e reproduzível de 10 casos reais cobrindo:
1. História
2. Ciência
3. Espaço
4. Geografia
5. Tecnologia
6. Mistério histórico
7. Curiosidade
8. Fato com poucos dados (sparse facts)
9. Caso com potencial de alucinação (mitos comuns)
10. Caso propositalmente adversarial (indução a especulações externas)

REGRAS:
- Conecta-se a um llama-server real (padrão: http://127.0.0.1:8089/v1).
- NÃO usa mocks.
- NÃO altera banco de produção (usa storage/shadow_homologation.db isolado).
- NÃO publica nem modifica tarefas de produção.
- Avalia conformidade estrita do FactGuard e tolerância da duração estimada.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from pathlib import Path
from typing import Dict, List, Optional, Tuple

# Garante raiz do projeto no path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from app.services.local_ai.fact_pack import Fact, FactPack
from app.services.local_ai.provider import LocalAIConfig, LocalAIProvider
from app.services.local_ai.router import LocalAIRole, LocalAIRouter
from app.services.local_ai.shadow_runner import LocalAIShadowRunner, ShadowRunResult
from app.utils import utils


def build_homologation_cases() -> List[Dict[str, Any]]:
    """Constrói os 10 casos de teste com FactPacks estritos e atômicos."""
    return [
        {
            "id": 1,
            "category": "história",
            "topic": "A Prensa Móvel de Gutenberg",
            "facts": [
                Fact(id="F1", text="Johannes Gutenberg desenvolveu a prensa móvel de tipos na Europa por volta de 1440."),
                Fact(id="F2", text="A Bíblia de Gutenberg foi um dos primeiros grandes livros impressos com a nova técnica."),
                Fact(id="F3", text="O sistema utilizava tipos móveis de liga metálica e tinta à base de óleo."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 2,
            "category": "ciência",
            "topic": "A Descoberta da Penicilina",
            "facts": [
                Fact(id="F1", text="Alexander Fleming descobriu a penicilina em setembro de 1928 no St. Mary's Hospital em Londres."),
                Fact(id="F2", text="A descoberta ocorreu após contaminação acidental de uma placa de cultura pelo fungo Penicillium notatum."),
                Fact(id="F3", text="O fungo produzia uma substância que impedia a proliferação da bactéria Staphylococcus aureus."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 3,
            "category": "espaço",
            "topic": "A Missão Voyager 1",
            "facts": [
                Fact(id="F1", text="A sonda espacial Voyager 1 foi lançada pela NASA em setembro de 1977."),
                Fact(id="F2", text="Em agosto de 2012, ela cruzou a heliopausa e entrou formalmente no espaço interestelar."),
                Fact(id="F3", text="A sonda carrega um disco de ouro com sons e imagens representativos da Terra."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 4,
            "category": "geografia",
            "topic": "A Fossa das Marianas",
            "facts": [
                Fact(id="F1", text="A Fossa das Marianas está situada no Oceano Pacífico ocidental."),
                Fact(id="F2", text="O ponto mais profundo é a Depressão Challenger com cerca de 11.000 metros de profundidade."),
                Fact(id="F3", text="A pressão no fundo atinge mais de mil vezes a pressão atmosférica ao nível do mar."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 5,
            "category": "tecnologia",
            "topic": "O Computador ENIAC",
            "facts": [
                Fact(id="F1", text="O ENIAC foi concluído em 1945 na Universidade da Pensilvânia, nos Estados Unidos."),
                Fact(id="F2", text="O equipamento pesava cerca de 30 toneladas e utilizava mais de 17.000 válvulas termiônicas."),
                Fact(id="F3", text="Ele foi concebido primariamente para calcular tabelas balísticas de artilharia para o Exército."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 6,
            "category": "mistério histórico",
            "topic": "A Colônia de Roanoke",
            "facts": [
                Fact(id="F1", text="A Colônia de Roanoke foi estabelecida por colonos ingleses na costa da atual Carolina do Norte."),
                Fact(id="F2", text="John White retornou à Inglaterra para buscar mantimentos e só conseguiu voltar em 1590."),
                Fact(id="F3", text="Ao chegar em 1590, os colonos haviam desaparecido e a inscrição CROATOAN foi vista em um poste."),
                Fact(id="F4", text="O destino definitivo dos colonos nunca foi comprovado em documentos históricos."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 7,
            "category": "curiosidade",
            "topic": "O Metabolismo da Preguiça",
            "facts": [
                Fact(id="F1", text="As preguiças apresentam uma das taxas metabólicas mais lentas entre os mamíferos terrestres."),
                Fact(id="F2", text="Elas descem ao solo apenas aproximadamente uma vez por semana para defecar."),
                Fact(id="F3", text="A digestão completa de uma refeição folhosa pode levar até trinta dias."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 8,
            "category": "fato com poucos dados",
            "topic": "O Manuscrito de Voynich",
            "facts": [
                Fact(id="F1", text="O Manuscrito de Voynich é um códice ilustrado datado por carbono-14 do início do século XV."),
                Fact(id="F2", text="Ele está redigido em um sistema de escrita e idioma desconhecidos que resistem à decifração."),
            ],
            "requested_duration": 60.0,
        },
        {
            "id": 9,
            "category": "potencial de alucinação",
            "topic": "Visibilidade da Grande Muralha da China",
            "facts": [
                Fact(id="F1", text="A Grande Muralha da China é um conjunto de fortificações construídas no norte da China antiga."),
                Fact(id="F2", text="Astronautas e agências espaciais confirmaram que ela não é visível a olho nu da órbita baixa sem telescópios."),
                Fact(id="F3", text="Sua estrutura foi feita de pedra, terra socada, madeira e tijolos ao longo de várias dinastias."),
            ],
            "requested_duration": 70.0,
        },
        {
            "id": 10,
            "category": "adversarial / contenção factual",
            "topic": "O Desaparecimento do Voo MH370",
            "facts": [
                Fact(id="F1", text="O voo MH370 da Malaysia Airlines desapareceu em 8 de março de 2014 com 239 pessoas."),
                Fact(id="F2", text="A aeronave era um Boeing 777-200ER que fazia a rota de Kuala Lumpur para Pequim."),
                Fact(id="F3", text="Destroços isolados foram localizados anos depois na costa do Oceano Índico ocidental."),
                Fact(id="F4", text="A localização do impacto principal e as causas exatas do desvio permanecem não determinadas."),
            ],
            "requested_duration": 70.0,
        },
    ]


def run_homologation(
    base_url: str = "http://127.0.0.1:8089/v1",
    model: str = "qwen3-8b",
    timeout: float = 300.0,
    db_path: Optional[str] = None,
    case_filter: Optional[int] = None,
    tolerance_seconds: float = 15.0,
    duration: Optional[float] = None,
) -> Tuple[List[ShadowRunResult], str]:
    """Executa a bateria de 10 testes shadow contra o servidor local real."""
    storage_db = db_path or os.path.join(utils.storage_dir(create=True), "shadow_homologation.db")
    print("\n" + "=" * 70)
    print(" VIDEO FACTORY — LOCAL AI SHADOW HOMOLOGATION HARNESS (V1.4D) ")
    print("=" * 70)
    print(f"Endpoint:           {base_url}")
    print(f"Modelo Alvo:        {model}")
    print(f"Timeout por Chamada:{timeout}s (HTTP per-call timeout)")
    print(f"Database Isolado:   {storage_db}")
    print(f"Tolerância Duração: ±{tolerance_seconds}s")
    if case_filter is not None and duration is not None:
        print(f"Duração Override:   {duration:.1f}s (para Caso {case_filter})")
    print("=" * 70 + "\n")

    # Configuração em modo shadow estrito
    cfg = LocalAIConfig(
        mode="shadow",
        base_url=base_url,
        model=model,
        timeout_seconds=timeout,
    )
    provider = LocalAIProvider(cfg)
    router = LocalAIRouter(provider=provider, quality_model=model)
    runner = LocalAIShadowRunner(provider=provider, router=router, db_path=storage_db)

    # Verificação de pré-voo do servidor
    print("[PRE-FLIGHT] Verificando disponibilidade do servidor local de IA...")
    is_online = provider.is_available(timeout=2.0)
    if not is_online:
        print(f"[PRE-FLIGHT WARN] llama-server em '{base_url}' parece offline ou lento.")
        print("                 O harness continuará para registrar a resiliência fail-safe do shadow.\n")
    else:
        print("[PRE-FLIGHT OK] llama-server respondendo normalmente.\n")

    all_cases = build_homologation_cases()
    if case_filter:
        all_cases = [c for c in all_cases if c["id"] == case_filter]

    results: List[ShadowRunResult] = []

    for c in all_cases:
        cid = c["id"]
        cat = c["category"]
        top = c["topic"]
        req_dur = c["requested_duration"]
        if case_filter is not None and duration is not None and cid == case_filter:
            req_dur = float(duration)
        pack = FactPack(topic=top, facts=c["facts"])

        print(f"[{cid:02d}/10] Executando Caso: {top} ({cat.upper()})...")
        t0 = time.time()
        res = runner.run_shadow(
            fact_pack=pack,
            task_id=f"homolog_case_{cid:02d}",
            requested_duration_seconds=req_dur,
            duration_tolerance_seconds=tolerance_seconds,
        )
        elapsed = time.time() - t0

        if res.error_type == "FACT_PACK_INSUFFICIENT":
            status_flag = "FACT_PACK_INSUFFICIENT"
            json_str = "N/A"
            fg_str = "NÃO EXECUTADO"
        elif res.fact_guard_approved:
            status_flag = "PASS"
            json_str = "SIM"
            fg_str = "APROVADO"
        elif res.generation_success:
            status_flag = "FAIL_CLOSED"
            json_str = "SIM" if res.json_valid else "NÃO"
            fg_str = "REPROVADO"
        else:
            status_flag = "ERROR"
            json_str = "SIM" if res.json_valid else "NÃO"
            fg_str = "NÃO EXECUTADO" if not res.generation_success else "REPROVADO"

        dur_flag = "OK" if res.duration_within_tolerance else "DELTA"
        print(
            f"       -> Status: {status_flag} | Latência Total: {res.latency_seconds:.1f}s "
            f"(Gen: {res.generation_latency_seconds:.1f}s, FG: {res.fact_guard_latency_seconds:.1f}s, Rew: {res.rewrite_latency_seconds:.1f}s) | "
            f"Tokens: P={res.prompt_tokens_total} C={res.completion_tokens_total} T={res.total_tokens_total} (Calls: {res.total_llm_calls}) | "
            f"JSON: {json_str} | "
            f"FactGuard: {fg_str} | "
            f"Claims Não Suportadas: {res.unsupported_claims_count} | "
            f"Duração: {res.estimated_duration_seconds:.1f}s/{res.requested_duration_seconds:.1f}s "
            f"(Palavras: {res.script_word_count}/{res.target_word_count}, {dur_flag})"
        )
        if res.candidate_script_word_count > 0 and not res.fact_guard_approved:
            print(
                f"       -> Candidato Reprovado: {res.candidate_script_word_count} palavras | "
                f"Duração estimada: {res.candidate_estimated_duration_seconds:.1f}s (delta: {res.candidate_duration_delta_seconds:.1f}s)"
            )
        if res.error_type:
            print(f"       -> Motivo/Erro: [{res.error_type}] {res.error_message}")
        if res.unsupported_claims:
            print(f"       -> Claims detectadas: {res.unsupported_claims}")

        results.append(res)
        print("-" * 70)

    # Consolidação das Métricas
    total = len(results)
    success = sum(1 for r in results if r.generation_success)
    json_valid = sum(1 for r in results if r.json_valid)
    fg_pass = sum(1 for r in results if r.fact_guard_approved)
    rewrites = sum(1 for r in results if r.rewrite_attempted)
    insufficient = sum(1 for r in results if r.error_type == "FACT_PACK_INSUFFICIENT")
    fail_closed = sum(1 for r in results if (r.generation_success and not r.fact_guard_approved))
    dur_tol = sum(1 for r in results if r.duration_within_tolerance)
    unsupported_total = sum(r.unsupported_claims_count for r in results)
    avg_lat = round(sum(r.latency_seconds for r in results) / max(1, total), 2)

    gen_lat_total = round(sum(r.generation_latency_seconds for r in results), 2)
    fg_lat_total = round(sum(r.fact_guard_latency_seconds for r in results), 2)
    rew_lat_total = round(sum(r.rewrite_latency_seconds for r in results), 2)
    total_llm_calls = sum(r.total_llm_calls for r in results)
    prompt_tokens_total = sum(r.prompt_tokens_total for r in results)
    completion_tokens_total = sum(r.completion_tokens_total for r in results)

    # Cálculo do Veredito Oficial
    case_verdict: Optional[str] = None
    if case_filter is not None:
        verdict = "SINGLE_CASE"
        if total > 0 and all(r.generation_success and r.json_valid and r.fact_guard_approved for r in results):
            case_verdict = "PASS"
        elif total > 0 and any(r.error_type == "FACT_PACK_INSUFFICIENT" for r in results):
            case_verdict = "FACT_PACK_INSUFFICIENT"
        else:
            case_verdict = "FAIL"
    elif total >= 10 and json_valid >= 9 and fg_pass >= 8 and (fail_closed + fg_pass == success):
        verdict = "PASS"
    elif total >= 10 and json_valid >= 7 and fg_pass >= 6:
        verdict = "REVIEW"
    else:
        verdict = "FAIL"

    print("\n" + "=" * 70)
    print(" RELATÓRIO CONSOLIDADO DE HOMOLOGAÇÃO SHADOW                      ")
    print("=" * 70)
    print(f"TOTAL = {total}")
    print(f"SUCCESS = {success}")
    print(f"JSON_VALID = {json_valid}")
    print(f"FACT_GUARD_PASS = {fg_pass}")
    print(f"REWRITES = {rewrites}")
    print(f"FAIL_CLOSED = {fail_closed}")
    print(f"FACT_PACK_INSUFFICIENT = {insufficient}")
    print(f"AVG_LATENCY = {avg_lat}s")
    print(f"GENERATION_LATENCY = {gen_lat_total}s")
    print(f"FACT_GUARD_LATENCY = {fg_lat_total}s")
    print(f"REWRITE_LATENCY = {rew_lat_total}s")
    print(f"TOTAL_LLM_CALLS = {total_llm_calls}")
    print(f"PROMPT_TOKENS_TOTAL = {prompt_tokens_total}")
    print(f"COMPLETION_TOKENS_TOTAL = {completion_tokens_total}")
    print(f"DURATION_WITHIN_TOLERANCE = {dur_tol}")
    print(f"UNSUPPORTED_CLAIMS_TOTAL = {unsupported_total}")
    print("-" * 70)
    print(f"SHADOW_HOMOLOGATION_VERDICT = {verdict}")
    if case_verdict is not None:
        print(f"CASE_VERDICT = {case_verdict}")
    print("=" * 70 + "\n")

    return results, verdict


def main():
    parser = argparse.ArgumentParser(description="MoneyPrinterTurbo - Local AI Shadow Homologation Harness")
    parser.add_argument("--base-url", type=str, default="http://127.0.0.1:8089/v1", help="URL do servidor OpenAI-compatible")
    parser.add_argument("--model", type=str, default="qwen3-8b", help="Nome do modelo configurado no servidor")
    parser.add_argument("--timeout", type=float, default=300.0, help="Tempo limite POR chamada HTTP em segundos (não é timeout total)")
    parser.add_argument("--db-path", type=str, default=None, help="Caminho do SQLite isolado para homologação")
    parser.add_argument("--case", type=int, default=None, help="Executar apenas caso específico (1 a 10)")
    parser.add_argument("--tolerance", type=float, default=15.0, help="Tolerância de duração estimada em segundos (±)")
    parser.add_argument("--duration", type=float, default=None, help="Sobrescrever requested_duration do caso selecionado (--case N)")
    args = parser.parse_args()

    results, verdict = run_homologation(
        base_url=args.base_url,
        model=args.model,
        timeout=args.timeout,
        db_path=args.db_path,
        case_filter=args.case,
        tolerance_seconds=args.tolerance,
        duration=args.duration,
    )

    # Retorna 0 para PASS e REVIEW, ou se SINGLE_CASE tiver sido aprovado
    all_ok = verdict in ("PASS", "REVIEW") or (
        verdict == "SINGLE_CASE" and len(results) > 0 and all(r.generation_success and r.json_valid and r.fact_guard_approved for r in results)
    )
    sys.exit(0 if all_ok else 1)


if __name__ == "__main__":
    main()
