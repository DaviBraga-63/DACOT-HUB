import { useState } from "react";
import { NavLink, useNavigate, Outlet, Navigate } from "react-router-dom";
import { LayoutDashboard, Building2, Blocks, LogOut, Settings, Menu, X } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { toast } from "sonner";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "menu-dashboard", end: true },
  { to: "/clientes", label: "Clientes", icon: Building2, testid: "menu-clientes" },
  { to: "/modulos", label: "Módulos", icon: Blocks, testid: "menu-modulos" },
];

function Brand() {
  return (
    <div className="flex items-center gap-3">
      <div 
        className="w-10 h-10 rounded-lg flex items-center justify-center text-white font-bold text-base shadow-md"
        style={{
          background: 'linear-gradient(135deg, #1B73B8 0%, #32A5DC 100%)',
          fontFamily: 'Cabinet Grotesk'
        }}
      >
        D
      </div>
      <div className="leading-tight hidden sm:block">
        <div className="font-bold text-sm tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>DACOT</div>
        <div className="text-[9px] text-slate-400 uppercase tracking-widest font-semibold">Hub</div>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const navigate = useNavigate();
  const [drawer, setDrawer] = useState(false);

  // Restaurant clients never enter the DACOT admin area (UX redirect — backend
  // is the real enforcement, all /api/hub/* endpoints require staff).
  if (user?.user_type === "restaurant") {
    return <Navigate to="/portal" replace />;
  }

  const initials = (user?.name || user?.email || "?")
    .split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();

  const doLogout = async () => { await logout(); navigate("/login"); };

  const navItems = (onNavigate) => NAV.map(({ to, label, icon: Icon, testid, end }) => (
    <NavLink
      key={to}
      to={to}
      end={end}
      data-testid={testid}
      onClick={onNavigate}
      className={({ isActive }) => `dh-sidebar-link ${isActive ? "dh-sidebar-link-active" : ""}`}
    >
      <Icon size={17} strokeWidth={1.8} />
      <span>{label}</span>
    </NavLink>
  ));

  const bottomSection = (
    <div className="border-t border-slate-100 px-3 py-4 space-y-1">
      <div className="flex items-center gap-3 px-3 py-2.5 rounded-lg">
        <div className="w-10 h-10 rounded-full flex items-center justify-center text-[14px] font-bold text-white shrink-0" 
             style={{ background: 'linear-gradient(135deg, #1B73B8 0%, #32A5DC 100%)' }}>
          {initials}
        </div>
        <div className="flex-1 min-w-0 leading-tight">
          <div className="text-[13px] font-semibold text-slate-900 truncate" data-testid="user-name">{user?.name || "Admin"}</div>
          <div className="text-[11px] text-slate-400 truncate">{user?.email}</div>
        </div>
      </div>
      <button
        onClick={() => toast.info("Configurações estarão disponíveis em breve.")}
        data-testid="menu-configuracoes"
        className="dh-sidebar-link w-full text-left"
      >
        <Settings size={17} strokeWidth={1.8} />
        <span>Configurações</span>
      </button>
      <button
        onClick={doLogout}
        data-testid="logout-btn"
        className="dh-sidebar-link w-full text-left"
      >
        <LogOut size={17} strokeWidth={1.8} />
        <span>Sair</span>
      </button>
    </div>
  );

  return (
    <div className="min-h-screen flex bg-[var(--dh-bg)]">
      {/* Sidebar — desktop */}
      <aside className="hidden lg:flex w-64 bg-white border-r border-slate-200 flex-col fixed inset-y-0 z-30" data-testid="sidebar">
        <div className="px-5 py-6 border-b border-slate-100">
          <Brand />
        </div>
        <nav className="flex-1 py-5 overflow-y-auto">
          <div className="px-6 pb-3 text-[10px] uppercase tracking-widest text-slate-400 font-semibold">Navegação</div>
          {navItems()}
        </nav>
        {bottomSection}
      </aside>

      {/* Topbar — mobile */}
      <div className="lg:hidden fixed top-0 inset-x-0 z-40 h-16 bg-white/95 backdrop-blur-md border-b border-slate-200 flex items-center justify-between px-4">
        <Brand />
        <button onClick={() => setDrawer(true)} data-testid="mobile-menu-btn"
                className="p-2 rounded-lg hover:bg-slate-100 transition-colors" aria-label="Abrir menu">
          <Menu size={20} strokeWidth={1.8} className="text-slate-700" />
        </button>
      </div>

      {/* Drawer — mobile */}
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div 
            className="absolute inset-0 bg-slate-900/40 backdrop-blur-sm" 
            onClick={() => setDrawer(false)} 
          />
          <aside className="absolute inset-y-0 left-0 w-72 bg-white shadow-xl flex flex-col dh-slide-in" data-testid="mobile-drawer">
            <div className="px-5 py-5 border-b border-slate-100 flex items-center justify-between">
              <Brand />
              <button onClick={() => setDrawer(false)} className="p-2 rounded-lg hover:bg-slate-100 transition-colors" aria-label="Fechar menu">
                <X size={18} strokeWidth={1.8} className="text-slate-500" />
              </button>
            </div>
            <nav className="flex-1 py-4 overflow-y-auto">
              <div className="px-6 pb-2 text-[10px] uppercase tracking-widest text-slate-400 font-semibold">Navegação</div>
              {navItems(() => setDrawer(false))}
            </nav>
            {bottomSection}
          </aside>
        </div>
      )}

      {/* Main */}
      <main className="flex-1 min-w-0 lg:pl-64 pt-16 lg:pt-0">
        <div className="px-5 sm:px-8 lg:px-10 py-8 max-w-[1400px] dh-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
