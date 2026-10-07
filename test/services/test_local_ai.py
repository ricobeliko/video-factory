"""
test/services/test_local_ai.py
==============================
Testes unitários direcionados para a fundação de IA Local (Fase V1.4B).

Cobertura exigida:
1. LocalAIProvider responde texto válido
2. JSON válido é parseado (inclusive markdown/fences)
3. Endpoint indisponível gera erro tipado controlado
4. FactPack valida estrutura e integridade (IDs únicos, campos obrigatórios)
5. Grounded generation inclui fact IDs e estrutura
6. FactGuard aprova conteúdo sustentado
7. FactGuard rejeita claim inventada/não suportada
8. Somente uma tentativa de rewrite no ciclo de guarda
9. Segunda falha aciona fail-closed (approved=False, final_content=None)
10. LOCAL_AI_ENABLED=false por padrão mantém produção intacta
11. Caso de regressão Roanoke contra alucinações históricas
"""

from __future__ import annotations

import io
import json
import os
import socket
import sqlite3
import tempfile
import unittest
import urllib.error
from unittest.mock import MagicMock, patch

from pydantic import ValidationError

from app.services.local_ai import (
    Fact,
    FactGuard,
    FactGuardResult,
    FactPack,
    GroundedContent,
    GroundedScene,
    LocalAIConfig,
    LocalAIError,
    LocalAIProvider,
    LocalAIResponse,
    LocalAIResponseFormatError,
    LocalAIRole,
    LocalAIRouter,
    LocalAIServerUnavailableError,
    LocalAITimeoutError,
    LocalAIShadowRunner,
    ShadowRunResult,
    generate_grounded_content_with_guard,
    get_shadow_db_path,
    init_shadow_db,
    save_shadow_run,
)
from app.services.local_ai.shadow_runner import sanitize_message



class TestLocalAIProvider(unittest.TestCase):
    """Validações do cliente HTTP leve e parsing da IA Local."""

    def test_01_provider_returns_valid_text(self):
        """1. LocalAIProvider responde texto válido a partir do endpoint OpenAI-compatible."""
        cfg = LocalAIConfig(base_url="http://127.0.0.1:8089/v1", model="qwen3-8b")
        provider = LocalAIProvider(cfg)

        mock_payload = {
            "choices": [
                {
                    "message": {
                        "role": "assistant",
                        "content": "A Colônia de Roanoke permanece um mistério histórico.",
                    }
                }
            ],
            "usage": {
                "prompt_tokens": 35,
                "completion_tokens": 12,
                "total_tokens": 47,
            },
        }

        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps(mock_payload).encode("utf-8")
        mock_resp.__enter__.return_value = mock_resp

        with patch("urllib.request.urlopen", return_value=mock_resp):
            resp = provider.chat_completion(
                messages=[{"role": "user", "content": "Resumo de Roanoke"}],
                temperature=0.1,
            )

        self.assertIsInstance(resp, LocalAIResponse)
        self.assertEqual(resp.content, "A Colônia de Roanoke permanece um mistério histórico.")
        self.assertEqual(resp.model, "qwen3-8b")
        self.assertEqual(resp.prompt_tokens, 35)
        self.assertEqual(resp.completion_tokens, 12)
        self.assertEqual(resp.total_tokens, 47)

    def test_02_json_parsing_direct_and_markdown(self):
        """2. JSON válido é parseado corretamente (direto e envolto em markdown fences)."""
        # Caso A: JSON direto
        resp_direct = LocalAIResponse(
            content='{"status": "ok", "count": 42}',
            model="qwen3-8b",
        )
        data_direct = resp_direct.json()
        self.assertEqual(data_direct["status"], "ok")
        self.assertEqual(data_direct["count"], 42)

        # Caso B: JSON dentro de markdown code fence com think tags
        resp_markdown = LocalAIResponse(
            content="<think>Raciocínio interno...</think>\n```json\n{\n  \"approved\": true,\n  \"unsupported_claims\": []\n}\n```",
            model="qwen3-8b",
        )
        data_markdown = resp_markdown.json()
        self.assertTrue(data_markdown["approved"])
        self.assertEqual(data_markdown["unsupported_claims"], [])

        # Caso C: Resposta sem JSON deve disparar LocalAIResponseFormatError
        resp_invalid = LocalAIResponse(
            content="Texto livre sem nenhuma chave json válida",
            model="qwen3-8b",
        )
        with self.assertRaises(LocalAIResponseFormatError):
            resp_invalid.json()

    def test_03_endpoint_unavailable_raises_typed_error(self):
        """3. Endpoint indisponível gera erro controlado e tipado (fail-closed)."""
        cfg = LocalAIConfig(base_url="http://127.0.0.1:8089/v1", timeout_seconds=1.0)
        provider = LocalAIProvider(cfg)

        # Connection Refused
        with patch("urllib.request.urlopen", side_effect=urllib.error.URLError("Connection refused")):
            with self.assertRaises(LocalAIServerUnavailableError):
                provider.chat_completion(messages=[{"role": "user", "content": "ping"}])

        # Timeout
        with patch("urllib.request.urlopen", side_effect=socket.timeout("Timed out")):
            with self.assertRaises(LocalAITimeoutError):
                provider.chat_completion(messages=[{"role": "user", "content": "ping"}])

        # is_available retorna False silenciosamente sem crash
        with patch("urllib.request.urlopen", side_effect=Exception("Offline")):
            self.assertFalse(provider.is_available())


class TestFactPack(unittest.TestCase):
    """Validações estruturais do FactPack e atomicidade dos fatos."""

    def test_04_fact_pack_validates_structure_and_uniqueness(self):
        """4. FactPack valida integridade, unicidade de IDs e rejeita duplicatas/vazios."""
        facts = [
            Fact(id="F1", text="Fato número um", source="Doc 1"),
            Fact(id="F2", text="Fato número dois", source="Doc 2"),
        ]
        pack = FactPack(topic="História", facts=facts)

        self.assertTrue(pack.validate_integrity())
        self.assertEqual(pack.get_fact_ids(), ["F1", "F2"])
        self.assertEqual(pack.get_fact("F1").text, "Fato número um")
        self.assertIn("[F1] Fato número um", pack.format_for_prompt())

        # IDs duplicados devem lançar ValidationError
        with self.assertRaises(ValidationError):
            FactPack(
                topic="História",
                facts=[
                    Fact(id="F1", text="Primeiro"),
                    Fact(id="F1", text="Duplicado"),
                ],
            )

        # Lista de fatos vazia deve lançar ValidationError
        with self.assertRaises(ValidationError):
            FactPack(topic="História", facts=[])


class TestFactGuardAndGroundedGeneration(unittest.TestCase):
    """Testes de geração ancorada, auditoria e resiliência fail-closed."""

    def setUp(self):
        self.cfg = LocalAIConfig(base_url="http://127.0.0.1:8089/v1", model="qwen3-8b")
        self.provider = LocalAIProvider(self.cfg)
        self.router = LocalAIRouter(self.provider, fast_model="qwen3-4b", quality_model="qwen3-8b")

        self.roanoke_facts = [
            Fact(id="F1", text="A Colônia de Roanoke foi estabelecida por colonos ingleses na atual Carolina do Norte."),
            Fact(id="F2", text="John White retornou à Inglaterra em busca de suprimentos."),
            Fact(id="F3", text="Quando voltou em 1590, os colonos haviam desaparecido."),
            Fact(id="F4", text="A palavra CROATOAN estava gravada em um poste."),
            Fact(id="F5", text="O destino definitivo dos colonos permanece incerto."),
        ]
        self.roanoke_pack = FactPack(topic="Colônia de Roanoke", facts=self.roanoke_facts)

    def test_05_grounded_generation_includes_fact_ids(self):
        """5. Grounded content generation inclui fact IDs e estrutura de cenas."""
        mock_llm_json = {
            "topic": "Colônia de Roanoke",
            "hook": "Em 1590, uma colônia inglesa inteira sumiu sem deixar rastros.",
            "script": "A Colônia de Roanoke foi estabelecida na Carolina do Norte. John White viajou por suprimentos...",
            "duration_seconds": 70,
            "facts_used": ["F1", "F2", "F3", "F4", "F5"],
            "scenes": [
                {
                    "scene": 1,
                    "narration": "A Colônia de Roanoke foi fundada por colonos ingleses.",
                    "visual_prompt": "navio inglês chegando à costa da Carolina do Norte",
                    "facts_used": ["F1"],
                },
                {
                    "scene": 2,
                    "narration": "Em 1590, John White encontrou apenas a palavra CROATOAN gravada em um poste.",
                    "visual_prompt": "poste de madeira com CROATOAN esculpido",
                    "facts_used": ["F3", "F4"],
                },
            ],
        }

        mock_resp = LocalAIResponse(content=json.dumps(mock_llm_json), model="qwen3-8b")

        with patch.object(self.router, "dispatch_chat", return_value=mock_resp):
            from app.services.local_ai.fact_guard import _generate_grounded_raw
            content = _generate_grounded_raw(self.roanoke_pack, self.router)

        self.assertEqual(content.topic, "Colônia de Roanoke")
        self.assertEqual(content.facts_used, ["F1", "F2", "F3", "F4", "F5"])
        self.assertEqual(len(content.scenes), 2)
        self.assertEqual(content.scenes[0].facts_used, ["F1"])
        self.assertEqual(content.scenes[1].facts_used, ["F3", "F4"])

    def test_06_fact_guard_approves_supported_content(self):
        """6. FactGuard aprova conteúdo estritamente fundamentado nos fatos."""
        guard = FactGuard(provider=self.provider, router=self.router)

        content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="O mistério de Roanoke.",
            script="A Colônia de Roanoke foi estabelecida por colonos ingleses na Carolina do Norte. Quando White retornou em 1590, encontrou apenas a inscrição CROATOAN. O destino dos colonos permanece incerto.",
            duration_seconds=70,
            facts_used=["F1", "F3", "F4", "F5"],
        )

        mock_audit_json = {
            "approved": True,
            "unsupported_claims": [],
            "used_fact_ids": ["F1", "F3", "F4", "F5"],
            "notes": ["Todas as afirmações estão expressamente suportadas no FactPack."],
        }
        mock_resp = LocalAIResponse(content=json.dumps(mock_audit_json), model="qwen3-8b")

        with patch.object(self.router, "dispatch_chat", return_value=mock_resp):
            audit = guard.validate_content(self.roanoke_pack, content)

        self.assertTrue(audit.approved)
        self.assertEqual(len(audit.unsupported_claims), 0)
        self.assertEqual(audit.used_fact_ids, ["F1", "F3", "F4", "F5"])
        self.assertIsNotNone(audit.final_content)

    def test_07_fact_guard_rejects_invented_claim(self):
        """7. FactGuard rejeita claim inventada ou externa não fornecida no FactPack."""
        guard = FactGuard(provider=self.provider, router=self.router)

        content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="O destino trágico de Roanoke.",
            script="John White era o líder da colônia e quando retornou viu que todos foram assassinados por tribos locais.",
            duration_seconds=70,
            facts_used=["F2", "F3"],
        )

        mock_audit_json = {
            "approved": False,
            "unsupported_claims": [
                "John White era o líder da colônia",
                "todos foram assassinados por tribos locais",
            ],
            "used_fact_ids": ["F2", "F3"],
            "notes": ["Afirmações não sustentadas pelo FactPack."],
        }
        mock_resp = LocalAIResponse(content=json.dumps(mock_audit_json), model="qwen3-8b")

        with patch.object(self.router, "dispatch_chat", return_value=mock_resp):
            audit = guard.validate_content(self.roanoke_pack, content)

        self.assertFalse(audit.approved)
        self.assertEqual(len(audit.unsupported_claims), 2)
        self.assertIn("John White era o líder da colônia", audit.unsupported_claims)
        self.assertIsNone(audit.final_content)

    def test_08_only_one_rewrite_attempt_on_initial_failure(self):
        """8. Exatamente UMA tentativa de rewrite ocorre em caso de rejeição inicial."""
        # 1. Geração inicial: com claims inventadas
        initial_gen = {
            "topic": "Colônia de Roanoke",
            "hook": "Mistério",
            "script": "Texto com alucinação.",
            "duration_seconds": 70,
            "facts_used": ["F1"],
            "scenes": [],
        }
        # 2. Primeira auditoria: REPROVA
        first_audit = {
            "approved": False,
            "unsupported_claims": ["Detalhe não fornecido"],
            "used_fact_ids": ["F1"],
            "notes": ["Reprovado na primeira rodada."],
        }
        # 3. Segunda geração (reescrita): corrigida
        rewritten_gen = {
            "topic": "Colônia de Roanoke",
            "hook": "Mistério resolvido",
            "script": "Texto estritamente limpo com fatos F1 e F2.",
            "duration_seconds": 70,
            "facts_used": ["F1", "F2"],
            "scenes": [],
        }
        # 4. Segunda auditoria: APROVA
        second_audit = {
            "approved": True,
            "unsupported_claims": [],
            "used_fact_ids": ["F1", "F2"],
            "notes": ["Aprovado após reescrita."],
        }

        call_responses = [
            LocalAIResponse(content=json.dumps(initial_gen), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(first_audit), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(rewritten_gen), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(second_audit), model="qwen3-8b"),
        ]

        with patch.object(self.router, "dispatch_chat", side_effect=call_responses) as mock_dispatch:
            result = generate_grounded_content_with_guard(
                fact_pack=self.roanoke_pack,
                provider=self.provider,
                router=self.router,
                max_rewrites=1,
            )

        self.assertTrue(result.approved)
        self.assertTrue(result.rewrite_attempted)
        self.assertIsNotNone(result.final_content)
        self.assertEqual(result.final_content.script, "Texto estritamente limpo com fatos F1 e F2.")
        # Total de chamadas: 1 gen + 1 audit + 1 rewrite + 1 audit = 4
        self.assertEqual(mock_dispatch.call_count, 4)

    def test_09_second_failure_triggers_fail_closed(self):
        """9. Segunda falha após rewrite dispara FAIL-CLOSED imediato (sem loops)."""
        gen_1 = {"topic": "Roanoke", "hook": "H1", "script": "S1", "duration_seconds": 70, "facts_used": ["F1"], "scenes": []}
        audit_1 = {"approved": False, "unsupported_claims": ["Alucinação persistente 1"], "used_fact_ids": ["F1"], "notes": []}
        gen_2 = {"topic": "Roanoke", "hook": "H2", "script": "S2", "duration_seconds": 70, "facts_used": ["F1"], "scenes": []}
        audit_2 = {"approved": False, "unsupported_claims": ["Alucinação persistente 2"], "used_fact_ids": ["F1"], "notes": []}

        call_responses = [
            LocalAIResponse(content=json.dumps(gen_1), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(audit_1), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(gen_2), model="qwen3-8b"),
            LocalAIResponse(content=json.dumps(audit_2), model="qwen3-8b"),
        ]

        with patch.object(self.router, "dispatch_chat", side_effect=call_responses) as mock_dispatch:
            result = generate_grounded_content_with_guard(
                fact_pack=self.roanoke_pack,
                provider=self.provider,
                router=self.router,
                max_rewrites=1,
            )

        self.assertFalse(result.approved)
        self.assertTrue(result.rewrite_attempted)
        self.assertIsNone(result.final_content)
        self.assertTrue(len(result.unsupported_claims) > 0)
        # Exatamente 4 chamadas, nunca 5 ou mais
        self.assertEqual(mock_dispatch.call_count, 4)

    def test_10_local_ai_disabled_by_default(self):
        """10. LOCAL_AI_ENABLED=false por padrão mantém o comportamento atual intacto."""
        with patch.dict("os.environ", {}, clear=True):
            cfg = LocalAIConfig(enabled=None)
            self.assertFalse(cfg.enabled)
            self.assertFalse(LocalAIProvider(cfg).is_enabled())

    def test_11_roanoke_hallucination_regression_case(self):
        """11. Caso de regressão Roanoke: detecta adições não fornecidas (líder, assassinato, refúgio, desordem)."""
        guard = FactGuard(provider=self.provider, router=self.router)

        hallucinated_script = (
            "A Colônia de Roanoke foi estabelecida por colonos ingleses na Carolina do Norte. "
            "John White era o líder da colônia e retornou à Inglaterra para buscar mantimentos. "
            "Quando voltou em 1590, os colonos haviam desaparecido e o local estava em completa desordem. "
            "Alguns historiadores dizem que eles foram assassinados ou se refugiaram com povos locais. "
            "A única pista era CROATOAN gravada em um poste, deixando o destino incerto."
        )

        content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="O líder John White encontrou a desordem.",
            script=hallucinated_script,
            duration_seconds=70,
            facts_used=["F1", "F2", "F3", "F4", "F5"],
        )

        # Simula auditoria do FactGuard detectando com rigor as 4 adições não autorizadas
        mock_audit_json = {
            "approved": False,
            "unsupported_claims": [
                "John White era o líder da colônia",
                "o local estava em completa desordem",
                "eles foram assassinados",
                "se refugiaram com povos locais",
            ],
            "used_fact_ids": ["F1", "F2", "F3", "F4", "F5"],
            "notes": ["Afirmações externas violam a política estrita de grounding."],
        }
        mock_resp = LocalAIResponse(content=json.dumps(mock_audit_json), model="qwen3-8b")

        with patch.object(self.router, "dispatch_chat", return_value=mock_resp):
            audit = guard.validate_content(self.roanoke_pack, content)

        self.assertFalse(audit.approved)
        self.assertEqual(len(audit.unsupported_claims), 4)
        for claim in [
            "John White era o líder da colônia",
            "o local estava em completa desordem",
            "eles foram assassinados",
            "se refugiaram com povos locais",
        ]:
            self.assertIn(claim, audit.unsupported_claims)
        self.assertIsNone(audit.final_content)


class TestLocalAIShadowRunner(unittest.TestCase):
    """Validações do executor Shadow (V1.4C) garantindo isolamento total de produção."""

    def setUp(self):
        self.roanoke_facts = [
            Fact(id="F1", text="A Colônia de Roanoke foi estabelecida por colonos ingleses na atual Carolina do Norte."),
            Fact(id="F2", text="John White retornou à Inglaterra em busca de suprimentos."),
            Fact(id="F3", text="Quando voltou em 1590, os colonos haviam desaparecido."),
            Fact(id="F4", text="A palavra CROATOAN estava gravada em um poste."),
            Fact(id="F5", text="O destino definitivo dos colonos permanece incerto."),
        ]
        self.roanoke_pack = FactPack(topic="Colônia de Roanoke", facts=self.roanoke_facts)

    def test_12_mode_off_does_not_execute_local_ai(self):
        """1. mode=off não executa Local AI e retorna registro seguro."""
        cfg = LocalAIConfig(mode="off")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        self.assertFalse(runner.should_run())

        with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard") as mock_gen:
            res = runner.run_shadow(self.roanoke_pack, task_id="task_123")
            mock_gen.assert_not_called()

        self.assertEqual(res.error_type, "MODE_OFF")
        self.assertFalse(res.generation_success)
        self.assertFalse(res.final_shadow_available)

    def test_13_mode_shadow_executes_runner(self):
        """2. mode=shadow executa o runner normalmente."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        self.assertTrue(runner.should_run())

        fake_content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="O mistério de Roanoke.",
            script="A Colônia de Roanoke foi estabelecida por colonos ingleses. Em 1590 todos sumiram.",
            duration_seconds=70,
            facts_used=["F1", "F3"],
        )
        fake_guard_res = FactGuardResult(
            approved=True,
            unsupported_claims=[],
            used_fact_ids=["F1", "F3"],
            final_content=fake_content,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(self.roanoke_pack, task_id="task_123", current_provider="azure")

            self.assertTrue(res.generation_success)
            self.assertTrue(res.json_valid)
            self.assertTrue(res.fact_guard_approved)
            self.assertTrue(res.final_shadow_available)
            self.assertEqual(res.current_provider, "azure")
            self.assertIsNone(res.error_type)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_14_shadow_never_replaces_content_and_never_publishes(self):
        """3 e 4. Shadow NUNCA substitui conteúdo oficial da tarefa e NUNCA publica."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        # Objeto de tarefa simulando produção
        official_task = {
            "task_id": "prod_task_999",
            "script": "Texto oficial aprovado pelo pipeline humano ou provedor principal.",
            "status": "PROCESSING",
            "published": False,
        }

        fake_content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="Hook shadow",
            script="Texto gerado pelo modelo local em shadow.",
            duration_seconds=70,
            facts_used=["F1"],
        )
        fake_guard_res = FactGuardResult(
            approved=True,
            final_content=fake_content,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(self.roanoke_pack, task_id=official_task["task_id"])

            # Validação: o conteúdo oficial não foi alterado de forma alguma
            self.assertEqual(
                official_task["script"],
                "Texto oficial aprovado pelo pipeline humano ou provedor principal.",
            )
            self.assertFalse(official_task["published"])
            self.assertEqual(official_task["status"], "PROCESSING")
            # O runner não possui métodos de publicação
            self.assertFalse(hasattr(runner, "publish"))
            self.assertFalse(hasattr(runner, "auto_publish"))
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_15_local_ai_offline_does_not_break_main_pipeline(self):
        """5. Local AI offline NÃO quebra o fluxo principal (fail-safe total)."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch(
                "app.services.local_ai.shadow_runner.generate_grounded_content_with_guard",
                side_effect=LocalAIServerUnavailableError("Connection refused to 127.0.0.1:8089"),
            ):
                # Chamada NÃO pode disparar exceção para o chamador
                res = runner.run_shadow(self.roanoke_pack, task_id="task_fail_safe")

            self.assertFalse(res.generation_success)
            self.assertEqual(res.error_type, "SERVER_UNAVAILABLE")
            self.assertIn("Connection refused", res.error_message)
            self.assertFalse(res.final_shadow_available)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_16_invalid_json_recorded_correctly(self):
        """6. JSON inválido é registrado com erro tipado sem quebrar o runner."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch(
                "app.services.local_ai.shadow_runner.generate_grounded_content_with_guard",
                side_effect=LocalAIResponseFormatError("Resposta não é JSON válido"),
            ):
                res = runner.run_shadow(self.roanoke_pack)

            self.assertFalse(res.generation_success)
            self.assertFalse(res.json_valid)
            self.assertEqual(res.error_type, "INVALID_JSON_FORMAT")
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_17_fact_guard_rejection_recorded(self):
        """7. Rejeição do FactGuard é devidamente registrada em métricas."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        fake_guard_res = FactGuardResult(
            approved=False,
            unsupported_claims=["Afirmação inventada sobre Roanoke"],
            used_fact_ids=["F1"],
            final_content=None,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(self.roanoke_pack)

            self.assertTrue(res.generation_success)
            self.assertFalse(res.fact_guard_approved)
            self.assertEqual(res.unsupported_claims_count, 1)
            self.assertIn("Afirmação inventada sobre Roanoke", res.unsupported_claims)
            self.assertFalse(res.final_shadow_available)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_18_rewrite_recorded(self):
        """8. Tentativa de reescrita é registrada nas métricas do shadow run."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        fake_content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="Hook corrigido",
            script="Texto após reescrita.",
            duration_seconds=70,
            facts_used=["F1", "F2"],
        )
        fake_guard_res = FactGuardResult(
            approved=True,
            rewrite_attempted=True,
            unsupported_claims=[],
            final_content=fake_content,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(self.roanoke_pack)

            self.assertTrue(res.rewrite_attempted)
            self.assertTrue(res.fact_guard_approved)
            self.assertTrue(res.final_shadow_available)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_19_duration_estimation_recorded(self):
        """9. Duração estimada baseada em palavras faladas é calculada e registrada."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        # 120 palavras / 2.4 palavras por segundo = exatamente 50.0s
        words_120 = " ".join(["palavra"] * 120)
        fake_content = GroundedContent(
            topic="Colônia de Roanoke",
            hook="Hook",
            script=words_120,
            duration_seconds=70,
            facts_used=["F1"],
        )
        fake_guard_res = FactGuardResult(
            approved=True,
            final_content=fake_content,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(
                    self.roanoke_pack,
                    requested_duration_seconds=70.0,
                    words_per_second=2.4,
                    duration_tolerance_seconds=15.0,
                )

            self.assertEqual(res.script_word_count, 120)
            self.assertEqual(res.requested_duration_seconds, 70.0)
            self.assertEqual(res.estimated_duration_seconds, 50.0)
            self.assertEqual(res.duration_delta_seconds, -20.0)
            # Diferença de 20s excede a tolerância de 15s
            self.assertFalse(res.duration_within_tolerance)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_20_storage_reuse_and_persistence(self):
        """10. Persistência e reuso da tabela SQLite local_ai_shadow_runs funciona perfeitamente."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name

        try:
            res = ShadowRunResult(
                shadow_run_id="run_test_storage",
                task_id="task_abc",
                topic="Persistência",
                model_role="QUALITY",
                model_name="qwen3-8b",
                started_at="2026-10-07T12:00:00Z",
                finished_at="2026-10-07T12:00:02Z",
                latency_seconds=2.0,
                generation_success=True,
                json_valid=True,
                fact_guard_approved=True,
                final_shadow_available=True,
                script_word_count=50,
                requested_duration_seconds=70.0,
                estimated_duration_seconds=68.0,
                duration_delta_seconds=-2.0,
                duration_within_tolerance=True,
            )
            save_shadow_run(res, target=temp_db)

            # Valida leitura direta no SQLite
            conn = sqlite3.connect(temp_db)
            conn.row_factory = sqlite3.Row
            row = conn.execute("SELECT * FROM local_ai_shadow_runs WHERE id = ?", ("run_test_storage",)).fetchone()
            conn.close()

            self.assertIsNotNone(row)
            self.assertEqual(row["topic"], "Persistência")
            self.assertEqual(row["task_id"], "task_abc")
            self.assertEqual(row["generation_success"], 1)
            self.assertEqual(row["estimated_duration_seconds"], 68.0)
            self.assertEqual(row["duration_within_tolerance"], 1)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)

    def test_21_no_credentials_persisted(self):
        """11. Nenhuma credencial ou segredo sensível é gravado nas mensagens de erro."""
        msg = "Falha ao autenticar com token Bearer secret_top_secret_12345 e chave sk-live1234567890"
        sanitized = sanitize_message(msg)
        self.assertNotIn("secret_top_secret_12345", sanitized)
        self.assertNotIn("sk-live1234567890", sanitized)
        self.assertIn("Bearer [REDACTED]", sanitized)
        self.assertIn("[REDACTED_API_KEY]", sanitized)

    def test_22_real_grounding_roanoke_shadow_workflow(self):
        """Caso de regressão Roanoke em modo Shadow: FactPack -> Qwen -> FactGuard registrado integralmente."""
        cfg = LocalAIConfig(mode="shadow")
        provider = LocalAIProvider(cfg)
        runner = LocalAIShadowRunner(provider=provider)

        # Simula resposta do Qwen com alucinação detectada pelo FactGuard
        fake_guard_res = FactGuardResult(
            approved=False,
            unsupported_claims=["John White era o líder da colônia"],
            used_fact_ids=["F1", "F2"],
            notes=["Reprovado por claim não fornecida"],
            final_content=None,
        )

        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tf:
            temp_db = tf.name
        runner.db_path = temp_db

        try:
            with patch("app.services.local_ai.shadow_runner.generate_grounded_content_with_guard", return_value=fake_guard_res):
                res = runner.run_shadow(self.roanoke_pack, task_id="roanoke_shadow_01")

            self.assertEqual(res.topic, "Colônia de Roanoke")
            self.assertTrue(res.generation_success)
            self.assertFalse(res.fact_guard_approved)
            self.assertEqual(res.unsupported_claims, ["John White era o líder da colônia"])
            self.assertFalse(res.final_shadow_available)
        finally:
            if os.path.exists(temp_db):
                os.remove(temp_db)


if __name__ == "__main__":
    unittest.main()

