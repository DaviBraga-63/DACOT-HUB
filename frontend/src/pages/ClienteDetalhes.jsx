import { useEffect, useState, useCallback } from "react";
import { useParams, Link } from "react-router-dom";
import { api } from "@/lib/api";
import { ArrowLeft, ExternalLink, Mail, Phone, MapPin, Calendar, Settings2 } from "lucide-react";
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
    return <div className="text-sm text-[var(--dh-muted)]">Carregando…</div>;
  }

  return (
    <div className="space-y-6" data-testid="tenant-detail-page">
      <div>
        <Link to="/clientes" className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] hover:text-[var(--dh-text)] inline-flex items-center gap-1">
          <ArrowLeft size={12} /> Clientes
        </Link>
        <div className="flex items-start justify-between mt-2 gap-6">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-3xl lg:text-4xl font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}} data-testid="tenant-name">{tenant.name}</h1>
              <StatusBadge status={tenant.status} testid="tenant-status" />
            </div>
            <div className="mt-1 text-[13px] text-[var(--dh-muted)] font-mono">tenant/{tenant.slug}</div>
          </div>
          <div className="flex items-center gap-2">
            <select
              value={tenant.status} onChange={(e) => changeStatus(e.target.value)}
              className="dh-input py-1.5 pl-3 pr-8 text-[12px] font-semibold uppercase tracking-wider"
              data-testid="change-status">
              {STATUS_OPTS.map((s) => <option key={s.v} value={s.v}>Status: {s.l}</option>)}
            </select>
          </div>
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b border-[var(--dh-border)] flex items-center">
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
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6 dh-fade-in">
          <div className="dh-card p-6 lg:col-span-2 space-y-4" data-testid="tenant-info">
            <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">Informações</div>
            <InfoRow icon={Mail} label="E-mail" value={tenant.email} />
            <InfoRow icon={Phone} label="Telefone" value={tenant.phone || "—"} />
            <InfoRow icon={MapPin} label="Endereço" value={tenant.address || "—"} />
            <InfoRow icon={Calendar} label="Cadastrado em"
                     value={tenant.created_at ? new Date(tenant.created_at).toLocaleString("pt-BR") : "—"} />
            {tenant.notes && (
              <div className="pt-3 mt-2 border-t border-[var(--dh-border)]">
                <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] mb-1">Observações</div>
                <div className="text-[14px]">{tenant.notes}</div>
              </div>
            )}
            <div className="grid grid-cols-3 gap-4 pt-4 mt-2 border-t border-[var(--dh-border)]">
              <MetricSmall label="Módulos ativos" value={tenant.active_modules} />
              <MetricSmall label="Usuários" value={tenant.users_count} />
              <MetricSmall label="Responsável" value={tenant.owner_name} textual />
            </div>
          </div>
          <div className="dh-card p-6" data-testid="tenant-activity">
            <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] mb-3">Atividade recente</div>
            <ul className="space-y-3">
              {activity.length === 0 && <li className="text-sm text-[var(--dh-muted)]">Sem eventos.</li>}
              {activity.map((a) => (
                <li key={a.id} className="pb-2 border-b border-[var(--dh-border)] last:border-b-0 text-[13px]">
                  <div><b>{a.actor_name}</b> <span className="text-[var(--dh-muted)]">— {a.action.replace(/_/g, " ")}</span></div>
                  <div className="text-[11px] text-[var(--dh-muted)]">{new Date(a.created_at).toLocaleString("pt-BR")}</div>
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
      <Icon size={15} strokeWidth={1.6} className="text-[var(--dh-muted)] mt-1" />
      <div>
        <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">{label}</div>
        <div className="text-[14px]">{value}</div>
      </div>
    </div>
  );
}

function MetricSmall({ label, value, textual }) {
  return (
    <div>
      <div className="text-[10px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">{label}</div>
      <div className={textual ? "text-[14px] font-semibold" : "text-2xl font-black"} style={!textual ? {fontFamily:"Cabinet Grotesk"} : {}}>{value ?? "—"}</div>
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

  return (
    <div className="grid grid-cols-1 md:grid-cols-2 gap-4 dh-fade-in" data-testid="modules-tab">
      {modules.map((m) => (
        <div key={m.key} className="dh-card p-5" data-testid={`module-card-${m.key}`}>
          <div className="flex items-start justify-between gap-4 mb-3">
            <div>
              <div className="flex items-center gap-2">
                <div className="text-[17px] font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
                {m.active
                  ? <span className="dh-chip dh-chip-success">ATIVO</span>
                  : <StatusBadge status={m.status} />}
              </div>
              <div className="text-[11px] text-[var(--dh-muted)] font-mono">{m.category || "—"}</div>
            </div>
            <label className="inline-flex items-center cursor-pointer">
              <input
                type="checkbox"
                checked={m.active}
                disabled={!m.active && !m.can_activate}
                onChange={() => toggle(m)}
                className="sr-only peer"
                data-testid={`toggle-${m.key}`}
              />
              <span className={`w-10 h-5 rounded-sm relative transition-colors border ${
                m.active ? "bg-[var(--dh-accent)] border-[var(--dh-accent)]"
                          : (m.can_activate ? "bg-[var(--dh-neutral-bg)] border-[var(--dh-border)]"
                                              : "bg-[var(--dh-neutral-bg)] border-[var(--dh-border)] opacity-50")
              }`}>
                <span className={`absolute top-0.5 h-4 w-4 bg-white rounded-sm shadow transition-transform ${m.active ? "translate-x-5" : "translate-x-0.5"}`}></span>
              </span>
            </label>
          </div>

          <p className="text-[13px] text-[var(--dh-muted)] mb-4 leading-relaxed">{m.description}</p>

          {m.active && (
            <div className="pt-3 border-t border-[var(--dh-border)] space-y-2">
              {editing === m.key ? (
                <LaunchUrlEditor tenantId={tenantId} mkey={m.key} initial={m.launch_url}
                                 onDone={() => { setEditing(null); reload(); }} />
              ) : (
                <div className="flex items-center gap-2">
                  <a
                    href={m.launch_url || "#"}
                    target="_blank" rel="noreferrer"
                    onClick={(e) => { if (!m.launch_url) { e.preventDefault(); toast.info("Configure a URL de acesso do módulo."); } }}
                    className="dh-btn dh-btn-outline flex-1"
                    data-testid={`open-${m.key}`}>
                    <ExternalLink size={13} strokeWidth={1.8} /> Abrir módulo
                  </a>
                  <button className="dh-btn dh-btn-ghost" onClick={() => setEditing(m.key)}
                          data-testid={`config-${m.key}`} title="Configurar URL">
                    <Settings2 size={13} strokeWidth={1.8} />
                  </button>
                </div>
              )}
              <div className="text-[11px] text-[var(--dh-muted)] font-mono truncate">
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
    <div className="flex gap-2">
      <input value={url} onChange={(e) => setUrl(e.target.value)}
             className="dh-input" placeholder="https://pedidos.dacot.app/…"
             data-testid={`launch-url-input-${mkey}`} />
      <button className="dh-btn dh-btn-primary" onClick={save} disabled={busy} data-testid={`launch-url-save-${mkey}`}>Salvar</button>
      <button className="dh-btn dh-btn-ghost" onClick={onDone}>Cancelar</button>
    </div>
  );
}

function UsersTab({ users }) {
  return (
    <div className="dh-card dh-fade-in" data-testid="users-tab">
      <div className="overflow-x-auto">
        <table className="dh-table">
          <thead>
            <tr>
              <th>Nome</th><th>E-mail</th><th>Função</th><th>Status</th>
            </tr>
          </thead>
          <tbody>
            {users.length === 0 && (
              <tr><td colSpan={4} className="text-center text-[var(--dh-muted)] py-10">
                Nenhum usuário ainda. Usuários são criados pelos módulos operacionais.
              </td></tr>
            )}
            {users.map((u) => (
              <tr key={u.id} data-testid={`user-row-${u.id}`}>
                <td className="font-semibold">{u.name}</td>
                <td className="text-[13px]">{u.email}</td>
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
