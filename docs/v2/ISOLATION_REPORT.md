# RELATÓRIO DE ISOLAMENTO — VIDEO FACTORY V2 (FASE V2.0)

**Data:** 18/10/2026  
**Status do Gate:** `ISOLATION_PASS` (100% Homologado)  
**Ambiente V2:** `D:\Projetos\MoneyPrinterTurbo-V2`  
**Branch Git:** `feat/video-factory-v2`  
**Commit Origem:** `cf7d647`  

---

## 1. Topologia e Isolamento Físico

| Componente | Produção (PC Forte) | DEV Original | Video Factory V2 |
| :--- | :--- | :--- | :--- |
| **Caminho Físico** | `C:\Projetos\MoneyPrinterTurbo` | `D:\Projetos\MoneyPrinterTurbo` | `D:\Projetos\MoneyPrinterTurbo-V2` |
| **Branch Git** | `main` (commit estável de deploy) | `main` | `feat/video-factory-v2` |
| **Ambiente Python** | Python 3.11 nativo / serviço nssm | `.venv` compartilhado | `.venv` próprio (CPython 3.11.16 isolado via uv) |
| **Frontend Node.js** | N/A (serviço estático compilado) | `webui-v2/node_modules` | `webui-v2/node_modules` próprio (Node v24.19.0) |
| **Banco SQLite** | `storage/video_factory.db` (PROD) | `storage/video_factory.db` (DEV) | `storage/video_factory_v2.db` (Isolado V2) |
| **Porta HTTP / API** | 8080 (FastAPI) + 8501 (Streamlit) | Portas de teste | 8090 (FastAPI V2) / 5174 (Vite Dev) |
| **Publicação Externa** | Autorizada e ativa | Controlada por mocks | **ESTRITAMENTE BLOQUEADA** (`auto_publish=False`) |
| **Scheduler em Loop**| Ativo via serviço Windows | Inativo ou manual | **DESATIVADO POR PADRÃO** (Sem background loop) |

---

## 2. Mecanismos de Proteção Ativa

1. **Guarda de Isolamento (`app/services/isolation_guard.py`):**
   - Valida programmaticamente que nenhum caminho pertencente a `C:\Projetos\MoneyPrinterTurbo` ou `D:\Projetos\MoneyPrinterTurbo\storage\video_factory.db` possa ser aberto, lido ou escrito por rotinas da V2.
   - Qualquer tentativa lança `IsolationViolationError` com severidade `CRITICAL`.
   - `is_external_publication_allowed()` retorna estritamente `False` na V2.

2. **Isolamento de Credenciais e Serviços:**
   - Variáveis de ambiente de produção não são injetadas no ambiente V2.
   - Chamadas aos clientes de publicação utilizam mocks determinísticos.

3. **Validação do DEV Original:**
   - O repositório original `D:\Projetos\MoneyPrinterTurbo` permanece exatamente no estado anterior, sem modificações ou commits de V2 na branch `main`.

---

## 3. Validação Executada

- Suíte de testes: `test.test_v2_isolation`
- Executada com: `.\.venv\Scripts\python.exe -m unittest test.test_v2_isolation`
- Resultado: **6 testes executados, 6 aprovados (100% PASS)**
- Gate `ISOLATION_PASS` liberado para avanço autônomo à **FASE V2.1 — AUDITORIA FUNCIONAL COMPLETA**.
