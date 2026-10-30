import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { Plus, Building2, ChevronRight, Trash2 } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";
import { toast } from "sonner";
import {
  AlertDialog, AlertDialogCancel, AlertDialogContent, AlertDialogDescription,
  AlertDialogFooter, AlertDialogHeader, AlertDialogTitle,
} from "@/components/ui/alert-dialog";

const FILTERS = [
  { key: "all", label: "Todos" },
  { key: "active", label: "Ativos" },
  { key: "trial", label: "Em teste" },
  { key: "suspended", label: "Suspensos" },
  { key: "inactive", label: "Inativos" },
];

export default function Clientes() {
  const { user } = useAuth();
  const canWrite = user?.role !== "viewer";
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
  const [tenantToDelete, setTenantToDelete] = useState(null);
  const [deleting, setDeleting] = useState(false);
  const navigate = useNavigate();

  useEffect(() => {
    setLoading(true);
    const params = {};
    if (status !== "all") params.status = status;
    if (q.trim()) params.q = q.trim();
    api.get("/hub/tenants", { params })
      .then((r) => setRows(r.data))
      .finally(() => setLoading(false));
  }, [status, q]);

  const counts = useMemo(() => {
    const c = { all: rows.length };
    rows.forEach((r) => { c[r.status] = (c[r.status] || 0) + 1; });
    return c;
  }, [rows]);

  const deleteTenant = async () => {
    if (!tenantToDelete) return;
    setDeleting(true);
    try {
      await api.delete(`/hub/tenants/${tenantToDelete.id}`);
      setRows((current) => current.filter((tenant) => tenant.id !== tenantToDelete.id));
      toast.success("Restaurante removido com segurança");
      setTenantToDelete(null);
    } catch (error) {
      toast.error(error.response?.data?.detail || "Não foi possível remover o restaurante.");
    } finally {
      setDeleting(false);
    }
  };

  return (
    <div className="space-y-6" data-testid="clientes-page">
      <div className="flex items-start justify-between gap-4 flex-wrap">
        <div>
          <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900" style={{fontFamily:"Cabinet Grotesk"}}>Clientes</h1>
          <p className="text-[15px] text-slate-500 mt-2">Restaurantes cadastrados na plataforma DACOT.</p>
        </div>
        {canWrite && (
          <Link to="/clientes/novo" className="dh-btn dh-btn-primary" data-testid="new-tenant-btn">
            <Plus size={16} strokeWidth={2} /> Novo cliente
          </Link>
        )}
      </div>

      <div className="dh-card overflow-hidden" style={{ borderRadius: 0 }}>
        <div className="flex items-center justify-between px-6 py-4 border-b border-slate-100 gap-4 flex-wrap">
          <div className="flex gap-2 flex-wrap">
            {FILTERS.map((f) => (
              <button 
                key={f.key}
                onClick={() => setStatus(f.key)}
                data-testid={`filter-${f.key}`}
                className={`px-4 py-2 text-[13px] font-medium rounded-full transition-all duration-150 ${
                  status === f.key
                    ? "bg-[var(--dh-accent)] text-white shadow-md"
                    : "bg-slate-100 text-slate-600 hover:bg-slate-200"
                }`}
              >
                {f.label}
              </button>
            ))}
          </div>
          <div className="w-full sm:max-w-xs">
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar restaurante…"
              className="dh-input"
              data-testid="search-input"
            />
          </div>
        </div>

        <div className="overflow-x-auto">
          <table className="dh-table" data-testid="tenants-table">
            <thead>
              <tr>
                <th>Restaurante</th>
                <th>Responsável</th>
                <th>Contato</th>
                <th>Status</th>
                <th className="text-right">Módulos</th>
                <th className="text-right">Usuários</th>
                <th>Cadastro</th>
                <th className="w-20"></th>
              </tr>
            </thead>
            <tbody>
              {loading && [0,1,2,3].map((i) => (
                <tr key={i}>
                  <td><div className="space-y-1.5"><div className="dh-skeleton h-4 w-36" /><div className="dh-skeleton h-3 w-24" /></div></td>
                  <td><div className="dh-skeleton h-4 w-24" /></td>
                  <td><div className="space-y-1.5"><div className="dh-skeleton h-4 w-40" /><div className="dh-skeleton h-3 w-20" /></div></td>
                  <td><div className="dh-skeleton h-5 w-16 rounded-full" /></td>
                  <td><div className="dh-skeleton h-4 w-6 ml-auto" /></td>
                  <td><div className="dh-skeleton h-4 w-6 ml-auto" /></td>
                  <td><div className="dh-skeleton h-4 w-20" /></td>
                  <td></td>
                </tr>
              ))}
              {!loading && rows.length === 0 && (
                <tr>
                  <td colSpan={8} className="py-16">
                    <div className="flex flex-col items-center justify-center text-center gap-3">
                      <span className="dh-icon-tile w-14 h-14 rounded-xl">
                        <Building2 size={24} strokeWidth={1.6} />
                      </span>
                      <div className="text-[15px] font-semibold text-slate-700">Nenhum cliente encontrado</div>
                      <div className="text-[13px] text-slate-500">Ajuste os filtros ou cadastre um novo restaurante.</div>
                      {canWrite && <Link to="/clientes/novo" className="dh-btn dh-btn-outline mt-2">Novo cliente</Link>}
                    </div>
                  </td>
                </tr>
              )}
              {rows.map((t) => (
                <tr key={t.id}
                    onClick={() => navigate(`/clientes/${t.id}`)}
                    data-testid={`tenant-row-${t.id}`}>
                  <td>
                    <div className="font-semibold text-slate-900">{t.name}</div>
                    <div className="text-[11px] text-slate-400 font-mono mt-0.5">{t.slug}</div>
                  </td>
                  <td className="text-[13px] text-slate-600">{t.owner_name}</td>
                  <td className="text-[13px]">
                    <div className="text-slate-700">{t.email}</div>
                    <div className="text-[11px] text-slate-400 mt-0.5">{t.phone}</div>
                  </td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="text-right tabular-nums font-semibold text-slate-900">{t.active_modules}</td>
                  <td className="text-right tabular-nums text-slate-600">{t.users_count}</td>
                  <td className="text-[12px] text-slate-400">
                    {t.created_at ? new Date(t.created_at).toLocaleDateString("pt-BR") : "—"}
                  </td>
                  <td>
                    <div className="flex items-center justify-end gap-2">
                      {canWrite && (
                        <button
                          type="button"
                          className="p-1.5 rounded-md text-slate-400 hover:text-red-500 hover:bg-red-500/10 transition-colors"
                          onClick={(event) => { event.stopPropagation(); setTenantToDelete(t); }}
                          aria-label={`Remover ${t.name}`}
                          title="Remover restaurante"
                          data-testid={`delete-tenant-${t.id}`}
                        >
                          <Trash2 size={16} strokeWidth={1.8} />
                        </button>
                      )}
                      <ChevronRight size={16} strokeWidth={1.8} className="text-slate-300" />
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-6 py-3 border-t border-slate-100 flex items-center justify-between text-[12px] text-slate-500">
          <span>Mostrando <b className="text-slate-700 font-semibold">{rows.length}</b> cliente(s)</span>
          <span>Total: {counts.all}</span>
        </div>
      </div>
      <AlertDialog open={Boolean(tenantToDelete)} onOpenChange={(open) => {
        if (!open && !deleting) setTenantToDelete(null);
      }}>
        <AlertDialogContent>
          <AlertDialogHeader>
            <AlertDialogTitle>Remover restaurante?</AlertDialogTitle>
            <AlertDialogDescription>
              {tenantToDelete ? `O restaurante ${tenantToDelete.name} deixará de aparecer nas operações normais e os acessos vinculados serão bloqueados. Os dados e o histórico serão preservados.` : ""}
            </AlertDialogDescription>
          </AlertDialogHeader>
          <AlertDialogFooter>
            <AlertDialogCancel disabled={deleting}>Cancelar</AlertDialogCancel>
            <button type="button" className="dh-btn bg-red-600 text-white hover:bg-red-700" onClick={deleteTenant}
                    disabled={deleting} data-testid="confirm-delete-tenant">
              {deleting ? "Removendo…" : "Remover restaurante"}
            </button>
          </AlertDialogFooter>
        </AlertDialogContent>
      </AlertDialog>
    </div>
  );
}
