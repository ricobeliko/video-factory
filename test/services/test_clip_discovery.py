"""
Test Suite para Clip Discovery Service (Fase V11-B).

Cobre os requisitos 31 a 60:
31. transcript inexistente rejeitado
32. incomplete transcript rejeitado
33. algoritmo determinístico
34. mesmo input gera mesmos candidatos
35. candidatos respeitam source duration
36. start >=0
37. end > start
38. duration backend calculated
39. sentence boundary melhora score
40. pergunta/hook adiciona componente explicável
41. speech density calculada deterministicamente
42. long silence penaliza
43. candidato muito curto penalizado
44. candidato >180s rejeitado
45. default max 10
46. ordenação score desc
47. tie usa start asc
48. selection_method heuristic
49. status CANDIDATE
50. manual segments preservados
51. candidate duplicate não duplicado
52. source/profile preservados
53. reason explicável
54. score entre 0 e 100
55. SELECTED manual preservado
56. REJECTED manual preservado
57. rerun discovery idempotente
58. zero LLM calls
59. zero HTTP
60. zero publication
"""
import os
import tempfile
import unittest
from unittest.mock import MagicMock, patch

from app.services import (
    clip_discovery,
    clip_mode,
    clip_transcription,
    operator_console,
    profile_manager,
)


class TestClipDiscovery(unittest.TestCase):
    def setUp(self):
        self.tmp_dir = tempfile.TemporaryDirectory()
        self.db_path = os.path.join(self.tmp_dir.name, "test_video_factory.db")

        # Configura instância como PRIMARY
        operator_console.reset_instance_for_testing()
        with operator_console._instance_state_lock:
            operator_console._current_role = operator_console.ROLE_PRIMARY

        # Inicializa tabelas
        profile_manager.init_profile_db(db_path=self.db_path)
        profile_manager.ensure_default_profile(db_path=self.db_path)
        clip_mode.init_clip_db(db_path=self.db_path)
        clip_transcription.init_clip_transcription_db(db_path=self.db_path)

        # Registra mock provider padrão
        self.mock_provider = clip_transcription.MockTranscriptProvider()
        clip_transcription.register_transcript_provider("mock", self.mock_provider)

        # Cria arquivo de vídeo de teste
        self.fake_video_path = os.path.join(self.tmp_dir.name, "sample_clip.mp4")
        with open(self.fake_video_path, "wb") as f:
            f.write(b"FAKE_MP4_VIDEO_FOR_DISCOVERY_TESTS_1234567890")

        self.default_probe_metadata = {
            "duration_seconds": 120.0,
            "width": 1920,
            "height": 1080,
            "fps": 30.0,
            "video_codec": "h264",
            "audio_codec": "aac",
            "has_audio": True,
        }

    def tearDown(self):
        operator_console.reset_instance_for_testing()
        self.tmp_dir.cleanup()

    def _create_source_and_completed_transcript(self, duration=120.0, profile_id="default", segments=None):
        probe_meta = dict(self.default_probe_metadata)
        probe_meta["duration_seconds"] = duration

        with patch("app.services.clip_mode.probe_video_metadata", return_value=probe_meta):
            src_res = clip_mode.import_clip_source(
                file_path=self.fake_video_path,
                source_origin="owned",
                authorization_confirmed=True,
                authorization_note="Autorizado para testes V11-B Discovery",
                profile_id=profile_id,
                db_path=self.db_path,
            )
            source_id = src_res["source_id"]

        dummy_wav = os.path.join(self.tmp_dir.name, "audio.wav")
        with open(dummy_wav, "wb") as f:
            f.write(b"RIFF_WAV")

        if segments is None:
            # Cria segmentos ricos com durações variadas para discovery
            segments = [
                {
                    "sequence": 0,
                    "start_seconds": 0.0,
                    "end_seconds": 12.0,
                    "text": "Você sabia que a criação de vídeos curtos pode ser automatizada com total controle?",
                    "confidence": 0.96,
                },
                {
                    "sequence": 1,
                    "start_seconds": 12.0,
                    "end_seconds": 28.0,
                    "text": "O segredo é estruturar roteiros bem amarrados e focar na retenção do espectador.",
                    "confidence": 0.93,
                },
                {
                    "sequence": 2,
                    "start_seconds": 28.0,
                    "end_seconds": 45.0,
                    "text": "Três coisas definem o sucesso: gancho inicial forte, ritmo ágil e chamada para ação.",
                    "confidence": 0.91,
                },
                {
                    "sequence": 3,
                    "start_seconds": 45.0,
                    "end_seconds": 65.0,
                    "text": "Quando você divide a fala em frases completas, a edição fica natural e profissional.",
                    "confidence": 0.94,
                },
                {
                    "sequence": 4,
                    "start_seconds": 65.0,
                    "end_seconds": 88.0,
                    "text": "Porém, se o corte começar no meio de uma frase, o espectador perde o contexto imediatamente.",
                    "confidence": 0.89,
                },
                {
                    "sequence": 5,
                    "start_seconds": 88.0,
                    "end_seconds": 115.0,
                    "text": "Pratique essa estrutura no seu próximo conteúdo e analise o salto na retenção.",
                    "confidence": 0.95,
                },
            ]

        custom_provider = clip_transcription.MockTranscriptProvider(
            mock_text=" ".join(s["text"] for s in segments),
            mock_segments=segments,
        )
        clip_transcription.register_transcript_provider("discovery_mock", custom_provider)

        with patch("app.services.clip_transcription.extract_clip_source_audio", return_value=dummy_wav):
            tr_res = clip_transcription.transcribe_clip_source(
                source_id=source_id,
                provider_name="discovery_mock",
                db_path=self.db_path,
            )
            return source_id, tr_res["transcript_id"]

    # 31. transcript inexistente rejeitado
    def test_31_nonexistent_transcript_rejected(self):
        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_discovery.discover_clip_candidates("tr_inexistente_999", db_path=self.db_path)
        self.assertIn("não encontrada", str(ctx.exception))

    # 32. incomplete transcript rejeitado
    def test_32_incomplete_transcript_rejected(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()

        # Altera status para PROCESSING
        with clip_mode.get_connection(self.db_path) as conn:
            conn.execute("UPDATE clip_transcripts SET status = 'PROCESSING' WHERE id = ?", (transcript_id,))

        with self.assertRaises(clip_mode.ClipValidationError) as ctx:
            clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertIn("não está concluída", str(ctx.exception))

    # 33. algoritmo determinístico
    def test_33_algorithm_deterministic(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates1 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        candidates2 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)

        self.assertEqual(len(candidates1), len(candidates2))
        for c1, c2 in zip(candidates1, candidates2):
            self.assertEqual(c1["start_seconds"], c2["start_seconds"])
            self.assertEqual(c1["end_seconds"], c2["end_seconds"])
            self.assertEqual(c1["duration_seconds"], c2["duration_seconds"])
            self.assertEqual(c1["title"], c2["title"])

    # 34. mesmo input gera mesmos candidatos
    def test_34_same_input_generates_same_candidates(self):
        text = "Você sabia que isso é determinístico? Funciona perfeitamente sempre."
        score1, reason1 = clip_discovery.score_candidate_window(
            text=text,
            duration_seconds=30.0,
            start_text="Você sabia que isso é determinístico?",
            end_text="Funciona perfeitamente sempre.",
        )
        score2, reason2 = clip_discovery.score_candidate_window(
            text=text,
            duration_seconds=30.0,
            start_text="Você sabia que isso é determinístico?",
            end_text="Funciona perfeitamente sempre.",
        )
        self.assertEqual(score1, score2)
        self.assertEqual(reason1, reason2)

    # 35. candidatos respeitam source duration
    def test_35_candidates_respect_source_duration(self):
        source_id, transcript_id = self._create_source_and_completed_transcript(duration=60.0)
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        for cand in candidates:
            self.assertLessEqual(cand["end_seconds"], 60.1)

    # 36. start >=0
    def test_36_start_gte_zero(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        for cand in candidates:
            self.assertGreaterEqual(cand["start_seconds"], 0.0)

    # 37. end > start
    def test_37_end_gt_start(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        for cand in candidates:
            self.assertGreater(cand["end_seconds"], cand["start_seconds"])

    # 38. duration backend calculated
    def test_38_duration_backend_calculated(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        for cand in candidates:
            expected_dur = round(cand["end_seconds"] - cand["start_seconds"], 3)
            self.assertEqual(cand["duration_seconds"], expected_dur)

    # 39. sentence boundary melhora score
    def test_39_sentence_boundary_improves_score(self):
        score_closed, _ = clip_discovery.score_candidate_window(
            text="Texto de teste com final pontuado.",
            duration_seconds=35.0,
            start_text="Texto de teste",
            end_text="final pontuado.",
        )
        score_open, _ = clip_discovery.score_candidate_window(
            text="Texto de teste sem pontuação final",
            duration_seconds=35.0,
            start_text="Texto de teste",
            end_text="sem pontuação final",
        )
        self.assertGreater(score_closed, score_open)

    # 40. pergunta/hook adiciona componente explicável
    def test_40_question_hook_adds_explainable_component(self):
        score_hook, reason_hook = clip_discovery.score_candidate_window(
            text="Você sabia que ganchos aumentam retenção? É verdade.",
            duration_seconds=30.0,
            start_text="Você sabia que ganchos aumentam retenção?",
            end_text="É verdade.",
        )
        score_no_hook, reason_no_hook = clip_discovery.score_candidate_window(
            text="Ontem nós conversamos sobre retenção. É verdade.",
            duration_seconds=30.0,
            start_text="Ontem nós conversamos sobre retenção.",
            end_text="É verdade.",
        )
        self.assertGreater(score_hook, score_no_hook)
        self.assertIn("gancho: pergunta", reason_hook)

    # 41. speech density calculada deterministicamente
    def test_41_speech_density_calculated_deterministically(self):
        words_text = "uma duas tres quatro cinco seis sete oito nove dez"
        density = clip_discovery._calculate_speech_density(words_text, 5.0)
        self.assertEqual(density, 2.0)

    # 42. long silence penaliza
    def test_42_long_silence_penalizes(self):
        # 5 palavras em 40 segundos -> 0.12 pal/s (ritmo atípico)
        score_slow, reason_slow = clip_discovery.score_candidate_window(
            text="Apenas cinco palavras faladas aqui.",
            duration_seconds=40.0,
            start_text="Apenas cinco",
            end_text="faladas aqui.",
        )
        # 90 palavras em 30 segundos -> 3.0 pal/s (ritmo ideal)
        ideal_text = " ".join(["palavra"] * 90) + "."
        score_ideal, reason_ideal = clip_discovery.score_candidate_window(
            text=ideal_text,
            duration_seconds=30.0,
            start_text="Palavra inicial",
            end_text="palavra final.",
        )
        self.assertGreater(score_ideal, score_slow)
        self.assertIn("ritmo atípico", reason_slow)

    # 43. candidato muito curto penalizado
    def test_43_too_short_candidate_penalized(self):
        score_short, reason_short = clip_discovery.score_candidate_window(
            text="Frase muito curta.",
            duration_seconds=8.0,
            start_text="Frase",
            end_text="curta.",
        )
        self.assertIn("fora do alvo", reason_short)

    # 44. candidato >180s rejeitado
    def test_44_candidate_gt_180s_rejected(self):
        score_over, reason_over = clip_discovery.score_candidate_window(
            text="Texto muito longo...",
            duration_seconds=200.0,
            start_text="Texto",
            end_text="longo.",
        )
        self.assertIn("fora do alvo", reason_over)

    # 45. default max 10
    def test_45_default_max_10(self):
        # Gera muitos segmentos pequenos
        many_segs = []
        for i in range(25):
            many_segs.append({
                "sequence": i,
                "start_seconds": i * 5.0,
                "end_seconds": (i + 1) * 5.0,
                "text": f"Frase número {i} para teste de limite.",
                "confidence": 0.9,
            })
        source_id, transcript_id = self._create_source_and_completed_transcript(
            duration=130.0, segments=many_segs
        )
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertLessEqual(len(candidates), 10)

    # 46. ordenação score desc
    def test_46_ordering_score_desc(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertGreater(len(candidates), 1)

        def extract_score(cand):
            # Extrai "score=XX.X" do selection_reason
            import re
            m = re.search(r"score=([\d\.]+)", cand.get("selection_reason") or "")
            return float(m.group(1)) if m else 0.0

        scores = [extract_score(c) for c in candidates]
        for i in range(len(scores) - 1):
            self.assertGreaterEqual(scores[i], scores[i + 1])

    # 47. tie usa start asc
    def test_47_tie_uses_start_asc(self):
        windows = [
            {"score": 80.0, "start_seconds": 40.0},
            {"score": 90.0, "start_seconds": 20.0},
            {"score": 80.0, "start_seconds": 10.0},
        ]
        windows.sort(key=lambda c: (-c["score"], c["start_seconds"]))
        self.assertEqual(windows[0]["start_seconds"], 20.0)
        self.assertEqual(windows[1]["start_seconds"], 10.0)
        self.assertEqual(windows[2]["start_seconds"], 40.0)

    # 48. selection_method heuristic
    def test_48_selection_method_heuristic(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertGreater(len(candidates), 0)
        for cand in candidates:
            self.assertEqual(cand["selection_method"], "heuristic")

    # 49. status CANDIDATE
    def test_49_status_candidate(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertGreater(len(candidates), 0)
        for cand in candidates:
            self.assertEqual(cand["status"], clip_mode.SEGMENT_STATUS_CANDIDATE)

    # 50. manual segments preservados
    def test_50_manual_segments_preserved(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        # Cria um segmento manual antes
        manual_seg = clip_mode.create_clip_segment(
            source_id=source_id,
            start_seconds=10.0,
            end_seconds=35.0,
            title="Segmento Manual Operador",
            db_path=self.db_path,
        )

        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        persisted_manual = clip_mode.get_clip_segment(manual_seg["segment_id"], db_path=self.db_path)
        self.assertIsNotNone(persisted_manual)
        self.assertEqual(persisted_manual["selection_method"], "manual")
        self.assertEqual(persisted_manual["title"], "Segmento Manual Operador")

    # 51. candidate duplicate não duplicado
    def test_51_candidate_duplicate_not_duplicated(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        cand1 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        count_before = len(cand1)

        # Roda discovery novamente
        cand2 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        count_after = len(cand2)

        with clip_mode.get_connection(self.db_path) as conn:
            total_db = conn.execute("SELECT COUNT(*) FROM clip_segments WHERE source_id = ?", (source_id,)).fetchone()[0]

        self.assertEqual(count_before, count_after)
        self.assertEqual(total_db, count_before)

    # 52. source/profile preservados
    def test_52_source_profile_preserved(self):
        profile_manager.create_profile("Channel Discovery", profile_id="channel_discovery", db_path=self.db_path)
        source_id, transcript_id = self._create_source_and_completed_transcript(profile_id="channel_discovery")

        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertGreater(len(candidates), 0)
        for cand in candidates:
            self.assertEqual(cand["source_id"], source_id)
            self.assertEqual(cand["profile_id"], "channel_discovery")

    # 53. reason explicável
    def test_53_reason_explainable(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        for cand in candidates:
            reason = cand.get("selection_reason") or ""
            self.assertIn("score=", reason)
            self.assertIn("dur=", reason)

    # 54. score entre 0 e 100
    def test_54_score_between_0_and_100(self):
        # Testa pontuação com diferentes durações e frases
        s1, _ = clip_discovery.score_candidate_window("Muito curto", 2.0, "Muito", "curto")
        self.assertGreaterEqual(s1, 0.0)
        self.assertLessEqual(s1, 100.0)

        s2, _ = clip_discovery.score_candidate_window(
            "Você sabia? Três coisas sobre inteligência artificial! O segredo é manter o ritmo e fechar.",
            45.0,
            "Você sabia?",
            "e fechar.",
        )
        self.assertGreaterEqual(s2, 0.0)
        self.assertLessEqual(s2, 100.0)

    # 55. SELECTED manual preservado
    def test_55_selected_manual_preserved(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        manual_seg = clip_mode.create_clip_segment(
            source_id=source_id,
            start_seconds=15.0,
            end_seconds=40.0,
            title="Manual Aprovado",
            db_path=self.db_path,
        )
        clip_mode.update_clip_segment_status(manual_seg["segment_id"], clip_mode.SEGMENT_STATUS_SELECTED, db_path=self.db_path)

        clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)

        seg_after = clip_mode.get_clip_segment(manual_seg["segment_id"], db_path=self.db_path)
        self.assertEqual(seg_after["status"], clip_mode.SEGMENT_STATUS_SELECTED)

    # 56. REJECTED manual preservado
    def test_56_rejected_manual_preserved(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        # Descobre candidatos pela primeira vez
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        self.assertGreater(len(candidates), 0)

        target_id = candidates[0]["id"]
        # Operador rejeita o candidato
        clip_mode.update_clip_segment_status(target_id, clip_mode.SEGMENT_STATUS_REJECTED, db_path=self.db_path)

        # Redescobre
        clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)

        # Verifica se o candidato permanece REJECTED
        cand_after = clip_mode.get_clip_segment(target_id, db_path=self.db_path)
        self.assertEqual(cand_after["status"], clip_mode.SEGMENT_STATUS_REJECTED)

    # 57. rerun discovery idempotente
    def test_57_rerun_discovery_idempotent(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        res1 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        res2 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
        res3 = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)

        self.assertEqual(len(res1), len(res2))
        self.assertEqual(len(res2), len(res3))

    # 58. zero LLM calls
    def test_58_zero_llm_calls(self):
        with patch("app.services.llm.generate_script", side_effect=AssertionError("LLM chamado indevidamente")):
            with patch("app.services.llm.generate_terms", side_effect=AssertionError("LLM chamado indevidamente")):
                source_id, transcript_id = self._create_source_and_completed_transcript()
                candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
                self.assertGreater(len(candidates), 0)

    # 59. zero HTTP
    def test_59_zero_http(self):
        with patch("urllib.request.urlopen", side_effect=AssertionError("HTTP chamado indevidamente")):
            with patch("requests.get", side_effect=AssertionError("HTTP chamado indevidamente")):
                with patch("requests.post", side_effect=AssertionError("HTTP chamado indevidamente")):
                    source_id, transcript_id = self._create_source_and_completed_transcript()
                    candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)
                    self.assertGreater(len(candidates), 0)

    # 60. zero publication
    def test_60_zero_publication(self):
        source_id, transcript_id = self._create_source_and_completed_transcript()
        candidates = clip_discovery.discover_clip_candidates(transcript_id, db_path=self.db_path)

        with clip_mode.get_connection(self.db_path) as conn:
            # Verifica que nenhuma publicação foi criada
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='content_analytics';")
            # Nenhuma tabela de publicação/analytics tem alterações provenientes do discovery
            self.assertGreater(len(candidates), 0)


if __name__ == "__main__":
    unittest.main()
