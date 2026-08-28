import { useEffect, useMemo, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api } from "@/lib/api";
import { Plus, Search } from "lucide-react";
import StatusBadge from "@/components/StatusBadge";

const FILTERS = [
  { key: "all", label: "Todos" },
  { key: "active", label: "Ativos" },
  { key: "trial", label: "Em teste" },
  { key: "suspended", label: "Suspensos" },
  { key: "inactive", label: "Inativos" },
];

export default function Clientes() {
  const [rows, setRows] = useState([]);
  const [status, setStatus] = useState("all");
  const [q, setQ] = useState("");
  const [loading, setLoading] = useState(true);
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

  return (
    <div className="space-y-6" data-testid="clientes-page">
      <div className="flex items-end justify-between">
        <div>
          <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-1">Gestão</div>
          <h1 className="text-3xl lg:text-4xl font-black tracking-tight" style={{fontFamily:"Cabinet Grotesk"}}>Clientes</h1>
          <p className="text-sm text-[var(--dh-muted)] mt-1">Restaurantes cadastrados na plataforma DACOT.</p>
        </div>
        <Link to="/clientes/novo" className="dh-btn dh-btn-primary" data-testid="new-tenant-btn">
          <Plus size={15} strokeWidth={2} /> Novo cliente
        </Link>
      </div>

      <div className="dh-card">
        <div className="flex items-center justify-between px-4 py-3 border-b border-[var(--dh-border)] gap-4">
          <div className="flex gap-1">
            {FILTERS.map((f) => (
              <button key={f.key}
                      onClick={() => setStatus(f.key)}
                      data-testid={`filter-${f.key}`}
                      className={`px-3 py-1.5 text-[12px] font-semibold rounded-sm transition-colors ${
                        status === f.key
                          ? "bg-[var(--dh-text)] text-white"
                          : "text-[var(--dh-muted)] hover:bg-[var(--dh-bg)]"
                      }`}>
                {f.label}
              </button>
            ))}
          </div>
          <div className="relative w-full max-w-xs">
            <Search size={14} strokeWidth={1.7} className="absolute left-3 top-1/2 -translate-y-1/2 text-[var(--dh-muted)]" />
            <input
              value={q} onChange={(e) => setQ(e.target.value)}
              placeholder="Buscar por nome, responsável, e-mail…"
              className="dh-input pl-9"
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
              </tr>
            </thead>
            <tbody>
              {loading && (
                <tr><td colSpan={7} className="text-center text-[var(--dh-muted)] py-10">Carregando…</td></tr>
              )}
              {!loading && rows.length === 0 && (
                <tr><td colSpan={7} className="text-center text-[var(--dh-muted)] py-10">Nenhum cliente encontrado.</td></tr>
              )}
              {rows.map((t) => (
                <tr key={t.id}
                    onClick={() => navigate(`/clientes/${t.id}`)}
                    data-testid={`tenant-row-${t.id}`}>
                  <td>
                    <div className="font-semibold">{t.name}</div>
                    <div className="text-[11px] text-[var(--dh-muted)] font-mono">{t.slug}</div>
                  </td>
                  <td className="text-[13px]">{t.owner_name}</td>
                  <td className="text-[13px]">
                    <div>{t.email}</div>
                    <div className="text-[11px] text-[var(--dh-muted)]">{t.phone}</div>
                  </td>
                  <td><StatusBadge status={t.status} /></td>
                  <td className="text-right tabular-nums font-semibold">{t.active_modules}</td>
                  <td className="text-right tabular-nums">{t.users_count}</td>
                  <td className="text-[12px] text-[var(--dh-muted)]">
                    {t.created_at ? new Date(t.created_at).toLocaleDateString("pt-BR") : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <div className="px-4 py-3 border-t border-[var(--dh-border)] flex items-center justify-between text-[12px] text-[var(--dh-muted)]">
          <span>Mostrando <b className="text-[var(--dh-text)]">{rows.length}</b> cliente(s)</span>
          <span>Total geral: {counts.all}</span>
        </div>
      </div>
    </div>
  );
}
