# Video Factory V2.15A — Manual e Especificação da Auditoria Passiva Pré-Cutover
**Documento Operacional V2.15A**
**Data de Criação:** 18/10/2026
**Script Oficial:** `scripts/v2_pre_cutover_audit.ps1`
**Ambiente Alvo de Execução:** PC Forte (`C:\Projetos\MoneyPrinterTurbo`)

---

## 1. Objetivo e Princípios de Não-Interferência

O script `scripts/v2_pre_cutover_audit.ps1` foi projetado especificamente para a fase pré-cutover da Video Factory V2.
Sua finalidade é auditar minuciosamente o estado real do PC Forte **antes** de qualquer intervenção humana de substituição da interface.

### Garantias de Segurança (100% Passivo):
1. **Somente Leitura:** Não cria, não edita e não deleta arquivos do repositório ou de dados.
2. **Sem Parada de Serviços:** Não interrompe processos, serviços Windows ou tarefas agendadas.
3. **Sem Locks de Banco:** Consultas SQLite são feitas de modo pontual e fechadas imediatamente, sem locks de escrita.
4. **Zero Vazamento de Secrets:** Nenhuma chave de API, cookie, token de sessão ou senha é impressa na tela ou gravada em logs. Apenas indica `CONFIGURED` ou `MISSING`.
5. **Zero Rede / Sem Publicações:** Não envia dados para a internet e não aciona despachos.
6. **Critério Objetivo:** Emite no final um status inegociável de `STATUS AUDITORIA : PASS` (código 0) ou `STATUS AUDITORIA : BLOCKED` (código 2).

---

## 2. Como Executar no PC Forte

O operador humano no PC Forte deve abrir o PowerShell como Administrador e executar:

```powershell
# Opção A: Executar de dentro da raiz do repositório
cd C:\Projetos\MoneyPrinterTurbo
powershell.exe -ExecutionPolicy Bypass -File scripts\v2_pre_cutover_audit.ps1

# Opção B: Especificar o caminho explicitamente
powershell.exe -ExecutionPolicy Bypass -File C:\Projetos\MoneyPrinterTurbo\scripts\v2_pre_cutover_audit.ps1 -RepoPath "C:\Projetos\MoneyPrinterTurbo"
```

---

## 3. Matriz de Checagens Realizadas

| Seção | Itens Inspecionados | Critério de Bloqueio (BLOCKED) | Alertas (WARNING) |
|---|---|---|---|
| **1. Git & Repositório** | Branch, Commit SHA, Working Tree status | Arquivos modificados não commitados que NÃO sejam o hotfix de `autonomous_production.py` ou `.bak` | Hotfix pontual detectado e apto à reconciliação |
| **2. Portas e Processos** | Ocupação de portas 8080 e 8501, processos `python.exe` (Streamlit, Uvicorn) | Nenhum (apenas informativo para planejamento) | Porta 8080 em uso; necessitará parada graciosa |
| **3. Agendador e Serviços** | Scheduled Tasks e Windows Services com termos VideoFactory / MoneyPrinter | Nenhum | Lista tarefas ativas |
| **4. Ferramentas** | Python, Node.js, FFmpeg no PATH | FFmpeg ausente no PATH | Python < 3.10; Node.js ausente |
| **5. Banco SQLite** | Existência de `db.sqlite3` / `storage/db.sqlite3`, `PRAGMA integrity_check`, contagem de tabelas, tarefas ativas | Falha no `integrity_check` (diferente de 'ok') | Tarefas ativas em processamento (`status IN ('processing', 'running')`) |
| **6. Espaço em Disco** | Espaço livre na partição do repositório | Espaço livre < 5 GB | Espaço livre < 15 GB |
| **7. Credenciais (Passivo)** | Presença de chaves no `.env` e variáveis de ambiente (YouTube, TikTok, Gemini, OpenAI, Groq, Pexels) | Nenhum bloqueio direto | Chaves ausentes são destacadas |

---

## 4. Interpretação dos Resultados

- **STATUS AUDITORIA : PASS (Exit Code 0):** O PC Forte está saudável, o banco está íntegro, ferramentas instaladas e o ambiente está liberado para o operador iniciar a janela de cutover.
- **STATUS AUDITORIA : BLOCKED (Exit Code 2):** Existem impedimentos críticos (ex: integridade do SQLite corrompida, arquivos modificados desconhecidos no Git, falta de espaço em disco ou ausência do FFmpeg). **NÃO INICIAR O CUTOVER** até resolver as causas apontadas.
