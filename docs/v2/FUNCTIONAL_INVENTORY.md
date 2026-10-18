# Video Factory V2 — Inventário Funcional Completo
**Documento de Auditoria V2.1**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Visão Geral das Páginas e Telas Streamlit

A interface Streamlit atual (`webui/Main.py` e componentes) está estruturada em torno de um único arquivo monolítico de mais de 10.000 linhas, complementado por consoles auxiliares (`operator_console.py`, `channel_factory.py`).

| Tela / Módulo Streamlit | Arquivo Fonte | Responsabilidade Funcional |
| :--- | :--- | :--- |
| **Grid de Geração Principal (4 Colunas)** | `webui/Main.py` | Entrada de tema/roteiro, seleção de vídeo/materiais, áudio/locução/BGM e legenda. |
| **Geração Individual e Lote** | `webui/Main.py` | Disparo de geração única (`generate_video`) ou lote (`parse_batch_topics`, max 10 vídeos simultâneos). |
| **Channel Factory (Fábrica de Canais)** | `webui/components/channel_factory.py` | Cadastro de canais, vínculo com perfis de conteúdo, seleção de contas Post for Me (YouTube/TikTok), metas de estoque e autonomia. |
| **Console do Operador (Operator Console)** | `webui/components/operator_console.py` | Visão operacional unificada: métricas de estoque, tarefas ativas, status do Scheduler, monitoramento de saúde e fila. |
| **Trend Radar (Radar de Tendências)** | `webui/Main.py` | Coleta de tópicos quentes do YouTube / Google Trends para alimentar o gerador de roteiro. |
| **Controle de Tarefas e Recuperação** | `webui/Main.py` (dialog) | Listagem de tarefas em andamento, cancelamento forçado, visualização de logs em tempo real e retomada de falhas. |
| **Diálogo de Publicação Manual** | `webui/Main.py` (dialog) | Envio ad-hoc de vídeo do estoque para YouTube ou TikTok via Post for Me com preenchimento manual de título/descrição. |
| **Configurações Globais (Settings Modal)** | `webui/Main.py` (dialog) | Configuração de chaves de API (LLM, Pexels, ElevenLabs, Post for Me), diretórios de saída e opções do FFmpeg. |

---

## 2. Ações Operacionais Disponíveis

1. **Geração de Vídeo Tradicional:**
   - LLM gera roteiro de 3 a 5 parágrafos.
   - Pexels/Pixabay busca clipes por termo de busca extraído.
   - Narração gerada por EdgeTTS / Azure / ElevenLabs.
   - Montagem via FFmpeg com transições e legendas sincronizadas.
2. **Geração de Vídeo Quiz Q0-R (Dilema / Escolhas Impossíveis):**
   - Roteiro estruturado em JSON com 2 opções contrastantes.
   - Geração de áudio para pergunta, opções e contagem regressiva.
   - Renderização especializada com split vertical e barra de votação visual homologada.
3. **Geração de Vídeo Quiz de Papel P1.3:**
   - Roteiro com perguntas e 4 alternativas em papel vintage.
   - Layout congelado com timer circular e reveal sincronizado.
   - Duração travada entre 60s e 65s.
4. **Gerenciamento de Canais:**
   - Criar, editar, ativar/desativar canais.
   - Atribuir formato, nicho, voz preferida e frequência de postagem.
   - Associar canais às contas de destino do Post for Me (multi-projeto).
5. **Automação e Estoque:**
   - Scheduler verifica meta de estoque por canal.
   - Se estoque < meta, enfileira tarefas de geração autônoma.
   - Publicador automático consome vídeos prontos e dispara no horário agendado.
6. **Analytics e Auditoria:**
   - Métricas de vídeos gerados, taxa de falhas e consumo de API.
   - Visualização dos logs específicos de cada vídeo (`tasks/{task_id}/task.log`).

---

## 3. Dependências com `st.session_state` e Gargalos

O Streamlit mantém todo o estado do formulário na memória volátil da sessão web:
- `st.session_state['current_channel_id']`
- `st.session_state['voice_name']`
- `st.session_state['active_tasks']`
- Recarregamentos acidentais (F5 ou alteração de dropdown) disparam re-execuções de milhares de linhas, causando travamentos de vários minutos e perdas de dados preenchidos.
- No V2, todo o estado é desacoplado: persistência canônica em SQLite e cache reativo no frontend (React Query / Zustand).
