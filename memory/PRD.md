# DACOT Hub — PRD

## Problem Statement (original — pt-BR, resumido)
Construir o **DACOT Hub**, painel administrativo central da DACOT (SaaS de gestão para
restaurantes composto por módulos independentes — Pedidos, Cozinha, etc.). O Hub é usado
pela **equipe interna da DACOT** para gerenciar restaurantes clientes (tenants), status,
usuários visíveis e — o coração do produto — **quais módulos DACOT estão ativos para cada
restaurante**. Deve ser multi-tenant, extensível a novos módulos sem refactor, e deve
preparar o handoff (botão "Abrir módulo") para o Módulo de Pedidos que existe em outro projeto.

## User Personas
- **Admin DACOT** (equipe interna): gerencia clientes, ativa/desativa módulos, monitora atividade.
- **Restaurante (tenant)**: apenas representado no Hub — os usuários operacionais reais consomem
  os módulos operacionais (Pedidos, Cozinha, …), fora do Hub.

## Arquitetura entregue
- **Backend**: FastAPI + Motor (MongoDB), JWT em cookies httpOnly (samesite=none, secure).
- **Frontend**: React 19 + React Router + Tailwind + shadcn/ui + Sonner + Lucide.
- **Coleções**: `hub_users`, `tenants`, `modules`, `tenant_modules` (N:M ativação),
  `tenant_users`, `activity_log`, `login_attempts`, `password_reset_tokens`, `password_reset_requests`.
- **Design**: Swiss Brutalist B2B — Cabinet Grotesk + Satoshi, off-white #F9F9F6, acento terracotta #D95D39.

## Implementado (28/02/2026)
- Auth completo: login, logout, /me, refresh, forgot/reset password (rate-limit + tokens hashados + TTL).
- Seed admin real do usuário + 6 módulos + 5 restaurantes fictícios com ativações e usuários.
- Dashboard: KPIs (Ativos / Em teste / Total / Módulos ativos), utilização por módulo, atividade recente.
- Clientes: lista com filtros por status, busca, contagem de módulos ativos/usuários, criação, edição inline de status, exclusão.
- Detalhes do cliente: abas Visão geral, Módulos (toggle + botão Abrir módulo com URL editável), Usuários.
- Catálogo de Módulos: 6 cards com status Disponível / Em desenvolvimento / Planejado.
- Módulos in_development/planned bloqueados para ativação (backend valida 400).
- Logging automático de todas as ações no activity_log.
- Testes: backend 100% + frontend 100% (iteration_1.json).

## Implementado (28/02/2026 — Integração Handoff Hub ↔ Módulo de Pedidos)
- Contrato técnico: `/app/DACOT_Module_Integration_Contract.md` + doc de env vars `/app/DACOT_Handoff_Env_Vars.md`.
- `POST /api/hub/tenants/{tid}/modules/{mkey}/launch-token`: JWT HS256 (60s, single-use por jti) com claims iss/aud/sub/restaurant_id/restaurant_slug/role/module/jti/iat/exp/nbf/handoff_version. Só super_admin/admin. Valida tenant, módulo no catálogo e ativação ativa. Nenhum dado do body é autoridade (restaurant_id/role/module sempre derivados no servidor; body ignorado).
- `GET /api/public/tenants/{tid}/modules/{mkey}/status`: autenticado por `X-Module-Key` (chave por módulo, compare_digest); valida existência (404) antes da chave (401); resposta consistente `{active, module, activated_at?}`; somente leitura, sem dados administrativos.
- Botão "Abrir módulo" agora solicita launch-token ao backend e abre `launch_url?handoff=<jwt>` em nova aba; JWT nunca gerado no frontend (segredo ausente do bundle — verificado).
- Env vars novas: `HANDOFF_JWT_SECRET`, `HANDOFF_ISSUER`, `ORDERS_MODULE_KEY`, `KITCHEN_MODULE_KEY` (apenas backend).
- Testes: backend 22/22 pytest + frontend E2E (iteration_2.json).

## Bugfix (29/08/2026 — 401 repetidos no frontend)
- Causa: access_token JWT expira em 60 min e o frontend nunca chamava `/api/auth/refresh`; após expiração, todas as chamadas autenticadas retornavam 401 "Token expirado" (diagnóstico documentado na conversa — backend e contrato intactos).
- Correção mínima em `/app/frontend/src/lib/api.js`: interceptor axios com refresh single-flight (1 chamada compartilhada por 401s concorrentes), flag `_retried` anti-loop, exclusão das rotas de auth (login/logout/refresh/forgot/reset/me — `/me` tratado como probe), repetição da requisição original após refresh, redirect full-page para `/login` se o refresh falhar. TTL de 60 min mantido por decisão do usuário.
- Testes: 31/31 pytest (nova suíte test_token_refresh.py) + E2E com cookies forjados (access expirado + refresh válido): refresh único, retry do launch-token com `?handoff=` correto, sem loop, login errado sem refresh, logout OK (iteration_3.json) + self-test do ajuste `/auth/me` (0 refresh no boot de visitante).

## Implementado (29/08/2026 — Separação Equipe DACOT × Clientes de Restaurante)
- **Dois escopos de role separados** (nunca colapsados): `hub_users` ganha `user_type: "staff"` (roles super_admin/admin/viewer); `tenant_users` ganha `user_type: "restaurant"`, `password_hash`, `token_version` e roles operacionais (admin/manager/waiter/kitchen) com `tenant_id` obrigatório.
- **JWT** carrega apenas claim `ut` (user_type) para localizar a conta; `role` e `tenant_id` são sempre re-derivados do banco a cada request.
- **Login unificado** (`/api/auth/login`) detecta a população; `/auth/me`, `/auth/refresh`, forgot/reset funcionam para ambas (reset escolhe a coleção via `user_type` no doc do token).
- **Dependências de autorização**: `get_staff_user` (leitura admin, inclui viewer), `get_staff_write` (super_admin/admin; viewer recebe 403), `get_restaurant_user` (portal; exige tenant_id na identidade).
- **Portal do cliente** (`/portal` + `GET /api/portal/context` + `POST /api/portal/modules/{mkey}/launch-token`): tenant vem exclusivamente da sessão; handoff representa o usuário do restaurante (`sub=tenant_user:<id>`, role operacional do DB, restaurant_id da sessão).
- **Migração não-destrutiva** no startup: backfill de `user_type`, mapeamento de roles de exibição → operacionais, senha seed para tenant_users, seeds idempotentes de staff (admin@dacot.com, viewer@dacot.com) — **[atualizado em 06/09/2026: essas duas contas de staff deixaram de ter e-mail/senha fixos no código; agora só são criadas se `STAFF_ADMIN_EMAIL`/`STAFF_ADMIN_PASSWORD` e `STAFF_VIEWER_EMAIL`/`STAFF_VIEWER_PASSWORD` forem fornecidos via ambiente — ver `server.py`, `OPTIONAL_STAFF_SEEDS`]**.
- Frontend: Login redireciona por user_type; AppLayout redireciona clientes ao portal; Portal simplificado com módulos do próprio restaurante e botão Abrir apenas para ativos.
- Auditoria manual curl: 14/14 casos (viewer 403 em escritas, cliente 403 em todo /api/hub/*, body malicioso ignorado, handoff com role correta por usuário).
- Testes: 67/67 pytest (nova suíte test_access_separation.py com 35 testes) + E2E 15/15 (iteration_4.json).
- Hardening pós-auditoria: lockout de brute-force usa `X-Forwarded-For` (primeiro hop) em vez do IP do pod do ingress — 429 confirmado na 6ª tentativa via URL pública; Portal.jsx não dispara `/portal/context` quando o logado é staff (0 chamadas espúrias, verificado).

## Backlog (não implementado — próximas fases)
- P1: CRUD real de usuários do restaurante no Hub + convites.
- P1: RBAC de hub_users (super_admin / admin / viewer) — schema pronto, UI pendente.
- P1: Integração real "Abrir módulo" — geração de launch-token JWT curto por tenant + assinatura, endpoint `/api/hub/tenants/{id}/modules/{key}/launch-token`.
- P2: Métricas de utilização real (chamadas por módulo, MRR, churn).
- P2: Auditoria/exportação de activity_log; timeline por cliente.
- P2: Multi-idioma (pt-BR/en); dark mode do dashboard.
- P2: Testes automatizados unitários (pytest + RTL).

## Contrato "Abrir módulo" (futuro)
Cada `tenant_modules.launch_url` pode ser preenchida (override) ou herdar do
`modules.launch_url_template` (com `{slug}` substituído). Quando o módulo de Pedidos entrar
em produção, o Hub emitirá um JWT curto contendo `tenant_id` + `module_key` e o anexará
como querystring. Nada precisa mudar no schema atual.
