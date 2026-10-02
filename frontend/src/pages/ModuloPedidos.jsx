import { useEffect, useMemo, useRef, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { ArrowLeft, Building2, Save, Users } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { getModuleIcon } from "@/lib/moduleIcons";
import StatusBadge from "@/components/StatusBadge";
import { toast } from "sonner";

const ROLE_LABEL = { admin: "Administrador", manager: "Gerente", waiter: "Atendente", kitchen: "Cozinha" };

export default function ModuloPedidos() {
  const { user } = useAuth();
  const navigate = useNavigate();
  const canWrite = user?.role === "admin" || user?.role === "super_admin";
  const [module, setModule] = useState(null);
  const [template, setTemplate] = useState("");
  const [tenants, setTenants] = useState([]);
  const [selectedTenantId, setSelectedTenantId] = useState("");
  const [tenantModule, setTenantModule] = useState(null);
  const [tenantUsers, setTenantUsers] = useState([]);
  const [grants, setGrants] = useState([]);
  const [loading, setLoading] = useState(true);
  const [tenantLoading, setTenantLoading] = useState(false);
  const [savingTemplate, setSavingTemplate] = useState(false);
  const [changingUserId, setChangingUserId] = useState(null);
  const tenantRequestRef = useRef(0);

  useEffect(() => {
    let mounted = true;
    Promise.all([api.get("/hub/modules"), api.get("/hub/tenants")])
      .then(([modulesResponse, tenantsResponse]) => {
        if (!mounted) return;
        const orders = modulesResponse.data.find((item) => item.key === "orders") || null;
        setModule(orders);
        setTemplate(orders?.launch_url_template || "");
        setTenants(tenantsResponse.data);
      })
      .catch((error) => toast.error(formatApiErrorDetail(error.response?.data?.detail)))
      .finally(() => { if (mounted) setLoading(false); });
    return () => { mounted = false; };
  }, []);

  const loadTenantAccess = async (tenantId) => {
    if (!tenantId) return;
    const requestId = ++tenantRequestRef.current;
    setTenantLoading(true);
    try {
      const [usersResponse, grantsResponse, modulesResponse] = await Promise.all([
        api.get(`/hub/tenants/${tenantId}/users`),
        api.get(`/hub/tenants/${tenantId}/modules/orders/access-grants`),
        api.get(`/hub/tenants/${tenantId}/modules`),
      ]);
      if (requestId === tenantRequestRef.current) {
        setTenantUsers(usersResponse.data);
        setGrants(grantsResponse.data);
        setTenantModule(modulesResponse.data.find((item) => item.key === "orders") || null);
      }
    } finally {
      if (requestId === tenantRequestRef.current) setTenantLoading(false);
    }
  };

  useEffect(() => {
    if (!selectedTenantId) {
      tenantRequestRef.current += 1;
      setTenantLoading(false);
      setTenantUsers([]);
      setGrants([]);
      setTenantModule(null);
      return;
    }
    let cancelled = false;
    loadTenantAccess(selectedTenantId).catch((error) => {
      if (cancelled) return;
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
      setTenantUsers([]);
      setGrants([]);
      setTenantModule(null);
    });
    return () => { cancelled = true; };
  }, [selectedTenantId]);

  const grantsByUserId = useMemo(
    () => new Map(grants.map((grant) => [grant.user_id, grant.active])),
    [grants],
  );

  const saveTemplate = async (event) => {
    event.preventDefault();
    if (!canWrite) return;
    setSavingTemplate(true);
    try {
      const { data } = await api.patch("/hub/modules/orders/launch-url-template", {
        launch_url_template: template,
      });
      setModule(data);
      setTemplate(data.launch_url_template || "");
      toast.success("URL global do módulo atualizada");
    } catch (error) {
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
    } finally {
      setSavingTemplate(false);
    }
  };

  const setUserAccess = async (tenantUser, active) => {
    if (!canWrite || !selectedTenantId || !tenantModule?.active) return;
    setChangingUserId(tenantUser.id);
    try {
      await api.put(`/hub/tenants/${selectedTenantId}/modules/orders/users/${tenantUser.id}/access`, { active });
      await loadTenantAccess(selectedTenantId);
      toast.success(active ? "Acesso concedido" : "Acesso removido");
    } catch (error) {
      toast.error(formatApiErrorDetail(error.response?.data?.detail));
    } finally {
      setChangingUserId(null);
    }
  };

  const ModuleIcon = getModuleIcon(module?.icon);

  if (loading) {
    return <div className="space-y-6"><div className="dh-skeleton h-5 w-24" /><div className="dh-skeleton h-10 w-64" /><div className="dh-card p-7"><div className="dh-skeleton h-48 w-full" /></div></div>;
  }

  if (!module) {
    return <div className="dh-card p-7 text-[14px] text-[var(--dh-muted)]">O módulo Pedidos não está disponível no catálogo.</div>;
  }

  return (
    <div className="max-w-5xl space-y-6" data-testid="orders-module-page">
      <div>
        <Link to="/modulos" className="inline-flex items-center gap-1.5 text-[12px] font-semibold text-[var(--dh-muted)] hover:text-[var(--dh-accent)] transition-colors" data-testid="orders-back-link">
          <ArrowLeft size={14} strokeWidth={2} /> Módulos
        </Link>
        <div className="flex items-start gap-4 mt-5">
          <span className="dh-icon-tile w-12 h-12 shrink-0 rounded-xl"><ModuleIcon size={24} strokeWidth={1.65} /></span>
          <div className="min-w-0">
            <div className="flex items-center gap-3 flex-wrap">
              <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-[var(--dh-text)]" style={{ fontFamily: "Cabinet Grotesk" }}>{module.name}</h1>
              <StatusBadge status={module.status} />
            </div>
            <div className="text-[11px] text-[var(--dh-muted)] uppercase tracking-wider font-semibold mt-2">{module.category || "Módulo DACOT"}</div>
            <p className="text-[15px] text-[var(--dh-muted)] mt-2 max-w-2xl">{module.description}</p>
          </div>
        </div>
      </div>

      <form className="dh-card p-6 sm:p-7" onSubmit={saveTemplate} data-testid="orders-template-form">
        <div className="flex items-start justify-between gap-4 flex-wrap mb-5">
          <div><h2 className="text-lg font-semibold text-[var(--dh-text)]">Configuração do módulo</h2><p className="text-[13px] text-[var(--dh-muted)] mt-1">A URL global preserva o placeholder obrigatório <code>{"{slug}"}</code>.</p></div>
          {!canWrite && <span className="dh-chip dh-chip-neutral">Somente leitura</span>}
        </div>
        <label className="text-[11px] uppercase tracking-wider font-semibold text-[var(--dh-muted)]">URL do módulo</label>
        <input value={template} onChange={(event) => setTemplate(event.target.value)} readOnly={!canWrite}
               className="dh-input mt-2 font-mono text-[13px]" data-testid="orders-template-input" />
        {canWrite && <div className="mt-4 flex justify-end"><button className="dh-btn dh-btn-primary" type="submit" disabled={savingTemplate} data-testid="orders-template-save"><Save size={15} strokeWidth={1.9} />{savingTemplate ? "Salvando…" : "Salvar alterações"}</button></div>}
      </form>

      <section className="dh-card p-6 sm:p-7" data-testid="orders-access-section">
        <div className="flex items-start gap-3 mb-6"><span className="dh-icon-tile-neutral w-10 h-10 rounded-lg"><Users size={19} strokeWidth={1.7} /></span><div><h2 className="text-lg font-semibold text-[var(--dh-text)]">Acesso de usuários</h2><p className="text-[13px] text-[var(--dh-muted)] mt-1">Configure acessos por restaurante, sem misturar usuários de tenants diferentes.</p></div></div>
        <label className="text-[11px] uppercase tracking-wider font-semibold text-[var(--dh-muted)]">Restaurante</label>
        <div className="relative mt-2 max-w-lg"><Building2 size={16} strokeWidth={1.8} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--dh-muted)]" /><select value={selectedTenantId} onChange={(event) => setSelectedTenantId(event.target.value)} className="dh-input pl-10" data-testid="orders-tenant-select"><option value="">Selecionar restaurante</option>{tenants.map((tenant) => <option key={tenant.id} value={tenant.id}>{tenant.name}</option>)}</select></div>

        {!selectedTenantId && <p className="text-[13px] text-[var(--dh-muted)] py-10 text-center">Selecione um restaurante para visualizar os usuários e seus acessos.</p>}
        {selectedTenantId && tenantLoading && <div className="mt-6 space-y-3"><div className="dh-skeleton h-12 w-full" /><div className="dh-skeleton h-12 w-full" /></div>}
        {selectedTenantId && !tenantLoading && !tenantModule?.active && <p className="mt-5 dh-chip dh-chip-warning">Pedidos não está ativo para este restaurante.</p>}
        {selectedTenantId && !tenantLoading && tenantModule?.active && (
          <div className="mt-6 divide-y divide-[var(--dh-border-soft)] border-y border-[var(--dh-border-soft)]">
            {tenantUsers.length === 0 && <p className="py-8 text-center text-[13px] text-[var(--dh-muted)]">Nenhum usuário cadastrado neste restaurante.</p>}
            {tenantUsers.map((tenantUser) => {
              const active = grantsByUserId.get(tenantUser.id) === true;
              const disabled = !canWrite || changingUserId === tenantUser.id || tenantUser.status !== "active";
              return <div className="flex items-center justify-between gap-4 py-4" key={tenantUser.id} data-testid={`orders-user-access-${tenantUser.id}`}>
                <button type="button" className="min-w-0 text-left group" onClick={() => navigate(`/clientes/${selectedTenantId}`)} data-testid={`orders-user-link-${tenantUser.id}`}><div className="font-semibold text-[var(--dh-text)] group-hover:text-[var(--dh-accent)] transition-colors truncate">{tenantUser.name}</div><div className="text-[12px] text-[var(--dh-muted)]">{ROLE_LABEL[tenantUser.role] || tenantUser.role}</div></button>
                <label className={`inline-flex items-center gap-2 ${disabled ? "cursor-not-allowed opacity-60" : "cursor-pointer"}`}><span className="text-[12px] text-[var(--dh-muted)]">{active ? "ON" : "OFF"}</span><input type="checkbox" className="sr-only peer" checked={active} disabled={disabled} onChange={(event) => setUserAccess(tenantUser, event.target.checked)} data-testid={`orders-user-toggle-${tenantUser.id}`} /><span className={`dh-toggle ${active ? "dh-toggle-on" : "dh-toggle-off"}`}><span className={`dh-toggle-knob ${active ? "translate-x-[20px]" : "translate-x-[2px]"}`} /></span></label>
              </div>;
            })}
          </div>
        )}
      </section>
    </div>
  );
}
