# WhatsApp do HUB na SpeedTrail

Preparação na branch `feature/whatsapp-speedtrail`, baseada em `9b8fc559`.
Este documento não autoriza deploy, pareamento ou envio. Não modifica Pedidos.

## Arquitetura e contrato de proxy

O HUB acessa `https://dacot-whatsapp.speedtrail.com.br` com TLS validado,
Bearer, HMAC SHA-256, timestamp de 120 segundos e idempotência persistente.
O gateway pode receber HTTP interno exclusivamente atrás de um proxy HTTPS,
selecionado explicitamente por `WHATSAPP_TRANSPORT=proxy-http`. Ele não confia
em X-Forwarded-For/Proto nem os usa como prova de segurança. A plataforma deve
garantir que a porta 3002 não seja acessível diretamente pela internet e que
HTTP público seja recusado ou redirecionado ANTES de chegar à aplicação.
Não enviar credenciais em HTTP mesmo se houver redirecionamento.

Confirmar esse contrato na SpeedTrail antes de habilitar envios. A referência
de outro gateway é indicativa, não comprova a configuração deste serviço.
Se não houver terminação TLS segura, manter `https` e fornecer certificados
ao Node ou parar a ativação; nunca desativar verificação no cliente HUB.

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
| WHATSAPP_TRANSPORT | `proxy-http` atrás do proxy; padrão `https` | Sim para proxy | Não |
| WHATSAPP_ENABLED | `false` inicialmente; `true` só após autorização | Opt-in; padrão desativado | Não |
| WHATSAPP_ADMIN_PORT | `3003`, somente loopback | Não | Não |
| WHATSAPP_DB_PATH | `/var/data/whatsapp.sqlite` (também padrão) | Recomendada explícita | Não |
| WHATSAPP_STORAGE_KEY | 32 bytes aleatórios em Base64, estáveis | Sim | Sim |
| WHATSAPP_SERVICE_SECRET | Aleatório >=32 bytes, compartilhado só com HUB | Sim | Sim |
| WHATSAPP_ADMIN_SECRET | Outro segredo aleatório >=32 bytes | Sim | Sim |
| WHATSAPP_FRONTEND_ORIGIN | `https://dacot-frontend.speedtrail.com.br` | Sim | Não |
| WHATSAPP_TLS_KEY_FILE | Caminho PEM privado; só no modo `https` | Condicional | Arquivo privado |
| WHATSAPP_TLS_CERT_FILE | Caminho do certificado correspondente, só `https` | Condicional | Não |

Gerar os três segredos com um gerenciador seguro/CSPRNG, salvar diretamente no
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
| HUB WHATSAPP_SERVICE_URL | `https://dacot-whatsapp.speedtrail.com.br` | Para WhatsApp; não secreta | Reiniciar HUB |
| HUB WHATSAPP_SERVICE_SECRET | Mesmo segredo de envio do gateway | Sim; secreta | Reiniciar HUB |
| HUB WHATSAPP_SERVICE_CA_FILE | Omitir com certificado público confiável; caminho de CA privada nos demais ambientes | Condicional; CA pública | Reiniciar HUB |
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

## Implantação autorizada em etapas e rollback

1. Revisar diff, resultados de testes e variáveis. Sem tocar docs/WHATSAPP_DEV.md.
2. Após autorização explícita, commit/push da branch de trabalho; sem merge main.
3. Confirmar contrato de proxy, persistência, única instância, shell e versão Node.
4. PONTO DE PARADA: autorizar alteração da aplicação SpeedTrail e secrets.
5. Configurar gateway completo, WHATSAPP_ENABLED=false; publicar em manutenção.
6. Validar HTTPS público com verificação normal, health, 401 para envio sem auth,
   404 público para status/QR/reset mesmo com credencial, métodos e tamanho.
   Não usar credenciais em comandos gravados. Nunca testar senhas reais.
7. Reiniciar em manutenção, confirmar persistência com dados sintéticos e excluir
   somente esses dados de teste por procedimento revisado. Não copiar banco WAL
   em uso: backup SQLite consistente ou parada controlada antes de copiar arquivos.
8. PONTO DE PARADA: autorização coordenada para publicar HUB/frontend da feature
   e suas variáveis; branches atuais main não contêm toda a integração.
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

## Limitações a registrar

Railpack/HTTPS/firewall/shell/rede direta/cabeçalhos/proteção de logs/recursos e
backups da SpeedTrail não foram confirmados por documentação oficial disponível.
HMAC+TLS não protege disponibilidade contra saturação pública; pedir limites no
ingress quando disponíveis. Baileys não é API oficial e pode sofrer bloqueios.
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
