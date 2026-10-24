"""
Testes direcionados para a Missão M:
Identificação de canais e formatos no Gerenciador de Tarefas e Agenda de Publicação.
"""
import os
import json
import sqlite3
import pytest
from app.models import const
from app.services import profile_manager, scheduler, safety_gate


@pytest.fixture
def test_env(tmp_path):
    db_file = str(tmp_path / "test_video_factory.db")
    profile_manager.init_profile_db(db_file)
    scheduler.init_db(db_file)

    # Cria perfis de teste
    with profile_manager.get_connection(db_file) as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO content_profiles (id, name, slug, niche, language, region, default_preset, growth_mode, is_active, created_at, updated_at)
            VALUES
            ('default', 'Video Factory Default', 'default', 'curiosidades', 'pt-BR', 'BR', 'cross_platform', 'warmup', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('profile-4d18bf9a5d94', 'Dose Diária de Escolhas', 'escolhas', 'quiz', 'pt-BR', 'BR', 'cross_platform', 'scale', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('profile-45cee883f80a', 'Quiz_Quiz', 'quiz-quiz', 'quiz', 'pt-BR', 'BR', 'cross_platform', 'scale', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('profile-historias-misterio', 'Dose Diária de Histórias e Mistério', 'historias-misterio', 'historias_misterio', 'pt-BR', 'BR', 'cross_platform', 'warmup', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('profile-gta-vi', 'Dose Diária de GTA VI', 'gta-vi', 'games', 'pt-BR', 'BR', 'cross_platform', 'warmup', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO publishing_channels (id, profile_id, platform, display_name, is_enabled, created_at, updated_at)
            VALUES
            ('channel-default-youtube', 'default', 'youtube', 'Dose Diária De Internet', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('channel-default-tiktok', 'default', 'tiktok', 'TikTok (Default)', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('channel-escolhas-yt', 'profile-4d18bf9a5d94', 'youtube', 'Dose Diária de Escolhas (YouTube)', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('channel-escolhas-tt', 'profile-4d18bf9a5d94', 'tiktok', 'Dose Diária de Escolhas (TikTok)', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('channel-quiz-yt', 'profile-45cee883f80a', 'youtube', 'Quiz_Quiz (YouTube)', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z'),
            ('channel-mystery-yt', 'profile-historias-misterio', 'youtube', 'Dose Diária de Histórias e Mistério (YouTube)', 1, '2026-10-24T00:00:00Z', '2026-10-24T00:00:00Z');
            """
        )
        conn.execute(
            """
            INSERT OR REPLACE INTO task_profiles (task_id, profile_id, created_at)
            VALUES
            ('task-paper-1', 'profile-45cee883f80a', '2026-10-24T00:00:00Z'),
            ('task-dilemma-1', 'profile-4d18bf9a5d94', '2026-10-24T00:00:00Z'),
            ('task-mystery-1', 'profile-historias-misterio', '2026-10-24T00:00:00Z'),
            ('task-default-1', 'default', '2026-10-24T00:00:00Z');
            """
        )

    # Cria tarefas com arquivos script.json em pasta isolada
    tasks_dir = tmp_path / "tasks"
    tasks_dir.mkdir()

    # 1. Tarefa Quiz de Papel
    t_paper = tasks_dir / "task-paper-1"
    t_paper.mkdir()
    with open(t_paper / "script.json", "w", encoding="utf-8") as f:
        json.dump({
            "script": "Qual destes animais você conhece?",
            "params": {
                "narrative_structure": "quiz_paper",
                "video_format": "quiz_paper",
            }
        }, f)

    # 2. Tarefa Quiz de Escolhas
    t_dilemma = tasks_dir / "task-dilemma-1"
    t_dilemma.mkdir()
    with open(t_dilemma / "script.json", "w", encoding="utf-8") as f:
        json.dump({
            "script": "O que você prefere?",
            "params": {
                "narrative_structure": "quiz_dilemma",
                "video_format": "quiz_dilemma",
            }
        }, f)

    # 3. Tarefa Tradicional (Mistério)
    t_mystery = tasks_dir / "task-mystery-1"
    t_mystery.mkdir()
    with open(t_mystery / "script.json", "w", encoding="utf-8") as f:
        json.dump({
            "script": "O mistério do navio fantasma Mary Celeste.",
            "params": {
                "narrative_structure": "mystery",
                "video_format": "traditional",
            }
        }, f)

    return {
        "db_path": db_file,
        "tasks_dir": str(tasks_dir),
    }


def test_task_real_structure_paper_quiz(test_env):
    """1. Valida que Quiz de Papel é identificado como 'Quiz de Papel / Perguntas & Respostas'."""
    task_path = os.path.join(test_env["tasks_dir"], "task-paper-1")
    s_id, s_name = profile_manager.get_task_real_structure(task_path=task_path)
    assert s_id == const.STRUCTURE_QUIZ_PAPER
    assert s_name == "Quiz de Papel / Perguntas & Respostas"

    # Mesmo com fallback incorreto no safety_info ('quiz_dilemma'), a fonte histórica script.json prevalece
    s_id_override, s_name_override = profile_manager.get_task_real_structure(
        task_path=task_path,
        safety_info={"narrative_structure": "quiz_dilemma"}
    )
    assert s_id_override == const.STRUCTURE_QUIZ_PAPER
    assert s_name_override == "Quiz de Papel / Perguntas & Respostas"


def test_task_real_structure_dilemma_quiz(test_env):
    """2. Valida que Quiz de Escolhas é identificado como 'Quiz / Escolhas Impossíveis'."""
    task_path = os.path.join(test_env["tasks_dir"], "task-dilemma-1")
    s_id, s_name = profile_manager.get_task_real_structure(task_path=task_path)
    assert s_id == const.STRUCTURE_QUIZ_DILEMMA
    assert s_name == "Quiz / Escolhas Impossíveis"


def test_task_real_structure_traditional(test_env):
    """3. Valida que formatos tradicionais mantêm seus rótulos existentes (ex: Mistério Investigativo)."""
    task_path = os.path.join(test_env["tasks_dir"], "task-mystery-1")
    s_id, s_name = profile_manager.get_task_real_structure(task_path=task_path)
    assert s_id == const.STRUCTURE_MYSTERY
    assert s_name == "Mistério Investigativo"


def test_task_origin_channel_resolution(test_env):
    """4. Valida resolução do canal responsável via task_profiles -> content_profiles.name."""
    db_path = test_env["db_path"]

    # Quiz_Quiz
    ch_paper = profile_manager.get_task_origin_channel_name("task-paper-1", db_path=db_path)
    assert ch_paper == "Quiz_Quiz"

    # Dose Diária de Escolhas
    ch_dilemma = profile_manager.get_task_origin_channel_name("task-dilemma-1", db_path=db_path)
    assert ch_dilemma == "Dose Diária de Escolhas"

    # Dose Diária de Histórias e Mistério
    ch_mystery = profile_manager.get_task_origin_channel_name("task-mystery-1", db_path=db_path)
    assert ch_mystery == "Dose Diária de Histórias e Mistério"

    # Default -> Dose Diária De Internet
    ch_default = profile_manager.get_task_origin_channel_name("task-default-1", db_path=db_path)
    assert ch_default == "Dose Diária De Internet"

    # Batch resolution
    batch = profile_manager.get_tasks_origin_channel_names(
        ["task-paper-1", "task-dilemma-1", "task-mystery-1", "task-non-existent"],
        db_path=db_path,
    )
    assert batch["task-paper-1"] == "Quiz_Quiz"
    assert batch["task-dilemma-1"] == "Dose Diária de Escolhas"
    assert batch["task-mystery-1"] == "Dose Diária de Histórias e Mistério"
    assert batch["task-non-existent"] == "Canal não identificado"


def test_task_origin_channel_missing_or_invalid(test_env):
    """5. Valida que dados ausentes apresentam 'Canal não identificado' sem inferência indevida."""
    db_path = test_env["db_path"]
    assert profile_manager.get_task_origin_channel_name("task-unlinked-999", db_path=db_path) == "Canal não identificado"
    assert profile_manager.get_task_origin_channel_name("", db_path=db_path) == "Canal não identificado"
    assert profile_manager.get_task_origin_channel_name(None, db_path=db_path) == "Canal não identificado"


def test_upcoming_posts_destination_channel_resolution(test_env):
    """6. Valida identificação do canal de destino e suporte a múltiplos destinos."""
    db_path = test_env["db_path"]

    posts = [
        {"id": 1, "task_id": "task-paper-1", "platform": "youtube", "channel_id": "channel-quiz-yt"},
        {"id": 2, "task_id": "task-dilemma-1", "platform": "tiktok", "channel_id": "channel-escolhas-tt"},
        # Mesma tarefa (task-dilemma-1), mas destino diferente (YouTube)
        {"id": 3, "task_id": "task-dilemma-1", "platform": "youtube", "channel_id": "channel-escolhas-yt"},
        # Canal default no YouTube
        {"id": 4, "task_id": "task-default-1", "platform": "youtube", "channel_id": "channel-default-youtube"},
        # Canal default no TikTok
        {"id": 5, "task_id": "task-default-1", "platform": "tiktok", "channel_id": "channel-default-tiktok"},
    ]

    dest_map = profile_manager.get_posts_destination_channel_names(posts, db_path=db_path)

    assert dest_map[1] == "Quiz_Quiz"
    assert dest_map[2] == "Dose Diária de Escolhas"
    assert dest_map[3] == "Dose Diária de Escolhas"
    assert dest_map[4] == "Dose Diária De Internet"
    assert dest_map[5] == "Dose Diária De Internet"


def test_upcoming_posts_missing_destination(test_env):
    """7. Valida que post sem channel_id ou inconsistente retorna 'Destino não identificado'."""
    db_path = test_env["db_path"]

    posts = [
        {"id": 10, "task_id": "task-1", "platform": "youtube", "channel_id": None},
        {"id": 11, "task_id": "task-2", "platform": "tiktok", "channel_id": ""},
        {"id": 12, "task_id": "task-3", "platform": "youtube", "channel_id": "channel-inexistente-123"},
    ]

    dest_map = profile_manager.get_posts_destination_channel_names(posts, db_path=db_path)
    assert dest_map[10] == "Destino não identificado"
    assert dest_map[11] == "Destino não identificado"
    assert dest_map[12] == "Destino não identificado"

    # Função individual
    assert profile_manager.get_post_destination_channel_name(posts[0], db_path=db_path) == "Destino não identificado"
    assert profile_manager.get_post_destination_channel_name({}, db_path=db_path) == "Destino não identificado"


def test_channel_filter_discovery_and_behavior(test_env):
    """8. Valida descoberta dinâmica das opções de canal e filtragem visual estrita."""
    db_path = test_env["db_path"]

    options = profile_manager.get_all_channel_filter_options(db_path=db_path)

    # 1. Opção padrão sempre é 'Todos os canais'
    assert options[0] == "Todos os canais"

    # 2. Descoberta dinâmica dos canais cadastrados
    assert "Dose Diária De Internet" in options
    assert "Dose Diária de Escolhas" in options
    assert "Quiz_Quiz" in options
    assert "Dose Diária de Histórias e Mistério" in options
    assert "Dose Diária de GTA VI" in options

    # 3. Simulação da filtragem visual
    upcoming_posts = [
        {"id": 1, "task_id": "t1", "channel_id": "channel-quiz-yt", "scheduled_at": "2026-10-25T10:00:00Z"},
        {"id": 2, "task_id": "t2", "channel_id": "channel-escolhas-yt", "scheduled_at": "2026-10-25T12:00:00Z"},
        {"id": 3, "task_id": "t3", "channel_id": "channel-quiz-yt", "scheduled_at": "2026-10-25T14:00:00Z"},
    ]
    dest_map = profile_manager.get_posts_destination_channel_names(upcoming_posts, db_path=db_path)

    # Filtro 'Todos os canais' preserva a lista completa e ordem cronológica
    filtered_all = upcoming_posts
    assert len(filtered_all) == 3
    assert [p["id"] for p in filtered_all] == [1, 2, 3]

    # Filtro 'Quiz_Quiz' retorna apenas posts 1 e 3
    filtered_quiz = [p for p in upcoming_posts if dest_map.get(p["id"]) == "Quiz_Quiz"]
    assert len(filtered_quiz) == 2
    assert [p["id"] for p in filtered_quiz] == [1, 3]

    # Filtro 'Dose Diária de Escolhas' retorna apenas post 2
    filtered_escolhas = [p for p in upcoming_posts if dest_map.get(p["id"]) == "Dose Diária de Escolhas"]
    assert len(filtered_escolhas) == 1
    assert [p["id"] for p in filtered_escolhas] == [2]

    # Filtro para canal sem posts agendados retorna lista vazia
    filtered_empty = [p for p in upcoming_posts if dest_map.get(p["id"]) == "Dose Diária de GTA VI"]
    assert len(filtered_empty) == 0
