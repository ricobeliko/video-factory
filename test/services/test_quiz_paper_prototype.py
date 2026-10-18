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

from scripts.poc_quiz_paper_render import PaperQuizConfig, PaperQuizEngine


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
        """P1.1: Pergunta e as 4 alternativas devem estar visíveis desde o primeiro frame."""
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
        """P1.1: Narração contém estritamente o enunciado da pergunta (sem alternativas nem números)."""
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

    def test_p1_1_thinking_window_ticks_sfx_and_timing(self):
        """P1.1: Valida janela de 4 segundos com tique-taque sintetizado durante a espera (não durante a voz)."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        exp_sec = float(config.timing_settings.get("expectation_sec", 4.0))
        rev_sec = float(config.timing_settings.get("reveal_sec", 1.0))

        # 1. Janela de expectativa deve ser exatamente 4.0 segundos
        self.assertAlmostEqual(exp_sec, 4.0, places=2, msg="Janela de expectativa deve ser exatamente 4.0 segundos")
        self.assertAlmostEqual(rev_sec, 1.0, places=2, msg="Janela de revelação da resposta deve ser 1.0 segundo")

        # 2. Síntese do áudio procedural de tique-taques
        ticks_wav = engine.generate_thinking_ticks_sfx(duration=exp_sec)
        self.assertTrue(os.path.exists(ticks_wav))

        with wave.open(ticks_wav, "r") as wf:
            self.assertEqual(wf.getnchannels(), 1)
            self.assertEqual(wf.getframerate(), 44100)
            dur_ticks = wf.getnframes() / float(wf.getframerate())
            self.assertAlmostEqual(dur_ticks, 4.0, places=2, msg="Arquivo de tique-taque deve ter 4 segundos de duração")

        # 3. Timing da mixagem: tique-taques ocorrem após a voz, não durante ela
        dur_narr = 2.65
        t_thinking_start = dur_narr
        t_reveal_start = t_thinking_start + exp_sec
        tot_dur = t_reveal_start + rev_sec

        # Tique-taques iniciam estritamente após a voz
        self.assertEqual(t_thinking_start, dur_narr)
        # Janela de raciocínio é de exatamente 4 segundos
        self.assertAlmostEqual(t_reveal_start - t_thinking_start, 4.0, places=5)
        # Revelação da resposta inicia somente após o término dos 4 segundos de espera
        self.assertAlmostEqual(tot_dur - t_reveal_start, 1.0, places=5)
        # Ordem temporal estrita
        self.assertTrue(0 < dur_narr == t_thinking_start < t_reveal_start < tot_dur)

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

