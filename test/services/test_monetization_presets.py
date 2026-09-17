import os
import sqlite3
import tempfile
import unittest
from datetime import datetime, timezone
from unittest.mock import MagicMock, patch

from app.models import const
from app.models.schema import VideoParams
from app.services import autopilot, llm, safety_gate, scheduler


class TestMonetizationPresets(unittest.TestCase):

    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.temp_dir.name, "test_monetization.db")
        safety_gate.init_safety_db(self.db_path)

    def tearDown(self):
        try:
            self.temp_dir.cleanup()
        except Exception:
            pass

    def test_01_preset_tiktok_rewards_generates_instruction_62_75s(self):
        prompt = llm.build_script_prompt(
            video_subject="Curiosidades sobre Buracos Negros",
            monetization_preset=const.PRESET_TIKTOK_REWARDS,
        )
        self.assertIn("62 a 75 segundos", prompt)
        self.assertIn("140 a 175 palavras", prompt)
        self.assertIn("TikTok Creator Rewards", prompt)
        self.assertIn("NUNCA abaixo de 60 segundos", prompt)

    def test_02_preset_cross_platform_generates_instruction_62_75s(self):
        prompt = llm.build_script_prompt(
            video_subject="O Mistério das Pirâmides",
            monetization_preset=const.PRESET_CROSS_PLATFORM,
        )
        self.assertIn("62 a 75 segundos", prompt)
        self.assertIn("140 a 175 palavras", prompt)
        self.assertIn("YouTube + TikTok Monetization", prompt)
        self.assertIn("NUNCA abaixo de 60 segundos", prompt)

    def test_03_youtube_preset_does_not_force_tiktok_rule(self):
        prompt = llm.build_script_prompt(
            video_subject="Análise Filosófica da Gravidade",
            monetization_preset=const.PRESET_YOUTUBE_ORIGINAL,
        )
        self.assertIn("45 a 90 segundos", prompt)
        self.assertNotIn("NUNCA abaixo de 60 segundos", prompt)

        spec = safety_gate.get_preset_spec(const.PRESET_YOUTUBE_ORIGINAL)
        self.assertFalse(spec["enforce_tiktok_rule"])
        self.assertEqual(spec["min_acceptable_duration"], 30.0)

    def test_04_pt_br_remains_present(self):
        prompt = llm.build_script_prompt(
            video_subject="O Futuro da Inteligência Artificial",
            language="pt-BR",
            monetization_preset=const.PRESET_CROSS_PLATFORM,
        )
        self.assertIn("pt-BR", prompt)
        self.assertIn("português brasileiro", prompt)
        self.assertIn("Monetization & Narrative Guidelines", prompt)

    def test_05_narrative_structures_vary(self):
        self.assertEqual(len(const.NARRATIVE_STRUCTURES), 5)
        for s in const.NARRATIVE_STRUCTURES:
            spec = safety_gate.get_structure_spec(s)
            self.assertIsNotNone(spec)
            self.assertTrue(len(spec["steps"]) >= 4)

        assigned = autopilot.assign_batch_narrative_structures(5)
        self.assertEqual(len(assigned), 5)
        self.assertEqual(len(set(assigned)), 5)

    def test_06_structure_does_not_repeat_indefinitely(self):
        recent = [const.STRUCTURE_MYSTERY]
        next_s = safety_gate.get_next_narrative_structure(recent_structures=recent, current_index=0)
        self.assertNotEqual(next_s, const.STRUCTURE_MYSTERY)

        history = [const.STRUCTURE_MYSTERY]
        for i in range(10):
            chosen = safety_gate.get_next_narrative_structure(recent_structures=history, current_index=i)
            self.assertNotEqual(chosen, history[0])
            history = [chosen] + history[:3]

    def test_07_duplicate_hook_is_detected(self):
        hook_text = "Este é um enigma que a ciência moderna jamais conseguiu decifrar."
        safety_gate.save_safety_assessment(
            {
                "task_id": "hist-task-1",
                "preset": const.PRESET_CROSS_PLATFORM,
                "narrative_structure": const.STRUCTURE_MYSTERY,
                "word_count": 150,
                "estimated_duration": 65.0,
                "safety_status": const.SAFETY_STATUS_PASS,
                "hook_text": hook_text,
                "cta_text": "Deixe seu comentário.",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=self.db_path,
        )

        dup_script = (
            f"{hook_text} Muitos cientistas tentaram resolver ao longo dos anos com dedicação constante. "
            "No entanto, as evidências históricas apontam para outro caminho completamente inesperado e surpreendente. "
            "Pesquisadores de diversas partes do mundo continuam coletando dados fascinantes sobre esses acontecimentos memoráveis. "
            "A cada nova descoberta, velhas teorias caem por terra enquanto novas hipóteses surgem para explicar a realidade factual. "
            "Ao final desse longo percurso analítico, o mistério permanece vivo, provocador e profundamente enriquecedor. "
            "O que você acha de tudo isso que descobrimos juntos hoje nesta análise cuidadosa? Deixe sua reflexão nos comentários."
        )
        res = safety_gate.evaluate_script_safety(
            task_id="new-task-2",
            topic="Um enigma misterioso",
            script=dup_script,
            preset=const.PRESET_CROSS_PLATFORM,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_BLOCK)
        reasons_combined = " ".join(res["safety_reasons"])
        self.assertTrue("Hook" in reasons_combined or "abertura" in reasons_combined)

    def test_08_duplicate_cta_is_detected(self):
        safety_gate.save_safety_assessment(
            {
                "task_id": "hist-task-cta",
                "preset": const.PRESET_CROSS_PLATFORM,
                "word_count": 150,
                "estimated_duration": 65.0,
                "safety_status": const.SAFETY_STATUS_PASS,
                "hook_text": "Um fato impressionante sobre a rotação da Terra.",
                "cta_text": "Inscreva-se agora no canal e compartilhe este vídeo com todos os seus amigos.",
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=self.db_path,
        )

        new_script = (
            "A velocidade da luz é a constante fundamental do universo observável e rege todos os fenômenos da física moderna. "
            "Nada pode viajar mais rápido do que fótons no vácuo perfeito segundo a consagrada teoria relativística. "
            "Essa regra foi formulada pela relatividade restrita de Albert Einstein no início do século vinte e permanece incontestada. "
            "Ela molda a estrutura do espaço e do tempo, definindo a causalidade e a propagação de informações no cosmos. "
            "Cientistas utilizam esse princípio para explorar as origens das galáxias e o nascimento das primeiras estrelas. "
            "Inscreva-se agora no canal e compartilhe este vídeo com todos os seus amigos."
        )
        res = safety_gate.evaluate_script_safety(
            task_id="new-task-cta-2",
            topic="A velocidade da luz",
            script=new_script,
            preset=const.PRESET_CROSS_PLATFORM,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_REVIEW)
        reasons_combined = " ".join(res["safety_reasons"])
        self.assertIn("CTA", reasons_combined)

    def test_09_highly_similar_topic_is_detected(self):
        conn = sqlite3.connect(self.db_path)
        try:
            conn.execute(
                """
                INSERT INTO monetization_safety (
                    task_id, topic, preset, word_count, estimated_duration, safety_status, hook_text, cta_text, checked_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
                """,
                (
                    "hist-task-topic",
                    "Por que o tempo passa mais devagar no espaço",
                    const.PRESET_CROSS_PLATFORM,
                    150,
                    65.0,
                    const.SAFETY_STATUS_PASS,
                    "Abertura original sobre dilatação temporal.",
                    "Fechamento original sobre física quântica.",
                    datetime.now(timezone.utc).isoformat(),
                ),
            )
            conn.commit()
        finally:
            conn.close()

        history = safety_gate.get_recent_safety_history(limit=10, db_path=self.db_path)
        res = safety_gate.evaluate_script_safety(
            task_id="new-task-topic-dup",
            topic="Por que o tempo passa mais devagar no espaço?",
            script=(
                "A dilatação gravitacional do tempo é uma das consequências mais espetaculares previstas pela relatividade geral. "
                "Quanto mais próximo você estiver de um campo gravitacional intenso, mais lentamente o tempo transcorrerá em relação a um observador distante. "
                "Esse efeito foi comprovado experimentalmente utilizando relógios atômicos de ultra precisão colocados a bordo de aviões e satélites. "
                "Sem as devidas correções relativísticas, os sistemas modernos de GPS apresentariam erros acumulados de quilômetros todos os dias. "
                "O universo demonstra de forma incontestável que o tempo não é absoluto, mas sim uma dimensão flexível e moldada pela gravidade."
            ),
            preset=const.PRESET_CROSS_PLATFORM,
            history=history,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_BLOCK)
        self.assertTrue(any("Tema altamente semelhante" in r for r in res["safety_reasons"]))

    def test_10_different_topic_passes(self):
        history = [
            {
                "task_id": "hist-task-topic",
                "topic": "Por que o tempo passa mais devagar no espaco",
                "hook_text": "Abertura sobre gravidade cósmica.",
                "cta_text": "Fechamento sobre gravidade cósmica.",
            }
        ]
        diff_script = (
            "A fascinante história do cultivo de café nas montanhas do Brasil colonial transformou radicalmente a economia de todo o continente americano. "
            "Grandes fazendas do interior paulista e fluminense criaram rotas comerciais estratégicas que ditaram o desenvolvimento do país durante todo o século dezenove. "
            "Milhares de trabalhadores, pioneiros e as primeiras ferrovias a vapor construíram os caminhos por onde fluía a principal riqueza da nação brasileira. "
            "As lavouras se expandiram pelas colinas férteis de terra roxa, atraindo imigrantes de diversas partes do globo em busca de novas oportunidades e trabalho. "
            "Ainda hoje, as técnicas aprimoradas, o controle de qualidade e o sabor inconfundível do café brasileiro continuam sendo a grande referência para os mercados mundiais mais exigentes. "
            "Trata-se de uma verdadeira herança histórica e cultural que reverbera com força em cada xícara degustada com prazer pelo planeta afora."
        )
        res = safety_gate.evaluate_script_safety(
            task_id="diff-task-1",
            topic="A história do café no Brasil colonial",
            script=diff_script,
            preset=const.PRESET_CROSS_PLATFORM,
            history=history,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_PASS)
        self.assertEqual(len(res["safety_reasons"]), 0)

    def test_11_tiktok_preset_below_60s_is_block(self):
        res = safety_gate.evaluate_duration_safety(
            task_id="short-tk-task",
            actual_duration=48.5,
            preset=const.PRESET_TIKTOK_REWARDS,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_BLOCK)
        reasons_str = " ".join(res["safety_reasons"])
        self.assertIn("abaixo do mínimo de 60s", reasons_str)

    def test_12_target_duration_passes(self):
        res = safety_gate.evaluate_duration_safety(
            task_id="good-tk-task",
            actual_duration=68.2,
            preset=const.PRESET_TIKTOK_REWARDS,
            db_path=self.db_path,
        )
        self.assertEqual(res["safety_status"], const.SAFETY_STATUS_PASS)

    def test_13_safety_block_not_admitted_to_automatic_scheduler(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 10, db_path=self.db_path)

        # Tarefa com status BLOCK
        safety_gate.save_safety_assessment(
            {
                "task_id": "blocked-task-1",
                "preset": const.PRESET_TIKTOK_REWARDS,
                "safety_status": const.SAFETY_STATUS_BLOCK,
                "safety_reasons": ["Duração 45s abaixo de 60s"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=self.db_path,
        )
        scheduler.save_task_platforms("blocked-task-1", ["tiktok"], db_path=self.db_path)

        tasks = [
            {
                "task_id": "blocked-task-1",
                "state": const.TASK_STATE_COMPLETE,
                "video_file": "dummy.mp4",
                "planned_platforms": ["tiktok"],
                "safety_status": const.SAFETY_STATUS_BLOCK,
            }
        ]
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(scheduled), 0)

    def test_14_safety_review_remains_reviewable_not_auto_scheduled(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

        safety_gate.save_safety_assessment(
            {
                "task_id": "review-task-1",
                "preset": const.PRESET_CROSS_PLATFORM,
                "safety_status": const.SAFETY_STATUS_REVIEW,
                "safety_reasons": ["Abertura moderadamente semelhante a vídeo recente"],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=self.db_path,
        )
        scheduler.save_task_platforms("review-task-1", ["tiktok"], db_path=self.db_path)

        tasks = [
            {
                "task_id": "review-task-1",
                "state": const.TASK_STATE_COMPLETE,
                "video_file": "dummy.mp4",
                "planned_platforms": ["tiktok"],
                "safety_status": const.SAFETY_STATUS_REVIEW,
            }
        ]
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(scheduled), 0)

        # Permanece no banco de safety disponível para inspeção
        rec = safety_gate.get_safety_assessment("review-task-1", db_path=self.db_path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["safety_status"], const.SAFETY_STATUS_REVIEW)

    def test_15_safety_pass_is_eligible(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_limit_24h", 10, db_path=self.db_path)

        safety_gate.save_safety_assessment(
            {
                "task_id": "pass-task-1",
                "preset": const.PRESET_CROSS_PLATFORM,
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "checked_at": datetime.now(timezone.utc).isoformat(),
            },
            db_path=self.db_path,
        )
        scheduler.save_task_platforms("pass-task-1", ["tiktok"], db_path=self.db_path)

        tasks = [
            {
                "task_id": "pass-task-1",
                "state": const.TASK_STATE_COMPLETE,
                "video_file": "dummy.mp4",
                "planned_platforms": ["tiktok"],
                "safety_status": const.SAFETY_STATUS_PASS,
            }
        ]
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["task_id"], "pass-task-1")

    def test_16_preset_data_persists_after_restart(self):
        safety_gate.save_safety_assessment(
            {
                "task_id": "persist-test-1",
                "preset": const.PRESET_TIKTOK_REWARDS,
                "narrative_structure": const.STRUCTURE_MYTH_REALITY,
                "word_count": 165,
                "estimated_duration": 68.0,
                "actual_duration": 69.5,
                "safety_status": const.SAFETY_STATUS_PASS,
                "safety_reasons": [],
                "hook_text": "Mito número um do sono.",
                "cta_text": "Durma bem esta noite.",
                "checked_at": "2026-09-16T12:00:00Z",
            },
            db_path=self.db_path,
        )

        # Consulta com nova conexão
        rec = safety_gate.get_safety_assessment("persist-test-1", db_path=self.db_path)
        self.assertIsNotNone(rec)
        self.assertEqual(rec["preset"], const.PRESET_TIKTOK_REWARDS)
        self.assertEqual(rec["narrative_structure"], const.STRUCTURE_MYTH_REALITY)
        self.assertEqual(rec["word_count"], 165)
        self.assertEqual(rec["actual_duration"], 69.5)
        self.assertEqual(rec["safety_status"], const.SAFETY_STATUS_PASS)

    def test_17_sqlite_migration_preserves_existing_database(self):
        scheduler.init_db(self.db_path)
        # Grava post e publicação existentes
        now = datetime.now(timezone.utc)
        scheduler.record_publication_event(
            task_id="legacy-pub-1",
            platform="youtube",
            status="success",
            published_at=now,
            external_id="YT-12345",
            db_path=self.db_path,
        )

        # Executa inicialização de safety novamente (migração idempotente)
        safety_gate.init_safety_db(self.db_path)

        with scheduler.get_connection(self.db_path) as conn:
            event = conn.execute(
                "SELECT * FROM publication_events WHERE task_id = 'legacy-pub-1';"
            ).fetchone()
            self.assertIsNotNone(event)
            self.assertEqual(event["external_id"], "YT-12345")

            tables = [
                r["name"]
                for r in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table';"
                ).fetchall()
            ]
            self.assertIn("monetization_safety", tables)
            self.assertIn("publication_events", tables)

    def test_18_old_pipeline_and_manual_publishing_continues_working(self):
        scheduler.init_db(self.db_path)
        scheduler.set_setting("scheduler_enabled", True, db_path=self.db_path)
        scheduler.set_setting("tiktok_enabled", True, db_path=self.db_path)

        # Tarefa legado sem registro em safety_status
        scheduler.save_task_platforms("legacy-task-1", ["tiktok"], db_path=self.db_path)
        tasks = [
            {
                "task_id": "legacy-task-1",
                "state": const.TASK_STATE_COMPLETE,
                "video_file": "dummy.mp4",
                "planned_platforms": ["tiktok"],
                # safety_status ausente/None
            }
        ]
        # Não causa exceção e é elegível normalmente
        scheduled = scheduler.plan_schedule(tasks, db_path=self.db_path)
        self.assertEqual(len(scheduled), 1)
        self.assertEqual(scheduled[0]["task_id"], "legacy-task-1")

    def test_19_existing_publication_not_altered(self):
        scheduler.init_db(self.db_path)
        now = datetime.now(timezone.utc)
        scheduler.record_publication_event(
            task_id="untouched-pub",
            platform="youtube",
            status="success",
            published_at=now,
            external_id="SMRl-CWMRTQ",
            provider_request_id="575e369eee38400f82c5cd0d81bd57b5",
            db_path=self.db_path,
        )

        safety_gate.evaluate_duration_safety(
            task_id="untouched-pub",
            actual_duration=65.0,
            preset=const.PRESET_CROSS_PLATFORM,
            db_path=self.db_path,
        )

        with scheduler.get_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT * FROM publication_events WHERE task_id = 'untouched-pub';"
            ).fetchone()
            self.assertEqual(row["external_id"], "SMRl-CWMRTQ")
            self.assertEqual(row["provider_request_id"], "575e369eee38400f82c5cd0d81bd57b5")

    def test_20_no_additional_paid_api_called(self):
        with patch("urllib.request.urlopen") as mock_url, patch("requests.post") as mock_post:
            res1 = safety_gate.evaluate_script_safety(
                task_id="local-check-1",
                topic="A velocidade da luz",
                script="Este é um roteiro longo o suficiente para passar pelos checks determinísticos locais sem nenhuma chamada externa... " * 8,
                preset=const.PRESET_CROSS_PLATFORM,
                db_path=self.db_path,
            )
            res2 = safety_gate.evaluate_duration_safety(
                task_id="local-check-1",
                actual_duration=66.5,
                preset=const.PRESET_CROSS_PLATFORM,
                db_path=self.db_path,
            )
            self.assertEqual(res1["safety_status"], const.SAFETY_STATUS_PASS)
            self.assertEqual(res2["safety_status"], const.SAFETY_STATUS_PASS)
            mock_url.assert_not_called()
            mock_post.assert_not_called()

    def test_21_pipeline_with_cross_platform_preset(self):
        from app.services import task as tm, state as sm
        task_id = "test-pipe-cross"
        params = VideoParams(
            video_subject="Por que as estrelas brilham?",
            video_language="pt-BR",
            monetization_preset=const.PRESET_CROSS_PLATFORM,
            narrative_structure=const.STRUCTURE_EXPLAINER,
        )

        with patch("app.services.task.generate_script", return_value="Este é o roteiro completo sobre por que as estrelas brilham na galáxia... " * 5), \
             patch("app.services.task.generate_terms", return_value=["estrelas", "universo"]), \
             patch("app.services.task.generate_audio", return_value=("audio.mp3", 65.0, None)), \
             patch("app.services.task.save_script_data"), \
             patch("app.services.task.utils.check_ffmpeg_ready", return_value=True):

            res = tm.start(task_id, params, stop_at="audio")
            self.assertIn("audio_file", res)
            task_state = sm.state.get_task(task_id)
            self.assertIsNotNone(task_state)
            self.assertEqual(params.monetization_preset, const.PRESET_CROSS_PLATFORM)
            self.assertIn(params.safety_status, {const.SAFETY_STATUS_PASS, const.SAFETY_STATUS_REVIEW, const.SAFETY_STATUS_BLOCK})

    def test_22_safety_pre_tts_does_not_abort_generation(self):
        from app.services import task as tm
        task_id = "test-pipe-pre-block"
        params = VideoParams(
            video_subject="Tema Repetido",
            monetization_preset=const.PRESET_TIKTOK_REWARDS,
        )

        with patch("app.services.task.generate_script", return_value="Script de teste curto."), \
             patch("app.services.task.generate_terms", return_value=["teste"]), \
             patch("app.services.task.generate_audio", return_value=("audio.mp3", 65.0, None)), \
             patch("app.services.task.save_script_data"), \
             patch("app.services.safety_gate.evaluate_script_safety", return_value={
                 "safety_status": const.SAFETY_STATUS_REVIEW,
                 "safety_reasons": ["Risco de repetição de tópico"],
                 "preset": const.PRESET_TIKTOK_REWARDS,
                 "narrative_structure": const.STRUCTURE_MYSTERY,
             }):
            res = tm.start(task_id, params, stop_at="terms")
            self.assertIn("script", res)
            self.assertEqual(params.safety_status, const.SAFETY_STATUS_REVIEW)

    def test_23_safety_post_tts_does_not_abort_generation(self):
        from app.services import task as tm
        task_id = "test-pipe-post-block"
        params = VideoParams(
            video_subject="Tema Curto",
            monetization_preset=const.PRESET_TIKTOK_REWARDS,
        )

        with patch("app.services.task.generate_script", return_value="Script de teste"), \
             patch("app.services.task.generate_terms", return_value=["teste"]), \
             patch("app.services.task.generate_audio", return_value=("audio.mp3", 45.0, None)), \
             patch("app.services.task.save_script_data"):
            res = tm.start(task_id, params, stop_at="audio")
            self.assertIn("audio_file", res)
            self.assertEqual(params.safety_status, const.SAFETY_STATUS_BLOCK)

    def test_24_exception_in_safety_handled_safely_or_marks_failure(self):
        from app.services import task as tm
        task_id = "test-pipe-safety-exc"
        params = VideoParams(video_subject="Tema Exceção")

        with patch("app.services.task.generate_script", return_value="Script de teste"), \
             patch("app.services.task.generate_terms", return_value=["teste"]), \
             patch("app.services.safety_gate.evaluate_script_safety", side_effect=RuntimeError("Safety DB error")):
            res = tm.start(task_id, params, stop_at="terms")
            self.assertIn("script", res)

    def test_25_video_params_safe_defaults(self):
        p = VideoParams(video_subject="Tema Padrão")
        self.assertEqual(p.monetization_preset, const.DEFAULT_MONETIZATION_PRESET)
        self.assertIsNone(p.narrative_structure)
        self.assertIsNone(p.safety_status)
        self.assertIsNone(p.safety_reasons)

    def test_26_script_json_serialization_with_new_params(self):
        import json
        p = VideoParams(
            video_subject="Teste de Serialização",
            monetization_preset=const.PRESET_CROSS_PLATFORM,
            narrative_structure=const.STRUCTURE_FACT_CONTEXT,
            safety_status=const.SAFETY_STATUS_PASS,
            safety_reasons="Nenhum risco detectado",
        )
        data = {"script": "Roteiro", "search_terms": ["termo"], "params": p}
        serialized = json.dumps(data, default=lambda val: val.__dict__, ensure_ascii=False)
        self.assertIn("cross_platform", serialized)
        self.assertIn("fact_context", serialized)
        self.assertIn("PASS", serialized)

    def test_27_legacy_script_json_deserialization(self):
        legacy_data = {
            "script": "Texto antigo",
            "search_terms": ["antigo"],
            "params": {
                "video_subject": "Assunto legado",
                "video_script": "Texto",
            }
        }
        params = VideoParams(**legacy_data["params"])
        self.assertEqual(params.video_subject, "Assunto legado")
        self.assertEqual(params.monetization_preset, const.DEFAULT_MONETIZATION_PRESET)
        self.assertIsNone(params.safety_status)

    def test_28_task_fails_visibly_and_does_not_stay_processing(self):
        from app.services import webui_task, state as sm
        fail_task_id = "test-fail-task-vis"

        with patch("app.services.task.start", side_effect=ValueError("Boom!")):
            failure = webui_task._run_generation(
                task_id=fail_task_id,
                params=VideoParams(video_subject="Teste Falha"),
                capture_logs=False,
            )
            self.assertEqual(failure["state"], const.TASK_STATE_FAILED)
            stored = sm.state.get_task(fail_task_id)
            self.assertEqual(stored["state"], const.TASK_STATE_FAILED)
            self.assertIn("Boom!", stored["error"])

    def test_29_scan_history_and_collect_recovers_persisted_task(self):
        from webui import Main
        task_dir = os.path.join(self.temp_dir.name, "tasks", "task-hist-rec")
        os.makedirs(task_dir, exist_ok=True)
        video_path = os.path.join(task_dir, "final-1.mp4")
        with open(video_path, "wb") as f:
            f.write(b"mp4data")

        with patch("app.utils.utils.task_dir", return_value=os.path.join(self.temp_dir.name, "tasks")):
            tasks = Main._scan_history_tasks(limit=10)
            rec = next((t for t in tasks if t["task_id"] == "task-hist-rec"), None)
            self.assertIsNotNone(rec)
            self.assertEqual(rec["state"], const.TASK_STATE_COMPLETE)
            self.assertEqual(rec["progress"], 100)

    def test_30_pipeline_without_preset_continues_working(self):
        from app.services import task as tm
        task_id = "test-pipe-no-preset"
        params = VideoParams(
            video_subject="Tema Clássico",
            monetization_preset=None,
            narrative_structure=None,
        )

        with patch("app.services.task.generate_script", return_value="Script clássico"), \
             patch("app.services.task.generate_terms", return_value=["termo"]), \
             patch("app.services.task.save_script_data"):
            res = tm.start(task_id, params, stop_at="terms")
            self.assertIn("script", res)
            self.assertEqual(res["script"], "Script clássico")

    def test_31_button_click_does_not_self_deadlock(self):
        from unittest.mock import MagicMock
        from webui import Main

        mock_st = MagicMock()
        mock_st.session_state = {
            "active_generation_tasks": {},
            "video_subject": "Teste Self-Deadlock",
        }
        with patch.object(Main, "st", mock_st):
            # 1. Usuário clica no botão (dispara on_click)
            Main._prepare_generation_task()
            pending_id = mock_st.session_state.get("pending_generation_task_id")
            self.assertIsNotNone(pending_id)

            # 2. Guarda na reexecução do script (linha 8496)
            is_locked = bool(
                Main.webui_task.has_active_generation_tasks() or
                Main._has_active_generation(exclude_task_id=pending_id)
            )
            # NÃO deve bloquear a própria submissão atual
            self.assertFalse(is_locked)

            # 3. Mas bloqueia se HOUVER outra tarefa realmente em execução
            mock_st.session_state["active_generation_tasks"]["other-task"] = {"subject": "Outro"}
            sm_patch = patch.object(Main.sm.state, "get_task", return_value={"state": const.TASK_STATE_PROCESSING})
            with sm_patch:
                other_locked = bool(
                    Main.webui_task.has_active_generation_tasks() or
                    Main._has_active_generation(exclude_task_id=pending_id)
                )
                self.assertTrue(other_locked)


if __name__ == "__main__":
    unittest.main()
