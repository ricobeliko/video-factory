# Video Factory V2 — Auditoria de Paridade Funcional e Mapeamento UI (V2.16)

> **Documento Canônico de Auditoria Funcional da Interface**  
> **Data:** 18/10/2026  
> **Ambiente:** Notebook DEV (`C:\Projetos\MoneyPrinterTurbo-V2`)  
> **Branch:** `feat/video-factory-v2`  
> **Princípio Fundamental:** O código real existente é a fonte da verdade. Nenhuma funcionalidade fictícia é introduzida.

---

## 1. Visão Geral da Auditoria

A presente auditoria comparativa examinou minuciosamente:
1. O ecossistema Streamlit legado (`webui/Main.py`, `webui/components/channel_factory.py`, `webui/components/operator_console.py`).
2. Os serviços centrais da fábrica (`app/services/profile_manager.py`, `autonomous_production.py`, `operator_console.py`, `scheduler.py`, `post_for_me.py`, `voice.py`, `bgm.py`, `flow_account_pool.py`).
3. Os contratos FastAPI V2 (`app/controllers/v2/operations.py`, `review.py`, `base.py`).
4. A implementação frontend React/Vite da V2 (`webui-v2/src/`).

---

## 2. Matriz de Mapeamento: Legado Streamlit vs. V2 Atual

| Recurso / Funcionalidade | Origem Legada (Arquivo/Função) | Backend / Serviço Real | Situação V2 Atual | Status | Solução Planejada |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **Identidade do Canal (Nome, Nicho, Idioma)** | `channel_factory.py` (Bloco 1) | `profile_manager.create_profile` / `update_profile` | Presente em `CreateChannelModal.jsx` | **OK** | Preservar e integrar ao novo wizard estruturado |
| **Formato de Vídeo Homologado (Tradicional, Quiz Q0-R, Quiz Papel P1.3)** | `channel_factory.py` (L100-141) | `profile_manager.py` (`ChannelWorkspaceSettings.editorial.video_format`) | Presente via `GET /api/v2/templates` | **OK** | Manter cards visuais com badges e tags de campos imutáveis |
| **Descrição Editorial / Tema Base (`topic_brief`)** | `channel_factory.py` (L109-114) | `EditorialSettings.topic_brief` | **Ausente** no `CreateChannelModal.jsx` e readonly no `ChannelDetailView` | **GAP** | Adicionar ao `CreateChannelRequest` no backend e input no modal |
| **Controles do Quiz Dilema (Q0-R: Encerramento e Qtd Dilemas)** | `channel_factory.py` (L118-138) | `EditorialSettings.closing_type`, `num_questions` | **Ausente** no modal e na edição de canal | **GAP** | Injetar campos condicionais quando `format_type == 'quiz_dilemma'` |
| **Destinos Sociais YouTube (Post for Me)** | `channel_factory.py` (L146-171) | `post_for_me.list_connected_publishing_accounts("youtube")` | **Ausente** (sem endpoint FastAPI V2) | **GAP** | Criar endpoint `GET /api/v2/publishing-accounts` e selector no modal |
| **Destinos Sociais TikTok (Post for Me)** | `channel_factory.py` (L172-196) | `post_for_me.list_connected_publishing_accounts("tiktok")` | **Ausente** (sem endpoint FastAPI V2) | **GAP** | Adicionar no endpoint `GET /api/v2/publishing-accounts` e selector |
| **Vínculo Físico de Canal (`publishing_channels`)** | `channel_factory.py` (L260-290) | `profile_manager.create_channel` | Criação em V2 cria apenas profile, sem vincular canais sociais | **GAP** | `POST /api/v2/channels` invoca `profile_manager.create_channel` quando contas selecionadas |
| **Voz do Narrador por Canal (`voice_name`)** | `channel_factory.py` (L199-203) | `VoiceSettings.voice_name` / `azure_voices.json` | Select com apenas 2 opções hardcoded | **GAP** | Criar endpoint `GET /api/v2/voices` com catálogo certificado pt-BR |
| **Visual Director & Fallback Stock** | `channel_factory.py` (L208-214) | `VisualSettings.visual_director_enabled`, `stock_fallback_enabled` | **Ausente** no formulário de criação da V2 | **GAP** | Toggles no bloco de IA/Visual do canal |
| **Google Flow por Canal (`flow_enabled`, `flow_scenes`)** | `channel_factory.py` (L210-218) | `VisualSettings.flow_enabled`, `flow_scene_count` | **Ausente** na criação da V2 (apenas pool global em `ProductionView`) | **GAP** | Configuração de Flow e slider de cenas (1..10) no canal |
| **Som Ambiente / BGM (`music_enabled`, `vol`, `mood`)** | `channel_factory.py` (L220-244) | `MusicSettings.enabled`, `volume`, `default_mood` | **Ausente** no modal de criação e na edição do canal | **GAP** | Controles no bloco de Áudio & Som Ambiente do canal |
| **Metas de Estoque & Autonomia Inicial** | `channel_factory.py` (L204, 248) | `profile_manager.update_profile_quotas`, `set_autonomous_mode_enabled_op` | Presente de forma básica no modal | **OK** | Manter default seguro pausado (`autonomous_enabled=false`) |
| **Teto de Gerações em 24h (`max_generations_24h`)** | `operator_console.py` | `AutomationSettings.max_generations_24h` | Presente apenas na aba de quotas do detalhe | **GAP** | Permitir ajuste de teto inicial ou default inteligente (5) |
| **Janela de Agendamento (`ScheduleSettings`)** | `scheduler.py` | `ScheduleSettings` (`start_hour`, `end_hour`, `timezone`) | Endpoint PATCH existe mas UI não expunha edição completa | **GAP** | Criar controles visuais de janela na aba de agendamentos |
| **Esteira de Produção (Pipeline Causal & Status)** | `operator_console.py` (L45-93) | `operator_console.get_system_status`, `get_live_executions` | Grafo 2x6 empilhado com cards no topo e tela vazia | **GAP** | Redesenhar em **Master-Detail Command Center** |
| **Revisão Humana de Vídeos (Estoque & Aprovação)** | `operator_console.py` | `app/controllers/v2/review.py` | Presente em `VideoReviewView.jsx` | **OK** | Manter e integrar à nova identidade visual |
| **Operação Pause / Resume Global da Fábrica** | `operator_console.py` | `operator_console.pause_factory` / `resume_factory` | Presente no header | **OK** | Preservar e reforçar feedback em tempo real |
| **Disparo de Ciclo Autônomo Supervisionado** | `channel_factory.py` | `operator_console.run_autonomous_cycle_op` | Presente no header e cards | **OK** | Preservar botões e prevenção contra concorrência |

---

## 3. Diagnóstico dos Problemas Estruturais da V2 Atual

### 3.1. Tela de Produção (`ProductionView.jsx`)
- **Problema:** Layout vertical empilhado. Cards dos canais formam um carrossel horizontal estranho no topo, seguido por um container gigante com o grafo ReactFlow 2x6 e muito espaço em branco nas laterais e no fundo.
- **Impacto no Operador:** Baixa densidade de informação útil, excesso de rolagem, sensação de aplicativo inacabado.
- **Solução Arquitetural:** Layout **Master-Detail em Split Screen**:
  - **Painel Master (Esquerda, ~380px):** Lista densa e elegante de canais, mostrando status (RUNNING/IDLE), estágio atual, progresso em porcentagem, formato, contadores de estoque/processamento e botão de foco rápido.
  - **Painel Detail (Direita, Flex 1):** Command deck do canal selecionado:
    - Cabeçalho com métricas em tempo real e ações imediatas (`Executar Ciclo`, `Pausar/Retomar`).
    - Stepper dinâmico dos estágios da esteira e visualização do grafo causal.
    - Monitor da tarefa ativa com telemetria detalhada (provedores, tempos, prompt/tema).
    - Botão contextual para abrir o Trace Causal detalhado no Drawer lateral.

### 3.2. Formulário Novo Canal (`CreateChannelModal.jsx`)
- **Problema:** Formulário único vertical, incompleto, sem opção de vincular contas sociais (YouTube/TikTok), sem configuração de descrição editorial, sem opções específicas do Quiz Dilema, sem Google Flow nem som ambiente.
- **Solução Arquitetural:** Wizard estruturado em 5 etapas progressivas e limpas:
  1. **Identidade & Nicho:** Nome, nicho, formato editorial (Tradicional, Quiz Q0-R, Quiz Papel P1.3) e briefing de tema.
  2. **Regras Específicas do Formato:** Encerramento e número de dilemas (para Quiz Dilema) ou resumo das regras imutáveis (para Quiz de Papel e Tradicional).
  3. **Destinos & Publicação:** Seleção de contas YouTube e TikTok via Post for Me (com opção fail-closed "Somente Estoque").
  4. **Produção, Visual & Áudio:** Seleção de voz certificada pt-BR, ativação de Visual Director, Google Flow (e slider de cenas), e Som Ambiente (volume e mood).
  5. **Metas & Ativação:** Meta de estoque pronto, teto de 24h e default seguro de produção autônoma pausada.

### 3.3. Adaptações Mínimas Necessárias no Backend FastAPI
Para viabilizar a paridade sem refatorar motores nem criar arquiteturas paralelas:
1. **Adicionar endpoint `GET /api/v2/publishing-accounts`:** Retorna contas sociais conectadas no Post for Me (`post_for_me.list_connected_publishing_accounts`), de forma segura, sem expor tokens ou secrets.
2. **Adicionar endpoint `GET /api/v2/voices`:** Retorna o catálogo das vozes pt-BR disponíveis e homologadas da Video Factory.
3. **Expandir `CreateChannelRequest` em `app/controllers/v2/operations.py`:** Aceitar os campos editoriais, de mídia, de som e destinos, repassando-os diretamente para `profile_manager.update_profile_settings` e `profile_manager.create_channel`.

---

## 4. Limitações e Salvaguardas do Ambiente DEV
- **Nenhum envio real a redes sociais:** O ambiente DEV opera com `is_external_publication_allowed() == False` garantido por `isolation_guard.py`.
- **Nenhuma renderização longa durante testes de UI:** Utilizar exclusivamente fixtures sintéticas e endpoints passivos.
- **Fábrica antiga intacta:** O Streamlit em `C:\Projetos\MoneyPrinterTurbo` permanece totalmente desvinculado e seguro.
