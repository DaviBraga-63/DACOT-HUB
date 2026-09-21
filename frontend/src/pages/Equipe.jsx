import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Users as UsersIcon, UserPlus } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { toast } from "sonner";

const ROLE_OPTS = [
  { v: "super_admin", l: "Super Admin" },
  { v: "admin", l: "Admin" },
  { v: "viewer", l: "Viewer" },
];

export default function Equipe() {
  const { user } = useAuth();
  const [users, setUsers] = useState(null);
  const [adding, setAdding] = useState(false);
  const canWrite = user?.role !== "viewer";

  const load = () => api.get("/hub/users").then((r) => setUsers(r.data));

  useEffect(() => { load().catch(() => {}); }, []);

  return (
    <div className="space-y-6" data-testid="equipe-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Equipe DACOT</h1>
          <p className="text-[15px] text-slate-500 mt-2">Usuários internos com acesso ao Hub.</p>
        </div>
        {canWrite && (
          <button className="dh-btn dh-btn-primary" onClick={() => setAdding((v) => !v)}
                  data-testid="add-staff-toggle">
            <UserPlus size={16} strokeWidth={2} /> Adicionar usuário
          </button>
        )}
      </div>

      {adding && canWrite && (
        <NewStaffForm onDone={() => { setAdding(false); load(); }} onCancel={() => setAdding(false)} />
      )}

      <div className="dh-card overflow-hidden">
        <div className="overflow-x-auto">
          <table className="dh-table" data-testid="staff-table">
            <thead>
              <tr>
                <th>Nome</th><th>E-mail</th><th>Função</th><th>Status</th>{canWrite && <th></th>}
              </tr>
            </thead>
            <tbody>
              {users === null && [0, 1, 2].map((i) => (
                <tr key={i}><td colSpan={5}><div className="dh-skeleton h-5 w-full" /></td></tr>
              ))}
              {users?.length === 0 && (
                <tr><td colSpan={5} className="py-14">
                  <div className="flex flex-col items-center justify-center text-center gap-3">
                    <span className="dh-icon-tile-neutral w-12 h-12 rounded-xl">
                      <UsersIcon size={20} strokeWidth={1.6} />
                    </span>
                    <div className="text-sm font-medium text-slate-700">Nenhum usuário ainda</div>
                  </div>
                </td></tr>
              )}
              {users?.map((u) => (
                <StaffRow key={u.id} staffUser={u} isSelf={u.id === user?.id}
                          canWrite={canWrite} reload={load} />
              ))}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}

function StaffRow({ staffUser, isSelf, canWrite, reload }) {
  const [editing, setEditing] = useState(false);
  const [busy, setBusy] = useState(false);
  // A user can never change their own role or active status here — always
  // routed through another admin account, mirroring the backend guard.
  const rowLocked = !canWrite || isSelf;

  const changeRole = async (role) => {
    setBusy(true);
    try {
      await api.patch(`/hub/users/${staffUser.id}`, { role });
      toast.success("Função atualizada");
      reload();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível atualizar a função.");
    } finally { setBusy(false); }
  };

  const toggleActive = async () => {
    setBusy(true);
    try {
      await api.patch(`/hub/users/${staffUser.id}`, { active: !staffUser.active });
      toast.success(staffUser.active ? "Usuário desativado" : "Usuário ativado");
      reload();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível atualizar o status.");
    } finally { setBusy(false); }
  };

  return (
    <tr data-testid={`staff-row-${staffUser.id}`}>
      <td className="font-semibold text-slate-900">
        {staffUser.name}{isSelf && <span className="text-slate-400 font-normal"> (você)</span>}
      </td>
      <td className="text-[13px] text-slate-600">{staffUser.email}</td>
      <td>
        {editing && !rowLocked ? (
          <select value={staffUser.role} disabled={busy} onChange={(e) => changeRole(e.target.value)}
                  className="dh-input w-auto py-1.5 pl-2 pr-7 text-[12px]"
                  data-testid={`staff-role-select-${staffUser.id}`}>
            {ROLE_OPTS.map((r) => <option key={r.v} value={r.v}>{r.l}</option>)}
          </select>
        ) : (
          <span className="dh-chip dh-chip-neutral">{ROLE_OPTS.find((r) => r.v === staffUser.role)?.l || staffUser.role}</span>
        )}
      </td>
      <td><StatusBadge status={staffUser.active ? "active" : "inactive"} /></td>
      {canWrite && (
        <td className="text-right">
          {rowLocked ? (
            <span className="text-[11px] text-slate-400" title="Peça a outro administrador para alterar sua própria conta">
              {isSelf ? "sua conta" : ""}
            </span>
          ) : (
            <div className="flex items-center justify-end gap-2">
              <button className="dh-btn dh-btn-ghost" onClick={() => setEditing((v) => !v)}
                      data-testid={`staff-edit-${staffUser.id}`} title="Editar função">
                Função
              </button>
              <button className="dh-btn dh-btn-outline" onClick={toggleActive} disabled={busy}
                      data-testid={`staff-toggle-active-${staffUser.id}`}>
                {staffUser.active ? "Desativar" : "Ativar"}
              </button>
            </div>
          )}
        </td>
      )}
    </tr>
  );
}

function NewStaffForm({ onDone, onCancel }) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [role, setRole] = useState("viewer");
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true);
    try {
      const { data } = await api.post("/hub/users", { name, email, role });
      if (data.temp_password) {
        toast.success(`Usuário criado. Senha temporária: ${data.temp_password}`, { duration: 15000 });
      } else {
        toast.success("Usuário criado");
      }
      onDone();
    } catch (e) {
      toast.error(e.response?.data?.detail || "Não foi possível criar o usuário.");
    } finally { setBusy(false); }
  };

  return (
    <form onSubmit={submit} className="dh-card p-5 flex flex-wrap items-end gap-3" data-testid="new-staff-form">
      <div className="flex-1 min-w-[160px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Nome</label>
        <input value={name} onChange={(e) => setName(e.target.value)} required
               className="dh-input mt-1" data-testid="new-staff-name" />
      </div>
      <div className="flex-1 min-w-[200px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">E-mail</label>
        <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} required
               className="dh-input mt-1" data-testid="new-staff-email" />
      </div>
      <div className="min-w-[160px]">
        <label className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">Função</label>
        <select value={role} onChange={(e) => setRole(e.target.value)}
                className="dh-input mt-1" data-testid="new-staff-role">
          {ROLE_OPTS.map((r) => <option key={r.v} value={r.v}>{r.l}</option>)}
        </select>
      </div>
      <div className="flex gap-2">
        <button type="submit" className="dh-btn dh-btn-primary" disabled={busy} data-testid="new-staff-submit">
          Criar
        </button>
        <button type="button" className="dh-btn dh-btn-ghost" onClick={onCancel}>Cancelar</button>
      </div>
    </form>
  );
}
