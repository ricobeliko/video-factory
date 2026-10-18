# -*- coding: utf-8 -*-
"""
test/test_v2_performance.py
===========================
Benchmark de desempenho da Video Factory V2.
Mede tempos de resposta das consultas SQLite e endpoints FastAPI.
"""

import time
import pytest
from app.services import operator_console, profile_manager


def test_channels_overview_performance():
    """Valida se a listagem de canais e perfis executa em menos de 1000ms."""
    # Warm-up inicial de tabelas SQLite
    operator_console.get_profile_operations_overview()

    start = time.perf_counter()
    overviews = operator_console.get_profile_operations_overview()
    duration_ms = (time.perf_counter() - start) * 1000

    print(f"\n[PERF] get_profile_operations_overview (steady-state): {duration_ms:.2f}ms (Total canais: {len(overviews)})")
    assert duration_ms < 1000, f"Tempo de resposta excedeu 1000ms: {duration_ms:.2f}ms"


def test_system_status_performance():
    """Valida se a consulta de status consolidado do sistema executa em menos de 1000ms."""
    # Warm-up de checagens
    operator_console.get_system_status()

    start = time.perf_counter()
    status = operator_console.get_system_status()
    duration_ms = (time.perf_counter() - start) * 1000

    print(f"\n[PERF] get_system_status (steady-state): {duration_ms:.2f}ms")
    assert duration_ms < 1000, f"Tempo de resposta excedeu 1000ms: {duration_ms:.2f}ms"



def test_live_execution_overview_performance():
    """Valida se o snapshot de telemetria live executa em menos de 500ms."""
    start = time.perf_counter()
    overview = operator_console.get_live_execution_overview()
    duration_ms = (time.perf_counter() - start) * 1000

    print(f"\n[PERF] get_live_execution_overview: {duration_ms:.2f}ms")
    assert duration_ms < 500, f"Tempo de resposta excedeu 500ms: {duration_ms:.2f}ms"
