# WhatsApp transacional do DACOT-HUB

O Hub entrega links de primeiro acesso e recuperação pelo serviço privado
`whatsapp-service`. O Hub envia apenas destino, finalidade e link temporário; o
serviço valida origem, token e assinatura e monta a mensagem final.

## Configuração do Hub

- `WHATSAPP_SERVICE_URL`: origem privada/HTTPS do `whatsapp-service`.
- `WHATSAPP_SERVICE_SECRET`: chave aleatória com pelo menos 32 caracteres, igual
  no Hub e no serviço.
- `WHATSAPP_SERVICE_TRANSPORT`: `https` por padrão; use
  `speedtrail-private-http` apenas para a origem privada fixa
  `http://dacot-whatsapp:3002`.
- `WHATSAPP_SERVICE_CA_FILE`: opcional, certificado CA privado para HTTPS.
- `WHATSAPP_PAIRING_SERVICE_SECRET`: chave separada, diferente da chave de
  envio, usada somente para códigos temporários de pareamento.
- `WHATSAPP_PAIRING_SELF_SERVICE_ENABLED`: habilita o pareamento protegido no
  Hub somente quando configurado como `true` nos dois serviços. O padrão é
  desativado.
- `WHATSAPP_ACCOUNT_SWITCH_SERVICE_SECRET`: segredo separado, com pelo menos
  32 caracteres, igual no Hub e no gateway. Habilita a troca assistida e
  autenticada de conta; sem ele, o envio e a sessão ativa continuam funcionando,
  mas a troca fica indisponível.

## Configuração do whatsapp-service

- `WHATSAPP_SERVICE_SECRET`: chave da integração Hub, com pelo menos 32
  caracteres.
- `WHATSAPP_ADMIN_SECRET`: segredo distinto para o listener administrativo
  restrito a loopback.
- `WHATSAPP_PAIRING_SERVICE_SECRET`: segredo distinto para pareamento.
- `WHATSAPP_ACCOUNT_SWITCH_SERVICE_SECRET`: segredo distinto para a API de
  troca de conta, nunca reutilizado para envio, pareamento ou administração.
- `WHATSAPP_FRONTEND_ORIGIN`: origem HTTPS exata do frontend Hub, usada para
  validar os links.
- `WHATSAPP_STORAGE_KEY`: chave base64 que decodifica para 32 bytes; protege as
  credenciais persistidas.
- `WHATSAPP_DB_PATH`: caminho do SQLite persistente (padrão
  `/var/data/whatsapp.sqlite`).
- `WHATSAPP_TRANSPORT`: `https` ou `proxy-http` quando TLS termina em proxy
  confiável.
- `WHATSAPP_ENABLED`: `true` para iniciar a sessão, `false` para manutenção.
- `WHATSAPP_PAIRING_SELF_SERVICE_ENABLED`: opt-in do código de pareamento.
- `WHATSAPP_TLS_KEY_FILE` e `WHATSAPP_TLS_CERT_FILE`: necessários quando o
  serviço termina TLS diretamente.
- `WHATSAPP_ADMIN_PORT`: listener administrativo loopback (padrão `3003`).

O serviço exige Node.js `>=22.13.0 <23` (ver `whatsapp-service/package.json`).
Quando a plataforma termina TLS na borda, use `WHATSAPP_TRANSPORT=proxy-http`
somente se a origem HTTP da aplicação ficar privada e inacessível diretamente
pela Internet. Caso contrário, use TLS no próprio serviço e configure
`WHATSAPP_TLS_KEY_FILE` e `WHATSAPP_TLS_CERT_FILE`.

O serviço retorna `accepted` quando Baileys aceita a chamada de envio. Isso não
confirma entrega ao destinatário; o Hub nunca apresenta esse estado como
entregue. O gateway guarda apenas hashes/HMAC das chaves de idempotência e
destinatários, e as credenciais de sessão ficam cifradas no volume persistente.

O serviço tenta reconectar com backoff crescente e para após oito tentativas; o
status passa a `error` para intervenção. Eventos atrasados de sockets antigos
são ignorados. Um lease SQLite com heartbeat impede dois processos de usar a
mesma sessão ao mesmo tempo; após encerramento abrupto, ele expira em até 60
segundos. Nenhuma falha apaga as credenciais automaticamente. `logged_out`
exige um reset explícito de pareamento pelo operador.

## Primeiro pareamento e reconexão

Com `WHATSAPP_ENABLED=true`, a conexão nova disponibiliza um QR enquanto o
status estiver `pairing`. O utilitário `node pair.mjs` busca o QR pelo listener
loopback e o imprime no terminal; execute-o em uma sessão administrativa privada
ou por túnel. Configure `WHATSAPP_SERVICE_URL` temporariamente como
`http://127.0.0.1:3003` para o utilitário e use o `WHATSAPP_ADMIN_SECRET` já
presente no ambiente do serviço. Leia o QR pelo fluxo “Aparelhos conectados” do
WhatsApp. O Hub também pode solicitar um código temporário, com reautenticação
de super_admin e limites, enquanto a conexão está aguardando pareamento.

Se o WhatsApp tiver encerrado a sessão (`logged_out`), execute `node pair.mjs
--reset` pelo mesmo canal privado e depois execute `node pair.mjs` para mostrar o
QR novo. Esse comando não deve ser usado em estado conectado.

## Operação e recuperação

- `GET /health` confirma apenas que o processo HTTP está respondendo. Para o
  estado WhatsApp, consulte a página de integração do Hub como `super_admin`;
  ela mostra `Conectado`, `Aguardando pareamento`, `Reconectando`,
  `Desconectado`, `Sessão encerrada` ou `Erro de conexão`.
- O estado `error` ocorre após oito tentativas de reconexão. Verifique logs e
  armazenamento no painel da hospedagem e reinicie o serviço uma vez após
  corrigir a causa. O reinício reaproveita as credenciais; não execute reset.
- Use `node pair.mjs --reset` apenas quando o estado for `logged_out`. Isso
  invalida a sessão anterior e inicia o pareamento explícito; em seguida use
  `node pair.mjs` para ler o QR. Nunca faça reset para corrigir erro de rede,
  indisponibilidade ou falha temporária de armazenamento.
- A cópia de segurança da sessão exige o arquivo SQLite e a mesma
  `WHATSAPP_STORAGE_KEY`. Pare o serviço de forma limpa antes de copiar o banco;
  guarde a chave separadamente em um gerenciador de segredos. Sem essa chave,
  as credenciais cifradas não podem ser recuperadas. Não coloque banco ou chave
  no Git, em logs ou em artefatos públicos.
- Rollback do Hub: reverta apenas o release do Hub no painel para o último
  release validado. Mantenha o `whatsapp-service`, seu banco e suas chaves
  intactos. As rotas de entrega e a assinatura HMAC devem permanecer compatíveis.

## SpeedTrail

O site público da SpeedTrail anuncia deploy de aplicações Node.js, variáveis de
ambiente protegidas e serviços gerenciados. Isso, por si só, não confirma os
recursos habilitados na conta DACOT. Antes de publicar, confirme no painel ou
com o suporte:

1. Uma aplicação/serviço Node independente do backend Hub, iniciada com
   `npm start`, runtime Node `22.13` até `<23` e política de reinício após falha.
2. Que o processo permanece ativo sem tráfego recebido e que a instância tem
   memória/CPU suficientes para Baileys. O pareamento e a conexão usam WebSocket
   de saída persistente.
3. Armazenamento persistente montável em `/var/data`, preservado após reinício,
   novo deploy e troca da instância. O caminho guarda `whatsapp.sqlite`; um disco
   local efêmero perde a sessão.
4. Rede privada entre Hub e serviço, com DNS interno `dacot-whatsapp` e porta
   `3002`, caso queira usar `WHATSAPP_SERVICE_TRANSPORT=speedtrail-private-http`.
   Esse modo aceita somente `http://dacot-whatsapp:3002`. Se não houver essa
   rede, use HTTPS com certificado válido; não exponha HTTP simples.
5. Que a porta `3003` de administração permanece somente em loopback. QR e
   reset não podem ficar públicos; confirme também se há terminal/SSH seguro
   para o utilitário `pair.mjs`, ou use o pareamento assistido do Hub, que vem
   desativado e exige habilitação explícita nos dois serviços.
6. Limites de memória, CPU, conexões de saída/WebSocket, armazenamento e
   retenção de logs, além do comportamento do serviço durante deploys.

Se os itens 1 a 5 estiverem disponíveis, o serviço pode ser hospedado na mesma
conta sem outro fornecedor. O código não consegue confirmar o plano ou os
recursos da instância existente; sem armazenamento persistente e processo
contínuo, não é seguro operar a sessão Baileys nessa hospedagem.
