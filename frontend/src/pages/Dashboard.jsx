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
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 mb-2" style={{fontFamily:"Cabinet Grotesk"}}>Visão geral</h1>
        <p className="text-[15px] text-slate-500">
          {stats
            ? `${stats.active} restaurantes ativos • ${stats.active_modules} módulos em operação`
            : "Resumo do estado atual da plataforma."}
        </p>
      </div>

      {/* KPIs — Premium card grid */}
      <div className="grid grid-cols-1 sm:grid-cols-2 xl:grid-cols-4 gap-5">
        {kpis.map(({ key, label, value, icon: Icon, testid }) => (
          <div
            key={key}
            className="dh-card p-6 group hover:shadow-lg transition-all duration-200 relative"
            data-testid={testid}
          >
            <div className="flex items-start justify-between mb-5">
              <div className="flex-1">
                <div className="dh-kpi-label mb-2">{label}</div>
                {value === undefined || value === null
                  ? <div className="dh-skeleton h-10 w-20" />
                  : <div className="dh-kpi-value dh-count-up">{value}</div>}
              </div>
              <div className="dh-icon-tile w-12 h-12 shrink-0">
                <Icon size={18} strokeWidth={1.8} />
              </div>
            </div>
            <div
              className="absolute top-0 left-0 h-1 rounded-t-lg bg-[var(--dh-accent)]"
              style={{ width: `${Math.min(100, (value || 0) * 10)}%` }}
            />
          </div>
        ))}
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-3 gap-5">
        {/* Utilização por módulo */}
        <div className="dh-card lg:col-span-2 p-6 sm:p-7">
          <div className="flex items-center justify-between mb-6">
            <div>
              <h2 className="text-lg font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Utilização por módulo</h2>
              <p className="text-[13px] text-slate-500 mt-0.5">Taxa de ativação por restaurante</p>
            </div>
            <Link to="/modulos" className="inline-flex items-center gap-1.5 text-[13px] font-semibold text-[var(--dh-accent)] hover:text-[var(--dh-accent-hover)] transition-colors group" data-testid="dash-catalog-link">
              Ver catálogo <ArrowRight size={14} strokeWidth={2} className="group-hover:translate-x-1 transition-transform" />
            </Link>
          </div>
          <div className="space-y-5">
            {!stats && [0,1,2,3].map((i) => (
              <div key={i} className="flex items-center gap-4">
                <div className="dh-skeleton h-4 w-28" />
                <div className="dh-skeleton h-3 flex-1" />
                <div className="dh-skeleton h-4 w-12" />
              </div>
            ))}
            {stats && (stats.per_module || []).map((m) => {
              const total = stats.total_tenants || 1;
              const pct = Math.round(((m.activations || 0) / total) * 100);
              return (
                <div key={m.key} className="group">
                  <div className="flex items-center gap-4 mb-2">
                    <div className="w-28 sm:w-32 text-[14px] font-medium text-slate-700 truncate">{m.name}</div>
                    <div className="flex-1 h-2 bg-slate-100 rounded-full overflow-hidden">
                      <div
                        className="h-full rounded-full transition-[width] duration-700 ease-out"
                        style={{
                          width: `${pct}%`,
                          background: 'linear-gradient(135deg, #1B73B8 0%, #32A5DC 100%)'
                        }}
                      />
                    </div>
                    <div className="w-14 text-right text-[13px] text-slate-600 font-semibold tabular-nums">
                      {pct}%
                    </div>
                  </div>
                  <div className="text-[11px] text-slate-400">
                    {m.activations} de {total} restaurantes
                  </div>
                </div>
              );
            })}
            {stats && stats.per_module?.length === 0 && (
              <div className="text-[14px] text-slate-500 text-center py-8">Nenhum módulo cadastrado.</div>
            )}
          </div>
        </div>

        {/* Atividade recente */}
        <div className="dh-card p-6 sm:p-7" data-testid="activity-feed">
          <div className="flex items-center gap-2.5 mb-5">
            <div className="dh-icon-tile w-9 h-9">
              <Activity size={16} strokeWidth={1.8} />
            </div>
            <h2 className="text-lg font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Atividade</h2>
          </div>
          <ul className="space-y-4">
            {activity === null && [0,1,2,3].map((i) => (
              <li key={i} className="space-y-2">
                <div className="dh-skeleton h-4 w-full" />
                <div className="dh-skeleton h-3 w-20" />
              </li>
            ))}
            {activity?.length === 0 && (
              <li className="text-[13px] text-slate-500 text-center py-8">Sem atividade</li>
            )}
            {activity?.map((it) => (
              <li key={it.id} className="pb-4 border-b border-slate-100 last:border-b-0 last:pb-0">
                <ActionLabel item={it} />
                <div className="text-[11px] text-slate-400 mt-1.5">{timeAgo(it.created_at)}</div>
              </li>
            ))}
          </ul>
        </div>
      </div>
    </div>
  );
}
