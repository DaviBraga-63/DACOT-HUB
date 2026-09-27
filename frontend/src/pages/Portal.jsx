import { useCallback, useEffect, useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { LogOut, ArrowUpRight, ClipboardList, ChefHat, Users, UserPlus, Pencil, KeyRound, Boxes, Landmark, Bike, Package } from "lucide-react";

const ICONS = {
  "clipboard-list": ClipboardList, "chef-hat": ChefHat, "users": Users,
  "boxes": Boxes, "landmark": Landmark, "bike": Bike,
};

const ROLE_LABEL = { admin: "Administrador", manager: "Gerente", waiter: "Garçom", kitchen: "Cozinha" };
const TENANT_STATUS = {
  active: { cls: "dh-chip-success", label: "Ativo" },
  trial: { cls: "dh-chip-warning", label: "Em teste" },
  suspended: { cls: "dh-chip-error", label: "Suspenso" },
  inactive: { cls: "dh-chip-neutral", label: "Inativo" },
};

export default function Portal() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [ctx, setCtx] = useState(null);
  const [err, setErr] = useState(null);
  const [tenantUsers, setTenantUsers] = useState([]);
  const [usersLoading, setUsersLoading] = useState(false);
  const [addingUser, setAddingUser] = useState(false);

  useEffect(() => {
    if (user?.user_type === "staff") return;
    api.get("/portal/context")
      .then((r) => setCtx(r.data))
      .catch((e) => setErr(formatApiErrorDetail(e.response?.data?.detail)));
  }, [user?.user_type]);

  const loadUsers = useCallback(async () => {
    setUsersLoading(true);
    try {
      const { data } = await api.get("/portal/users");
      setTenantUsers(data);
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setUsersLoading(false);
    }
  }, []);

  useEffect(() => {
    if (user?.user_type === "restaurant" && user?.role === "admin") loadUsers();
  }, [user?.user_type, user?.role, loadUsers]);

  if (user?.user_type === "staff") return <Navigate to="/" replace />;

  const openModule = async (m) => {
    try {
      const { data } = await api.post(`/portal/modules/${m.key}/launch-token`);
      if (!data?.handoff || !data?.launch_url) {
        toast.info("Este módulo ainda não possui URL de acesso configurada.");
        return;
      }
      const sep = data.launch_url.includes("?") ? "&" : "?";
      window.open(`${data.launch_url}${sep}handoff=${encodeURIComponent(data.handoff)}`, "_blank", "noopener,noreferrer");
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    }
  };

  const tenantStatus = TENANT_STATUS[ctx?.tenant?.status] || TENANT_STATUS.inactive;
  const firstName = (ctx?.user?.name || user?.name || "").split(/\s+/)[0];

  return (
    <div className="min-h-screen bg-[var(--dh-bg)]" data-testid="portal-page">
      <header className="bg-white/95 backdrop-blur-md border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-4xl mx-auto px-5 sm:px-6 lg:px-8 h-16 flex items-center justify-between">
          <div className="flex items-center gap-3">
            <div 
              className="w-9 h-9 rounded-lg flex items-center justify-center text-white font-bold text-[13px]"
              style={{background: 'linear-gradient(135deg, #1B73B8 0%, #32A5DC 100%)', fontFamily:"Cabinet Grotesk"}}
            >
              D
            </div>
            <div className="font-bold text-sm tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
          </div>
          <div className="flex items-center gap-4">
            <div className="text-right leading-tight hidden sm:block">
              <div className="text-[13px] font-semibold text-slate-900" data-testid="portal-user-name">{user?.name}</div>
              <div className="text-[11px] text-slate-400" data-testid="portal-user-role">{ROLE_LABEL[user?.role] || user?.role}</div>
            </div>
            <button onClick={async () => { await logout(); navigate("/login"); }}
                    data-testid="portal-logout-btn" title="Sair"
                    className="p-2 rounded-lg hover:bg-slate-100 transition-colors">
              <LogOut size={16} strokeWidth={1.8} className="text-slate-600" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-4xl mx-auto px-5 sm:px-6 lg:px-8 pt-16 pb-16">
        {err && <div className="dh-chip dh-chip-error mb-6" data-testid="portal-error">{err}</div>}
        {!ctx && !err && (
          <div className="space-y-6">
            <div className="space-y-3">
              <div className="dh-skeleton h-5 w-32" />
              <div className="dh-skeleton h-10 w-72" />
            </div>
            <div className="dh-card p-4 space-y-3">
              {[0,1,2].map((i) => <div key={i} className="dh-skeleton h-20 rounded-lg" />)}
            </div>
          </div>
        )}

        {ctx && (
          <div className="space-y-10 dh-fade-in">
            <div>
              <div className="text-[13px] text-slate-500 font-semibold uppercase tracking-wide mb-2">Olá, {firstName}</div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-4xl lg:text-5xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}} data-testid="portal-tenant-name">
                  {ctx.tenant.name}
                </h1>
                <span className={`dh-chip ${tenantStatus.cls}`} data-testid="portal-tenant-status">{tenantStatus.label}</span>
              </div>
            </div>

            <section>
              <h2 className="text-[12px] uppercase tracking-widest font-bold text-slate-400 mb-4">Seus módulos</h2>
              <div className="dh-card divide-y divide-slate-100 overflow-hidden" data-testid="portal-modules">
                {ctx.modules.map((m, idx) => {
                  const Icon = ICONS[m.icon] || Package;
                  return (
                    <div 
                      key={m.key} 
                      className="flex items-center gap-5 px-6 py-5 hover:bg-slate-50 transition-colors"
                      data-testid={`portal-module-${m.key}`}
                      style={{
                        borderLeft: m.active ? '4px solid var(--dh-accent)' : '4px solid transparent'
                      }}
                    >
                      <div className={`${m.active ? "dh-icon-tile" : "dh-icon-tile-neutral"} w-11 h-11 shrink-0 rounded-lg`}>
                        <Icon size={20} strokeWidth={1.6} />
                      </div>
                      <div className="flex-1 min-w-0">
                        <div className="text-[16px] font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
                        <div className="text-[13px] text-slate-500 truncate mt-0.5">{m.description}</div>
                      </div>
                      {m.active ? (
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="dh-chip dh-chip-success hidden sm:inline-flex">Ativo</span>
                          <button className="dh-btn dh-btn-primary text-[13px]" onClick={() => openModule(m)}
                                  data-testid={`portal-open-${m.key}`}>
                            Abrir <ArrowUpRight size={15} strokeWidth={2} />
                          </button>
                        </div>
                      ) : (
                        <span className="dh-chip dh-chip-neutral shrink-0">Inativo</span>
                      )}
                    </div>
                  );
                })}
              </div>
            </section>

            {ctx.user.role === "admin" && (
              <section data-testid="portal-users-section">
                <div className="flex items-center justify-between gap-4 mb-4">
                  <h2 className="text-[12px] uppercase tracking-widest font-bold text-slate-400">Equipe</h2>
                  <button className="dh-btn dh-btn-primary text-[13px]" onClick={() => setAddingUser((v) => !v)}
                          data-testid="portal-add-user-toggle">
                    <UserPlus size={15} strokeWidth={1.8} /> Adicionar usuário
                  </button>
                </div>

                {addingUser && (
                  <PortalUserForm
                    onCancel={() => setAddingUser(false)}
                    onCreated={() => { setAddingUser(false); loadUsers(); }}
                  />
                )}

                <div className="dh-card overflow-hidden mt-4">
                  <div className="overflow-x-auto">
                    <table className="dh-table" data-testid="portal-users-table">
                      <thead><tr><th>Nome</th><th>E-mail</th><th>Função</th><th>Status</th><th></th></tr></thead>
                      <tbody>
                        {usersLoading && (
                          <tr><td colSpan={5} className="text-center py-8 text-slate-400">Carregando equipe...</td></tr>
                        )}
                        {!usersLoading && tenantUsers.map((tenantUser) => (
                          <PortalUserRow key={tenantUser.id} tenantUser={tenantUser}
                                         currentUserId={ctx.user.id} reload={loadUsers} />
                        ))}
                      </tbody>
                    </table>
                  </div>
                </div>
              </section>
            )}

            <p className="text-[13px] text-slate-500 text-center">
              Precisa de um módulo inativo? Fale com a equipe DACOT para solicitar a ativação.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}

function PortalUserRow({ tenantUser, currentUserId, reload }) {
  const [editing, setEditing] = useState(false);
  const [name, setName] = useState(tenantUser.name);
  const [email, setEmail] = useState(tenantUser.email);
  const [role, setRole] = useState(tenantUser.role);
  const [busy, setBusy] = useState(false);
  const isSelf = tenantUser.id === currentUserId;

  const save = async () => {
    setBusy(true);
    try {
      const payload = { name, email };
      if (!isSelf) payload.role = role;
      await api.patch(`/portal/users/${tenantUser.id}`, payload);
      toast.success("Usuário atualizado");
      setEditing(false);
      await reload();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const toggleStatus = async () => {
    const nextStatus = tenantUser.status === "active" ? "inactive" : "active";
    if (nextStatus === "inactive" && !window.confirm(`Desativar ${tenantUser.name}? O acesso será revogado.`)) return;
    setBusy(true);
    try {
      await api.patch(`/portal/users/${tenantUser.id}`, { status: nextStatus });
      toast.success(nextStatus === "active" ? "Usuário reativado" : "Usuário desativado");
      await reload();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  const resetPassword = async () => {
    if (!window.confirm(`Gerar uma nova senha para ${tenantUser.name}? As sessões atuais serão revogadas.`)) return;
    setBusy(true);
    try {
      const { data } = await api.post(`/portal/users/${tenantUser.id}/reset-password`);
      toast.success(`Nova senha temporária: ${data.temp_password}`, { duration: 15000 });
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  if (editing) {
    return (
      <tr data-testid={`portal-user-${tenantUser.id}`}>
        <td><input className="dh-input min-w-[150px]" value={name} onChange={(e) => setName(e.target.value)}
                   required maxLength={120} data-testid={`portal-user-name-${tenantUser.id}`} /></td>
        <td><input className="dh-input min-w-[210px]" type="email" value={email}
                   onChange={(e) => setEmail(e.target.value)} required data-testid={`portal-user-email-${tenantUser.id}`} /></td>
        <td>
          <select className="dh-input min-w-[145px]" value={role} onChange={(e) => setRole(e.target.value)}
                  disabled={isSelf} data-testid={`portal-user-role-${tenantUser.id}`}>
            <option value="admin">Administrador</option>
            <option value="manager">Gerente</option>
            <option value="waiter">Garçom</option>
            <option value="kitchen">Cozinha</option>
          </select>
        </td>
        <td><span className={`dh-chip ${tenantUser.status === "active" ? "dh-chip-success" : "dh-chip-neutral"}`}>
          {tenantUser.status === "active" ? "Ativo" : "Inativo"}
        </span></td>
        <td className="text-right whitespace-nowrap">
          <button className="dh-btn dh-btn-primary mr-2" onClick={save} disabled={busy}>Salvar</button>
          <button className="dh-btn dh-btn-ghost" onClick={() => setEditing(false)} disabled={busy}>Cancelar</button>
        </td>
      </tr>
    );
  }

  return (
    <tr data-testid={`portal-user-${tenantUser.id}`}>
      <td className="font-semibold text-slate-900">{tenantUser.name}{isSelf && <span className="text-slate-400 font-normal"> (você)</span>}</td>
      <td className="text-[13px] text-slate-600">{tenantUser.email}</td>
      <td><span className="dh-chip dh-chip-neutral">{ROLE_LABEL[tenantUser.role] || tenantUser.role}</span></td>
      <td><span className={`dh-chip ${tenantUser.status === "active" ? "dh-chip-success" : "dh-chip-neutral"}`}>
        {tenantUser.status === "active" ? "Ativo" : "Inativo"}
      </span></td>
      <td className="text-right whitespace-nowrap">
        <button className="dh-btn dh-btn-ghost mr-1" onClick={() => setEditing(true)} disabled={busy}
                title="Editar usuário" data-testid={`portal-user-edit-${tenantUser.id}`}>
          <Pencil size={14} strokeWidth={1.8} />
        </button>
        {!isSelf && (
          <>
            <button className="dh-btn dh-btn-ghost mr-1" onClick={resetPassword} disabled={busy}
                    title="Gerar nova senha" data-testid={`portal-user-password-${tenantUser.id}`}>
              <KeyRound size={14} strokeWidth={1.8} />
            </button>
            <button className="dh-btn dh-btn-outline" onClick={toggleStatus} disabled={busy}
                    data-testid={`portal-user-status-${tenantUser.id}`}>
              {tenantUser.status === "active" ? "Desativar" : "Reativar"}
            </button>
          </>
        )}
      </td>
    </tr>
  );
}

function PortalUserForm({ onCancel, onCreated }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("waiter");
  const [busy, setBusy] = useState(false);

  const submit = async (event) => {
    event.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/portal/users", { name, email, role });
      toast.success(`Usuário criado. Senha temporária: ${data.temp_password}`, { duration: 15000 });
      onCreated();
    } catch (e) {
      toast.error(formatApiErrorDetail(e.response?.data?.detail));
    } finally {
      setBusy(false);
    }
  };

  return (
    <form onSubmit={submit} className="dh-card p-5 flex flex-wrap items-end gap-3" data-testid="portal-new-user-form">
      <div className="flex-1 min-w-[160px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Nome</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required maxLength={120}
               className="dh-input mt-1" data-testid="portal-new-user-name" />
      </div>
      <div className="flex-1 min-w-[200px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">E-mail</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
               className="dh-input mt-1" data-testid="portal-new-user-email" />
      </div>
      <div className="min-w-[160px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Função</label>
        <select value={role} onChange={(e) => setRole(e.target.value)} className="dh-input mt-1"
                data-testid="portal-new-user-role">
          <option value="admin">Administrador</option>
          <option value="manager">Gerente</option>
          <option value="waiter">Garçom</option>
          <option value="kitchen">Cozinha</option>
        </select>
      </div>
      <div className="flex gap-2">
        <button type="submit" className="dh-btn dh-btn-primary" disabled={busy} data-testid="portal-new-user-submit">
          Criar
        </button>
        <button type="button" className="dh-btn dh-btn-ghost" onClick={onCancel} disabled={busy}>Cancelar</button>
      </div>
    </form>
  );
}
