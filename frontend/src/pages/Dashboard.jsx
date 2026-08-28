import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Activity, Building2, FlaskConical, Blocks, Users } from "lucide-react";

const ACTION_LABEL = {
  "hub_user.login": "Fez login no Hub",
  "tenant.created": "criou o cliente",
  "tenant.status_changed": "alterou o status de",
  "tenant.deleted": "removeu o cliente",
  "module.activated": "ativou o módulo",
  "module.deactivated": "desativou o módulo",
};

function ActionLabel({ item }) {
  const label = ACTION_LABEL[item.action] || item.action;
  const target = item.metadata?.name || item.metadata?.tenant_name || "";
  const mod = item.metadata?.module ? ` — ${item.metadata.module}` : "";
  return (
    <span className="text-[13px] text-[var(--dh-text)]">
      <span className="font-semibold">{item.actor_name}</span>{" "}
      <span className="text-[var(--dh-muted)]">{label}</span>{" "}
      <span className="font-semibold">{target}{mod}</span>
    </span>
  );
}

function timeAgo(iso) {
  if (!iso) return "";
  const d = new Date(iso);
  const s = Math.floor((Date.now() - d.getTime()) / 1000);
  if (s < 60) return `há ${s}s`;
  const m = Math.floor(s / 60);
  if (m < 60) return `há ${m}min`;
  const h = Math.floor(m / 60);
  if (h < 24) return `há ${h}h`;
  return d.toLocaleDateString("pt-BR");
}

export default function Dashboard() {
  const [stats, setStats] = useState(null);
  const [activity, setActivity] = useState([]);

  useEffect(() => {
    api.get("/hub/dashboard/stats").then((r) => setStats(r.data));
    api.get("/hub/dashboard/activity", { params: { limit: 12 } }).then((r) => setActivity(r.data));
  }, []);

  const kpis = [
    { key: "active", label: "Clientes ativos", value: stats?.active ?? "—", icon: Building2, testid: "kpi-active" },
    { key: "trial", label: "Em teste", value: stats?.trial ?? "—", icon: FlaskConical, testid: "kpi-trial" },
    { key: "total", label: "Total restaurantes", value: stats?.total_tenants ?? "—", icon: Users, testid: "kpi-total" },
    { key: "mods", label: "Módulos ativos", value: stats?.active_modules ?? "—", icon: Blocks, testid: "kpi-modules" },
  ];

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-1">Visão geral</div>
          <h1 className="text-3xl lg:text-4xl font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>Dashboard</h1>
        </div>
      </div>

      {/* KPIs — dense bento */}
      <div className="dh-grid grid grid-cols-1 md:grid-cols-4">
        {kpis.map(({ key, label, value, icon: Icon, testid }) => (
          <div key={key} className="dh-grid-cell p-5 min-h-[110px] flex flex-col justify-between" data-testid={testid}>
            <div className="flex items-center justify-between">
              <span className="dh-kpi-label">{label}</span>
              <Icon size={16} strokeWidth={1.6} className="text-[var(--dh-muted)]" />
            </div>
            <div className="dh-kpi-value">{value}</div>
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
        {/* Utilization by module */}
        <div className="dh-card lg:col-span-2 p-6">
          <div className="flex items-center justify-between mb-5">
            <div>
              <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">Utilização por módulo</div>
              <div className="text-lg font-bold" style={{fontFamily:"Cabinet Grotesk"}}>Ativações ativas</div>
            </div>
            <Link to="/modulos" className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)]" data-testid="dash-catalog-link">
              Ver catálogo →
            </Link>
          </div>
          <div className="space-y-3">
            {(stats?.per_module || []).map((m) => {
              const total = stats?.total_tenants || 1;
              const pct = Math.round(((m.activations || 0) / total) * 100);
              return (
                <div key={m.key} className="flex items-center gap-4">
                  <div className="w-40 text-[13px] font-semibold truncate">{m.name}</div>
                  <div className="flex-1 h-2 bg-[var(--dh-neutral-bg)] rounded-sm overflow-hidden">
                    <div className="h-full bg-[var(--dh-accent)] transition-[width] duration-300" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="w-24 text-right text-[12px] text-[var(--dh-muted)] tabular-nums">
                    <span className="font-bold text-[var(--dh-text)]">{m.activations}</span> / {stats?.total_tenants}
                  </div>
                </div>
              );
            })}
            {stats && stats.per_module?.length === 0 && (
              <div className="text-sm text-[var(--dh-muted)]">Nenhum módulo cadastrado.</div>
            )}
          </div>
        </div>

        {/* Activity */}
        <div className="dh-card p-6" data-testid="activity-feed">
          <div className="flex items-center gap-2 mb-4">
            <Activity size={14} strokeWidth={1.7} className="text-[var(--dh-accent)]" />
            <div className="text-[11px] uppercase tracking-widest font-bold">Atividade recente</div>
          </div>
          <ul className="space-y-3">
            {activity.length === 0 && (
              <li className="text-sm text-[var(--dh-muted)]">Sem atividade ainda.</li>
            )}
            {activity.map((it) => (
              <li key={it.id} className="pb-3 border-b border-[var(--dh-border)] last:border-b-0 last:pb-0">
                <ActionLabel item={it} />
                <div className="text-[11px] text-[var(--dh-muted)] mt-1">{timeAgo(it.created_at)}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
