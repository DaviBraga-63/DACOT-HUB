import { useEffect, useState } from "react";
import { api } from "@/lib/api";
import { toast } from "sonner";

const roleLabels = {
  admin: "Administrador",
  manager: "Gerente",
  waiter: "Garçom",
  kitchen: "Cozinha",
};

const statusLabels = {
  active: "Ativo",
  inactive: "Inativo",
};

const accessLabels = {
  granted: "Acesso liberado",
  blocked: "Acesso bloqueado",
};

export default function PortalEquipe() {
  const [team, setTeam] = useState(null);

  useEffect(() => {
    let mounted = true;
    api.get("/portal/team")
      .then(({ data }) => {
        if (!mounted || !Array.isArray(data?.team)) throw new Error("invalid-team-response");
        setTeam(data.team);
      })
      .catch(() => {
        if (mounted) toast.error("Não foi possível carregar a equipe.");
      });
    return () => { mounted = false; };
  }, []);

  return <div className="max-w-6xl space-y-6 dh-fade-in" data-testid="portal-team-page">
    <div>
      <p className="text-xs font-semibold uppercase tracking-[.16em] text-[var(--dh-muted)]">Portal</p>
      <h1 className="dh-font-display mt-2 text-3xl font-bold text-[var(--dh-text)]">Equipe</h1>
      <p className="mt-2 text-sm text-[var(--dh-muted)]">
        Consulte os funcionários e os acessos gerenciados no módulo responsável.
      </p>
    </div>

    <div className="dh-card overflow-x-auto">
      <table className="dh-table w-full">
        <thead><tr><th>Nome</th><th>Cargo</th><th>Módulo</th><th>Situação</th><th>Acesso</th></tr></thead>
        <tbody>{team?.map((member, index) => <tr key={`${member.name}-${member.role}-${index}`}>
          <td>{member.name}</td>
          <td>{roleLabels[member.role] || member.role}</td>
          <td>{member.module}</td>
          <td>{statusLabels[member.status] || member.status}</td>
          <td>{accessLabels[member.access] || member.access}</td>
        </tr>)}</tbody>
      </table>
      {team === null && <div className="p-6 text-sm text-[var(--dh-muted)]">Carregando…</div>}
      {team?.length === 0 && <div className="p-6 text-sm text-[var(--dh-muted)]">Nenhum funcionário cadastrado no Pedidos.</div>}
    </div>
  </div>;
}
