import { useEffect, useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { LogOut, ArrowUpRight, ClipboardList, ChefHat, Users, Boxes, Landmark, Bike, Package } from "lucide-react";

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

  useEffect(() => {
    if (user?.user_type === "staff") return;
    api.get("/portal/context")
      .then((r) => setCtx(r.data))
      .catch((e) => setErr(formatApiErrorDetail(e.response?.data?.detail)));
  }, [user?.user_type]);

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
      <header className="bg-white/90 backdrop-blur-md border-b border-slate-200 sticky top-0 z-20">
        <div className="max-w-3xl mx-auto px-5 sm:px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2.5">
            <div className="w-7 h-7 bg-[var(--dh-accent)] rounded-lg flex items-center justify-center text-white font-bold text-[13px]" style={{fontFamily:"Cabinet Grotesk"}}>D</div>
            <div className="font-bold text-[14px] tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight hidden sm:block">
              <div className="text-[13px] font-semibold text-slate-900" data-testid="portal-user-name">{user?.name}</div>
              <div className="text-[11px] text-slate-400" data-testid="portal-user-role">{ROLE_LABEL[user?.role] || user?.role}</div>
            </div>
            <button onClick={async () => { await logout(); navigate("/login"); }}
                    data-testid="portal-logout-btn" title="Sair"
                    className="p-2 rounded-lg hover:bg-slate-100 transition-colors">
              <LogOut size={15} strokeWidth={1.8} className="text-slate-500" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-5 sm:px-6 pt-12 sm:pt-16 pb-12">
        {err && <div className="dh-chip dh-chip-error" data-testid="portal-error">{err}</div>}
        {!ctx && !err && (
          <div className="space-y-6">
            <div className="space-y-3">
              <div className="dh-skeleton h-4 w-24" />
              <div className="dh-skeleton h-9 w-64" />
            </div>
            <div className="dh-card p-2 space-y-2">
              {[0,1,2].map((i) => <div key={i} className="dh-skeleton h-16 rounded-lg" />)}
            </div>
          </div>
        )}

        {ctx && (
          <div className="space-y-8 dh-fade-in">
            <div>
              <div className="text-[13px] text-slate-500 font-medium mb-1.5">Olá, {firstName}</div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}} data-testid="portal-tenant-name">
                  {ctx.tenant.name}
                </h1>
                <span className={`dh-chip ${tenantStatus.cls}`} data-testid="portal-tenant-status">{tenantStatus.label}</span>
              </div>
            </div>

            <section>
              <h2 className="text-[11px] uppercase tracking-widest font-semibold text-slate-400 mb-3">Seus módulos</h2>
              <div className="dh-card divide-y divide-slate-100" data-testid="portal-modules">
                {ctx.modules.map((m) => {
                  const Icon = ICONS[m.icon] || Package;
                  return (
                    <div key={m.key} className="flex items-center gap-4 px-5 py-4" data-testid={`portal-module-${m.key}`}>
                      <span className={`${m.active ? "dh-icon-tile" : "dh-icon-tile-neutral"} w-10 h-10 shrink-0`}>
                        <Icon size={18} strokeWidth={1.6} />
                      </span>
                      <div className="flex-1 min-w-0">
                        <div className="text-[15px] font-semibold text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
                        <div className="text-[12px] text-slate-400 truncate">{m.description}</div>
                      </div>
                      {m.active ? (
                        <div className="flex items-center gap-3 shrink-0">
                          <span className="dh-chip dh-chip-success hidden sm:inline-flex">Ativo</span>
                          <button className="dh-btn dh-btn-primary" onClick={() => openModule(m)}
                                  data-testid={`portal-open-${m.key}`}>
                            Abrir módulo <ArrowUpRight size={14} strokeWidth={2} />
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

            <p className="text-[12px] text-slate-400">
              Precisa de um módulo inativo? Fale com a equipe DACOT para solicitar a ativação.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
