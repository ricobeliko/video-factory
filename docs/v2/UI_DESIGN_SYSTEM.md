# VIDEO FACTORY V2.11 — SISTEMA DE DESIGN SHADCN ADMIN (ZINC DARK THEME)

## 1. Filosofia de Design e Referência Canônica
A Video Factory V2.11 adota a arquitetura de design visual idêntica ao projeto open source **`satnaing/shadcn-admin`** ([https://github.com/satnaing/shadcn-admin](https://github.com/satnaing/shadcn-admin) | [https://shadcn-admin.netlify.app](https://shadcn-admin.netlify.app/)).

A paleta azul-escura/navy anterior foi totalmente descontinuada e substituída pela autêntica paleta **Zinc / Neutral Dark** do ecossistema shadcn/ui. O objetivo é proporcionar um ambiente de trabalho operacional com estética contemporânea, densidade equilibrada, contraste de alta nitidez e microinterações táteis via CSS nativo.

---

## 2. Tokens de Design (Shadcn Zinc Tokens)

| Token CSS | Valor Hex / Fallback | Mapeamento Tailwind / Shadcn | Uso no Produto |
|---|---|---|---|
| `--v2-bg-canvas` | `#09090b` | `zinc-950` (`oklch(0.145 0 0)`) | Fundo principal da aplicação e sidebar |
| `--v2-bg-card` | `#0c0c0e` | `zinc-900` sutilmente elevado | Superfície dos cards KPI e painéis |
| `--v2-bg-card-hover` | `#121215` | `zinc-900` hover | Elevação ao passar o mouse em cards interativos |
| `--v2-bg-subdued` | `#121215` | `zinc-900` container | Fundo de linhas de lista, cabeçalhos de tabela |
| `--v2-bg-input` | `#121215` | `zinc-900` | Inputs, selects e textareas |
| `--v2-border-subtle` | `#27272a` | `zinc-800` (`oklch(0.269 0 0)`) | Bordas estruturais 1px limpas |
| `--v2-border-strong` | `#3f3f46` | `zinc-700` | Bordas no hover e separadores enfatizados |
| `--v2-ring` | `#71717a` | `zinc-500` | Anel de foco acessível (`focus-visible`) |
| `--v2-text-primary` | `#fafafa` | `zinc-50` (`oklch(0.985 0 0)`) | Títulos, métricas e textos primários |
| `--v2-text-secondary` | `#a1a1aa` | `zinc-400` | Rótulos, descrições e itens secundários |
| `--v2-text-muted` | `#71717a` | `zinc-500` | Metadados e textos desabilitados |
| `--v2-primary` | `#fafafa` | `zinc-50` | Botão primário Shadcn (fundo branco / texto escuro) |
| `--v2-primary-fg` | `#09090b` | `zinc-950` | Cor de texto para botões primários |
| `--v2-secondary` | `#27272a` | `zinc-800` | Botão secundário e item ativo da sidebar |
| `--v2-success` | `#10b981` | `emerald-500` | Indicador de fábrica online e tarefas ativas |
| `--v2-warning` | `#f59e0b` | `amber-500` | Indicador de fábrica pausada ou aviso |
| `--v2-danger` | `#ef4444` | `rose-500` | Erros reais de renderização ou serviços parados |

---

## 3. Microinterações Implementadas

### A. Cards e Superfícies
- **Elevação Dinâmica:** Cards interativos (`.v2-kpi-card`, `.v2-upcoming-row`, `.v2-channel-summary-row`) realizam elevação sutil (`transform: translateY(-1.5px)`), aumento de sombra (`box-shadow: 0 4px 20px -2px rgba(0, 0, 0, 0.6)`) e clareamento de borda (`border-color: var(--v2-border-strong)`).
- **Cards Estáticos:** Cards puramente informativos (como itens de saúde do sistema) não sofrem translações desnecessárias, apenas clareamento suave de borda.

### B. Botões e Ações
- **Feedback Tátil:** Ao serem pressionados (`:active`), os botões reduzem sutilmente a escala (`transform: scale(0.98)`), fornecendo sensação tátil imediata sem causar layout shift (CLS = 0).
- **Estados Desabilitados:** `opacity: 0.5; pointer-events: none; transform: none; cursor: not-allowed`.
- **Botão Primário Shadcn:** Branco puro (`#fafafa`) com texto escuro (`#09090b`), hover para `#f4f4f5`.

### C. Sidebar
- **Item Ativo:** Fundo `#27272a` (Zinc-800), texto `#fafafa`, borda sutil `#3f3f46` e peso semi-bold (`font-weight: 600`), idêntico à navegação lateral do `satnaing/shadcn-admin`.
- **Hover:** `rgba(255, 255, 255, 0.04)` com transição suave (`0.15s cubic-bezier(0.16, 1, 0.3, 1)`).

### D. Modais e Drawers
- **Entrada Suave:** `@keyframes v2-fade-in` (`opacity: 0 -> 1` e `scale(0.985) -> 1`).
- **Backdrop:** Escurecimento neutro com filtro `backdrop-filter: blur(4px)`.
- **Fechamento:** Suporte a tecla `Escape` e botão `.v2-btn-close`.

### E. Listas e Tabelas
- **Linhas Interativas:** `tr:hover` aplica `background-color: rgba(255, 255, 255, 0.025)` com transição de 0.15s, facilitando leitura contínua de grandes listas.

### F. Acessibilidade e Reduced Motion
- **Prevenção de Vertigem/Náusea:** Implementado `@media (prefers-reduced-motion: reduce)` que zera durações de animações e transições instantaneamente.
- **Navegação por Teclado:** Foco visível padronizado com anel duplo Shadcn (`0 0 0 2px var(--v2-bg-canvas), 0 0 0 4px var(--v2-ring)`).
