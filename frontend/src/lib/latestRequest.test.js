import { createLatestRequestGate } from "./latestRequest";

test("keeps a newer status request authoritative when an older response arrives last", () => {
  const gate = createLatestRequestGate();
  const initialLoad = gate.begin();
  const manualRefresh = gate.begin();

  expect(gate.isCurrent(manualRefresh)).toBe(true);
  expect(gate.isCurrent(initialLoad)).toBe(false);
});
