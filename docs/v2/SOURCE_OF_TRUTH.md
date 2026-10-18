# Video Factory V2 — Fonte Única de Verdade (Single Source of Truth)
**Documento de Arquitetura V2.2**
**Data de Criação:** 2026-10-18
**Ambiente:** Isolado (V2 Worktree: `feat/video-factory-v2`)

---

## 1. Princípio de Fonte Canônica

Na Video Factory V2, cada parâmetro de configuração possui **uma única origem canônica autoritativa**. Nenhuma interface web ou script deve armazenar cópias concorrentes ou divergentes.

| Parâmetro | Fonte Canônica | Módulo Python Autorizado a Alterar | Formato de Armazenamento |
| :--- | :--- | :--- | :--- |
| **Definição de Canal** | SQLite: `publishing_channels` / `content_profiles` | `app/services/profile_manager.py` | Colunas relacionais e JSON serializado |
| **Voz do Narrador** | `profile_settings.voice` (com fallback para template e global) | `app/services/profile_manager.py` | String identificadora (ex: `pt-BR-AntonioNeural`) |
| **Destinos de Publicação** | `publishing_channels` (com `project_id` Post for Me) | `app/services/profile_manager.py` | Linhas na tabela de canais associados |
| **Metas de Estoque** | `profile_settings.quotas.target_ready_stock` | `app/services/profile_manager.py` | Inteiro (1 a 10) |
| **Janela de Publicação** | `profile_settings.schedule` | `app/services/profile_manager.py` | Objeto com horas início/fim e timezone |
| **Estado de Autonomia** | `profile_settings.autonomous_enabled` | `app/services/autonomous_production.py` | Booleano |
| **Regras de Template Quiz** | `resource/quiz_templates/*.json` | Versionado em Git (somente leitura pelo app) | Arquivos JSON congelados |
| **Credenciais de Provedores** | `config.toml` (seção correspondente) | Leitura exclusiva via `app/config/config.py` | Arquivo TOML |

---

## 2. Regra de Resolução Hierárquica

Quando o sistema precisa de uma configuração durante a renderização de um vídeo, a resolução segue estritamente a seguinte ordem:

```
1. Propriedade Congelada de Template
   (Ex: Quiz Paper P1.3 impõe duração de 60s, timer circular e fontes rígidas)
   │
   ▼ (Se não for imposto pelo template)
2. Configuração Específica do Canal
   (Ex: voz configurada no perfil do canal "Dose Diária de Escolhas")
   │
   ▼ (Se não configurado no canal)
3. Configuração Padrão do Sistema
   (Ex: default_voice em config.toml)
```

Nenhum formulário frontend pode inventar valores padrão divergentes desses três níveis canônicos.
