# Video Factory V2 — Sistema de Identidade Visual e Design System (V2.16)

> **Documento Canônico de Especificação Visual e Arquitetura de Interface**  
> **Data:** 18/10/2026  
> **Ambiente:** Notebook DEV (`C:\Projetos\MoneyPrinterTurbo-V2`)  
> **Branch:** `feat/video-factory-v2`  
> **Princípio:** Interface operacional de alto padrão ("Modern Command Deck"), sem sobrecarga de animações inúteis, com paridade funcional autêntica e densidade informacional inteligente.

---

## 1. Pesquisa de Referências e Direção Visual

### 1.1. Análise Comparativa de Referências

1. **Shadcn UI Blocks ([ui.shadcn.com/blocks](https://ui.shadcn.com/blocks))**:
   - *Pontos fortes:* Tipografia limpa, hierarquia de cards, uso contido de bordas suaves (`border-slate-800`), modais com overlays escuros focados, botões com variantes semânticas claras (`default`, `secondary`, `destructive`, `ghost`).
   - *Adoção:* Estrutura de botões, inputs, abas, badges e modais dialog/drawer com cantos arredondados contidos (`rounded-lg` / 8px).

2. **Sat Naing Shadcn Admin ([github.com/satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin))**:
   - *Pontos fortes:* Shell operacional densa, barra lateral recolhível com ícones destacados, cabeçalho de comando contextual com pílulas de status, tabelas com filtros rápidos e métricas resumidas no topo.
   - *Adoção:* Master-Detail na Esteira de Produção, header contextual com indicadores em tempo real, grid responsivo para Canais e Estoque.

3. **Motion for React ([motion.dev/docs/react](https://motion.dev/docs/react)) & Micro-interações CSS**:
   - *Pontos fortes:* Transições suaves de abas, entrada de modais com fade-in e scale sutil (0.98 -> 1.00), feedback tátil em botões.
   - *Adoção:* Transições CSS e keyframes otimizados para `transform` e `opacity`, garantindo 60fps sem dependências pesadas e respeitando `prefers-reduced-motion`.

---

## 2. Conceito da Identidade: *Modern Command Deck*

A Video Factory V2 não é um CRUD administrativo tradicional de formulários brancos. É uma **central de comando de automação de vídeo em tempo real**.

### 2.1. Pilares da Identidade
- **Central de Comando Operacional:** O operador deve sentir o pulso da fábrica imediatamente ao abrir a tela.
- **Hierarquia Visual Estrita:** Informações operacionais críticas (Erros, Renderizações ativas, Estoque crítico) têm prioridade ótica sobre dados secundários.
- **Master-Detail em telas complexas:** Eliminação de empilhamento vertical cansativo. A esteira de produção divide a tela em trilha de seleção e deck de telemetria.
- **Feedback Vivo e Confiável:** Cada clique (executar ciclo, alternar autonomia, alterar quotas) gera feedback imediato visual e confirmação de persistência real.

---

## 3. Design Tokens e Paleta Semântica

### 3.1. Cores de Superfície (Dark Theme)
```css
--bg-root: #090d16;          /* Fundo principal da aplicação */
--bg-surface: #0f172a;       /* Superfície de cards e painéis secundários */
--bg-surface-elevated: #1e293b; /* Superfície de modais, drawers e dropdowns */
--bg-surface-hover: #1e293b; /* Hover em linhas e botões secundários */
--border-subtle: rgba(255, 255, 255, 0.08); /* Divisões suaves */
--border-focus: #38bdf8;     /* Foco de acessibilidade e destaque ativo */
```

### 3.2. Acentos Semânticos e Status
- **Cyan / Sky (`#0ea5e9` / `#38bdf8`):** Identidade de comando primária, esteira em andamento e seleção de canal ativo.
- **Emerald / Green (`#10b981` / `#34d399`):** Sucesso, canal autônomo ativo, vídeo renderizado, estoque saudável.
- **Amber / Orange (`#f59e0b` / `#fbbf24`):** Atenção, estoque baixo, renderização aguardando slot, processamento em fila.
- **Rose / Red (`#f43f5e` / `#fb7185`):** Falha em pipeline, fábrica pausada, erro de publicação, ação destrutiva.
- **Violet / Purple (`#8b5cf6` / `#a78bfa`):** Motores de Inteligência Artificial, Google Flow, Visual Director.

### 3.3. Tipografia
- **Família Principal:** `Inter`, `-apple-system`, `BlinkMacSystemFont`, `"Segoe UI"`, `Roboto`, sans-serif.
- **Família Monospaçada (Telemetria):** `"JetBrains Mono"`, `"Fira Code"`, `ui-monospace`, monospace (para hashes, tempos de render, logs e contadores).
- **Escala Modular:**
  - `text-xs`: 11px / 1.4 (badges, tags técnicas, metadados)
  - `text-sm`: 13px / 1.5 (corpo principal, labels de formulário)
  - `text-base`: 15px / 1.5 (títulos de cards, valores de métricas)
  - `text-lg`: 18px / 1.4 (títulos de seção)
  - `text-xl`: 22px / 1.3 (títulos de tela, status da central)

---

## 4. Blueprint dos Componentes Principais

### 4.1. App Shell & Navegação
- **Sidebar:** Barra vertical escura (`#0b1120`), ícones Lucide modernos com indicador de rota ativa em pílula azul brilhante, status do ambiente (DEV ISOLADO em verde), versão e link para alternar modo recolhido/expandido.
- **Header Contextual:** Barra superior fixada com glassmorphism (`backdrop-filter: blur(12px)`), título da tela atual com migalhas de pão (breadcrumbs), botão de Emergência Global (Pausar/Retomar Fábrica com indicador pulsante), e contador de vídeos em processamento.

### 4.2. Tela "Meus Canais" (`ChannelListView.jsx`)
- **Filtros e Ações:** Busca por nome, filtro por formato (Tradicional, Dilema, Papel) e status de autonomia.
- **Grid de Canais:** Cards com cabeçalho contendo avatar/ícone de nicho, badge do formato homologado, toggle rápido de modo autônomo, barra de progresso de estoque (vídeos prontos vs meta), chips de contas conectadas (YouTube/TikTok), e botão "Gerenciar Canal".

### 4.3. Wizard "Novo Canal" (`CreateChannelModal.jsx`)
Substituição do formulário longo por um **Wizard com 5 passos claros**:
1. **Passo 1: Identidade & Nicho:** Nome, descrição base (`topic_brief`), nicho e idioma (pt-BR certificado).
2. **Passo 2: Formato Editorial:** Seleção de formato homologado (Tradicional vs Quiz Dilema vs Quiz Papel). Se Quiz Dilema for selecionado, expõe regras de encerramento (`closing_type`) e quantidade de dilemas (`num_questions`).
3. **Passo 3: Destinos Sociais:** Carrega contas conectadas via Post for Me (`GET /api/v2/publishing-accounts`) e permite vincular canal do YouTube e/ou TikTok.
4. **Passo 4: Motores de IA, Voz & Áudio:**
   - Seleção de Voz Neural pt-BR carregada de `GET /api/v2/voices`.
   - Toggles de Visual Director e Fallback Stock.
   - Toggle de Google Flow com slider de cenas (1 a 10).
   - Configurações de Som Ambiente (BGM) com volume e mood.
5. **Passo 5: Estoque, Automação & Revisão:** Meta de estoque, teto de geração diária, status inicial de autonomia (default seguro: pausado) e resumo final para criação com validação.

### 4.4. Tela "Esteira de Produção" (`ProductionView.jsx`)
Transformação radical de layout para **Master-Detail Command Center**:
- **Trilha Lateral de Canais (Master, 360px):**
  - Lista vertical de canais com indicador de status em tempo real (bolinha pulsante verde para renderizando, azul para pronto, cinza para ocioso).
  - Mostra o estágio atual (`script`, `audio`, `visual`, `montage`, `ready`) e barra de progresso.
  - Seleção visual com borda de acento luminosa.
- **Command Deck do Canal Selecionado (Detail, flex-1):**
  - **Barra de Controle Rápido:** Título do canal, nicho, botão "Executar Ciclo Agora" (com debounce), e botão "Ver Trace Causal Completo".
  - **Pipeline Stepper Visual:** 5 etapas horizontais conectadas com badges de status, tempo decorrido de cada etapa e provedor utilizado.
  - **Monitor de Telemetria da Tarefa Ativa:** Card moderno exibindo:
    - ID do Job / UUID
    - Título do vídeo sendo gerado
    - Provedor de imagem (ex: Google Flow / Pexels)
    - Provedor de voz (Azure Speech pt-BR)
    - Log de evento mais recente formatado
  - **Drawer de Trace Causal:** Desliza suavemente da direita com detalhes de causalidade, histórico de transições de estado e detalhes de falhas sem poluir o deck principal.

### 4.5. Detalhe e Edição do Canal (`ChannelDetailView.jsx`)
- Abas contextuais:
  - **Aba Editorial:** Formato, nicho, topic_brief, regras de quiz.
  - **Aba Áudio & Vídeo:** Voz neural, Flow scenes, BGM volume/mood, Visual Director.
  - **Aba Publicação:** Contas conectadas YouTube/TikTok e status de automação.
  - **Aba Quotas & Automação:** Meta de estoque, teto 24h, botão de toggle de autonomia.

---

## 5. Salvaguardas e Acessibilidade

1. **DEV Isolation Visível:** Indicador constante no rodapé da Sidebar e cabeçalho informando `DEV ISOLATED MODE — ZERO PRODUCTION IMPACT`.
2. **Acessibilidade:**
   - Contraste texto/fundo >= 4.5:1.
   - Indicadores de status combinam cor + texto ou ícone (não apenas cor).
   - `@media (prefers-reduced-motion: reduce)` desabilita animações de pulso e transições complexas.
