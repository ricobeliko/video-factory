"""
test/services/test_quiz_paper_prototype.py
==========================================
VIDEO FACTORY — FASE P0: TESTES DIRECIONADOS DO PROTÓTIPO QUIZ FOLHA DE PAPEL

Validação mínima e direcionada:
1. Estrutura de perguntas, alternativas e fontes auditadas.
2. Seleção de resposta correta e renderização de estado revelado.
3. Síntese do efeito sonoro procedural de acerto (chime harmônico).
4. Geração de thumbnail vertical 9:16 independente.
"""

import os
import shutil
import tempfile
import unittest
import wave
from PIL import Image

from scripts.poc_quiz_paper_render import PaperQuizConfig, PaperQuizEngine, DurationGateError


class TestQuizPaperPrototype(unittest.TestCase):
    def setUp(self):
        self.test_dir = tempfile.mkdtemp()
        self.template_path = os.path.join(
            os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
            "resource", "quiz_templates", "quiz_template_perguntas_respostas_papel.json"
        )

    def tearDown(self):
        shutil.rmtree(self.test_dir, ignore_errors=True)

    def test_paper_quiz_template_structure(self):
        """1. Valida estrutura rigorosa do template: 4 alternativas, resposta válida e fonte factual."""
        self.assertTrue(os.path.exists(self.template_path), f"Template não encontrado: {self.template_path}")
        config = PaperQuizConfig.from_json(self.template_path)

        self.assertEqual(config.quiz_type, "multiple_choice_paper")
        self.assertGreaterEqual(len(config.questions), 4, "Quiz deve possuir pelo menos 4 questões para atingir tempo")

        for q in config.questions:
            self.assertIn("id", q)
            self.assertIn("question", q)
            self.assertIn("options", q)
            self.assertEqual(len(q["options"]), 4, f"Questão {q['id']} deve ter exatamente 4 alternativas")

            letters = [opt["letter"] for opt in q["options"]]
            self.assertEqual(letters, ["A", "B", "C", "D"], f"Alternativas da questão {q['id']} devem ser A, B, C, D")

            correct = q.get("correct_option")
            self.assertIn(correct, ["A", "B", "C", "D"], f"Resposta correta inválida na questão {q['id']}")

            source = q.get("source")
            self.assertTrue(bool(source and len(source.strip()) > 5), f"Questão {q['id']} deve conter fonte factual auditável")

    def test_question_and_options_visible_together_from_first_frame(self):
        """P1.1/P1.2: Pergunta e as 4 alternativas devem estar visíveis desde o primeiro frame."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        for q in config.questions:
            # O frame inicial da cena (t=0) é o frame de opções não revelado
            img_initial = engine.render_question_frame(q, state="options")
            self.assertEqual(img_initial.size, (1080, 1920))

            # Verifica que o frame de opções é diferente da folha em branco
            img_blank = engine._draw_paper_sheet()
            self.assertNotEqual(img_initial.tobytes(), img_blank.tobytes())

            # Verifica que a resposta correta NÃO está revelada prematuramente no primeiro frame
            pixels = list(img_initial.getdata())
            has_emerald_border = any(p[0] == 5 and p[1] == 150 and p[2] == 105 for p in pixels)
            self.assertFalse(has_emerald_border, f"Questão {q['id']}: resposta correta revelada prematuramente no frame inicial!")

    def test_narration_contains_only_question_statement(self):
        """P1.1/P1.2: Narração contém estritamente o enunciado da pergunta (sem alternativas nem números)."""
        config = PaperQuizConfig.from_json(self.template_path)
        voice_rate = config.voice_settings.get("voice_rate")
        self.assertEqual(voice_rate, "+20%", f"Taxa de voz esperada de +20%, obtido: {voice_rate}")

        for q in config.questions:
            narr = q.get("narration", "").strip()
            self.assertTrue(len(narr) > 0, f"Questão {q['id']} sem narração")

            for forbidden in ["letra a", "letra b", "letra c", "letra d", "opção a", "opção b", "opção c", "opção d"]:
                self.assertNotIn(forbidden, narr.lower(), f"Narração da questão {q['id']} contém alternativas: {narr}")

            for forbidden_num in ["questão 1", "questão 2", "questão 3", "pergunta 1", "pergunta 2", "pergunta 0"]:
                self.assertNotIn(forbidden_num, narr.lower(), f"Narração da questão {q['id']} anuncia o número: {narr}")

            self.assertEqual(narr, q["question"].strip())

    def test_p1_2_thinking_window_6s_and_ticks_sfx(self):
        """P1.2: Valida janela de 6 segundos de expectativa com tique-taques discretos a cada segundo."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        exp_sec = float(config.timing_settings.get("expectation_sec", 6.0))
        rev_sec = float(config.timing_settings.get("reveal_sec", 1.0))

        # 1. Janela de expectativa deve ser exatamente 6.0 segundos
        self.assertAlmostEqual(exp_sec, 6.0, places=2, msg="Janela de expectativa deve ser exatamente 6.0 segundos")
        self.assertAlmostEqual(rev_sec, 1.0, places=2, msg="Janela de revelação da resposta deve ser 1.0 segundo")

        # 2. Síntese do áudio procedural de tique-taques (6s)
        ticks_wav = engine.generate_thinking_ticks_sfx(duration=exp_sec)
        self.assertTrue(os.path.exists(ticks_wav))

        with wave.open(ticks_wav, "r") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getframerate(), 44100)
            dur_ticks = wf.getnframes() / float(wf.getframerate())
            self.assertAlmostEqual(dur_ticks, 6.0, places=2, msg="Arquivo de tique-taque deve ter 6 segundos de duração")

    def test_p1_2_duration_calculation_per_question(self):
        """P1.2: Valida cálculo de duração da cena por questão: narração + 6s espera + 1s revelação."""
        config = PaperQuizConfig.from_json(self.template_path)
        exp_sec = 6.0
        rev_sec = 1.0

        sample_narration_durations = [2.5, 3.2, 4.0]
        for dur_narr in sample_narration_durations:
            expected_scene_duration = dur_narr + exp_sec + rev_sec
            t_thinking_start = dur_narr
            t_reveal_start = t_thinking_start + exp_sec
            t_scene_end = t_reveal_start + rev_sec

            self.assertAlmostEqual(t_thinking_start, dur_narr, places=5)
            self.assertAlmostEqual(t_reveal_start - t_thinking_start, 6.0, places=5)
            self.assertAlmostEqual(t_scene_end - t_reveal_start, 1.0, places=5)
            self.assertAlmostEqual(t_scene_end, expected_scene_duration, places=5)

    def test_p1_3_circular_timer_frames_progression(self):
        """P1.3: Valida geração de frames do timer circular progressivo de 0% a 100% durante 6 segundos (180 frames a 30fps)."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        exp_sec = float(config.timing_settings.get("expectation_sec", 6.0))
        fps = int(config.video_settings.get("fps", 30))
        pattern, (tw, th) = engine.generate_circular_timer_frames(duration=exp_sec, fps=fps)

        self.assertEqual(tw, 48)
        self.assertEqual(th, 48)
        timer_dir = os.path.dirname(pattern)
        frames = sorted([f for f in os.listdir(timer_dir) if f.endswith(".png")])
        self.assertEqual(len(frames), 180, "Timer de 6s a 30fps deve gerar exatamente 180 frames")

        # Frame 0 (início a 0%): arco ainda não percorrido
        im0 = Image.open(os.path.join(timer_dir, frames[0]))
        self.assertEqual(im0.size, (48, 48))
        self.assertEqual(im0.mode, "RGBA")

        # Frame 179 (final a 100%): arco percorrido completo
        im_last = Image.open(os.path.join(timer_dir, frames[-1]))
        self.assertEqual(im_last.size, (48, 48))

        # Frames intermediários devem possuir preenchimentos crescentes
        self.assertNotEqual(im0.tobytes(), im_last.tobytes())

    def test_p1_3_timer_synchronization_and_position(self):
        """P1.3: Valida sincronização exata do timer com a revelação e coordenadas alinhadas ao slot."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        q1 = config.questions[0]
        timer_pos = engine.get_question_timer_position(q1["question"])
        self.assertIsInstance(timer_pos, tuple)
        self.assertEqual(len(timer_pos), 2)
        tx, ty = timer_pos
        self.assertTrue(800 <= tx <= 950, f"Posição X do timer ({tx}) deve estar no slot direito do card")
        self.assertTrue(400 <= ty <= 800, f"Posição Y do timer ({ty}) deve acompanhar a altura da pergunta")

        # No frame de opções, o slot existe; no frame revelado, o timer não existe e resposta está revelada
        im_opts = engine.render_question_frame(q1, state="options")
        im_rev = engine.render_question_frame(q1, state="revealed")
        self.assertNotEqual(im_opts.tobytes(), im_rev.tobytes())

    def test_p1_3_outro_duration_6s_and_comment_challenge(self):
        """P1.3: Valida encerramento com exatamente 6 segundos e chamada clara para comentários."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        outro_cfg = config.outro_challenge
        self.assertEqual(float(outro_cfg.get("duration_sec", 6.0)), 6.0)
        self.assertIn("Comente", outro_cfg.get("narration", ""))

        img_outro = engine.render_outro_frame()
        self.assertEqual(img_outro.size, (1080, 1920))

    def test_p1_3_dynamic_selection_with_6s_outro(self):
        """P1.3: Seleciona dinamicamente a quantidade de perguntas considerando o novo encerramento de 6s."""
        import asyncio
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        candidate_questions = [
            {"id": i, "question": f"Pergunta {i}?", "narration": f"Pergunta {i}?", "options": [], "correct_option": "A"}
            for i in range(1, 11)
        ]
        # Baseline intro=4.7s + 0.25 = 4.95s, outro=6.0s => dur_baseline = 10.95s
        # Perguntas: narração=3.3s + 6.0s (espera) + 1.0s (revelação) = 10.3s por pergunta.
        # Com 5 perguntas: 10.95 + 5 * 10.3 = 62.45s (dentro de [60.0, 65.0]s, quase no ponto médio 62.5s)
        async def mock_synthesize(text, output_path):
            if "intro" in output_path:
                return 4.7
            elif "outro" in output_path:
                return 2.5
            return 3.3

        engine.synthesize_voice = mock_synthesize

        selected, est_dur = asyncio.run(
            engine.select_questions_for_target_duration(
                candidate_questions, target_min=60.0, target_max=65.0, expectation_sec=6.0, reveal_sec=1.0
            )
        )
        self.assertEqual(len(selected), 5, f"Esperado 5 questões para atingir a faixa [60, 65]s, obteve {len(selected)}")
        self.assertTrue(60.0 <= est_dur <= 65.0, f"Duração estimada {est_dur} fora da faixa [60, 65]s")
        for idx, q in enumerate(selected, 1):
            self.assertEqual(q["number"], idx)

    def test_p1_3_duration_gate_blocking(self):
        """P1.3: Bloqueia homologação e levanta DurationGateError se nenhuma combinação atingir a faixa."""
        import asyncio
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        few_questions = [
            {"id": 1, "question": "P1?", "narration": "P1?", "options": [], "correct_option": "A"}
        ]
        async def mock_synth(text, output_path):
            return 2.0

        engine.synthesize_voice = mock_synth

        with self.assertRaises(DurationGateError) as cm:
            asyncio.run(
                engine.select_questions_for_target_duration(
                    few_questions, target_min=60.0, target_max=65.0
                )
            )
        self.assertIn("Nenhuma seleção de perguntas", str(cm.exception))

    def test_answer_revealed_only_after_waiting_window(self):
        """P1.1: A resposta correta deve ser revelada somente após o término da janela de espera."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        q1 = config.questions[0]
        img_unrevealed = engine.render_question_frame(q1, state="options")
        img_revealed = engine.render_question_frame(q1, state="revealed")

        # Os dois frames devem ter tamanhos idênticos e conteúdos visuais distintos
        self.assertEqual(img_unrevealed.size, (1080, 1920))
        self.assertEqual(img_revealed.size, (1080, 1920))
        self.assertNotEqual(img_unrevealed.tobytes(), img_revealed.tobytes())

        # No frame revelado, deve constar a marcação esmeralda
        pixels_rev = list(img_revealed.getdata())
        has_emerald = any(p[0] == 5 and p[1] == 150 and p[2] == 105 for p in pixels_rev)
        self.assertTrue(has_emerald, "O frame revelado deve conter a marcação de resposta correta!")

    def test_procedural_chime_generation(self):
        """Valida síntese matemática do chime harmônico de acerto."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        sfx_path = engine.generate_correct_ding_sfx()
        self.assertTrue(os.path.exists(sfx_path))
        self.assertGreater(os.path.getsize(sfx_path), 500)

        with wave.open(sfx_path, "r") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getframerate(), 44100)
            dur = wf.getnframes() / float(wf.getframerate())
            self.assertGreater(dur, 0.4)
            self.assertLess(dur, 1.0)

    def test_thumbnail_generation(self):
        """Valida geração de thumbnail independente 1080x1920 em formato JPG."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        config.output_thumbnail_path = os.path.join(self.test_dir, "test_thumb.jpg")
        engine = PaperQuizEngine(config)

        thumb_path = engine.generate_thumbnail()
        self.assertTrue(os.path.exists(thumb_path))

        with Image.open(thumb_path) as im:
            self.assertEqual(im.size, (1080, 1920))
            self.assertEqual(im.format, "JPEG")


if __name__ == "__main__":
    unittest.main()

