import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api } from "@/lib/api";
import { Building2, FlaskConical, Blocks, LayoutGrid, ArrowRight } from "lucide-react";

export default function Dashboard() {
  const [stats, setStats] = useState(null);

  useEffect(() => {
    api.get("/hub/dashboard/stats").then((r) => setStats(r.data));
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

      <div>
        {/* Utilização por módulo */}
        <div className="dh-card p-6 sm:p-7">
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
                          background: 'var(--dh-accent-gradient)'
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

      </div>
    </div>
  );
}
