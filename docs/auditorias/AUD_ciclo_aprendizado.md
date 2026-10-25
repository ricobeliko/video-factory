# Auditoria Canônica do Ciclo Fechado de Aprendizado (Closed Feedback Loop)

- **Documento:** `docs/auditorias/AUD_ciclo_aprendizado.md`
- **Missão:** Missão B — V2 Auditoria de Aprendizado (Somente Leitura)
- **Data:** 24 de Outubro de 2026
- **Status da Operação:** SOMENTE LEITURA (`mode=ro`). Zero escritas, zero alteração de regras de negócio, zero rede externa.

---

## Sumário Executivo

Esta auditoria técnica investigou detalhadamente o ecossistema de aprendizado de máquina adaptativo e feedback contínuo da Video Factory V1, analisando o código-fonte em DEV (`C:\Projetos\MoneyPrinterTurbo-V1`), o mecanismo do agendador (`scheduler.py` e `analytics_scheduler.py`), o motor estatístico de aprendizado (`analytics.py`) e a integração na esteira autônoma de produção (`autonomous_production.py`).

### Resumo dos Vereditos por Canal

| Canal | Formato Técnico | Veredito | Causa Raiz Técnica Primária |
| :--- | :---: | :---: | :--- |
| **Dose Diária de Internet** (`default`) | Tradicional / Variado | **NÃO FUNCIONA / FALTA DADO** | Flag global desativada; ausência do mínimo de 12 snapshots na janela 72–96h com copyright `clean_manual`. |
| **Dose Diária de Histórias e Mistério** (`profile-historias-misterio`) | Tradicional (`mystery`) | **FALTA DADO** | O código suporta integralmente o canal, mas a base histórica não possui 12 vídeos maduros na janela 72–96h com contraste estatístico. |
| **Dose Diária de Escolhas** (`profile-4d18bf9a5d94`) | `quiz_dilemma` (Procedural) | **NÃO FUNCIONA** | A esteira autônoma sobrescreve a estrutura (`rec_struct = fixed_format`) e o pipeline procedural em `task.py` ignora o clustering. |
| **Quiz_Quiz** (`profile-45cee883f80a`) | `quiz_paper` (Procedural) | **NÃO FUNCIONA** | Mesma sobrescrita incondicional da estrutura recomendada e bypass de roteirização tradicional. |
| **Dose Diária de GTA VI** (`profile-gta-vi`) | Tradicional | **FALTA DADO** | Canal em pausa operacional, sem volume de publicações com snapshots elegíveis na janela de 72–96h. |

---

## 1. Quais Perfis e Formatos Entram de Fato no Closed Loop?

### 1.1 Análise de Código em `autonomous_production.py`

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

**Conclusão do Item 1:** Para canais tradicionais (`mystery`, `explainer`, `default`), o closed loop consegue injetar `rec_struct` e `topic_cluster`. Para `quiz_dilemma` e `quiz_paper`, o closed loop é um **no-op operacional**: consome tempo de banco de dados, mas não afeta em nada a geração.

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
- A tabela `content_analytics` **não existe** (zero snapshots de métricas).
- A tabela `autopilot_settings` não possui histórico de execuções de analytics (`analytics_last_cycle_at = NULL`).
- As publicações existentes são mockups e testes locais, sem vinculação com canais ativos do YouTube.

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

---

## 4. Script de Auditoria Somente Leitura (`scripts/audit_learning_loop.py`)

Para que o operador possa auditar o banco de produção do PC Forte sem qualquer risco de contaminação, escrita ou vazamento de credenciais, foi criado o script canônico:

[scripts/audit_learning_loop.py](file:///c:/Projetos/MoneyPrinterTurbo-V1/scripts/audit_learning_loop.py)

### 4.1 Características de Segurança

- **Modo Estritamente Somente Leitura:** Abre a conexão com SQLite via URI `file:<path>?mode=ro`. Qualquer tentativa acidental de escrita resulta em `sqlite3.OperationalError: attempt to write a readonly database`.
- **Integridade Criptográfica (SHA-256):** O script calcula o hash SHA-256 do arquivo `.db` antes da execução e após o término da inspeção. Se o hash divergir, aborta com código de erro fatal.
- **Isolamento de Rede:** ZERO chamadas a APIs externas, Google Flow, YouTube ou TikTok.
- **Sanitização de Segredos:** Nenhuma chave de API, segredo ou token do `config.toml` é lido, exibido ou gravado no relatório.
- **Geração de Relatório:** Grava automaticamente o relatório estruturado em `docs/auditorias/AUDIT_LEARNING_LOOP_REPORT.md` e opcionalmente imprime no terminal com `--stdout`.

### 4.2 Instrução de Execução pelo Operador no PC Forte

No terminal do PC Forte, o operador pode executar:

```powershell
python scripts/audit_learning_loop.py --db-path "C:\Projetos\MoneyPrinterTurbo\storage\video_factory.db" --stdout
```

---

## 5. Conclusão Detalhada por Canal

### 5.1 Dose Diária de Internet (`default`)
- **Veredito:** **NÃO FUNCIONA / FALTA DADO**
- **Diagnóstico Técnico:**
  1. A flag global `closed_feedback_loop_enabled` vem desativada por padrão no banco.
  2. O canal ainda não acumulou o mínimo de 12 publicações com snapshots colhidos estritamente na janela de 72–96 horas com status de copyright marcado como `clean_manual`.
- **Menor Correção Possível (sem implementar):**
  Ativar a flag `closed_feedback_loop_enabled = true` em `autopilot_settings`, garantir que o `YouTubeAnalyticsProvider` realize snapshots regulares aos 3 dias pós-publicação e auditar manualmente o status de copyright dos vídeos elegíveis via WebUI.

### 5.2 Dose Diária de Histórias e Mistério (`profile-historias-misterio`)
- **Veredito:** **FALTA DADO**
- **Diagnóstico Técnico:**
  O canal utiliza formato tradicional narrativo (`mystery` / `explainer`), sendo plenamente compatível com o clustering de temas e adaptação de estruturas em `autonomous_production.py`. No entanto, o volume de vídeos publicados ainda não atingiu a massa crítica de 12 amostras na janela de 72–96h. O motor reporta corretamente `INSUFFICIENT_DATA`.
- **Menor Correção Possível (sem implementar):**
  Nenhuma alteração de código é necessária. Aguardar a produção e publicação continuada até atingir 12 vídeos na janela alvo de métricas com copyright aprovado.

### 5.3 Dose Diária de Escolhas (`profile-4d18bf9a5d94`)
- **Veredito:** **NÃO FUNCIONA**
- **Diagnóstico Técnico:**
  O canal opera no formato `quiz_dilemma`.
  1. A estrutura recomendada pelo closed loop é anulada na linha 3152 de `autonomous_production.py`, que força `rec_struct = fixed_format`.
  2. O pipeline procedural em [task.py:2844](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L2844) (`_run_quiz_pipeline`) gera dilemas através de um gerador procedural específico, ignorando tópicos do Trend Radar e estruturas narrativas do closed loop.
- **Menor Correção Possível (sem implementar):**
  Desativar expressamente a consulta de closed loop para perfis procedurais em `autonomous_production.py`, ou criar uma dimensão de aprendizado específica para quizzes (ex: categorias de dilemas, retenção por tempo de transição de tela) ao invés de tentar encaixar a estrutura de 3 atos tradicional.

### 5.4 Quiz_Quiz (`profile-45cee883f80a`)
- **Veredito:** **NÃO FUNCIONA**
- **Diagnóstico Técnico:**
  O canal opera no formato `quiz_paper`. Apresenta exatamente a mesma causa raiz do Quiz de Escolhas: sobrescrita incondicional da estrutura na linha 3152 de `autonomous_production.py` e bypass de roteirização tradicional em [task.py:3025](file:///c:/Projetos/MoneyPrinterTurbo-V1/app/services/task.py#L3025) (`_run_quiz_paper_pipeline`).
- **Menor Correção Possível (sem implementar):**
  Isolar o canal da lógica de narrativa tradicional no closed loop. O canal depende exclusivamente do gerador procedural de perguntas de papel e de assets gráficos locais.

### 5.5 Dose Diária de GTA VI (`profile-gta-vi`)
- **Veredito:** **FALTA DADO**
- **Diagnóstico Técnico:**
  Canal com formato tradicional compatível com o closed loop, mas atualmente em pausa operacional (`autonomous_mode_enabled = False` e poucas publicações históricas). Não possui amostras na janela 72–96h.
- **Menor Correção Possível (sem implementar):**
  Retomar a produção quando conveniente e aguardar o ciclo de maturação de 12 vídeos para avaliação estatística.
