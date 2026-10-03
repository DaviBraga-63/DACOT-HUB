import { NavLink, Outlet, useNavigate } from "react-router-dom";
import { LayoutDashboard, Blocks, LogOut, Moon, Sun } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";

export default function PortalLayout() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const exit = async () => { await logout(); navigate("/login"); };

  return (
    <div className="min-h-screen bg-[var(--dh-bg)]">
      <header className="dh-topnav sticky top-0 z-30 h-[68px] flex items-center px-3 sm:px-8 lg:px-10">
        <div className="flex items-center gap-3 mr-2 sm:mr-12">
          <img src="/dacot-logo.png" alt="DACOT" className="dh-brand-logo dh-brand-logo-sm" />
          <span className="hidden sm:inline dh-font-display font-bold text-[15px] tracking-tight text-[var(--dh-text)]">DACOT</span>
        </div>
        <nav className="flex items-center gap-1 flex-1" aria-label="Navegação do portal">
          <PortalLink to="/portal" end icon={LayoutDashboard} label="Painel" testid="portal-nav-dashboard" />
          <PortalLink to="/portal/modulos" icon={Blocks} label="Módulos" testid="portal-nav-modules" />
        </nav>
        <div className="flex items-center gap-2">
          <div className="hidden sm:block text-right leading-tight mr-2">
            <div className="text-[12px] font-semibold text-[var(--dh-text)]">{user?.name}</div>
            <div className="text-[10px] text-[var(--dh-muted)]">{user?.email}</div>
          </div>
          <Tooltip><TooltipTrigger asChild><button type="button" onClick={toggleTheme} className="dh-topnav-action" data-testid="portal-theme-toggle" aria-label="Alternar tema">
            {theme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
          </button></TooltipTrigger><TooltipContent>Tema {theme === "dark" ? "claro" : "escuro"}</TooltipContent></Tooltip>
          <Tooltip><TooltipTrigger asChild><button type="button" onClick={exit} className="dh-topnav-action dh-topnav-logout" data-testid="portal-logout-btn" aria-label="Sair"><LogOut size={18} /></button></TooltipTrigger><TooltipContent>Sair</TooltipContent></Tooltip>
        </div>
      </header>
      <main className="px-5 sm:px-8 lg:px-10 py-8 lg:py-10"><Outlet /></main>
    </div>
  );
}

function PortalLink({ to, end, icon: Icon, label, testid }) {
  return <NavLink to={to} end={end} data-testid={testid} className={({ isActive }) => `dh-topnav-link ${isActive ? "dh-topnav-link-active" : ""}`}><Icon size={18} strokeWidth={1.75} /><span>{label}</span></NavLink>;
}
