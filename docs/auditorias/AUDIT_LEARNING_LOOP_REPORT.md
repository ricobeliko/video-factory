# Relatório de Auditoria: Ciclo Fechado de Aprendizado (Closed Feedback Loop)

- **Data da Auditoria (UTC):** `2026-10-25T00:18:03.650168+00:00`
- **Banco Inspecionado:** `C:\Projetos\MoneyPrinterTurbo-V1\storage\video_factory.db` *(Modo estritamente somente-leitura `mode=ro`)*
- **Flag Global de Closed Loop (`closed_feedback_loop_enabled`):** `None`
- **Flag Global de Coleta de Métricas (`auto_collection_enabled`):** `None`
- **Último Ciclo de Analytics Executado:** `—`
- **Último Sucesso de Coleta de Analytics:** `—`
- **Total de Decisões de Closed Loop no SQLite:** `0` *(Adaptadas: 0)*

---

## 1. Diagnóstico Consolidado por Canal / Perfil

| Perfil / Canal | Formato | Autônomo? | Snapshots (72–96h) | Amostras Elegíveis | Evidence State | Decisões (Adaptadas) | Última Coleta | Veredito |
| :--- | :---: | :---: | :---: | :---: | :---: | :---: | :---: | :---: |
| **Video Factory Default** | `traditional` | Não | 0 | 0 / 12 | `ERROR_FALLBACK (evidence_read_error)` | 0 (0) | `Nunca` | ⏸️ NÃO FUNCIONA (flag global desativada) |

---

## 2. Detalhamento de Snapshots em `content_analytics` por Janela de Idade

| Perfil | Canal YouTube | < 6h | 6–24h | 24–72h | **72–96h (Janela Alvo)** | > 96h | **Total Snapshots** |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **Video Factory Default** | `channel-default-youtube` | 0 | 0 | 0 | **0** | 0 | **0** |

---

## 3. Motivos de Exclusão de Evidências (`excluded_counts_by_reason`)

*Nenhum motivo de exclusão registrado ou sem publicações para avaliar.*

---
*Relatório gerado automaticamente de forma estritamente somente-leitura pelo `scripts/audit_learning_loop.py`.*
