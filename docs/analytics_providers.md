# Provedores Oficiais de Analytics (Fases V10-A & V10-B)

Este documento descreve a arquitetura, autenticação, métricas suportadas e fluxos operacionais para coleta manual e controlada de estatísticas reais do YouTube e TikTok no MoneyPrinterTurbo.

---

## 🔒 Princípios de Segurança e Boas Práticas

1. **Nunca versionar credenciais:** Chaves de API e tokens de acesso JAMAIS devem ser adicionados ao git, arquivos de configuração compartilhados ou commits.
2. **Zero segredos em logs e banco:** Nenhuma chave (`API Key`), token de autenticação (`Bearer Token`) ou cabeçalho HTTP é persistido no SQLite, exposto em logs ou gravado em `metadata_json`.
3. **Coleta Controlada e Manual:** Não existe polling agressivo, daemons ou coleta em massa. Cada requisição é disparada manualmente para uma publicação por vez.
4. **Isolamento de Erros:** Falhas em chamadas de analytics **nunca** alteram o estado da tarefa de vídeo nem invalidam eventos de publicação.

---

## 1. YouTube Analytics Provider

### Autenticação Suportada
- **Método Oficial:** YouTube Data API v3 (API Key pública).
- **Origem da Configuração:**
  - Variável de ambiente: `YOUTUBE_API_KEY`
  - Ou no arquivo `config.toml`:
    ```toml
    [app]
    youtube_api_key = "AIzaSy..."
    ```

### Endpoints Utilizados
- `GET https://www.googleapis.com/youtube/v3/videos?part=statistics,contentDetails,snippet&id={VIDEO_ID}&key={API_KEY}`

### Métricas Disponíveis (Métricas Públicas)
- `views` (`viewCount`)
- `likes` (`likeCount`)
- `comments` (`commentCount`)
- `favorites` (`favoriteCount`)

### Métricas NÃO Disponíveis (Permanecem `None`)
- `watch_time_seconds`
- `average_view_duration_seconds`
- `average_view_percentage`
- `retention_rate`
- `subscribers_gained`

> [!NOTE]
> Métricas de retenção e tempo de exibição exigem a **YouTube Analytics Reporting API** com fluxo de autorização OAuth 2.0 do proprietário do canal (escopo `https://www.googleapis.com/auth/yt-analytics.readonly`).

### Como Testar Manualmente
1. Defina a variável `YOUTUBE_API_KEY="sua_chave"` no ambiente.
2. Certifique-se de ter ao menos uma tarefa com publicação registrada no banco.
3. No Operator Console (WebUI) -> Seção *Saúde dos Provedores* -> *YouTube Analytics*:
   - Clique em **🔍 Testar Configuração** para validar estaticamente sem gastar cota.
   - Use o popover **📥 Coleta Manual (YOUTUBE)**, informe a `Task ID`, selecione se deseja persistir e clique em **Confirmar e Buscar Métricas**.

---

## 2. TikTok Analytics Provider

### Autenticação Suportada
- **Método Oficial:** TikTok for Developers API v2 (Bearer Access Token).
- **Origem da Configuração:**
  - Variável de ambiente: `TIKTOK_ACCESS_TOKEN`
  - Ou no arquivo `config.toml`:
    ```toml
    [app]
    tiktok_access_token = "act.example..."
    ```

### Endpoints Utilizados
- `POST https://open.tiktokapis.com/v2/video/query/?fields=id,title,view_count,like_count,comment_count,share_count`
- Headers: `Authorization: Bearer {TIKTOK_ACCESS_TOKEN}`, `Content-Type: application/json`
- Body: `{"filters": {"video_ids": ["{VIDEO_ID}"]}}`

### Métricas Disponíveis
- `views` (`view_count`)
- `likes` (`like_count`)
- `comments` (`comment_count`)
- `shares` (`share_count`)

### Métricas NÃO Disponíveis (Permanecem `None`)
- `watch_time_seconds`
- `average_view_duration_seconds`
- `average_view_percentage`
- `retention_rate`
- `favorites`

---

## 3. Modos de Coleta

### Modo Dry Run (`dry_run=True`)
- Não executa nenhuma requisição HTTP externa.
- Retorna estrutura normalizada com contadores zerados e `raw_metadata: {"dry_run": True}`.
- Usado para testes e pipelines onde chamadas de rede não devem ocorrer.

### Modo Fetch Sem Persistência (`persist=False`)
- Executa a requisição real no endpoint oficial.
- Normaliza os dados retornados.
- Retorna o dicionário de métricas sem gravar snapshot no SQLite (`content_analytics`).
- Pode ser executado tanto em nós `PRIMARY` quanto em nós `SECONDARY_VIEW_ONLY`.

### Modo Fetch Com Persistência (`persist=True`)
- Requer papel `PRIMARY` da fábrica (Single-Instance Safety).
- Executa a requisição real, normaliza os dados e grava o snapshot via `analytics.save_snapshot(...)`.
- Preserva estritamente o `profile_id` e `channel_id` originais da publicação histórica.
