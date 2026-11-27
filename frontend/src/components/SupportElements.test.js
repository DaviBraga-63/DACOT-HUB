import { renderToStaticMarkup } from "react-dom/server";
import { ConversationMessage, TicketStatus, TicketUnread } from "./SupportElements";

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

test.each([
  ["admin sees own reply", true, "staff", true, true, "Você"],
  ["admin sees another admin's reply", true, "staff", false, true, "Outro autor"],
  ["admin sees restaurant reply", true, "restaurant", false, false, "Outro autor"],
  ["owner sees own reply", false, "restaurant", true, true, "Você"],
  ["owner sees another restaurant reply", false, "restaurant", false, true, "Outro autor"],
  ["owner sees staff reply", false, "staff", false, false, "Equipe DACOT"],
])("%s on the expected side, with its color and author", (_, staff, authorType, isMine, outgoing, author) => {
  const message = { kind: "message", author_type: authorType, author_label: "Outro autor", is_mine: isMine, text: "Mensagem de teste" };
  const markup = renderToStaticMarkup(<ConversationMessage message={message} staff={staff} timeLabel="10:30" />);
  expect(markup).toContain(outgoing ? "justify-end" : "justify-start");
  expect(markup).not.toContain(outgoing ? "justify-start" : "justify-end");
  expect(markup).toContain(outgoing ? "rounded-br-sm bg-[var(--dh-accent-soft)]" : "rounded-bl-sm bg-[var(--dh-surface-secondary)]");
  expect(markup).toContain(`>${author}</span>`);
  expect(markup).toContain(">10:30</time>");
});
