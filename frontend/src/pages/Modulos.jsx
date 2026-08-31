import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import StatusBadge from "@/components/StatusBadge";
import { ClipboardList, ChefHat, Users, Boxes, Landmark, Bike, Package } from "lucide-react";

const ICONS = {
  "clipboard-list": ClipboardList, "chef-hat": ChefHat, "users": Users,
  "boxes": Boxes, "landmark": Landmark, "bike": Bike,
};

export default function Modulos() {
  const [mods, setMods] = useState(null);

  useEffect(() => { api.get("/hub/modules").then((r) => setMods(r.data)); }, []);

  return (
    <div className="space-y-6" data-testid="modulos-page">
      <div>
        <h1 className="text-2xl sm:text-3xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Módulos DACOT</h1>
        <p className="text-sm text-slate-500 mt-1.5">
          Catálogo de módulos do ecossistema, disponibilizados individualmente para cada restaurante.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {!mods && [0,1,2,3,4,5].map((i) => (
          <div key={i} className="dh-card p-6 space-y-4">
            <div className="flex items-start justify-between">
              <div className="dh-skeleton w-11 h-11 rounded-xl" />
              <div className="dh-skeleton h-5 w-24 rounded-full" />
            </div>
            <div className="dh-skeleton h-5 w-32" />
            <div className="dh-skeleton h-3.5 w-full" />
            <div className="dh-skeleton h-3.5 w-4/5" />
          </div>
        ))}
        {mods?.map((m) => {
          const Icon = ICONS[m.icon] || Package;
          return (
            <div key={m.key} className="dh-card dh-card-hover p-6 flex flex-col" data-testid={`catalog-${m.key}`}>
              <div className="flex items-start justify-between mb-5">
                <span className="dh-icon-tile w-11 h-11 rounded-xl">
                  <Icon size={20} strokeWidth={1.6} />
                </span>
                <StatusBadge status={m.status} />
              </div>
              <div className="text-lg font-semibold tracking-tight text-slate-900 mb-1" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
              <div className="text-[11px] text-slate-400 font-medium uppercase tracking-wider mb-3">{m.category || "Módulo"}</div>
              <p className="text-[13px] text-slate-500 leading-relaxed flex-1">{m.description}</p>
              <div className="mt-5 pt-4 border-t border-slate-100 flex items-center justify-between text-[11px] text-slate-400 font-mono">
                <span>key: <b className="text-slate-600 font-semibold">{m.key}</b></span>
                {m.status === "available" && <span className="text-emerald-600 font-sans font-medium">Pronto para ativação</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
