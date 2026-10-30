// Prevent a slower, older read response from replacing a newer UI state.
// This has no transport side effects and deliberately keeps the newest
// server response as the source of truth.
export function createLatestRequestGate() {
  let latest = 0;

  return {
    begin() {
      latest += 1;
      return latest;
    },
    isCurrent(requestId) {
      return requestId === latest;
    },
  };
}
