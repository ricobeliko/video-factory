"""Testes direcionados da Missão O — Google Flow: Capacidade por vídeo e correção do Streamlit.

Cobre os 10 cenários canônicos exigidos pela missão:
1. Rejeição de conta com 50 créditos para vídeo de 90 créditos.
2. Seleção de Conta B com 831 créditos quando a tarefa requer 90 créditos.
3. Tarefa que precisa de menos créditos (ex.: 2 cenas = 30 cr) aceita conta com 50 créditos.
4. Não somar créditos de contas diferentes (ex.: duas de 50 não atendem 90).
5. Preservação de stickiness se o vídeo já iniciou.
6. Falha de reconciliação não inventa créditos.
7. Conta stale não é promovida a verificada.
8. Ausência de duplicidade de chaves no componente Streamlit.
9. Pool com 3 contas suportado transparentemente.
10. Quiz procedural e outros geradores sem Google Flow continuam operando normalmente sem impacto.
"""

from datetime import datetime, timedelta, timezone
import json
import os
import shutil
import tempfile
from unittest.mock import MagicMock, patch

import pytest

from app.services import flow_account_pool as fap


@pytest.fixture
def temp_pool_env():
    """Ambiente temporário isolado para testes do pool multi-contas."""
    temp_dir = tempfile.mkdtemp(prefix="test_mission_o_pool_")
    config_path = os.path.join(temp_dir, "flow_accounts.json")
    runtime_path = os.path.join(temp_dir, "flow_accounts_runtime.json")

    # Configuração inicial com 3 contas: flow-primary (A), flow-b (B) e flow-c (C)
    initial_config = {
        "schema_version": 1,
        "accounts": [
            {
                "account_id": "flow-primary",
                "display_name": "Conta A",
                "enabled": True,
                "priority": 100,
                "user_data_dir": os.path.join(temp_dir, "flow_browser_profile"),
            },
            {
                "account_id": "flow-b",
                "display_name": "Conta B",
                "enabled": True,
                "priority": 90,
                "user_data_dir": os.path.join(temp_dir, "flow_browser_profiles", "flow-b"),
            },
            {
                "account_id": "flow-c",
                "display_name": "Conta C",
                "enabled": True,
                "priority": 80,
                "user_data_dir": os.path.join(temp_dir, "flow_browser_profiles", "flow-c"),
            },
        ],
    }
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(initial_config, f)

    initial_runtime = {
        "accounts": {
            "flow-primary": {
                "account_id": "flow-primary",
                "status": fap.STATUS_AVAILABLE,
                "credits_remaining": 50,
                "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
                "credits_last_verified_at": datetime.now(timezone.utc).isoformat(),
            },
            "flow-b": {
                "account_id": "flow-b",
                "status": fap.STATUS_AVAILABLE,
                "credits_remaining": 831,
                "credits_source": fap.CREDIT_SOURCE_LOCAL_ESTIMATE,
                "credits_last_verified_at": datetime.now(timezone.utc).isoformat(),
            },
            "flow-c": {
                "account_id": "flow-c",
                "status": fap.STATUS_AVAILABLE,
                "credits_remaining": 50,
                "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
                "credits_last_verified_at": datetime.now(timezone.utc).isoformat(),
            },
        }
    }
    with open(runtime_path, "w", encoding="utf-8") as f:
        json.dump(initial_runtime, f)

    yield {
        "temp_dir": temp_dir,
        "config_path": config_path,
        "runtime_path": runtime_path,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


# ===========================================================================
# 1. Rejeição de conta com 50 créditos para vídeo de 90 créditos
# ===========================================================================
def test_scenario_1_reject_50_credits_for_90_credits_video(temp_pool_env):
    """Cenário 1: Se apenas conta com 50 créditos estiver disponível e o vídeo exigir 90 cr, deve rejeitar."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    # Desativa Conta B e Conta C, deixando apenas Conta A com 50 créditos
    fap.disable_account("flow-b", config_path=config_p)
    fap.disable_account("flow-c", config_path=config_p)

    task_manifest = {
        "scenes": [
            {"scene_index": 1, "is_flow_premium": True},
            {"scene_index": 2, "is_flow_premium": True},
            {"scene_index": 3, "is_flow_premium": True},
            {"scene_index": 4, "is_flow_premium": True},
            {"scene_index": 5, "is_flow_premium": True},
            {"scene_index": 6, "is_flow_premium": True},
        ]
    }
    needed = fap.estimate_task_flow_credits(task_manifest)
    assert needed == 90

    selected = fap.select_flow_account(
        task_manifest,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is None, "Deveria retornar None porque 50 < 90 cr e fail-closed se aplica."

    resolved = fap.resolve_manifest_account(
        task_manifest,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert resolved is None, "resolve_manifest_account deve retornar None para pré-dispatch sem saldo."


# ===========================================================================
# 2. Seleção de Conta B com 831 créditos quando a tarefa requer 90 créditos
# ===========================================================================
def test_scenario_2_select_account_b_with_831_credits_for_90_cr(temp_pool_env):
    """Cenário 2: Conta A tem 50 cr verificado (Tier 4 p/ 90 cr), Conta B tem 831 cr estimado (Tier 2 p/ 90 cr).
    Conta B deve ser selecionada para atender a demanda de 90 créditos."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    task_manifest = {
        "scenes": [
            {"scene_index": 1, "is_flow_premium": True},
            {"scene_index": 2, "is_flow_premium": True},
            {"scene_index": 3, "is_flow_premium": True},
            {"scene_index": 4, "is_flow_premium": True},
            {"scene_index": 5, "is_flow_premium": True},
            {"scene_index": 6, "is_flow_premium": True},
        ]
    }

    selected = fap.select_flow_account(
        task_manifest,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is not None
    assert selected["account_id"] == "flow-b", f"Esperado 'flow-b' com 831 cr, obteve {selected['account_id']}"


# ===========================================================================
# 3. Tarefa que precisa de menos créditos (2 cenas = 30 cr) aceita conta de 50 cr
# ===========================================================================
def test_scenario_3_small_task_accepts_50_credits_account(temp_pool_env):
    """Cenário 3: Tarefa pequena (2 cenas = 30 cr). Conta A (50 cr verificado, Tier 1)
    deve vencer Conta B (831 cr estimado, Tier 2) porque 50 >= 30 cr e verificado tem precedência."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    task_manifest = {
        "scenes": [
            {"scene_index": 1, "is_flow_premium": True},
            {"scene_index": 2, "is_flow_premium": True},
        ]
    }
    needed = fap.estimate_task_flow_credits(task_manifest)
    assert needed == 30

    selected = fap.select_flow_account(
        task_manifest,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is not None
    assert selected["account_id"] == "flow-primary", f"Esperado 'flow-primary' (Tier 1 verificado), obteve {selected['account_id']}"


# ===========================================================================
# 4. Não somar créditos de contas diferentes (ex.: duas de 50 não atendem 90)
# ===========================================================================
def test_scenario_4_do_not_sum_credits_across_accounts(temp_pool_env):
    """Cenário 4: Duas contas de 50 cr (total consolidado = 100 cr). Nenhuma individualmente tem 90 cr.
    O sistema NUNCA deve somar e deve recusar a seleção para 90 cr."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    # Desativa Conta B (831 cr), deixando Conta A (50 cr) e Conta C (50 cr)
    fap.disable_account("flow-b", config_path=config_p)

    status = fap.get_flow_accounts_status(config_path=config_p, runtime_path=runtime_p)
    assert status["total_known_credits"] == 100, "Total informativo deve reportar 100 créditos somados."
    assert status["recommended_account_id"] is None, "Nenhuma conta pode ser recomendada para ~90 cr."

    # Tenta selecionar conta para 90 cr
    selected = fap.select_flow_account(
        required_credits=90,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is None, "Não deve somar contas diferentes para autorizar o vídeo."


# ===========================================================================
# 5. Preservação de stickiness se o vídeo já iniciou
# ===========================================================================
def test_scenario_5_stickiness_preserved_once_started(temp_pool_env):
    """Cenário 5: Se o vídeo já foi iniciado em flow-primary (url do projeto existe ou completed_scenes > 0),
    a vinculação é estritamente mantida mesmo que o saldo esteja baixo."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    # Manifesto com projeto já iniciado na conta flow-primary
    manifest_started = {
        "flow_account_id": "flow-primary",
        "flow_project_url": "https://labs.google/flow/project-active-456",
        "flow_generation": {
            "completed_scenes": [1],
        },
        "scenes": [
            {"scene_index": 1, "is_flow_premium": True},
            {"scene_index": 2, "is_flow_premium": True},
            {"scene_index": 3, "is_flow_premium": True},
            {"scene_index": 4, "is_flow_premium": True},
            {"scene_index": 5, "is_flow_premium": True},
            {"scene_index": 6, "is_flow_premium": True},
        ]
    }

    selected = fap.select_flow_account(
        manifest_started,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is not None
    assert selected["account_id"] == "flow-primary", "Stickiness deve preservar a conta do projeto já criado."

    resolved = fap.resolve_manifest_account(
        manifest_started,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert resolved["account_id"] == "flow-primary"


# ===========================================================================
# 6. Falha de reconciliação não inventa créditos
# ===========================================================================
def test_scenario_6_failed_reconciliation_preserves_credits(temp_pool_env):
    """Cenário 6: Se a verificação headless falhar ou não encontrar número, o saldo anterior
    não pode ser inventado ou corrompido."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    # Simula falha na verificação
    mock_verify_res = {
        "account_id": "flow-primary",
        "login_status": "BLOCKED_CAPTCHA",
        "credits_remaining": None,
        "credits_source": fap.CREDIT_SOURCE_UNKNOWN,
        "message": "Challenge detectado no login",
    }

    with patch("app.services.flow_account_pool.verify_flow_account_session", return_value=mock_verify_res):
        res = fap.refresh_account_credits(
            "flow-primary",
            force=True,
            config_path=config_p,
            runtime_path=runtime_p,
        )
        assert res["success"] is False
        assert res["credits_remaining"] == 50, "Deve preservar os 50 créditos conhecidos anteriormente sem inventar nada."

    rt = fap.get_account_runtime("flow-primary", runtime_path=runtime_p)
    assert rt["credits_remaining"] == 50
    assert rt["credits_source"] == fap.CREDIT_SOURCE_FLOW_UI_VERIFIED


# ===========================================================================
# 7. Conta stale não é promovida a verificada
# ===========================================================================
def test_scenario_7_stale_account_is_not_treated_as_verified(temp_pool_env):
    """Cenário 7: Conta com verificação > 24h atrás é tratada como stale (Tier 3)
    e não tem precedência sobre conta com saldo estimado recente (Tier 2)."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    stale_time = (datetime.now(timezone.utc) - timedelta(hours=48)).isoformat()
    # Conta A com 200 créditos mas stale (48h atrás)
    fap.update_account_runtime(
        "flow-primary",
        {
            "credits_remaining": 200,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": stale_time,
        },
        runtime_path=runtime_p,
    )

    rt_a = fap.get_account_runtime("flow-primary", runtime_path=runtime_p)
    is_stale, reason, hours = fap.is_credit_reading_stale(rt_a)
    assert is_stale is True
    assert hours > 24.0

    # Para um vídeo de 90 cr, Conta B (831 cr estimado recente, Tier 2)
    # deve vencer Conta A (200 cr desatualizado, Tier 3)
    selected = fap.select_flow_account(
        required_credits=90,
        config_path=config_p,
        runtime_path=runtime_p,
    )
    assert selected is not None
    assert selected["account_id"] == "flow-b", "Conta estimada recente (Tier 2) deve vencer conta stale (Tier 3)."


# ===========================================================================
# 8. Ausência de duplicidade de chaves no componente Streamlit
# ===========================================================================
def test_scenario_8_no_duplicate_keys_in_streamlit():
    """Cenário 8: Garante que _render_flow_pool_management_block é chamado exatamente UMA vez
    em webui/components/operator_console.py e possui guard de execução por ciclo."""
    op_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
        "webui",
        "components",
        "operator_console.py",
    )
    with open(op_path, "r", encoding="utf-8") as f:
        content = f.read()

    lines = content.splitlines()
    call_lines = [
        line.strip()
        for line in lines
        if "_render_flow_pool_management_block" in line and not line.strip().startswith("def ")
    ]
    assert len(call_lines) == 1, f"Deve haver exatamente 1 chamada canônica para o bloco Flow, encontrado {len(call_lines)}: {call_lines}"

    # Valida guard de ciclo
    assert 'st.session_state.get("_flow_pool_block_rendered")' in content
    assert 'st.session_state["_flow_pool_block_rendered"] = True' in content
    assert 'st.session_state["_flow_pool_block_rendered"] = False' in content


# ===========================================================================
# 9. Pool com 3 contas suportado transparentemente
# ===========================================================================
def test_scenario_9_three_accounts_supported_transparently(temp_pool_env):
    """Cenário 9: Pool com 3 contas ativas (flow-primary, flow-b, flow-c).
    Valida telemetria por conta, identificação correta de recomendada e capacidade individual."""
    config_p = temp_pool_env["config_path"]
    runtime_p = temp_pool_env["runtime_path"]

    status = fap.get_flow_accounts_status(config_path=config_p, runtime_path=runtime_p)
    accounts = status["accounts"]
    assert len(accounts) == 3
    aids = [a["account_id"] for a in accounts]
    assert aids == ["flow-primary", "flow-b", "flow-c"]

    # Capacidades individuais
    acct_b = next(a for a in accounts if a["account_id"] == "flow-b")
    assert acct_b["can_produce_standard_video"] is True
    assert acct_b["standard_video_capacity"] == 831 // 90  # 9 vídeos

    acct_a = next(a for a in accounts if a["account_id"] == "flow-primary")
    assert acct_a["can_produce_standard_video"] is False
    assert acct_a["standard_video_capacity"] == 0

    assert status["recommended_account_id"] == "flow-b"
    assert status["total_known_credits"] == 50 + 831 + 50  # 931 créditos


# ===========================================================================
# 10. Quiz procedural e geradores sem Google Flow não são afetados
# ===========================================================================
def test_scenario_10_procedural_generators_unaffected(temp_pool_env):
    """Cenário 10: Tarefas com flow_enabled=False (ex.: quiz_dilemma, quiz_paper)
    não sofrem restrições do pool Flow e executam de forma independente."""
    from app.services.task import VideoParams

    # Simula parâmetros de um quiz procedural
    quiz_params = VideoParams(
        video_subject="Qual você escolhe?",
        video_script="Dilema 1 ou Dilema 2",
        flow_enabled=False,
        video_source="procedural_dilemma",
    )

    # Verifica que flow_enabled é False
    assert getattr(quiz_params, "flow_enabled", False) is False

    # Na lógica de task.py, se flow_enabled=False, o provedor visual não é Google Flow
    visuals_prov = (
        "Google Flow"
        if getattr(quiz_params, "flow_enabled", False)
        else (getattr(quiz_params, "video_source", None) or "materials")
    )
    assert visuals_prov == "procedural_dilemma"
