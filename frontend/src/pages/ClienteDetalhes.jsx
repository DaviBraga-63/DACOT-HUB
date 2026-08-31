import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { ArrowLeft, ExternalLink, Mail, Phone, MapPin, Calendar, Settings2, Users as UsersIcon } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { toast } from "sonner";

const TABS = [
  { key: "overview", label: "Visão geral" },
  { key: "modules", label: "Módulos" },
  { key: "users", label: "Usuários" },
];

const STATUS_OPTS = [
  { v: "active", l: "Ativo" },
  { v: "trial", l: "Em teste" },
  { v: "suspended", l: "Suspenso" },
  { v: "inactive", l: "Inativo" },
];

export default function ClienteDetalhes() {
  const { id } = useParams();
  const [tab, setTab] = useState("overview");
  const [tenant, setTenant] = useState(null);
  const [modules, setModules] = useState([]);
  const [users, setUsers] = useState([]);
  const [activity, setActivity] = useState([]);

  const load = useCallback(async () => {
    const [t, m, u, a] = await Promise.all([
      api.get(`/hub/tenants/${id}`),
      api.get(`/hub/tenants/${id}/modules`),
      api.get(`/hub/tenants/${id}/users`),
      api.get(`/hub/dashboard/activity`, { params: { limit: 30 } }),
    ]);
    setTenant(t.data); setModules(m.data); setUsers(u.data);
    setActivity(a.data.filter((x) => x.tenant_id === id).slice(0, 10));
  }, [id]);

  useEffect(() => { load().catch(() => {}); }, [load]);

  const changeStatus = async (status) => {
    await api.patch(`/hub/tenants/${id}`, { status });
    toast.success("Status atualizado");
    load();
  };

  if (!tenant) {
    return (
      <div className="space-y-6">
        <div className="dh-skeleton h-4 w-24" />
        <div className="dh-skeleton h-9 w-72" />
        <div className="dh-card p-7"><div className="dh-skeleton h-40 w-full" /></div>
      </div>
    );
  }

  return (
    <div className="space-y-6" data-testid="tenant-detail-page">
      <div>
        <Link to="/clientes" className="text-[12px] font-medium text-slate-400 hover:text-slate-700 transition-colors inline-flex items-center gap-1.5">
          <ArrowLeft size={13} strokeWidth={1.8} /> Clientes
        </Link>
        <div className="flex items-start justify-between mt-3 gap-6 flex-wrap">
          <div>
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}} data-testid="tenant-name">{tenant.name}</h1>
              <StatusBadge status={tenant.status} testid="tenant-status" />
            </div>
            <div className="mt-1.5 text-[12px] text-slate-400 font-mono">tenant/{tenant.slug}</div>
          </div>
          <select
            value={tenant.status} onChange={(e) => changeStatus(e.target.value)}
            className="dh-input w-auto py-2 pl-3 pr-8 text-[13px] font-medium"
            data-testid="change-status">
            {STATUS_OPTS.map((s) => <option key={s.v} value={s.v}>Status: {s.l}</option>)}
          </select>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-slate-200 flex items-center">
        {TABS.map((t) => (
          <button key={t.key}
                  onClick={() => setTab(t.key)}
                  data-testid={`tab-${t.key}`}
                  className={`dh-tab ${tab === t.key ? "dh-tab-active" : ""}`}>
            {t.label}
          </button>
        ))}
      </div>

      {tab === "overview" && (
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-5 dh-fade-in">
          <div className="dh-card p-6 sm:p-7 lg:col-span-2" data-testid="tenant-info">
            <h2 className="text-base font-semibold text-slate-900 mb-5" style={{fontFamily:"Cabinet Grotesk"}}>Informações</h2>
            <div className="grid grid-cols-1 sm:grid-cols-2 gap-x-6 gap-y-5">
              <InfoRow icon={Mail} label="E-mail" value={tenant.email} />
              <InfoRow icon={Phone} label="Telefone" value={tenant.phone || "—"} />
              <InfoRow icon={MapPin} label="Endereço" value={tenant.address || "—"} />
              <InfoRow icon={Calendar} label="Cadastrado em"
                       value={tenant.created_at ? new Date(tenant.created_at).toLocaleString("pt-BR") : "—"} />
            </div>
            {tenant.notes && (
              <div className="pt-5 mt-5 border-t border-slate-100">
                <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400 mb-1.5">Observações</div>
                <div className="text-[14px] text-slate-700 leading-relaxed">{tenant.notes}</div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-4 pt-5 mt-5 border-t border-slate-100">
              <MetricSmall label="Módulos ativos" value={tenant.active_modules} />
              <MetricSmall label="Usuários" value={tenant.users_count} />
              <MetricSmall label="Responsável" value={tenant.owner_name} textual />
            </div>
          </div>
          <div className="dh-card p-6 sm:p-7" data-testid="tenant-activity">
            <h2 className="text-base font-semibold text-slate-900 mb-4" style={{fontFamily:"Cabinet Grotesk"}}>Atividade recente</h2>
            <ul className="space-y-3.5">
              {activity.length === 0 && <li className="text-sm text-slate-500">Sem eventos.</li>}
              {activity.map((a) => (
                <li key={a.id} className="pb-3.5 border-b border-slate-100 last:border-b-0 last:pb-0 text-[13px]">
                  <div className="leading-snug"><b className="text-slate-900">{a.actor_name}</b> <span className="text-slate-500">— {a.action.replace(/_/g, " ")}</span></div>
                  <div className="text-[11px] text-slate-400 mt-1">{new Date(a.created_at).toLocaleString("pt-BR")}</div>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {tab === "modules" && (
        <ModulesTab tenantId={id} tenantSlug={tenant.slug} modules={modules} reload={load} />
      )}

      {tab === "users" && <UsersTab users={users} />}
    </div>
  );
}

function InfoRow({ icon: Icon, label, value }) {
  return (
    <div className="flex items-start gap-3">
      <span className="dh-icon-tile-neutral w-8 h-8 shrink-0">
        <Icon size={14} strokeWidth={1.8} />
      </span>
      <div className="min-w-0">
        <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">{label}</div>
        <div className="text-[14px] text-slate-800 mt-0.5 break-words">{value}</div>
      </div>
    </div>
  );
}

function MetricSmall({ label, value, textual }) {
  return (
    <div>
      <div className="text-[11px] uppercase tracking-wider font-semibold text-slate-400">{label}</div>
      <div className={textual ? "text-[14px] font-semibold text-slate-800 mt-1" : "dh-kpi-value mt-1"}>{value ?? "—"}</div>
    </div>
  );
}

function ModulesTab({ tenantId, tenantSlug, modules, reload }) {
  const [editing, setEditing] = useState(null);

  const toggle = async (m) => {
    if (!m.can_activate && !m.active) {
      toast.error(`Módulo "${m.name}" ainda não está disponível para ativação.`);
      return;
    }
    if (m.active) {
      await api.post(`/hub/tenants/${tenantId}/modules/${m.key}/deactivate`);
      toast.success(`${m.name} desativado`);
    } else {
      await api.post(`/hub/tenants/${tenantId}/modules/${m.key}/activate`);
      toast.success(`${m.name} ativado`);
    }
    reload();
  };

  const openModule = async (m) => {
    try {
      const { data } = await api.post(
        `/hub/tenants/${tenantId}/modules/${m.key}/launch-token`,
      );
      if (!data?.handoff || !data?.launch_url) {
        toast.info("Configure a URL de acesso do módulo antes de abrir.");
        return;
      }
      const sep = data.launch_url.includes("?") ? "&" : "?";
      const url = `${data.launch_url}${sep}handoff=${encodeURIComponent(data.handoff)}`;
      window.open(url, "_blank", "noopener,noreferrer");
    } catch (e) {
      const detail = e.response?.data?.detail;
      toast.error(typeof detail === "string" ? detail : "Não foi possível gerar o token de acesso.");
    }
  };

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-5 dh-fade-in" data-testid="modules-tab">
      {modules.map((m) => (
        <div key={m.key} className="dh-card p-6" data-testid={`module-card-${m.key}`}>
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <div className="flex items-center gap-2.5 flex-wrap">
                <div className="text-[17px] font-semibold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
                {m.active
                  ? <span className="dh-chip dh-chip-success">Ativo</span>
                  : <StatusBadge status={m.status} />}
              </div>
              <div className="text-[11px] text-slate-400 font-medium uppercase tracking-wider mt-1">{m.category || "Módulo"}</div>
            </div>
            <label className="inline-flex items-center cursor-pointer shrink-0">
              <input
                type="checkbox"
                checked={m.active}
                disabled={!m.active && !m.can_activate}
                onChange={() => toggle(m)}
                className="sr-only peer"
                data-testid={`toggle-${m.key}`}
              />
              <span className={`dh-toggle ${m.active ? "dh-toggle-on" : "dh-toggle-off"} ${!m.active && !m.can_activate ? "dh-toggle-disabled" : ""}`}>
                <span className={`dh-toggle-knob ${m.active ? "translate-x-[20px]" : "translate-x-[2px]"}`}></span>
              </span>
            </label>
          </div>

          <p className="text-[13px] text-slate-500 mb-4 leading-relaxed">{m.description}</p>

          {m.active && (
            <div className="pt-4 border-t border-slate-100 space-y-2.5">
              {editing === m.key ? (
                <LaunchUrlEditor tenantId={tenantId} mkey={m.key} initial={m.launch_url}
                                 onDone={() => { setEditing(null); reload(); }} />
              ) : (
                <div className="flex items-center gap-2">
                  <button
                    type="button"
                    onClick={() => openModule(m)}
                    className="dh-btn dh-btn-outline flex-1"
                    data-testid={`open-${m.key}`}>
                    <ExternalLink size={13} strokeWidth={1.8} /> Abrir módulo
                  </button>
                  <button className="dh-btn dh-btn-ghost" onClick={() => setEditing(m.key)}
                          data-testid={`config-${m.key}`} title="Configurar URL">
                    <Settings2 size={14} strokeWidth={1.8} />
                  </button>
                </div>
              )}
              <div className="text-[11px] text-slate-400 font-mono truncate">
                {m.launch_url || `https://pedidos.dacot.app/${tenantSlug}`}
              </div>
            </div>
          )}
        </div>
      ))}
    </div>
  );
}

function LaunchUrlEditor({ tenantId, mkey, initial, onDone }) {
  const [url, setUrl] = useState(initial || "");
  const [busy, setBusy] = useState(false);
  const save = async () => {
    setBusy(true);
    try {
      await api.patch(`/hub/tenants/${tenantId}/modules/${mkey}`, { launch_url: url });
      toast.success("URL de acesso salva");
      onDone();
    } finally { setBusy(false); }
  };
  return (
    <div className="flex gap-2 flex-wrap">
      <input value={url} onChange={(e) => setUrl(e.target.value)}
             className="dh-input flex-1 min-w-[180px]" placeholder="https://pedidos.dacot.app/…"
             data-testid={`launch-url-input-${mkey}`} />
      <button className="dh-btn dh-btn-primary" onClick={save} disabled={busy} data-testid={`launch-url-save-${mkey}`}>Salvar</button>
      <button className="dh-btn dh-btn-ghost" onClick={onDone}>Cancelar</button>
    </div>
  );
}

function UsersTab({ users }) {
  return (
    <div className="dh-card overflow-hidden dh-fade-in" data-testid="users-tab">
      <div className="overflow-x-auto">
        <table className="dh-table">
          <thead>
            <tr>
              <th>Nome</th><th>E-mail</th><th>Função</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr><td colSpan={4} className="py-14">
                <div className="flex flex-col items-center justify-center text-center gap-3">
                  <span className="dh-icon-tile-neutral w-12 h-12 rounded-xl">
                    <UsersIcon size={20} strokeWidth={1.6} />
                  </span>
                  <div className="text-sm font-medium text-slate-700">Nenhum usuário ainda</div>
                  <div className="text-[13px] text-slate-400">Usuários são criados pelos módulos operacionais.</div>
                </div>
              </td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.id}`}>
                <td className="font-semibold text-slate-900">{u.name}</td>
                <td className="text-[13px] text-slate-600">{u.email}</td>
                <td><span className="dh-chip dh-chip-neutral">{u.role}</span></td>
                <td><StatusBadge status={u.status} /></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
