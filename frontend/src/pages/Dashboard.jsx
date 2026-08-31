import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Activity, Building2, FlaskConical, Blocks, LayoutGrid, ArrowRight } from "lucide-react";

const ACTION_LABEL = {
  "hub_user.login": "Fez login no Hub",
  "restaurant_user.login": "acessou o portal",
  "tenant.created": "criou o cliente",
  "tenant.status_changed": "alterou o status de",
  "tenant.deleted": "removeu o cliente",
  "module.activated": "ativou o módulo",
  "module.deactivated": "desativou o módulo",
  "module.launch_token_issued": "abriu o módulo",
};

function ActionLabel({ item }) {
  const label = ACTION_LABEL[item.action] || item.action.replace(/_/g, " ");
  const target = item.metadata?.name || item.metadata?.tenant_name || "";
  const mod = item.metadata?.module ? ` — ${item.metadata.module}` : "";
  return (
    <span className="text-[13px] text-slate-700 leading-snug">
      <span className="font-semibold text-slate-900">{item.actor_name}</span>{" "}
      <span className="text-slate-500">{label}</span>{" "}
      <span className="font-semibold text-slate-900">{target}{mod}</span>
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
  const [activity, setActivity] = useState(null);

  useEffect(() => {
    api.get("/hub/dashboard/stats").then((r) => setStats(r.data));
    api.get("/hub/dashboard/activity", { params: { limit: 12 } }).then((r) => setActivity(r.data));
  }, []);

  const kpis = [
    { key: "active", label: "Restaurantes ativos", value: stats?.active, icon: Building2, testid: "kpi-active" },
    { key: "trial", label: "Em teste", value: stats?.trial, icon: FlaskConical, testid: "kpi-trial" },
    { key: "total", label: "Restaurantes cadastrados", value: stats?.total_tenants, icon: LayoutGrid, testid: "kpi-total" },
    { key: "mods", label: "Módulos ativos", value: stats?.active_modules, icon: Blocks, testid: "kpi-modules" },
  ];

  return (
    <div className="space-y-8" data-testid="dashboard-page">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Visão geral</h1>
        <p className="text-sm text-slate-500 mt-1.5">
          {stats
            ? `A plataforma tem ${stats.active} restaurantes ativos e ${stats.active_modules} ativações de módulos neste momento.`
            : "Resumo do estado atual da plataforma."}
        </p>
      </div>

      {/* KPIs */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {kpis.map(({ key, label, value, icon: Icon, testid }) => (
          <div key={key} className="dh-card p-5" data-testid={testid}>
            <div className="flex items-center justify-between mb-4">
              <span className="dh-kpi-label">{label}</span>
              <span className="dh-icon-tile-neutral w-8 h-8">
                <Icon size={15} strokeWidth={1.8} />
              </span>
            </div>
            {value === undefined || value === null
              ? <div className="dh-skeleton h-9 w-14" />
              : <div className="dh-kpi-value">{value}</div>}
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Utilização por módulo */}
        <div className="dh-card lg:col-span-2 p-6 sm:p-7">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-base font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Utilização por módulo</h2>
              <p className="text-[13px] text-slate-500 mt-0.5">Ativações ativas por restaurante</p>
            </div>
            <Link to="/modulos" className="inline-flex items-center gap-1 text-[13px] font-medium text-[var(--dh-accent)] hover:text-[var(--dh-accent-hover)] transition-colors" data-testid="dash-catalog-link">
              Ver catálogo <ArrowRight size={13} strokeWidth={2} />
            </Link>
          </div>
          <div className="space-y-4">
            {!stats && [0,1,2,3].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="dh-skeleton h-4 w-28" />
                <div className="dh-skeleton h-2 flex-1" />
                <div className="dh-skeleton h-4 w-12" />
              </div>
            ))}
            {stats && (stats.per_module || []).map((m) => {
              const total = stats.total_tenants || 1;
              const pct = Math.round(((m.activations || 0) / total) * 100);
              return (
                <div key={m.key} className="flex items-center gap-4">
                  <div className="w-28 sm:w-36 text-[13px] font-medium text-slate-700 truncate">{m.name}</div>
                  <div className="flex-1 h-1.5 bg-slate-100 rounded-full overflow-hidden">
                    <div className="h-full bg-[var(--dh-accent)] rounded-full transition-[width] duration-500 ease-out" style={{ width: `${pct}%` }} />
                  </div>
                  <div className="w-16 text-right text-[12px] text-slate-500 tabular-nums">
                    <span className="font-semibold text-slate-900">{m.activations}</span> / {stats.total_tenants}
                  </div>
                </div>
              );
            })}
            {stats && stats.per_module?.length === 0 && (
              <div className="text-sm text-slate-500">Nenhum módulo cadastrado.</div>
            )}
          </div>
        </div>

        {/* Atividade recente */}
        <div className="dh-card p-6 sm:p-7" data-testid="activity-feed">
          <div className="flex items-center gap-2 mb-5">
            <Activity size={15} strokeWidth={1.8} className="text-[var(--dh-accent)]" />
            <h2 className="text-base font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Atividade recente</h2>
          </div>
          <ul className="space-y-4">
            {activity === null && [0,1,2,3].map((i) => (
              <li key={i} className="space-y-2">
                <div className="dh-skeleton h-3.5 w-full" />
                <div className="dh-skeleton h-3 w-16" />
              </li>
            ))}
            {activity?.length === 0 && (
              <li className="text-sm text-slate-500">Sem atividade ainda.</li>
            )}
            {activity?.map((it) => (
              <li key={it.id} className="pb-4 border-b border-slate-100 last:border-b-0 last:pb-0">
                <ActionLabel item={it} />
                <div className="text-[11px] text-slate-400 mt-1">{timeAgo(it.created_at)}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
