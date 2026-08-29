# DACOT — Handoff Integration: Variáveis para o Módulo de Pedidos

Documento operacional. Descreve **apenas as variáveis de ambiente e endpoints** que o backend do
Módulo de Pedidos precisa para validar tokens de handoff emitidos pelo DACOT Hub.
**Nenhuma alteração deste contrato deve ser feita no frontend** — todo processamento do
handoff ocorre no backend do Módulo.

---

## 1. Variáveis obrigatórias no `.env` do backend do Módulo de Pedidos

| Variável                 | Fonte                                                 | Descrição                                                                                       |
|--------------------------|-------------------------------------------------------|-------------------------------------------------------------------------------------------------|
| `HANDOFF_JWT_SECRET`     | **Mesmo valor** do `HANDOFF_JWT_SECRET` do Hub        | Segredo HS256 usado para verificar a assinatura do JWT de handoff. **Nunca no frontend.**       |
| `HANDOFF_ISSUER`         | Fixo: `dacot-hub`                                     | Valor esperado do claim `iss`. Rejeitar se diferente.                                           |
| `HANDOFF_AUDIENCE`       | Fixo: `dacot-orders`                                  | Valor esperado do claim `aud`. Rejeitar se diferente.                                           |
| `HANDOFF_MAX_AGE_SECONDS`| `90`                                                  | Tolerância máxima de `exp - iat`. Rejeitar tokens que declarem TTL maior que este valor.        |
| `HANDOFF_VERSIONS`       | `1` (CSV se houver mais de um)                        | Versões de `handoff_version` aceitas. Permite evolução sem quebrar produção.                    |
| `HUB_BASE_URL`           | URL pública do Hub (`https://hub.dacot.app`)          | Base para chamada de revalidação de ativação.                                                   |
| `HUB_MODULE_KEY`         | **Mesmo valor** do `ORDERS_MODULE_KEY` do Hub         | Enviada no header `X-Module-Key` para o endpoint público de status.                             |

**Valores atualmente configurados no Hub (ambiente de preview):**
```
HANDOFF_JWT_SECRET=e2d4a8b5c9f3a1d7e6b8c2f4a5d9e1b3c7f8a2d4e6b1c9f5a3d7e2b8c4f1a6d5
HANDOFF_ISSUER=dacot-hub
ORDERS_MODULE_KEY=9f3a2b5c8d1e4f7a2b5c8d1e4f7a2b5c
```
Estes valores devem ser trocados por segredos aleatórios em produção e sincronizados nos dois
backends. Ambos devem estar em `.env`, nunca em git, nunca no frontend.

---

## 2. Endpoints expostos pelo Hub para o Módulo consumir

### 2.1 `GET /api/public/tenants/{tenant_id}/modules/{module_key}/status`

- **Auth**: header `X-Module-Key: <HUB_MODULE_KEY>`.
- **Path params**:
  - `tenant_id`: string 24-hex (`tenants._id` do Hub).
  - `module_key`: `"orders"`.
- **Respostas**:
  - `200 { "active": true,  "module": "orders", "activated_at": "..." }`
  - `200 { "active": false }` — módulo cadastrado mas não ativo para o tenant.
  - `401` — chave ausente/errada.
  - `404` — tenant, módulo ou id inválido.

O Módulo **DEVE** chamar este endpoint antes de emitir a sessão local, e a cada refresh dela.

---

## 3. Formato do JWT de handoff (assinatura HS256)

```json
{
  "iss": "dacot-hub",
  "aud": "dacot-orders",
  "sub": "hub_user:<hub_users._id>",
  "restaurant_id": "<tenants._id, 24-hex>",
  "restaurant_slug": "<slug>",
  "role": "admin | manager | waiter | kitchen",
  "module": "orders",
  "jti": "<string única>",
  "iat": <unix seconds>,
  "nbf": <iat - 5>,
  "exp": <iat + 60>,
  "handoff_version": 1
}
```

### 3.1 Validações mínimas obrigatórias no Módulo (backend)

Nesta ordem exata:

1. Decodificar com `HANDOFF_JWT_SECRET` (HS256). Falha → 401.
2. `iss === "dacot-hub"`.
3. `aud === "dacot-orders"`.
4. `module === "orders"`.
5. `handoff_version ∈ HANDOFF_VERSIONS`.
6. `now < exp` e `now >= nbf`.
7. `exp - iat <= HANDOFF_MAX_AGE_SECONDS` (90 s).
8. `role ∈ {admin, manager, waiter, kitchen}`.
9. `restaurant_id` é string de 24 caracteres hex válida.
10. **Anti-replay**: consultar cache de `jti` consumidos (Redis/Mongo/memória). Se existir → 401. Caso contrário, inserir com TTL de `exp - now + 60s`.
11. Chamar `GET {HUB_BASE_URL}/api/public/tenants/{restaurant_id}/modules/orders/status` com `X-Module-Key: HUB_MODULE_KEY`. Se resposta não for `{active: true}` → 403.
12. Só então: emitir a sessão própria do Módulo (o JWT interno que ele já usa).

### 3.2 O que **NÃO** pode ser feito

- Ler `restaurant_id`, `role` ou `module` de querystring, body ou headers do cliente.
- Confiar em qualquer campo enviado pelo frontend do Módulo antes da verificação do JWT.
- Aceitar `handoff` via GET com query — o exchange deve ser `POST` no backend do Módulo.
- Reenviar o `handoff` para o frontend depois do consumo.

### 3.3 Fluxo esperado no frontend do Módulo (apenas transporte)

1. Recebe navegação com `?handoff=<jwt>`.
2. Envia `POST /api/orders/session/exchange` (nome sugerido) com `{ "handoff": "<jwt>" }`.
3. Remove o parâmetro da URL via `window.history.replaceState`.
4. O backend responde com cookies httpOnly próprios do Módulo — nenhum JWT do handoff é armazenado no cliente.

---

## 4. Endpoint do Hub que emite o token (referência)

Chamado **apenas pelo próprio Hub** quando o admin clica em "Abrir módulo".

- `POST /api/hub/tenants/{tenant_id}/modules/orders/launch-token`
- Requer sessão de `hub_user` (cookie httpOnly) com role `super_admin` ou `admin`.
- Retorna: `{ handoff, launch_url, expires_in: 60, expires_at, jti }`
- `launch_url` já vem resolvido (override do tenant → template do catálogo).
- Sem entrada autoritativa do frontend: `restaurant_id`, `role` e `module` vêm sempre do servidor.
- Token duração fixa **60 segundos**, single-use por `jti`.

O Módulo de Pedidos **não deve** chamar este endpoint — apenas o frontend autenticado do Hub o faz.

---

## 5. Checklist de compatibilidade para o time do Módulo

- [ ] `.env` recebeu `HANDOFF_JWT_SECRET`, `HANDOFF_ISSUER`, `HANDOFF_AUDIENCE`, `HANDOFF_MAX_AGE_SECONDS`, `HANDOFF_VERSIONS`, `HUB_BASE_URL`, `HUB_MODULE_KEY`.
- [ ] Nenhuma dessas variáveis é referenciada no frontend do Módulo (grep em `src/`).
- [ ] Rota `POST /api/orders/session/exchange` implementada.
- [ ] Verificação de assinatura HS256 com PyJWT (ou lib equivalente): `jwt.decode(token, secret, algorithms=["HS256"], audience="dacot-orders", issuer="dacot-hub")`.
- [ ] Cache anti-replay por `jti` funcional.
- [ ] Chamada bloqueante ao `/api/public/tenants/{id}/modules/orders/status` antes de emitir sessão.
- [ ] `role` do handoff mapeada para role operacional do Módulo (sem sobrescrever role local existente, exceto `admin`).
- [ ] Frontend chama exchange e faz `history.replaceState` para limpar `?handoff=`.
