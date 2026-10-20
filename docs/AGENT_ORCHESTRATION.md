# Protocolo de Orquestração Nativa Assistida — Video Factory V1

Este documento estabelece o protocolo canônico, enxuto e persistente de coordenação multiagente para evolução estrutural da **Video Factory V1** (`MoneyPrinterTurbo-V1`), utilizando exclusivamente as primitivas nativas do ambiente de agentes e o MCP Trello oficial.

---

## 1. Unidade de Coordenação e Quadro Trello

- **Quadro Oficial:** `Video Factory V1 | Reorganização Estrutural` (`https://trello.com/b/0ewihckV`)
- **Regra de Granularidade:** Cada tarefa ou lote técnico corresponde a **1 cartão Trello único**, que concentra o escopo autorizado, arquivos permitidos, critérios de aceite (DoD), branch/worktree e trilha de auditoria em comentários.
- **Fluxo nas 6 Listas Canônicas:**
  1. `01 · Backlog` — Tarefas identificadas aguardando detalhamento ou priorização.
  2. `02 · Em auditoria` — Escopo, diagnóstico técnico, contratos e isolamento em definição pelo Arquiteto-Chefe.
  3. `03 · Arquitetura aprovada` — Plano técnico validado e autorizado pelo Operador para execução.
  4. `04 · Em implementação` — Subagente especialista atuando no worktree isolado do lote.
  5. `05 · Em validação` — Implementação e testes locais concluídos pelo subagente; aguardando auditoria independente do Arquiteto-Chefe.
  6. `06 · Concluído` — Código auditado, integrado localmente na branch consolidada da V1 e homologado.

---

## 2. Modo de Operação Assistida

- A orquestração opera em **modo assistido**: o **Operador humano** inicia ou autoriza explicitamente cada missão (em especial qualquer missão que envolva alteração de código, configuração ou operação em produção).
- Uma vez que a missão está autorizada em `03 · Arquitetura aprovada`, a coordenação interna entre o **Arquiteto-Chefe** e os **Subagentes Especialistas** ocorre de forma autônoma, orientada a eventos (wakeup reativo) e rastreada no cartão Trello até a entrega em `05 · Em validação` / `06 · Concluído`.

---

## 3. Papéis e Ciclo Operacional Nativo

### 3.1. Arquiteto-Chefe (Agente Coordenador e Revisor)
1. **Planejamento e Isolamento:** Define o escopo estrito, critérios de aceite (DoD), arquivos autorizados e prepara o worktree isolado da missão em `.worktrees/<lote>` (com branch dedicada).
2. **Despacho Nativo:** Instancia e aciona o subagente especialista via `define_subagent` + `invoke_subagent` (ou `send_message` para subagente existente), fornecendo o ID/ARI do cartão Trello e os limites do worktree.
3. **Recebimento Reativo:** Aguarda o retorno automático do subagente via `<SYSTEM_MESSAGE>` (sem loops de polling).
4. **Auditoria Independente:** Inspeciona diretamente `git status`, `git diff` e a execução de testes no worktree do lote, além de verificar a integridade do repositório principal e demais worktrees.
5. **Homologação ou Devolução:**
   - **Aprovado:** Realiza o merge local na branch integrada da V1, registra o parecer de auditoria e o SHA consolidado no cartão Trello e move o cartão para `06 · Concluído`.
   - **Reprovado:** Registra os achados (`CF-XX`) em comentário no cartão Trello, move o cartão de volta para `04 · Em implementação` e reaciona o subagente via `send_message`.

### 3.2. Subagentes Especialistas (Agentes 1, 2, 3 e Documentação)
1. **Leitura e Início:** Lê o cartão da missão em `03 · Arquitetura aprovada` via MCP Trello (`trelloReadCard`) e move-o imediatamente para `04 · Em implementação` (`trelloWriteCard`).
2. **Execução Isolada:** Opera **exclusivamente** dentro do worktree designado (`.worktrees/<lote>`), restrito aos arquivos autorizados no cartão.
3. **Validação Local (`TEST POLICY`):** Executa a validação exigida pelas regras de `AGENTS.md`:
   - Mudança somente documental: não exige `pytest` (valida com `git diff --check` e `git status`).
   - Mudança em código: executa no máximo 1 comando inicial de `pytest` direcionado (arquivo específico e/ou `-k`); se passar, parar.
   - Regressão completa ou coverage: **somente com autorização humana explícita** (concluir um gate não autoriza regressão completa).
4. **Commit e Registro:** Realiza commit local na branch do worktree, publica comentário estruturado de entrega no cartão Trello (contendo Worktree, Branch, Commit SHA, arquivos tocados e resultado da validação) e move o cartão para `05 · Em validação`.
5. **Retorno ao Arquiteto:** Reporta a conclusão ao Arquiteto-Chefe via `send_message` e encerra o turno.

---

## 4. Limites Estritos de Segurança e Governança

1. **Proibição de Operações Críticas por Subagentes:** Nenhum subagente está autorizado a executar deploy, `git push`, merge na branch integrada ou aprovação para produção.
2. **Ausência de Sandbox Físico em `EnableWriteTools=true`:** A flag `EnableWriteTools=true` habilita ferramentas de escrita no ambiente, mas **não constitui sandbox físico de filesystem** por diretório. Portanto, antes de qualquer merge ou homologação, o Arquiteto-Chefe deve verificar obrigatoriamente `git status` e `git diff` **tanto no worktree do lote quanto no repositório principal (`C:\Projetos\MoneyPrinterTurbo-V1`) e nos demais worktrees**, garantindo zero contaminação cruzada.
3. **Proteção da V2 e do PC Forte (Produção):** A Video Factory V2 e o ambiente de produção (PC Forte) permanecem estritamente intocáveis sem autorização humana específica e explícita do Operador.
4. **Zero Infraestrutura Paralela de Orquestração:** É estritamente proibida a criação de bots externos, scripts de polling contínuo, daemons/sidecars paralelos ou camadas intermediárias (`AgentBridge`); toda coordenação utiliza apenas as ferramentas nativas da plataforma e o MCP Trello.
