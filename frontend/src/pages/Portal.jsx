import { useCallback, useEffect, useState } from "react";
import { Landmark } from "lucide-react";
import { api, formatApiErrorDetail } from "@/lib/api";

export default function Portal() {
  const [context, setContext] = useState(null);
  const [error, setError] = useState(null);
  const [revenue, setRevenue] = useState(null);
  const [revenueError, setRevenueError] = useState(false);

  const loadRevenue = useCallback(() => {
    setRevenue(null);
    setRevenueError(false);
    api.get("/portal/analytics/revenue")
      .then(({ data }) => setRevenue(data))
      .catch(() => setRevenueError(true));
  }, []);

  useEffect(() => {
    let active = true;
    api.get("/portal/context")
      .then(({ data }) => active && setContext(data))
      .catch((requestError) => active && setError(formatApiErrorDetail(requestError.response?.data?.detail)));
    loadRevenue();
    return () => { active = false; };
  }, [loadRevenue]);

  if (error) return <div className="dh-chip dh-chip-error" data-testid="portal-error">{error}</div>;

  if (!context) {
    return <div className="space-y-4" data-testid="portal-loading">
      <div className="dh-skeleton h-4 w-20" />
      <div className="dh-skeleton h-10 w-64" />
      <div className="dh-card p-6"><div className="dh-skeleton h-24 w-full" /></div>
    </div>;
  }

  return (
    <div className="max-w-5xl space-y-7 dh-fade-in" data-testid="portal-page">
      <div>
        <p className="text-[12px] font-semibold uppercase tracking-[0.16em] text-[var(--dh-muted)]">Painel</p>
        <h1 className="dh-font-display mt-2 text-3xl font-bold tracking-tight text-[var(--dh-text)]" data-testid="portal-tenant-name">
          {context.tenant.name}
        </h1>
        <p className="mt-2 text-sm text-[var(--dh-muted)]">Acompanhe as novidades do seu restaurante na DACOT.</p>
      </div>

      <section className="grid max-w-3xl grid-cols-1 gap-5 sm:grid-cols-2" aria-label="Faturamento">
        <RevenueCard label="Faturamento hoje" cents={revenue?.today_cents} error={revenueError} onRetry={loadRevenue} testid="portal-revenue-today" />
        <RevenueCard label="Faturamento no mês" cents={revenue?.current_month_cents} error={revenueError} onRetry={loadRevenue} testid="portal-revenue-month" />
      </section>
    </div>
  );
}

function RevenueCard({ label, cents, error, onRetry, testid }) {
  const formatted = typeof cents === "number"
    ? new Intl.NumberFormat("pt-BR", { style: "currency", currency: "BRL" }).format(cents / 100)
    : null;
  return <article className="dh-card p-6" data-testid={testid}>
    <div className="flex items-start justify-between gap-4">
      <div>
        <p className="text-sm font-medium text-[var(--dh-muted)]">{label}</p>
        {!error && !formatted && <div className="dh-skeleton mt-4 h-9 w-36" data-testid={`${testid}-loading`} />}
        {!error && formatted && <p className="dh-font-display mt-3 text-3xl font-bold tracking-tight text-[var(--dh-text)]">{formatted}</p>}
        {error && <>
          <p className="mt-3 text-sm font-medium text-[var(--dh-muted)]">Faturamento indisponível no momento</p>
          <button type="button" className="dh-btn dh-btn-ghost mt-3 text-sm" onClick={onRetry} data-testid={`${testid}-retry`}>Tentar novamente</button>
        </>}
      </div>
      <span className="dh-icon-tile h-10 w-10 shrink-0 rounded-lg"><Landmark size={19} strokeWidth={1.65} /></span>
    </div>
  </article>;
}
