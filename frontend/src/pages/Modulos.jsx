import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { ClipboardList, ChefHat, Users, Boxes, Landmark, Bike, Package } from "lucide-react";

const ICONS = {
  "clipboard-list": ClipboardList, "chef-hat": ChefHat, "users": Users,
  "boxes": Boxes, "landmark": Landmark, "bike": Bike,
};

export default function Modulos() {
  const [mods, setMods] = useState([]);

  useEffect(() => { api.get("/hub/modules").then((r) => setMods(r.data)); }, []);

  return (
    <div className="space-y-6" data-testid="modulos-page">
      <div>
        <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-1">Catálogo</div>
        <h1 className="text-3xl lg:text-4xl font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>Módulos DACOT</h1>
        <p className="text-sm text-[var(--dh-muted)] mt-1">
          Ecossistema de módulos disponibilizados aos restaurantes. Novos módulos serão adicionados sem impacto arquitetural.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
        {mods.map((m) => {
          const Icon = ICONS[m.icon] || Package;
          return (
            <div key={m.key} className="dh-card p-6 flex flex-col" data-testid={`catalog-${m.key}`}>
              <div className="flex items-start justify-between mb-4">
                <div className="w-11 h-11 border border-[var(--dh-border)] rounded-sm flex items-center justify-center bg-[var(--dh-bg)]">
                  <Icon size={20} strokeWidth={1.5} className="text-[var(--dh-text)]" />
                </div>
                <StatusBadge status={m.status} />
              </div>
              <div className="text-[18px] font-black tracking-tight mb-1" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
              <div className="text-[11px] text-[var(--dh-muted)] font-mono mb-3">{m.category || "—"}</div>
              <p className="text-[13px] text-[var(--dh-muted)] leading-relaxed flex-1">{m.description}</p>
              <div className="mt-4 pt-3 border-t border-[var(--dh-border)] text-[11px] text-[var(--dh-muted)] font-mono">
                key: <b className="text-[var(--dh-text)]">{m.key}</b>
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
