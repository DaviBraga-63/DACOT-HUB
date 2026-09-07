# Hub → Módulo de Pedidos: Contrato de Handoff

**Versão**: 1.0  
**Data**: 2026-09-01  
**Status**: Ativo em produção  
**Escopo**: Autenticação e integração entre **DACOT Hub** (painel administrativo multi-tenant) e **Módulo de Pedidos** (aplicação operacional)

---

## 1. Visão Geral

### 1.1 Objetivo

Quando um usuário autenticado no Hub clica em **"Abrir módulo → Pedidos"**, o Hub gera um **token temporário assinado (handoff)** que:

1. Prova a identidade e role do usuário
2. Prova que o restaurante/tenant está ativo
3. Prova que o Módulo está ativo para aquele tenant
4. Possui validade curta (60 segundos) para evitar reutilização

### 1.2 Fluxo esperado

```
1. Usuário autenticado no Hub (cookie JWT)
2. Seleciona restaurante
3. Clica "Abrir módulo → Pedidos"
4. Hub gera handoff (POST /api/hub/tenants/{id}/modules/orders/launch-token)
5. Hub redireciona para:
   https://pedidos.dacot.app/{restaurant_slug}?handoff={JWT}
6. Módulo recebe a URL
7. Módulo extrai o handoff da query
8. Módulo envia POST /api/orders/session/exchange com { "handoff": "<jwt>" }
9. Módulo valida o JWT
10. Módulo cria/recupera sessão local
11. Módulo redireciona para sessão autenticada (remover token da URL)
12. Usuário entra no módulo sem segundo login
```

---

## 2. Origem do Handoff (Lado Hub)

### 2.1 Endpoint de geração

O Hub oferece **dois endpoints** para gerar handoff:

#### Para Admin do Hub (acesso via `/api/hub/...`)
```
POST /api/hub/tenants/{tenant_id}/modules/{module_key}/launch-token
Content-Type: application/json
Authorization: Cookie (JWT de admin do Hub)

Response (200):
{
  "handoff": "<JWT assinado>",
  "launch_url": "https://pedidos.dacot.app/restaurant-slug",
  "expires_in": 60,
  "expires_at": "2026-09-01T12:00:00+00:00",
  "jti": "<string única>"
}
```

#### Para Usuário do Restaurante (acesso via `/api/portal/...`)
```
POST /api/portal/modules/{module_key}/launch-token
Content-Type: application/json
Authorization: Cookie (JWT de usuário do restaurante)

Response (200):
{
  "handoff": "<JWT assinado>",
  "launch_url": "https://pedidos.dacot.app/restaurant-slug",
  "expires_in": 60,
  "expires_at": "2026-09-01T12:00:00+00:00",
  "jti": "<string única>"
}
```

### 2.2 URL de abertura

O Hub monta a URL assim:

```javascript
// Frontend do Hub (Portal.jsx, ClienteDetalhes.jsx)
const sep = launch_url.includes("?") ? "&" : "?";
const finalUrl = `${launch_url}${sep}handoff=${encodeURIComponent(handoff)}`;
window.open(finalUrl, "_blank", "noopener,noreferrer");

// Exemplo de URL final:
// https://pedidos.dacot.app/padaria-grao-dourado?handoff=eyJhbGc...
```

### 2.3 Segurança (lado Hub)

- ✅ **Autenticação obrigatória**: Apenas usuários logados (admin ou restaurante) geram handoff
- ✅ **Tenant derivado do servidor**: `restaurant_id` vem da identidade do usuário, **nunca** do body da requisição
- ✅ **Role derivada do servidor**: A role vem da identidade do usuário
  - Para admin do Hub: sempre `"admin"`
  - Para usuário do restaurante: role operacional do usuário (`admin`, `manager`, `waiter`, `kitchen`)
- ✅ **Validação de ativação**: Módulo deve estar `active: true` em `tenant_modules`
- ✅ **Segredo não exposto**: `HANDOFF_JWT_SECRET` nunca aparece no corpo da resposta
- ✅ **JTI único**: Cada chamada gera um `jti` diferente
- ✅ **TTL curto**: 60 segundos
- ✅ **Log de auditoria**: Evento `module.launch_token_issued` registrado

---

## 3. Formato do JWT de Handoff

### 3.1 Estrutura (três partes separadas por `.`)

```
eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.{payload_base64url}.{signature_base64url}
```

### 3.2 Payload (decodificado)

```json
{
  "iss": "dacot-hub",
  "aud": "dacot-orders",
  "sub": "hub_user:507f1f77bcf86cd799439001",
  "restaurant_id": "507f1f77bcf86cd799439010",
  "restaurant_slug": "padaria-grao-dourado",
  "role": "admin",
  "module": "orders",
  "jti": "9B5zX-9f2k_L4mN3pQ7rS8tU",
  "iat": 1725177600,
  "nbf": 1725177595,
  "exp": 1725177660,
  "handoff_version": 1
}
```

### 3.3 Assinatura

- **Algoritmo**: HS256 (HMAC com SHA-256)
- **Segredo**: `HANDOFF_JWT_SECRET` (compartilhado entre Hub e Módulo)
- **Tamanho do segredo**: Mínimo 32 bytes (recomendado 64 caracteres hexadecimais)

---

## 4. Claims e Validações

### 4.1 Claims obrigatórios

| Claim | Tipo | Significado | Validação |
|-------|------|-------------|-----------|
| `iss` | string | Emissor do token | Deve ser `"dacot-hub"` |
| `aud` | string | Destinatário do token | Deve ser `"dacot-orders"` |
| `sub` | string | Sujeito (quem iniciou) | Formato `"hub_user:<id>"` ou `"tenant_user:<id>"` |
| `restaurant_id` | string | ID do restaurante/tenant | 24 caracteres hexadecimais (MongoDB ObjectId) |
| `restaurant_slug` | string | Slug do restaurante | Usado para URL, **não** para autenticação |
| `role` | string | Role operacional do usuário | Deve estar em `["admin", "manager", "waiter", "kitchen"]` |
| `module` | string | Módulo solicitado | Deve ser `"orders"` |
| `jti` | string | JWT ID único | Usado para anti-replay |
| `iat` | número (unix) | Issued At — quando foi criado | |
| `nbf` | número (unix) | Not Before — antes disso, não é válido | Geralmente `iat - 5` (5s de tolerância) |
| `exp` | número (unix) | Expiração | Geralmente `iat + 60` (60 segundos de validade) |
| `handoff_version` | número | Versão do contrato | Deve ser `1` (permite evolução futura) |

### 4.2 Processo de validação (ordem importante)

Execute **nesta ordem exata**:

1. **Decodificar JWT**
   ```python
   try:
       claims = jwt.decode(
           token,
           HANDOFF_JWT_SECRET,
           algorithms=["HS256"],
           audience="dacot-orders",
           issuer="dacot-hub"
       )
   except jwt.InvalidSignatureError:
       return 401  # Assinatura inválida
   except jwt.InvalidTokenError as e:
       return 401  # Token malformado, expirado, etc
   ```

2. **Validar claims essenciais**
   ```python
   if claims.get("module") != "orders":
       return 401  # Módulo errado
   
   if claims.get("handoff_version") not in [1]:
       return 401  # Versão desconhecida
   
   if claims.get("role") not in ["admin", "manager", "waiter", "kitchen"]:
       return 401  # Role inválida
   ```

3. **Validar TTL**
   ```python
   import time
   now = int(time.time())
   
   if now < claims["nbf"]:
       return 401  # Token ainda não é válido
   
   if now >= claims["exp"]:
       return 401  # Token expirado
   
   if claims["exp"] - claims["iat"] > 90:
       return 401  # TTL maior que o permitido (90s max)
   ```

4. **Validar restaurant_id**
   ```python
   rest_id = claims.get("restaurant_id", "")
   if not re.match(r"^[a-f0-9]{24}$", rest_id):
       return 401  # Not a valid MongoDB ObjectId
   ```

5. **Anti-replay (cache de JTI)**
   ```python
   jti = claims.get("jti")
   cache_key = f"handoff_used:{jti}"
   
   if redis.exists(cache_key):
       return 401  # JTI já foi utilizado
   
   ttl = claims["exp"] - now + 60  # TTL do cache = até 60s após expiração
   redis.setex(cache_key, ttl, "1")
   ```

6. **Validar ativação do módulo**
   ```python
   # Chamada backend → backend (NUNCA deixe o cliente fazer isso)
   response = httpx.get(
       f"{HUB_BASE_URL}/api/public/tenants/{rest_id}/modules/orders/status",
       headers={"X-Module-Key": HUB_MODULE_KEY},
       timeout=5
   )
   
   if response.status_code != 200:
       return 403  # Módulo não disponível ou tenant inativo
   
   status_data = response.json()
   if not status_data.get("active"):
       return 403  # Módulo não está ativo para este tenant
   ```

7. **Só então: criar sessão local**
   ```python
   # Agora está validado. Crie sua sessão local.
   # O token do handoff NÃO deve ser armazenado no cliente.
   # Você emite seus próprios cookies/tokens internos.
   
   user_id = claims["sub"]  # hub_user:... ou tenant_user:...
   user_email = ...  # Descobrir no seu banco
   restaurant_id = claims["restaurant_id"]
   role = claims["role"]
   
   # Criar JWT/session próprio do Módulo
   local_token = create_local_session(
       user_id, user_email, restaurant_id, role
   )
   
   return {
       "session_token": local_token,  # Seu próprio JWT
       "user": { "id": user_id, "role": role },
       "restaurant": { "id": restaurant_id, "slug": claims["restaurant_slug"] }
   }
   ```

---

## 5. Configuração do Módulo de Pedidos

### 5.1 Variáveis de ambiente obrigatórias

Adicionar ao `.env` do backend do Módulo:

```bash
# Validação do handoff
HANDOFF_JWT_SECRET=e2d4a8b5c9f3a1d7e6b8c2f4a5d9e1b3c7f8a2d4e6b1c9f5a3d7e2b8c4f1a6d5
HANDOFF_ISSUER=dacot-hub
HANDOFF_AUDIENCE=dacot-orders
HANDOFF_MAX_AGE_SECONDS=90
HANDOFF_VERSIONS=1

# Revalidação com o Hub
HUB_BASE_URL=https://hub.dacot.app
HUB_MODULE_KEY=9f3a2b5c8d1e4f7a2b5c8d1e4f7a2b5c

# Cache de JTI (anti-replay)
# Se usar Redis:
REDIS_URL=redis://localhost:6379/0
# Se usar Mongo ou memória:
JTI_CACHE_TTL=120
```

### 5.2 Configuração inicial

**Importante**: `HANDOFF_JWT_SECRET` deve ser **exatamente o mesmo** no Hub e no Módulo. Não é um segredo público — nunca o commit em git, nunca o exponha no frontend.

---

## 6. Endpoint do Módulo para Receber Handoff

### 6.1 Contrato esperado

O Módulo deve expor um endpoint que o frontend chame **imediatamente** após receber a URL:

```
POST /api/orders/session/exchange
Content-Type: application/json

Request body:
{
  "handoff": "<JWT_base64_tres_partes>"
}

Response (200 OK):
{
  "ok": true,
  "session_token": "<JWT_interno_do_modulo>",
  "user": {
    "id": "tenant_user:507f1f77bcf86cd799439001",
    "email": "operador@padaria.com",
    "role": "admin"
  },
  "restaurant": {
    "id": "507f1f77bcf86cd799439010",
    "slug": "padaria-grao-dourado"
  }
}

Error responses:
401 Unauthorized — handoff inválido, expirado, etc
403 Forbidden — restaurante inativo, módulo não autorizado
400 Bad Request — body malformado
500 Internal Server Error — erro no backend do módulo
```

### 6.2 Fluxo no frontend do Módulo

```javascript
// 1. Página de entrada (_app.js, router, etc)
useEffect(() => {
  const searchParams = new URLSearchParams(window.location.search);
  const handoff = searchParams.get("handoff");
  
  if (!handoff) {
    // Não há handoff — usuário entrou direto
    // Se já autenticado (cookie), continua
    // Se não, redireciona para login
    return;
  }

  // 2. Enviar handoff para backend (NUNCA decodifique no frontend)
  fetch("/api/orders/session/exchange", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ handoff }),
    credentials: "include"  // Enviar cookies httpOnly
  })
    .then(r => {
      if (r.status === 200) {
        // 3. Remover token da URL
        window.history.replaceState({}, "", window.location.pathname);
        
        // 4. Sessão está criada (cookies httpOnly)
        // Redirecionar para dashboard ou página inicial
        window.location.href = "/dashboard";
      } else {
        // Handoff inválido — redirecionar para login ou erro
        window.location.href = "/login?error=invalid_handoff";
      }
    })
    .catch(err => {
      console.error("Exchange failed:", err);
      window.location.href = "/login?error=server_error";
    });
}, []);
```

---

## 7. Tratamento de Erros

### 7.1 Cenários de rejeição (401 Unauthorized)

| Cenário | Causa | Resposta |
|---------|-------|----------|
| Handoff não enviado | Parâmetro `handoff` faltando | 400 Bad Request |
| Handoff malformado | Não possui 3 partes separadas por `.` | 401 Unauthorized |
| Assinatura inválida | `HANDOFF_JWT_SECRET` diferente ou token adulterado | 401 Unauthorized |
| Issuer errado | `iss ≠ "dacot-hub"` | 401 Unauthorized |
| Audience errado | `aud ≠ "dacot-orders"` | 401 Unauthorized |
| Module errado | `module ≠ "orders"` | 401 Unauthorized |
| Role inválida | `role` não está em lista permitida | 401 Unauthorized |
| Token expirado | `now >= exp` | 401 Unauthorized |
| Token ainda não válido | `now < nbf` | 401 Unauthorized |
| TTL muito longo | `exp - iat > 90` | 401 Unauthorized |
| JTI já consumido | Token já foi usado antes | 401 Unauthorized (ou 403) |
| restaurant_id inválido | Não é um ObjectId MongoDB válido | 401 Unauthorized |

### 7.2 Cenários de rejeição (403 Forbidden)

| Cenário | Causa | Resposta |
|---------|-------|----------|
| Restaurante inativo | Hub retorna `active: false` | 403 Forbidden |
| Módulo não ativo | Módulo não está ativado para este tenant no Hub | 403 Forbidden |
| Módulo não comunicável | Falha ao chamar `/api/public/tenants/{id}/modules/orders/status` | 503 Service Unavailable (ou 403) |

### 7.3 Tratamento de erro no cliente (frontend)

```javascript
// Não confunda "credenciais inválidas" com "restaurante inativo"

if (response.status === 401) {
  // Mostrar: "Token inválido. Tente abrir o módulo novamente no Hub."
  toast.error("Sessão expirou. Volte ao Hub e tente novamente.");
} else if (response.status === 403) {
  // Mostrar: "Restaurante inativo ou módulo não autorizado"
  toast.error("Este restaurante não tem acesso ao módulo. Fale com a equipe.");
} else if (response.status >= 500) {
  // Servidor indisponível
  toast.error("Serviço indisponível. Tente mais tarde.");
}

// Redirecionar para login (não tente auto-recuperar)
setTimeout(() => window.location.href = "/login", 2000);
```

---

## 8. Características de Segurança

### 8.1 Proteções implementadas

✅ **Assinatura HS256**: Impossível forjar handoff sem o segredo  
✅ **Audience específica**: Token destinado apenas ao Módulo de Pedidos  
✅ **Issuer validado**: Garante origem do Hub  
✅ **TTL curto**: 60 segundos, reverte rapidamente  
✅ **JTI único**: Cada chamada gera novo identificador (anti-replay)  
✅ **Role servidor-derivada**: Cliente não consegue alterar sua role  
✅ **Restaurant ID servidor-derivado**: Cliente não consegue acessar outro restaurante  
✅ **Validação de ativação**: Confirma que módulo/restaurante estão ativos  
✅ **Log de auditoria**: Rastreabilidade de quem gerou o handoff  
✅ **Secreto nunca exposto**: `HANDOFF_JWT_SECRET` nunca aparece no bundle JS

### 8.2 O que NÃO é segurança

❌ **Restaurant slug na URL**: `/padaria-grao-dourado` é apenas roteamento, **não** autenticação  
❌ **Headers customizados**: Client-side, podem ser falsificados  
❌ **IP do cliente**: Roteável/falsificável  
❌ **User-Agent**: Roteável/falsificável  
❌ **Referrer**: Pode ser bloqueado pelo cliente  

---

## 9. Fluxo Completo (Exemplo)

### 9.1 Admin do Hub abre Pedidos para a Padaria Grão Dourado

```bash
# 1. Hub valida autenticação do admin
# Verificar: user.user_type === "staff" && user.role in ["super_admin", "admin"]

# 2. Hub valida tenant
# Verificar: tenants._id === "507f1f77bcf86cd799439010"

# 3. Hub valida módulo
# Verificar: modules.key === "orders" && status === "available"

# 4. Hub valida ativação
# Verificar: tenant_modules.tenant_id === "507f1f77bcf86cd799439010" 
#           && tenant_modules.module_key === "orders" 
#           && tenant_modules.active === true

# 5. Hub gera handoff
POST /api/hub/tenants/507f1f77bcf86cd799439010/modules/orders/launch-token
→ Response:
{
  "handoff": "eyJhbGci...",
  "launch_url": "https://pedidos.dacot.app/padaria-grao-dourado",
  "expires_in": 60
}

# 6. Hub abre em nova aba
window.open("https://pedidos.dacot.app/padaria-grao-dourado?handoff=eyJhbGci...", "_blank")

# 7. Módulo recebe requisição GET /padaria-grao-dourado?handoff=eyJhbGci...

# 8. Frontend do Módulo envia POST /api/orders/session/exchange
POST /api/orders/session/exchange
{
  "handoff": "eyJhbGci..."
}

# 9. Backend do Módulo:
#    - Decodifica com HANDOFF_JWT_SECRET
#    - Valida claims (iss, aud, exp, nbf, etc)
#    - Chama GET /api/public/tenants/507f1f77bcf86cd799439010/modules/orders/status
#    - Cria sessão local
#    - Responde 200

# 10. Frontend remove token da URL
window.history.replaceState({}, "", "/padaria-grao-dourado")

# 11. Usuário entrou no módulo sem segundo login ✅
```

---

## 10. Troubleshooting

### 10.1 "Invalid signature"

**Causa**: `HANDOFF_JWT_SECRET` diferente no Hub e Módulo  
**Solução**: Verificar que ambos têm exatamente o mesmo valor no `.env`

### 10.2 "Token expired"

**Causa**: Mais de 60 segundos entre abertura do Hub e consumo no Módulo  
**Solução**: Comportamento esperado — pedir para o usuário tentar novamente

### 10.3 "Module not active"

**Causa**: Módulo desativado no Hub para este restaurante  
**Solução**: Verificar em Hub Admin → Clientes → {Restaurante} → Módulos → Ativar "Pedidos"

### 10.4 "JTI already used"

**Causa**: Handoff foi consumido duas vezes (replay attack)  
**Solução**: Rejeitar com 401. Cache impede reutilização.

### 10.5 "Hub unreachable"

**Causa**: `/api/public/tenants/{id}/modules/orders/status` não responde  
**Solução**: 
- Verificar conectividade de rede
- Verificar `HUB_BASE_URL` está correto
- Verificar `HUB_MODULE_KEY` está correto
- Retornar 503 ou aguardar retry

---

## 11. Roadmap Futuro

| Versão | Mudança |
|--------|---------|
| 1.0 | HS256 com segredo compartilhado (atual) |
| 2.0 | RS256 com JWKS público (maior segurança, complexidade) |
| 3.0 | OAuth2/OpenID Connect (SE aplicável) |

Versão `handoff_version` permite evolução sem quebrar produção — Módulo pode rejeitar versões desconhecidas.

---

## 12. Referências

- **Hub código**: `/app/backend/server.py` linhas 680-735 (endpoint launch-token)
- **Hub testes**: `/app/backend/tests/backend_test.py` (TestLaunchToken)
- **Frontend Hub**: `/app/frontend/src/pages/Portal.jsx` e `ClienteDetalhes.jsx` (botão "Abrir módulo")
- **Contrato original**: `/app/DACOT_Module_Integration_Contract.md`
- **Env vars**: `/app/DACOT_Handoff_Env_Vars.md`

---

## 13. Contato & Suporte

**Projeto**: DACOT Hub  
**Maintainer**: Tim Cobot (Backend)  
**Última atualização**: 2026-09-01  

Para dúvidas sobre o handoff, consulte:
1. Este documento
2. Testes em `/app/backend/tests/backend_test.py`
3. Código-fonte em `/app/backend/server.py`
