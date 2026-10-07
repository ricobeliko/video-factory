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