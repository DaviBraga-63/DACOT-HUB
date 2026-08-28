import { NavLink, useNavigate, Outlet } from "react-router-dom";
import { LayoutDashboard, Building2, Blocks, LogOut, User } from "lucide-react";
import { useAuth } from "@/context/AuthContext";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "menu-dashboard", end: true },
  { to: "/clientes", label: "Clientes", icon: Building2, testid: "menu-clientes" },
  { to: "/modulos", label: "Módulos", icon: Blocks, testid: "menu-modulos" },
];

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const initials = (user?.name || user?.email || "?")
    .split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();

  return (
    <div className="min-h-screen flex bg-[var(--dh-bg)]">
      {/* Sidebar */}
      <aside className="w-60 bg-white border-r border-[var(--dh-border)] flex flex-col" data-testid="sidebar">
        <div className="px-5 py-5 border-b border-[var(--dh-border)] flex items-center gap-2">
          <div className="w-7 h-7 bg-[var(--dh-accent)] rounded-sm flex items-center justify-center text-white font-black text-sm" style={{fontFamily:"Cabinet Grotesk"}}>D</div>
          <div className="leading-tight">
            <div className="font-black text-[15px] tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
            <div className="text-[10px] text-[var(--dh-muted)] uppercase tracking-widest font-bold">HUB</div>
          </div>
        </div>

        <nav className="flex-1 py-4">
          <div className="px-5 pb-2 text-[10px] uppercase tracking-widest text-[var(--dh-muted)] font-bold">Navegação</div>
          {NAV.map(({ to, label, icon: Icon, testid, end }) => (
            <NavLink
              key={to}
              to={to}
              end={end}
              data-testid={testid}
              className={({ isActive }) => `dh-sidebar-link ${isActive ? "dh-sidebar-link-active" : ""}`}
            >
              <Icon size={17} strokeWidth={1.6} />
              <span>{label}</span>
            </NavLink>
          ))}
        </nav>

        <div className="border-t border-[var(--dh-border)] px-4 py-3 flex items-center gap-3">
          <div className="w-8 h-8 bg-[var(--dh-neutral-bg)] rounded-sm flex items-center justify-center text-xs font-bold text-[var(--dh-text)]">
            {initials}
          </div>
          <div className="flex-1 min-w-0 leading-tight">
            <div className="text-[13px] font-semibold truncate" data-testid="user-name">{user?.name || "Admin"}</div>
            <div className="text-[11px] text-[var(--dh-muted)] truncate">{user?.email}</div>
          </div>
          <button onClick={async () => { await logout(); navigate("/login"); }}
                  data-testid="logout-btn" title="Sair"
                  className="p-2 hover:bg-[var(--dh-bg)] rounded-sm transition-colors">
            <LogOut size={15} strokeWidth={1.7} className="text-[var(--dh-muted)]" />
          </button>
        </div>
      </aside>

      {/* Main */}
      <main className="flex-1 min-w-0 overflow-x-hidden">
        <header className="h-14 bg-white border-b border-[var(--dh-border)] flex items-center justify-between px-8">
          <div className="flex items-center gap-3 text-sm text-[var(--dh-muted)]">
            <User size={14} strokeWidth={1.6} />
            <span>Painel administrativo interno</span>
          </div>
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">
            v1.0 • MVP
          </div>
        </header>
        <div className="p-8 dh-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
