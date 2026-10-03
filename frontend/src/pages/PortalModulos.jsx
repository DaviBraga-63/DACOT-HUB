import { useEffect, useState } from "react";
import { ArrowUpRight, Package } from "lucide-react";
import { toast } from "sonner";
import { api, formatApiErrorDetail } from "@/lib/api";
import { getModuleIcon } from "@/lib/moduleIcons";
import { isReleasedModule } from "@/lib/releasedModules";

export default function PortalModulos() {
  const [modules, setModules] = useState(null);
  const [error, setError] = useState(null);
  const [opening, setOpening] = useState(null);

  useEffect(() => {
    let active = true;
    api.get("/portal/context")
      .then(({ data }) => {
        if (!active) return;
        setModules((data.modules || []).filter((module) => (
          isReleasedModule(module) && module.active && module.status === "available"
        )));
      })
      .catch((requestError) => active && setError(formatApiErrorDetail(requestError.response?.data?.detail)));
    return () => { active = false; };
  }, []);

  const openModule = async (module) => {
    setOpening(module.key);
    try {
      const { data } = await api.post(`/portal/modules/${module.key}/launch-token`);
      if (!data?.handoff || !data?.launch_url) throw new Error("Resposta de acesso ao módulo inválida.");
      const separator = data.launch_url.includes("?") ? "&" : "?";
      window.open(`${data.launch_url}${separator}handoff=${encodeURIComponent(data.handoff)}`, "_blank", "noopener,noreferrer");
    } catch (requestError) {
      toast.error(formatApiErrorDetail(requestError.response?.data?.detail || requestError.message));
    } finally {
      setOpening(null);
    }
  };

  return (
    <div className="max-w-5xl space-y-7 dh-fade-in" data-testid="portal-modules-page">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[var(--dh-muted)]">Módulos</p>
        <h1 className="dh-font-display mt-2 text-3xl font-bold tracking-tight text-[var(--dh-text)]">Módulos disponíveis</h1>
        <p className="mt-2 text-sm text-[var(--dh-muted)]">Acesse os módulos ativos para o seu restaurante.</p>
      </div>

      {error && <div className="dh-chip dh-chip-error" data-testid="portal-modules-error">{error}</div>}
      {!modules && !error && <div className="grid grid-cols-1 gap-5 md:grid-cols-2"><div className="dh-card p-6 space-y-4"><div className="dh-skeleton h-12 w-12 rounded-lg" /><div className="dh-skeleton h-5 w-32" /><div className="dh-skeleton h-4 w-full" /></div></div>}
      {modules?.length === 0 && <div className="dh-card p-8 text-sm text-[var(--dh-muted)]" data-testid="portal-modules-empty">Nenhum módulo está disponível para este restaurante.</div>}
      {modules?.length > 0 && <div className="grid grid-cols-1 gap-5 md:grid-cols-2">
        {modules.map((module) => {
          const Icon = getModuleIcon(module.icon) || Package;
          return <article key={module.key} className="dh-card p-6" data-testid={`portal-module-${module.key}`}>
            <div className="flex items-start justify-between gap-4">
              <span className="dh-icon-tile h-12 w-12 rounded-lg"><Icon size={22} strokeWidth={1.65} /></span>
              <span className="dh-chip dh-chip-success">Disponível</span>
            </div>
            <h2 className="dh-font-display mt-5 text-xl font-bold text-[var(--dh-text)]">{module.name}</h2>
            <p className="mt-2 text-sm leading-6 text-[var(--dh-muted)]">{module.description}</p>
            <button type="button" className="dh-btn dh-btn-primary mt-6" onClick={() => openModule(module)} disabled={opening === module.key} data-testid={`portal-open-${module.key}`}>
              {opening === module.key ? "Abrindo…" : "Abrir módulo"} <ArrowUpRight size={16} strokeWidth={1.8} />
            </button>
          </article>;
        })}
      </div>}
    </div>
  );
}
