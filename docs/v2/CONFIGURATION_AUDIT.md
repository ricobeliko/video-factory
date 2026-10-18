# Video Factory V2 — Auditoria de Configurações
**Documento de Auditoria V2.1**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Mapeamento de Configurações e Persistência

Atualmente, as configurações da fábrica estão divididas entre arquivos de configuração em disco (`config.toml`, `config.example.toml`), banco de dados SQLite (`storage/video_factory.db`) e metadados de templates JSON (`resource/quiz_templates/`).

| Domínio de Configuração | Armazenamento Atual | Leitores Principais | Escritores Principais |
| :--- | :--- | :--- | :--- |
| **Chaves de API Globais** (LLM, Pexels, ElevenLabs, Post for Me) | `config.toml` (seção `[app]`, `[llm]`, etc.) | `app/config/config.py` | Streamlit Settings Dialog / Edição manual |
| **Canais de Publicação** | SQLite: tabela `publishing_channels` | `app/services/channel_service.py` | `Channel Factory`, CLI de importação |
| **Perfis de Conteúdo (Nicho/Voz)** | SQLite: tabela `content_profiles` | `app/services/profile_service.py` | `Channel Factory`, Operator Console |
| **Destinos de Redes Sociais** | SQLite: colunas `post_for_me_channel_id`, `post_for_me_project_id`, `platform` | `app/services/post_for_me_service.py` | `Channel Factory` |
| **Metas de Estoque e Agendamento** | SQLite: colunas `stock_target`, `daily_target`, `schedule_cron` | `app/services/scheduler.py` | `Channel Factory`, Operator Console |
| **Templates de Formato (Quiz / Paper)** | JSON: `resource/quiz_templates/*.json` | `app/services/quiz_engine.py` | Engenharia / Arquivos versionados |

---

## 2. Investigação Crítica: Regras de Precedência de Voz

Na interface Streamlit atual, a voz do narrador pode ser selecionada em até 4 pontos concorrentes, gerando confusão e resultados inconsistentes:

1. **Configuração Global do Streamlit (`config.ui["voice_name"]`):** Definida na aba de áudio do `Main.py`.
2. **Configuração do Perfil do Canal (`profile.voice_name`):** Salva no banco SQLite associada ao canal.
3. **Parâmetro de Template (`template["tts_voice"]`):** Embutido no JSON de formatos estruturados (ex: Quiz).
4. **Campo Avulso na Geração Manual:** O operador pode sobrescrever o dropdown no momento do envio.

### Regra Canônica de Precedência Estabelecida para a V2:
```
1. Template Fixo (se o formato congelado exigir voz específica, ex: Quiz Paper P1.3)
   └── Se não for fixo:
       2. Voz do Canal (armazenada em publishing_channels / content_profile)
          └── Se não definida no canal:
              3. Voz Global do Sistema (config.toml / default_voice)
```
*Na V2, quando um canal está selecionado, o seletor de voz no formulário carrega automaticamente a voz do canal e sinaliza visualmente se há bloqueio ou herança.*

---

## 3. Investigação Crítica: Canais e Destinos Post for Me (Multiprojeto)

O Post for Me possui suporte a múltiplos projetos:
- Projeto Principal (`farme videos LABEL`): Contas YouTube.
- Projeto Secundário (`tiktok`): Contas TikTok e YouTube adicionais.

### Fonte Canônica:
A tabela `publishing_channels` armazena explicitamente:
- `external_account_id`: Identificador único da conta no Post for Me.
- `project_id`: Identificador do projeto ao qual a conta pertence (`main` ou `secondary`).
- `platform`: `youtube` ou `tiktok`.

O serviço `app/services/post_for_me_service.py` resolve a API Key correta consultando o `project_id` associado ao canal, eliminando o erro de "contas não encontradas" em chamadas cruzadas.
