# Video Factory V2 — Referencias de Design & Auditoria MCP
**Data:** 2026-10-18
**Ambiente:** D:\Projetos\MoneyPrinterTurbo-V2
**Branch:** feat/video-factory-v2

---

## 1. Pesquisa de Referencias de Design

Para transformar a interface da Video Factory V2 em um produto visualmente profissional, clean, consistente e operacionalmente intuitivo, foram pesquisados quatro projetos e bibliotecas lideres de mercado:

### 1.1. `satnaing/shadcn-admin` (GitHub)
- **Repositorio:** [https://github.com/satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin)
- **Licenca:** MIT
- **Padroes Reutilizados:**
  - **Estrutura de Layout:** Sidebar lateral compacta com secoes agrupadas (Core / Operacional / Sistema) e estado ativo refinado (fundo com opacidade sutil, sem cores berrantes).
  - **Cabecalho Minimalista:** Eliminacao de barras cheias de badges; substituicao por breadcrumb da secao ativa, acoes primarias discretas, status simplificado e icone de notificacoes.
  - **Area de Conteudo (Main Wrapper):** Espacamento consistente (padding de 24px desktop / 16px mobile), containers com max-width fluido e limites claros.
  - **Modais e Drawers:** Acoes pontuais (ex: criar canal, telemetria detalhada) desacopladas da tela principal, mantendo o operador focado.

### 1.2. `ui.shadcn.com/blocks?category=dashboard`
- **Referencia Oficial:** [https://ui.shadcn.com/blocks?category=dashboard](https://ui.shadcn.com/blocks?category=dashboard)
- **Padroes Reutilizados:**
  - **Grid de Cards KPI (4 colunas):** Linha superior com os indicadores vitais que respondem instantaneamente as duvidas do operador:
    1. *Canais Ativos* (Total de perfis e modo de operacao)
    2. *Em Producao* (Tarefas em andamento com indicador de pulso ou estado ocioso)
    3. *Estoque Pronto* (Total de videos aprovados aguardando publicacao)
    4. *Proximo Agendamento* (Horario e canal do proximo video na fila)
  - **Divisao de Conteudo em Duas Colunas:**
    - Painel principal operacional (60%): Lista compacta de canais e progresso de estoque.
    - Painel secundario contextual (40%): Atividade recente, tarefa em execucao e logs de alerta.

### 1.3. `tremorlabs/tremor` (GitHub & tremor.so)
- **Repositorio:** [https://github.com/tremorlabs/tremor](https://github.com/tremorlabs/tremor)
- **Filosofia Central:** *"Show the data, hide the chrome"*.
- **Padroes Reutilizados:**
  - **Hierarquia Tipografica de Metricas:** Titulo do indicador em texto muted (12px, tracking discreto), numero principal em destaque tipografico pesado (26px, weight 700, cor branca pura) e texto de contexto/meta inferior (11px).
  - **Cores Semanticas com Intencao:** O Tremor condena o uso decorativo de cores. Adotamos:
    - *Azul neutro (#3b82f6):* Cor de foco, selecao e acoes primarias.
    - *Esmeralda (#10b981):* Conclusao, aprovacao nos Gates, servicos operacionais ativos.
    - *Ambar (#f59e0b):* Videos aguardando revisao humana, fila pausada.
    - *Rosa/Vermelho (#ef4444):* Erros de pipeline, rejeicao de gates, servico parado inesperadamente.
    - *Slate (#64748b):* Estados inativos neutros ou informativos.

### 1.4. `shadcndashboard/shadcndashboard`
- **Padroes Reutilizados:**
  - **Densidade Visual Otimizada:** Reducao drastica de espacos mortos (white/dark space excessivo) sem amontoar elementos.
  - **Separacao de Responsabilidades:** Informacoes puramente tecnicas (Worker, Scheduler, Flow accounts) encapsuladas em subcards organizados ou abas de Diagnostico, sem poluir o painel de tarefas de rotina.

---

## 2. Investigacao e Decisao de MCPs

Conforme a secao 3 do plano, foram avaliados os MCPs candidatos para automacao e inspecao:

| Servidor MCP | Comando Candidato | Finalidade | Avaliacao no Ambiente | Decisao |
| :--- | :--- | :--- | :--- | :--- |
| **shadcn MCP** | `npx shadcn@latest mcp` | Catalogo e geracao de blocos shadcn | O projeto V2 utiliza React 18 + Vite com design system em Vanilla CSS tokens (para latencia de build <10s e bundle <150kB). Rodar o CLI shadcn exigiria injetar Tailwind compiler completo e dependencias pesadas no runtime. | **NAO INSTALAR:** Componentes e tokens adaptados diretamente no design system React/CSS existente com zero overhead. |
| **Playwright MCP** | `npx @playwright/mcp@latest` | Inspecao visual e navegacao | O ambiente Antigravity ja dispoe do tool nativo `browser_subagent` com gravacao automatica em WebP, captura de tela e suporte nativo ao Chrome DevTools. Alem disso, ha scripts Playwright Python dedicados em DEV. | **NAO INSTALAR:** Capacidade de browser automation ja integralmente coberta pelas ferramentas nativas do agente sem dependencias extras. |

---

## 3. Direcao Visual Escolhida & Justificativa

Adotamos a **Direcao SaaS Minimalista Escura (Dark Mode Refinado)**:

1. **Paleta Base:**
   - Fundo do Canvas: `#090d16` (neutral dark slate)
   - Fundo dos Cards: `#0f172a` (slate-900 com borda `#1e293b`)
   - Fundo de Elevacao/Hover: `#1e293b` (slate-800)
   - Cor Primaria: `#3b82f6` (SaaS Blue discreto)
2. **Eliminacao da Poluicao Visual:**
   - Remocao da barra de 8 badges chamativos no topo.
   - Remocao da aba Agent Ops da navegacao principal do operador.
   - Limitacao de gradientes e eliminacao de caixas aninhadas sem funcao.
3. **Regra de Ouro:** *Uma configuracao = um unico local principal de edicao*.
