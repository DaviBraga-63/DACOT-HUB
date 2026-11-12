/**
 * Temporary frontend rollout rule. Inventory is additionally customer-visible
 * only after the Hub's server-side rollout gate and tenant activation permit it.
 */
export const isReleasedModule = (module) => ["orders", "inventory"].includes(module?.key);
