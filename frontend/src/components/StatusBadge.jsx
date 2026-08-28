const MAP = {
  active:    { cls: "dh-chip-success", label: "Ativo" },
  trial:     { cls: "dh-chip-warning", label: "Em teste" },
  suspended: { cls: "dh-chip-error",   label: "Suspenso" },
  inactive:  { cls: "dh-chip-neutral", label: "Inativo" },
  available: { cls: "dh-chip-success", label: "Disponível" },
  in_development: { cls: "dh-chip-warning", label: "Em desenvolvimento" },
  planned:   { cls: "dh-chip-neutral", label: "Planejado" },
};

export default function StatusBadge({ status, testid }) {
  const info = MAP[status] || { cls: "dh-chip-neutral", label: status };
  return (
    <span className={`dh-chip ${info.cls}`} data-testid={testid}>
      {info.label}
    </span>
  );
}
