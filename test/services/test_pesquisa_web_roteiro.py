"""Testes direcionados da funcionalidade Pesquisa na Web por Canal (Google Search grounding do Gemini).

Sem chamadas de rede reais: todos os clientes externos são mockados.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import os
import tempfile
import types as py_types
import unittest
from unittest.mock import MagicMock, patch

from fastapi import Request

from app.config import config
from app.controllers.v2 import operations as v2_ops
from app.models import const
from app.models.exception import HttpException
from app.services import (
    autonomous_production,
    autopilot,
    llm,
    operator_console,
    profile_manager,
    scheduler,
    state as sm,
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
    # (3) falha na chamada com busca -> levanta WebResearchUnavailableError (NUNCA fallback sem busca)
    # ------------------------------------------------------------------
    def test_3_web_search_failure_raises_unavailable_without_fallback(self):
        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-key-fail-closed",
            "gemini_model_name": "gemini-2.5-flash",
            "gemini_base_url": "",
        }

        # Caso A: modelo rejeita google_search (erro 400) -> 1 chamada, sem fallback sem busca
        configs_case_a = []

        class FakeModelsUnsupported:
            def generate_content(self, **kwargs):
                cfg = kwargs["config"]
                configs_case_a.append(cfg)
                err = Exception("400 INVALID_ARGUMENT: Search grounding is not supported for this model")
                err.code = 400
                raise err

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
            with patch("google.genai.Client", FakeClientA), patch("app.services.llm.time.sleep") as mock_sleep_a:
                with self.assertRaises(llm.WebResearchUnavailableError) as ctx_a:
                    llm._generate_response(
                        "Escreva roteiro GTA VI",
                        app_config=app_cfg,
                        web_search=True,
                        web_search_stage="script",
                    )
        finally:
            llm.logger.remove(sink_a)

        self.assertEqual(len(configs_case_a), 1)
        self.assertIsNotNone(configs_case_a[0].tools)
        mock_sleep_a.assert_not_called()
        self.assertIn("web_research_unavailable", str(ctx_a.exception))
        self.assertTrue(
            any("[WEB_RESEARCH] indisponivel etapa=script motivo=" in w and "video adiado" in w for w in warnings_a)
        )

        # Caso B: chamada com busca retorna resposta vazia -> levanta WebResearchUnavailableError sem fallback
        configs_case_b = []

        class FakeModelsEmptySearch:
            def generate_content(self, **kwargs):
                cfg = kwargs["config"]
                configs_case_b.append(cfg)
                return py_types.SimpleNamespace(text="   ")

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
                with self.assertRaises(llm.WebResearchUnavailableError) as ctx_b:
                    llm._generate_response(
                        "Escreva roteiro GTA VI",
                        app_config=app_cfg,
                        web_search=True,
                        web_search_stage="ideias",
                    )
        finally:
            llm.logger.remove(sink_b)

        self.assertEqual(len(configs_case_b), 1)
        self.assertIsNotNone(configs_case_b[0].tools)
        self.assertEqual(ctx_b.exception.reason, "empty_response")
        self.assertTrue(
            any("[WEB_RESEARCH] indisponivel etapa=ideias motivo=empty_response video adiado" in w for w in warnings_b)
        )

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

    # ------------------------------------------------------------------
    # Falha fechada (v2/pesquisa-web-falha-fechada)
    # (1) 429/RESOURCE_EXHAUSTED com busca falha imediatamente, sem sleep de retry
    # ------------------------------------------------------------------
    def test_8_429_with_web_search_fails_immediately_without_sleep(self):
        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-key-429",
            "gemini_model_name": "gemini-2.5-flash-lite",
            "gemini_base_url": "",
        }
        calls = 0

        class FakeModels429:
            def generate_content(self, **kwargs):
                nonlocal calls
                calls += 1
                err = Exception("429 RESOURCE_EXHAUSTED: Search grounding quota exceeded")
                err.code = 429
                raise err

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels429()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        logs: list[str] = []
        sink_id = llm.logger.add(lambda m: logs.append(str(m)), level="WARNING")
        try:
            with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
                with self.assertRaises(llm.WebResearchUnavailableError) as ctx:
                    llm._generate_response(
                        "Notícias de hoje sobre GTA VI",
                        app_config=app_cfg,
                        web_search=True,
                        web_search_stage="ideias",
                    )
        finally:
            llm.logger.remove(sink_id)

        self.assertEqual(calls, 1)
        mock_sleep.assert_not_called()
        self.assertIn("429", ctx.exception.reason)
        self.assertTrue(
            any("[WEB_RESEARCH] indisponivel etapa=ideias motivo=" in w and "video adiado" in w for w in logs)
        )

    # ------------------------------------------------------------------
    # (2) 503 com busca respeita os retries existentes (5, 15, 45) e depois levanta WebResearchUnavailableError
    # ------------------------------------------------------------------
    def test_9_503_with_web_search_respects_retries_then_raises_unavailable(self):
        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-key-503",
            "gemini_model_name": "gemini-2.5-flash-lite",
            "gemini_base_url": "",
        }
        calls = 0

        class FakeModels503:
            def generate_content(self, **kwargs):
                nonlocal calls
                calls += 1
                err = Exception("503 UNAVAILABLE: Model overloaded")
                err.code = 503
                raise err

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels503()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
            with self.assertRaises(llm.WebResearchUnavailableError):
                llm._generate_response(
                    "Roteiro com busca",
                    app_config=app_cfg,
                    web_search=True,
                    web_search_stage="script",
                )

        # 1 tentativa inicial + 3 retries (5, 15, 45) = 4 chamadas; zero fallback sem busca
        self.assertEqual(calls, 1 + len(llm.GEMINI_RETRY_DELAYS_SECONDS))
        self.assertEqual(
            [c.args[0] for c in mock_sleep.call_args_list],
            list(llm.GEMINI_RETRY_DELAYS_SECONDS),
        )

    # ------------------------------------------------------------------
    # (3) Regressão: chamada SEM busca com 429 mantém os retries atuais
    # ------------------------------------------------------------------
    def test_10_429_without_web_search_preserves_existing_retries(self):
        app_cfg = {
            "llm_provider": "gemini",
            "gemini_api_key": "fake-key-no-search-429",
            "gemini_model_name": "gemini-2.5-flash",
            "gemini_base_url": "",
        }
        calls = 0

        class FakeModels429Recover:
            def generate_content(self, **kwargs):
                nonlocal calls
                calls += 1
                if calls == 1:
                    err = Exception("429 RESOURCE_EXHAUSTED: Rate limit")
                    err.code = 429
                    raise err
                return py_types.SimpleNamespace(text="Recuperado sem busca")

        class FakeClient:
            def __init__(self, **kwargs):
                self.models = FakeModels429Recover()

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc_val, exc_tb):
                return False

        with patch("google.genai.Client", FakeClient), patch("app.services.llm.time.sleep") as mock_sleep:
            res = llm._generate_response(
                "Prompt comum sem busca",
                app_config=app_cfg,
                web_search=False,
            )

        self.assertEqual(res, "Recuperado sem busca")
        self.assertEqual(calls, 2)
        mock_sleep.assert_called_once_with(llm.GEMINI_RETRY_DELAYS_SECONDS[0])

    # ------------------------------------------------------------------
    # Helper de perfil para testes de ciclo autônomo
    # ------------------------------------------------------------------
    def _create_autonomous_profile(self, name: str, web_search: bool) -> str:
        onboard = profile_manager.onboard_channel_workspace(
            name=name,
            niche="games_gta",
            topic_brief="Notícias recentes verificadas sobre GTA VI",
            video_format="traditional",
            autonomous_enabled=True,
            require_destination=False,
            db_path=self.db_path,
        )
        pid = onboard["profile_id"]
        ws = profile_manager.get_profile_settings(pid, db_path=self.db_path)
        ws.voice.voice_name = "pt-BR-AntonioNeural"
        ws.visual.flow_enabled = False
        ws.editorial.web_search = web_search
        profile_manager.update_profile_settings(pid, ws, db_path=self.db_path)

        # Destino YouTube ativo para não bloquear por falta de destino
        now_iso = datetime.now(timezone.utc).isoformat()
        with profile_manager.get_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO publishing_channels
                    (id, profile_id, platform, display_name, is_enabled, auto_publish_authorized, created_at, updated_at)
                VALUES (?, ?, 'youtube', ?, 1, 0, ?, ?);
                """,
                (f"ch-yt-{pid}", pid, f"{name} YT", now_iso, now_iso),
            )
            conn.commit()
        scheduler.set_setting("youtube_enabled", True, db_path=self.db_path)
        autonomous_production.set_profile_autonomous_mode_enabled(pid, True, db_path=self.db_path)
        return pid

    # ------------------------------------------------------------------
    # (4) Ideias: ciclo termina idle com reason="web_research_unavailable", sem tarefa e sem tentativa
    # ------------------------------------------------------------------
    def test_11_ideas_unavailable_cycle_ends_idle_without_task_or_attempt(self):
        pid = self._create_autonomous_profile("Canal GTA Web", web_search=True)
        now_dt = datetime(2026, 11, 21, 18, 0, 0, tzinfo=timezone.utc)
        task_base = os.path.join(self.temp_dir.name, "tasks_ideas")
        os.makedirs(task_base, exist_ok=True)

        with (
            patch.object(operator_console, "get_db_path", return_value=self.db_path),
            patch.object(operator_console, "is_factory_paused", return_value=False),
            patch.object(operator_console, "require_primary_instance", return_value=None),
            patch.object(autonomous_production, "check_required_providers_preflight", return_value=(True, "ok", {})),
            patch.object(
                autopilot,
                "generate_ideas",
                side_effect=llm.WebResearchUnavailableError("429 RESOURCE_EXHAUSTED", stage="ideias"),
            ),
            patch("app.services.webui_task.submit_generation") as mock_submit,
            patch("app.services.webui_task.has_active_generation_tasks", return_value=False),
        ):
            res = autonomous_production.run_autonomous_cycle(
                now=now_dt,
                force=True,
                db_path=self.db_path,
                task_base_dir=task_base,
                profile_id=pid,
            )

        self.assertEqual(res["status"], "idle")
        self.assertEqual(res["reason"], "web_research_unavailable")
        mock_submit.assert_not_called()
        self.assertEqual(
            autonomous_production.count_generation_attempts_in_last_24h(
                now=now_dt, db_path=self.db_path, profile_id=pid
            ),
            0,
        )
        # Visibilidade: motivo aparece no estado/mensagem do canal e em operational_events
        saved_state = autonomous_production._get_cycle_setting(
            autonomous_production.KEY_AUTONOMOUS_STATE, "", profile_id=pid, db_path=self.db_path
        )
        saved_msg = autonomous_production._get_cycle_setting(
            autonomous_production.KEY_AUTONOMOUS_MESSAGE, "", profile_id=pid, db_path=self.db_path
        )
        self.assertEqual(saved_state, autonomous_production.STATE_BLOCKED)
        self.assertIn("429 RESOURCE_EXHAUSTED", saved_msg)

    # ------------------------------------------------------------------
    # (5) Roteiro: erro propaga sem laço 3x/5x, tarefa falha no estágio script e NÃO conta nas tentativas 24h
    # ------------------------------------------------------------------
    def test_12_script_error_propagates_without_retry_loop_and_excludes_24h_attempt(self):
        pid = self._create_autonomous_profile("Canal GTA Script", web_search=True)
        now_dt = datetime.now(timezone.utc)
        tid = "task-wr-script-001"

        # Registra a tarefa no perfil e um evento generation_started (como o ciclo faz ao iniciar)
        profile_manager.save_task_profile(tid, pid, db_path=self.db_path)
        operator_console.log_operational_event(
            component="autonomous_production",
            severity=operator_console.SEVERITY_INFO,
            event_type="generation_started",
            task_id=tid,
            message="Iniciando geração autônoma",
            metadata={"profile_id": pid},
            db_path=self.db_path,
        )
        self.assertEqual(
            autonomous_production.count_generation_attempts_in_last_24h(
                now=now_dt, db_path=self.db_path, profile_id=pid
            ),
            1,
        )

        # (5a) llm.generate_script deixa WebResearchUnavailableError propagar na 1ª tentativa (sem repetir _max_retries)
        gen_calls = 0

        def fail_web_research(**kwargs):
            nonlocal gen_calls
            gen_calls += 1
            raise llm.WebResearchUnavailableError("429 RESOURCE_EXHAUSTED", stage="script")

        with patch.object(llm, "_generate_response", side_effect=fail_web_research):
            with self.assertRaises(llm.WebResearchUnavailableError):
                llm.generate_script(
                    video_subject="Novidade GTA VI",
                    language="pt-BR",
                    paragraph_number=1,
                    web_search=True,
                )
        self.assertEqual(gen_calls, 1)

        # (5b) task.start falha no estágio "script" com motivo web_research_unavailable e registra provider_unavailable_block
        params = autonomous_production.build_autonomous_video_params(
            topic="Novidade GTA VI",
            profile_id=pid,
            db_path=self.db_path,
        )
        orig_state = tm.sm.state
        mem_state = sm.MemoryState()
        tm.sm.state = mem_state
        try:
            with (
                patch.object(operator_console, "get_db_path", return_value=self.db_path),
                patch.object(llm, "_generate_response", side_effect=fail_web_research),
            ):
                fail_res = tm.start(tid, params, stop_at="script")
        finally:
            tm.sm.state = orig_state

        self.assertEqual(gen_calls, 2)  # +1 chamada apenas (sem retry loop)
        self.assertEqual(fail_res["state"], const.TASK_STATE_FAILED)
        self.assertEqual(fail_res["failed_stage"], "script")
        self.assertEqual(fail_res["reason"], "web_research_unavailable")
        self.assertEqual(fail_res["WebResearch"], "UNAVAILABLE")

        # (5c) Tentativas 24h por perfil, globais e consulta em lote do operator_console NÃO contam essa tarefa
        self.assertEqual(
            autonomous_production.count_generation_attempts_in_last_24h(
                now=now_dt, db_path=self.db_path, profile_id=pid
            ),
            0,
        )
        self.assertEqual(
            autonomous_production.count_all_profiles_attempts_24h(
                now=now_dt, db_path=self.db_path
            ),
            0,
        )
        # Verifica também o SQL do operator_console (~4318) diretamente
        h24_ago = (now_dt - timedelta(hours=24)).isoformat()
        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute(
                f"""
                SELECT count(DISTINCT COALESCE(NULLIF(o.task_id, ''), CAST(o.id AS TEXT))) AS cnt
                FROM operational_events o
                LEFT JOIN task_profiles tp ON tp.task_id = o.task_id
                WHERE o.component = 'autonomous_production'
                  AND o.event_type = 'generation_started'
                  AND o.timestamp >= ?
                  AND {autonomous_production.SQL_EXCLUDE_INSUFFICIENT_CREDITS_ATTEMPT};
                """,
                (h24_ago,),
            ).fetchone()
        self.assertEqual(int(row[0]), 0)

    # ------------------------------------------------------------------
    # (6) Cooldown de 20 min impede nova tentativa do mesmo perfil até expirar
    # ------------------------------------------------------------------
    def test_13_cooldown_20_min_blocks_same_profile_until_expired(self):
        pid = self._create_autonomous_profile("Canal GTA Cooldown", web_search=True)
        t0 = datetime(2026, 11, 21, 18, 0, 0, tzinfo=timezone.utc)
        t_during = t0 + timedelta(minutes=10)
        t_after = t0 + timedelta(minutes=21)
        task_base = os.path.join(self.temp_dir.name, "tasks_cooldown")
        os.makedirs(task_base, exist_ok=True)

        discover_calls = 0

        def fake_discover(*args, **kwargs):
            nonlocal discover_calls
            discover_calls += 1
            if discover_calls == 1:
                raise llm.WebResearchUnavailableError("429 RESOURCE_EXHAUSTED", stage="ideias")
            return None  # após expirar cooldown, volta a consultar normalmente

        with (
            patch.object(operator_console, "get_db_path", return_value=self.db_path),
            patch.object(operator_console, "is_factory_paused", return_value=False),
            patch.object(operator_console, "require_primary_instance", return_value=None),
            patch.object(autonomous_production, "check_required_providers_preflight", return_value=(True, "ok", {})),
            patch.object(autonomous_production, "discover_candidate_topic", side_effect=fake_discover),
            patch("app.services.webui_task.has_active_generation_tasks", return_value=False),
        ):
            r1 = autonomous_production.run_autonomous_cycle(
                now=t0, force=True, db_path=self.db_path, task_base_dir=task_base, profile_id=pid
            )
            # 10 min depois: bloqueado pelo cooldown de 20 min sem chamar discover_candidate_topic novamente
            r2 = autonomous_production.run_autonomous_cycle(
                now=t_during, force=True, db_path=self.db_path, task_base_dir=task_base, profile_id=pid
            )
            # 21 min depois: cooldown expirou -> volta a chamar discover_candidate_topic
            r3 = autonomous_production.run_autonomous_cycle(
                now=t_after, force=True, db_path=self.db_path, task_base_dir=task_base, profile_id=pid
            )

        self.assertEqual(r1["status"], "idle")
        self.assertEqual(r1["reason"], "web_research_unavailable")

        self.assertEqual(r2["status"], "idle")
        self.assertEqual(r2["reason"], "web_research_unavailable")
        self.assertGreaterEqual(r2.get("cooldown_remaining_minutes", 0), 1)

        self.assertEqual(r3["status"], "idle")
        self.assertEqual(r3["reason"], "no_candidate")
        # discover_candidate_topic chamado em t0 e t_after, mas NÃO em t_during!
        self.assertEqual(discover_calls, 2)

    # ------------------------------------------------------------------
    # (7) Canal sem web_search não muda de comportamento
    # ------------------------------------------------------------------
    def test_14_channel_without_web_search_is_unaffected(self):
        pid = self._create_autonomous_profile("Canal Normal Sem Busca", web_search=False)
        now_dt = datetime(2026, 11, 21, 18, 0, 0, tzinfo=timezone.utc)
        task_base = os.path.join(self.temp_dir.name, "tasks_normal")
        os.makedirs(task_base, exist_ok=True)

        # Mesmo com erro genérico no autopilot, canal sem web_search continua retornando no_candidate (sem WebResearchUnavailableError)
        with (
            patch.object(operator_console, "get_db_path", return_value=self.db_path),
            patch.object(operator_console, "is_factory_paused", return_value=False),
            patch.object(operator_console, "require_primary_instance", return_value=None),
            patch.object(autonomous_production, "check_required_providers_preflight", return_value=(True, "ok", {})),
            patch.object(autopilot, "generate_ideas", side_effect=RuntimeError("Erro genérico LLM")) as mock_ideas,
            patch("app.services.webui_task.has_active_generation_tasks", return_value=False),
        ):
            res = autonomous_production.run_autonomous_cycle(
                now=now_dt,
                force=True,
                db_path=self.db_path,
                task_base_dir=task_base,
                profile_id=pid,
            )

        self.assertEqual(res["status"], "idle")
        self.assertEqual(res["reason"], "no_candidate")
        self.assertIs(mock_ideas.call_args.kwargs["web_search"], False)


if __name__ == "__main__":
    unittest.main()
