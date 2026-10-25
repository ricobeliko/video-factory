# Protótipo "Central de Frota" (referência visual da V2)

Isto é a referência de identidade visual da tela principal da V2. É um protótipo com DADOS DE EXEMPLO e animação SIMULADA: serve para copiar o visual, o layout e a hierarquia, nunca os dados nem a simulação.

## Arquivos
- `Central_de_Frota.dc.html`: o protótipo completo (HTML + CSS inline + lógica). NÃO é React; é um formato de protótipo (tags `<sc-for>`, `<sc-if>`, buracos `{{assim}}`, classe com `tick()`). Leia como referência: cores, tipografia, espaçamentos, estrutura das seções e textos em português estão todos nele.
- `sprites/`: imagens dos robôs (PNG com transparência).

## Identidade visual (valores extraídos do protótipo)
- Tema escuro. Fundo da página `#0A0C11`, barra superior `#0D1016`, cartões `#10131A` com borda `#1B2029` e raio 14px, texto `#E8EBF1`, texto secundário `#9099AA`, foco `#8B9DFF`.
- Fontes: Inter (texto) e JetBrains Mono (números e rótulos técnicos, com `tabular-nums`).
- Seções da tela, na ordem: barra superior (logo, abas Frota/Produção/Publicação/Revisão/Sistema, busca, estado do sistema) → título "Frota" → 6 indicadores → "Fábrica ao vivo" (oficina) → "Precisa de você" + "Mapa da frota" → tabela "Todos os canais" com filtros → gaveta de detalhe do canal.

## Sprites
- Robôs das 6 estações: `roteiro.png`, `gates.png` (verificação de qualidade), `narracao.png`, `cenas.png`, `render.png`, `publicar.png`. Cada folha tem 1152x267 px com 4 poses lado a lado, cada célula 288x267: ordem idle, working, happy, error. No protótipo cada célula aparece a 144x134 px (metade do tamanho; `background-size: 576px 134px`, troca de pose por `background-position`).
- `courier.png`: 912x132 px, 6 quadros de 152x132: quadros 0 a 3 = andando, 4 = parado, 5 = feliz. No protótipo aparece a 76x66 px (folha a 456px de largura).
- `desk.png`: 382x356 px, mesa decorativa (perspectiva isométrica; os robôs são de frente).
- Na animação de andar, usar `steps()` no CSS.

## Regras
- Dados reais: nunca usar os 24 canais de exemplo nem a simulação de rejeições do protótipo. Tudo vem da API.
- Os personagens são originais, criados para este projeto. Não substitua por personagens de terceiros.
