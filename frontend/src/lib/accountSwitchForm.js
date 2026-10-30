export function canStartAccountSwitch({ phone, password, available, busy }) {
  const digits = typeof phone === "string" ? phone.replace(/\D/g, "") : "";
  return Boolean(available && !busy && /^(?:55)?[1-9]\d{9,10}$/.test(digits) && password);
}

// Closing a form before a candidate operation exists is local-only. Keeping
// this reset separate makes it explicit that no gateway request is involved.
export function clearedAccountSwitchDraft() {
  return { phone: "", password: "", confirm: false, code: "", state: "", error: "" };
}
