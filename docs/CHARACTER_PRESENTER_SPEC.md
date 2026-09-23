# Especificação de Personagem / Virtual Presenter (Fase V14-C.1)

## Canal Alvo
- **Nome:** Dose Diária de Histórias e Mistério
- **Identificador de Perfil:** `profile-historias-misterio`
- **Nicho:** Histórias, mistérios, investigações históricas, fatos insólitos.
- **Público:** Jovens e adultos interessados em suspense, curiosidades e teorias instigantes.

---

## 1. Identidade e Conceito do Personagem

- **Nome Oficial:** **Nox** (Detetive Nox / Investigador do Desconhecido)
- **Character ID:** `nox_v1` (compatível com `misterio_host_v1`)
- **Single Character All Channels:** **SIM** (Nox é o personagem-base unificado da fábrica para todos os canais; variações futuras apenas de estilo, skin, roupa ou tom narrativo)
- **Papel Narrativo:** O anfitrião curioso e compenetrado que investiga os mistérios junto com o espectador, sem ser assustador. Amigável, intrigante e expressivo.
- **Estilo Visual:** **Cartoon / Semi-Cartoon 2D** (linhas vetoriais nítidas, estilo animação moderna com sombreamento cel shading ou leve gradiente; NÃO foto-realista).

---

## 2. Direção de Arte e Atributos Físicos Canônicos (Fase V14-C.3)

| Elemento | Descrição |
| :--- | :--- |
| **Idade Aparente** | Jovem adulto (faixa aparente 20–30 anos). |
| **Expressão Base** | Olhar penetrante e atento, sobrancelhas expressivas, curioso, amigável e levemente misterioso. |
| **Rosto e Corpo** | Rosto fino, visual moderno, corpo magro. |
| **Pele** | Morena clara. |
| **Cabelo** | Preto escuro, corte bagunçado com leves reflexos roxos sutis. |
| **Olhos** | Castanhos escuros expressivos. |
| **Vestimenta Oficial**| Jaqueta/moletom preto sobre camiseta preta, com detalhes discretos em tom roxo escuro; sem logotipos ou elementos datados. |
| **Paleta Canônica** | - **Preto Base:** `#111115`<br>- **Roxo Escuro:** `#2B143E`<br>- **Lilás / Acento:** `#6B3FA0`<br>- **Azul Petróleo:** `#183040` |
| **Enquadramento** | *Busto / Cintura para cima* (waist-up), braços visíveis para gesticulação, reações e apontamentos. |
| **Proporção** | Otimizado para vídeos verticais 9:16 (resolução nativa 1080x1920) com margem segura de 4% lateral e 6% inferior. Source canônico em 1024x1024 ou proporcional. |

---

## 3. Contrato do Asset Pack Local

O character pack deve residir em um dos diretórios padrão:
`resource/presenter_assets/<character_id>/` ou `storage/presenter_assets/<character_id>/`.

### Arquivos Obrigatórios e Poses Padrão:

| Arquivo | Nome da Pose | Função na Timeline |
| :--- | :--- | :--- |
| `neutral.png` | `neutral` | Pose neutra / relaxada / observadora (usada como fallback seguro e início em corner mode). |
| `talking_1.png` | `talking_1` | Fala moderada: boca entreaberta, mão levantada discretamente em tom de narração. |
| `talking_2.png` | `talking_2` | Fala enfática: boca aberta, expressão animada ou de revelação. |
| `surprised.png` | `surprised` | Reação a plot-twists, revelações ou fatos inacreditáveis (olhos arregalados). |
| `serious.png` | `serious` | Tom solene, suspense profundo ou momentos dramáticos da narrativa. |
| `thinking.png` | `thinking` | Mão no queixo, sobrancelha franzida, levantando dúvida no espectador. |
| `pointing_left.png` | `pointing_left` | Gesto apontando para o centro/esquerda da tela (direcionando o foco para as legendas). |
| `pointing_right.png` | `pointing_right` | Gesto apontando para o lado direito. |
| `cta.png` | `cta` | Chamada para ação final (apontando para botão de inscrição, like ou comentários). |
| `config.json` | *metadados* | Configuração de escala padrão, posição e catálogo de poses. |

---

## 4. Estrutura do `config.json`

```json
{
  "character_id": "nox_v1",
  "name": "Nox",
  "style": "cartoon",
  "version": "1.0.0",
  "default_pose": "neutral",
  "default_scale": 0.38,
  "default_position": "bottom_right",
  "default_opacity": 1.0,
  "poses": {
    "neutral": "neutral.png",
    "talking_1": "talking_1.png",
    "talking_2": "talking_2.png",
    "surprised": "surprised.png",
    "serious": "serious.png",
    "thinking": "thinking.png",
    "pointing_left": "pointing_left.png",
    "pointing_right": "pointing_right.png",
    "cta": "cta.png"
  }
}
```

---

## 5. Especificações Técnicas de Exportação

1. **Formato:** PNG com canal alfa (RGBA de 32 bits, transparência limpa sem halos ou bordas brancas).
2. **Resolução de cada pose:** Mínimo 600x900px, recomendado 800x1200px (proporção aproximada 2:3).
3. **Ponto de ancoragem:** Base inferior alinhada horizontalmente entre todas as poses, permitindo alternância fluida entre falas sem "pulos" de altura.
4. **Sem fundo:** Fundo 100% transparente em todos os frames.

---

## 6. Controlador Expressivo e Interação com Legendas (Fase V14-C.2)

### 6.1. Pipeline Temporal de Expressões
O controlador `build_presenter_expression_timeline` sincroniza as expressões do Nox com o áudio narrado e as legendas (SRT), garantindo:
1. **Alternância de fala determinística:** Enquanto o narrador fala em trecho neutro, alterna `talking_1` e `talking_2` a cada ~0.35s, dando dinamismo visual sem requerer lip-sync neural.
2. **Reações de significado (Keywords):**
   - **SURPRISE:** Palavras de impacto/choque (`inacreditável`, `assustador`, `chocante`, etc.) ativam pose `surprised`.
   - **THINKING:** Dúvidas/hipóteses (`teoria`, `hipótese`, `ninguém sabe`, etc.) ativam pose `thinking`.
   - **SERIOUS:** Temas graves/solenes (`morte`, `morreu`, `tragédia`, `crime`, etc.) ativam pose `serious`.
   - **CTA:** Chamadas para ação (`inscreva-se`, `comenta`, `compartilhe`, etc.) ativam gestos de CTA e apontamento.
3. **Prioridade Estrita:** `CTA > SERIOUS > SURPRISE > THINKING > TALKING > NEUTRAL`.
4. **Interação Geométrica de Apontamento:**
   - Se `avatar_position = bottom_right`, Nox aponta para a esquerda (`pointing_left`), direcionando o olhar do espectador para a legenda centralizada.
   - Se `avatar_position = bottom_left`, Nox aponta para a direita (`pointing_right`).
5. **Ajuste de Tom por Canal:**
   - Canal Padrão / Geral: Mais expressivo, alternância rápida e reação `surprised`.
   - `profile-historias-misterio`: Reações mais contidas e sóbrias (palavras de surpresa mapeiam para `serious`/`thinking` com motivo `mystery_contained_reaction`).
6. **Robustez e Fail-Safe:** Se o SRT estiver corrompido ou ausente, o pipeline recorre suavemente aos segmentos estruturais (hook, return, cta) sem interromper a renderização.

---

## 7. Fundação do Asset Pack Canônico (Fase V14-C.3)

### 7.1. Estrutura Canônica de Diretórios
```
assets/presenter/nox_v1/
├── manifest.json
├── reference/
│   └── nox_v1_reference.png   (Âncora visual fornecida pelo operador)
├── poses/
│   ├── neutral.png            (Core)
│   ├── talking_1.png          (Core)
│   ├── talking_2.png          (Core)
│   ├── surprised.png          (Core)
│   ├── serious.png            (Core)
│   ├── thinking.png           (Core)
│   ├── pointing_left.png      (Core)
│   ├── pointing_right.png     (Core)
│   └── cta.png                (Core)
└── previews/
    └── nox_contact_sheet.png  (Contact sheet gerada localmente)
```

### 7.2. Core Poses (Obrigatórias) e Extended Motion Pack (Opcionais)
- **Core Poses (9):** `neutral`, `talking_1`, `talking_2`, `surprised`, `serious`, `thinking`, `pointing_left`, `pointing_right`, `cta`.
- **Extended Motion Pack (13):** `blink`, `talking_3`, `talking_4`, `half_smile`, `confused`, `skeptical`, `looking_left`, `looking_right`, `hand_up`, `open_hands`, `lean_forward`, `warning`, `excited`.

### 7.3. Fallback Graph Determinístico
Quando uma pose estendida for solicitada na timeline mas não estiver presente no pack físico, o pipeline recorre deterministicamente através da cadeia:
- `talking_4` → `talking_2` → `talking_1` → `neutral`
- `talking_3` → `talking_1` → `talking_2` → `neutral`
- `blink` → `neutral`
- `confused` → `thinking` → `neutral`
- `skeptical` → `thinking` → `neutral`
- `looking_left` / `looking_right` → `neutral`
- `hand_up` / `open_hands` → `talking_1` → `neutral`
- `lean_forward` → `neutral`
- `warning` → `serious` → `neutral`
- `excited` → `surprised` → `neutral`
- `half_smile` → `neutral`

### 7.4. Validação de Consistência e Preview
- `validate_character_pack_assets`: Executa validação de formato (PNG), canal alfa real (RGBA com transparência) e uniformidade rigorosa de dimensões de tela entre todas as poses do pack.
- `generate_contact_sheet`: Produz contact sheet visual em grid organizada (Core Poses 3x3 no topo + Extended Poses abaixo) para validação rápida pelo operador humano antes de aprovação de assets.
