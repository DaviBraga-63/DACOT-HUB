# WhatsApp do HUB na SpeedTrail

Preparação na branch `feature/whatsapp-speedtrail`, com adaptação de rede privada
sobre o commit publicado `a32ce22deb2d6788f9aa80b543d06c5472209649`.
Este documento não autoriza deploy, pareamento ou envio. Não modifica Pedidos.

## Arquitetura e contrato de proxy

Conforme resposta do suporte fornecida pelos fundadores, a rede privada existe
entre aplicações do MESMO projeto, ambiente e região. Endereços confirmados:
`http://dacot-principal:8000`, `http://dacot-frontend:3000` e
`http://dacot-whatsapp:3002`. O tráfego privado é HTTP, sem proxy público ou TLS.
HTTPS público termina no proxy da SpeedTrail e chega como HTTP ao container.

O HUB usa `WHATSAPP_SERVICE_URL=http://dacot-whatsapp:3002` SOMENTE com
`WHATSAPP_SERVICE_TRANSPORT=speedtrail-private-http`. O padrão `https` continua
exigindo HTTPS. A exceção compara a origem exata, com porta explícita 3002:
não admite outros hosts, IPs, caminhos, portas, credenciais ou query strings.
Uma barra final simples é aceita. Links de primeiro acesso/recuperação continuam
HTTPS no frontend PÚBLICO, nunca nos hostnames privados.

Bearer, HMAC SHA-256, timestamp de 120 segundos, idempotência e timeout de 10s
permanecem. Nenhum redirecionamento é seguido, nem mesmo para outro destino
privado. O cliente usa `trust_env=False`: HTTP_PROXY/HTTPS_PROXY/ALL_PROXY não
podem encaminhar a chamada e credenciais por outro host. URLs públicas HTTPS
continuam válidas em ambos os modos, com validação de certificado habilitada;
não configurar CA de testes para o domínio público.

RISCO ACEITO DE TRANSPORTE: HTTP privado não oferece confidencialidade. Quem
conseguir observar essa rede pode ler destinatário, link e Bearer. Como a chave
HMAC é o próprio segredo de envio, sua captura também permite forjar mensagens;
HMAC não resolve esse risco. O isolamento da plataforma/projeto e os controles de
acesso às aplicações são parte da fronteira de confiança. Uma aplicação
comprometida no mesmo ambiente é um risco residual. Não hospedar aplicações não
confiáveis nele. Se for exigida confidencialidade ponta a ponta dentro da rede,
usar o modo HTTPS próprio com CA/certificado interno adequado em outra etapa.

A URL pública do gateway permanece, mas deve ser restringida por IP na aba Rede.
Segundo o suporte, isso não interfere na rota privada. Nunca enviar segredos
para HTTP público, nem para testar um redirecionamento.

Administração fica em listener separado, FIXO em 127.0.0.1, porta 3003 por
padrão. A porta pública nunca encaminha status, QR ou reset, mesmo com o
segredo administrativo correto. Exige segredo independente, métodos exatos e
limite global de 30 solicitações/minuto. O envio público tem limite global
de 120 solicitações/minuto (uma instância) e limite persistente por destinatário.
Isso não substitui proteção de disponibilidade no proxy da plataforma.

O HUB é a fronteira multi-tenant: valida super_admin, responsável, vínculo,
versão e restaurante antes de solicitar envio. O gateway tem uma única sessão
DACOT, não uma sessão por restaurante. Não expor suas credenciais aos clientes.

## Gateway: configuração exata

Raiz `whatsapp-service`; branch a publicar `feature/whatsapp-speedtrail`.
Railpack: manter build command vazio se a detecção do package-lock executar
`npm ci`; alternativa explícita `npm ci`. Start definitivo `node server.mjs`
(`npm start` é equivalente porque o package.json define esse mesmo comando).
Node >=22.13.0 e <23; validar versão efetiva nos logs de build. Não presumir
que `NODE_VERSION` seja reconhecido pelo Railpack: é configuração do provedor,
não uma variável lida pelo aplicativo. Health HTTP `GET /health`, 200 `{ok:true}`;
mede liveness, não conexão WhatsApp. Não configurar health para rotas internas.

Todas as variáveis abaixo são lidas ao iniciar: alterar exige reinicialização
ou novo deploy controlado, não recompilação React.

| KEY | Valor/finalidade | Obrigatória | Secreta |
| --- | --- | --- | --- |
| HOST | `0.0.0.0` (também padrão) | Recomendada explícita | Não |
| PORT | `3002` (padrão) | Recomendada explícita | Não |
| WHATSAPP_TRANSPORT | `proxy-http` para HTTP privado e terminação HTTPS pública; padrão `https` | Sim nesta arquitetura | Não |
| WHATSAPP_ENABLED | `false` inicialmente; `true` só após autorização | Opt-in; padrão desativado | Não |
| WHATSAPP_ADMIN_PORT | `3003`, somente loopback | Não | Não |
| WHATSAPP_DB_PATH | `/var/data/whatsapp.sqlite` (também padrão) | Recomendada explícita | Não |
| WHATSAPP_STORAGE_KEY | 32 bytes aleatórios em Base64, estáveis | Sim | Sim |
| WHATSAPP_SERVICE_SECRET | Aleatório >=32 bytes, compartilhado só com HUB | Sim | Sim |
| WHATSAPP_ADMIN_SECRET | Outro segredo aleatório >=32 bytes | Sim | Sim |
| WHATSAPP_PAIRING_SERVICE_SECRET | Segredo novo e distinto >=32 bytes, compartilhado apenas com o HUB | Condicional | Sim |
| WHATSAPP_PAIRING_SELF_SERVICE_ENABLED | `false` por padrão; `true` apenas para gerar o código | Condicional | Não |
| WHATSAPP_FRONTEND_ORIGIN | `https://dacot-frontend.speedtrail.com.br` | Sim | Não |
| WHATSAPP_TLS_KEY_FILE | Caminho PEM privado; só no modo `https` | Condicional | Arquivo privado |
| WHATSAPP_TLS_CERT_FILE | Caminho do certificado correspondente, só `https` | Condicional | Não |

Gerar os quatro segredos com um gerenciador seguro/CSPRNG, salvar diretamente no
cofre da plataforma, sem terminal gravado, chat ou Git. Para STORAGE_KEY gerar
exatamente 32 bytes e codificar Base64; os demais podem codificar 32 ou mais bytes
em Base64/hex. Nunca reutilizar JWT_SECRET, HANDOFF_JWT_SECRET ou MODULE_API_KEY.
Guardar cópia protegida da chave de armazenamento separada do backup SQLite.
Não substituir a chave em restart: uma chave nova torna a sessão ilegível.

Volume persistente 1 GB em `/var/data`; banco e WAL/SHM ficam juntos. Diretório
privado (0700), processo com um único usuário e umask 077; SQLite 0600.
Uma única instância/processo: não usar cluster, autoscaling ou workers duplicados.
Confirmar que rolling deploy não mantém duas instâncias sobre a mesma sessão;
se necessário usar stop/start sequencial. A aplicação não implementa fencing
distribuído. Confirmar persistência em restart/rebuild e recuperação do volume.

A limpeza roda no startup e a cada hora: retém registros de envio por 35 dias,
mais do que os links de primeiro acesso (30 dias) e recuperação (24 horas).
Não toca credenciais. Inclui pending/indeterminate após esse prazo: expirada a
credencial de redefinição, a idempotência não é arquivamento permanente.
Metadados de destinatário/request são HMAC; credenciais são AES-256-GCM.
SQLite não é criptografado integralmente: proteger volume e backups também.

## HUB e frontend

| Aplicação/KEY | Preenchimento | Obrigatória/secreta | Aplicação da mudança |
| --- | --- | --- | --- |
| HUB WHATSAPP_SERVICE_URL | `http://dacot-whatsapp:3002` | Para WhatsApp; não secreta | Reiniciar HUB |
| HUB WHATSAPP_SERVICE_TRANSPORT | `speedtrail-private-http`; padrão `https` | Obrigatória para habilitar a exceção HTTP | Reiniciar HUB |
| HUB WHATSAPP_SERVICE_SECRET | Mesmo segredo de envio do gateway | Sim; secreta | Reiniciar HUB |
| HUB WHATSAPP_PAIRING_SERVICE_SECRET | Segredo novo, aleatório e distinto (>=32 bytes), igual apenas ao segredo de delegação do gateway | Condicional; secreta | Somente durante pareamento controlado |
| HUB WHATSAPP_PAIRING_SELF_SERVICE_ENABLED | `false` por padrão; `true` somente durante a janela controlada | Condicional; não secreta | Reiniciar HUB |
| HUB WHATSAPP_SERVICE_CA_FILE | Omitir no HTTP privado e HTTPS público confiável; caminho de CA privada somente com HTTPS próprio | Condicional; CA pública | Reiniciar HUB |
| HUB FRONTEND_URL | `https://dacot-frontend.speedtrail.com.br` | Sim; não secreta | Reiniciar HUB |
| HUB RECOVERY_TRUSTED_PROXY_CIDRS | Somente CIDRs de proxies verificados; vazio até comprovação | Opcional; não secreta | Reiniciar HUB |
| Frontend REACT_APP_BACKEND_URL | `https://dacot-api.speedtrail.com.br` sem `/api` | Para implantação separada; não secreta | REBUILD frontend |

FRONTEND_URL e WHATSAPP_FRONTEND_ORIGIN devem corresponder exatamente.
WHATSAPP_ADMIN_SECRET e STORAGE_KEY nunca são configurados no HUB/frontend.
Variáveis REACT_APP_* são públicas no bundle; jamais colocar segredos nelas.
Preservar todas as demais configurações de MongoDB, e-mail, sessões e handoff.
Build backend `python -m pip install -r requirements.txt`, raiz `backend`;
start `python -m uvicorn server:app --host 0.0.0.0 --port 8000 --no-proxy-headers`.
O flag impede que Uvicorn altere o par direto antes da política de confiança.
Login e recuperação agora usam a mesma política: sem proxy confiável, ignoram
X-Forwarded-For. Isso pode agregar vários usuários no mesmo limite por origem.
Não resolver com 0.0.0.0/0. Confirmar se o proxy sobrescreve ou anexa cabeçalhos,
se a porta do backend aceita conexões diretas e quais são seus endereços.

### Verificação da cadeia de proxies

IPs de borda informados: 45.234.95.183 e 45.234.93.242. Cabeçalhos informados:
X-Forwarded-For, X-Forwarded-Proto, X-Forwarded-Host e X-Real-IP. Isso NÃO prova
que esses IPs sejam os pares TCP vistos pelo container. Não copiar esses dois
endereços automaticamente para RECOVERY_TRUSTED_PROXY_CIDRS.

Antes de configurar: pedir ao suporte o par/intervalo exato do último salto,
a ordem da cadeia e se o proxy descarta cabeçalhos fornecidos pelo cliente.
Em homologação, com Uvicorn --no-proxy-headers, observar apenas o par TCP e a
cadeia de IPs de requisições sintéticas, sem cookies, Authorization, corpos,
query strings ou contas reais. Não criar endpoint público de diagnóstico.
Comparar requisição pública normal, outra com X-Forwarded-For forjado e uma
requisição interna autorizada. Confiar somente em /32 ou /128 observados e
confirmados como estáveis pelo suporte, ou CIDR mínimo oficialmente garantido.
Verificar que o backend não aceita bypass público direto. Se os pares forem
dinâmicos e não documentados, manter vazio e registrar a agregação do limite
por IP do proxy; não ampliar confiança por tentativa. Remover instrumentação
temporária de homologação após a análise. Não usar X-Real-IP como atalho.

### Rede privada nas três aplicações e restrição pública

1. Conferir no painel o mesmo projeto, ambiente e região das três aplicações.
   Não foi confirmada a existência/necessidade de um botão de ativação; se
   houver associação de rede, usar somente a configuração documentada do painel.
2. Confirmar os aliases e portas: principal:8000, frontend:3000, whatsapp:3002
   com os hostnames completos listados no início. Manter a administração em
   127.0.0.1:3003 sem publicação de porta, domínio ou regra de proxy para ela.
3. Com gateway em manutenção e acesso privado autorizado, confirmar no ambiente
   do HUB a resolução do alias pelo DNS privado da plataforma e testar
   GET http://dacot-whatsapp:3002/health. O nome exato permitido pelo código não
   comprova sozinho a rota/DNS privado. Não enviar mensagens de teste.
4. Não alterar URLs dos navegadores: frontend/API continuam nos domínios HTTPS
   públicos existentes. O frontend não precisa consumir hostname privado.
5. Na aba Rede do gateway, aplicar bloqueio público por padrão e permitir apenas
   IPs de saída administrativos/monitoramento conhecidos, se a interface exigir
   uma lista de permitidos. Confirmar a semântica da regra com o suporte antes
   de salvar; uma lista vazia não deve ser presumida como bloqueio total.
6. Não liberar os IPs de borda por conveniência: verificar se o controle avalia
   o cliente original ou o proxy. Liberar um proxy compartilhado pode liberar
   todos os visitantes. Nunca usar 0.0.0.0/0.
7. Testar acesso público de uma origem autorizada e outra não autorizada e,
   separadamente, o health privado do HUB. Verificar também health checks da
   plataforma para não bloquear sua avaliação de disponibilidade por engano.
8. Registrar regra anterior e procedimento de reversão antes da mudança.

Frontend: Yarn 1.22.22, `yarn install --frozen-lockfile --production=false`
e `yarn build`; servir `build/` com fallback SPA sem capturar `/api`.
Preservar CORS explícito, withCredentials e cookies HttpOnly/Secure existentes.
Login desktop informado pelo usuário não prova compatibilidade de todos os
navegadores móveis: validar cookies entre esses hosts antes da publicação final.
Falha WhatsApp não desfaz cadastro; reenvio posterior respeita limites. E-mail
é canal alternativo explícito; não há fallback automático de canal prometido.

## Pareamento administrativo

Exige shell interativo privado no mesmo container ou túnel SSH autorizado.
Confirmar disponibilidade na SpeedTrail antes de ativar; se não existir, PARAR
essa etapa. Não criar endpoint público de QR para contornar essa limitação.
No terminal privado, configurar WHATSAPP_SERVICE_URL=`http://127.0.0.1:3003`
para o script `node pair.mjs`, com segredo administrativo já no ambiente.
HTTP existe apenas no loopback local ou dentro do túnel SSH criptografado.
Não executar pelo pipeline/log de deploy nem salvar saída ou captura do QR.
Sem `--reset` inicialmente; reset somente para conta desconectada definitivamente.
Consultar estado somente na porta administrativa com autenticação.

### Código de vinculação controlado pelo HUB

Caso a SpeedTrail não disponibilize shell/túnel privado, o QR continua proibido
na web pública. Há uma alternativa estritamente temporária: o código de
vinculação do WhatsApp. Ela só existe quando **as duas** aplicações recebem
`WHATSAPP_PAIRING_SELF_SERVICE_ENABLED=true` e deve ser desligada logo após o
pareamento.

- Somente uma sessão de `super_admin` do HUB pode solicitar o código em
  `/administracao/whatsapp`; a senha atual é confirmada a cada pedido.
- O navegador recebe apenas o código efêmero, em resposta `no-store`; não recebe
  `WHATSAPP_ADMIN_SECRET`, QR, estado administrativo ou credenciais da sessão.
- O HUB usa `WHATSAPP_PAIRING_SERVICE_SECRET`, exclusivo para esse único pedido.
  Ele é diferente de `WHATSAPP_SERVICE_SECRET` e de `WHATSAPP_ADMIN_SECRET`.
  A credencial administrativa continua somente no gateway.
- A chamada HUB → gateway usa Bearer, HMAC-SHA256, timestamp de 120 segundos,
  idempotência e sem redirects/proxies de ambiente. O gateway guarda somente
  hashes para anti-replay/limite; nunca o código ou número em logs/auditoria.
- Limites: duas tentativas por superadministrador e seis globais por 15 minutos
  no HUB; três por número no gateway. Erros genéricos não revelam estado da
  sessão. A ação é auditada sem telefone ou código.

Para uso controlado: configurar `WHATSAPP_ENABLED=true` apenas no gateway,
preencher o novo segredo idêntico no HUB/gateway e manter a restrição pública
por IP. No WhatsApp da conta de serviço, usar **Dispositivos conectados →
Vincular com número de telefone** e digitar o código exibido. Após conexão
confirmada, voltar a variável `WHATSAPP_PAIRING_SELF_SERVICE_ENABLED=false` nos
dois serviços e reiniciá-los. Não é necessário — nem permitido — expor 3003.

## Implantação autorizada em etapas e rollback

1. Revisar diff, resultados de testes e variáveis. Sem tocar docs/WHATSAPP_DEV.md.
2. Após autorização explícita, commit/push da branch de trabalho; sem merge main.
3. Confirmar projeto/ambiente/região, regra pública por IP, única instância,
   shell privado e versão Node. Validar rede e backup antes de alterações reais.
4. PONTO DE PARADA: autorizar alteração da aplicação SpeedTrail e secrets.
5. Configurar gateway completo, WHATSAPP_ENABLED=false; publicar em manutenção.
6. Validar health privado do HUB e HTTPS público a partir de IP permitido,
   401 para envio sem auth,
   404 público para status/QR/reset mesmo com credencial, métodos e tamanho.
   Não usar credenciais em comandos gravados. Nunca testar senhas reais.
7. Reiniciar em manutenção, confirmar persistência com dados sintéticos e excluir
   somente esses dados de teste por procedimento revisado. Não copiar banco WAL
   em uso: backup SQLite consistente ou parada controlada antes de copiar arquivos.
8. PONTO DE PARADA: autorização coordenada para publicar HUB/frontend da feature
   e suas variáveis; branches atuais main não contêm toda a integração. Usar
   URL privada e modo explícito no HUB; preservar URLs públicas no frontend.
9. Testar login, e-mail, CORS, cookies e isolamento com contas descartáveis.
10. PONTO DE PARADA: autorização de ativação WHATSAPP_ENABLED=true e pareamento
    no terminal privado. Nunca conectar a sessão local de testes por acidente.
11. Testar primeiro acesso (30 dias) e recuperação (24 horas), uso único, senha
    anterior rejeitada, troca de número, indisponibilidade e reenvio limitado.
12. Validar restart preservando sessão e deduplicação, consumo RAM/disco, logs
    sem tokens/QR/telefones. Não considerar status Live como prova de entrega.

Rollback gateway/proxy: WHATSAPP_ENABLED=false e restaurar comando temporário
anterior ou versão conhecida, conservando volume/chave. Erro SQLite: parar serviço,
preservar cópia consistente e investigar; nunca apagar banco ou gerar chave nova.
WhatsApp desconectado: manter e-mail, manutenção e recuperar sessão por terminal.
Erro HUB: restaurar commit/configuração anteriores sem desfazer banco por cópia
antiga; tokens novos podem ficar inválidos, reemitir depois pelo fluxo autorizado.
Frontend: restaurar build anterior com URL API compatível; coordenar com backend.
Nenhum passo requer exclusão de coleções, índices ou alteração manual de usuários.
Rollback do transporte HUB: antes de voltar a a32ce22 ou anterior, restaurar a
URL HTTPS pública (ela rejeita HTTP) e a política de IP necessária para o HUB
somente após confirmação; alternativamente deixar WhatsApp indisponível e manter
e-mail enquanto se recupera. Nunca reabrir irrestritamente o gateway para isso.
Backups de volume: suporte informa cópias diárias com retenção de sete dias;
confirmar no painel um backup real e o procedimento de restauração antes de
depender dele. Restaurar SQLite de forma consistente, sem trocar STORAGE_KEY;
um snapshot antigo pode perder deduplicação recente. Não repetir envios de estado
incerto automaticamente. Registrar horário do último backup/restauração.

## Limitações a registrar

Suporte confirmou HTTP privado, escopo projeto/ambiente/região, TLS no proxy,
restrição pública por IP e backup diário com retenção de sete dias. Permanecem
pendentes shell/túnel privado, pares TCP efetivos, sanitização de cabeçalhos,
isolamento das portas, comportamento do deploy em instância única e evidência
de restauração de backup. Acesso privado ao namespace de rede do container é
necessário para parear: console interativo não gravado ou SSH com port forwarding
até 127.0.0.1:3003. Sem esse recurso, manter WHATSAPP_ENABLED=false. Não expor a
administração em 0.0.0.0 nem criar rota pública de QR para contornar o bloqueio.
HMAC não protege disponibilidade contra saturação; Baileys não é API oficial.
Rotação da chave STORAGE exige procedimento próprio, não alteração direta.

## Evidências locais — 22/10/2026

- `python -m pytest -c backend/pytest.ini backend/p0_tests -p no:cacheprovider`:
  114 aprovados, zero falhas, 48 avisos de depreciação on_event do FastAPI.
  Python isolado 3.12.14, pytest 9.1.1, xdist 2 workers; P0_MONGOD aponta
  exclusivamente ao executável local e P0_ORDERS_BACKEND à cópia isolada já
  existente do Pedidos. Harness cria MongoDB replica set descartável e credenciais
  sintéticas, executa transações, isolamento, handoff e regressão sem produção.
- `npx --yes --package=node@22.22.0 node --test test/*.test.mjs`:
  10 aprovados, zero falhas ou skips. Runtime temporário, sem instalar Node global.
  Inclui proxy HTTPS local real com CA/leaf descartáveis, rejeição de CA e SAN
  incorretos, manutenção real em subprocesso, sessão sintética preservada,
  autenticação/HMAC/replay/idempotência, retenção e limite administrativo.
  OpenSSL gera certificados só no diretório temporário do teste, removido depois;
  não instala nenhuma confiança no Windows ou navegador. Node 22 emite aviso
  de que node:sqlite ainda é experimental nessa versão.
- `npm run build` em frontend: compilou com sucesso com dependências já
  instaladas. `yarn build` não executou porque Yarn não está no PATH local;
  o script craco é o mesmo. Nenhuma dependência/lockfile frontend foi alterada.
- `git diff --check`: sem erros; avisos de conversão LF/CRLF existentes no Git.
- Não existe suíte unitária em frontend/src nesta cópia. Navegador/E2E,
  Railpack real, proxy SpeedTrail, reinício Linux/SIGTERM, pareamento, entrega
  real e persistência do volume remoto não foram executados nesta etapa.
  Os testes Node de encerramento usam terminação do subprocesso Windows;
  não comprovam recebimento gracioso de SIGTERM em Linux.
- Nenhum teste envia mensagens reais ou conecta Baileys; conexão é mockada ou
  desativada. Builds gerados permanecem ignorados. docs/WHATSAPP_DEV.md preservado.

### Regressão após adaptação privada — 22/10/2026

- Mesma suíte P0 completa e harness descartável: **147 aprovados, zero falhas**,
  em 117,24 segundos, com 48 avisos de depreciação on_event existentes.
- Suíte Node 22.22.0: **10 aprovados, zero falhas ou skips**; gateway inalterado.
- Recorte inicial do adaptador/proxy: 42 aprovados (já incluídos nos 147).
- Novos casos cobrem origem privada exata e configuração explícita, portas,
  usuário/senha na URL, query/path/fragment, hosts públicos, IPs/metadados,
  preservação do HMAC/Bearer e links HTTPS, redirects reais do cliente httpx
  com MockTransport e desconsideração de proxies de ambiente.
- `git diff --check` sem erros. Frontend não foi alterado; não foi necessário
  repetir o build desta etapa. DNS privado real, restrição por IP, proxy e
  backup da SpeedTrail não foram acessados nem validados por estes testes.
- Quatro arquivos alterados: backend/whatsapp_delivery.py, backend/server.py,
  backend/p0_tests/test_whatsapp_delivery.py e este documento. Sem commit,
  push, merge ou deploy nesta etapa.
