import { renderToStaticMarkup } from "react-dom/server";
import { TicketStatus, TicketUnread } from "./SupportElements";

test.each([
  ["awaiting_support", "Aguardando suporte", "Aguardando suporte", "dh-chip-warning"],
  ["awaiting_customer", "Aguardando cliente", "Aguardando sua resposta", "dh-support-info"],
  ["resolved", "Resolvido", "Resolvido", "dh-chip-success"],
])("renders %s for each audience with the same semantic color", (status, staffLabel, ownerLabel, tone) => {
  for (const [staff, label] of [[true, staffLabel], [false, ownerLabel]]) {
    const markup = renderToStaticMarkup(<TicketStatus status={status} staff={staff} testId="support-ticket-status" />);
    expect(markup).toContain(`>${label}</span>`);
    expect(markup).toContain(tone);
    expect(markup).toContain('data-testid="support-ticket-status"');
  }
});

test("the unread marker labels new activity without showing a read receipt", () => {
  const markup = renderToStaticMarkup(<TicketUnread />);
  expect(markup).toContain('aria-hidden="true"');
  expect(markup).toContain("Novidades");
  expect(markup).not.toMatch(/visualizad[oa]|hora da leitura|digitando|online/i);
});
