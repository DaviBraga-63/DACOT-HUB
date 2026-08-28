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
