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

    def test_paper_quiz_revelation_state_selection(self):
        """2. Valida renderização dos estados não-revelado e revelado com destaque da correta."""
        config = PaperQuizConfig.from_json(self.template_path)
        config.temp_dir = self.test_dir
        engine = PaperQuizEngine(config)

        q1 = config.questions[0]
        img_unrevealed = engine.render_question_frame(q1, revealed=False)
        img_revealed = engine.render_question_frame(q1, revealed=True)

        self.assertEqual(img_unrevealed.size, (1080, 1920))
        self.assertEqual(img_revealed.size, (1080, 1920))

        # Os dois frames devem ser diferentes devido ao destaque da resposta correta
        self.assertNotEqual(img_unrevealed.tobytes(), img_revealed.tobytes())

    def test_procedural_chime_generation(self):
        """3. Valida síntese matemática do chime harmônico de acerto."""
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
        """4. Valida geração de thumbnail independente 1080x1920 em formato JPG."""
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
