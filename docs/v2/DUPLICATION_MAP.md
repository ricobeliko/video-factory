# Video Factory V2 — Mapa de Duplicações e Conflitos de Interface
**Documento de Auditoria V2.1**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Mapeamento de Telas e Controles Duplicados

A auditoria identificou diversas áreas onde a mesma entidade ou configuração é manipulada em telas diferentes, gerando divergência de estado e esforço repetitivo do operador:

| Funcionalidade / Controle | Localização 1 | Localização 2 | Localização 3 | Problema Gerado |
| :--- | :--- | :--- | :--- | :--- |
| **Seleção de Voz do Narrador** | `webui/Main.py` (Coluna Áudio) | `channel_factory.py` (Aba Voz) | Diálogo de Geração em Lote | O operador altera a voz no formulário principal, mas ao rodar pelo canal a voz do perfil sobrescreve sem aviso. |
| **Meta de Estoque de Vídeos** | `channel_factory.py` (Aba Metas) | `operator_console.py` (Painel Estoque) | `app/services/scheduler.py` | Configuração duplicada; alterar a meta no console não persistia no banco do canal. |
| **Contas Post for Me / Destinos** | `channel_factory.py` | Diálogo de Publicação Manual | `settings_dialog` | Contas vinculadas a um canal não apareciam pré-selecionadas no diálogo de publicação manual. |
| **Monitoramento de Tarefas** | `Main.py` (Task restore dialog) | `operator_console.py` (Active Tasks) | Logs do terminal | Duas listas distintas de tarefas ativas com estados desincronizados. |
| **Definição de Formato de Vídeo** | Dropdown no topo do `Main.py` | Perfil de Conteúdo na Channel Factory | Parâmetro na geração em lote | Formato tradicional tentava aplicar configurações de quiz e vice-versa. |

---

## 2. Controles Conflitantes e Incompatíveis no Mesmo Formulário

No Streamlit atual, o formulário de 4 colunas tenta acomodar simultaneamente:
1. **Vídeo Tradicional (Pexels / LLM):** Requer termos de busca visual, proporção de tela, transições e busca de tags.
2. **Quiz Q0-R (Escolhas Impossíveis):** Tem layout 1080x1920 congelado, split 50/50, barra de porcentagem de votos e timers rígidos. Não utiliza termos de busca Pexels nem Visual Director.
3. **Quiz de Papel P1.3:** Formato estático com texturas de papel, perguntas e alternativas reveladas em bloco único e duração estrita de 60-65 segundos.

**Sintomas na interface antiga:**
- Ao alternar para "Quiz", os campos de busca de vídeo do Pexels continuavam visíveis, confundindo o usuário.
- O campo de "Google Flow Scenes" aparecia mesmo quando o formato Quiz estava ativo.
- O slider de "Duração do Vídeo" permitia valores como 30 segundos ou 3 minutos, que quebravam o motor do Quiz Paper P1.3.

---

## 3. Resolução Estrutural na Video Factory V2

Na V2, todas as duplicações e conflitos são resolvidos por dois princípios fundamentais:

1. **Canal como Centro:**
   - O operador seleciona o Canal uma única vez no topo ou acessa o painel do Canal.
   - O formato (`traditional`, `quiz_dilemma`, `quiz_paper`), a voz, as contas de destino e as metas de estoque são carregadas automaticamente a partir do registro único do canal.
2. **Formulários Inteligentes Orientados ao Formato (Format-Aware Forms):**
   - Se o formato for **Quiz Q0-R**, os controles de busca visual Pexels e parâmetros de montagem livre são completamente ocultados e substituídos pelos controles exclusivos de dilema (tópicos de escolhas e porcentagem de votos).
   - Se o formato for **Quiz Paper P1.3**, todos os parâmetros técnicos congelados (duração de 60s, layout, fontes e timer) são exibidos como **somente leitura informativos**, impedindo alterações acidentais que quebrem a homologação do formato.
