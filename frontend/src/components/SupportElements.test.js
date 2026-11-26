import { renderToStaticMarkup } from "react-dom/server";
import { TicketStatus, TicketUnread } from "./SupportElements";

test.each([
  ["awaiting_support", "Aguardando suporte", "dh-chip-warning"],
  ["awaiting_customer", "Aguardando cliente", "dh-support-info"],
  ["resolved", "Resolvido", "dh-chip-success"],
])("renders the support status %s with a label and a semantic color", (status, label, tone) => {
  const markup = renderToStaticMarkup(<TicketStatus status={status} testId="support-ticket-status" />);
  expect(markup).toContain(label);
  expect(markup).toContain(tone);
  expect(markup).toContain('data-testid="support-ticket-status"');
});

test("the unread marker labels new activity without showing a read receipt", () => {
  const markup = renderToStaticMarkup(<TicketUnread />);
  expect(markup).toContain('aria-hidden="true"');
  expect(markup).toContain("Novidades");
  expect(markup).not.toMatch(/visualizad[oa]|hora da leitura|digitando|online/i);
});
