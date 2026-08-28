import { useState } from "react";
import { useNavigate, Link } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";
import { ArrowLeft } from "lucide-react";

const STATUS = [
  { v: "active", l: "Ativo" },
  { v: "trial", l: "Em teste" },
  { v: "suspended", l: "Suspenso" },
  { v: "inactive", l: "Inativo" },
];

export default function ClienteNovo() {
  const nav = useNavigate();
  const [form, setForm] = useState({
    name: "", owner_name: "", email: "", phone: "",
    status: "trial", address: "", notes: "",
  });
  const [err, setErr] = useState(null);
  const [busy, setBusy] = useState(false);

  const submit = async (e) => {
    e.preventDefault();
    setBusy(true); setErr(null);
    try {
      const { data } = await api.post("/hub/tenants", form);
      nav(`/clientes/${data.id}`);
    } catch (e) {
      setErr(formatApiErrorDetail(e.response?.data?.detail) || e.message);
    } finally { setBusy(false); }
  };

  const set = (k) => (e) => setForm((f) => ({ ...f, [k]: e.target.value }));

  return (
    <div className="max-w-3xl space-y-6" data-testid="new-tenant-page">
      <div>
        <Link to="/clientes" className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] hover:text-[var(--dh-text)] inline-flex items-center gap-1">
          <ArrowLeft size={12} /> Clientes
        </Link>
        <h1 className="text-3xl lg:text-4xl font-black tracking-tight mt-2" style={{fontFamily:"Cabinet Grotesk"}}>Novo cliente</h1>
        <p className="text-sm text-[var(--dh-muted)] mt-1">Cadastre um restaurante na plataforma DACOT.</p>
      </div>

      <form onSubmit={submit} className="dh-card p-6 space-y-5">
        <div className="grid grid-cols-1 md:grid-cols-2 gap-5">
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
          <textarea rows={3} className="dh-input resize-none" value={form.notes} onChange={set("notes")} data-testid="input-notes" />
        </Field>

        {err && <div className="dh-chip dh-chip-error">{err}</div>}

        <div className="flex items-center justify-end gap-3 pt-2 border-t border-[var(--dh-border)]">
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
      <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-muted)] mb-2">
        {label}{required && <span className="text-[var(--dh-accent)]">*</span>}
      </div>
      {children}
    </label>
  );
}
