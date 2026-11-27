import React, { act } from "react";
import { createRoot } from "react-dom/client";
import SupportConversation from "./SupportConversation";
import { api } from "@/lib/api";

let mockPoll;
jest.mock("react-router-dom", () => ({
  Link: ({ children, to, ...props }) => <a href={to} {...props}>{children}</a>,
}), { virtual: true });
jest.mock("@/context/SupportNotifications", () => ({
  useSupportNotifications: () => ({ refresh: jest.fn() }),
  useSupportPolling: (callback) => { mockPoll = callback; },
}));
jest.mock("@/lib/api", () => ({
  api: { get: jest.fn(), post: jest.fn() },
  formatApiErrorDetail: () => "Falha no envio",
}));

const thread = {
  ticket: { number: "T-1", status: "awaiting_support", category: "technical", subject: "Teste" },
  messages: [], through: 0,
};
let container;
let root;

async function setup(staff = false) {
  api.get.mockResolvedValue({ data: thread });
  container = document.createElement("div");
  document.body.appendChild(container);
  root = createRoot(container);
  await act(async () => {
    root.render(<SupportConversation staff={staff} ticketId="1" apiPath="/support" basePath="/support" />);
  });
  return container.querySelector("textarea");
}

async function type(input, value) {
  await act(async () => {
    Object.getOwnPropertyDescriptor(HTMLTextAreaElement.prototype, "value").set.call(input, value);
    input.dispatchEvent(new Event("input", { bubbles: true }));
  });
}

async function key(input, options) {
  await act(async () => input.dispatchEvent(new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true, ...options })));
}

beforeEach(() => {
  global.IS_REACT_ACT_ENVIRONMENT = true;
  window.matchMedia = jest.fn().mockReturnValue({ matches: true });
  Object.defineProperty(window, "crypto", { configurable: true, value: { randomUUID: () => "test-request-id" } });
  api.get.mockReset();
  api.post.mockReset();
});
afterEach(async () => {
  if (root) await act(async () => root.unmount());
  container?.remove();
  root = null;
});

test.each([false, true])("Enter submits and clears the composer for staff=%s", async (staff) => {
  api.post.mockResolvedValue({});
  const input = await setup(staff);
  await type(input, "Olá");
  await key(input);
  expect(api.post).toHaveBeenCalledTimes(1);
  expect(api.post.mock.calls[0][1].message).toBe("Olá");
  expect(input.value).toBe("");
});

test("Shift+Enter, IME, and whitespace do not submit", async () => {
  const input = await setup();
  await type(input, "  ");
  await key(input);
  await type(input, "Olá");
  await key(input, { shiftKey: true });
  await key(input, { isComposing: true });
  expect(api.post).not.toHaveBeenCalled();
});

test("a pending request prevents repeated Enter and submit", async () => {
  let finish;
  api.post.mockImplementation(() => new Promise(resolve => { finish = resolve; }));
  const input = await setup();
  await type(input, "Olá");
  await key(input);
  await key(input);
  await act(async () => input.form.dispatchEvent(new Event("submit", { bubbles: true, cancelable: true })));
  expect(api.post).toHaveBeenCalledTimes(1);
  await act(async () => finish({}));
});

test("failed submission preserves newlines for retry", async () => {
  api.post.mockRejectedValue(new Error("offline"));
  const input = await setup();
  await type(input, "Primeira\nSegunda");
  await key(input);
  expect(input.value).toBe("Primeira\nSegunda");
  expect(container.textContent).toContain("Falha no envio");
});

test("mobile Enter leaves newline handling to the virtual keyboard", async () => {
  window.matchMedia.mockReturnValue({ matches: false });
  const input = await setup();
  await type(input, "Linha");
  const event = new KeyboardEvent("keydown", { key: "Enter", bubbles: true, cancelable: true });
  await act(async () => input.dispatchEvent(event));
  expect(event.defaultPrevented).toBe(false);
  expect(api.post).not.toHaveBeenCalled();
});

test("composer height shrinks after a successful send", async () => {
  api.post.mockResolvedValue({});
  const input = await setup();
  Object.defineProperty(input, "scrollHeight", { configurable: true, get: () => input.value ? 200 : 48 });
  await type(input, "Mensagem longa");
  expect(input.style.height).toBe("144px");
  await key(input);
  expect(input.style.height).toBe("48px");
});

test("new messages do not scroll away from older messages", async () => {
  await setup();
  const scroller = container.querySelector('[aria-label="Conversa"] > div');
  Object.defineProperties(scroller, {
    scrollHeight: { configurable: true, value: 1000 },
    clientHeight: { configurable: true, value: 300 },
  });
  scroller.scrollTop = 100;
  await act(async () => scroller.dispatchEvent(new Event("scroll", { bubbles: true })));
  api.get.mockResolvedValue({ data: { ...thread, messages: [{ id: "m1", seq: 1, kind: "message", author_type: "staff", text: "Nova" }] } });
  await act(async () => mockPoll());
  expect(scroller.scrollTop).toBe(100);
});
