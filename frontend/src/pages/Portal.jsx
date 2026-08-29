import { useEffect, useState } from "react";
import { useNavigate, Navigate } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";
import { LogOut, ExternalLink, ClipboardList, ChefHat, Users, Boxes, Landmark, Bike, Package } from "lucide-react";

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

  return (
    <div className="min-h-screen bg-[var(--dh-bg)]" data-testid="portal-page">
      <header className="bg-white border-b border-[var(--dh-border)]">
        <div className="max-w-3xl mx-auto px-6 h-14 flex items-center justify-between">
          <div className="flex items-center gap-2">
            <div className="w-7 h-7 bg-[var(--dh-accent)] rounded-sm flex items-center justify-center text-white font-black text-sm" style={{fontFamily:"Cabinet Grotesk"}}>D</div>
            <div className="leading-tight">
              <div className="font-black text-[14px] tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
              <div className="text-[9px] text-[var(--dh-muted)] uppercase tracking-widest font-bold">Portal do restaurante</div>
            </div>
          </div>
          <div className="flex items-center gap-3">
            <div className="text-right leading-tight hidden sm:block">
              <div className="text-[13px] font-semibold" data-testid="portal-user-name">{user?.name}</div>
              <div className="text-[11px] text-[var(--dh-muted)]" data-testid="portal-user-role">{ROLE_LABEL[user?.role] || user?.role}</div>
            </div>
            <button onClick={async () => { await logout(); navigate("/login"); }}
                    data-testid="portal-logout-btn" title="Sair"
                    className="p-2 hover:bg-[var(--dh-bg)] rounded-sm transition-colors">
              <LogOut size={15} strokeWidth={1.7} className="text-[var(--dh-muted)]" />
            </button>
          </div>
        </div>
      </header>

      <main className="max-w-3xl mx-auto px-6 py-10">
        {err && <div className="dh-chip dh-chip-error" data-testid="portal-error">{err}</div>}
        {!ctx && !err && <div className="text-sm text-[var(--dh-muted)]">Carregando…</div>}

        {ctx && (
          <div className="space-y-6 dh-fade-in">
            <div>
              <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-1">Seu restaurante</div>
              <div className="flex items-center gap-3 flex-wrap">
                <h1 className="text-3xl lg:text-4xl font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}} data-testid="portal-tenant-name">
                  {ctx.tenant.name}
                </h1>
                <span className={`dh-chip ${tenantStatus.cls}`} data-testid="portal-tenant-status">{tenantStatus.label}</span>
              </div>
              <p className="text-sm text-[var(--dh-muted)] mt-2">
                Estes são os módulos DACOT disponíveis para o seu restaurante.
              </p>
            </div>

            <div className="dh-card divide-y divide-[var(--dh-border)]" data-testid="portal-modules">
              {ctx.modules.map((m) => {
                const Icon = ICONS[m.icon] || Package;
                return (
                  <div key={m.key} className="flex items-center gap-4 px-5 py-4" data-testid={`portal-module-${m.key}`}>
                    <div className="w-10 h-10 border border-[var(--dh-border)] rounded-sm flex items-center justify-center bg-[var(--dh-bg)] shrink-0">
                      <Icon size={18} strokeWidth={1.5} className="text-[var(--dh-text)]" />
                    </div>
                    <div className="flex-1 min-w-0">
                      <div className="text-[15px] font-bold" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
                      <div className="text-[12px] text-[var(--dh-muted)] truncate">{m.description}</div>
                    </div>
                    {m.active ? (
                      <>
                        <span className="dh-chip dh-chip-success">Ativo</span>
                        <button className="dh-btn dh-btn-primary" onClick={() => openModule(m)}
                                data-testid={`portal-open-${m.key}`}>
                          <ExternalLink size={13} strokeWidth={1.8} /> Abrir
                        </button>
                      </>
                    ) : (
                      <span className="dh-chip dh-chip-neutral">Inativo</span>
                    )}
                  </div>
                );
              })}
            </div>

            <p className="text-[12px] text-[var(--dh-muted)]">
              Precisa de um módulo inativo? Fale com a equipe DACOT para solicitar a ativação.
            </p>
          </div>
        )}
      </main>
    </div>
  );
}
