import { useEffect, useState } from "react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { toast } from "sonner";

const roles = [
  { v: "admin", l: "Administrador operacional" },
  { v: "manager", l: "Gerente" },
  { v: "waiter", l: "Garçom" },
  { v: "kitchen", l: "Cozinha" },
];

const accessLabels = {
  granted: "Acesso liberado",
  blocked: "Acesso bloqueado",
  pending: "Configuração pendente",
};

export default function PortalEquipe() {
  const [users, setUsers] = useState(null);
  const [custom, setCustom] = useState([]);
  const [ownerId, setOwnerId] = useState(null);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [accessBusy, setAccessBusy] = useState(null);

  const load = async () => {
    const [usersResponse, rolesResponse, grantsResponse, contextResponse] = await Promise.all([
      api.get("/portal/users"),
      api.get("/portal/orders/custom-roles").catch(() => ({ data: { custom_roles: [] } })),
      api.get("/portal/orders/access-grants"),
      api.get("/portal/context"),
    ]);
    const grants = new Map((grantsResponse.data.grants || []).map((grant) => [grant.user_id, grant.state]));
    const enriched = await Promise.all(usersResponse.data.map(async (item) => {
      try {
        const { data } = await api.get(`/portal/users/${item.id}/custom-role`);
        return { ...item, custom_role: data.custom_role, orders_access: grants.get(item.id) || "blocked" };
      } catch {
        return { ...item, orders_access: grants.get(item.id) || "blocked" };
      }
    }));
    setUsers(enriched);
    setCustom(rolesResponse.data.custom_roles || []);
    setOwnerId(contextResponse.data.user?.id || null);
  };

  useEffect(() => {
    load().catch(() => toast.error("Não foi possível carregar a equipe."));
  }, []);

  const save = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      if (form.id) {
        await api.patch(`/portal/users/${form.id}`, {
          name: form.name,
          email: form.email,
          role: form.role,
          status: form.status,
          custom_role_id: form.custom_role_id || null,
        });
      } else {
        await api.post("/portal/users", {
          name: form.name,
          email: form.email,
          role: form.role,
          password: form.password,
          custom_role_id: form.custom_role_id || null,
        });
      }
      toast.success("Equipe atualizada.");
      setForm(null);
      await load();
    } catch (error) {
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const reset = async (user) => {
    const password = window.prompt(`Nova senha para ${user.name}:`);
    if (!password) return;
    try {
      await api.post(`/portal/users/${user.id}/password`, { password });
      toast.success("Senha redefinida.");
    } catch (error) {
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
    }
  };

  const setOrdersAccess = async (user, active) => {
    setAccessBusy(user.id);
    try {
      await api.put(`/portal/users/${user.id}/orders/access`, { active });
      toast.success(active ? "Acesso ao Pedidos liberado." : "Acesso ao Pedidos bloqueado.");
      await load();
    } catch (error) {
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
      await load().catch(() => undefined);
    } finally {
      setAccessBusy(null);
    }
  };

  return <div className="max-w-6xl space-y-6 dh-fade-in" data-testid="portal-team-page">
    <div className="flex flex-wrap items-start justify-between gap-4">
      <div>
        <p className="text-xs font-semibold uppercase tracking-[.16em] text-[var(--dh-muted)]">Portal</p>
        <h1 className="dh-font-display mt-2 text-3xl font-bold text-[var(--dh-text)]">Equipe</h1>
        <p className="mt-2 text-sm text-[var(--dh-muted)]">Gerencie quem acessa o Pedidos.</p>
      </div>
      <button className="dh-btn dh-btn-primary" onClick={() => setForm({ name: "", email: "", password: "", role: "waiter", status: "active", custom_role_id: "" })}>Adicionar funcionário</button>
    </div>

    {form && <form onSubmit={save} className="dh-card grid gap-3 p-5 md:grid-cols-2">
      <input required className="dh-input" placeholder="Nome" value={form.name} onChange={(event) => setForm({ ...form, name: event.target.value })} />
      <input required type="email" className="dh-input" placeholder="E-mail" value={form.email} onChange={(event) => setForm({ ...form, email: event.target.value })} />
      {!form.id && <input required minLength="6" type="password" className="dh-input" placeholder="Senha definida pelo proprietário" value={form.password} onChange={(event) => setForm({ ...form, password: event.target.value })} />}
      <select className="dh-input" value={form.role} onChange={(event) => setForm({ ...form, role: event.target.value, custom_role_id: event.target.value === "waiter" ? form.custom_role_id : "" })}>
        {roles.map((role) => <option key={role.v} value={role.v}>{role.l}</option>)}
      </select>
      {form.role === "waiter" && <select className="dh-input" value={form.custom_role_id || ""} onChange={(event) => setForm({ ...form, custom_role_id: event.target.value })}>
        <option value="">Sem cargo personalizado</option>
        {custom.map((role) => <option key={role.id} value={role.id}>{role.name}</option>)}
      </select>}
      <div className="flex gap-2">
        <button disabled={busy} className="dh-btn dh-btn-primary">{busy ? "Salvando…" : "Salvar"}</button>
        <button type="button" className="dh-btn" onClick={() => setForm(null)}>Cancelar</button>
      </div>
    </form>}

    <div className="dh-card overflow-x-auto">
      <table className="dh-table w-full">
        <thead><tr><th>Nome</th><th>E-mail</th><th>Cargo</th><th>Situação</th><th>Pedidos</th><th /></tr></thead>
        <tbody>{users?.map((user) => {
          const state = user.orders_access || "blocked";
          const isOwner = user.id === ownerId;
          return <tr key={user.id}>
            <td>{user.name}</td>
            <td>{user.email}</td>
            <td>{user.custom_role?.name || roles.find((role) => role.v === user.role)?.l || user.role}</td>
            <td>{user.status === "active" ? "Ativo" : "Inativo"}</td>
            <td>{accessLabels[state]}</td>
            <td className="flex gap-2 py-2">
              <button className="dh-btn" onClick={() => setForm({ ...user, password: "", custom_role_id: user.custom_role?.id || "" })}>Editar</button>
              <button className="dh-btn" onClick={() => reset(user)}>Senha</button>
              {!isOwner && state === "granted" && <button disabled={accessBusy === user.id} className="dh-btn" onClick={() => setOrdersAccess(user, false)}>Revogar acesso</button>}
              {!isOwner && state === "blocked" && <button disabled={accessBusy === user.id || user.status !== "active"} className="dh-btn dh-btn-primary" onClick={() => setOrdersAccess(user, true)}>Autorizar acesso</button>}
              {!isOwner && state === "pending" && <button disabled={accessBusy === user.id || user.status !== "active"} className="dh-btn dh-btn-primary" onClick={() => setOrdersAccess(user, true)}>Repetir configuração</button>}
            </td>
          </tr>;
        })}</tbody>
      </table>
      {users === null && <div className="p-6 text-sm text-[var(--dh-muted)]">Carregando…</div>}
    </div>
  </div>;
}
