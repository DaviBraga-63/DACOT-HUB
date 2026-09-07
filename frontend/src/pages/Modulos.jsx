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
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 mb-2" style={{fontFamily:"Cabinet Grotesk"}}>Módulos DACOT</h1>
        <p className="text-[15px] text-slate-500">
          Catálogo de módulos do ecossistema disponibilizados para cada restaurante.
        </p>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 xl:grid-cols-3 gap-5">
        {!mods && [0,1,2,3,4,5].map((i) => (
          <div key={i} className="dh-card p-6 space-y-4">
            <div className="flex items-start justify-between">
              <div className="dh-skeleton w-12 h-12 rounded-xl" />
              <div className="dh-skeleton h-6 w-24 rounded-full" />
            </div>
            <div className="dh-skeleton h-6 w-32" />
            <div className="dh-skeleton h-4 w-full" />
            <div className="dh-skeleton h-4 w-4/5" />
          </div>
        ))}
        {mods?.map((m, idx) => {
          const Icon = ICONS[m.icon] || Package;
          return (
            <div 
              key={m.key} 
              className="dh-card dh-card-hover p-6 flex flex-col group" 
              data-testid={`catalog-${m.key}`}
              style={{
                animation: `dhFadeIn 0.3s ease-out ${idx * 50}ms both`
              }}
            >
              <div className="flex items-start justify-between mb-5">
                <span className="dh-icon-tile w-12 h-12 rounded-lg group-hover:scale-110 transition-transform duration-200">
                  <Icon size={22} strokeWidth={1.6} />
                </span>
                <StatusBadge status={m.status} />
              </div>
              <div className="text-[18px] font-bold tracking-tight text-slate-900 mb-1" style={{fontFamily:"Cabinet Grotesk"}}>{m.name}</div>
              <div className="text-[11px] text-slate-400 font-semibold uppercase tracking-wider mb-3">{m.category || "Módulo"}</div>
              <p className="text-[13px] text-slate-600 leading-relaxed flex-1 mb-5">{m.description}</p>
              <div className="pt-5 border-t border-slate-100 flex items-center justify-between text-[11px]">
                <span className="text-slate-500 font-mono">key: <b className="text-slate-700">{m.key}</b></span>
                {m.status === "available" && <span className="text-emerald-600 font-medium">Pronto</span>}
              </div>
            </div>
          );
        })}
      </div>
    </div>
  );
}
