# SMS transacional no DACOT-HUB

O Hub envia links temporários de primeiro acesso e recuperação por SMS usando
Twilio Programmable Messaging via HTTPS e `httpx`; não há SDK adicional, gateway
próprio, sessão de mensageria ou callback de status nesta implementação.

## Configuração do serviço backend

- `SMS_PROVIDER=twilio`
- `TWILIO_ACCOUNT_SID`: Account SID Twilio.
- `TWILIO_AUTH_TOKEN`: segredo de autenticação Twilio.
- Configure exatamente uma opção de remetente:
  - `SMS_FROM`: remetente E.164 autorizado pela conta; ou
  - `TWILIO_MESSAGING_SERVICE_SID`: SID de Messaging Service.

As credenciais ficam somente no backend. O provedor recebe um destino brasileiro
normalizado como celular brasileiro E.164, o texto curto e a URL de reset. Respostas HTTP 201 com SID
de mensagem válido resultam no estado correspondente: `accepted` para
`accepted`/`queued`/`sending`, `sent` para `sent`, `delivered` para `delivered`,
`failed` para `failed` e `undelivered` para `undelivered`. Assim, `accepted` não
confirma entrega. O ID `SM...`, status HTTP e código numérico de erro podem ser
registrados. Texto, telefone, credenciais e URL com token não são registrados.

Timeout e falhas de conexão retornam estado `unknown`, pois não é possível saber
se o provedor recebeu a solicitação antes da falha. Respostas negativas retornam
`failed`. Não há webhook de delivery receipt; o Hub só reporta `sent` ou
`delivered` se esse status vier diretamente na resposta de criação do provedor.

## Compatibilidade de dados legados

Novos registros e alterações usam `tenants.mobile_phone`, `tenants.phone_user_id`,
`tenant_users.phone_number`, `tenant_users.phone_binding_version` e
`phone_audit`. Leitura temporária aceita os campos antigos
`whatsapp_phone`, `whatsapp_user_id`, `whatsapp_number`,
`whatsapp_binding_version` e `whatsapp_audit`. O payload administrativo antigo
`whatsapp_phone` também é aceito apenas como alias de entrada e nunca é gravado.
Não há migração automática nem alteração dos documentos existentes. A remoção
do fallback deve ocorrer somente depois de inventário/migração operacional dos
campos legados.

O campo `access_channel` continua distinguindo e-mail de SMS. A recuperação por
SMS permanece limitada ao usuário ativo vinculado ao telefone do próprio tenant;
os limites de recuperação e as regras de geração, uso único, expiração e hash do
token permanecem no Hub.
