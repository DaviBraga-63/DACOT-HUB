# P0 — contrato executável e homologação Hub ↔ Pedidos

Este documento substitui as instruções conflitantes de handoff dos documentos
antigos. Nenhuma implantação ou migração de produção foi executada por este lote.

## Escopo e compatibilidade

- Somente usuários de restaurante acessam a operação do próprio restaurante.
- O endpoint administrativo de launch retorna 403; o botão indica acesso pelo portal.
- Pedidos continua rejeitando `hub_user:`. Não há impersonação/suporte V1.
- Handoff: HS256, emissor `dacot-hub`, audiência `dacot-orders`, módulo `orders`,
  `sub=tenant_user:<ObjectId>`, validade máxima 60s, `jti` de uso único.
- Extensão obrigatória: `hub_access={user: int, tenant: int, module: int}`. Valores
  não negativos provenientes exclusivamente do banco do Hub. A versão de envelope
  continua 1; tokens antigos sem essa extensão são rejeitados com 401.
- Pedidos aceita `/api/orders/session/exchange` e `/api/session/exchange`.
- A sessão local mantém a cópia assinada das versões. Ela não usa a versão mais
  recente da cópia do usuário para "atualizar" silenciosamente uma sessão antiga.
- O Hub não recebe nem armazena pedidos. Não há alteração em WhatsApp ou outros domínios.

## Status efetivo e autorização

`GET /api/public/tenants/{tid}/modules/orders/status`, com `X-Module-Key`, exige
tenant existente em active/trial, módulo existente em available e ativação ativa.
Recurso inexistente retorna 404; suspensão/inativação retorna `active:false`.
Chave é validada antes da consulta de existência.

Novo contrato interno:
`POST /api/public/tenants/{tid}/modules/orders/access`, mesmo cabeçalho, corpo:

```json
{"subject":"tenant_user:<id>","role":"admin","hub_access":{"user":0,"tenant":0,"module":0}}
```

Além do status efetivo, exige usuário pertencente ao tenant, ativo, com senha,
sem recuperação obrigatória, papel válido/igual ao solicitado e todas as versões
iguais às persistidas. Retorna somente `{"active":true|false}`, sem dados pessoais,
com Cache-Control no-store. O endpoint não emite sessão e não aceita usuário staff.

## Revogação e indisponibilidade

- Alterar status do tenant incrementa `tenants.access_version`.
- Desativar módulo incrementa `tenant_modules.access_version`.
- Alterar papel/status do usuário incrementa `tenant_users.token_version`.
- Recuperar senha ou aplicar quarentena de conta incrementa `token_version`.
- Exclusão de tenant/usuário ou módulo indisponível também bloqueia a consulta.
- Novos handoffs são confirmados no Hub na troca, sem reutilizar cache positivo.
- Nas requisições autenticadas de usuários vindos do Hub, Pedidos usa confirmação
  positiva por **no máximo 60 segundos**, contados antes da chamada HTTP.
- Cache por processo, limitado a 10.000 entradas, chave composta de tenant,
  usuário, papel e versões; locks de tamanho fixo agrupam chamadas concorrentes.
  Não é um cache global entre workers: a carga é no máximo uma confirmação por
  identidade/versões/minuto em cada worker com sessão ativa, além dos handoffs.
- O prazo não é renovado por uso do cache. Reativar uma entidade não ressuscita
  sessões com versões antigas. É necessário um novo handoff.
- Com Hub indisponível, confirmação ainda válida pode ser usada pelo restante dos
  60s. Depois disso, falha fechada: 503, sem servir operações protegidas. Negativa
  explícita retorna 403. Timeout HTTP de 5s; requisições já autorizadas/em curso não
  são canceladas retroativamente. A janela limita a admissão de novas operações.
- Sessões locais preexistentes do Pedidos não são convertidas em identidades Hub.
  Antes da homologação, inventariar contas locais: não tratar contas independentes
  como se fossem revogadas pelo Hub.
- Reiniciar workers perde cache, o que exige nova confirmação, não amplia acesso.

## Bootstrap e contas históricas

Hub não cria restaurantes/usuários de demonstração, inclusive em desenvolvimento.
O catálogo de módulos permanece. Admin e contas opcionais são criados somente se
ausentes; contas existentes nunca têm senha restaurada pelo ambiente. O bootstrap
não altera token_version existente. ADMIN_PASSWORD só é necessário para criar a
conta ADMIN_EMAIL ainda inexistente. Não trocar ADMIN_EMAIL como método de reset.

Usuário sem hash continua sem senha até recuperação/ação administrativa. Nenhum
usuário é apagado. O fluxo normal de recuperação continua de uso único e invalida
sessões, removendo a marca `password_reset_required` após sucesso.

Para contas que podem ter recebido a senha histórica compartilhada, usar a ferramenta
`backend/audit_legacy_passwords.py`. Não confundir ausência de registros de origem
com prova de segurança: o diagnóstico compara a senha candidata com cada hash bcrypt.
Ele identifica senha ausente, hash inválido ou correspondência; não prova quando ou
por quem uma senha igual foi definida. Não imprime senha/hash, somente IDs/motivo.

Procedimento administrativo (não executado em produção):

1. Fazer backup do banco e configurar explicitamente MONGO_URL e DB_NAME no terminal
   administrativo seguro. A ferramenta não lê .env.
2. Executar `python backend/audit_legacy_passwords.py`. Digitar privadamente a antiga
   senha conhecida; ela não vai na linha de comando. O padrão é somente diagnóstico.
3. Revisar os IDs. Executar com `--apply --confirm-db NOME_EXATO_DO_BANCO` para marcar
   as correspondências com recuperação obrigatória e revogar sessões por versão.
   Não há alteração do hash/senha nem exclusão. A operação é idempotente e compara
   o hash antes de gravar para não invalidar uma recuperação concorrente.
4. Orientar usuários afetados a recuperar senha via e-mail. Validar o serviço de
   e-mail antes de aplicar. Contas sem e-mail controlado exigem revisão humana.
5. Reexecutar diagnóstico após recuperação. Remover a flag manualmente não é a
   remediação: a credencial antiga precisa deixar de ser utilizada.

Não foi feita quarentena automática no startup. Contas históricas permanecem um
risco até a execução e revisão administrativa deste procedimento.

## Configuração (somente backend)

Hub:
- `APP_ENV=production` (padrão quando ausente).
- `MONGO_URL`, `DB_NAME`, `JWT_SECRET`, `ADMIN_EMAIL`; `ADMIN_PASSWORD` para bootstrap inicial.
- `HANDOFF_JWT_SECRET`: segredo forte compartilhado somente entre os backends.
- `HANDOFF_ISSUER=dacot-hub`.
- `MODULE_API_KEY`: chave separada do segredo JWT para Pedidos consultar o Hub.
- `HANDOFF_ALLOWED_ORIGINS_JSON={"orders":["https://HOST_REAL_PEDIDOS"]}`.
- `FRONTEND_URL` e configuração de e-mail existentes, para recuperação.

Pedidos:
- `APP_ENV=production`.
- `HUB_BASE_URL=https://HOST_REAL_API_HUB` (origem da API, sem `/api`).
- `MODULE_API_KEY`: mesmo valor do Hub.
- `HANDOFF_JWT_SECRET`, `HANDOFF_ISSUER=dacot-hub`, `HANDOFF_AUDIENCE=dacot-orders`.
- `HANDOFF_MODULE_ID=orders`, `HANDOFF_VERSION=1`.
- `JWT_SECRET` próprio para sessões do Pedidos, diferente do segredo handoff.

Aliases de transição: Hub aceita ORDERS_MODULE_KEY; Pedidos aceita HUB_MODULE_KEY.
Se canônica e alias estiverem presentes, precisam ser idênticas; conflito falha
fechado. Preferir apenas MODULE_API_KEY nos dois lados. Nenhuma chave no frontend.

Destinos: allowlist vazia bloqueia. Apenas origens exatas (sem wildcard/subdomínio
implícito), HTTPS, sem userinfo, query/fragmento ou parsing ambíguo. Caminhos dentro
da origem são permitidos: a origem deve ser totalmente controlada pelo DACOT, sem
redirecionadores abertos/conteúdo de terceiros. Validação ocorre ao salvar a URL e
antes de emitir o JWT, inclusive para URLs antigas/templates do banco.

Local: configurar explicitamente APP_ENV=development em ambos e autorizar, por
exemplo, `{"orders":["http://127.0.0.1:3001"]}`. HTTP permitido apenas em loopback.
Não colocar curingas ou origens de desenvolvimento no ambiente de produção.

## Ordem de implantação futura

1. Preparar allowlist e chaves nos dois ambientes de homologação.
2. Publicar Hub primeiro (API access e claims), depois Pedidos. Não houve publicação neste lote.
3. Durante transição, o Pedidos antigo ainda não aplica revogação: não liberar uso
   real até ambos atualizados. Pedidos novo com Hub antigo falha fechado.
4. Sessões/handoffs antigos sem hub_access exigirão entrada novamente pelo portal.
5. Executar diagnóstico de contas históricas antes de liberar uso real.

## Homologação com dois restaurantes

1. Usar bancos de homologação vazios, credenciais sintéticas, HTTPS e e-mail de teste.
2. Com admin DACOT, cadastrar Restaurante A e B, ambos active. Ativar orders em ambos
   e configurar URLs aprovadas com seus slugs. Criar um usuário admin para cada um.
3. Em perfis de navegador separados, entrar no Hub como A e B, abrir Pedidos pelo
   portal e confirmar restaurante/papel corretos. Confirmar remoção de handoff da URL.
4. Criar um pedido sintético no A pelo fluxo existente do Pedidos. Com B, tentar
   ler seu ID: deve retornar 404; listagens de B não devem conter dados de A.
5. Suspender A: novo handoff falha imediatamente. Sessão A aberta deve bloquear
   novas operações em até 60s; B continua funcionando. Reativar A não recupera a
   sessão antiga; novo handoff deve funcionar.
6. Repetir com desativação/reativação de orders no A e com inativação do usuário A.
   Repetir troca de papel e recuperação de senha para verificar versões de usuário.
7. Em homologação, indisponibilizar Hub: sessão com confirmação recente dura somente
   o restante da janela; depois recebe 503. Restaurar Hub recupera sessões ainda
   autorizadas; sessões revogadas continuam bloqueadas.
8. Tentar URL não autorizada/HTTP em produção: salvar/emitir deve falhar. Verificar
   que staff não consegue gerar handoff e que a tela administrativa orienta o portal.
9. Capturar somente token de teste: repetir exchange retorna 401; esperar mais de
   60s antes do primeiro exchange retorna 401. Não registrar tokens reais em logs.

## Testes reproduzíveis

Usar Python com dependências dos dois backends, pytest e pytest-xdist instalados.
Não executar suites antigas contra URLs de preview/produção.

```powershell
$env:P0_MONGOD='CAMINHO_ABSOLUTO/mongod.exe'
$env:P0_ORDERS_BACKEND='CAMINHO_ABSOLUTO/DACOT-PEDIDOS/backend'
python -m pytest backend/p0_tests -n 0 -q
```

A fixture lança os dois backends reais e Mongo temporário em 127.0.0.1, com bancos
separados, portas dinâmicas, segredos aleatórios e .env desabilitado. Fecha os
processos e remove somente seu diretório temporário ao terminar. Nenhuma credencial
real é usada. O teste da janela de revogação aguarda 61s de relógio real.
