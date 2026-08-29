# DACOT Module Integration Contract

**Versão**: 1.0 (draft para revisão)
**Status**: Proposta técnica — nenhuma alteração de código realizada
**Escopo**: Handoff entre **DACOT Hub** (painel administrativo) e o **Módulo de Pedidos** (aplicação operacional multi-tenant já existente em outro projeto).
**Não incluído nesta fase**: implementação. Apenas contrato para validação cruzada entre os dois projetos.

---

## 1. Identidade do Tenant (Restaurante)

### 1.1 Como o Hub identifica um tenant hoje

O Hub trata cada restaurante como um **tenant**. A identidade canônica está na coleção `tenants` do MongoDB e é composta por:

| Campo   | Tipo   | Origem                                            | Estabilidade | Uso                                              |
|---------|--------|---------------------------------------------------|--------------|--------------------------------------------------|
| `_id`   | `ObjectId` (serializado como `str` de 24 hex) | Gerado pelo MongoDB no `insertOne` | **Imutável**  | ID técnico canônico — chave primária global      |
| `slug`  | `str` (kebab-case, único) | Derivado de `name` no cadastro     | Mutável em tese, único garantido por índice | ID legível — usado em URLs de módulos (`{slug}`) |
| `email` | `str` (único por convenção; não indexado como único) | Cadastro | Pode mudar | Contato — **não** usar como identidade          |
| `name`  | `str`  | Cadastro | Pode mudar   | Exibição apenas                                  |

### 1.2 Qual ID é usado atualmente

- **ID canônico**: `tenants._id` (string de 24 caracteres hexadecimais) — este é o valor exposto pela API do Hub como `id` e é o que aparece em `tenant_modules.tenant_id`.
- **ID de URL/apresentação**: `tenants.slug` — hoje é substituído em `modules.launch_url_template` (`https://pedidos.dacot.app/{slug}`) para compor a URL do módulo.

### 1.3 Decisão contratual

- O **JWT de handoff** deve carregar o `_id` (não o slug) no claim `restaurant_id`.
  Motivo: o slug é derivado do nome; se o nome mudar no futuro o slug pode ser recomputado e quebrar tokens/logs.
- O `slug` continua sendo aceito **apenas** em URLs (como conveniência humana), nunca como fonte de autorização.

---

## 2. Estado atual de ativação de módulos

### 2.1 Modelo `tenant_modules`

```
tenant_modules {
  tenant_id:    str    // referência a tenants._id
  module_key:   str    // "orders", "kitchen", ...
  module_id:    str    // referência a modules._id (cache)
  active:       bool
  activated_at, deactivated_at, activated_by
  launch_url:   str    // override opcional por tenant
}
```
Índice único composto: `(tenant_id, module_key)`.

### 2.2 Como o Hub sabe que "Pedidos está ativo" para um restaurante

Existe um documento `tenant_modules` com:
- `tenant_id = <ID do restaurante>`
- `module_key = "orders"`
- `active = true`

Consulta canônica de verificação (feita hoje por `GET /api/hub/tenants/{id}/modules`):
```
db.tenant_modules.findOne({tenant_id, module_key: "orders", active: true})
```

### 2.3 Como o botão "Abrir módulo" funciona hoje

1. Frontend lê `GET /api/hub/tenants/{id}/modules`.
2. Para módulos com `active = true`, backend devolve `launch_url` já resolvido:
   - Se `tenant_modules.launch_url` estiver preenchido → usa esse valor.
   - Caso contrário → substitui `{slug}` em `modules.launch_url_template`.
3. Frontend renderiza um `<a href="{launch_url}" target="_blank">Abrir módulo</a>`.
4. **Não há token de handoff**. A URL abre em nova aba e o Módulo de Pedidos é responsável por sua própria autenticação.

### 2.4 URL esperada para o Módulo de Pedidos

- Template padrão: `https://pedidos.dacot.app/{slug}` (configurável).
- Após a introdução do handoff proposto abaixo:
  `https://pedidos.dacot.app/{slug}?handoff=<JWT>` (ver seção 4.3).

---

## 3. Contexto do Módulo de Pedidos (fornecido pelo usuário)

- Autenticação própria JWT.
- `restaurant_id` derivado do JWT.
- Isolamento multi-tenant.
- Roles: `admin`, `manager`, `waiter`, `kitchen`.
- RBAC no backend.
- Pedidos, produtos, clientes, cozinha.

Isso significa que o Módulo de Pedidos **já sabe emitir** um JWT próprio depois de identificar o usuário. O que ele precisa do Hub é um **envelope assinado e curto de introdução (handoff)** que prove: "este é o tenant X e este operador tem role Y". A partir daí, ele emite os próprios tokens de sessão.

---

## 4. Contrato do JWT de Handoff (Launch Token)

### 4.1 Princípios

- **Assinado pelo Hub**, verificado pelo Módulo de Pedidos.
- **Curta duração** (60 segundos, single-use).
- **Nunca circula no frontend do Hub** além do momento da abertura da nova aba.
- **Não substitui** a sessão do Módulo de Pedidos — apenas inicia uma.
- Regras invioláveis:
  1. `restaurant_id` **NUNCA** vem da querystring; sempre do claim assinado.
  2. `role` e `module` **NUNCA** vêm do frontend; sempre do claim assinado.
  3. Módulo de Pedidos **DEVE** revalidar no Hub se o módulo continua ativo antes de emitir sessão.

### 4.2 Algoritmo de assinatura

- **Recomendado**: `RS256` (assimétrico).
  - Hub guarda **chave privada** (`HUB_JWT_PRIVATE_KEY`).
  - Módulo de Pedidos guarda **apenas a chave pública** (`HUB_JWT_PUBLIC_KEY`) — não pode forjar tokens, apenas verificar.
  - Vantagem: se o Módulo de Pedidos for comprometido, o atacante não pode emitir handoffs.
- **Alternativa aceitável (menor complexidade)**: `HS256` com segredo compartilhado (`HUB_HANDOFF_SECRET`).
  - Menor overhead; ambos os projetos guardam o mesmo segredo em `.env`.
  - Rotação exige coordenação simultânea. Menos seguro que RS256.

**Decisão proposta**: começar com **HS256** para acelerar o MVP da integração e migrar para **RS256** quando houver rotação automatizada de chaves.

### 4.3 Formato do envelope (querystring)

```
https://pedidos.dacot.app/{slug}?handoff=<JWT>
```
- Um único parâmetro `handoff`.
- Nenhum outro dado sensível na URL.
- O Módulo de Pedidos, ao consumir, deve **remover o parâmetro da URL** via `history.replaceState` para evitar vazamento por logs de servidor/referer.

### 4.4 Claims obrigatórios

```json
{
  "iss": "dacot-hub",
  "aud": "dacot-orders",
  "sub": "hub_user:<hub_users._id>",
  "restaurant_id": "<tenants._id>",
  "restaurant_slug": "<tenants.slug>",
  "role": "admin",
  "module": "orders",
  "jti": "<uuid v4 único>",
  "iat": 1740700000,
  "exp": 1740700060,
  "nbf": 1740699995,
  "handoff_version": 1
}
```

| Claim              | Obrigatório | Descrição / Regra                                                                              |
|--------------------|:-----------:|------------------------------------------------------------------------------------------------|
| `iss`              | ✅          | Emissor. Fixo: `"dacot-hub"`. Módulo rejeita se diferente.                                     |
| `aud`              | ✅          | Público. Fixo por módulo destino: `"dacot-orders"` (para outros módulos: `"dacot-kitchen"`…).  |
| `sub`              | ✅          | Sujeito do handoff (admin DACOT que iniciou o acesso). Formato `hub_user:<id>`.                |
| `restaurant_id`    | ✅          | `tenants._id` como string 24 hex. **Fonte única de autorização de tenant.**                    |
| `restaurant_slug`  | ⚪ opcional | Conveniência para rotas humanas. Nunca usado para autorização.                                 |
| `role`             | ✅          | Uma de `admin`, `manager`, `waiter`, `kitchen`. Deve casar com o RBAC do Módulo.               |
| `module`           | ✅          | Sempre `"orders"` neste handoff. Se o Módulo receber outro valor, rejeita.                     |
| `jti`              | ✅          | UUID v4 único por token. Módulo mantém cache (redis/mongo) de `jti` consumidos por 5 min.      |
| `iat`              | ✅          | Timestamp de emissão (segundos Unix).                                                          |
| `exp`              | ✅          | Máximo `iat + 60` segundos. Módulo rejeita `exp - iat > 90`.                                    |
| `nbf`              | ⚪ opcional | `iat - 5` para tolerar dessincronização de relógio.                                            |
| `handoff_version`  | ✅          | Inteiro. Módulo rejeita se desconhecido — permite evolução do contrato sem quebrar prod.       |

### 4.5 Quem assina, quem valida

- **Assina**: apenas o backend do DACOT Hub, no endpoint (a construir na próxima fase)
  `POST /api/hub/tenants/{id}/modules/orders/launch-token`.
  Requer sessão de `hub_user` válida (cookie httpOnly).
- **Valida**: backend do Módulo de Pedidos, em rota pública `POST /api/orders/session/exchange` (nome sugerido).
  O frontend do Módulo NUNCA valida — apenas repassa o `handoff` para o próprio backend.

### 4.6 Distribuição segura da chave

Nenhum dos dois projetos deve carregar a chave no frontend.

- **HS256 (inicial)**
  - `HUB_HANDOFF_SECRET` de 64 caracteres hex aleatórios.
  - Presente **apenas em**:
    - `/app/backend/.env` do Hub (usado para assinar).
    - `.env` do backend do Módulo de Pedidos (usado para verificar).
  - Nunca em Git — o `.env` já está ignorado.
  - Rotação: gerar novo segredo, deployar simultaneamente em ambos os backends. Uma janela de dupla-chave (aceitar segredo antigo por 5 min) resolve zero-downtime.
- **RS256 (evolução recomendada)**
  - Hub gera par RSA-2048.
  - Chave privada permanece apenas no backend do Hub.
  - Chave pública é publicada em `GET /api/hub/.well-known/jwks.json` (endpoint público, apenas metadados).
  - Módulo de Pedidos busca a JWKS em intervalos regulares (ex.: 1h) e cacheia.
  - Rotação sem coordenação — basta publicar nova chave e manter a antiga no JWKS até que todos tokens expirem.

### 4.7 Como o Módulo de Pedidos consome o handoff

Fluxo obrigatório no backend do Módulo:

1. **Recebe** o JWT via `POST /api/orders/session/exchange` (body `{ "handoff": "..." }`).
2. **Verifica assinatura** com `HUB_HANDOFF_SECRET` (ou JWKS público).
3. **Valida claims**:
   - `iss === "dacot-hub"`
   - `aud === "dacot-orders"`
   - `module === "orders"`
   - `exp > now` e `iat > now - 60`
   - `handoff_version` conhecido
   - `role ∈ {admin, manager, waiter, kitchen}`
   - `restaurant_id` é ObjectId válido
4. **Anti-replay**: consulta cache de `jti` já consumidos. Se existe → 401. Caso contrário, insere no cache com TTL = `exp - now + 60s`.
5. **Verifica ativação atual** chamando o Hub:
   `GET https://hub.dacot.app/api/public/tenants/{restaurant_id}/modules/orders/status`
   (novo endpoint público a construir — retorna `{active: bool}` sem exigir sessão, apenas API key de módulo).
   Se `active !== true` → 403.
6. **Resolve/cria** o usuário operacional no Módulo:
   - Chave de identidade: `(restaurant_id, hub_sub)` — vinculando o admin DACOT que abriu ao restaurante-alvo.
   - Se não existir usuário local com essa chave, cria com o `role` do token.
   - Se existir, **não sobrescreve** role local (o Módulo é dono do RBAC operacional). Uma exceção clara: se `role === "admin"` no handoff, promove/mantém como admin.
7. **Emite sua própria sessão** (o JWT interno que o Módulo já usa hoje) via cookies httpOnly ou header.
8. **Redireciona** o frontend do Módulo para a rota inicial adequada (dashboard de pedidos, cozinha, etc. conforme role).

### 4.8 Endpoint público de verificação de ativação (a criar no Hub)

Objetivo: permitir que o Módulo revalide o estado sem depender de sessão de admin.

```
GET /api/public/tenants/{tenant_id}/modules/{module_key}/status
Headers: X-Module-Key: <segredo específico do módulo consumidor>
→ 200 { "active": true, "activated_at": "..." }
→ 404 { "active": false }
```

- Cada módulo consumidor recebe seu próprio `X-Module-Key` (rotacionável, com um por ambiente).
- Endpoint é read-only, sem PII do cliente.

---

## 5. Ameaças e mitigações

| Ameaça                                                                 | Mitigação contratual                                                                                              |
|------------------------------------------------------------------------|-------------------------------------------------------------------------------------------------------------------|
| Usuário edita a querystring para trocar `restaurant_id`                | `restaurant_id` só é lido do JWT assinado; querystring extra é ignorada.                                          |
| Usuário edita `role` ou `module` no localStorage/frontend do Módulo    | Módulo lê essas claims exclusivamente do JWT verificado no backend, nunca do body/query/localStorage.             |
| Replay do link de handoff (compartilhado / salvo / logado em referer)  | `exp = 60s`, single-use por `jti` cache, `history.replaceState` remove da URL após consumir.                      |
| Token roubado via CDN/proxy que loga URLs                              | `exp = 60s` limita a janela; endpoint de exchange é POST no backend do Módulo (jamais GET com JWT em URL).        |
| Módulo de Pedidos comprometido                                         | RS256 (fase 2) — atacante não consegue forjar handoffs. Em HS256, rotação de segredo revoga em minutos.           |
| Admin do Hub gera handoff para tenant que não deveria acessar          | `POST /launch-token` valida sessão do hub_user + RBAC dele + confere `tenant_modules.active === true`.            |
| Módulo continua permitindo acesso após desativação do módulo no Hub    | Step 5 do fluxo (verificação de ativação atual) + sessão emitida com `exp` curto (ex.: 8h) para forçar re-check.  |
| Confusão entre roles do Hub (super_admin/admin) e do Módulo (waiter…)  | Claim `role` do handoff carrega **role operacional**, não o do Hub. `sub` guarda o admin do Hub como auditoria.    |

---

## 6. Ciclo de vida do handoff

```
[Hub UI]                     [Hub API]                      [Orders API]              [Orders UI]
    │  clica "Abrir Pedidos"    │                              │                            │
    ├──────────────────────────▶│ POST /launch-token           │                            │
    │                           │ (valida hub_user + ativo)    │                            │
    │◀── { handoff: <JWT 60s> } │                              │                            │
    │  window.open(              │                              │                            │
    │   ".../{slug}?handoff=X")─┼─────────────────────────────▶│  navegação inicial         │
    │                           │                              │  frontend chama            │
    │                           │                              │  POST /session/exchange    │
    │                           │                              │  { handoff: X }            │
    │                           │           (verify sig,       │                            │
    │                           │            valida claims,    │                            │
    │                           │            anti-replay,      │                            │
    │                           │            GET status ↓)     │                            │
    │                           │◀─────────────────────────────┤                            │
    │  200 { active: true }     │                              │                            │
    │                           │─────────────────────────────▶│                            │
    │                           │                              │  cria/vincula usuário,     │
    │                           │                              │  emite cookies próprios,   │
    │                           │                              │  redireciona ────────────▶│
    │                           │                              │                            │
```

### 6.1 Expiração

- Handoff: 60 s (máximo 90 s aceito pelo Módulo).
- Sessão do Módulo (após exchange): controlada pelo próprio Módulo (recomendado ≤ 8 h, refresh próprio).
- **O Hub não gerencia sessão do Módulo** — apenas emite o handoff inicial.

### 6.2 Reutilização

- Um `jti` só pode ser consumido uma vez. Segunda tentativa → 401 no exchange.
- Se o operador abrir múltiplas abas rapidamente e o front chamar `/session/exchange` em ambas, apenas a primeira sucede. A segunda deve mostrar mensagem "sessão já iniciada; use a aba anterior" e não tentar re-emitir do Hub.

### 6.3 Logout

- Logout no Módulo de Pedidos é problema do próprio Módulo (limpa cookies dele).
- Logout no Hub não desloga o Módulo (sessões independentes por design).
- Se o admin DACOT for **desabilitado** no Hub, ele não conseguirá gerar novos handoffs, mas sessões já emitidas no Módulo continuam válidas até expirarem. Para revogação imediata, o Módulo pode oferecer um endpoint de "kill session" que o Hub aciona, mas isso está **fora do escopo do MVP** do handoff.
- Se o módulo for **desativado** no Hub para um tenant, novas sessões falharão no step 5, mas sessões já emitidas continuam até expirarem. Recomendação: sessão do Módulo revalida `active` a cada refresh de token.

---

## 7. Checklist de compatibilidade

Para o time do Módulo de Pedidos validar contra o próprio código:

- [ ] Módulo aceita `POST /api/orders/session/exchange` (ou equivalente) com body `{"handoff": "<jwt>"}`.
- [ ] Verificação de assinatura HS256 com segredo compartilhado ou RS256 via JWKS.
- [ ] Validação estrita de `iss`, `aud`, `module`, `exp`, `nbf`, `handoff_version`.
- [ ] Cache anti-replay por `jti` (Redis, MongoDB ou memória por instância + TTL).
- [ ] Chamada ao endpoint `GET /api/public/tenants/{id}/modules/orders/status` do Hub antes de emitir sessão.
- [ ] Mapeamento `role` do handoff → role operacional do Módulo, sem confiar em roles do frontend.
- [ ] Frontend do Módulo remove `?handoff=` da URL logo após o POST.
- [ ] Nenhuma rota do Módulo aceita `restaurant_id` via querystring ou body como fonte de autorização.

---

## 8. O que **NÃO** está neste contrato (e será tratado depois)

- Provisionamento inicial do primeiro usuário operacional (owner) — hoje o Hub tem `tenants.owner_name` mas não cria conta no Módulo. Uma opção é o próprio handoff (com `role: admin`) fazer isso na primeira vez.
- Sincronização bidirecional (Módulo → Hub) de estatísticas de uso (contagem de pedidos, MRR).
- Webhooks do Módulo notificando o Hub sobre eventos.
- Modo "impersonation" completo (admin DACOT operando como um usuário real do restaurante para suporte).

Cada um desses itens vira contrato próprio quando priorizado.

---

## 9. Ações do usuário (você)

1. Compartilhar este documento com o time/repo do Módulo de Pedidos.
2. Confirmar que os claims 4.4 são compatíveis com o JWT interno do Módulo (nomes, tipos).
3. Confirmar RBAC: as roles `admin | manager | waiter | kitchen` são exatamente as usadas hoje?
4. Decidir HS256 (mais rápido) vs RS256 (mais seguro) para a primeira versão.
5. Confirmar hostname público final do Módulo (`https://pedidos.dacot.app/{slug}` é apenas o placeholder atual).
6. Após aprovação deste contrato, implemento no Hub:
   - Endpoint `POST /api/hub/tenants/{id}/modules/orders/launch-token`.
   - Endpoint `GET /api/public/tenants/{id}/modules/{key}/status` (com `X-Module-Key`).
   - Ajuste do botão "Abrir módulo" no frontend para consultar o launch-token e abrir `?handoff=<jwt>`.

Nenhuma dessas alterações foi feita ainda — este documento é somente contrato para revisão cruzada.
