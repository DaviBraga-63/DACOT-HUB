// Presentation only; the backend validates and normalizes the number.
export function formatBrazilianPhone(value) {
  let digits = value.replace(/\D/g, "");
  if (digits.length > 11 && digits.startsWith("55")) digits = digits.slice(2);
  digits = digits.slice(0, 11);
  if (digits.length <= 2) return digits ? `(${digits}` : "";
  const ddd = digits.slice(0, 2);
  const subscriber = digits.slice(2);
  const split = subscriber.length > 8 ? 5 : 4;
  return `(${ddd}) ${subscriber.slice(0, split)}${subscriber.length > split ? `-${subscriber.slice(split)}` : ""}`;
}
