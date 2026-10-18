# ROADMAP — VIDEO FACTORY V2
## Reconstrução Organizada da Interface & Desacoplamento do Streamlit

**Versão da Arquitetura:** Video Factory V2  
**Ambiente:** `D:\Projetos\MoneyPrinterTurbo-V2`  
**Branch:** `feat/video-factory-v2`  
**Origem:** `cf7d647`  

---

## 1. Fases e Status dos Gates

| Fase | Descrição | Gate de Saída | Status |
| :--- | :--- | :--- | :--- |
| **V2.0** | Isolamento e Baseline do Ambiente | `ISOLATION_PASS` | **CONCLUÍDO (6/6 PASS)** |
| **V2.1** | Auditoria Funcional Completa & Mapeamento de Duplicações | `AUDIT_COMPLETE` | **CONCLUÍDO** |
| **V2.2** | Arquitetura Mínima, Fonte de Verdade e Contratos de API | `ARCHITECTURE_READY` | **CONCLUÍDO** |
| **V2.3** | Design System Moderno, Navegação e Layout Base | `UI_FOUNDATION_READY` | **EM ANDAMENTO** |
| **V2.4** | Canal como Centro da Aplicação (Channel Workspace) | `CHANNEL_WORKSPACE_READY` | PENDENTE |
| **V2.5** | Formulários Inteligentes por Formato (Tradicional/Quiz) | `FORMAT_AWARE_UI_READY` | PENDENTE |
| **V2.6** | Migração das Demais Funcionalidades & Matriz de Paridade | `FUNCTIONAL_PARITY_PASS` | PENDENTE |
| **V2.7** | Otimização de Desempenho e Tempos de Resposta | `PERFORMANCE_PASS` | PENDENTE |
| **V2.8** | Homologação Integrada, Testes de Migração e Cutover Plan | `V2_DEV_HOMOLOGATED` | PENDENTE |

---

## 2. Princípios de Execução Autônoma

1. **Reaproveitamento Máximo:** Preservar intactos os motores Python homologados (FFmpeg, Quiz Engine, Telemetria, TTS, Idempotência).
2. **Fonte Única de Verdade:** Nenhuma configuração duplicada entre telas ou persistências conflitantes.
3. **Canal Centralizado:** Toda informação, destino, voz, formato, estoque e automação gerenciada a partir do canal.
4. **Proteção Absoluta da Produção:** Zero impacto em `C:\Projetos\MoneyPrinterTurbo` e no DEV original `D:\Projetos\MoneyPrinterTurbo`.
5. **Zero Publicações Reais em DEV:** Publicação externa sempre simulada ou protegida por guarda de isolamento.
