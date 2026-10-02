import { useEffect, useRef, useState } from "react";
import { NavLink, useLocation, useNavigate, Outlet, Navigate } from "react-router-dom";
import { LayoutDashboard, Building2, Blocks, Users, LogOut, Settings, Menu, Moon, Sun, X, ChevronDown } from "lucide-react";
import { useAuth } from "@/context/AuthContext";
import { useTheme } from "@/context/ThemeContext";
import { api } from "@/lib/api";
import { getModuleIcon } from "@/lib/moduleIcons";
import { isReleasedModule } from "@/lib/releasedModules";
import { toast } from "sonner";
import { Tooltip, TooltipContent, TooltipTrigger } from "@/components/ui/tooltip";
import StatusBadge from "@/components/StatusBadge";

const NAV = [
  { to: "/", label: "Dashboard", icon: LayoutDashboard, testid: "menu-dashboard", end: true },
  { to: "/clientes", label: "Clientes", icon: Building2, testid: "menu-clientes" },
  { to: "/modulos", label: "Módulos", icon: Blocks, testid: "menu-modulos" },
  { to: "/equipe", label: "Equipe", icon: Users, testid: "menu-equipe" },
];

function Brand({ compact }) {
  return (
    <div className="flex items-center gap-3">
      <img
        src="/dacot-logo.png"
        alt="DACOT"
        className={`dh-brand-logo ${compact ? "dh-brand-logo-sm" : ""}`}
      />
      <div className={`flex items-center ${compact ? "" : "hidden sm:flex"}`}>
        <div className="dh-font-display font-bold text-[15px] tracking-tight text-[var(--dh-text)]">DACOT</div>
      </div>
    </div>
  );
}

export default function AppLayout() {
  const { user, logout } = useAuth();
  const { theme, toggleTheme } = useTheme();
  const navigate = useNavigate();
  const location = useLocation();
  const [drawer, setDrawer] = useState(false);
  const [modulesOpen, setModulesOpen] = useState(false);
  const [modules, setModules] = useState(null);
  const [modulesError, setModulesError] = useState(false);
  const modulesMenuRef = useRef(null);

  const initials = (user?.name || user?.email || "?")
    .split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();

  const doLogout = async () => { await logout(); navigate("/login"); };

  useEffect(() => {
    if (user?.user_type === "restaurant") return undefined;
    let mounted = true;
    api.get("/hub/modules")
      .then((response) => { if (mounted) setModules(response.data); })
      .catch(() => { if (mounted) setModulesError(true); });
    return () => { mounted = false; };
  }, [user?.user_type]);

  useEffect(() => {
    setModulesOpen(false);
  }, [location.pathname]);

  useEffect(() => {
    if (!modulesOpen) return undefined;
    const closeWhenOutside = (event) => {
      if (!modulesMenuRef.current?.contains(event.target)) {
        setModulesOpen(false);
      }
    };
    const closeWithEscape = (event) => {
      if (event.key === "Escape") {
        setModulesOpen(false);
      }
    };
    document.addEventListener("mousedown", closeWhenOutside);
    document.addEventListener("keydown", closeWithEscape);
    return () => {
      document.removeEventListener("mousedown", closeWhenOutside);
      document.removeEventListener("keydown", closeWithEscape);
    };
  }, [modulesOpen]);

  if (user?.user_type === "restaurant") {
    return <Navigate to="/portal" replace />;
  }

  const selectModule = (module) => {
    if (module.key === "orders") {
      setModulesOpen(false);
      navigate("/modulos/orders");
      return;
    }
    setModulesOpen(false);
    if (module.status === "available") {
      toast.info(`Selecione um restaurante para acessar ${module.name}.`);
      navigate("/clientes");
      return;
    }
    navigate("/modulos");
  };

  const closeModulesMenu = () => {
    setModulesOpen(false);
  };

  const toggleModulesMenu = () => {
    if (modulesOpen) {
      closeModulesMenu();
      return;
    }
    setModulesOpen(true);
  };

  const visibleModules = modules?.filter(isReleasedModule);

  const desktopModulesMenu = (
    <div key="/modulos" className="dh-modules-menu-wrap" ref={modulesMenuRef}>
      <button
        type="button"
        className={`dh-topnav-link ${location.pathname === "/modulos" ? "dh-topnav-link-active" : ""}`}
        data-testid="menu-modulos"
        onClick={toggleModulesMenu}
        aria-haspopup="menu"
        aria-expanded={modulesOpen}
        aria-controls="desktop-modules-menu"
      >
        <Blocks size={18} strokeWidth={1.75} />
        <span>Módulos</span>
        <ChevronDown className={`dh-modules-menu-chevron ${modulesOpen ? "dh-modules-menu-chevron-open" : ""}`} size={15} strokeWidth={2} />
      </button>
      {modulesOpen && (
        <div id="desktop-modules-menu" className="dh-modules-menu" role="menu" aria-label="Módulos DACOT">
          {modules === null && !modulesError && (
            <div className="dh-modules-menu-message" role="status">Carregando módulos…</div>
          )}
          {modulesError && (
            <div className="dh-modules-menu-message">Não foi possível carregar os módulos.</div>
          )}
          {visibleModules?.length === 0 && (
            <div className="dh-modules-menu-message">Nenhum módulo disponível.</div>
          )}
          {visibleModules?.map((module) => {
            const Icon = getModuleIcon(module.icon);
            return (
              <button
                key={module.key}
                type="button"
                role="menuitem"
                className="dh-modules-menu-item"
                onClick={() => selectModule(module)}
                data-testid={`menu-module-${module.key}`}
              >
                <span className="dh-icon-tile-neutral dh-modules-menu-icon"><Icon size={16} strokeWidth={1.75} /></span>
                <span className="min-w-0 flex-1 text-left truncate">{module.name}</span>
                <StatusBadge status={module.status} />
              </button>
            );
          })}
          <div className="dh-modules-menu-divider" />
          <button
            type="button"
            role="menuitem"
            className="dh-modules-menu-manage"
            onClick={() => { setModulesOpen(false); navigate("/modulos"); }}
            data-testid="menu-manage-modules"
          >
            <Blocks size={16} strokeWidth={1.75} />
            Gerenciar módulos
          </button>
        </div>
      )}
    </div>
  );

  const navItems = (variant, onNavigate) => NAV.map(({ to, label, icon: Icon, testid, end }) => {
    if (variant === "desktop" && to === "/modulos") return desktopModulesMenu;
    return (
      <NavLink
        key={to}
        to={to}
        end={end}
        data-testid={testid}
        onClick={onNavigate}
        className={({ isActive }) => `${variant === "desktop" ? "dh-topnav-link" : "dh-sidebar-link"} ${isActive ? `${variant === "desktop" ? "dh-topnav-link-active" : "dh-sidebar-link-active"}` : ""}`}
      >
        <Icon size={18} strokeWidth={1.75} />
        <span>{label}</span>
      </NavLink>
    );
  });

  const mobileBottomSection = (
    <div className="dh-sidebar-footer pt-4 pb-5 px-3 space-y-1">
      <div className="flex items-center gap-3 px-3 py-3 mb-1">
        <div className="dh-user-avatar">{initials}</div>
        <div className="flex-1 min-w-0 leading-tight">
          <div className="text-[13px] font-semibold text-[var(--dh-text)] truncate" data-testid="user-name">
            {user?.name || "Admin"}
          </div>
          <div className="text-[11px] text-[var(--dh-muted)] truncate">{user?.email}</div>
        </div>
      </div>
      <button
        onClick={() => toast.info("Configurações estarão disponíveis em breve.")}
        data-testid="menu-configuracoes"
        className="dh-sidebar-link w-full text-left"
      >
        <Settings size={18} strokeWidth={1.75} />
        <span>Configurações</span>
      </button>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={toggleTheme}
            data-testid="theme-toggle"
            className="dh-sidebar-link w-full text-left"
            aria-label={theme === "dark" ? "Alternar para tema claro" : "Alternar para tema escuro"}
            aria-pressed={theme === "dark"}
          >
            {theme === "dark" ? <Sun size={18} strokeWidth={1.75} /> : <Moon size={18} strokeWidth={1.75} />}
            <span>{theme === "dark" ? "Tema claro" : "Tema escuro"}</span>
          </button>
        </TooltipTrigger>
        <TooltipContent side="right">
          {theme === "dark" ? "Mudar para tema claro" : "Mudar para tema escuro"}
        </TooltipContent>
      </Tooltip>
      <button
        onClick={doLogout}
        data-testid="logout-btn"
        className="dh-sidebar-link w-full text-left text-[#64748B] hover:!text-[var(--dh-error-fg)] hover:!bg-[var(--dh-error-bg)]"
      >
        <LogOut size={18} strokeWidth={1.75} />
        <span>Sair</span>
      </button>
    </div>
  );

  const desktopActions = (
    <div className="flex items-center gap-1.5 shrink-0">
      <div className="dh-topnav-user hidden xl:flex items-center gap-2.5 mr-1 pl-2 pr-3 py-1.5">
        <div className="dh-user-avatar dh-user-avatar-sm">{initials}</div>
        <div className="min-w-0 leading-tight">
          <div className="text-[12px] font-semibold text-[var(--dh-text)] truncate max-w-[130px]" data-testid="user-name">
            {user?.name || "Admin"}
          </div>
          <div className="text-[10px] text-[var(--dh-muted)] truncate max-w-[130px]">{user?.email}</div>
        </div>
      </div>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={() => toast.info("Configurações estarão disponíveis em breve.")}
            data-testid="menu-configuracoes"
            className="dh-topnav-action"
            aria-label="Configurações"
          >
            <Settings size={18} strokeWidth={1.75} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Configurações</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            type="button"
            onClick={toggleTheme}
            data-testid="theme-toggle"
            className="dh-topnav-action"
            aria-label={theme === "dark" ? "Alternar para tema claro" : "Alternar para tema escuro"}
            aria-pressed={theme === "dark"}
          >
            {theme === "dark" ? <Sun size={18} strokeWidth={1.75} /> : <Moon size={18} strokeWidth={1.75} />}
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">{theme === "dark" ? "Mudar para tema claro" : "Mudar para tema escuro"}</TooltipContent>
      </Tooltip>
      <Tooltip>
        <TooltipTrigger asChild>
          <button
            onClick={doLogout}
            data-testid="logout-btn"
            className="dh-topnav-action dh-topnav-logout"
            aria-label="Sair"
          >
            <LogOut size={18} strokeWidth={1.75} />
          </button>
        </TooltipTrigger>
        <TooltipContent side="bottom">Sair</TooltipContent>
      </Tooltip>
    </div>
  );

  return (
    <div className="min-h-screen bg-[var(--dh-bg)]">
      {/* Desktop navigation */}
      <header
        className="hidden lg:flex h-[68px] dh-topnav sticky top-0 z-30 items-center px-8 xl:px-10"
        data-testid="sidebar"
      >
        <div className="shrink-0 pr-8 xl:pr-12">
          <Brand />
        </div>
        <nav className="flex items-center gap-1 flex-1 min-w-0" aria-label="Navegação principal">
          {navItems("desktop")}
        </nav>
        {desktopActions}
      </header>

      {/* Topbar — mobile */}
      <div className="dh-mobile-topbar lg:hidden fixed top-0 inset-x-0 z-40 h-[56px] backdrop-blur-lg border-b border-[var(--dh-border)] flex items-center justify-between px-4 shadow-[var(--dh-shadow-xs)]">
        <Brand compact />
        <button
          onClick={() => setDrawer(true)}
          data-testid="mobile-menu-btn"
          className="p-2.5 rounded-[var(--dh-radius-sm)] hover:bg-[var(--dh-border-soft)] transition-colors"
          aria-label="Abrir menu"
        >
          <Menu size={20} strokeWidth={1.75} className="text-[var(--dh-muted-strong)]" />
        </button>
      </div>

      {/* Drawer — mobile */}
      {drawer && (
        <div className="lg:hidden fixed inset-0 z-50">
          <div className="absolute inset-0 dh-drawer-overlay" onClick={() => setDrawer(false)} />
          <aside
            className="absolute inset-y-0 left-0 w-[280px] dh-sidebar shadow-[var(--dh-shadow-lg)] flex flex-col dh-drawer-panel"
            data-testid="mobile-drawer"
          >
            <div className="px-5 py-6 border-b border-[var(--dh-border-soft)] flex items-center justify-between">
              <Brand />
              <button
                onClick={() => setDrawer(false)}
                className="p-2 rounded-[var(--dh-radius-sm)] hover:bg-[var(--dh-border-soft)] transition-colors"
                aria-label="Fechar menu"
              >
                <X size={18} strokeWidth={1.75} className="text-[var(--dh-muted)]" />
              </button>
            </div>
            <nav className="flex-1 py-5 overflow-y-auto">
              <div className="dh-section-label">Navegação</div>
              {navItems("mobile", () => setDrawer(false))}
            </nav>
            {mobileBottomSection}
          </aside>
        </div>
      )}

      {/* Main */}
      <main className="w-full min-w-0 pt-[56px] lg:pt-0">
        <div className="px-5 sm:px-8 lg:px-10 py-8 lg:py-10 w-full dh-fade-in">
          <Outlet />
        </div>
      </main>
    </div>
  );
}
