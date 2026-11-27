import { formatSupportUpdatedAt } from "./support";

const localDate = (year, month, day, hour = 0, minute = 0) => new Date(year, month - 1, day, hour, minute);

test.each([
  [localDate(2026, 11, 26, 23, 27), localDate(2026, 11, 26, 23, 58), "Atualizado às 23:27"],
  [localDate(2026, 11, 26, 0, 5), localDate(2026, 11, 26, 8), "Atualizado às 00:05"],
  [localDate(2026, 11, 25, 23, 27), localDate(2026, 11, 26, 0, 5), "Atualizado ontem às 23:27"],
  [localDate(2026, 11, 30, 7, 3), localDate(2026, 12, 1, 23, 59), "Atualizado ontem às 07:03"],
  [localDate(2026, 12, 31, 23, 27), localDate(2027, 1, 1, 0, 5), "Atualizado ontem às 23:27"],
  [localDate(2026, 11, 24, 23, 27), localDate(2026, 11, 26, 0, 5), "Atualizado em 24/11/2026"],
  [localDate(2026, 2, 3, 9), localDate(2026, 11, 26, 10), "Atualizado em 03/02/2026"],
])("formats %p relative to the local calendar at %p", (date, now, expected) => {
  expect(formatSupportUpdatedAt(date.toISOString(), now)).toBe(expected);
});

test.each([null, undefined, "", "data inválida"])("displays a neutral fallback for %p", (value) => {
  expect(formatSupportUpdatedAt(value)).toBe("—");
});
