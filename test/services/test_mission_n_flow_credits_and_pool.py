"""Testes direcionados da Missão N — Google Flow: Créditos Atualizados, Pool Multi-Contas e Preparação da Conta C."""

import json
import os
import shutil
import tempfile
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, MagicMock

import pytest

from app.services import flow_account_pool as fap
from app.services import operator_console


@pytest.fixture
def temp_pool_env():
    """Ambiente temporário isolado para testes de configuração e runtime do pool."""
    temp_dir = tempfile.mkdtemp(prefix="test_flow_pool_")
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
        json.dump(initial_config, f, indent=2)

    yield {
        "dir": temp_dir,
        "config_path": config_path,
        "runtime_path": runtime_path,
    }

    shutil.rmtree(temp_dir, ignore_errors=True)


def test_is_credit_reading_stale_and_formatting():
    """Valida detecção de telemetria desatualizada (> 24h) e formatação amigável de tempo."""
    now = datetime.now(timezone.utc)

    # 1. Registro nulo ou vazio -> stale
    is_stale, reason, age = fap.is_credit_reading_stale(None)
    assert is_stale is True
    assert age is None

    # 2. Registro com mais de 24 horas (ex: 216h / 9 dias atrás) -> stale
    old_ts = (now - timedelta(days=9)).isoformat()
    rt_old = {
        "credits_remaining": 2,
        "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
        "credits_last_verified_at": old_ts,
    }
    is_stale, reason, age = fap.is_credit_reading_stale(rt_old)
    assert is_stale is True
    assert age is not None and age > 24.0
    assert "mais de 24h" in reason

    # 3. Registro recente (< 24h, ex: 2h atrás) -> não stale
    recent_ts = (now - timedelta(hours=2)).isoformat()
    rt_recent = {
        "credits_remaining": 50,
        "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
        "credits_last_verified_at": recent_ts,
    }
    is_stale, reason, age = fap.is_credit_reading_stale(rt_recent)
    assert is_stale is False
    assert age is not None and 1.9 <= age <= 2.1

    # 4. Fonte UNKNOWN -> sempre stale
    rt_unknown = {
        "credits_remaining": 100,
        "credits_source": fap.CREDIT_SOURCE_UNKNOWN,
        "credits_last_verified_at": recent_ts,
    }
    is_stale, _, _ = fap.is_credit_reading_stale(rt_unknown)
    assert is_stale is True

    # 5. Formatação amigável
    assert fap.format_last_verified_time(None) == "Nunca verificado"
    assert "min" in fap.format_last_verified_time((now - timedelta(minutes=5)).isoformat())
    assert "2h" in fap.format_last_verified_time(recent_ts)
    assert "Há 9d" in fap.format_last_verified_time(old_ts)


def test_refresh_account_credits_cached_when_fresh(temp_pool_env):
    """Valida que refresh com saldo recente e force=False aproveita cache sem abrir navegador."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    # Grava saldo recente de 100 créditos para flow-b
    now_iso = datetime.now(timezone.utc).isoformat()
    fap.update_account_runtime(
        "flow-b",
        {
            "credits_remaining": 100,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": now_iso,
            "status": fap.STATUS_AVAILABLE,
        },
        runtime_path=r_path,
    )

    with patch("app.services.flow_account_pool.verify_flow_account_session") as mock_verify:
        res = fap.refresh_account_credits("flow-b", force=False, config_path=c_path, runtime_path=r_path)
        assert res["refreshed"] is False
        assert res["reason"] == "CACHED_FRESH"
        assert res["credits_remaining"] == 100
        mock_verify.assert_not_called()


def test_refresh_account_credits_recovery_from_exhausted(temp_pool_env):
    """Valida que reconciliação atualiza saldo e recupera conta de EXHAUSTED para AVAILABLE."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    # Simula estado da produção: flow-primary congelado em 2 créditos e EXHAUSTED desde 15/10/2026
    old_ts = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    fap.update_account_runtime(
        "flow-primary",
        {
            "status": fap.STATUS_EXHAUSTED,
            "credits_remaining": 2,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": old_ts,
        },
        runtime_path=r_path,
    )

    # Simula verificação headless encontrando 50 créditos na interface
    mock_verify_res = {
        "account_id": "flow-primary",
        "login_status": "AUTHENTICATED",
        "credits_remaining": 50,
        "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
    }

    with patch("app.services.flow_account_pool.verify_flow_account_session", return_value=mock_verify_res):
        res = fap.refresh_account_credits("flow-primary", force=True, config_path=c_path, runtime_path=r_path)
        assert res["refreshed"] is True
        assert res["success"] is True
        assert res["credits_remaining"] == 50

        # Verifica que o runtime foi atualizado para AVAILABLE e com timestamp fresco
        rt = fap.get_account_runtime("flow-primary", runtime_path=r_path)
        assert rt["credits_remaining"] == 50
        assert rt["status"] == fap.STATUS_AVAILABLE
        assert rt["credits_source"] == fap.CREDIT_SOURCE_FLOW_UI_VERIFIED
        is_stale, _, _ = fap.is_credit_reading_stale(rt)
        assert is_stale is False


def test_refresh_account_credits_failure_preserves_balance(temp_pool_env):
    """Valida que falha na leitura não apaga nem zera o último saldo conhecido."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    # Saldo conhecido anterior: 251 créditos
    fap.update_account_runtime(
        "flow-b",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 251,
            "credits_source": fap.CREDIT_SOURCE_LOCAL_ESTIMATE,
        },
        runtime_path=r_path,
    )

    # Simula falha temporária de rede/login
    mock_fail = {
        "account_id": "flow-b",
        "login_status": "AUTH_REQUIRED",
        "credits_remaining": None,
        "message": "Timeout ao abrir Flow",
    }

    with patch("app.services.flow_account_pool.verify_flow_account_session", return_value=mock_fail):
        res = fap.refresh_account_credits("flow-b", force=True, config_path=c_path, runtime_path=r_path)
        assert res["refreshed"] is True
        assert res["success"] is False
        # O saldo anterior deve ter sido preservado
        assert res["credits_remaining"] == 251

        rt = fap.get_account_runtime("flow-b", runtime_path=r_path)
        assert rt["credits_remaining"] == 251


def test_select_flow_account_ranking_and_tiers(temp_pool_env):
    """Valida a seleção entre 3 contas elegíveis: B (1000) > C (200) > A (50)."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]
    now_iso = datetime.now(timezone.utc).isoformat()

    # Conta A: 50 créditos (verificado recente)
    fap.update_account_runtime(
        "flow-primary",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 50,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": now_iso,
        },
        runtime_path=r_path,
    )

    # Conta B: 1000 créditos (verificado recente)
    fap.update_account_runtime(
        "flow-b",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 1000,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": now_iso,
        },
        runtime_path=r_path,
    )

    # Conta C: 200 créditos (verificado recente)
    fap.update_account_runtime(
        "flow-c",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 200,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": now_iso,
        },
        runtime_path=r_path,
    )

    # 1. Conta B deve ser selecionada primeiro por ter maior capacidade
    selected = fap.select_flow_account(config_path=c_path, runtime_path=r_path)
    assert selected is not None
    assert selected["account_id"] == "flow-b"

    # 2. Se Conta B ficar esgotada (0 créditos), seleciona Conta C (200 créditos)
    fap.update_account_runtime(
        "flow-b",
        {
            "status": fap.STATUS_EXHAUSTED,
            "credits_remaining": 0,
            "credits_last_verified_at": now_iso,
        },
        runtime_path=r_path,
    )
    selected2 = fap.select_flow_account(config_path=c_path, runtime_path=r_path)
    assert selected2 is not None
    assert selected2["account_id"] == "flow-c"

    # 3. Se Conta C também for esgotada, seleciona Conta A (50 créditos)
    fap.update_account_runtime(
        "flow-c",
        {
            "status": fap.STATUS_EXHAUSTED,
            "credits_remaining": 0,
            "credits_last_verified_at": now_iso,
        },
        runtime_path=r_path,
    )
    selected3 = fap.select_flow_account(config_path=c_path, runtime_path=r_path)
    assert selected3 is not None
    assert selected3["account_id"] == "flow-primary"


def test_select_flow_account_stale_account_not_permanently_blocked(temp_pool_env):
    """Valida que uma conta com saldo baixo/esgotado no passado (>24h) NÃO fica permanentemente bloqueada."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    # Conta A está marcada como EXHAUSTED com 2 créditos, mas a data é de 9 dias atrás
    old_ts = (datetime.now(timezone.utc) - timedelta(days=9)).isoformat()
    fap.update_account_runtime(
        "flow-primary",
        {
            "status": fap.STATUS_EXHAUSTED,
            "credits_remaining": 2,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": old_ts,
        },
        runtime_path=r_path,
    )

    # Contas B e C desativadas
    fap.disable_account("flow-b", config_path=c_path)
    fap.disable_account("flow-c", config_path=c_path)

    # A Conta A deve ser selecionada no Tier 3 (stale/reavaliação) em vez de retornar None (pool morto)
    selected = fap.select_flow_account(config_path=c_path, runtime_path=r_path)
    assert selected is not None
    assert selected["account_id"] == "flow-primary"


def test_select_flow_account_auth_failed_remains_ineligible(temp_pool_env):
    """Valida que conta com falha ou necessidade de autenticação permanece estritamente inelegível."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    fap.update_account_runtime(
        "flow-primary",
        {"status": fap.STATUS_AUTH_REQUIRED, "credits_remaining": 500},
        runtime_path=r_path,
    )
    fap.update_account_runtime(
        "flow-b",
        {"status": fap.STATUS_AUTH_FAILED, "credits_remaining": 1000},
        runtime_path=r_path,
    )
    fap.update_account_runtime(
        "flow-c",
        {"status": fap.STATUS_DISABLED, "credits_remaining": 200},
        runtime_path=r_path,
    )

    selected = fap.select_flow_account(config_path=c_path, runtime_path=r_path)
    assert selected is None


def test_task_stickiness_and_failover_boundaries(temp_pool_env):
    """Valida stickiness mandatória se projeto iniciado e permissão de failover pré-dispatch."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]

    # Manifest com projeto já iniciado no Flow (URL presente)
    started_manifest = {
        "task_id": "task-test-sticky-1",
        "flow_account_id": "flow-b",
        "flow_project_url": "https://flow.google.com/project/12345",
        "flow_generation": {"completed_scenes": [0]},
    }
    # Failover DEVE ser proibido para projeto já iniciado
    assert fap.can_failover_account(started_manifest) is False

    # Seleção com manifesto iniciado DEVE manter a conta vinculada (flow-b)
    chosen = fap.select_flow_account(started_manifest, config_path=c_path, runtime_path=r_path)
    assert chosen is not None
    assert chosen["account_id"] == "flow-b"

    # Manifest pré-dispatch (sem URL, zero cenas completadas)
    predispatch_manifest = {
        "task_id": "task-test-predispatch-1",
        "flow_account_id": "flow-primary",
        "flow_project_url": None,
        "flow_generation": {"completed_scenes": []},
    }
    # Failover é permitido pré-dispatch
    assert fap.can_failover_account(predispatch_manifest) is True


def test_profile_isolation_flow_c(temp_pool_env):
    """Valida que Conta C possui diretório de perfil Edge estritamente isolado."""
    c_path = temp_pool_env["config_path"]
    cfg = fap.load_accounts_config(c_path)
    accounts = {a["account_id"]: a for a in cfg.get("accounts", [])}

    assert "flow-c" in accounts
    c_dir = accounts["flow-c"]["user_data_dir"]
    primary_dir = accounts["flow-primary"]["user_data_dir"]
    b_dir = accounts["flow-b"]["user_data_dir"]

    assert c_dir != primary_dir
    assert c_dir != b_dir
    assert "flow-c" in c_dir
    assert ".." not in c_dir


def test_get_flow_accounts_status_and_operator_console_overview(temp_pool_env):
    """Valida telemetria consolidada com is_stale, staleness_reason e integração com Console Operacional."""
    c_path = temp_pool_env["config_path"]
    r_path = temp_pool_env["runtime_path"]
    now_iso = datetime.now(timezone.utc).isoformat()
    old_ts = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()

    fap.update_account_runtime(
        "flow-primary",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 50,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": old_ts,  # Stale (>24h)
        },
        runtime_path=r_path,
    )
    fap.update_account_runtime(
        "flow-b",
        {
            "status": fap.STATUS_AVAILABLE,
            "credits_remaining": 1000,
            "credits_source": fap.CREDIT_SOURCE_FLOW_UI_VERIFIED,
            "credits_last_verified_at": now_iso,  # Recente
        },
        runtime_path=r_path,
    )

    status = fap.get_flow_accounts_status(config_path=c_path, runtime_path=r_path)
    assert len(status["accounts"]) == 3
    assert status["active_account_id"] == "flow-b"

    acc_map = {a["account_id"]: a for a in status["accounts"]}
    assert acc_map["flow-primary"]["is_stale"] is True
    assert "mais de 24h" in acc_map["flow-primary"]["staleness_reason"]
    assert acc_map["flow-b"]["is_stale"] is False

    # Valida wrappers expostos em operator_console
    with patch("app.services.flow_account_pool.get_flow_accounts_status", return_value=status):
        op_status = operator_console.get_flow_accounts_status_op()
        assert op_status["active_account_id"] == "flow-b"
        assert len(op_status["accounts"]) == 3
