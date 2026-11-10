import { useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, formatApiErrorDetail } from "@/lib/api";

export default function OwnerContactConfirmation({ channel }) {
  const [params] = useSearchParams();
  const token = params.get("token") || "";
  const [busy, setBusy] = useState(false);
  const [done, setDone] = useState(false);
  const [error, setError] = useState("");
  const isEmail = channel === "email";

  const confirm = async () => {
    if (!token) { setError("Link de confirmação inválido."); return; }
    setBusy(true); setError("");
    try {
      await api.post(isEmail ? "/auth/confirm-owner-email" : "/auth/confirm-owner-whatsapp", { token });
      setDone(true);
    } catch (err) {
      setError(formatApiErrorDetail(err.response?.data?.detail) || "Não foi possível confirmar este canal.");
    } finally { setBusy(false); }
  };

  return <div className="min-h-screen flex items-center justify-center px-6 bg-[var(--dh-bg)]">
    <div className="dh-card p-8 w-full max-w-md dh-fade-in">
      <div className="text-[11px] uppercase tracking-widest font-bold text-[var(--dh-accent)] mb-3">Confirmação de segurança</div>
      <h1 className="text-3xl font-bold mb-3" style={{ fontFamily: "Cabinet Grotesk" }}>Confirmar {isEmail ? "e-mail" : "WhatsApp"}</h1>
      <p className="text-sm text-slate-500 mb-6">O canal novo só será usado para acesso e recuperação após esta confirmação.</p>
      {done ? <><p className="dh-chip dh-chip-success">Canal confirmado com segurança.</p><Link to="/login" className="block mt-6 text-center text-[12px] uppercase tracking-widest font-bold text-slate-500">Ir para o login</Link></> : <>
        {error && <p role="alert" className="dh-chip dh-chip-error mb-4">{error}</p>}
        <button type="button" className="dh-btn dh-btn-primary w-full py-3" onClick={confirm} disabled={busy}>{busy ? "Confirmando…" : "Confirmar canal"}</button>
      </>}
    </div>
  </div>;
}
