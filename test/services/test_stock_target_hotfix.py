import os
import tempfile
import pytest

from app.services import autonomous_production, operator_console, profile_manager, scheduler


@pytest.fixture
def isolated_db():
    temp_dir = tempfile.mkdtemp(prefix="test_stock_target_")
    db_path = os.path.join(temp_dir, "test_video_factory.db")
    scheduler.init_db(db_path)
    profile_manager.init_profile_db(db_path)
    old_role = getattr(operator_console, "_current_role", None)
    operator_console._current_role = operator_console.ROLE_PRIMARY
    yield db_path
    operator_console._current_role = old_role


def test_stock_target_clamping_and_read_write_specific_profile(isolated_db):
    """Garante que para perfis específicos (ex: Quiz), a meta de 10 seja persistida,

    lida e respeitada no status sem truncamento em 6.
    """
    quiz_profile_id = "profile-quiz-escolhas"

    # 1. Gravação com meta 10
    autonomous_production.set_target_ready_stock(10, profile_id=quiz_profile_id, db_path=isolated_db)

    # 2. Leitura direta
    target = autonomous_production.get_target_ready_stock(profile_id=quiz_profile_id, db_path=isolated_db)
    assert target == 10, f"Esperado target 10, obtido {target}"

    # 3. Leitura via get_autonomous_ready_stock
    ready_stock_info = autonomous_production.get_autonomous_ready_stock(
        profile_id=quiz_profile_id, db_path=isolated_db
    )
    assert ready_stock_info["target_stock"] == 10

    # 4. Leitura via get_autonomous_status
    status = autonomous_production.get_autonomous_status(
        profile_id=quiz_profile_id, db_path=isolated_db
    )
    assert status["target_ready_stock"] == 10

    # 5. Leitura via get_autonomous_production_status_op (usado no card do Console Operacional)
    op_status = operator_console.get_autonomous_production_status_op(
        profile_id=quiz_profile_id, db_path=isolated_db
    )
    assert op_status["target_ready_stock"] == 10

    # 6. Clamping mínimo (1 -> 3)
    autonomous_production.set_target_ready_stock(1, profile_id=quiz_profile_id, db_path=isolated_db)
    assert autonomous_production.get_target_ready_stock(profile_id=quiz_profile_id, db_path=isolated_db) == 3

    # 7. Clamping máximo (15 -> 10)
    autonomous_production.set_target_ready_stock(15, profile_id=quiz_profile_id, db_path=isolated_db)
    assert autonomous_production.get_target_ready_stock(profile_id=quiz_profile_id, db_path=isolated_db) == 10


def test_stock_target_clamping_and_read_write_default_profile(isolated_db):
    """Garante que a regra [3, 10] se aplica também ao perfil default."""
    # 1. Meta 10 no perfil default
    autonomous_production.set_target_ready_stock(10, profile_id="default", db_path=isolated_db)
    assert autonomous_production.get_target_ready_stock(profile_id="default", db_path=isolated_db) == 10
    assert autonomous_production.get_target_ready_stock(profile_id=None, db_path=isolated_db) == 10

    # 2. Clamping mínimo em default (1 -> 3)
    autonomous_production.set_target_ready_stock(1, profile_id="default", db_path=isolated_db)
    assert autonomous_production.get_target_ready_stock(profile_id="default", db_path=isolated_db) == 3
    assert autonomous_production.get_target_ready_stock(profile_id=None, db_path=isolated_db) == 3

    # 3. Clamping máximo em default (15 -> 10)
    autonomous_production.set_target_ready_stock(15, profile_id="default", db_path=isolated_db)
    assert autonomous_production.get_target_ready_stock(profile_id="default", db_path=isolated_db) == 10
    assert autonomous_production.get_target_ready_stock(profile_id=None, db_path=isolated_db) == 10


def test_sqlite_persisted_target_10_read_correctly(isolated_db):
    """Simula exatamente o caso de produção: o SQLite tem meta Quiz = 10 gravada

    anteriormente e o Autopilot deve ler 10 (e não 6).
    """
    quiz_pid = "profile-6224c41b78e4"
    # Grava diretamente no banco simulando o estado de produção pré-hotfix
    autonomous_production.set_autonomous_setting(
        f"autonomous_target_ready_stock:{quiz_pid}", "10", db_path=isolated_db
    )

    # Verifica leitura canônica
    read_target = autonomous_production.get_target_ready_stock(profile_id=quiz_pid, db_path=isolated_db)
    assert read_target == 10, f"Autopilot deveria ler 10, mas leu {read_target}"

    # Verifica status reportado para o card
    status = autonomous_production.get_autonomous_status(profile_id=quiz_pid, db_path=isolated_db)
    assert status["target_ready_stock"] == 10
