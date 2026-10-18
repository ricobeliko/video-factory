# Video Factory V2 — Design System & Guia de Estilo
**Versao:** 2.0 (SaaS Minimalist Dark)
**Data:** 2026-10-18
**Ambiente:** D:\Projetos\MoneyPrinterTurbo-V2

---

## 1. Filosofia de Design

A interface da Video Factory V2 foi concebida sob os seguintes pilares:
1. **Clareza Operacional:** O operador deve entender o estado de cada canal e tarefa em menos de 3 segundos.
2. **"Show the Data, Hide the Chrome" (Tremor):** Reduzir elementos puramente decorativos. Cores existem para sinalizar estados reais, nao para enfeitar.
3. **Consistencia Visual (shadcn):** Mesmos raios de borda, mesmas alturas de input, mesma escala tipografica e espacamentos harmonicos em todas as telas.
4. **Fonte Unica de Edicao:** Cada parametro tem apenas um lugar de configuracao.

---

## 2. Tokens de Design (CSS Variables)

```css
:root {
  /* Canvas & Superficies */
  --v2-bg-canvas: #090d16;
  --v2-bg-sidebar: #0b0f19;
  --v2-bg-card: #0f172a;
  --v2-bg-card-hover: #162036;
  --v2-bg-subdued: #070a10;
  --v2-bg-input: #090d16;

  /* Bordas & Divisores */
  --v2-border-subtle: #1e293b;
  --v2-border-strong: #334155;
  --v2-border-focus: #3b82f6;

  /* Tipografia */
  --v2-text-primary: #f8fafc;
  --v2-text-secondary: #94a3b8;
  --v2-text-muted: #64748b;
  --v2-text-inverted: #020617;

  /* Cores Semanticas */
  --v2-primary: #3b82f6;
  --v2-primary-hover: #2563eb;
  --v2-primary-subtle: rgba(59, 130, 246, 0.12);
  --v2-primary-border: rgba(59, 130, 246, 0.3);

  --v2-success: #10b981;
  --v2-success-subtle: rgba(16, 185, 129, 0.12);
  --v2-success-border: rgba(16, 185, 129, 0.3);

  --v2-warning: #f59e0b;
  --v2-warning-subtle: rgba(245, 158, 11, 0.12);
  --v2-warning-border: rgba(245, 158, 11, 0.3);

  --v2-danger: #ef4444;
  --v2-danger-subtle: rgba(239, 68, 68, 0.12);
  --v2-danger-border: rgba(239, 68, 68, 0.3);

  /* Espacamento & Raios */
  --v2-radius-sm: 4px;
  --v2-radius-md: 6px;
  --v2-radius-lg: 8px;
  --v2-radius-full: 9999px;

  --v2-sidebar-width: 240px;
  --v2-header-height: 56px;
}
```

---

## 3. Escala Tipografica

| Elemento | Tamanho | Peso | Cor |
| :--- | :--- | :--- | :--- |
| **KPI Metric** | 26px | 700 (Bold) | `--v2-text-primary` (#f8fafc) |
| **Page Title** | 20px | 600 (Semibold) | `--v2-text-primary` (#f8fafc) |
| **Section Header** | 15px | 600 (Semibold) | `--v2-text-primary` (#f1f5f9) |
| **Card Title** | 13px | 600 (Semibold) | `--v2-text-primary` (#f1f5f9) |
| **Body / Labels** | 13px | 400 (Regular) | `--v2-text-secondary` (#94a3b8) |
| **Caption / Metadados** | 11px | 500 (Medium) | `--v2-text-muted` (#64748b) |

---

## 4. Componentes Padronizados

1. **Card KPI (Estilo Tremor):**
   - Padding: 16px
   - Borda: 1px solid `--v2-border-subtle`
   - Background: `--v2-bg-card`
   - Top label: 12px muted
   - Main Metric: 26px bold
   - Context footer: barra de progresso ou delta badge sutil.
2. **Sidebar (Estilo shadcn-admin):**
   - Largura fixa: 240px em desktop.
   - Header com icone e titulo elegante.
   - Botoes de navegacao com icone, label e badge numerico sutil quando aplicavel.
   - Transicao de hover suave (0.15s ease).
3. **Cabecalho Global (Header):**
   - Altura: 56px.
   - Titulo da pagina ativa + status simplificado.
   - Acoes rapidas agrupadas e sem excesso de informacao tecnica.
4. **Formularios e Modais:**
   - Inputs com altura padrao de 36px, fundo dark `#090d16` e borda `#1e293b`.
   - Modais com overlay backdrop-filter blur de 6px.
   - Templates fixos (Quiz) com campos readonly explicitamente travados.

---

## 5. Breakpoints Responsivos

- **Desktop (>= 1280px):** Layout completo com sidebar 240px e grids de 4 colunas nos KPIs.
- **Notebook (1024px - 1279px):** Sidebar mantida em 220px, KPIs em 2x2.
- **Tablet / Telas menores (768px - 1023px):** Sidebar compacta ou toggle, grid adaptativo.
- **Mobile (< 768px):** Sidebar colapsavel em drawer, colunas empilhadas (1 coluna).
