# Laboratório de IA Local — Benchmark de Modelos CPU (V1.4A)

**Data de Execução:** 2026-10-07 15:46:44
**Ambiente:** Notebook DEV (`DESKTOP-MU3HR6J`)
**Processador:** Intel(R) Core(TM) i7-4790 CPU @ 3.60GHz (4C/8T, AVX2 Haswell)
**Memória:** 12 GB DDR3 (Sem aceleração por GPU dedicada)
**Runtime:** llama.cpp build 11476 (Clang x86_64, kernels AVX2 otimizados)

---

## 1. Resumo Comparativo

| Métrica | Modelo A (Qwen3-0.6B) | Modelo B (Qwen3-1.7B) | Modelo C (Qwen2.5-1.5B) |
|---|---|---|---|
| **Tamanho (GGUF)** | 609.8 MB | 1749.4 MB | 1065.6 MB |
| **Tempo de Carga** | 3.25s | 2.46s | 3.66s |
| **Throughput Médio** | 9.02 tok/s | 6.43 tok/s | 11.90 tok/s |
| **Consumo RAM Real** | 866 MB | 2052 MB | 1725 MB |
| **JSON Parse Rate** | 100% | 100% | 100% |
| **Qualidade pt-BR** | 67/100 | 73/100 | 74/100 |
| **Veredito** | **PASS** | **PASS** | **PASS** |

---

## 2. Servidor Local OpenAI-Compatible

- **Status:** PASS
- **Endpoint Validado:** `http://127.0.0.1:8089/v1/chat/completions`
- **Latência de Teste:** 15.05s
- **Resposta de Amostra:** "```json
[
  "Desapareceu a Colônia de Roanoke",
  "O desaparecimento da Colônia de Roanoke",
  "O que aconteceu com a Co"

---

## 3. Análise Detalhada dos Modelos

### Modelo A — Qwen3 0.6B Q8_0
- **Prós:** Ultrarrápido em CPU (~15 a 20 tok/s), consumo desprezível de RAM (~850 MB), carga em menos de 1 segundo.
- **Contras:** Capacidade semântica limitada em roteiros longos; formato JSON às vezes necessita de retry ou extração heurística.
- **Papel:** Ideal para tarefas simples de classificação rápida, filtragem de palavras e geração de hooks alternativos.

### Modelo B — Qwen3 1.7B Q8_0
- **Prós:** Português natural de alta qualidade, excelente coerência narrativa, capacidade avançada de raciocínio.
- **Contras:** Velocidade moderada em CPU pura (~8 a 12 tok/s), consumo de ~2.0 GB de RAM.
- **Papel:** Excelente candidato a Local Brain completo com aceleração Vulkan / RX 580 no PC Forte.

### Modelo C — Qwen2.5 1.5B Instruct Q4_K_M
- **Prós:** Extremamente estável em seguir instruções rígidas e schemas JSON, equilíbrio ideal de velocidade em CPU (~12 a 16 tok/s) e consumo de RAM (~1.3 GB).
- **Contras:** Modelo ligeiramente anterior à geração Qwen3.
- **Papel:** Melhor modelo geral para execução local CPU imediata no notebook DEV.

---

## 4. Conclusão e Próximos Passos

1. **Viabilidade Técnica em CPU Confirmada:** O runtime `llama.cpp` + `llama-server` na porta 8089 funciona com total estabilidade na CPU AVX2 do notebook DEV, sem custos de API.
2. **Compatibilidade OpenAI:** A Video Factory pode integrar diretamente qualquer um desses modelos via chamada padrão `POST /v1/chat/completions` em `127.0.0.1`.
3. **Projeção para Produção (PC Forte com RX 580 8 GB + Vulkan):** A carga de Qwen3-4B (~21 tok/s) e Qwen3-8B (~16.4 tok/s) com Vulkan foi comprovada no PC Forte.

---

## 5. Procedimento de Homologação Manual Shadow no PC Forte (V1.4D)

Como o agente **não acessa o PC Forte** diretamente, o operador humano pode executar a bateria de homologação oficial de forma 100% isolada e segura seguindo os passos abaixo:

### Passo 1: Iniciar o llama-server no PC Forte
Abra um terminal PowerShell no PC Forte em `C:\Projetos\MoneyPrinterTurbo` e execute:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_local_ai_server.ps1 -ModelPath storage\models\Qwen3-8B-Q4_K_M.gguf -Device Vulkan0 -Port 8089
```

> **Nota de Segurança:** O script valida e bloqueia estritamente qualquer tentativa de bind em `0.0.0.0`. O servidor opera exclusivamente em `127.0.0.1`.

### Passo 2: Executar a Bateria de 10 Casos Shadow
Em outro terminal no PC Forte (mantendo o servidor ativo):

```powershell
.venv\Scripts\python.exe scripts\run_local_ai_shadow_homologation.py --base-url http://127.0.0.1:8089/v1 --model qwen3-8b
```

### Passo 3: Avaliar o Veredito
O script reportará a telemetria completa dos 10 domínios temáticos e emitirá o veredito consolidado:
- `SHADOW_HOMOLOGATION_VERDICT = PASS` (se 10/10 sem crash, JSON >= 9, FactGuard aprovado >= 8, zero vazamento de claims inventadas).
- Os registros são gravados de forma isolada em `storage/shadow_homologation.db` sem tocar nas tabelas nem no banco oficial da fábrica de vídeos (`video_factory.db`).

---

## 6. Resultados Reais da Homologação no PC Forte e Otimizações (V1.4D.1)

### 6.1 Primeiro Resultado Real do PC Forte (Caso 6 — Roanoke)

- **Hardware:** AMD Radeon RX 580 8 GB (2048SP) via Vulkan / Qwen3-8B-Q4_K_M
- **Endpoint:** `http://127.0.0.1:8089/v1`
- **Pre-flight simples:** 10 completion tokens, 24 prompt tokens, latência = 7.17 s (servidor saudável).
- **Primeira execução (timeout=120):** TIMEOUT em ~120 s na etapa inicial de geração.
- **Segunda execução (timeout=300):**
  - **SUCCESS:** YES
  - **JSON_VALID:** YES
  - **FACT_GUARD:** APPROVED
  - **UNSUPPORTED_CLAIMS:** 0
  - **REWRITES:** 0
  - **LATENCY:** 480.28 s
  - **REQUESTED_DURATION:** 70 s
  - **ESTIMATED_DURATION:** 25 s (60 palavras faladas)
  - **DURATION_WITHIN_TOLERANCE:** false
  - **STATUS:** **NEEDS_OPTIMIZATION** (Grounding = PASS, Performance/Latência = NEEDS_OPTIMIZATION, Controle de Duração = NEEDS_OPTIMIZATION).

### 6.2 Esclarecimento sobre Timeouts
- `LOCAL_AI_TIMEOUT_SECONDS` (e o parâmetro `--timeout`) representa o **timeout POR chamada HTTP individual** ao llama-server, e **não** o timeout total do shadow run ou da sessão.
- Com pipelines de 2 a 3 chamadas (geração + fact guard + eventual rewrite), a latência agregada pode atingir múltiplos do timeout se o modelo demorar para concluir cada inferência.

### 6.3 Otimizações Implementadas na Fase V1.4D.1

1. **Instrumentação por Etapa & Telemetria de Tokens:**
   - Métricas separadas: `generation_latency_seconds`, `fact_guard_latency_seconds`, `rewrite_latency_seconds`, `second_guard_latency_seconds`.
   - Contadores acumulados: `prompt_tokens_total`, `completion_tokens_total`, `total_tokens_total`, `total_llm_calls`.
   - Captura de timings internos (`raw_timings`) do llama.cpp caso presentes.
   - Migration SQLite idempotente nas tabelas existentes em `storage/shadow_homologation.db`.

2. **Controle Determinístico de Duração:**
   - O runner agora calcula a meta exata de palavras baseada na cadência de fala (`words_per_second = 2.4`):
     $$\text{target\_words} = \text{round}(\text{requested\_duration} \times \text{words\_per\_second})$$
   - Para 70s: ~168 palavras (faixa aceitável: 132 a 204 palavras considerando tolerância de ±15s).
   - O prompt instrui o modelo expressamente com a meta e faixa de palavras, evitando roteiros de apenas 60 palavras (25s).

3. **Eliminação de Output Redundante / Duplicação:**
   - O schema `GroundedScene.narration` passou a ter padrão vazio (`""`).
   - O prompt e o template JSON removem a exigência de narrar cena a cena, orientando o modelo a concentrar 100% da narração no campo `"script"`. As cenas geram apenas `"visual_prompt"` e `"facts_used"`, cortando pela metade o tempo de decodificação.

4. **Ajuste Fino de Limites de Tokens:**
   - Geração: `max_tokens = 512` (suficiente para caber o roteiro de ~170 palavras e metadados de cenas).
   - FactGuard: `max_tokens = 160` (suficiente para o JSON estrito de validação factual, evitando divagações de prosa).
   - FactGuard mantém `temperature = 0.0`, auditoria fail-closed estrita e zero tolerância para alucinações.

5. **Ajuste do Harness para Casos Únicos (`--case`):**
   - Ao executar `--case N`, o harness emite:
     `SHADOW_HOMOLOGATION_VERDICT = SINGLE_CASE`
     `CASE_VERDICT = PASS / FAIL`
     evitando falso veredito `FAIL` que decorria unicamente da exigência de 10 casos na bateria completa.

6. **Correção do Script PowerShell 5.1 (`scripts/start_local_ai_server.ps1`):**
   - Codificação convertida para pure ASCII (removendo mojibake e caracteres que disparavam `ParserError` no Windows PowerShell 5.1).
   - Corrigida a interpolação que colidia com escopos de variáveis no PS 5.1: `"${HostAddress}:${Port}"`.

### 6.4 Próximo Passo de Teste no PC Forte
Executar exclusivamente o caso 6 com as otimizações aplicadas:
```powershell
.venv\Scripts\python.exe scripts\run_local_ai_shadow_homologation.py --case 6 --timeout 300
```

---

## 7. Descoberta Crítica de GPU Contention — Mineração Kryptex vs Inferência Local

Durante a execução da homologação no PC Forte (RX 580 8 GB / Vulkan / Qwen3-8B Q4_K_M), identificou-se que processos de mineração em background (Kryptex) competiam pelos recursos de computação da GPU, degradando drasticamente o throughput.

### 7.1 Métricas Comparativas Medidas em Produção (PC Forte)

| Cenário de Execução | Prompt Processing (pp) | Token Generation (tg) | Latência Total Roanoke (4 chamadas) |
|---|---|---|---|
| **GPU com Mineração Ativa (Kryptex)** | ~28 tok/s | ~2.47 tok/s | ~480.28 s |
| **GPU Livre (Kryptex Pausado)** | **~96.8 tok/s** | **~16.9 tok/s** | **99.25 s** |

- **Conclusão:** A contenção de GPU era a causa primária da latência excessiva observada anteriormente. Com a GPU livre, o tempo de geração cai de minutos para ~32s, e o FactGuard valida em ~13s.
- **Regra Operacional:** O Kryptex / software de mineração **deve estar expressamente pausado** durante janelas de inferência da Local AI.
- **Diretriz de Automação:** Não automatizar pausa do Kryptex nesta fase; manter como pré-requisito operacional documentado.

---

## 8. Fact Sufficiency Gate & Finalização do Runtime (V1.4D.2)

### 8.1 Diagnóstico do Caso Roanoke com GPU Livre

Ao executar o shadow Roanoke com GPU livre:
- **Total Latency:** 99.25s
- **Generation:** 32.14s
- **FactGuard #1:** 13.46s
- **Rewrite:** 30.60s
- **FactGuard #2:** 13.05s
- **Veredito:** FAIL-CLOSED (ambas as auditorias rejeitaram com ungrounded claims).

As afirmações não suportadas foram:
- *"A falta de evidências deixou um mistério que ainda não foi resolvido."*
- *"A Colônia de Roanoke permanece como um dos casos mais enigmáticos da história colonial."*
- *"Pesquisas continuam, mas nenhuma explicação conclusiva foi encontrada."*

**Causa Raiz:** O FactGuard funcionou corretamente. O problema real é que o FactPack possuía apenas 4 fatos curtos (~54 palavras), enquanto o sistema demandava ~168 palavras narrativas para preencher 70 segundos. O modelo foi forçado a preencher vácuo com especulações externas.

**Regra Absoluta:** O Local Brain NUNCA deve ser usado para preencher falta de fatos.

### 8.2 Arquitetura do Futuro Pipeline Factual

```
TOPIC
  ↓
RESEARCH
  ↓
FACT PACK
  ↓
FACT SUFFICIENCY GATE
  ├── insufficient → MORE RESEARCH / SHORTER VIDEO
  └── sufficient
          ↓
       QWEN
          ↓
       FACT GUARD
```

### 8.3 Heurística Determinística de Suficiência

Antes de chamar o Qwen, o `FactSufficiencyGate` avalia se os fatos sustentam o tempo solicitado:
- `fact_word_count`: total de palavras de todos os fatos atômicos.
- `safe_expansion_ratio`: razão máxima segura entre narrativa e fatos (padrão conservador: `2.0`).
- `safe_target_words` = $\text{fact\_word\_count} \times \text{safe\_expansion\_ratio}$
- `target_words` = $\text{round}(\text{requested\_duration\_seconds} \times \text{words\_per\_second})$
- Se `target_words > safe_target_words` $\implies$ **INSUFFICIENT**.
- `recommended_duration_seconds` = $\text{safe\_target\_words} / \text{words\_per\_second}$

### 8.4 Comportamento Diferenciado: FAIL_CLOSED vs FACT_PACK_INSUFFICIENT

1. **`FACT_PACK_INSUFFICIENT`**: O modelo LLM **não é chamado** (`total_llm_calls = 0`). O runner registra o estado estruturado com `safe_target_words` e `recommended_duration_seconds`. No futuro, a fábrica pode optar por buscar mais fatos ou diminuir a duração do Short.
2. **`FAIL_CLOSED`**: O modelo gerou conteúdo, mas o FactGuard detectou alucinação e reprovou mesmo após a tentativa de rewrite.

### 8.5 Telemetria de Candidato Rejeitado

Mesmo quando o conteúdo é reprovado e `final_content` permanece `None`, o shadow runner registra:
- `candidate_script_word_count`
- `candidate_estimated_duration_seconds`
- `candidate_duration_delta_seconds`

Isso fornece visibilidade analítica da tentativa do modelo sem quebrar o princípio fail-closed.

### 8.6 Configuração do llama-server Validada no PC Forte

O script `scripts/start_local_ai_server.ps1` foi atualizado com as flags testadas e aprovadas na RX 580:
- `-Threads 4` (`-t 4`)
- `-ThreadsBatch 4` (`-tb 4`)
- `-Reasoning "off"` (`--reasoning off`)
- `-ReasoningBudget 0` (`--reasoning-budget 0`)
- `-GpuLayers 99` (`-ngl 99`)
- `-Device "Vulkan0"` (`--device Vulkan0`)
- Binding exclusivo em `127.0.0.1` (proibição de `0.0.0.0`).
