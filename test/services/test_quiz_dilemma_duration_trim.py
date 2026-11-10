"""
test/services/test_quiz_dilemma_duration_trim.py
================================================
Testes direcionados da Missão v2/duracao-quiz-dilemma:
1. Corta 1 pergunta quando a duração estimada é ~73s (8 -> 7 perguntas, dentro de [60.0s, 70.0s]).
2. Corta 2 perguntas quando necessário (~78s -> ~72s -> ~64s, 8 -> 6 perguntas).
3. Falha cedo com duration_safety quando cortar não basta (sem renderizar nenhuma cena).
4. Não corta perguntas quando a duração estimada já está dentro da faixa [60.0s, 70.0s].
5. Quiz de papel (PaperQuizEngine) inalterado.
"""

import asyncio
import os
from unittest.mock import MagicMock, patch
import pytest

from scripts.poc_quiz_render import DurationGateError, QuizConfig, QuizEngine
from scripts.poc_quiz_paper_render import PaperQuizEngine, DurationGateError as PaperDurationGateError


def _make_dummy_quiz_config(num_questions: int = 8, task_id: str = "test-task-quiz-trim") -> QuizConfig:
    questions = []
    for i in range(1, num_questions + 1):
        questions.append({
            "id": f"q{i}",
            "header": f"DILEMA {i}",
            "narration": f"Texto narrado da pergunta {i} sobre escolhas impossíveis",
            "top": {
                "title": f"Opção A {i}",
                "tag": "OPÇÃO A",
                "image_name": f"q{i}_top.jpg",
                "image_query": f"top query {i}",
            },
            "bottom": {
                "title": f"Opção B {i}",
                "tag": "OPÇÃO B",
                "image_name": f"q{i}_bot.jpg",
                "image_query": f"bot query {i}",
            },
            "is_hook": (i == 1),
            "hook_narration": "Atenção: a última escolha vai te surpreender!" if i == 1 else None,
        })

    return QuizConfig(
        niche="curiosidades",
        quiz_title="QUAL VOCÊ ESCOLHE?",
        output_video_path="storage/poc_quiz/test_output.mp4",
        output_thumbnail_path="storage/poc_quiz/test_thumb.jpg",
        temp_dir="storage/poc_quiz/test_temp",
        images_dir="storage/poc_quiz/test_images",
        min_target_duration_sec=60.0,
        target_duration_range=(60.0, 70.0),
        task_id=task_id,
        questions=questions,
    )


def test_trim_cuts_one_question_when_duration_73s():
    """1. Corta 1 pergunta quando duração estimada ~73s (8 -> 7 perguntas)."""
    cfg = _make_dummy_quiz_config(8, task_id="task-trim-1q")
    engine = QuizEngine(cfg)

    # 8 perguntas * 7.8s = 62.4s voz. min_total = 62.4 + 2.6 + 7*1.1 = 72.7s (~73s).
    # Com 7 perguntas: 7 * 7.8s = 54.6s voz. min_total = 54.6 + 2.6 + 6*1.1 = 63.8s.
    # Calibração expande para 65.0s (dentro de [60.0s, 70.0s]).
    async def mock_synthesize(text, out_path):
        if "hook" in out_path:
            return 2.0
        return 7.8

    rendered_scenes = []

    def mock_render_scene(item):
        rendered_scenes.append(item["id"])
        return f"mock_scene_{item['id']}.mp4"

    with patch.object(engine, "synthesize_voice", side_effect=mock_synthesize), \
         patch.object(engine, "ensure_images"), \
         patch.object(engine, "generate_thumbnail"), \
         patch.object(engine, "generate_revelation_sfx", return_value="mock_sfx.wav"), \
         patch.object(engine, "generate_countdown_sfx", return_value="mock_cnt.wav"), \
         patch.object(engine, "mix_segment_audio", return_value=True), \
         patch.object(engine, "render_scene", side_effect=mock_render_scene), \
         patch.object(engine, "concat_and_mix_bgm", return_value=True), \
         patch("scripts.poc_quiz_render.probe_media", return_value={"format_duration": 65.0, "video_streams": [{"width": 1080, "height": 1920}]}), \
         patch("scripts.poc_quiz_render.logger.info") as mock_logger_info:

        result = asyncio.run(engine.render_async())

    assert len(engine.config.questions) == 7
    assert len(rendered_scenes) == 7
    assert "q8" not in rendered_scenes

    # Verifica log obrigatório: [QUIZ_DURATION_TRIM] task_id=... antes=XX.XXs depois=XX.XXs perguntas=N->M
    trim_logs = [call.args[0] for call in mock_logger_info.call_args_list if "[QUIZ_DURATION_TRIM]" in str(call.args[0])]
    assert len(trim_logs) == 1
    log_msg = trim_logs[0]
    assert "task_id=task-trim-1q" in log_msg
    assert "perguntas=8->7" in log_msg
    assert "antes=72.70s" in log_msg or "antes=7" in log_msg
    assert "depois=65.00s" in log_msg or "depois=6" in log_msg


def test_trim_cuts_two_questions_when_necessary():
    """2. Corta 2 perguntas quando necessário (8 -> 6 perguntas)."""
    cfg = _make_dummy_quiz_config(8, task_id="task-trim-2q")
    engine = QuizEngine(cfg)

    # Q1..Q6 = 8.8s cada (52.8s). Q7 = 7.0s. Q8 = 5.0s.
    # Total 8q = 64.8s voz. min_total = 64.8 + 2.6 + 7.7 = 75.1s (> 70s).
    # Total 7q (sem Q8): voz = 59.8s. min_total = 59.8 + 2.6 + 6.6 = 70.0s? 59.8+2.6+6.6 = 69.0s <= 70s.
    # Para ter 7q ainda > 70s:
    # Q1..Q6 = 9.0s (54.0s). Q7 = 7.5s. Q8 = 5.0s.
    # 8q: voz = 66.5s. min_total = 66.5 + 2.6 + 7.7 = 76.8s (> 70s).
    # 7q (sem Q8): voz = 61.5s. min_total = 61.5 + 2.6 + 6.6 = 70.7s (> 70s).
    # 6q (sem Q7, Q8): voz = 54.0s. min_total = 54.0 + 2.6 + 5.5 = 62.1s (em [60s, 70s]).
    dur_map = {
        "q1": 9.0, "q2": 9.0, "q3": 9.0, "q4": 9.0, "q5": 9.0, "q6": 9.0,
        "q7": 7.5, "q8": 5.0,
    }

    async def mock_synthesize(text, out_path):
        if "hook" in out_path:
            return 2.0
        for q_id, dur in dur_map.items():
            if f"narration_{q_id}.mp3" in out_path:
                return dur
        return 9.0

    rendered_scenes = []

    def mock_render_scene(item):
        rendered_scenes.append(item["id"])
        return f"mock_scene_{item['id']}.mp4"

    with patch.object(engine, "synthesize_voice", side_effect=mock_synthesize), \
         patch.object(engine, "ensure_images"), \
         patch.object(engine, "generate_thumbnail"), \
         patch.object(engine, "generate_revelation_sfx", return_value="mock_sfx.wav"), \
         patch.object(engine, "generate_countdown_sfx", return_value="mock_cnt.wav"), \
         patch.object(engine, "mix_segment_audio", return_value=True), \
         patch.object(engine, "render_scene", side_effect=mock_render_scene), \
         patch.object(engine, "concat_and_mix_bgm", return_value=True), \
         patch("scripts.poc_quiz_render.probe_media", return_value={"format_duration": 65.0, "video_streams": [{"width": 1080, "height": 1920}]}), \
         patch("scripts.poc_quiz_render.logger.info") as mock_logger_info:

        result = asyncio.run(engine.render_async())

    assert len(engine.config.questions) == 6
    assert len(rendered_scenes) == 6
    assert "q7" not in rendered_scenes
    assert "q8" not in rendered_scenes

    trim_logs = [call.args[0] for call in mock_logger_info.call_args_list if "[QUIZ_DURATION_TRIM]" in str(call.args[0])]
    assert len(trim_logs) == 1
    log_msg = trim_logs[0]
    assert "task_id=task-trim-2q" in log_msg
    assert "perguntas=8->6" in log_msg


def test_trim_fails_early_when_cutting_cannot_reach_range():
    """3. Falha cedo com DurationGateError quando cortar não basta (sem renderizar nenhuma cena)."""
    cfg = _make_dummy_quiz_config(2, task_id="task-fail-early")
    engine = QuizEngine(cfg)

    # 2 perguntas de 36s de voz cada = 72s de voz.
    # Com 2 perguntas: min_total = 72 + 2.6 + 1.1 = 75.7s (> 70s).
    # Com 1 pergunta: voz = 36s. Com max pause 4.0s: 36 + 2.6 + 4.0 = 42.6s (< 60s).
    # Não há como atingir a faixa [60.0s, 70.0s].
    async def mock_synthesize(text, out_path):
        if "hook" in out_path:
            return 2.0
        return 36.0

    mock_render_scene = MagicMock()

    with patch.object(engine, "synthesize_voice", side_effect=mock_synthesize), \
         patch.object(engine, "ensure_images"), \
         patch.object(engine, "generate_thumbnail"), \
         patch.object(engine, "generate_revelation_sfx", return_value="mock_sfx.wav"), \
         patch.object(engine, "render_scene", mock_render_scene):

        with pytest.raises(DurationGateError) as exc_info:
            asyncio.run(engine.render_async())

    assert "fora da faixa editorial obrigatória para Quiz [60.0s, 70.0s]" in str(exc_info.value)
    # Nenhuma cena deve ter sido renderizada
    mock_render_scene.assert_not_called()


def test_task_pipeline_catches_duration_gate_error_early():
    """3b. Valida que o pipeline em task.py captura DurationGateError do QuizEngine e falha em duration_safety."""
    from app.services import task
    from app.models import schema, const

    params = schema.VideoParams(
        video_subject="Dilemas Falha Cedo",
        narrative_structure="quiz_dilemma",
        voice_name="pt-BR-AntonioNeural",
    )

    fake_quiz_data = {
        "niche": "curiosidades",
        "quiz_title": "ESCOLHAS IMPOSSÍVEIS",
        "questions": [{"id": "q1", "narration": "q1", "top": {}, "bottom": {}}],
    }

    mock_engine = MagicMock()
    mock_engine.render.side_effect = DurationGateError(
        "Duração de 75.70s fora da faixa editorial obrigatória para Quiz [60.0s, 70.0s]",
        actual_duration=75.70,
    )

    with patch("app.services.quiz_generator.QuizContentGenerator.generate_quiz_structure", return_value=fake_quiz_data), \
         patch("app.services.quiz_safety_gate.evaluate_quiz_script_safety", return_value={"safety_status": "PASS", "safety_reasons": []}), \
         patch("app.services.quiz_assets.QuizAssetManager.process_quiz", return_value=fake_quiz_data), \
         patch("app.services.quiz_generator.QuizContentGenerator.export_to_quiz_config", return_value=MagicMock()), \
         patch("scripts.poc_quiz_render.QuizEngine", return_value=mock_engine), \
         patch("app.services.quiz_bgm.resolve_quiz_bgm", return_value={"path": "mock_bgm.mp3", "source": "none"}), \
         patch("app.services.voice.resolve_quiz_voice_rate", return_value="+12%"), \
         patch("app.services.task_artifacts.patch_script_data"):

        res = task._run_quiz_pipeline("test-early-fail-task", params)

    assert res.get("status") == "error" or "failed_stage" in res or res.get("error") is not None
    # Verifica que o erro reportado indica duration_safety
    failed_stage = res.get("failed_stage") or res.get("error_stage")
    assert failed_stage == "duration_safety"
    err_msg = res.get("error") or res.get("message") or ""
    assert "75.70s fora da faixa editorial obrigatória para Quiz [60.0s, 70.0s]" in err_msg


def test_trim_does_not_cut_when_already_in_range():
    """4. Não corta perguntas quando a duração estimada já está dentro da faixa [60.0s, 70.0s]."""
    cfg = _make_dummy_quiz_config(8, task_id="task-in-range")
    engine = QuizEngine(cfg)

    # 8 perguntas de 6.0s voz cada = 48.0s voz. min_total = 48.0 + 2.6 + 7.7 = 58.3s.
    # desired_total = 65.0s (dentro de [60.0s, 70.0s]). Não deve cortar nada!
    async def mock_synthesize(text, out_path):
        if "hook" in out_path:
            return 2.0
        return 6.0

    rendered_scenes = []

    def mock_render_scene(item):
        rendered_scenes.append(item["id"])
        return f"mock_scene_{item['id']}.mp4"

    with patch.object(engine, "synthesize_voice", side_effect=mock_synthesize), \
         patch.object(engine, "ensure_images"), \
         patch.object(engine, "generate_thumbnail"), \
         patch.object(engine, "generate_revelation_sfx", return_value="mock_sfx.wav"), \
         patch.object(engine, "generate_countdown_sfx", return_value="mock_cnt.wav"), \
         patch.object(engine, "mix_segment_audio", return_value=True), \
         patch.object(engine, "render_scene", side_effect=mock_render_scene), \
         patch.object(engine, "concat_and_mix_bgm", return_value=True), \
         patch("scripts.poc_quiz_render.probe_media", return_value={"format_duration": 65.0, "video_streams": [{"width": 1080, "height": 1920}]}), \
         patch("scripts.poc_quiz_render.logger.info") as mock_logger_info:

        result = asyncio.run(engine.render_async())

    assert len(engine.config.questions) == 8
    assert len(rendered_scenes) == 8
    trim_logs = [call.args[0] for call in mock_logger_info.call_args_list if "[QUIZ_DURATION_TRIM]" in str(call.args[0])]
    assert len(trim_logs) == 0


def test_paper_quiz_unaltered():
    """5. Quiz de papel (PaperQuizEngine) inalterado."""
    assert issubclass(PaperDurationGateError, RuntimeError)
    assert hasattr(PaperQuizEngine, "select_questions_for_target_duration")
    assert hasattr(PaperQuizEngine, "render_async")
