# CONTEXT — Video Factory / MoneyPrinterTurbo

> **Documento de Contexto Operacional e Estratégico**
> Atualizado em: 07/10/2026

---

## 1. Estado Atual Canônico

- **CURRENT_FOCUS** = `VIDEO_QUALITY_GOOGLE_FLOW`
- **CURRENT_PHASE** = `V1.1_FIRST_REAL_VIDEO`
- **PROJECT_STATUS** = `ACTIVE_DEV / NEW_TRACK_INITIALIZED`
- **ACTIVE_BRANCH** = `main`
- **NEXT_GATE** = `PRODUCE_FIRST_REAL_VIDEO_WORKFLOW`

---

## 2. Objetivo da Frente de Qualidade Visual

Melhorar significativamente a qualidade visual dos vídeos produzidos pela fábrica utilizando **Google AI Pro / Google Flow / Nano Banana** como geração visual externa, mantendo a **Video Factory (MoneyPrinterTurbo)** como o núcleo orquestrador e produtor responsável por:

- **Roteiro:** geração de script estruturado por cenas.
- **Narração:** síntese de voz TTS neural e temporização de áudio.
- **Montagem:** composição final dos clipes, alinhamento temporal e renderização.
- **Legendas:** renderização de legendas dinâmicas ou nativas (formato ASS / burn-in).
- **Música:** trilha sonora de fundo e mixagem de áudio.
- **Publicação:** gestão de canais, metadados e publicação automatizada no YouTube.

---

## 3. Filosofia Operacional: "FAZER MENOS"

Todas as tarefas desta frente devem seguir rigorosamente os seguintes princípios:

1. **Fazer menos:** não construir código ou processos além do estritamente necessário.
2. **Sem arquitetura excessiva:** não criar camadas de abstração prematuras ou especulativas.
3. **Sem testes redundantes:** executar somente testes diretamente relacionados às alterações; alterações puramente documentais não disparam testes (`pytest`).
4. **Sem gates desnecessários:** eliminar burocracias que atrasem a entrega de resultados reais.
5. **Não reconstruir o que já existe:** reaproveitar integralmente a infraestrutura consolidada da Video Factory.
6. **Se funcionou, considerar concluído:** evitar loops de polimento desnecessários.
7. **Não pedir aprovação de cada comando:** agir com autonomia técnica dentro dos limites seguros do projeto.
8. **Não criar infraestrutura especulativa:** implementar apenas o que for exigido pelo passo imediato.
9. **Priorizar solução pronta:** preferir ferramentas, scripts e fluxos já existentes e validados.

---

## 4. Separação Estrita de Ambientes: DEV-FIRST / PRODUCTION-LAST

O projeto opera sob a regra mandatória **DEV-FIRST / PRODUCTION-LAST** em dois ambientes físicos totalmente distintos. **NUNCA misturar os dois ambientes:**

| Ambiente | Host / Máquina | Diretório Raiz | Função |
| :--- | :--- | :--- | :--- |
| **DEV** | Notebook (Desenvolvimento) | `D:\Projetos\MoneyPrinterTurbo` | Todo desenvolvimento, criação de scripts, validações locais, experimentação e testes pontuais. |
| **PRODUÇÃO** | PC Forte (Produção) | `C:\Projetos\MoneyPrinterTurbo` | Ambiente de produção: execução autônoma, render oficial, agendador (`Scheduler`) e publicação ativa. |

### Regras Mandatórias de Operação:
1. **Todo desenvolvimento ocorre no NOTEBOOK:** `D:\Projetos\MoneyPrinterTurbo`.
2. **O PC FORTE é ambiente de produção:** `C:\Projetos\MoneyPrinterTurbo`.
3. **Sem experimentação no PC Forte:** Não implementar, experimentar ou fazer investigação exploratória no PC Forte quando isso puder ser feito no notebook.
4. **Critérios estritos de promoção:** Só levar alterações ao PC Forte quando:
   - A implementação estiver pronta e validada no notebook; ou
   - Houver um teste que dependa especificamente do ambiente de produção.
5. **Sem sincronizações parciais:** Não sincronizar mudanças parciais apenas para testar hipóteses.
6. **Isolamento absoluto:** Sempre preservar a regra: nunca misturar os dois ambientes.

---

## 5. Delimitação de Modelos e Escopo

- **Google Flow API:** **NÃO integrar neste momento.** Primeiro devemos produzir vídeos reais manualmente no Google Flow para vivenciar e aprender o workflow na prática antes de qualquer automação.
- **MuseTalk local (RX580 + DirectML):** POC já concluída com sucesso. Fica **estritamente congelado** como laboratório e fallback futuro. Não trabalhar nele nesta fase.
- **Modelos/Serviços fora de escopo:** Krea, HeyGen pago e ElevenLabs vídeo estão formalmente fora do escopo atual.
- **Hardware Generativo Local:** Geração pesada de vídeo localmente na GPU atual não é recomendada; foco total em geração externa via Google Flow.

---

## 6. Roadmap da Nova Frente

```text
V1.1 (Atual) ──> V1.2 (Otimização) ──> V1.3 (Agente Diretor) ──> V1.4 (Automação API) ──> Futuro (Hardware)
```

- **V1.1 — Primeiro Vídeo REAL (CURRENT_PHASE):**
  - Produzir o primeiro vídeo real utilizando roteiro e narração já existentes da Video Factory.
  - Gerar manualmente os clipes visuais no Google Flow (Nano Banana / Google AI Pro).
  - Utilizar a Video Factory para montagem, legendagem, música e publicação.
- **V1.2 — Otimizar Atrito Manual:**
  - Otimizar somente os passos manuais que efetivamente gerarem retrabalho na prática.
- **V1.3 — Agente Assistente de Cenas & Prompts:**
  - Agente prepara a divisão de cenas, prompts visuais e manifesto de mídia estruturado.
- **V1.4 — Avaliação de API & Automação:**
  - Avaliar viabilidade de automação e integração de API somente após a validação de múltiplos vídeos reais.
- **Futuro — Hardware e Geração Local:**
  - Upgrade de hardware e eventual reavaliação de geração local (mantendo MuseTalk DirectML como fallback).

---

## 7. Documentação Canônica de Referência

A documentação detalhada e histórico completo de engenharia residem em `docs/`:

- [docs/PROJECT_HANDOFF.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/PROJECT_HANDOFF.md) — Estado consolidado dos componentes, deploys e backlog.
- [docs/ROADMAP.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/ROADMAP.md) — Linha do tempo de todas as fases e evolução do sistema.
- [docs/PRODUCTION_RUNBOOK.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/PRODUCTION_RUNBOOK.md) — Procedimentos operacionais seguros em produção (PC Forte).
- [docs/DOCUMENTATION_POLICY.md](file:///d:/Projetos/MoneyPrinterTurbo/docs/DOCUMENTATION_POLICY.md) — Regras de governança de documentação para agentes e desenvolvedores.
