import { useState } from "react";
import { useNavigate, Link, Navigate } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { useAuth } from "@/context/AuthContext";
import { ArrowLeft } from "lucide-react";

const STATUS = [
  { v: "active", l: "Ativo" },
  { v: "trial", l: "Em teste" },
  { v: "suspended", l: "Suspenso" },
  { v: "inactive", l: "Inativo" },
];

export default function ClienteNovo() {
  const nav = useNavigate();
  const { user } = useAuth();
  const [form, setForm] = useState({
    name: "", owner_name: "", email: "", phone: "",
    status: "trial", address: "", notes: "",
    create_hub_access: false, access_name: "", access_email: "",
  });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  // Backend already rejects this for viewer (get_staff_write) — redirect
  // away instead of showing a form that can only ever fail.
  if (user?.role === "viewer") return <Navigate to="/clientes" replace />;

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const payload = {
        ...form,
        // Empty optional fields are omitted so the backend can deliberately
        // fall back to the restaurant owner contact.
        access_name: form.access_name.trim() || undefined,
        access_email: form.access_email.trim() || undefined,
      };
      const { data } = await api.post("/hub/tenants/onboard", payload);
      nav(`/clientes/${data.id}`);
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setBusy(false); }
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="max-w-3xl space-y-6" data-testid="new-tenant-page">
      <div>
        <Link to="/clientes" className="text-[12px] font-semibold text-slate-500 hover:text-slate-700 transition-colors inline-flex items-center gap-1.5">
          <ArrowLeft size={14} strokeWidth={2} /> Voltar
        </Link>
        <h1 className="text-3xl sm:text-4xl font-bold tracking-tight text-slate-900 mt-4 mb-2" style={{fontFamily:"Cabinet Grotesk"}}>Novo cliente</h1>
        <p className="text-[15px] text-slate-500">Cadastre um restaurante na plataforma DACOT.</p>
      </div>

      <form onSubmit={submit} className="dh-card p-6 sm:p-8 space-y-7">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-6">
          <Field label="Nome do restaurante" required>
            <input required className="dh-input" value={form.name} onChange={set("name")} data-testid="input-name" />
          </Field>
          <Field label="Responsável" required>
            <input required className="dh-input" value={form.owner_name} onChange={set("owner_name")} data-testid="input-owner" />
          </Field>
          <Field label="E-mail" required>
            <input type="email" required className="dh-input" value={form.email} onChange={set("email")} data-testid="input-email" />
          </Field>
          <Field label="Telefone">
            <input className="dh-input" value={form.phone} onChange={set("phone")} data-testid="input-phone" />
          </Field>
          <Field label="Status">
            <select className="dh-input" value={form.status} onChange={set("status")} data-testid="input-status">
              {STATUS.map((s) => <option key={s.v} value={s.v}>{s.l}</option>)}
            </select>
          </Field>
          <Field label="Endereço">
            <input className="dh-input" value={form.address} onChange={set("address")} data-testid="input-address" />
          </Field>
        </div>
        <Field label="Observações">
          <textarea rows={4} className="dh-input resize-none" value={form.notes} onChange={set("notes")} data-testid="input-notes" />
        </Field>

        <section className="pt-6 border-t border-[var(--dh-border-soft)] space-y-4" data-testid="hub-access-section">
          <div>
            <div className="text-[12px] uppercase tracking-widest font-bold text-[var(--dh-muted)]">Acesso ao Hub</div>
            <p className="text-[13px] text-[var(--dh-muted)] mt-1">Crie o primeiro acesso do responsável sem expor senha temporária.</p>
          </div>
          <label className="flex items-start gap-3 cursor-pointer">
            <input type="checkbox" checked={form.create_hub_access}
                   onChange={(e) => setForm((f) => ({ ...f, create_hub_access: e.target.checked }))}
                   className="mt-1" data-testid="create-hub-access" />
            <span className="text-[14px] font-medium text-[var(--dh-text)]">Criar acesso ao Hub para o responsável</span>
          </label>
          {form.create_hub_access && (
            <div className="grid grid-cols-1 md:grid-cols-2 gap-6 dh-fade-in">
              <Field label="Nome de acesso" required>
                <input required className="dh-input" value={form.access_name || form.owner_name}
                       onChange={set("access_name")} data-testid="input-access-name" />
              </Field>
              <Field label="E-mail de acesso" required>
                <input type="email" required className="dh-input" value={form.access_email || form.email}
                       onChange={set("access_email")} data-testid="input-access-email" />
              </Field>
            </div>
          )}
          {form.create_hub_access && <p className="text-[12px] text-[var(--dh-muted)]">O responsável receberá um link seguro para definir a própria senha.</p>}
        </section>

        {err && <div className="dh-chip dh-chip-error">{err}</div>}

        <div className="flex items-center justify-end gap-3 pt-6 border-t border-slate-100">
          <Link to="/clientes" className="dh-btn dh-btn-ghost">Cancelar</Link>
          <button type="submit" disabled={busy} className="dh-btn dh-btn-primary" data-testid="submit-tenant">
            {busy ? "Salvando…" : "Cadastrar cliente"}
          </button>
        </div>
      </form>
    </div>
  );
}

function Field({ label, required, children }) {
  return (
    <label className="block">
      <div className="text-[13px] font-medium text-slate-700 mb-1.5">
        {label}{required && <span className="text-[var(--dh-accent)]"> *</span>}
      </div>
      {children}
    </label>
  );
}
