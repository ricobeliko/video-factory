"""Testes direcionados da funcionalidade Pesquisa na Web por Canal (Google Search grounding do Gemini).

Sem chamadas de rede reais: todos os clientes externos são mockados.
"""

from __future__ import annotations

from datetime import datetime
import os
import tempfile
import types as py_types
import unittest
from unittest.mock import MagicMock, patch

from fastapi import Request

from app.config import config
from app.controllers.v2 import operations as v2_ops
from app.models.exception import HttpException
from app.services import (
    autonomous_production,
    autopilot,
    llm,
    operator_console,
    profile_manager,
    scheduler,
    task as tm,
    trend_radar,
)


FACTUAL_RULE_TEXT = (
    "use somente fatos encontrados na pesquisa; se algo não estiver confirmado por fonte, "
    "diga 'segundo relatos' ou omita; nunca apresente rumor como fato confirmado; "
    "nunca invente datas, números, nomes ou imagens"
)


def _dummy_request() -> Request:
    return Request({"type": "http", "method": "PATCH", "path": "/api/v2/channels/test/editorial", "headers": []})


class TestPesquisaWebRoteiro(unittest.TestCase):
    def setUp(self):
        self._orig_app_cfg = dict(config.app)
        self.temp_dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db_path = os.path.join(self.temp_dir.name, "test_web_search.db")
        scheduler.init_db(self.db_path)
        profile_manager.init_profile_db(self.db_path)
        trend_radar.init_trend_db(self.db_path)
        profile_manager.ensure_default_profile(self.db_path)

    def tearDown(self):
        config.app.clear()
        config.app.update(self._orig_app_cfg)
        self.temp_dir.cleanup()

    # ------------------------------------------------------------------
    # (1) web_search=False: sem tools no Gemini e prompt byte a byte idêntico
    # ------------------------------------------------------------------
    def test_1_web_search_false_has_no_tools_and_identical_prompt(self):
        prompt_default = llm.build_script_prompt(
            video_subject="Lançamento de GTA VI",
            language="pt-BR",
            paragraph_number=2,
            monetization_preset="youtube_shorts_original",
            narrative_structure="curiosity_gap",
            topic_brief="Cobertura diária de GTA VI",
        )
        prompt_explicit_false = llm.build_script_prompt(
            video_subject="Lançamento de GTA VI",
            language="pt-BR",
            paragraph_number=2,
            monetization_preset="youtube_shorts_original",
            narrative_structure="curiosity_gap",
            topic_brief="Cobertura diária de GTA VI",
            web_search=False,
        )
        self.assertEqual(prompt_default, prompt_explicit_false)
        self.assertNotIn("Pesquisa na Web", prompt_explicit_false)
        self.assertNotIn(FACTUAL_RULE_TEXT, prompt_explicit_false)

        ideas_default = autopilot.build_ideas_prompt(
            niche="Games",
            count=5,
            language="pt-BR",
            topic_brief="GTA VI",
        )
        ideas_explicit_false = autopilot.build_ideas_prompt(
            niche="Games",
            count=5,
            language="pt-BR",
            topic_brief="GTA VI",
            web_search=False,
        )
        self.assertEqual(ideas_default, ideas_explicit_false)
        self.assertNotIn("Pesquisa na Web ativa", ideas_explicit_false)

        captured_configs = []

        class FakeModels:
            def generate_content(self, **kwargs):
                captured_configs.append(kwargs["config"])
                return py_types.SimpleNamespace(text="Roteiro sem busca")

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-gemini-key-no-leak",
            "gemini_model_name": "gemini-2.5-flash",
            "gemini_base_url": "",
        }
        with patch("google.genai.Client", FakeClient):
            res = llm._generate_response("Prompt simples", app_config=app_cfg, web_search=False)

        self.assertEqual(res, "Roteiro sem busca")
        self.assertEqual(len(captured_configs), 1)
        self.assertIsNone(captured_configs[0].tools)

    # ------------------------------------------------------------------
    # (2) web_search=True: config contém google_search, prompt contém data ISO e regra factual, log registra fontes=N
    # ------------------------------------------------------------------
    def test_2_web_search_true_sends_google_search_tool_date_rule_and_logs_sources(self):
        today_iso = datetime.now().date().isoformat()

        script_prompt = llm.build_script_prompt(
            video_subject="Trailer novo de GTA VI",
            language="pt-BR",
            paragraph_number=1,
            topic_brief="Notícias verificadas sobre GTA VI",
            web_search=True,
        )
        self.assertIn(today_iso, script_prompt)
        self.assertIn(FACTUAL_RULE_TEXT, script_prompt)

        ideas_prompt = autopilot.build_ideas_prompt(
            niche="Games",
            count=5,
            language="pt-BR",
            topic_brief="Notícias recentes sobre GTA VI",
            web_search=True,
        )
        self.assertIn(today_iso, ideas_prompt)
        self.assertIn("notícias e fatos recentes verificáveis", ideas_prompt)
        self.assertIn(FACTUAL_RULE_TEXT, ideas_prompt)

        captured_calls = []

        class FakeModels:
            def generate_content(self, **kwargs):
                captured_calls.append(kwargs)
                fake_chunks = [
                    py_types.SimpleNamespace(web=py_types.SimpleNamespace(uri="https://rockstargames.com/1", title="Fonte Secreta 1")),
                    py_types.SimpleNamespace(web=py_types.SimpleNamespace(uri="https://ign.com/2", title="Fonte Secreta 2")),
                    py_types.SimpleNamespace(web=py_types.SimpleNamespace(uri="https://eurogamer.pt/3", title="Fonte Secreta 3")),
                ]
                gm = py_types.SimpleNamespace(grounding_chunks=fake_chunks)
                cand = py_types.SimpleNamespace(grounding_metadata=gm)
                return py_types.SimpleNamespace(text="1. Data oficial confirmada pela Rockstar", candidates=[cand])

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "SECRET_GEMINI_KEY_XYZ",
            "gemini_model_name": "gemini-2.5-flash",
            "gemini_base_url": "",
        }
        logged_messages: list[str] = []
        sink_id = llm.logger.add(lambda msg: logged_messages.append(str(msg)))
        try:
            with patch("google.genai.Client", FakeClient):
                ideas = autopilot.generate_ideas(
                    niche="Games",
                    count=3,
                    language="pt-BR",
                    app_config=app_cfg,
                    topic_brief="GTA VI",
                    web_search=True,
                )
        finally:
            llm.logger.remove(sink_id)

        self.assertEqual(ideas, ["Data oficial confirmada pela Rockstar"])
        self.assertEqual(len(captured_calls), 1)
        sent_cfg = captured_calls[0]["config"]
        self.assertIsNotNone(sent_cfg.tools)
        self.assertEqual(len(sent_cfg.tools), 1)
        self.assertIsNotNone(sent_cfg.tools[0].google_search)

        joined_logs = "\n".join(logged_messages)
        self.assertIn(
            "[WEB_RESEARCH] ativo=True etapa=ideias provider=gemini modelo=gemini-2.5-flash fontes=3",
            joined_logs,
        )
        # Não loga texto de fontes nem chaves
        self.assertNotIn("Fonte Secreta", joined_logs)
        self.assertNotIn("rockstargames.com", joined_logs)
        self.assertNotIn("SECRET_GEMINI_KEY_XYZ", joined_logs)

    # ------------------------------------------------------------------
    # (3) falha na chamada com busca -> segunda chamada sem busca + warning explícito
    # ------------------------------------------------------------------
    def test_3_web_search_failure_falls_back_once_without_search_and_logs_warning(self):
        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-key-fallback",
            "gemini_model_name": "gemini-2.5-flash",
            "gemini_base_url": "",
        }

        # Caso A: modelo rejeita google_search (erro não transitório 400)
        configs_case_a = []

        class FakeModelsUnsupported:
            def generate_content(self, **kwargs):
                cfg = kwargs["config"]
                configs_case_a.append(cfg)
                if cfg.tools:
                    err = Exception("400 INVALID_ARGUMENT: Search grounding is not supported for this model")
                    err.code = 400
                    raise err
                return py_types.SimpleNamespace(text="Roteiro gerado via fallback sem busca")

        class FakeClientA:
            def __init__(self, **kwargs):
                self.models = FakeModelsUnsupported()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        warnings_a: list[str] = []
        sink_a = llm.logger.add(lambda msg: warnings_a.append(str(msg)), level="WARNING")
        try:
            with patch("google.genai.Client", FakeClientA):
                out_a = llm._generate_response(
                    "Escreva roteiro GTA VI",
                    app_config=app_cfg,
                    web_search=True,
                    web_search_stage="script",
                )
        finally:
            llm.logger.remove(sink_a)

        self.assertEqual(out_a, "Roteiro gerado via fallback sem busca")
        self.assertEqual(len(configs_case_a), 2)
        self.assertIsNotNone(configs_case_a[0].tools)
        self.assertIsNone(configs_case_a[1].tools)
        self.assertTrue(any("[WEB_RESEARCH] fallback sem busca" in w for w in warnings_a))

        # Caso B: chamada com busca retorna resposta vazia -> fallback sem busca
        configs_case_b = []

        class FakeModelsEmptySearch:
            def generate_content(self, **kwargs):
                cfg = kwargs["config"]
                configs_case_b.append(cfg)
                if cfg.tools:
                    return py_types.SimpleNamespace(text="   ")
                return py_types.SimpleNamespace(text="Texto válido sem busca")

        class FakeClientB:
            def __init__(self, **kwargs):
                self.models = FakeModelsEmptySearch()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        warnings_b: list[str] = []
        sink_b = llm.logger.add(lambda msg: warnings_b.append(str(msg)), level="WARNING")
        try:
            with patch("google.genai.Client", FakeClientB):
                out_b = llm._generate_response(
                    "Escreva roteiro GTA VI",
                    app_config=app_cfg,
                    web_search=True,
                    web_search_stage="script",
                )
        finally:
            llm.logger.remove(sink_b)

        self.assertEqual(out_b, "Texto válido sem busca")
        self.assertEqual(len(configs_case_b), 2)
        self.assertIsNotNone(configs_case_b[0].tools)
        self.assertIsNone(configs_case_b[1].tools)
        self.assertTrue(any("[WEB_RESEARCH] fallback sem busca" in w for w in warnings_b))

    # ------------------------------------------------------------------
    # (4) provider não-Gemini com web_search=True: ignora busca, loga aviso 1x e não quebra
    # ------------------------------------------------------------------
    def test_4_non_gemini_provider_ignores_web_search_with_single_warning(self):
        app_cfg = {
            "llm_provider": "openai",
            "openai_api_key": "sk-fake-openai",
            "openai_model_name": "gpt-4o-mini",
            "openai_base_url": "https://api.openai.com/v1",
        }

        fake_completion = llm.ChatCompletion(
            id="chatcmpl-test",
            choices=[
                {
                    "index": 0,
                    "message": {"role": "assistant", "content": "Resposta OpenAI normal"},
                    "finish_reason": "stop",
                }
            ],
            created=1700000000,
            model="gpt-4o-mini",
            object="chat.completion",
        )
        fake_openai_instance = MagicMock()
        fake_openai_instance.chat.completions.create.return_value = fake_completion

        warn_msgs: list[str] = []
        sink_id = llm.logger.add(lambda msg: warn_msgs.append(str(msg)), level="WARNING")
        try:
            with patch.object(llm, "OpenAI", return_value=fake_openai_instance):
                res = llm._generate_response(
                    "Teste OpenAI com web_search",
                    app_config=app_cfg,
                    web_search=True,
                    web_search_stage="script",
                )
        finally:
            llm.logger.remove(sink_id)

        self.assertEqual(res, "Resposta OpenAI normal")
        matching_warns = [w for w in warn_msgs if "[WEB_RESEARCH]" in w and "ignorado" in w]
        self.assertEqual(len(matching_warns), 1)

    # ------------------------------------------------------------------
    # (5) default = False e build_channel_settings_payload expõe o campo
    # ------------------------------------------------------------------
    def test_5_default_is_false_and_build_channel_settings_payload_exposes_field(self):
        ed_default = profile_manager.EditorialSettings()
        self.assertIs(ed_default.web_search, False)

        # JSON legado sem a chave web_search deve carregar como False
        ws_legacy = profile_manager.ChannelWorkspaceSettings.from_json('{"editorial": {"topic_brief": "GTA"}}')
        self.assertIs(ws_legacy.editorial.web_search, False)
        self.assertEqual(ws_legacy.editorial.topic_brief, "GTA")

        payload = v2_ops.build_channel_settings_payload("default", db_path=self.db_path)
        self.assertIn("workspace_settings", payload)
        self.assertIn("editorial", payload["workspace_settings"])
        self.assertIs(payload["workspace_settings"]["editorial"]["web_search"], False)

    # ------------------------------------------------------------------
    # (6) flag do perfil chega a generate_script e a generate_ideas
    # ------------------------------------------------------------------
    def test_6_profile_flag_propagates_to_generate_script_and_generate_ideas(self):
        onboard = profile_manager.onboard_channel_workspace(
            name="Dose Diária de GTA VI",
            niche="games_gta",
            topic_brief="Notícias diárias verificadas sobre GTA VI",
            video_format="traditional",
            autonomous_enabled=False,
            require_destination=False,
            db_path=self.db_path,
        )
        pid = onboard["profile_id"]

        # Define voz pt-BR válida e habilita web_search no perfil
        ws = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        ws.voice.voice_name = "pt-BR-AntonioNeural"
        ws.editorial.web_search = True
        profile_manager.update_profile_settings(pid, ws, db_path=self.db_path)

        params = autonomous_production.build_autonomous_video_params(
            topic="Data e novidades de GTA VI",
            profile_id=pid,
            db_path=self.db_path,
        )
        self.assertTrue(params.web_search)
        self.assertEqual(params.topic_brief, "Notícias diárias verificadas sobre GTA VI")

        # (6a) task.generate_script repassa web_search=True para llm.generate_script
        with patch.object(tm.llm, "generate_script", return_value="Roteiro verificado") as mock_gen_script:
            out_script = tm.generate_script("task-gta-01", params)
        self.assertEqual(out_script, "Roteiro verificado")
        self.assertIs(mock_gen_script.call_args.kwargs["web_search"], True)
        self.assertEqual(mock_gen_script.call_args.kwargs["topic_brief"], "Notícias diárias verificadas sobre GTA VI")

        # (6b) discover_candidate_topic repassa web_search=True para autopilot.generate_ideas
        with patch.object(autopilot, "generate_ideas", return_value=["Novo detalhe oficial de GTA VI"]) as mock_gen_ideas:
            cand = autonomous_production.discover_candidate_topic(
                niche=params.niche,
                language=params.video_language,
                db_path=self.db_path,
                topic_brief=params.topic_brief,
                web_search=params.web_search,
            )
        self.assertIsNotNone(cand)
        self.assertEqual(cand["topic"], "Novo detalhe oficial de GTA VI")
        self.assertIs(mock_gen_ideas.call_args.kwargs["web_search"], True)
        self.assertEqual(mock_gen_ideas.call_args.kwargs["topic_brief"], "Notícias diárias verificadas sobre GTA VI")

    # ------------------------------------------------------------------
    # (7) endpoint PATCH /channels/{id}/editorial grava só web_search e preserva topic_brief e demais campos
    # ------------------------------------------------------------------
    def test_7_editorial_patch_endpoint_updates_only_web_search_and_preserves_topic_brief(self):
        onboard = profile_manager.onboard_channel_workspace(
            name="Canal GTA Notícias",
            niche="games",
            topic_brief="Cobertura factual do lançamento de GTA VI em 19/11/2026",
            video_format="traditional",
            autonomous_enabled=False,
            require_destination=False,
            db_path=self.db_path,
        )
        pid = onboard["profile_id"]

        before_ws = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        before_ws.editorial.narrative_structure = "curiosity_gap"
        profile_manager.update_profile_settings(pid, before_ws, db_path=self.db_path)

        before_ws = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        self.assertEqual(before_ws.editorial.topic_brief, "Cobertura factual do lançamento de GTA VI em 19/11/2026")
        self.assertEqual(before_ws.editorial.video_format, "traditional")
        self.assertEqual(before_ws.editorial.narrative_structure, "curiosity_gap")
        self.assertIs(before_ws.editorial.web_search, False)

        with (
            patch.object(operator_console, "get_db_path", return_value=self.db_path),
            patch.object(operator_console, "require_primary_instance", return_value=None),
        ):
            resp = v2_ops.update_channel_editorial(
                request=_dummy_request(),
                profile_id=pid,
                payload=v2_ops.UpdateEditorialSettingsRequest(web_search=True),
            )

            self.assertEqual(resp["status"], 200)
            self.assertIs(resp["data"]["web_search"], True)
            self.assertEqual(
                resp["data"]["topic_brief"],
                "Cobertura factual do lançamento de GTA VI em 19/11/2026",
            )

            after_payload = v2_ops.build_channel_settings_payload(pid, db_path=self.db_path)
            ed_after = after_payload["workspace_settings"]["editorial"]
            self.assertIs(ed_after["web_search"], True)
            self.assertEqual(
                ed_after["topic_brief"],
                "Cobertura factual do lançamento de GTA VI em 19/11/2026",
            )
            self.assertEqual(ed_after["video_format"], "traditional")
            self.assertEqual(ed_after["narrative_structure"], "curiosity_gap")
            self.assertEqual(ed_after["content_style"], before_ws.editorial.content_style)

            # Canal Quiz deve rejeitar web_search=True com HTTP 400
            quiz_onboard = profile_manager.onboard_channel_workspace(
                name="Quiz Papel Teste",
                niche="curiosidades",
                topic_brief="Perguntas gerais",
                video_format="quiz_paper",
                autonomous_enabled=False,
                require_destination=False,
                db_path=self.db_path,
            )
            quiz_pid = quiz_onboard["profile_id"]
            with self.assertRaises(HttpException) as ctx:
                v2_ops.update_channel_editorial(
                    request=_dummy_request(),
                    profile_id=quiz_pid,
                    payload=v2_ops.UpdateEditorialSettingsRequest(web_search=True),
                )
            self.assertEqual(ctx.exception.status_code, 400)


if __name__ == "__main__":
    unittest.main()
