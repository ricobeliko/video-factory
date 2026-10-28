# Regras comuns das missões V2

Toda missão V2 segue estas regras. O prompt de cada missão diz apenas "leia este arquivo" e traz a tarefa específica.

## Ambiente e branches
- Trabalhe SOMENTE no DEV. Nunca execute nada no PC Forte (PROD).
- Branch base: v2/base. Cada missão cria sua branch v2/<nome-da-missão> a partir de v2/base.
- NUNCA faça commit, merge ou push na main. A main é a V1 em produção.
- NUNCA apague branches. Não faça force push.
- Só se integra uma branch na v2/base em missão de sincronismo pedida explicitamente, com merge --no-ff. Se houver QUALQUER conflito, pare, não resolva sozinho e reporte os arquivos.
- Mensagens de commit começam com "v2:" e são em português.
- Publicação: git push origin <branch>.

## Escopo
- Mudanças ADITIVAS. Não altere código da V1 que já funciona (webui/, scripts de produção atuais, regras de negócio) a menos que a missão peça isso explicitamente e nomeie os arquivos.
- FAZER MENOS: entregue só o que a missão pede. Nada de refatoração oportunista.
- Um agente modifica o repositório por vez.
- Nenhum deploy, nenhuma alteração na Scheduled Task do Windows e nenhuma ativação de flag em banco de produção sem autorização expressa do Rico.

## Segurança
- Nunca leia, imprima, copie ou grave segredos (tokens, chaves, client_secret, credenciais). Não inclua nada disso em commits, relatórios ou logs.
- Operações de auditoria são somente leitura. Para auditar banco, trabalhe numa cópia (sqlite3 backup), nunca no arquivo ao vivo.

## Princípio de fonte única (obrigatório para missões de tela ou API)
- **"Um controle = um lugar. Uma informação = uma fonte."**
- Nenhum controle pode existir em duas telas ou endpoints concorrentes (ex.: trocar a voz, dar play/pausa na fábrica, alterar cotas ou modo autônomo).
- Nenhuma informação pode ser calculada em dois lugares diferentes (ex.: estoque pronto, estado da fábrica, limites diários, status do canal).
- Outras telas só **mostram** o valor (somente leitura) e levam até o único lugar onde se edita.
- **Obrigatório antes de entregar toda missão que mexa em tela ou em API:** o relatório final deve informar explicitamente:
  1. Quais controles/informações a missão criou ou tocou;
  2. Em que único lugar cada um vive (onde é editado e onde é calculado/fonte);
  3. Se a missão criou alguma duplicidade (não pode).

## TEST POLICY
- No máximo 1 comando de teste direcionado, o que a missão indicar. Se passou, pare. Não rode a suíte inteira.
- Missão só de documentação: sem testes.

## Relatório final (sempre estas 5 partes, curto)
1. Branch e SHA do commit (copie o SHA de git rev-parse; nunca digite de memória).
2. Arquivos alterados ou criados.
3. Comando de teste executado e resultado.
4. O que ficou de fora de propósito.
5. Riscos ou dúvidas que precisam de decisão do Rico.
