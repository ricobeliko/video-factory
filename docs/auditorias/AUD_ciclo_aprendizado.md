# Auditoria Canônica do Ciclo Fechado de Aprendizado (Closed Feedback Loop)

- **Documento:** `docs/auditorias/AUD_ciclo_aprendizado.md`
- **Missão:** Missão B — V2 Auditoria de Aprendizado (Somente Leitura)
- **Data:** 24 de Outubro de 2026 (Atualizado com evidências empíricas de PROD em 25/10/2026)
- **Status da Operação:** SOMENTE LEITURA (`mode=ro`). Zero escritas, zero alteração de regras de negócio, zero rede externa.

---

## Sumário Executivo

Esta auditoria técnica investigou detalhadamente o ecossistema de aprendizado de máquina adaptativo e feedback contínuo da Video Factory V1, combinando a análise analítica do código-fonte em DEV (`C:\Projetos\MoneyPrinterTurbo-V1`) com a execução empírica do script de auditoria sobre o banco de dados real de produção no **PC Forte**.

> [!IMPORTANT]
> **Evidência Operacional do PC Forte (Produção Real):**
> A execução no banco de produção revelou **503 decisões de closed loop registradas**, com exatamente **0 decisões adaptadas** (`closed_loop_adapted_total = 0`).
> A causa primária comprovada: **100% dos snapshots de métricas colhidos foram sumariamente excluídos pelo filtro de copyright com o motivo `copyright_unknown`** (descartes por perfil: **251, 188, 18, 11 e 1**). Como nenhuma publicação recebeu auditoria de copyright explícita (`clean_manual`), nenhuma atingiu a elegibilidade para compor evidência estatística.

### Resumo dos Vereditos por Canal

*(Veredictos iniciais estabelecidos por inferência analítica do código-fonte; confirmados e aprofundados pela auditoria empírica do PC Forte)*

| Canal | Formato Técnico | Veredito (Inferência pelo Código) | Evidência Empírica em Produção (PC Forte) |
| :--- | :---: | :---: | :--- |
| **Dose Diária de Internet** (`default`) | Tradicional / Variado | **NÃO FUNCIONA / FALTA DADO** | 188 snapshots excluídos por `copyright_unknown`; 0 amostras elegíveis; 0 decisões adaptadas. |
| **Dose Diária de Histórias e Mistério** (`profile-historias-misterio`) | Tradicional (`mystery`) | **FALTA DADO** | 251 snapshots excluídos por `copyright_unknown`; 0 amostras elegíveis; 0 decisões adaptadas. |
| **Dose Diária de Escolhas** (`profile-4d18bf9a5d94`) | `quiz_dilemma` (Procedural) | **NÃO FUNCIONA** | 18 snapshots excluídos por `copyright_unknown`; sobrescrita incondicional de estrutura (`rec_struct = fixed_format`). |
| **Quiz_Quiz** (`profile-45cee883f80a`) | `quiz_paper` (Procedural) | **NÃO FUNCIONA** | 11 snapshots excluídos por `copyright_unknown`; sobrescrita incondicional e bypass da roteirização tradicional. |
| **Dose Diária de GTA VI** (`profile-gta-vi`) | Tradicional | **FALTA DADO** | 1 snapshot excluído por `copyright_unknown`; canal em pausa operacional. |

---

## 1. Quais Perfis e Formatos Entram de Fato no Closed Loop?

### 1.1 Análise de Código em `autonomous_production.py` *(Inferência pelo Código)*

O ciclo fechado de aprendizado é acionado na esteira autônoma em [autonomous_production.py](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L3038-L3153):

```python
# autonomous_production.py:3038-3042
cl_enabled = operator_console.get_closed_feedback_loop_enabled_op()
if cl_enabled and yt_channel_id:
    evidence = analytics.get_learning_evidence(
        platform="youtube",
        profile_id=profile_id,
        channel_id=yt_channel_id,
        db_path=db_path,
    )
```

Para que qualquer perfil execute este bloco, dois pré-requisitos são avaliados:
1. `operator_console.get_closed_feedback_loop_enabled_op()` deve retornar `True` (chave `closed_feedback_loop_enabled` em `autopilot_settings`).
2. O canal deve possuir um `yt_channel_id` configurado e habilitado na tabela `publishing_channels`.

Caso a evidência seja `ELIGIBLE`, o código seleciona a estrutura e o cluster vencedores:
```python
# autonomous_production.py:3085-3094
best_struct = evidence.get("recommended_narrative_structure")
best_cluster = evidence.get("recommended_topic_cluster")
if best_struct and best_struct in const.NARRATIVE_STRUCTURES:
    rec_struct = best_struct
    struct_source = "closed_feedback_loop"
if best_cluster and best_cluster in ("tech_ai", "science_curiosity", "space_astronomy", "gaming_news"):
    rec_cluster = best_cluster
    cluster_source = "closed_feedback_loop"
```

### 1.2 O Bloqueio / Desvio Estrutural dos Quizzes (`quiz_dilemma` e `quiz_paper`)

Embora os perfis de quiz possam disparar o bloco acima se possuírem `yt_channel_id`, a recomendação do closed loop é **completamente anulada logo a seguir** pelas seguintes causas raízes:

1. **Sobrescrita Incondicional da Estrutura em `autonomous_production.py:3151-3153`:**
   ```python
   # autonomous_production.py:3003-3006
   fixed_format = prof_ctx.get("video_format") or prof_ctx.get("content_style")

   # autonomous_production.py:3151-3153
   if fixed_format and fixed_format not in ("traditional", "standard", "auto", ""):
       rec_struct = fixed_format
   ```
   Como o perfil do Quiz de Escolhas tem `video_format = "quiz_dilemma"` e o Quiz de Papel tem `video_format = "quiz_paper"`, a variável `rec_struct` é **imediatamente revertida para o formato fixo**. A estrutura adaptada pela evidência é descartada.

2. **Bypass da Roteirização Tradicional em `app/services/task.py`:**
   - Em [task.py:2844](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L2844) (`_run_quiz_pipeline`), o fluxo desvia para o motor de dilemas procedurais.
   - Em [task.py:3025](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L3025) (`_run_quiz_paper_pipeline`), o fluxo desvia para o motor procedural de quiz em papel.
   - Nenhum desses dois motores consome `topic_cluster` (`tech_ai`, `science_curiosity`, etc.) ou a estrutura narrativa de 3 atos tradicional. Eles utilizam geradores próprios com prompts fechados de pares de perguntas e dilemas.

3. **Incompatibilidade Semântica de Trends:**
   O Trend Radar ([autonomous_production.py:3047-3065](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L3047-L3065)) busca tópicos noticiosos gerais. Tópicos de notícias não possuem relação semântica com perguntas atemporais de quiz ("Você prefere X ou Y?").

**Conclusão do Item 1:** Para canais tradicionais (`mystery`, `explainer`, `default`), o closed loop consegue teoricamente injetar `rec_struct` e `topic_cluster`. Para `quiz_dilemma` e `quiz_paper`, o closed loop é um **no-op operacional**: consome tempo de banco de dados, mas não afeta em nada a geração.

---

## 2. A Coleta de Métricas Está Agendada e Rodando?

### 2.1 Ponto de Agendamento e Thread Worker

A coleta de analytics é gerenciada pelo scheduler da aplicação:
- **Arquivo / Linha:** [app/services/scheduler.py:3143-3148](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/scheduler.py#L3143-L3148)
- **Função:** `_scheduler_worker_loop()`
- **Processo:** Executado na thread em background do processo `PRIMARY` (iniciado em `production_entrypoint.py` / `webui`).

O loop principal acorda a cada 30 segundos, mas o disparo real de analytics é protegido por um throttle estrito em [app/services/analytics_scheduler.py:794-810](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/analytics_scheduler.py#L794-L810):

```python
ANALYTICS_CYCLE_MIN_INTERVAL_SECONDS = 300  # Intervalo mínimo de 5 minutos
```

Se o ciclo anterior correu há menos de 300 segundos, o agendador aborta imediatamente sem consumir quota.

### 2.2 Plataformas Suportadas e Credenciais

- **Plataformas:** [analytics_scheduler.py:38](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/analytics_scheduler.py#L38) define estritamente:
  ```python
  SUPPORTED_ANALYTICS_PLATFORMS = ("youtube",)
  ```
  O TikTok **não é suportado** para coleta automática de métricas (retorna não suportado).
- **Credenciais Necessárias:**
  O provedor [YouTubeAnalyticsProvider](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/analytics_providers/youtube.py#L33-L51) exige **apenas** uma chave pública de API (`youtube_api_key`), obtida via `config.app["youtube_api_key"]` ou variável de ambiente `YOUTUBE_API_KEY`.
  Não requer fluxo de autorização OAuth2 para obter contadores públicos de visualizações (`viewCount`), curtidas (`likeCount`) e comentários (`commentCount`).

### 2.3 Condições de Bloqueio

A coleta automática de métricas **para imediatamente** nas seguintes situações:
1. `autopilot_settings.auto_collection_enabled` for falso (desligado pelo operador na WebUI ou banco).
2. Ausência da chave `youtube_api_key` configurada no ambiente.
3. Não existência de publicações com status `success` e `privacy_status = 'public'` com IDs externos do YouTube válidos.

---

## 3. O que os Dados Mostram no Banco?

### 3.1 Ambiente DEV (Notebook)

No banco de dados local do ambiente de desenvolvimento (`storage/video_factory.db`):
- A tabela `content_analytics` **não possui snapshots reais de produção** (apenas testes sintéticos).
- A tabela `autopilot_settings` não possui histórico de execuções de analytics (`analytics_last_cycle_at = NULL`).

### 3.2 Regras Estritas de Evidência em Produção (`analytics.py`)

No banco de produção (PC Forte), o algoritmo de validação em [app/services/analytics.py:162-225](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/analytics.py#L162-L225) impõe os seguintes filtros para que um snapshot seja aceito como evidência:

1. **Janela Temporal Restrita (72h a 96h):**
   ```python
   TARGET_AGE_HOURS = 72.0
   MAX_AGE_HOURS = 96.0
   ```
   Qualquer snapshot coletado antes de 72h (ex: 24h ou 48h) ou após 96h é classificado como `incomparable_age` e descartado.
2. **Auditoria de Copyright Obrigatória (`clean_manual`):**
   - Publicações com status de copyright `unknown` são rejeitadas por fail-closed (`copyright_unknown`).
   - Apenas publicações que receberam explicitamente o evento `clean_manual` em `operational_events` são elegíveis.
3. **Filtro de Qualidade e Segurança:**
   - Score de qualidade >= 70 (`GOOD` ou `STRONG`).
   - Safety Gate com status `PASS`.
4. **Tamanho Mínimo de Amostra:**
   - Mínimo de **12 publicações elegíveis** (`MIN_ELIGIBLE_PUBLICATIONS = 12`).
   - Exigência de pelo menos 2 grupos na dimensão analisada com no mínimo 5 amostras cada para haver contraste estatístico válido (`MIN_GROUP_SAMPLES = 5`). Se não houver variação suficiente, o estado é `NO_CONTRAST`.

### 3.3 Evidência Empírica Real do Banco de Produção (PC Forte)

A auditoria em tempo real executada no PC Forte sobre a base `C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db` comprovou matematicamente o diagnóstico:

- **Decisões Registradas:** Foram executadas **503 decisões de closed loop** registradas na tabela `operational_events`.
- **Decisões Adaptadas:** Exatamente **0 decisões adaptadas** (`closed_loop_adapted_total = 0`). A taxa real de adaptação é de **0,0%**.
- **Descarte de Snapshots:** **100% dos snapshots colhidos foram descartados por `copyright_unknown`**.
- **Distribuição de Descartes por Perfil:**
  1. `profile-historias-misterio`: **251** publicações/snapshots descartados (`copyright_unknown`).
  2. `default` (Dose Diária de Internet): **188** publicações/snapshots descartados (`copyright_unknown`).
  3. `profile-4d18bf9a5d94` (Dose Diária de Escolhas): **18** publicações/snapshots descartados (`copyright_unknown`).
  4. `profile-45cee883f80a` (Quiz_Quiz): **11** publicações/snapshots descartados (`copyright_unknown`).
  5. `profile-gta-vi`: **1** publicação/snapshot descartado (`copyright_unknown`).

**Causa Raiz Empírica Definitiva:** O algoritmo de validação em [analytics.py:183-186](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/analytics.py#L183-L186) descarta sumariamente qualquer publicação cujo status de copyright não seja explicitamente `clean_manual`. Como na operação diária os vídeos são publicados sem auditoria humana manual de copyright, 100% das publicações permanecem em `unknown`, tornando impossível qualquer canal atingir as 12 amostras necessárias para adaptação.

---

## 4. Script de Auditoria Somente Leitura (`scripts/audit_learning_loop.py`)

Para que o operador possa auditar o banco de produção do PC Forte sem qualquer risco de contaminação, lock de concorrência ou vazamento de credenciais, foi desenvolvido o script canônico:

[scripts/audit_learning_loop.py](file:///c:/Projetos/MoneyPrinterTurbo-V1/scripts/audit_learning_loop.py)

### 4.1 Características de Segurança e Arquitetura

- **Cópia Segura via `sqlite3.backup`:** O script conecta ao banco ao vivo com URI estrita `Path.as_uri() + "?mode=ro"` e realiza uma cópia snapshot online para um arquivo temporário (`tempfile.mkstemp()`). Isso **elimina falsos alarmes de verificação de hash** causados pelas escritas normais da fábrica em execução e garante isolamento absoluto.
- **Validação de Existência do Banco:** Retorna mensagem de erro clara e fatal (`[ERRO FATAL] Banco de dados SQLite não encontrado...`) com código de saída 1 caso o caminho informado não exista.
- **Fonte Canônica de Autonomia e Formato:** Utiliza diretamente as APIs `autonomous_production.is_profile_autonomous_mode_enabled()` e `profile_manager.get_generation_profile_context()` com fallback SQL robusto que lê `content_profiles.settings_json` e `autopilot_settings`, garantindo exibição correta dos canais autônomos e formatos procedurais (`quiz_dilemma`, `quiz_paper`).
- **Default de Saída em Pasta Temporária:** O argumento `--output` grava por padrão no diretório temporário do sistema operacional (`tempfile.gettempdir()`), evitando poluir acidentalmente o repositório Git.
- **Isolamento de Rede e Segredos:** ZERO chamadas a APIs externas, Google Flow, YouTube ou TikTok. Nenhuma credencial é acessada ou impressa.

### 4.2 Instrução de Execução pelo Operador no PC Forte

No terminal do PC Forte, o operador pode executar:

```powershell
python scripts/audit_learning_loop.py --db-path "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" --stdout
```

---

## 5. Conclusão Detalhada por Canal

### 5.1 Dose Diária de Internet (`default`)
- **Veredito Inicial (Inferência do Código):** **NÃO FUNCIONA / FALTA DADO**
- **Comprovação em Produção (PC Forte):** 188 snapshots colhidos, mas **100% excluídos por `copyright_unknown`**. 0 amostras elegíveis.
- **Diagnóstico Técnico:**
  1. A flag global `closed_feedback_loop_enabled` vem desativada por padrão no banco.
  2. Todas as 188 publicações na base foram descartadas porque nenhuma possui status `clean_manual`.

### 5.2 Dose Diária de Histórias e Mistério (`profile-historias-misterio`)
- **Veredito Inicial (Inferência do Código):** **FALTA DADO**
- **Comprovação em Produção (PC Forte):** 251 snapshots colhidos, mas **100% excluídos por `copyright_unknown`**. 0 amostras elegíveis.
- **Diagnóstico Técnico:**
  O canal possui volume histórico massivo (251 publicações avaliadas), formato narrativo tradicional (`mystery`) totalmente compatível com o clustering de temas. No entanto, o bloqueio absoluto de copyright `unknown` impede que qualquer uma das 251 publicações entre na contagem de amostras elegíveis.

### 5.3 Dose Diária de Escolhas (`profile-4d18bf9a5d94`)
- **Veredito Inicial (Inferência do Código):** **NÃO FUNCIONA**
- **Comprovação em Produção (PC Forte):** 18 snapshots colhidos, **100% excluídos por `copyright_unknown`**.
- **Diagnóstico Técnico:**
  O canal opera no formato procedural `quiz_dilemma`. Além da exclusão de copyright, a estrutura recomendada é anulada incondicionalmente em [autonomous_production.py:3152](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/autonomous_production.py#L3152) (`rec_struct = fixed_format`) e o gerador procedural de dilemas ignora o clustering.

### 5.4 Quiz_Quiz (`profile-45cee883f80a`)
- **Veredito Inicial (Inferência do Código):** **NÃO FUNCIONA**
- **Comprovação em Produção (PC Forte):** 11 snapshots colhidos, **100% excluídos por `copyright_unknown`**.
- **Diagnóstico Técnico:**
  O canal opera no formato procedural `quiz_paper`. Apresenta exatamente a mesma anulação estrutural em `autonomous_production.py:3152` e bypass de roteirização tradicional em [task.py:3025](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L3025).

### 5.5 Dose Diária de GTA VI (`profile-gta-vi`)
- **Veredito Inicial (Inferência do Código):** **FALTA DADO**
- **Comprovação em Produção (PC Forte):** 1 snapshot colhido, **100% excluído por `copyright_unknown`**.
- **Diagnóstico Técnico:**
  Canal com formato tradicional compatível com o closed loop, mas atualmente pausado e com apenas 1 publicação registrada na base histórica.
