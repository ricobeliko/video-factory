---
name: video-flow
description: Produção de vídeos de alta qualidade visual utilizando Google AI Pro, Google Flow e Nano Banana como geração externa de clipes, combinados com a Video Factory (MoneyPrinterTurbo) para roteiro, narração, montagem, legendas, música e publicação.
---

# Video Flow — Geração Visual Externa com Video Factory

Esta skill orienta o agente e o operador no fluxo híbrido de produção de vídeos, unindo a geração visual cinematográfica do **Google Flow / Nano Banana / Google AI Pro** com o pipeline automatizado de montagem e publicação da **Video Factory (MoneyPrinterTurbo)**.

---

## 1. Registros e Foco Operacional

- **CURRENT_FOCUS** = `VIDEO_QUALITY_GOOGLE_FLOW`
- **CURRENT_PHASE** = `V1.2_MANUAL_FLOW_OPTIMIZATION`

---

## 2. Princípio Mandatório: "FAZER MENOS"

- **Sem arquitetura excessiva:** Não construir camadas de abstração ou infraestrutura especulativa.
- **Sem integração antecipada de API:** **NÃO integrar API do Google Flow neste momento.** O fluxo inicial deve ser manual para aprender e validar o processo antes de automatizar.
- **Sem testes redundantes:** Testes pontuais e direcionados apenas se houver alteração de código. Mudança documental não exige `pytest`.
- **Sem reconstrução:** Aproveitar 100% dos serviços já prontos da Video Factory (narração TTS neural, corte de áudio, legendas ASS/burn-in, mixagem e publicação).
- **Se funcionou, considerar concluído:** Entregar o objetivo e parar.

---

## 3. Divisão de Responsabilidades

| Responsabilidade | Executor | Descrição |
| :--- | :--- | :--- |
| **Roteiro & Divisão de Cenas** | Video Factory | Estruturação textual e divisão semântica das cenas. |
| **Narração & Voz** | Video Factory | Síntese de áudio via Edge TTS neural (`pt-BR-AntonioNeural-Male`) com tempos precisos. |
| **Clipes Visuais** | Google Flow / Nano Banana | Geração visual de alta fidelidade e consistência cinematográfica no ambiente web do Flow. |
| **Montagem & Concatenação** | Video Factory | Alinhamento temporal dos clipes com a narração e transições. |
| **Legendas** | Video Factory | Posicionamento e formatação de legendas ASS nativas (`bottom`, fonte 60, contraste nítido). |
| **Trilha Sonora (BGM)** | Video Factory | Mixagem de música de fundo em volume equilibrado. |
| **Publicação** | Video Factory | Agendamento e upload seguro para o YouTube. |

---

## 4. Workflow de Execução (Fase V1.1 — Primeiro Vídeo Real)

### Passo 1: Definição de Roteiro e Narração
- Selecionar uma task existente com roteiro e narração aprovados ou gerar uma nova narração limpa via Video Factory.
- Extrair a minutagem/duração de cada cena e a mensagem visual necessária.

### Passo 2: Definição dos Prompts Visuais
- Descrever o prompt de cada clipe visual mantendo coerência estilística, iluminação e enquadramento vertical (`9:16`) para o Google Flow.
- Manter prompts diretos e focados na ação ou atmosfera da cena.

### Passo 3: Geração Externa Manual no Google Flow
- O operador gera manualmente os clipes no Google Flow utilizando os prompts planejados.
- Baixar os arquivos de vídeo resultantes (`.mp4`) com as durações correspondentes a cada cena.

### Passo 4: Ingestão e Montagem na Video Factory
- Organizar os clipes nos diretórios de cena da tarefa na Video Factory.
- Executar a montagem final através do pipeline consolidado da Video Factory:
  - Sincronizar clipes com áudio da narração.
  - Aplicar legendas nativas ASS.
  - Aplicar trilha sonora.
  - Renderizar o `.mp4` final em `1080x1920`.

### Passo 5: Validação e Publicação
- Verificar visualmente o vídeo gerado: sincronia de áudio/vídeo, legibilidade das legendas e qualidade dos clipes.
- Publicar através dos fluxos existentes da Video Factory.

---

## 5. Salvaguardas e Limites Rígidos: DEV-FIRST / PRODUCTION-LAST

- **Regra Operacional Obrigatória (DEV-FIRST / PRODUCTION-LAST):**
  - **DEV / Notebook (`D:\Projetos\MoneyPrinterTurbo`):** Todo desenvolvimento ocorre aqui.
  - **PRODUÇÃO / PC Forte (`C:\Projetos\MoneyPrinterTurbo`):** Ambiente estrito de produção.
  - Não implementar, experimentar ou fazer investigação exploratória no PC Forte quando isso puder ser feito no notebook.
  - Só levar alterações ao PC Forte quando:
    1. A implementação estiver pronta e validada no notebook; ou
    2. Houver um teste que dependa especificamente do ambiente de produção.
  - Não sincronizar mudanças parciais apenas para testar hipóteses.
  - Sempre preservar a regra: **nunca misturar os dois ambientes.**
- **MuseTalk Local:**
  - POC concluída com RX580 + DirectML. Fica estritamente **congelado** como laboratório/fallback futuro. Não alterar nem executar nesta frente.
- **Provedores Descartados:**
  - Krea, HeyGen pago e ElevenLabs vídeo estão fora de escopo.

---

## 6. Evolução das Fases

- **V1.1:** Produzir o primeiro vídeo REAL manual com clipe do Flow + montagem da Video Factory (CONCLUÍDA — 90.50s aprovado).
- **V1.2 (CURRENT_PHASE):** Otimizar unicamente os passos manuais que gerarem retrabalho real (prompts, cenas, organização e ingestão).
- **V1.3:** Agente assume suporte à divisão de cenas, redação de prompts e manifesto de mídia.
- **V1.4:** Avaliação de API/automação somente após múltiplos vídeos reais bem-sucedidos.
- **Futuro:** Upgrade de hardware e reavaliação de geração local. Arquitetura de uma única Video Factory para múltiplos canais/nichos.
