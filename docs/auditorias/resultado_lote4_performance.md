# RELATÓRIO DE AJUSTES FINAIS — LOTE 4 | STREAMLIT V1

**Data:** 2026-10-20  
**Worktree:** `C:\Projetos\MoneyPrinterTurbo-V1\.worktrees\lote4-performance`  
**Branch:** `feat/v1-lote4-streamlit-performance`  
**HEAD:** `c9f68e2f1e642d78cebf909dd08d6677fd5acc44` (curto: `c9f68e2`)  
**Baseline Integrado:** `4ea28dff219830714190e844b7bc985a3d39c153`  
**Status:** **AJUSTES FINAIS CONCLUÍDOS — 0 REGRESSÕES NOVAS**

---

## 1. STATUS GERAL
Após a auditoria comparativa direta realizada pelo Arquiteto-Chefe entre o baseline `4ea28df` e o commit `f023c44`, foram eliminadas de forma cirúrgica e definitiva as 4 regressões novas identificadas, mantendo as 2 falhas comprovadamente preexistentes sem mascaramentos.

Todos os 55 testes direcionados do Lote 4, Channel Factory e UX Stability foram executados e passaram com 100% de sucesso.

---

## 2. AS 4 REGRESSÕES NOVAS ELIMINADAS

### 1. `test_channel_factory_onboarding_form_calls_canonical_global_voice`
- **Causa Raiz:** Um arquivo residual `config.toml` havia sido gravado na raiz do worktree durante execuções de testes anteriores contendo `voice_name = "pt-BR-AntonioNeural"`. Além disso, o botão de submissão `submitted = st.button(...)` avaliava como `True` sob `MagicMock` genérico dos testes unitários.
- **Correção:** 
  - Isolamento completo dos testes de escrita em `tmp_path` (usando `monkeypatch` em `config.config_file` e `config.root_dir`).
  - Remoção do artefato residual `config.toml` da raiz do worktree.
  - Adoção de verificação booleana estrita `if submitted is True:` em `_render_onboarding_form`.

### 2. `test_render_channel_factory_renders_without_attribute_error`
- **Causa Raiz:** O decorator `_channel_factory_fragment` avaliava `st.fragment` no momento da definição de módulo, o que falhava ou impedia a execução transparente em bare mode (sem contexto ativo do script runner do Streamlit).
- **Correção:** Verificação dinâmica de contexto via `_get_current_script_run_ctx()` em tempo de execução/chamada. Em bare mode de testes (`ctx is None`), a função original é executada diretamente sem acionar o runtime do Streamlit.

### 3. `test_generation_log_fragment_refreshes_within_half_a_second`
- **Causa Raiz:** `webui/Main.py` definia um valor fixo de `run_every="5s"`.
- **Correção:** Atualizado cirurgicamente para `@st.fragment(run_every=webui_task.TASK_LOG_REFRESH_INTERVAL_SECONDS)`, respeitando a constante canônica de 0.5s.

### 4. Locks e Dirty Tracking em `_SynchronizedConfig`
- **Causa Raiz:** A adição de dirty tracking interno aos métodos de dicionário de `_SynchronizedConfig` aumentava a complexidade de locks e podia disparar gravações redundantes ou riscos de contenção.
- **Correção:** Revertido `_SynchronizedConfig` estritamente ao comportamento canônico do baseline `4ea28df`. Mantidos `try_save_config(force=True)` como padrão público, `update_config_nonblocking` e `delete_config_nonblocking` para alterações pontuais, e `force=False` exclusivamente nos reruns passivos do Streamlit em `Main.py`.

---

## 3. FALHAS PREEXISTENTES COMPROVADAS (INALTERADAS)

As duas falhas abaixo pertencem a contratos introduzidos em lotes anteriores e foram preservadas sem modificação artificial:

1. **`test_operator_console.py: test_canonical_ready_stock_matches_autonomous_production`**
   - **Origem:** Introduzido no Lote 3B (regras de negócio RN-02 e RN-03), onde o Copyright Gate tornou-se mandatório para qualificação de estoque autônomo. A fixture sintética legada do teste não possui assessment de copyright.
2. **`test_webui_task.py: test_submit_generation_copies_params_before_starting_worker`**
   - **Origem:** Introduzido no Lote 1, onde a hidratação canônica obrigatória (`profile_manager.hydrate_video_params`) preenche os valores default da fábrica a partir do perfil no momento da submissão da tarefa, divergindo do objeto cru não-hidratado.

---

## 4. BATERIA DE TESTES EXECUTADA

### Suíte Primária (Lote 4 + Channel Factory + UX):
```powershell
pytest test/services/test_channel_factory.py test/services/test_lote4_performance.py test/services/test_webui_ux_stability.py
```
**Resultado:** **55 passed in 29.04s** (100% de sucesso)

### Verificação de Compatibilidade e Não-Regressão Adicional:
```powershell
pytest test/services/test_operator_console.py test/services/test_webui_task.py
```
**Resultado:** **40 passed, 2 failed** (exatamente as 2 falhas preexistentes já documentadas, 0 regressões novas).

---

## 5. GANHOS DE PERFORMANCE PRESERVADOS

| Ponto de Medição | Baseline Inicial | Lote 4 Otimizado | Ganho Efetivo |
| :--- | :--- | :--- | :--- |
| `config.try_save_config(force=False)` | 9.93 ms (pico 33.6 ms) | **0.00 ms** | > 99.9% (zero I/O síncrono em reruns) |
| `utils.check_ffmpeg_ready()` (em cache) | 136.61 ms | **0.00 ms** (1ª: 47 ms) | > 99.9% (elimina subprocessos contínuos) |
| `get_available_factory_voices()` | 7.15 ms | **1.54 ms** | ~80% |
| `operator_console.get_provider_health_summary()` | 272.85 ms | **13.38 ms** | ~95% |
| Interações Channel Factory / Voz Global | Travamento / Dimming geral | **Fragmentos isolados** | Fluidez imediata sem escurecer UI |

---

## 6. PRÓXIMO GATE SEGURO
- **Commit Local:** `c9f68e2f1e642d78cebf909dd08d6677fd5acc44` na branch `feat/v1-lote4-streamlit-performance`.
- **Status:** Pronto para homologação final pelo Arquiteto-Chefe e merge de integração.
- **Restrições:** Nenhum push remoto, deploy ou alteração externa executada.
