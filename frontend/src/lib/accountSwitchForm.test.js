import { canStartAccountSwitch, clearedAccountSwitchDraft } from "./accountSwitchForm";

test("closing an unstarted account switch clears every sensitive draft field locally", () => {
  expect(clearedAccountSwitchDraft()).toEqual({
    phone: "", password: "", confirm: false, code: "", state: "", error: "",
  });
});

test("starting a candidate requires a valid number and password, not an introductory acknowledgement", () => {
  expect(canStartAccountSwitch({
    phone: "(11) 91234-5678", password: "confirmed-password", available: true, busy: false,
  })).toBe(true);
  expect(canStartAccountSwitch({ phone: "11912345678", password: "", available: true, busy: false })).toBe(false);
  expect(canStartAccountSwitch({ phone: "111", password: "confirmed-password", available: true, busy: false })).toBe(false);
});
